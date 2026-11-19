"""Emergency Ambulance Management System - web front end (Flask + HTML) on the Oracle database."""
import datetime
import hmac
import secrets
from functools import wraps

import oracledb
from flask import (Flask, abort, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import config
import db
import ops
import settings

app = Flask(__name__)
# the sample key in config.py is public, so unless you set your own the app makes a random one at each start (everybody signs in again after a restart)
app.secret_key = config.SECRET_KEY if not str(config.SECRET_KEY).startswith("change-this") else __import__("secrets").token_hex(32)
app.permanent_session_lifetime = datetime.timedelta(minutes=settings.SESSION_MINUTES)
app.jinja_env.globals["STALE_MINUTES"] = settings.STALE_MINUTES
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

OPS_ROLES = ("AGENT", "ADMIN")            # calls, dispatch, patients, billing, hospitals, ambulance status
FLEET_ROLES = ("MAINTENANCE", "ADMIN")    # vehicles, insurance, servicing, equipment
HR_ROLES = ("HR", "ADMIN")                # staff, attendance, leave, salary
ADMIN_ROLES = ("ADMIN",)                  # users and the audit trail
SELF_ROLES = ("DRIVER", "PARAMEDIC")             # employees with their own login: their trips, attendance and leave
SELF_ONLY_ROLES = ("DRIVER", "PARAMEDIC")        # their login shows only that one page

ROLE_NAMES = dict(ops.ROLES)

SECTIONS = {"my_trips": "mytrips", "my_trip_collect": "mytrips", "my_trip_bill": "mytrips", "calls_page": "calls", "call_new": "calls", "call_detail": "calls", "call_dispatch": "calls",
            "dispatches_page": "dispatches", "dispatch_detail": "dispatches", "dispatch_destination": "dispatches",
            "patients_page": "patients", "patient_detail": "patients", "patient_new": "patients",
            "bills_page": "bills", "bill_new": "bills", "bill_detail": "bills", "hospitals_page": "hospitals",
            "fleet_page": "fleet", "fleet_detail": "fleet", "ambulances_page": "ambulances",
            "my_leave": "myleave", "agent_leave": "agentleave", "my_attendance": "myleave", "staff_page": "staff", "staff_detail": "staff", "attendance_page": "attendance", "leaves_page": "leaves",
            "home": "home", "board_page": "board", "audit_page": "audit",
            "users_page": "users", "user_new": "users", "password_page": "account"}


# ------------------------------------------------------------------ helpers
def get_conn():
    if "conn" not in g:
        g.conn = db.connect(session.get("user"))
    return g.conn


@app.teardown_appcontext
def close_conn(_):
    conn = g.pop("conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def allowed_tables(role):
    rule = settings.ROLE_TABLES.get(role, [])
    return list(db.TABLES) if rule == "ALL" else [t for t in db.TABLES if t in rule]


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def table_access(f):
    """The table in the address must exist and be allowed for the signed-in role."""
    @wraps(f)
    def wrapper(table, *a, **kw):
        if table not in db.TABLES:
            abort(404)
        if table not in allowed_tables(session["role"]):
            return render_template("denied.html", title="Access denied"), 403
        return f(table, *a, **kw)
    return wrapper


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def guard():
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("_csrf", ""), session.get("_csrf", "-")):
            abort(400)
    # a person who was switched off while signed in is signed out at the next click
    if "user_id" in session and request.endpoint not in ("static", "login", "logout", "first_login"):
        if not ops.user_is_active(get_conn(), session["user_id"]):
            session.clear()
            flash("Your account is switched off. Ask an administrator.", "error")
            return redirect(url_for("login"))


def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user" not in session:
                return redirect(url_for("login"))
            if session["role"] not in roles:
                return render_template("denied.html", title="Access denied"), 403
            return f(*a, **kw)
        return wrapper
    return deco


def role_in(roles):
    return session.get("role") in roles


def attempt(conn, fn, *args):
    """Run one workflow action; show a clear message when a rule or the database refuses it."""
    try:
        return True, fn(conn, *args)
    except ops.RuleError as e:
        conn.rollback()
        flash(str(e), "error")
    except db.FormError as e:
        conn.rollback()
        flash(str(e), "error")
    except oracledb.DatabaseError as e:
        conn.rollback()
        flash(db.friendly_error(e), "error")
    return False, None


def form_data():
    """The submitted form. The agent login is shared, so the agent chosen on the form is remembered as the default for the next form."""
    d = request.form.to_dict()
    if session.get("role") == "AGENT" and d.get("agent_id", "").isdigit():
        session["agent_id"] = int(d["agent_id"])
    return d


@app.context_processor
def inject():
    role = session.get("role")
    nav = [(t, db.LABELS[t]) for t in allowed_tables(role)] if role else []
    waiting_n = None
    if role in OPS_ROLES and request.endpoint not in ("login", "static"):
        try:   # the number on the "Live board" menu item; never let it break a page
            waiting_n = ops.waiting_count(get_conn())
        except Exception:
            waiting_n = None
    return {"waiting_n": waiting_n, "csrf_token": csrf_token, "nav": nav, "role": role,
            "role_name": ROLE_NAMES.get(role, ""), "user": session.get("user"),
            "full_name": session.get("full_name"),
            "ops_ok": role in OPS_ROLES, "fleet_ok": role in FLEET_ROLES, "hr_ok": role in HR_ROLES,
            "admin_ok": role in ADMIN_ROLES, "self_ok": role in SELF_ROLES,
            "section": SECTIONS.get(request.endpoint, ""), "settings": settings}


@app.template_filter("show")
def show_filter(v, col):
    return db.show(v, col)


@app.template_filter("dt")
def dt_filter(v):
    return v.strftime("%d %b %Y, %H:%M") if v else ""


@app.template_filter("day")
def day_filter(v):
    return v.strftime("%d %b %Y") if v else ""


@app.template_filter("money")
def money_filter(v):
    return "" if v is None else "\u20b9{:,.2f}".format(float(v))


@app.errorhandler(404)
def not_found(e):
    return render_template("notfound.html", title="Page not found"), 404


@app.errorhandler(oracledb.Error)
def oracle_down(e):
    return render_template("error.html", title="Cannot reach Oracle", message=db.friendly_error(e)), 500


@app.errorhandler(RuntimeError)
def runtime_problem(e):
    return render_template("error.html", title="Problem", message=str(e)), 500


# ------------------------------------------------------------------ sign in
DUMMY_HASH = generate_password_hash("not-a-real-password")


@app.route("/")
def index():
    return redirect(url_for("home" if "user" in session else "login"))


def start_session(u):
    ops.note_login(get_conn(), u["user_id"])
    session.clear()
    session.permanent = True
    session.update(user=u["username"], user_id=int(u["user_id"]), role=u["user_role"], full_name=u["full_name"],
                   hr_id=u["my_hr_id"] and int(u["my_hr_id"]))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_conn()
        name = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        u = ops.get_user_by_name(conn, name) if name else None
        if u is None:
            check_password_hash(DUMMY_HASH, pw)          # same time taken whether or not the name exists
            flash("Wrong ID or password.", "error")
        elif u["is_active"] != "Y":
            flash("This account is switched off. Ask an administrator or HR.", "error")
        elif u["locked_minutes"]:
            flash("Too many wrong attempts. Try again in %d minute%s." % (u["locked_minutes"], "" if u["locked_minutes"] == 1 else "s"), "error")
        elif not u["password_hash"]:
            flash("No password has been set for this ID yet. Use \"First time? Set your password\" below.", "error")
        elif not check_password_hash(u["password_hash"], pw):
            ops.note_failed_login(conn, u["user_id"])
            left = ops.MAX_FAILED - (u["failed_attempts"] + 1)
            flash("Wrong ID or password." + (" %d attempt%s left." % (left, "" if left == 1 else "s") if 0 < left <= 3 else ""), "error")
            if left <= 0:
                flash("The account is locked for %d minutes." % ops.LOCK_MINUTES, "error")
        else:
            start_session(u)
            return redirect(url_for("home"))
    return render_template("login.html", title="Sign in")


@app.route("/first-login", methods=["GET", "POST"])
def first_login():
    """An employee's first sign-in: Employee ID + date of birth, then they choose their own password."""
    if request.method == "POST":
        conn = get_conn()
        ok, u = attempt(conn, ops.first_login, request.form.get("username", ""), request.form.get("dob", ""),
                        request.form.get("new", ""), request.form.get("again", ""), generate_password_hash)
        if ok:
            start_session(u)
            flash("Your password is set. From now on sign in with your Employee ID and this password.", "ok")
            return redirect(url_for("home"))
    return render_template("first_login.html", title="Set your password", f=request.form)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account/password", methods=["GET", "POST"])
@login_required
def password_page():
    if request.method == "POST":
        conn = get_conn()
        u = ops.get_user_by_name(conn, session["user"])
        new, again = request.form.get("new", ""), request.form.get("again", "")
        if not check_password_hash(u["password_hash"], request.form.get("current", "")):
            flash("The current password is wrong.", "error")
        elif new != again:
            flash("The two new passwords are not the same.", "error")
        else:
            ok, _ = attempt(conn, ops.set_password, session["user_id"], new, generate_password_hash)
            if ok:
                flash("Password changed.", "ok")
                return redirect(url_for("home"))
    return render_template("password.html", title="Change password")


# ------------------------------------------------------------------ pages
@app.route("/home")
@login_required
def home():
    if session.get("role") in SELF_ONLY_ROLES:      # a driver / paramedic only has their own leave and attendance
        return redirect(url_for("my_trips"))
    conn = get_conn()
    d = {"title": "Dashboard"}
    if role_in(OPS_ROLES):
        d["k"] = ops.kpis(conn)
        d["waiting"] = ops.list_calls(conn, status="Waiting", limit=6)
    if role_in(FLEET_ROLES):
        d["ins_alerts"] = ops.insurance_alerts(conn)
        d["maint_alerts"] = ops.maintenance_alerts(conn)
        d["equip_alerts"] = ops.equipment_alerts(conn)
        d["fleet"] = ops.fleet(conn)
    if role_in(HR_ROLES):
        d["staff_n"] = ops.staff_counts(conn)
        d["hr_n"] = ops.hr_summary(conn)
        d["pending_leaves"] = ops.list_leaves(conn, status="Pending", limit=5)
        d["lic_alerts"] = ops.license_alerts(conn)
    if role_in(ADMIN_ROLES):
        d["recent"] = ops.audit_entries(conn, limit=8)
    return render_template("dashboard.html", **d)


# ------------------------------------------------------------------ live board
@app.route("/board")
@roles_required(*OPS_ROLES)
def board_page():
    conn = get_conn()
    active = ops.list_dispatches(conn, active_only=True)
    cols = [(name, [d for d in active if d["status"] == name]) for name in ops.ACTIVE]
    stale = [d for d in active if (d["idle_min"] or 0) >= settings.STALE_MINUTES]
    unbilled = [d for d in ops.list_dispatches(conn, limit=100) if d["status"] == "Completed" and not d["billing_id"]]
    return render_template("board.html", title="Live board", waiting=ops.list_calls(conn, status="Waiting"), cols=cols,
                           free=ops.free_ambulances(conn), stale=stale, unbilled=unbilled)


# ------------------------------------------------------------------ calls
@app.route("/calls")
@roles_required(*OPS_ROLES)
def calls_page():
    status, q = request.args.get("status", ""), request.args.get("q", "").strip()
    return render_template("calls.html", title="Calls", calls=ops.list_calls(get_conn(), status, q), status=status, q=q)


@app.route("/calls/new", methods=["GET", "POST"])
@roles_required(*OPS_ROLES)
def call_new():
    conn = get_conn()
    if request.method == "POST":
        ok, call_id = attempt(conn, ops.create_call, form_data())
        if ok:
            if request.form.get("is_false_alarm"):
                flash("Call recorded as a false alarm. No ambulance is needed.", "ok")
                return redirect(url_for("call_detail", call_id=call_id))
            flash("Call recorded. Now send an ambulance.", "ok")
            return redirect(url_for("call_dispatch", call_id=call_id))
    return render_template("call_new.html", title="New emergency call", agents=ops.agents(conn),
                           f=request.form, default_agent=session.get("agent_id"))


@app.route("/calls/<int:call_id>")
@roles_required(*OPS_ROLES)
def call_detail(call_id):
    conn = get_conn()
    call = ops.get_call(conn, call_id)
    if call is None:
        abort(404)
    return render_template("call_detail.html", title="Call %d" % call_id, c=call,
                           dispatches=ops.list_dispatches(conn, call_id=call_id))


@app.route("/calls/<int:call_id>/dispatch", methods=["GET", "POST"])
@roles_required(*OPS_ROLES)
def call_dispatch(call_id):
    conn = get_conn()
    call = ops.get_call(conn, call_id)
    if call is None:
        abort(404)
    if request.method == "GET" and call["call_status"] in ("In progress", "Completed"):
        flash("An ambulance is already on this call." if call["call_status"] == "In progress" else "This call has already been completed.", "error")
        return redirect(url_for("call_detail", call_id=call_id))
    if request.method == "POST":
        ok, did = attempt(conn, ops.create_dispatch, call_id, form_data())
        if ok:
            flash("Ambulance dispatched.", "ok")
            return redirect(url_for("board_page"))
    return render_template("dispatch_new.html", title="Send an ambulance", c=call,
                           hospitals=ops.nearest_hospitals(conn, call["pick_lat"], call["pick_lon"]),
                           has_pos=call["pick_lat"] is not None,
                           ambulances=ops.ambulances_by_distance(conn, call["pick_lat"], call["pick_lon"]),
                           drivers=ops.free_drivers(conn), paramedics=ops.free_paramedics(conn), agents=ops.agents(conn),
                           default_agent=session.get("agent_id") or call["agent_id"], f=request.form)


# ------------------------------------------------------------------ dispatches
def trip_or_404(conn, dispatch_id):
    d = ops.get_dispatch(conn, dispatch_id)
    if d is None:
        abort(404)
    return d


def back_url(default):
    back = request.form.get("back", "") or request.args.get("back", "")
    return back if back.startswith("/") and not back.startswith("//") else default


@app.route("/dispatches")
@roles_required(*OPS_ROLES)
def dispatches_page():
    view = request.args.get("view", "active")
    return render_template("dispatches.html", title="Dispatches", view=view,
                           dispatches=ops.list_dispatches(get_conn(), active_only=(view != "all")))


@app.route("/dispatches/<int:dispatch_id>")
@roles_required(*OPS_ROLES)
def dispatch_detail(dispatch_id):
    conn = get_conn()
    d = trip_or_404(conn, dispatch_id)
    return render_template("dispatch_detail.html", title="Dispatch %d" % dispatch_id, d=d,
                           events=ops.timeline(conn, dispatch_id), patients=ops.list_patients(conn, dispatch_id=dispatch_id),
                           phone=ops.caller_phone(conn, d["customer_id"]) if d["customer_id"] else None)


@app.route("/dispatches/<int:dispatch_id>/destination", methods=["GET", "POST"])
@roles_required(*OPS_ROLES)
def dispatch_destination(dispatch_id):
    conn = get_conn()
    d = trip_or_404(conn, dispatch_id)
    if request.method == "POST":
        ok, msg = attempt(conn, ops.step_dispatch, dispatch_id, "tohospital", request.form)
        if ok:
            flash(msg, "ok")
            return redirect(back_url(url_for("dispatch_detail", dispatch_id=dispatch_id)))
    return render_template("destination.html", title="Choose the hospital", d=d,
                           hospitals=ops.nearest_hospitals(conn, d["pick_lat"], d["pick_lon"]), back=back_url(""))


@app.route("/dispatches/<int:dispatch_id>/<action>", methods=["POST"])
@roles_required(*OPS_ROLES)
def dispatch_step(dispatch_id, action):
    conn = get_conn()
    d = trip_or_404(conn, dispatch_id)
    if action == "tohospital":
        if d.get("hospital_id") is None:           # no hospital was chosen at dispatch: ask now
            return redirect(url_for("dispatch_destination", dispatch_id=dispatch_id, back=back_url("")))
        ok, msg = attempt(conn, ops.step_dispatch, dispatch_id, action)
        if ok:
            flash(msg, "ok")
            return redirect(back_url(url_for("dispatches_page")))
        # the chosen hospital has no free bed any more: let them pick another
        return redirect(url_for("dispatch_destination", dispatch_id=dispatch_id, back=back_url("")))
    ok, msg = attempt(conn, ops.step_dispatch, dispatch_id, action)
    if ok:
        flash(msg, "ok")
    return redirect(back_url(url_for("dispatches_page")))


# ------------------------------------------------------------------ hospitals
@app.route("/hospitals")
@roles_required(*OPS_ROLES)
def hospitals_page():
    return render_template("hospitals.html", title="Hospitals", hospitals=ops.hospital_directory(get_conn()))


@app.route("/hospitals/<int:hospital_id>/beds", methods=["POST"])
@roles_required(*OPS_ROLES)
def hospital_beds(hospital_id):
    ok, _ = attempt(get_conn(), ops.update_beds, hospital_id, request.form)
    if ok:
        flash("Free beds updated.", "ok")
    return redirect(url_for("hospitals_page"))


# ------------------------------------------------------------------ patients and vitals
@app.route("/patients")
@roles_required(*OPS_ROLES)
def patients_page():
    q = request.args.get("q", "").strip()
    return render_template("patients.html", title="Patients", patients=ops.list_patients(get_conn(), q), q=q)


@app.route("/dispatches/<int:dispatch_id>/patient/new", methods=["GET", "POST"])
@roles_required(*OPS_ROLES)
def patient_new(dispatch_id):
    conn = get_conn()
    d = ops.get_dispatch(conn, dispatch_id)
    if d is None:
        abort(404)
    if request.method == "POST":
        ok, pid = attempt(conn, ops.create_patient, dispatch_id, request.form)
        if ok:
            flash("Patient recorded. One bed was taken at the hospital.", "ok")
            return redirect(url_for("patient_detail", patient_id=pid))
    return render_template("patient_new.html", title="Add patient", d=d, f=request.form)


@app.route("/patients/<int:patient_id>")
@roles_required(*OPS_ROLES)
def patient_detail(patient_id):
    conn = get_conn()
    p = ops.get_patient(conn, patient_id)
    if p is None:
        abort(404)
    return render_template("patient_detail.html", title=p["name"], p=p, vitals=ops.vitals(conn, patient_id), f=request.form)


@app.route("/patients/<int:patient_id>/vitals", methods=["POST"])
@roles_required(*OPS_ROLES)
def vitals_add(patient_id):
    ok, _ = attempt(get_conn(), ops.add_vitals, patient_id, request.form)
    if ok:
        flash("Vitals recorded.", "ok")
    return redirect(url_for("patient_detail", patient_id=patient_id))


# ------------------------------------------------------------------ billing
@app.route("/bills")
@roles_required(*OPS_ROLES)
def bills_page():
    status = request.args.get("status", "")
    return render_template("bills.html", title="Billing", bills=ops.list_bills(get_conn(), status), status=status)


@app.route("/dispatches/<int:dispatch_id>/bill/new", methods=["GET", "POST"])
@roles_required("ADMIN")          # the driver / paramedic makes the bill (My trips); the Administrator can step in
def bill_new(dispatch_id):
    conn = get_conn()
    d = ops.get_dispatch(conn, dispatch_id)
    if d is None:
        abort(404)
    if request.method == "POST":
        ok, bid = attempt(conn, ops.create_bill, dispatch_id, form_data(), None)
        if ok:
            flash("Bill created.", "ok")
            return redirect(url_for("bill_detail", billing_id=bid))
    try:
        t = ops.tariff(conn, d["type_of_ambulance"])
    except ops.RuleError as e:
        flash(str(e), "error")
        t = None
    return render_template("bill_new.html", title="Create bill", d=d, t=t, f=request.form, suggested=ops.suggested_km(d))


@app.route("/bills/<int:billing_id>")
@roles_required(*OPS_ROLES)
def bill_detail(billing_id):
    conn = get_conn()
    b = ops.get_bill(conn, billing_id)
    if b is None:
        abort(404)
    return render_template("bill_detail.html", title="Receipt " + (b["receipt"] or ""), b=b,
                           d=ops.get_dispatch(conn, b["dispatch_id"]))


@app.route("/bills/<int:billing_id>/payment", methods=["POST"])
@roles_required("ADMIN")
def bill_payment(billing_id):
    ok, _ = attempt(get_conn(), ops.record_payment, billing_id, request.form)
    if ok:
        flash("Payment recorded.", "ok")
    return redirect(url_for("bill_detail", billing_id=billing_id))


# ------------------------------------------------------------------ ambulance status (agents) and the maintenance team's vehicle pages
@app.route("/ambulances")
@roles_required(*OPS_ROLES)
def ambulances_page():
    return render_template("ambulances.html", title="Ambulances", fleet=ops.fleet(get_conn()))


@app.route("/fleet")
@roles_required(*FLEET_ROLES)
def fleet_page():
    conn = get_conn()
    return render_template("fleet.html", title="Fleet", fleet=ops.fleet(conn), ins_alerts=ops.insurance_alerts(conn),
                           maint_alerts=ops.maintenance_alerts(conn), equip_alerts=ops.equipment_alerts(conn))


def ambulance_or_404(conn, ambulance_id):
    a = ops.get_ambulance(conn, ambulance_id)
    if a is None:
        abort(404)
    return a


@app.route("/fleet/<int:ambulance_id>")
@roles_required(*FLEET_ROLES)
def fleet_detail(ambulance_id):
    conn = get_conn()
    return render_template("fleet_detail.html", title="Ambulance", a=ambulance_or_404(conn, ambulance_id),
                           policies=ops.insurance_list(conn, ambulance_id), services=ops.service_list(conn, ambulance_id),
                           equipment=ops.equipment_list(conn, ambulance_id), pings=ops.recent_pings(conn, ambulance_id),
                           statuses=ops.FLEET_STATUSES, policy_types=ops.POLICY_TYPES, service_types=ops.SERVICE_TYPES,
                           conditions=ops.EQUIPMENT_CONDITIONS, today=datetime.date.today().isoformat(), f=request.form)


def fleet_action(ambulance_id, fn, message, *extra):
    conn = get_conn()
    ambulance_or_404(conn, ambulance_id)
    ok, _ = attempt(conn, fn, ambulance_id, request.form, *extra)
    if ok:
        flash(message, "ok")
    return redirect(url_for("fleet_detail", ambulance_id=ambulance_id) + "#" + message.split()[0].lower())


@app.route("/fleet/<int:ambulance_id>/status", methods=["POST"])
@roles_required(*FLEET_ROLES)
def fleet_update(ambulance_id):
    return fleet_action(ambulance_id, ops.update_ambulance, "Status updated.")


@app.route("/fleet/<int:ambulance_id>/insurance", methods=["POST"])
@roles_required(*FLEET_ROLES)
def fleet_insurance(ambulance_id):
    return fleet_action(ambulance_id, ops.add_insurance, "Insurance policy added.")


@app.route("/fleet/<int:ambulance_id>/service", methods=["POST"])
@roles_required(*FLEET_ROLES)
def fleet_service(ambulance_id):
    return fleet_action(ambulance_id, ops.add_service, "Service recorded.", session.get("full_name") or session.get("user"))


@app.route("/fleet/<int:ambulance_id>/equipment", methods=["POST"])
@roles_required(*FLEET_ROLES)
def fleet_equipment(ambulance_id):
    return fleet_action(ambulance_id, ops.add_equipment, "Equipment added.")


@app.route("/fleet/<int:ambulance_id>/equipment/<int:equipment_no>", methods=["POST"])
@roles_required(*FLEET_ROLES)
def fleet_equipment_condition(ambulance_id, equipment_no):
    conn = get_conn()
    ambulance_or_404(conn, ambulance_id)
    ok, _ = attempt(conn, ops.set_equipment_condition, ambulance_id, equipment_no, request.form)
    if ok:
        flash("Equipment condition updated.", "ok")
    return redirect(url_for("fleet_detail", ambulance_id=ambulance_id) + "#equipment")


# ------------------------------------------------------------------ HR: staff, attendance, leave
@app.route("/staff")
@roles_required(*HR_ROLES)
def staff_page():
    conn = get_conn()
    kind = request.args.get("type", "")
    people = [s for s in ops.staff(conn) if not kind or s["role"] == kind]
    return render_template("staff.html", title="Staff", staff=people, kind=kind, n=ops.staff_counts(conn),
                           lic_alerts=ops.license_alerts(conn))


@app.route("/staff/new", methods=["GET", "POST"])
@roles_required(*HR_ROLES)
def staff_new():
    conn = get_conn()
    if request.method == "POST":
        ok, hr_id = attempt(conn, ops.add_staff, request.form)
        if ok:
            if request.form.get("kind") == "Agent":
                flash("Agent added. Employee ID: %s. Agents share one login; they use their Employee ID to apply for leave (\"Apply for leave\"), and HR marks their attendance." % ops.emp_id(hr_id), "ok")
            else:
                flash("Employee added. Employee ID: %s. They sign in with \"First time? Set your password\" using this ID and their date of birth." % ops.emp_id(hr_id), "ok")
            return redirect(url_for("staff_detail", hr_id=hr_id))
    return render_template("staff_new.html", title="Add employee", kinds=ops.EMPLOYEE_KINDS, shifts=ops.AGENT_SHIFTS,
                           levels=ops.PARAMEDIC_LEVELS, ambulances=ops.ambulance_choices(conn),
                           kind=request.values.get("kind", "Agent"), f=request.form)


@app.route("/staff/<int:hr_id>")
@roles_required(*HR_ROLES)
def staff_detail(hr_id):
    conn = get_conn()
    p = ops.staff(conn, hr_id)
    if p is None:
        abort(404)
    return render_template("staff_detail.html", title=p["name"], p=p, login=ops.login_of(conn, hr_id), dob=ops.employee_dob(conn, hr_id),
                           emp_id=ops.emp_id(hr_id), counts=ops.attendance_counts(conn, hr_id),
                           history=ops.attendance_history(conn, hr_id), leaves=ops.list_leaves(conn, hr_id=hr_id, limit=10),
                           f=request.form)


@app.route("/staff/<int:hr_id>/hr", methods=["POST"])
@roles_required(*HR_ROLES)
def staff_hr_update(hr_id):
    ok, _ = attempt(get_conn(), ops.update_hr, hr_id, request.form)
    if ok:
        flash("HR record saved.", "ok")
    return redirect(url_for("staff_detail", hr_id=hr_id))


@app.route("/hr/attendance", methods=["GET", "POST"])
@roles_required(*HR_ROLES)
def attendance_page():
    conn = get_conn()
    raw = request.values.get("date") or datetime.date.today().isoformat()
    try:
        day = datetime.datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        flash("That date is not valid. Showing today.", "error")
        day = datetime.datetime.combine(datetime.date.today(), datetime.time())
    if request.method == "POST":
        ok, n = attempt(conn, ops.save_attendance, day, request.form)
        if ok:
            flash("Attendance saved for %d people." % n, "ok")
            return redirect(url_for("attendance_page", date=day.date().isoformat()))
    d = day.date()
    return render_template("hr_attendance.html", title="Attendance", day=d, sheet=ops.attendance_sheet(conn, day),
                           statuses=ops.ATTENDANCE_STATUSES, today=datetime.date.today(),
                           prev_day=(d - datetime.timedelta(days=1)).isoformat(), next_day=(d + datetime.timedelta(days=1)).isoformat())


@app.route("/hr/attendance/close", methods=["POST"])
@roles_required(*HR_ROLES)
def attendance_close():
    raw = request.form.get("date") or datetime.date.today().isoformat()
    try:
        day = datetime.datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        flash("That date is not valid.", "error")
        return redirect(url_for("attendance_page"))
    ok, res = attempt(get_conn(), ops.close_day, day)
    if ok:
        flash("Day closed: %d marked Absent, %d marked On Leave. Everybody else was already marked." % res, "ok")
    return redirect(url_for("attendance_page", date=day.date().isoformat()))


@app.route("/staff/<int:hr_id>/reset-login", methods=["POST"])
@roles_required(*HR_ROLES)
def staff_reset_login(hr_id):
    ok, _ = attempt(get_conn(), ops.reset_login, hr_id)
    if ok:
        flash("The password was cleared. At the next sign-in the employee chooses a new one with their Employee ID and date of birth.", "ok")
    return redirect(url_for("staff_detail", hr_id=hr_id))


@app.route("/hr/leaves")
@roles_required(*HR_ROLES)
def leaves_page():
    conn = get_conn()
    status = request.args.get("status", "")
    return render_template("hr_leaves.html", title="Leave", leaves=ops.list_leaves(conn, status), status=status,
                           people=ops.people_choices(conn), types=ops.LEAVE_TYPES, f=request.form)


@app.route("/hr/leaves/new", methods=["POST"])
@roles_required(*HR_ROLES)
def leave_new():
    conn = get_conn()
    ok, _ = attempt(conn, ops.apply_leave, request.form)
    if ok:
        flash("Leave request recorded. It is waiting for a decision.", "ok")
        return redirect(url_for("leaves_page"))
    return render_template("hr_leaves.html", title="Leave", leaves=ops.list_leaves(conn, ""), status="",
                           people=ops.people_choices(conn), types=ops.LEAVE_TYPES, f=request.form)


@app.route("/hr/leaves/<int:leave_id>/decide", methods=["POST"])
@roles_required(*HR_ROLES)
def leave_decide(leave_id):
    ok, d = attempt(get_conn(), ops.decide_leave, leave_id, request.form.get("decision", ""), session.get("user"))
    if ok:
        flash("Leave %s." % d.lower(), "ok")
    return redirect(back_url(url_for("leaves_page")))


# ------------------------------------------------------------------ an employee's own leave (agents, drivers, paramedics)
@app.route("/my/trips")
@roles_required(*SELF_ONLY_ROLES)
def my_trips():
    conn = get_conn()
    trips = ops.my_trips(conn, session["hr_id"]) if session.get("hr_id") else []
    prices = {t["ambulance_type"]: (float(t["base_fare"]), float(t["rate_per_km"]))
              for t in ops.rows(conn, "SELECT ambulance_type, base_fare, rate_per_km FROM tariff")}
    return render_template("my_trips.html", title="My trips", trips=trips, modes=settings.PAYMENT_MODES, prices=prices)


@app.route("/my/trips/<int:dispatch_id>/bill", methods=["POST"])
@roles_required(*SELF_ONLY_ROLES)
def my_trip_bill(dispatch_id):
    ok, msg = attempt(get_conn(), ops.crew_bill, session.get("hr_id"), dispatch_id, form_data())
    if ok:
        flash(msg, "ok")
    return redirect(url_for("my_trips"))


@app.route("/my/trips/<int:dispatch_id>/collect", methods=["POST"])
@roles_required(*SELF_ONLY_ROLES)
def my_trip_collect(dispatch_id):
    ok, msg = attempt(get_conn(), ops.crew_collect, session.get("hr_id"), dispatch_id, request.form)
    if ok:
        flash(msg, "ok")
    return redirect(url_for("my_trips"))


@app.route("/agent/leave", methods=["GET", "POST"])
@roles_required(*OPS_ROLES)
def agent_leave():
    """Agents share one login, so they identify themselves with their Employee ID; HR approves the request."""
    if request.method == "POST":
        ok, name = attempt(get_conn(), ops.agent_apply_leave, request.form)
        if ok:
            flash("Leave request saved for %s. It now waits for HR to approve it." % name, "ok")
            return redirect(url_for("agent_leave"))
    return render_template("agent_leave.html", title="Apply for leave", types=ops.LEAVE_TYPES, f=request.form)


def self_page(conn, hr_id):
    o = {}
    if hr_id:
        try:
            o = ops.my_leave_overview(conn, hr_id)
        except ops.RuleError as e:
            flash(str(e), "error")
            hr_id = None
    return render_template("my_leave.html", title="Leave and attendance", types=ops.LEAVE_TYPES, f=request.form, who=hr_id, **o)


@app.route("/my/leave", methods=["GET", "POST"])
@roles_required(*SELF_ROLES)
def my_leave():
    conn = get_conn()
    hr_id = session.get("hr_id")
    if request.method == "POST":
        if not hr_id:
            flash("Your login is not linked to an employee record. Ask HR.", "error")
        else:
            data = request.form.to_dict()
            data["hr_id"] = str(hr_id)              # always for the chosen person, whatever else the form says
            ok, _ = attempt(conn, ops.apply_leave, data)
            if ok:
                flash("Your leave request was sent to HR.", "ok")
                return redirect(url_for("my_leave"))
    return self_page(conn, hr_id)


@app.route("/my/attendance", methods=["POST"])
@roles_required(*SELF_ROLES)
def my_attendance():
    conn = get_conn()
    hr_id = session.get("hr_id")
    if not hr_id:
        flash("Your login is not linked to an employee record. Ask HR.", "error")
        return redirect(url_for("my_leave"))
    status = request.form.get("status", "")
    ok, _ = attempt(conn, ops.mark_my_attendance, hr_id, status)
    if ok:
        flash("You are marked %s for today." % status, "ok")
    return redirect(url_for("my_leave"))


@app.route("/my/leave/<int:leave_id>/cancel", methods=["POST"])
@roles_required(*SELF_ROLES)
def my_leave_cancel(leave_id):
    conn = get_conn()
    hr_id = session.get("hr_id")
    if hr_id:
        ok, _ = attempt(conn, ops.cancel_leave, leave_id, hr_id)
        if ok:
            flash("Your request was withdrawn.", "ok")
    else:
        flash("Your login is not linked to an employee record. Ask HR.", "error")
    return redirect(url_for("my_leave"))


# ------------------------------------------------------------------ audit trail (administrator)
@app.route("/audit")
@roles_required(*ADMIN_ROLES)
def audit_page():
    conn = get_conn()
    a = {k: request.args.get(k, "").strip() for k in ("user", "table", "action", "day_from", "day_to", "q")}
    entries = []
    try:
        entries = ops.audit_entries(conn, **a)
    except ops.RuleError as e:
        flash(str(e), "error")
    return render_template("audit.html", title="Audit log", entries=entries, a=a, users=ops.audit_users(conn),
                           tables=[(t.upper(), db.LABELS[t]) for t in db.TABLES] + [("APP_USER", "Users")], limit=300)


# ------------------------------------------------------------------ users (administrator)
@app.route("/users")
@roles_required(*ADMIN_ROLES)
def users_page():
    return render_template("users.html", title="Users", users=ops.list_users(get_conn()), roles=ROLE_NAMES)


@app.route("/users/new", methods=["GET", "POST"])
@roles_required(*ADMIN_ROLES)
def user_new():
    conn = get_conn()
    if request.method == "POST":
        ok, _ = attempt(conn, ops.create_user, request.form, generate_password_hash)
        if ok:
            flash("User created. Give them the username and the password, and ask them to change it.", "ok")
            return redirect(url_for("users_page"))
    return render_template("user_new.html", title="New user", roles=ops.CREATABLE_ROLES, f=request.form)


@app.route("/users/<int:user_id>/password", methods=["POST"])
@roles_required(*ADMIN_ROLES)
def user_password(user_id):
    ok, _ = attempt(get_conn(), ops.set_password, user_id, request.form.get("password", ""), generate_password_hash)
    if ok:
        flash("Password changed.", "ok")
    return redirect(url_for("users_page"))


@app.route("/users/<int:user_id>/active", methods=["POST"])
@roles_required(*ADMIN_ROLES)
def user_active(user_id):
    if user_id == session["user_id"]:
        flash("You cannot switch off your own account.", "error")
    else:
        make = request.form.get("active") == "Y"
        ok, _ = attempt(get_conn(), ops.set_user_active, user_id, make)
        if ok:
            flash("Account switched on." if make else "Account switched off.", "ok")
    return redirect(url_for("users_page"))


@app.route("/users/<int:user_id>/unlock", methods=["POST"])
@roles_required(*ADMIN_ROLES)
def user_unlock(user_id):
    ok, _ = attempt(get_conn(), ops.unlock_user, user_id)
    if ok:
        flash("Account unlocked.", "ok")
    return redirect(url_for("users_page"))


# ------------------------------------------------------------------ all tables (add / edit / delete)
@app.route("/t/<table>")
@login_required
@table_access
def list_page(table):
    conn = get_conn()
    m = db.meta(conn)[table]
    q = request.args.get("q", "").strip()
    rows = db.list_rows(conn, table, q)
    owners = None
    if table == "hr":   # show whose HR record each row is (the link lives in agent / driver / paramedic)
        owners = ops.hr_owners(conn)
        pk = [i for i, c in enumerate(m["cols"]) if c["key"] == "hr_id"][0]
        for r in rows:
            r["owner"] = owners.get(int(r["cells"][pk]))
    return render_template("list.html", title=m["label"], t=m, rows=rows, q=q, limit=db.MAX_ROWS, owners=owners)


def _form_page(table, m, mode, values, rid=None):
    return render_template("form.html", title=("Add " if mode == "new" else "Edit ") + m["label"],
                           t=m, mode=mode, values=values, rid=rid, opts=db.fk_options(get_conn(), table),
                           input_value=db.input_value)


@app.route("/t/<table>/new", methods=["GET", "POST"])
@login_required
@table_access
def new_page(table):
    conn = get_conn()
    m = db.meta(conn)[table]
    if request.method == "POST":
        try:
            db.insert_row(conn, table, request.form)
            flash("Saved.", "ok")
            return redirect(url_for("list_page", table=table))
        except db.FormError as e:
            flash(str(e), "error")
        except oracledb.DatabaseError as e:
            conn.rollback()
            flash(db.friendly_error(e), "error")
        return _form_page(table, m, "new", {c["key"]: request.form.get(c["key"], "") for c in m["cols"]})
    return _form_page(table, m, "new", {})


@app.route("/t/<table>/edit", methods=["GET", "POST"])
@login_required
@table_access
def edit_page(table):
    conn = get_conn()
    m = db.meta(conn)[table]
    rid = request.values.get("r", "")
    current = db.get_row(conn, table, rid)
    if current is None:
        abort(404)
    if request.method == "POST":
        try:
            db.update_row(conn, table, rid, request.form)
            flash("Changes saved.", "ok")
            return redirect(url_for("list_page", table=table))
        except db.FormError as e:
            flash(str(e), "error")
        except oracledb.DatabaseError as e:
            conn.rollback()
            flash(db.friendly_error(e), "error")
        typed = {c["key"]: request.form.get(c["key"], "") for c in m["cols"]}
        typed.update({c["key"]: db.input_value(current[c["key"]], c) for c in m["cols"] if c["name"] in m["pk"]})
        return _form_page(table, m, "edit", typed, rid)
    return _form_page(table, m, "edit", {c["key"]: db.input_value(current[c["key"]], c) for c in m["cols"]}, rid)


@app.route("/t/<table>/delete", methods=["POST"])
@login_required
@table_access
def delete_page(table):
    conn = get_conn()
    try:
        db.delete_row(conn, table, request.form.get("r", ""))
        flash("Record deleted.", "ok")
    except oracledb.DatabaseError as e:
        conn.rollback()
        flash(db.friendly_error(e), "error")
    return redirect(url_for("list_page", table=table))


if __name__ == "__main__":
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=False)
