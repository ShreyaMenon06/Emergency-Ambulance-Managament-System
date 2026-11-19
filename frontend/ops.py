"""The workflow of the ambulance service: emergency call -> dispatch -> patient -> bill.
Every function takes the open Oracle connection first. SQL is written for Oracle 11g."""
import datetime
import decimal
import math

import settings

ACTIVE = ("En Route", "At Scene", "To Hospital", "At Hospital")
ACTIVE_SQL = "('En Route','At Scene','To Hospital','At Hospital')"
MAX_ROWS = 300


class RuleError(Exception):
    """A rule of the service was broken (shown to the user as a message)."""


# ------------------------------------------------------------------ small helpers
def rows(conn, sql, **params):
    cur = conn.cursor()
    cur.execute(sql, params)
    names = [d[0].lower() for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def one(conn, sql, **params):
    r = rows(conn, sql, **params)
    return r[0] if r else None


def scalar(conn, sql, **params):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchone()[0]


def run(conn, sql, **params):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.rowcount


def nextval(conn, seq):
    return int(scalar(conn, "SELECT %s.NEXTVAL FROM dual" % seq))


def text(f, key):
    return (f.get(key) or "").strip()


def need(f, key, label):
    v = text(f, key)
    if not v:
        raise RuleError("%s is required." % label)
    return v


def split_list(value, maxlen, label):
    """'English, Hindi, english' -> ['English', 'Hindi']: one entry per value, no blanks, no repeats (the child tables hold one value per row)."""
    out, seen = [], set()
    for x in (value or "").split(","):
        x = x.strip()
        if not x or x.lower() in seen:
            continue
        if len(x) > maxlen:
            raise RuleError("%s can have at most %d characters." % (label, maxlen))
        seen.add(x.lower())
        out.append(x)
    return out


def whole(f, key, label, required=True):
    v = text(f, key)
    if not v:
        if required:
            raise RuleError("%s is required." % label)
        return None
    try:
        return int(v)
    except ValueError:
        raise RuleError("%s must be a whole number." % label)


def number(f, key, label, required=True):
    v = text(f, key)
    if not v:
        if required:
            raise RuleError("%s is required." % label)
        return None
    try:
        n = decimal.Decimal(v)
    except decimal.InvalidOperation:
        raise RuleError("%s must be a number." % label)
    if not n.is_finite() or abs(n) >= 10 ** 12:
        raise RuleError("%s must be a normal number." % label)
    return n


def date_of(f, key, label, required=True):
    """A date typed as 2026-11-18 (the browser's date box)."""
    v = text(f, key)
    if not v:
        if required:
            raise RuleError("%s is required." % label)
        return None
    try:
        return datetime.datetime.strptime(v[:10], "%Y-%m-%d")
    except ValueError:
        raise RuleError("%s is not a valid date." % label)


# ------------------------------------------------------------------ dashboard
def kpis(conn):
    return one(conn, """
        SELECT
          (SELECT COUNT(*) FROM emergency_call c WHERE NVL(c.is_false_alarm,'N') <> 'Y'
              AND NOT EXISTS (SELECT 1 FROM dispatch d WHERE d.call_id = c.call_id AND d.status <> 'Cancelled')) AS waiting_calls,
          (SELECT COUNT(*) FROM dispatch WHERE status IN %(a)s) AS active_dispatches,
          (SELECT COUNT(*) FROM ambulance a WHERE a.status = 'Available'
              AND NOT EXISTS (SELECT 1 FROM dispatch d WHERE d.ambulance_id = a.ambulance_id AND d.status IN %(a)s)) AS free_ambulances,
          (SELECT COUNT(*) FROM ambulance) AS total_ambulances,
          (SELECT COUNT(*) FROM billing WHERE NVL(payment_status,'Unpaid') <> 'Paid') AS unpaid_bills,
          (SELECT NVL(SUM(total_amount - amount_paid),0) FROM billing WHERE NVL(payment_status,'Unpaid') <> 'Paid') AS unpaid_amount,
          (SELECT ROUND(AVG(response_time),1) FROM dispatch WHERE response_time IS NOT NULL) AS avg_response,
          (SELECT COUNT(*) FROM emergency_call) AS total_calls
        FROM dual""" % {"a": ACTIVE_SQL})


def waiting_count(conn):
    return int(scalar(conn, """SELECT COUNT(*) FROM emergency_call c WHERE NVL(c.is_false_alarm,'N') <> 'Y'
        AND NOT EXISTS (SELECT 1 FROM dispatch d WHERE d.call_id = c.call_id AND d.status <> 'Cancelled')"""))


def insurance_alerts(conn):
    return rows(conn, """
        SELECT i.policy_no, a.vehicle_no, i.insurer, i.expiry_date, i.expiry_date - TRUNC(SYSDATE) AS days_left
        FROM ambulance_insurance i JOIN ambulance a ON a.ambulance_id = i.ambulance_id
        WHERE i.expiry_date <= TRUNC(SYSDATE) + :d ORDER BY i.expiry_date""", d=settings.INSURANCE_WARN_DAYS)


def maintenance_alerts(conn):
    return rows(conn, """
        SELECT a.vehicle_no, m.maintenance_type, m.next_due_date, m.next_due_date - TRUNC(SYSDATE) AS days_left
        FROM ambulance_maintenance_log m JOIN ambulance a ON a.ambulance_id = m.ambulance_id
        WHERE m.next_due_date <= TRUNC(SYSDATE) + :d
          AND m.maintenance_date = (SELECT MAX(m2.maintenance_date) FROM ambulance_maintenance_log m2
                                    WHERE m2.ambulance_id = m.ambulance_id)
        ORDER BY m.next_due_date""", d=settings.MAINTENANCE_WARN_DAYS)


def license_alerts(conn):
    return rows(conn, """
        SELECT TRIM(first_name || ' ' || last_name) AS name, license_no, license_expiry,
               license_expiry - TRUNC(SYSDATE) AS days_left
        FROM driver WHERE is_active = 'Y' AND license_expiry <= TRUNC(SYSDATE) + :d ORDER BY license_expiry""", d=settings.LICENSE_WARN_DAYS)


def staff_counts(conn):
    return one(conn, """
        SELECT (SELECT COUNT(*) FROM call_center_agent WHERE is_active = 'Y') AS agents,
               (SELECT COUNT(*) FROM driver WHERE is_active = 'Y') AS drivers,
               (SELECT COUNT(*) FROM paramedic WHERE is_active = 'Y') AS paramedics,
               (SELECT COUNT(*) FROM hr) AS hr_records
        FROM dual""")


# ------------------------------------------------------------------ calls
CALL_SQL = """
SELECT c.call_id, c.call_time, c.pick_location, c.call_type, c.urgency_level, c.is_false_alarm,
       c.call_duration, c.description, c.agent_id, c.customer_id, c.pick_lat, c.pick_lon,
       TRIM(cu.first_name || ' ' || cu.last_name) AS caller,
       CASE WHEN NVL(c.is_false_alarm,'N') = 'Y' THEN 'False alarm'
            WHEN EXISTS (SELECT 1 FROM dispatch d WHERE d.call_id = c.call_id AND d.status IN %s) THEN 'In progress'
            WHEN EXISTS (SELECT 1 FROM dispatch d WHERE d.call_id = c.call_id AND d.status = 'Completed') THEN 'Completed'
            ELSE 'Waiting' END AS call_status
FROM emergency_call c LEFT JOIN customer cu ON cu.customer_id = c.customer_id
""" % ACTIVE_SQL


def list_calls(conn, status="", q="", limit=MAX_ROWS):
    where, params = [], {}
    if status:
        where.append("call_status = :s")
        params["s"] = status
    if q:
        where.append("(UPPER(caller) LIKE :q OR UPPER(pick_location) LIKE :q OR UPPER(call_type) LIKE :q "
                     "OR UPPER(description) LIKE :q OR TO_CHAR(call_id) = :qq)")
        params["q"] = "%" + q.upper() + "%"
        params["qq"] = q
    sql = ("SELECT * FROM (SELECT * FROM (%s) %s ORDER BY DECODE(call_status,'Waiting',0,'In progress',1,2), "
           "DECODE(urgency_level,'Critical',1,'High',2,'Medium',3,4), call_time DESC) WHERE ROWNUM <= %d"
           % (CALL_SQL, ("WHERE " + " AND ".join(where)) if where else "", int(limit)))
    return rows(conn, sql, **params)


def get_call(conn, call_id):
    return one(conn, CALL_SQL + " WHERE c.call_id = :i", i=call_id)


def at_work(alias):
    """SQL: the employee (alias.hr_id) is not on approved leave and not marked On Leave / Absent today."""
    return ("""NOT EXISTS (SELECT 1 FROM hr_attendance t WHERE t.hr_id = %(a)s.hr_id AND t.att_date = TRUNC(SYSDATE)
                          AND t.status IN ('On Leave', 'Absent'))
               AND NOT EXISTS (SELECT 1 FROM hr_leave l WHERE l.hr_id = %(a)s.hr_id AND l.status = 'Approved'
                          AND TRUNC(SYSDATE) BETWEEN l.start_date AND l.end_date)""" % {"a": alias})


def agents(conn):
    return rows(conn, "SELECT agent_id, TRIM(first_name || ' ' || last_name) AS name FROM call_center_agent "
                      "WHERE is_active = 'Y' AND " + at_work("call_center_agent") + " ORDER BY agent_id")


def customers(conn):
    return rows(conn, """SELECT customer_id, TRIM(first_name || ' ' || last_name) AS name,
                                (SELECT LISTAGG(p.phone_no, ', ') WITHIN GROUP (ORDER BY p.phone_no)
                                 FROM customer_phone p WHERE p.customer_id = c.customer_id) AS phone
                         FROM customer c ORDER BY customer_id""")


def find_area(chosen, location):
    """The area picked on the call; if none was picked, an area whose name appears in the pick-up address."""
    if chosen in settings.AREAS:
        return chosen
    low = (location or "").lower()
    for name in settings.AREAS:
        if name.lower() in low:
            return name
    return None


def distance_km(lat1, lon1, lat2, lon2):
    """Straight-line distance between two points on the map (haversine), in km."""
    la1, lo1, la2, lo2 = (math.radians(float(x)) for x in (lat1, lon1, lat2, lon2))
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest_hospitals(conn, lat, lon):
    """All hospitals, those with a free bed first and the closest to (lat, lon) first. Each row gets distance_km (None if unknown)
    and nearest = True on the closest hospital that has a free bed."""
    hs = hospital_directory(conn)
    for h in hs:
        known = lat is not None and lon is not None and h["latitude"] is not None and h["longitude"] is not None
        h["distance_km"] = round(distance_km(lat, lon, h["latitude"], h["longitude"]), 1) if known else None
        h["nearest"] = False
    hs.sort(key=lambda h: (0 if h["beds_available"] else 1, h["distance_km"] is None, h["distance_km"] or 0))
    if hs and hs[0]["beds_available"] and hs[0]["distance_km"] is not None:
        hs[0]["nearest"] = True
    return hs


def create_call(conn, f):
    agent_id = whole(f, "agent_id", "Agent")
    # No "new or existing caller" question in an emergency: the phone number finds a caller we already know,
    # otherwise a caller record is made from whatever was given. Nothing given = the call is saved without a caller.
    first, last, phone = text(f, "first_name"), text(f, "last_name"), text(f, "phone")
    addr = {k: text(f, k) or None for k in ("street", "city", "state", "pincode")}
    if addr["pincode"] and not (addr["pincode"].isdigit() and len(addr["pincode"]) == 6):
        raise RuleError("The pincode must be 6 digits.")
    cust_id = None
    if phone:
        known = one(conn, "SELECT customer_id FROM customer_phone WHERE phone_no = :p AND ROWNUM = 1", p=phone)
        if known:
            cust_id = known["customer_id"]
            # a known caller: fill only the address parts that were still empty, never overwrite
            for k, v in addr.items():
                if v:
                    run(conn, "UPDATE customer SET %s = :v WHERE customer_id = :i AND %s IS NULL" % (k, k), v=v, i=cust_id)
    if cust_id is None and (first or last or phone or any(addr.values())):
        cust_id = nextval(conn, "seq_customer")
        cols, vals, params = ["customer_id", "first_name", "last_name", "agent_id"], [":i", ":f", ":l", ":a"], \
            {"i": cust_id, "f": first or "Unknown", "l": last or "Caller", "a": agent_id}
        for k, v in addr.items():
            if v:
                cols.append(k); vals.append(":" + k); params[k] = v
        run(conn, "INSERT INTO customer (%s) VALUES (%s)" % (", ".join(cols), ", ".join(vals)), **params)
        if phone:
            run(conn, "INSERT INTO customer_phone (customer_id, phone_no) VALUES (:i, :p)", i=cust_id, p=phone)
    call_id = nextval(conn, "seq_emergency_call")
    location = need(f, "pick_location", "Pick-up location")
    area = find_area(text(f, "area"), location)
    lat, lon = settings.AREAS[area] if area else (None, None)
    run(conn, """INSERT INTO emergency_call (call_id, call_time, pick_location, call_type, is_false_alarm, call_duration,
                                              urgency_level, description, pick_lat, pick_lon, agent_id, customer_id)
                 VALUES (:i, SYSDATE, :loc, :t, :fa, :dur, :u, :d, :lat, :lon, :a, :c)""",
        i=call_id, loc=location, lat=lat, lon=lon, t=need(f, "call_type", "Type of emergency"),
        fa="Y" if f.get("is_false_alarm") else "N", dur=whole(f, "call_duration", "Call duration", False),
        u=need(f, "urgency_level", "Urgency"), d=text(f, "description") or None, a=agent_id, c=cust_id)
    conn.commit()
    return call_id


# ------------------------------------------------------------------ dispatch
DISPATCH_SQL = """
SELECT d.dispatch_id, d.status, d.dispatch_time, d.arrival_time, d.hospital_arrival_time, d.response_time,
       d.call_id, d.agent_id, d.ambulance_id, d.driver_id, d.paramedic_id, d.hospital_id,
       c.pick_location, c.call_type, c.urgency_level, c.customer_id, c.description, c.pick_lat, c.pick_lon,
       h.latitude AS hosp_lat, h.longitude AS hosp_lon,
       TRIM(cu.first_name || ' ' || cu.last_name) AS caller,
       h.hospital_name, h.branch_name,
       a.vehicle_no, a.type_of_ambulance,
       TRIM(dr.first_name || ' ' || dr.last_name) AS driver,
       TRIM(p.first_name || ' ' || p.last_name) AS paramedic,
       (SELECT COUNT(*) FROM patient pt WHERE pt.dispatch_id = d.dispatch_id) AS patients,
       (SELECT MAX(b.billing_id) FROM billing b WHERE b.dispatch_id = d.dispatch_id) AS billing_id,
       dr.phone_no AS driver_phone, p.phone_no AS paramedic_phone,
       bl.total_amount AS bill_total, bl.amount_paid AS bill_paid, bl.payment_status AS bill_status, bl.payment_mode AS bill_mode,
       ROUND((SYSDATE - CAST(NVL((SELECT MAX(l.changed_at) FROM dispatch_status_log l WHERE l.dispatch_id = d.dispatch_id),
                                 d.dispatch_time) AS DATE)) * 1440) AS idle_min
FROM dispatch d
JOIN emergency_call c ON c.call_id = d.call_id
LEFT JOIN customer cu ON cu.customer_id = c.customer_id
JOIN ambulance a ON a.ambulance_id = d.ambulance_id
JOIN driver dr ON dr.driver_id = d.driver_id
LEFT JOIN paramedic p ON p.paramedic_id = d.paramedic_id
LEFT JOIN hospital h ON h.hospital_id = d.hospital_id
LEFT JOIN billing bl ON bl.dispatch_id = d.dispatch_id
"""


def list_dispatches(conn, active_only=False, call_id=None, driver_id=None, limit=MAX_ROWS):
    where, params = [], {}
    if driver_id is not None:
        where.append("d.driver_id = :dr")
        params["dr"] = driver_id
    if active_only:
        where.append("d.status IN %s" % ACTIVE_SQL)
    if call_id is not None:
        where.append("d.call_id = :c")
        params["c"] = call_id
    sql = ("SELECT * FROM (%s %s ORDER BY d.dispatch_time DESC) WHERE ROWNUM <= %d"
           % (DISPATCH_SQL, ("WHERE " + " AND ".join(where)) if where else "", int(limit)))
    return rows(conn, sql, **params)


def get_dispatch(conn, dispatch_id):
    return one(conn, DISPATCH_SQL + " WHERE d.dispatch_id = :i", i=dispatch_id)


def free_ambulances(conn):
    return rows(conn, """SELECT a.ambulance_id, a.model, a.vehicle_no, a.type_of_ambulance, a.current_location
        FROM ambulance a WHERE a.status = 'Available'
          AND NOT EXISTS (SELECT 1 FROM dispatch d WHERE d.ambulance_id = a.ambulance_id AND d.status IN %s)
        ORDER BY a.ambulance_id""" % ACTIVE_SQL)


def ambulances_by_distance(conn, lat, lon):
    """The free ambulances, the one closest to (lat, lon) first. Where an ambulance is: its latest location ping if it has one,
    otherwise the area named in its current location (e.g. 'Whitefield'). distance_km is None when that is not known."""
    ambs = free_ambulances(conn)
    pings = {int(r["ambulance_id"]): r for r in rows(conn, """
        SELECT l.ambulance_id, l.latitude, l.longitude FROM location_log l
        WHERE l.log_time = (SELECT MAX(l2.log_time) FROM location_log l2 WHERE l2.ambulance_id = l.ambulance_id)""")}
    for a in ambs:
        p = pings.get(int(a["ambulance_id"]))
        if p and p["latitude"] is not None and p["longitude"] is not None:
            a_lat, a_lon = float(p["latitude"]), float(p["longitude"])
        else:
            area = find_area(None, a["current_location"])
            a_lat, a_lon = settings.AREAS[area] if area else (None, None)
        a["distance_km"] = round(distance_km(lat, lon, a_lat, a_lon), 1) if None not in (lat, lon, a_lat, a_lon) else None
        a["nearest"] = False
    ambs.sort(key=lambda a: (a["distance_km"] is None, a["distance_km"] or 0))
    if ambs and ambs[0]["distance_km"] is not None:
        ambs[0]["nearest"] = True
    return ambs


def free_drivers(conn):
    return rows(conn, """SELECT d.driver_id, TRIM(d.first_name || ' ' || d.last_name) AS name, d.license_expiry, d.ambulance_id
        FROM driver d WHERE d.is_active = 'Y' AND NOT EXISTS (SELECT 1 FROM dispatch x WHERE x.driver_id = d.driver_id AND x.status IN %s)
          AND (d.license_expiry IS NULL OR d.license_expiry >= TRUNC(SYSDATE))
          AND %s
        ORDER BY d.driver_id""" % (ACTIVE_SQL, at_work("d")))


def free_paramedics(conn):
    return rows(conn, """SELECT p.paramedic_id, TRIM(p.first_name || ' ' || p.last_name) AS name,
                                p.certification_level, p.ambulance_id
        FROM paramedic p WHERE p.is_active = 'Y' AND NOT EXISTS (SELECT 1 FROM dispatch x WHERE x.paramedic_id = p.paramedic_id AND x.status IN %s)
          AND %s
        ORDER BY p.paramedic_id""" % (ACTIVE_SQL, at_work("p")))


def create_dispatch(conn, call_id, f):
    call = get_call(conn, call_id)
    if call is None:
        raise RuleError("That call does not exist.")
    if call["is_false_alarm"] == "Y":
        raise RuleError("This call is marked as a false alarm, so no ambulance can be sent.")
    if call["call_status"] == "In progress":
        raise RuleError("An ambulance is already on this call. Wait until that trip is finished or cancelled.")
    if call["call_status"] == "Completed":
        raise RuleError("This call has already been completed. Take a new call if there is a new emergency.")
    amb, drv = whole(f, "ambulance_id", "Ambulance"), whole(f, "driver_id", "Driver")
    par = whole(f, "paramedic_id", "Paramedic", False)
    agent = whole(f, "agent_id", "Agent")
    hosp = whole(f, "hospital_id", "Hospital")
    h = one(conn, "SELECT hospital_name, beds_available FROM hospital WHERE hospital_id = :h", h=hosp)
    if h is None:
        raise RuleError("That hospital does not exist.")
    if not h["beds_available"]:
        raise RuleError("%s has no free bed. Choose another hospital." % h["hospital_name"])
    if amb not in [a["ambulance_id"] for a in free_ambulances(conn)]:
        raise RuleError("That ambulance is no longer available. Choose another one.")
    if drv not in [d["driver_id"] for d in free_drivers(conn)]:
        raise RuleError("That driver cannot be sent (busy, on leave or absent today, or licence expired). Choose another one.")
    if par is not None and par not in [p["paramedic_id"] for p in free_paramedics(conn)]:
        raise RuleError("That paramedic cannot be sent (on another dispatch, or on leave or absent today). Choose another one.")
    dispatch_id = nextval(conn, "seq_dispatch")
    run(conn, """INSERT INTO dispatch (dispatch_id, status, dispatch_time, call_id, agent_id, ambulance_id, driver_id, paramedic_id, hospital_id)
                 VALUES (:i, 'En Route', SYSDATE, :c, :a, :m, :d, :p, :h)""",
        i=dispatch_id, c=call_id, a=agent, m=amb, d=drv, p=par, h=hosp)
    conn.commit()          # the database trigger sets the ambulance to On Duty and records the first history line
    return dispatch_id


# action -> (statuses it can start from, SQL set clause, message).
# The ambulance status and the status history are kept by a database trigger.
STEPS = {
    "arrive":     (("En Route",),                "status = 'At Scene', arrival_time = SYSDATE",
                   "Ambulance reached the scene."),
    "tohospital": (("At Scene",),                "status = 'To Hospital', hospital_id = :h",
                   "Patient is on the way to the hospital."),
    "hospital":   (("To Hospital",),             "status = 'At Hospital', hospital_arrival_time = SYSDATE",
                   "Ambulance reached the hospital."),
    "complete":   (("At Scene", "At Hospital"),  "status = 'Completed'",
                   "Dispatch completed. The ambulance is free again."),
    "cancel":     (("En Route", "At Scene"),     "status = 'Cancelled'",
                   "Dispatch cancelled. The ambulance is free again."),
}


def step_dispatch(conn, dispatch_id, action, f=None):
    if action not in STEPS:
        raise RuleError("Unknown action.")
    allowed, sets, message = STEPS[action]
    d = get_dispatch(conn, dispatch_id)
    if d is None:
        raise RuleError("That dispatch does not exist.")
    if d["status"] not in allowed:
        raise RuleError("This dispatch is '%s', so that step is not possible." % d["status"])
    params = {"i": dispatch_id, "s": d["status"]}
    if action == "cancel" or (action == "complete" and d["status"] == "At Scene"):
        sets += ", hospital_id = NULL"       # the patient never went to the hospital chosen at dispatch
    if action == "tohospital":
        hosp = whole(f or {}, "hospital_id", "Hospital", False) or d["hospital_id"]     # the one chosen at dispatch unless changed
        if hosp is None:
            raise RuleError("Choose the hospital.")
        h = one(conn, "SELECT hospital_name, beds_available FROM hospital WHERE hospital_id = :h", h=hosp)
        if h is None:
            raise RuleError("That hospital does not exist.")
        if not h["beds_available"]:
            raise RuleError("%s has no free bed. Choose another hospital." % h["hospital_name"])
        params["h"] = hosp
    if run(conn, "UPDATE dispatch SET %s WHERE dispatch_id = :i AND status = :s" % sets, **params) == 0:
        raise RuleError("The dispatch was changed by someone else. Reload and try again.")
    # the ambulance's current location follows the trip, so the "free ambulances" list shows where each one really is
    where = None
    if action == "arrive":
        where = d["pick_location"]
    elif action == "hospital":
        h = one(conn, "SELECT hospital_name, branch_name FROM hospital WHERE hospital_id = (SELECT hospital_id FROM dispatch WHERE dispatch_id = :i)", i=dispatch_id)
        where = (h["hospital_name"] + (", " + h["branch_name"] if h["branch_name"] else "")) if h else None
    if where:
        run(conn, "UPDATE ambulance SET current_location = :w WHERE ambulance_id = :a", w=where[:200], a=d["ambulance_id"])
    conn.commit()
    return message


# ------------------------------------------------------------------ driver / paramedic: see own trips, record money collected
def crew_ids(conn, hr_id):
    d = one(conn, "SELECT driver_id FROM driver WHERE hr_id = :h", h=hr_id)
    p = one(conn, "SELECT paramedic_id FROM paramedic WHERE hr_id = :h", h=hr_id)
    return (d["driver_id"] if d else None), (p["paramedic_id"] if p else None)


def my_trips(conn, hr_id, limit=15):
    """The trips this driver or paramedic is (or was) assigned to, newest first. Each gets suggested_km for the bill form."""
    dr, pm = crew_ids(conn, hr_id)
    trips = rows(conn, "SELECT * FROM (" + DISPATCH_SQL + """ WHERE (d.driver_id = :dr OR d.paramedic_id = :pm)
                          ORDER BY d.dispatch_time DESC) WHERE ROWNUM <= %d""" % int(limit), dr=dr, pm=pm)
    for t in trips:
        t["suggested_km"] = suggested_km(t)
    return trips


def own_trip(conn, hr_id, dispatch_id):
    dr, pm = crew_ids(conn, hr_id)
    d = get_dispatch(conn, dispatch_id)
    if d is None or not ((dr and d["driver_id"] == dr) or (pm and d["paramedic_id"] == pm)):
        raise RuleError("That is not your trip.")
    return d


def crew_bill(conn, hr_id, dispatch_id, f):
    """The driver / paramedic makes the bill at the end of their own trip and fills in what was received."""
    own_trip(conn, hr_id, dispatch_id)
    create_bill(conn, dispatch_id, f, billed_by=hr_id)
    return "Bill made. The agent can see its status."


def crew_collect(conn, hr_id, dispatch_id, f):
    """The crew record money they collected on one of their own trips; the agent sees it on the bill at once."""
    d = own_trip(conn, hr_id, dispatch_id)
    if not d["billing_id"]:
        raise RuleError("Make the bill for this trip first.")
    record_payment(conn, d["billing_id"], f)
    return "Payment recorded. The agent can see it."


def timeline(conn, dispatch_id):
    return rows(conn, """SELECT status, changed_at, changed_by FROM dispatch_status_log
                         WHERE dispatch_id = :d ORDER BY changed_at, log_id""", d=dispatch_id)


def caller_phone(conn, customer_id):
    try:
        r = one(conn, """SELECT LISTAGG(p.phone_no, ', ') WITHIN GROUP (ORDER BY p.phone_no) AS phone
                         FROM customer_phone p WHERE p.customer_id = :i""", i=customer_id)
        return r["phone"] if r else None
    except Exception:
        return None


# ------------------------------------------------------------------ patients and vitals
PATIENT_SQL = """
SELECT p.patient_id, TRIM(p.first_name || ' ' || p.last_name) AS name, p.dob,
       TRUNC(MONTHS_BETWEEN(SYSDATE, p.dob) / 12) AS age, p.blood_group, p.gender,
       (SELECT LISTAGG(al.allergy, ', ') WITHIN GROUP (ORDER BY al.allergy) FROM patient_allergy al WHERE al.patient_id = p.patient_id) AS allergies,
       p.chief_complaint, p.dispatch_id, p.hospital_id, h.hospital_name, h.branch_name
FROM patient p JOIN hospital h ON h.hospital_id = p.hospital_id
"""


def list_patients(conn, q="", dispatch_id=None, limit=MAX_ROWS):
    where, params = [], {}
    if dispatch_id is not None:
        where.append("p.dispatch_id = :d")
        params["d"] = dispatch_id
    if q:
        where.append("(UPPER(p.first_name || ' ' || p.last_name) LIKE :q OR UPPER(h.hospital_name) LIKE :q)")
        params["q"] = "%" + q.upper() + "%"
    sql = ("SELECT * FROM (%s %s ORDER BY p.patient_id DESC) WHERE ROWNUM <= %d"
           % (PATIENT_SQL, ("WHERE " + " AND ".join(where)) if where else "", int(limit)))
    return rows(conn, sql, **params)


def get_patient(conn, patient_id):
    return one(conn, PATIENT_SQL + " WHERE p.patient_id = :i", i=patient_id)


def hospitals(conn):
    return rows(conn, "SELECT hospital_id, hospital_name, branch_name, city, beds_available FROM hospital ORDER BY hospital_name, branch_name")


def hospital_directory(conn):
    return rows(conn, """SELECT h.hospital_id, h.hospital_name, h.branch_name, h.street, h.city, h.beds_available, h.beds_updated_on, h.latitude, h.longitude,
                                (SELECT LISTAGG(hp.phone_no, ', ') WITHIN GROUP (ORDER BY hp.phone_no) FROM hospital_phone hp WHERE hp.hospital_id = h.hospital_id) AS phones
                         FROM hospital h ORDER BY h.hospital_name, h.branch_name""")


def update_beds(conn, hospital_id, f):
    beds = whole(f, "beds_available", "Free beds")
    if beds < 0:
        raise RuleError("Free beds cannot be negative.")
    if run(conn, "UPDATE hospital SET beds_available = :b WHERE hospital_id = :h", b=beds, h=hospital_id) == 0:
        raise RuleError("That hospital does not exist.")
    conn.commit()


def create_patient(conn, dispatch_id, f):
    d = get_dispatch(conn, dispatch_id)
    if d is None:
        raise RuleError("That dispatch does not exist.")
    if not d["hospital_id"] or d["status"] not in ("To Hospital", "At Hospital", "Completed"):
        raise RuleError("A patient can be added once the ambulance is heading to the hospital (step 'Heading to hospital').")
    if not scalar(conn, "SELECT beds_available FROM hospital WHERE hospital_id = :h", h=d["hospital_id"]):
        raise RuleError("%s has no free bed left. Update its beds under Hospitals, or choose another hospital." % (d["hospital_name"] or "The hospital"))
    pid = nextval(conn, "seq_patient")
    cols = ["patient_id", "first_name", "dispatch_id", "hospital_id"]
    vals = [":i", ":f", ":d", ":h"]
    params = {"i": pid, "f": need(f, "first_name", "First name"), "d": dispatch_id, "h": d["hospital_id"]}
    for key in ("middle_name", "last_name", "blood_group", "gender", "chief_complaint"):
        if text(f, key):
            cols.append(key); vals.append(":" + key); params[key] = text(f, key)
    if text(f, "dob"):
        cols.append("dob"); vals.append("TO_DATE(:dob, 'YYYY-MM-DD')"); params["dob"] = text(f, "dob")
    allergies = split_list(text(f, "known_allergies"), 60, "Each allergy")
    # the database trigger takes one bed at the hospital (and refuses when none is free)
    run(conn, "INSERT INTO patient (%s) VALUES (%s)" % (", ".join(cols), ", ".join(vals)), **params)
    for a in allergies:                      # one row per allergy (first normal form)
        run(conn, "INSERT INTO patient_allergy (patient_id, allergy) VALUES (:p, :a)", p=pid, a=a)
    conn.commit()
    return pid


def vitals(conn, patient_id):
    return rows(conn, """SELECT log_time, temperature, o2, systolic, diastolic, heart_rate
                         FROM patient_vitals_log WHERE patient_id = :p ORDER BY log_time DESC""", p=patient_id)


def add_vitals(conn, patient_id, f):
    if get_patient(conn, patient_id) is None:
        raise RuleError("That patient does not exist.")
    vals = {k: number(f, k, label, False) for k, label in (("temperature", "Temperature"), ("o2", "Oxygen (SpO2)"),
                                                          ("systolic", "Systolic"), ("diastolic", "Diastolic"),
                                                          ("heart_rate", "Heart rate"))}
    if all(v is None for v in vals.values()):
        raise RuleError("Enter at least one reading.")
    run(conn, """INSERT INTO patient_vitals_log (patient_id, log_time, temperature, o2, systolic, diastolic, heart_rate)
                 VALUES (:p, SYSTIMESTAMP, :temperature, :o2, :systolic, :diastolic, :heart_rate)""", p=patient_id, **vals)
    conn.commit()


# ------------------------------------------------------------------ billing
BILL_SQL = """
SELECT b.billing_id, b.receipt, b.bill_date, b.total_amount, b.amount_paid, b.total_amount - b.amount_paid AS balance,
       b.distance_km, b.base_fare, b.payment_mode, b.payment_status, b.dispatch_id, b.customer_id,
       b.agent_id, b.billed_by, TRIM(cu.first_name || ' ' || cu.last_name) AS customer,
       TRIM(ag.first_name || ' ' || ag.last_name) AS agent,
       (SELECT TRIM(x.first_name || ' ' || x.last_name) FROM driver x WHERE x.hr_id = b.billed_by
        UNION ALL SELECT TRIM(y.first_name || ' ' || y.last_name) FROM paramedic y WHERE y.hr_id = b.billed_by) AS billed_by_name
FROM billing b JOIN customer cu ON cu.customer_id = b.customer_id
LEFT JOIN call_center_agent ag ON ag.agent_id = b.agent_id
"""


def list_bills(conn, status="", limit=MAX_ROWS):
    where, params = "", {}
    if status == "open":
        where = "WHERE NVL(b.payment_status,'Unpaid') <> 'Paid'"
    elif status:
        where, params = "WHERE b.payment_status = :s", {"s": status}
    return rows(conn, "SELECT * FROM (%s %s ORDER BY b.billing_id DESC) WHERE ROWNUM <= %d" % (BILL_SQL, where, int(limit)), **params)


def get_bill(conn, billing_id):
    return one(conn, BILL_SQL + " WHERE b.billing_id = :i", i=billing_id)


def tariff(conn, ambulance_type):
    t = one(conn, "SELECT ambulance_type, description, base_fare, rate_per_km FROM tariff WHERE ambulance_type = :t", t=ambulance_type)
    if t is None:
        raise RuleError("There is no price for ambulance type '%s'. Add it under Records, Tariff." % ambulance_type)
    return t


def bill_total(base, km, rate):
    return (decimal.Decimal(str(base)) + decimal.Decimal(str(km)) * decimal.Decimal(str(rate))).quantize(decimal.Decimal("0.01"))


def suggested_km(d):
    """A starting figure for the distance of a trip (scene to hospital by road), from the two map positions; the crew can change it."""
    if d.get("pick_lat") is None or d.get("hosp_lat") is None:
        return None
    return round(distance_km(d["pick_lat"], d["pick_lon"], d["hosp_lat"], d["hosp_lon"]) * settings.ROAD_FACTOR, 1)


def payer_for(conn, d, f):
    """The customer who pays. The caller if the call has one; otherwise the payer's name (and phone) typed on the bill is saved as a
    customer and linked to the call, so the call, the customer and the bill always agree."""
    if d["customer_id"] is not None:
        return d["customer_id"]
    name, phone = text(f, "payer_name"), text(f, "payer_phone")
    if not name:
        raise RuleError("The call has no caller on record. Enter the name of the person who is paying.")
    cust_id = None
    if phone:
        known = one(conn, "SELECT customer_id FROM customer_phone WHERE phone_no = :p AND ROWNUM = 1", p=phone)
        if known:
            cust_id = known["customer_id"]
    if cust_id is None:
        first, _, last = name.partition(" ")
        cust_id = nextval(conn, "seq_customer")
        run(conn, "INSERT INTO customer (customer_id, first_name, last_name, agent_id) VALUES (:i, :f, :l, :a)",
            i=cust_id, f=first, l=last.strip() or "-", a=d["agent_id"])
        if phone:
            run(conn, "INSERT INTO customer_phone (customer_id, phone_no) VALUES (:i, :p)", i=cust_id, p=phone)
    run(conn, "UPDATE emergency_call SET customer_id = :c WHERE call_id = :k AND customer_id IS NULL", c=cust_id, k=d["call_id"])
    return cust_id


def create_bill(conn, dispatch_id, f, billed_by=None):
    """Make the bill of a trip. Normally the driver / paramedic does this at the end of the trip (billed_by = their hr_id);
    the Administrator can also do it. The agent only sees the status."""
    d = get_dispatch(conn, dispatch_id)
    if d is None:
        raise RuleError("That dispatch does not exist.")
    if d["status"] not in ("At Hospital", "Completed"):
        raise RuleError("A bill can be made once the ambulance has reached the hospital or the trip is completed.")
    if d["billing_id"]:
        raise RuleError("This dispatch already has a bill.")
    mode = need(f, "payment_mode", "Payment mode")
    if mode not in settings.PAYMENT_MODES:
        raise RuleError("Payment mode must be %s." % ", ".join(settings.PAYMENT_MODES))
    km = number(f, "distance_km", "Distance (km)")
    if km < 0 or km > 1000:
        raise RuleError("The distance must be between 0 and 1000 km.")
    t = tariff(conn, d["type_of_ambulance"])
    total = bill_total(t["base_fare"], km, t["rate_per_km"])
    paid = number(f, "amount_paid", "Amount received", False) or decimal.Decimal("0")
    if paid < 0 or paid > total:
        raise RuleError("The amount received must be between 0 and the total (%s)." % total)
    customer = payer_for(conn, d, f)
    bid = nextval(conn, "seq_billing")
    run(conn, """INSERT INTO billing (billing_id, payment_mode, bill_date, receipt, total_amount, amount_paid, distance_km,
                                       base_fare, customer_id, dispatch_id, agent_id, billed_by)
                 VALUES (:i, :pm, SYSDATE, :r, :t, :pd, :km, :bf, :c, :d, :a, :b)""",
        i=bid, pm=mode, r="RCP-%04d" % bid, t=total, pd=paid, km=km, bf=t["base_fare"], c=customer, d=dispatch_id,
        a=d["agent_id"], b=billed_by)
    conn.commit()
    return bid


def record_payment(conn, billing_id, f):
    b = get_bill(conn, billing_id)
    if b is None:
        raise RuleError("That bill does not exist.")
    amount = number(f, "amount", "Amount")
    if amount <= 0:
        raise RuleError("Enter an amount greater than zero.")
    if amount > b["balance"]:
        raise RuleError("The amount is more than the balance still to pay (%s)." % b["balance"])
    mode = need(f, "payment_mode", "Payment mode")
    if mode not in settings.PAYMENT_MODES:
        raise RuleError("Payment mode must be %s." % ", ".join(settings.PAYMENT_MODES))
    run(conn, "UPDATE billing SET amount_paid = amount_paid + :a, payment_mode = :m WHERE billing_id = :i",
        a=amount, m=mode, i=billing_id)
    conn.commit()


# ------------------------------------------------------------------ fleet and staff
def fleet(conn):
    return rows(conn, """
        SELECT a.ambulance_id, a.model, a.vehicle_no, a.type_of_ambulance, a.status, a.current_location,
               (SELECT MAX(d.dispatch_id) FROM dispatch d WHERE d.ambulance_id = a.ambulance_id AND d.status IN %s) AS active_dispatch,
               (SELECT MAX(i.expiry_date) FROM ambulance_insurance i WHERE i.ambulance_id = a.ambulance_id) AS insured_until,
               (SELECT MAX(m.next_due_date) FROM ambulance_maintenance_log m WHERE m.ambulance_id = a.ambulance_id) AS next_service,
               (SELECT MAX(l.log_time) FROM location_log l WHERE l.ambulance_id = a.ambulance_id) AS last_ping,
               (SELECT l.latitude FROM location_log l WHERE l.ambulance_id = a.ambulance_id
                   AND l.log_time = (SELECT MAX(l2.log_time) FROM location_log l2 WHERE l2.ambulance_id = a.ambulance_id)) AS ping_lat,
               (SELECT l.longitude FROM location_log l WHERE l.ambulance_id = a.ambulance_id
                   AND l.log_time = (SELECT MAX(l2.log_time) FROM location_log l2 WHERE l2.ambulance_id = a.ambulance_id)) AS ping_lon
        FROM ambulance a ORDER BY a.ambulance_id""" % ACTIVE_SQL)


def equipment_alerts(conn):
    return rows(conn, """
        SELECT a.vehicle_no, e.equipment_name, e.equipment_condition, e.expiry_date, e.expiry_date - TRUNC(SYSDATE) AS days_left
        FROM ambulance_equipment e JOIN ambulance a ON a.ambulance_id = e.ambulance_id
        WHERE (e.expiry_date IS NOT NULL AND e.expiry_date <= TRUNC(SYSDATE) + :d) OR e.equipment_condition = 'Needs Repair'
        ORDER BY e.expiry_date""", d=settings.EQUIPMENT_WARN_DAYS)


FLEET_STATUSES = ["Available", "Maintenance"]


def update_ambulance(conn, ambulance_id, f):
    status = need(f, "status", "Status")
    if status not in FLEET_STATUSES:
        raise RuleError("Choose Available or Maintenance. 'On Duty' is set automatically by dispatch.")
    if scalar(conn, "SELECT COUNT(*) FROM dispatch WHERE ambulance_id = :a AND status IN %s" % ACTIVE_SQL, a=ambulance_id):
        raise RuleError("This ambulance is on an active dispatch. Complete the dispatch first.")
    if run(conn, "UPDATE ambulance SET status = :s, current_location = NVL(:l, current_location) WHERE ambulance_id = :a",
           s=status, l=text(f, "current_location") or None, a=ambulance_id) == 0:
        raise RuleError("That ambulance does not exist.")
    conn.commit()


ATT_PCT = """(SELECT ROUND(100 * SUM(DECODE(t.status, 'Present', 1, 'Half Day', 0.5, 0)) / NULLIF(COUNT(CASE WHEN t.status <> 'On Leave' THEN 1 END), 0))
          FROM hr_attendance t WHERE t.hr_id = s.hr_id AND t.att_date > TRUNC(SYSDATE) - 30 AND t.att_date <= TRUNC(SYSDATE))"""

STAFF_BASE = """
        SELECT 'Agent' AS role, a.agent_id AS id, a.hr_id, TRIM(a.first_name || ' ' || a.last_name) AS name, a.phone_no,
               TRIM(a.agent_role || CASE WHEN a.shift IS NOT NULL THEN ' (' || a.shift || ')' END) AS title,
               TRUNC(MONTHS_BETWEEN(SYSDATE, a.dob) / 12) AS age, a.date_of_joining,
               ROUND(MONTHS_BETWEEN(SYSDATE, a.date_of_joining) / 12, 1) AS years,
               (SELECT LISTAGG(l.language, ', ') WITHIN GROUP (ORDER BY l.language) FROM agent_language l WHERE l.agent_id = a.agent_id) AS languages, a.is_active,
               NULL AS ambulance
        FROM call_center_agent a
        UNION ALL
        SELECT 'Driver', d.driver_id, d.hr_id, TRIM(d.first_name || ' ' || d.last_name), d.phone_no,
               'Ambulance driver, licence ' || d.license_no,
               TRUNC(MONTHS_BETWEEN(SYSDATE, d.dob) / 12), d.date_of_joining,
               ROUND(MONTHS_BETWEEN(SYSDATE, d.date_of_joining) / 12, 1), NULL, d.is_active,
               (SELECT x.vehicle_no FROM ambulance x WHERE x.ambulance_id = d.ambulance_id)
        FROM driver d
        UNION ALL
        SELECT 'Paramedic', p.paramedic_id, p.hr_id, TRIM(p.first_name || ' ' || p.last_name), p.phone_no,
               p.certification_level,
               TRUNC(MONTHS_BETWEEN(SYSDATE, p.dob) / 12), p.date_of_joining,
               ROUND(MONTHS_BETWEEN(SYSDATE, p.date_of_joining) / 12, 1), NULL, p.is_active,
               (SELECT x.vehicle_no FROM ambulance x WHERE x.ambulance_id = p.ambulance_id)
        FROM paramedic p"""

LEAVE_USED = """(SELECT NVL(SUM(l.end_date - l.start_date + 1), 0) FROM hr_leave l
                 WHERE l.hr_id = s.hr_id AND l.status = 'Approved' AND l.leave_type <> 'Unpaid'
                   AND TO_CHAR(l.start_date, 'YYYY') = TO_CHAR(SYSDATE, 'YYYY'))"""


def staff(conn, hr_id=None):
    """Everybody HR looks after, with the figures worked out from the attendance and leave tables."""
    sql = """
        SELECT s.*, h.salary, h.annual_leave_days, h.leave_policy, h.staff_insurance,
               %s AS attendance_pct,
               h.annual_leave_days - %s AS leave_left,
               (SELECT COUNT(*) FROM hr_leave l WHERE l.hr_id = s.hr_id AND l.status = 'Pending') AS pending_leaves
        FROM (%s) s JOIN hr h ON h.hr_id = s.hr_id""" % (ATT_PCT, LEAVE_USED, STAFF_BASE)
    if hr_id is not None:
        return one(conn, sql + " WHERE s.hr_id = :h", h=hr_id)
    return rows(conn, sql + " ORDER BY s.role, s.name")


EMPLOYEE_KINDS = [("Agent", "Call-centre agent"), ("Driver", "Ambulance driver"), ("Paramedic", "Paramedic")]
AGENT_SHIFTS = ("Day", "Evening", "Night")
PARAMEDIC_LEVELS = ("Basic", "Intermediate", "Advanced")


def ambulance_choices(conn):
    return rows(conn, "SELECT ambulance_id, vehicle_no FROM ambulance ORDER BY vehicle_no")


def add_staff(conn, f):
    """Add one new employee: the HR record (salary, leave, insurance) and the agent / driver / paramedic record together."""
    kind = need(f, "kind", "Role")
    if kind not in [k for k, _ in EMPLOYEE_KINDS]:
        raise RuleError("Choose the role of the new employee.")
    first, last = need(f, "first_name", "First name"), need(f, "last_name", "Last name")
    dob, joined = date_of(f, "dob", "Date of birth"), date_of(f, "date_of_joining", "Date of joining")
    if joined.date() > datetime.date.today():
        raise RuleError("The date of joining cannot be in the future.")
    if (joined.year - dob.year) - ((joined.month, joined.day) < (dob.month, dob.day)) < 18:
        raise RuleError("An employee must be at least 18 years old on the date of joining.")
    aadhar = need(f, "aadhar", "Aadhar number")
    if not (aadhar.isdigit() and len(aadhar) == 12):
        raise RuleError("The Aadhar number must be 12 digits.")
    pin = text(f, "pincode")
    if pin and not (pin.isdigit() and len(pin) == 6):
        raise RuleError("The pincode must be 6 digits.")
    phone = need(f, "phone_no", "Phone number")
    salary = number(f, "salary", "Monthly salary")
    days = whole(f, "annual_leave_days", "Leave days per year")
    if salary < 0 or days < 0:
        raise RuleError("Salary and leave days cannot be negative.")
    common = dict(f=first, m=text(f, "middle_name") or None, l=last, d=dob, a=aadhar, s=text(f, "street") or None,
                  c=text(f, "city") or None, st=text(f, "state") or None, p=pin or None, ph=phone, j=joined)
    hr_id = nextval(conn, "seq_hr")
    run(conn, "INSERT INTO hr (hr_id, salary, annual_leave_days, leave_policy, staff_insurance) VALUES (:h, :s, :d, :p, :i)",
        h=hr_id, s=salary, d=days, p=text(f, "leave_policy") or None, i=text(f, "staff_insurance") or None)
    if kind == "Agent":
        shift = need(f, "shift", "Shift")
        if shift not in AGENT_SHIFTS:
            raise RuleError("Choose Day, Evening or Night shift.")
        langs = split_list(text(f, "languages"), 40, "Each language")
        agent_id = nextval(conn, "seq_call_center_agent")
        run(conn, """INSERT INTO call_center_agent (agent_id, first_name, middle_name, last_name, dob, aadhar, street, city, state, pincode,
                         phone_no, shift, agent_role, date_of_joining, hr_id)
                     VALUES (:aid, :f, :m, :l, :d, :a, :s, :c, :st, :p, :ph, :sh, :role, :j, :h)""",
            aid=agent_id, h=hr_id, sh=shift, role=text(f, "agent_role") or "Agent", **common)
        for lang in langs:                   # one row per language (first normal form)
            run(conn, "INSERT INTO agent_language (agent_id, language) VALUES (:a, :l)", a=agent_id, l=lang)
    elif kind == "Driver":
        lic = need(f, "license_no", "Licence number")
        lic_exp = date_of(f, "license_expiry", "Licence expiry")
        if lic_exp.date() <= datetime.date.today():
            raise RuleError("That driving licence has already expired.")
        run(conn, """INSERT INTO driver (driver_id, first_name, middle_name, last_name, dob, aadhar, street, city, state, pincode,
                         phone_no, license_no, license_expiry, driving_experience, date_of_joining, hr_id, ambulance_id)
                     VALUES (seq_driver.NEXTVAL, :f, :m, :l, :d, :a, :s, :c, :st, :p, :ph, :lic, :le, :ex, :j, :h, :amb)""",
            h=hr_id, lic=lic, le=lic_exp, ex=whole(f, "driving_experience", "Years of driving experience", False),
            amb=whole(f, "ambulance_id", "Ambulance", False), **common)
    else:
        level = need(f, "certification_level", "Certification level")
        if level not in PARAMEDIC_LEVELS:
            raise RuleError("Choose Basic, Intermediate or Advanced.")
        common.pop("ph")
        run(conn, """INSERT INTO paramedic (paramedic_id, first_name, middle_name, last_name, dob, aadhar, street, city, state, pincode,
                         phone_no, certification_no, certification_level, date_of_joining, hr_id, ambulance_id)
                     VALUES (seq_paramedic.NEXTVAL, :f, :m, :l, :d, :a, :s, :c, :st, :p, :ph, :cn, :cl, :j, :h, :amb)""",
            h=hr_id, ph=phone, cn=need(f, "certification_no", "Certification number"), cl=level,
            amb=whole(f, "ambulance_id", "Ambulance", False), **common)
    conn.commit()
    return hr_id


def hr_owners(conn):
    """Which employee each HR record belongs to: {hr_id: (name, role)}."""
    out = {}
    for r in rows(conn, """
        SELECT a.hr_id, 'Call-centre agent' AS role, TRIM(a.first_name || ' ' || a.last_name) AS name FROM call_center_agent a
        UNION ALL SELECT d.hr_id, 'Driver', TRIM(d.first_name || ' ' || d.last_name) FROM driver d
        UNION ALL SELECT p.hr_id, 'Paramedic', TRIM(p.first_name || ' ' || p.last_name) FROM paramedic p"""):
        out[int(r["hr_id"])] = (r["name"], r["role"])
    return out


# ------------------------------------------------------------------ users and sign-in
MAX_FAILED = 5
LOCK_MINUTES = 15
ROLES = [("ADMIN", "Administrator"), ("AGENT", "Call-centre agent"), ("HR", "HR officer"), ("MAINTENANCE", "Maintenance"),
         ("DRIVER", "Driver"), ("PARAMEDIC", "Paramedic")]
CREATABLE_ROLES = [("ADMIN", "Administrator"), ("AGENT", "Call-centre agent (shared login)"), ("HR", "HR officer"),
                   ("MAINTENANCE", "Maintenance")]   # drivers and paramedics get their own login when they are added


def emp_id(hr_id):
    """The Employee ID used to sign in."""
    return "EMP%03d" % int(hr_id)


def login_name(typed):
    """What a person typed in the ID box: EMP004, emp004 or just 4."""
    t = typed.strip()
    return emp_id(t) if t.isdigit() else t

USER_SQL = """
SELECT u.user_id, u.username, u.password_hash, u.full_name, u.user_role, u.hr_id, u.hr_id AS my_hr_id,
       CASE WHEN u.is_active = 'Y' AND NOT EXISTS (
              SELECT 1 FROM (SELECT hr_id FROM call_center_agent WHERE is_active = 'N'
                             UNION ALL SELECT hr_id FROM driver WHERE is_active = 'N'
                             UNION ALL SELECT hr_id FROM paramedic WHERE is_active = 'N') x WHERE x.hr_id = u.hr_id)
            THEN 'Y' ELSE 'N' END AS is_active,
       u.failed_attempts, u.last_login, u.created_on,
       CASE WHEN u.locked_until > SYSDATE THEN CEIL((u.locked_until - SYSDATE) * 1440) ELSE 0 END AS locked_minutes
FROM app_user u
"""


def get_user_by_name(conn, username):
    return one(conn, USER_SQL + " WHERE LOWER(u.username) = :n", n=login_name(username).lower())


def user_is_active(conn, user_id):
    u = one(conn, USER_SQL + " WHERE u.user_id = :i", i=user_id)
    return u is not None and u["is_active"] == "Y"


def note_failed_login(conn, user_id):
    run(conn, """UPDATE app_user SET failed_attempts = failed_attempts + 1,
                    locked_until = CASE WHEN failed_attempts + 1 >= :m THEN SYSDATE + :l / 1440 ELSE locked_until END
                 WHERE user_id = :i""", m=MAX_FAILED, l=LOCK_MINUTES, i=user_id)
    conn.commit()


def note_login(conn, user_id):
    run(conn, "UPDATE app_user SET failed_attempts = 0, locked_until = NULL, last_login = SYSDATE WHERE user_id = :i", i=user_id)
    conn.commit()


def list_users(conn):
    return rows(conn, USER_SQL + " ORDER BY u.user_role, u.username")


def check_password_rules(pw):
    if len(pw) < 8:
        raise RuleError("The password must have at least 8 characters.")
    if pw.isdigit() or pw.isalpha():
        raise RuleError("The password must mix letters with numbers or symbols.")


def create_user(conn, f, make_hash):
    """A shared login for a role: administrator, call-centre agents, HR officer or maintenance supervisor."""
    name = need(f, "username", "Username").lower()
    if len(name) < 3 or not name.replace("_", "").replace(".", "").isalnum():
        raise RuleError("The username needs at least 3 letters or numbers (underscore and dot are allowed).")
    if name.startswith("emp") and name[3:].isdigit():
        raise RuleError("Usernames like EMP004 are Employee IDs and are made automatically.")
    role = need(f, "user_role", "Role")
    if role not in [r for r, _ in CREATABLE_ROLES]:
        raise RuleError("Choose Administrator, Call-centre agent, HR officer or Maintenance. Drivers and paramedics get their login when they are added under Staff.")
    pw = need(f, "password", "Password")
    check_password_rules(pw)
    if get_user_by_name(conn, name):
        raise RuleError("That username is already taken.")
    uid = nextval(conn, "seq_app_user")
    run(conn, """INSERT INTO app_user (user_id, username, password_hash, full_name, user_role)
                 VALUES (:i, :u, :h, :n, :r)""",
        i=uid, u=name, h=make_hash(pw), n=need(f, "full_name", "Full name"), r=role)
    conn.commit()
    return uid


def employee_dob(conn, hr_id):
    r = one(conn, """SELECT dob FROM (SELECT hr_id, dob FROM call_center_agent UNION ALL SELECT hr_id, dob FROM driver
                                      UNION ALL SELECT hr_id, dob FROM paramedic) WHERE hr_id = :h""", h=hr_id)
    return r["dob"] if r else None


def first_login(conn, typed_id, dob_text, new_pw, again, make_hash):
    """First sign-in of an employee: Employee ID + date of birth (known to HR) prove who they are, then they choose their password.
    Wrong answers count like wrong passwords: 5 in a row lock the ID for 15 minutes. Returns the user row."""
    u = get_user_by_name(conn, typed_id) if typed_id.strip() else None
    if u is None or u["hr_id"] is None:
        raise RuleError("That Employee ID or date of birth is not right.")
    if u["is_active"] != "Y":
        raise RuleError("This account is switched off. Ask HR.")
    if u["locked_minutes"]:
        raise RuleError("Too many wrong attempts. Try again in %d minute%s." % (u["locked_minutes"], "" if u["locked_minutes"] == 1 else "s"))
    try:
        dob = datetime.datetime.strptime(dob_text.strip()[:10], "%Y-%m-%d")
    except ValueError:
        raise RuleError("Enter your date of birth.")
    real = employee_dob(conn, u["hr_id"])
    if real is None or real.date() != dob.date():
        note_failed_login(conn, u["user_id"])
        raise RuleError("That Employee ID or date of birth is not right.")
    if u["password_hash"]:
        raise RuleError("A password is already set for this ID. Sign in with it, or ask HR to reset it.")
    if new_pw != again:
        raise RuleError("The two passwords are not the same.")
    set_password(conn, u["user_id"], new_pw, make_hash)
    return get_user_by_name(conn, u["username"])


def login_of(conn, hr_id):
    """The sign-in account of one employee, for the HR page."""
    return one(conn, USER_SQL + " WHERE u.hr_id = :h", h=hr_id)


def reset_login(conn, hr_id):
    """Forgotten password: empty it, so the employee chooses a new one (Employee ID + date of birth)."""
    if run(conn, "UPDATE app_user SET password_hash = NULL, failed_attempts = 0, locked_until = NULL WHERE hr_id = :h", h=hr_id) == 0:
        raise RuleError("This employee has no login yet.")
    conn.commit()


def set_password(conn, user_id, new_password, make_hash):
    check_password_rules(new_password)
    run(conn, "UPDATE app_user SET password_hash = :h, failed_attempts = 0, locked_until = NULL WHERE user_id = :i",
        h=make_hash(new_password), i=user_id)
    conn.commit()


def set_user_active(conn, user_id, active):
    run(conn, "UPDATE app_user SET is_active = :a, failed_attempts = 0, locked_until = NULL WHERE user_id = :i",
        a="Y" if active else "N", i=user_id)
    conn.commit()


def unlock_user(conn, user_id):
    run(conn, "UPDATE app_user SET failed_attempts = 0, locked_until = NULL WHERE user_id = :i", i=user_id)
    conn.commit()


# ================================================================== HR: attendance, leave, salary
ATTENDANCE_STATUSES = ("Present", "Half Day", "Absent", "On Leave")
LEAVE_TYPES = ("Casual", "Sick", "Earned", "Unpaid")


def hr_summary(conn):
    return one(conn, """
        SELECT (SELECT COUNT(*) FROM hr_leave WHERE status = 'Pending') AS pending_leaves,
               (SELECT COUNT(*) FROM (%s) s WHERE s.is_active = 'Y'
                   AND NOT EXISTS (SELECT 1 FROM hr_attendance t WHERE t.hr_id = s.hr_id AND t.att_date = TRUNC(SYSDATE))) AS not_marked_today,
               (SELECT COUNT(*) FROM hr_attendance WHERE att_date = TRUNC(SYSDATE) AND status = 'Absent') AS absent_today,
               (SELECT COUNT(*) FROM hr_attendance WHERE att_date = TRUNC(SYSDATE) AND status = 'On Leave') AS on_leave_today
        FROM dual""" % STAFF_BASE)


def people_choices(conn):
    """Active staff for the drop-down lists."""
    return rows(conn, "SELECT s.hr_id, s.name, s.role FROM (%s) s WHERE s.is_active = 'Y' ORDER BY s.role, s.name" % STAFF_BASE)


def attendance_sheet(conn, day):
    """Every active person with the status already saved for that day (or the approved leave that covers it)."""
    return rows(conn, """
        SELECT s.hr_id, s.name, s.role, s.title, s.date_of_joining, t.status, t.check_in,
               CASE WHEN EXISTS (SELECT 1 FROM hr_leave l WHERE l.hr_id = s.hr_id AND l.status = 'Approved'
                                 AND :d BETWEEN l.start_date AND l.end_date) THEN 'Y' ELSE 'N' END AS has_leave
        FROM (%s) s LEFT JOIN hr_attendance t ON t.hr_id = s.hr_id AND t.att_date = :d
        WHERE s.is_active = 'Y' ORDER BY s.role, s.name""" % STAFF_BASE, d=day)


def _set_attendance(conn, hr_id, day, status):
    if run(conn, "UPDATE hr_attendance SET status = :s WHERE hr_id = :h AND att_date = :d", s=status, h=hr_id, d=day) == 0:
        run(conn, "INSERT INTO hr_attendance (hr_id, att_date, status) VALUES (:h, :d, :s)", h=hr_id, d=day, s=status)


def save_attendance(conn, day, f):
    if day > datetime.datetime.now() + datetime.timedelta(days=1):
        raise RuleError("Attendance cannot be marked for a future date.")
    saved = 0
    for p in people_choices(conn):
        st = text(f, "s_%d" % p["hr_id"])
        if not st:
            continue
        if st not in ATTENDANCE_STATUSES:
            raise RuleError("Unknown attendance status '%s'." % st)
        _set_attendance(conn, p["hr_id"], day, st)
        saved += 1
    if not saved:
        raise RuleError("Nothing to save: choose a status for at least one person.")
    conn.commit()
    return saved


def close_day(conn, day):
    """End of the day: everybody who did not mark themselves and was not marked by HR becomes Absent,
    or On Leave when an approved leave covers that day. People who joined after that day are skipped."""
    if day.date() > datetime.date.today():
        raise RuleError("A day that has not happened yet cannot be closed.")
    absent = on_leave = 0
    for p in attendance_sheet(conn, day):
        if p["status"] or (p["date_of_joining"] and p["date_of_joining"] > day):
            continue
        st = "On Leave" if p["has_leave"] == "Y" else "Absent"
        _set_attendance(conn, p["hr_id"], day, st)
        if st == "Absent":
            absent += 1
        else:
            on_leave += 1
    conn.commit()
    return absent, on_leave


def attendance_history(conn, hr_id, days=30):
    return rows(conn, """SELECT att_date, status, check_in FROM hr_attendance
                         WHERE hr_id = :h AND att_date > TRUNC(SYSDATE) - :n ORDER BY att_date DESC""", h=hr_id, n=days)


def attendance_counts(conn, hr_id):
    r = one(conn, """SELECT COUNT(CASE WHEN status = 'Present' THEN 1 END) AS present,
                            COUNT(CASE WHEN status = 'Half Day' THEN 1 END) AS half_day,
                            COUNT(CASE WHEN status = 'Absent' THEN 1 END) AS absent,
                            COUNT(CASE WHEN status = 'On Leave' THEN 1 END) AS on_leave
                     FROM hr_attendance WHERE hr_id = :h AND att_date > TRUNC(SYSDATE) - 30""", h=hr_id)
    return r


LEAVE_SQL = """
SELECT l.leave_id, l.hr_id, s.name, s.role, l.leave_type, l.start_date, l.end_date, l.end_date - l.start_date + 1 AS days,
       l.reason, l.status, l.applied_on, l.decided_by, l.decided_on
FROM hr_leave l JOIN (%s) s ON s.hr_id = l.hr_id
""" % STAFF_BASE


def list_leaves(conn, status="", hr_id=None, limit=MAX_ROWS):
    where, params = [], {}
    if status:
        where.append("l.status = :s")
        params["s"] = status
    if hr_id is not None:
        where.append("l.hr_id = :h")
        params["h"] = hr_id
    sql = LEAVE_SQL + (" WHERE " + " AND ".join(where) if where else "") + \
        " ORDER BY DECODE(l.status, 'Pending', 0, 1), l.start_date DESC"
    return rows(conn, "SELECT * FROM (%s) WHERE ROWNUM <= :n" % sql, n=limit, **params)


def leave_left(conn, hr_id):
    return scalar(conn, """SELECT h.annual_leave_days - %s FROM hr h JOIN (SELECT :h AS hr_id FROM dual) s ON s.hr_id = h.hr_id""" % LEAVE_USED, h=hr_id)


def apply_leave(conn, f):
    hr_id = whole(f, "hr_id", "Employee")
    kind = need(f, "leave_type", "Leave type")
    if kind not in LEAVE_TYPES:
        raise RuleError("Unknown leave type.")
    start, end = date_of(f, "start_date", "From date"), date_of(f, "end_date", "To date")
    if end < start:
        raise RuleError("The last day of leave cannot be before the first day.")
    if (end - start).days > 60:
        raise RuleError("A single leave request cannot be longer than 60 days.")
    if scalar(conn, """SELECT COUNT(*) FROM hr_leave WHERE hr_id = :h AND status IN ('Pending','Approved')
                       AND start_date <= :e AND end_date >= :s""", h=hr_id, s=start, e=end):
        raise RuleError("This person already has a leave request that overlaps these dates.")
    if not scalar(conn, "SELECT COUNT(*) FROM hr WHERE hr_id = :h", h=hr_id):
        raise RuleError("That employee does not exist.")
    new_id = nextval(conn, "seq_hr_leave")
    run(conn, """INSERT INTO hr_leave (leave_id, hr_id, leave_type, start_date, end_date, reason)
                 VALUES (:i, :h, :t, :s, :e, :r)""", i=new_id, h=hr_id, t=kind, s=start, e=end, r=text(f, "reason") or None)
    conn.commit()
    return new_id


def agent_by_emp(conn, typed):
    """The agent whose Employee ID (EMP005, emp005 or just 5) was typed on the shared agent login."""
    t = text({"x": typed}, "x")
    if not t:
        raise RuleError("Enter your Employee ID.")
    t = emp_id(t) if t.isdigit() else t.upper()
    a = one(conn, """SELECT a.hr_id, TRIM(a.first_name || ' ' || a.last_name) AS name FROM call_center_agent a
                     WHERE a.is_active = 'Y' AND 'EMP' || LPAD(a.hr_id, 3, '0') = :e""", e=t)
    if a is None:
        raise RuleError("No agent has that Employee ID. HR can tell you yours.")
    return a


def agent_apply_leave(conn, f):
    """An agent applies for leave from the shared agent login with only their Employee ID; the request waits for HR."""
    agent = agent_by_emp(conn, f.get("emp_id"))
    apply_leave(conn, dict(f, hr_id=str(agent["hr_id"])))
    return agent["name"]


def cancel_leave(conn, leave_id, hr_id):
    """An employee withdraws a request that nobody has decided yet."""
    if run(conn, "DELETE FROM hr_leave WHERE leave_id = :i AND hr_id = :h AND status = 'Pending'", i=leave_id, h=hr_id) == 0:
        raise RuleError("Only your own request that is still waiting for a decision can be withdrawn.")
    conn.commit()


def mark_my_attendance(conn, hr_id, status):
    """An employee marks themself for today. Only Present or Half Day; a day that is already marked is changed by HR only."""
    if status not in ("Present", "Half Day"):
        raise RuleError("Choose Present or Half Day.")
    cur = one(conn, "SELECT status FROM hr_attendance WHERE hr_id = :h AND att_date = TRUNC(SYSDATE)", h=hr_id)
    if cur is not None:
        raise RuleError("Today is already marked as %s. Ask HR if it needs to be changed." % cur["status"])
    if scalar(conn, """SELECT COUNT(*) FROM hr_leave WHERE hr_id = :h AND status = 'Approved'
                       AND TRUNC(SYSDATE) BETWEEN start_date AND end_date""", h=hr_id):
        raise RuleError("You are on approved leave today, so attendance cannot be marked. Ask HR if that is wrong.")
    run(conn, "INSERT INTO hr_attendance (hr_id, att_date, status, check_in) VALUES (:h, TRUNC(SYSDATE), :s, SYSDATE)", h=hr_id, s=status)
    conn.commit()


def my_leave_overview(conn, hr_id):
    """What an employee sees on the 'My leave' page: balance, policy, attendance and own requests."""
    me = staff(conn, hr_id)
    if me is None:
        raise RuleError("Your employee record was not found. Ask HR.")
    today = one(conn, "SELECT status, check_in FROM hr_attendance WHERE hr_id = :h AND att_date = TRUNC(SYSDATE)", h=hr_id)
    return {"me": me, "counts": attendance_counts(conn, hr_id), "leaves": list_leaves(conn, hr_id=hr_id, limit=50),
            "today": today, "history": attendance_history(conn, hr_id, 14)}


def decide_leave(conn, leave_id, decision, by):
    if decision not in ("Approved", "Rejected"):
        raise RuleError("Unknown decision.")
    lv = one(conn, "SELECT hr_id, leave_type, start_date, end_date, status FROM hr_leave WHERE leave_id = :i", i=leave_id)
    if lv is None:
        raise RuleError("That leave request does not exist.")
    if lv["status"] != "Pending":
        raise RuleError("This request was already %s." % lv["status"].lower())
    days = (lv["end_date"] - lv["start_date"]).days + 1
    if decision == "Approved" and lv["leave_type"] != "Unpaid":
        left = leave_left(conn, lv["hr_id"])
        if days > left:
            raise RuleError("Only %d leave day%s left this year, but %d are asked for. Reject it or approve it as Unpaid leave." %
                            (left, "" if left == 1 else "s", days))
    run(conn, "UPDATE hr_leave SET status = :s, decided_by = :b, decided_on = SYSDATE WHERE leave_id = :i", s=decision, b=by, i=leave_id)
    if decision == "Approved":      # the attendance sheet shows these days as On Leave
        for n in range(days):
            _set_attendance(conn, lv["hr_id"], lv["start_date"] + datetime.timedelta(days=n), "On Leave")
    conn.commit()
    return decision


def update_hr(conn, hr_id, f):
    salary = number(f, "salary", "Salary")
    days = whole(f, "annual_leave_days", "Annual leave days")
    if salary < 0 or days < 0:
        raise RuleError("Salary and leave days cannot be negative.")
    if run(conn, """UPDATE hr SET salary = :s, annual_leave_days = :d, leave_policy = :p, staff_insurance = :i WHERE hr_id = :h""",
           s=salary, d=days, p=text(f, "leave_policy") or None, i=text(f, "staff_insurance") or None, h=hr_id) == 0:
        raise RuleError("That HR record does not exist.")
    conn.commit()


# ================================================================== Maintenance: vehicles, insurance, servicing, equipment
POLICY_TYPES = ("Comprehensive", "Third Party")
SERVICE_TYPES = ("Routine service", "Tyre replacement", "Brake service", "Engine repair", "Electrical", "Body work", "Other")
EQUIPMENT_CONDITIONS = ("Good", "Fair", "Needs Repair")


def get_ambulance(conn, ambulance_id):
    return one(conn, """
        SELECT a.ambulance_id, a.model, a.vehicle_no, a.type_of_ambulance, a.status, a.manufacture_year, a.current_location,
               (SELECT MAX(d.dispatch_id) FROM dispatch d WHERE d.ambulance_id = a.ambulance_id AND d.status IN %s) AS active_dispatch
        FROM ambulance a WHERE a.ambulance_id = :a""" % ACTIVE_SQL, a=ambulance_id)


def insurance_list(conn, ambulance_id):
    return rows(conn, """SELECT policy_no, insurer, policy_type, start_date, expiry_date, premium,
                                expiry_date - TRUNC(SYSDATE) AS days_left
                         FROM ambulance_insurance WHERE ambulance_id = :a ORDER BY expiry_date DESC""", a=ambulance_id)


def service_list(conn, ambulance_id):
    return rows(conn, """SELECT maintenance_date, maintenance_type, description, workshop, handled_by, cost, next_due_date,
                                next_due_date - TRUNC(SYSDATE) AS days_left
                         FROM ambulance_maintenance_log WHERE ambulance_id = :a ORDER BY maintenance_date DESC""", a=ambulance_id)


def equipment_list(conn, ambulance_id):
    return rows(conn, """SELECT equipment_no, equipment_name, equipment_condition, expiry_date, quantity,
                                expiry_date - TRUNC(SYSDATE) AS days_left
                         FROM ambulance_equipment WHERE ambulance_id = :a ORDER BY equipment_no""", a=ambulance_id)


def recent_pings(conn, ambulance_id, limit=5):
    return rows(conn, """SELECT * FROM (SELECT log_time, speed, latitude, longitude FROM location_log
                                        WHERE ambulance_id = :a ORDER BY log_time DESC) WHERE ROWNUM <= :n""", a=ambulance_id, n=limit)


def add_insurance(conn, ambulance_id, f):
    policy = need(f, "policy_no", "Policy number")
    kind = need(f, "policy_type", "Policy type")
    if kind not in POLICY_TYPES:
        raise RuleError("Choose Comprehensive or Third Party.")
    start, end = date_of(f, "start_date", "Start date"), date_of(f, "expiry_date", "Expiry date")
    if end <= start:
        raise RuleError("The expiry date must be after the start date.")
    premium = number(f, "premium", "Premium", False)
    if premium is not None and premium < 0:
        raise RuleError("The premium cannot be negative.")
    if scalar(conn, "SELECT COUNT(*) FROM ambulance_insurance WHERE policy_no = :p", p=policy):
        raise RuleError("A policy with this number is already recorded.")
    run(conn, """INSERT INTO ambulance_insurance (policy_no, ambulance_id, insurer, policy_type, start_date, expiry_date, premium)
                 VALUES (:p, :a, :i, :t, :s, :e, :m)""", p=policy, a=ambulance_id, i=need(f, "insurer", "Insurer"), t=kind, s=start, e=end, m=premium)
    conn.commit()


def add_service(conn, ambulance_id, f, by):
    day = date_of(f, "maintenance_date", "Service date")
    kind = need(f, "maintenance_type", "Type of work")
    if kind not in SERVICE_TYPES:
        raise RuleError("Unknown type of work.")
    nxt = date_of(f, "next_due_date", "Next service due", False)
    if nxt is not None and nxt < day:
        raise RuleError("The next service cannot be due before this service.")
    cost = number(f, "cost", "Cost", False)
    if cost is not None and cost < 0:
        raise RuleError("The cost cannot be negative.")
    if scalar(conn, "SELECT COUNT(*) FROM ambulance_maintenance_log WHERE ambulance_id = :a AND maintenance_date = :d", a=ambulance_id, d=day):
        raise RuleError("A service is already recorded for this ambulance on that date.")
    run(conn, """INSERT INTO ambulance_maintenance_log (ambulance_id, maintenance_date, maintenance_type, description, workshop, handled_by, cost, next_due_date)
                 VALUES (:a, :d, :t, :x, :w, :b, :c, :n)""",
        a=ambulance_id, d=day, t=kind, x=text(f, "description") or None, w=text(f, "workshop") or None, b=by, c=cost, n=nxt)
    conn.commit()


def add_equipment(conn, ambulance_id, f):
    name = need(f, "equipment_name", "Equipment")
    cond = need(f, "equipment_condition", "Condition")
    if cond not in EQUIPMENT_CONDITIONS:
        raise RuleError("Unknown condition.")
    qty = whole(f, "quantity", "Quantity")
    if qty < 0:
        raise RuleError("The quantity cannot be negative.")
    no = int(scalar(conn, "SELECT NVL(MAX(equipment_no), 0) + 1 FROM ambulance_equipment WHERE ambulance_id = :a", a=ambulance_id))
    run(conn, """INSERT INTO ambulance_equipment (ambulance_id, equipment_no, equipment_name, equipment_condition, expiry_date, quantity)
                 VALUES (:a, :n, :e, :c, :x, :q)""", a=ambulance_id, n=no, e=name, c=cond, x=date_of(f, "expiry_date", "Expiry date", False), q=qty)
    conn.commit()


def set_equipment_condition(conn, ambulance_id, equipment_no, f):
    cond = need(f, "equipment_condition", "Condition")
    if cond not in EQUIPMENT_CONDITIONS:
        raise RuleError("Unknown condition.")
    if run(conn, "UPDATE ambulance_equipment SET equipment_condition = :c WHERE ambulance_id = :a AND equipment_no = :n",
           c=cond, a=ambulance_id, n=equipment_no) == 0:
        raise RuleError("That equipment item does not exist.")
    conn.commit()


# ================================================================== Admin: the audit trail
def audit_users(conn):
    return [r["changed_by"] for r in rows(conn, "SELECT DISTINCT changed_by FROM audit_log WHERE changed_by IS NOT NULL ORDER BY 1")]


def audit_entries(conn, user="", table="", action="", day_from="", day_to="", q="", limit=300):
    where, params = [], {}
    if user:
        where.append("changed_by = :u"); params["u"] = user
    if table:
        where.append("table_name = :t"); params["t"] = table.upper()
    if action:
        where.append("action = :a"); params["a"] = action
    for key, label, op in (("day_from", day_from, ">="), ("day_to", day_to, "<")):
        if label:
            try:
                d = datetime.datetime.strptime(label, "%Y-%m-%d")
            except ValueError:
                raise RuleError("The dates must look like 2026-11-18.")
            params[key] = d + datetime.timedelta(days=1) if key == "day_to" else d
            where.append("changed_at %s :%s" % (op, key))
    if q:
        where.append("(LOWER(details) LIKE :q OR LOWER(record_id) LIKE :q)")
        params["q"] = "%" + q.lower() + "%"
    sql = """SELECT audit_id, changed_at, changed_by, table_name, record_id, action, details FROM audit_log""" + \
          (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY changed_at DESC, audit_id DESC"
    return rows(conn, "SELECT * FROM (%s) WHERE ROWNUM <= :n" % sql, n=limit, **params)
