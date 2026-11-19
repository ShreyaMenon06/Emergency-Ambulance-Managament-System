"""All Oracle access lives here. The page layouts are built from the database's own
data dictionary (USER_TAB_COLS, USER_CONSTRAINTS ...), so the 16 tables need no hand-written forms."""
import datetime
import decimal
import re

import oracledb

import config

# The tables of the ER diagram (16) plus the price list (TARIFF), in the order they are shown.
# APP_USER (logins) and DISPATCH_STATUS_LOG (history) are not here: they have their own pages.
TABLES = ["customer", "call_center_agent", "hr", "driver", "paramedic", "ambulance",
          "ambulance_insurance", "hospital", "emergency_call", "dispatch", "patient",
          "billing", "patient_vitals_log", "location_log", "ambulance_maintenance_log",
          "ambulance_equipment", "tariff", "hr_attendance", "hr_leave",
          "agent_language", "hospital_phone", "customer_phone", "customer_email", "patient_allergy"]

LABELS = {"customer": "Customer", "call_center_agent": "Agent", "hr": "HR", "driver": "Driver",
          "paramedic": "Paramedic", "ambulance": "Ambulance", "ambulance_insurance": "Insurance",
          "hospital": "Hospital", "emergency_call": "Call", "dispatch": "Dispatch",
          "patient": "Patient", "billing": "Billing", "patient_vitals_log": "Vitals",
          "location_log": "GPS Log", "ambulance_maintenance_log": "Maintenance log",
          "ambulance_equipment": "Equipment", "tariff": "Tariff",
          "hr_attendance": "Attendance", "hr_leave": "Leave",
          "agent_language": "Agent languages", "hospital_phone": "Hospital phones", "customer_phone": "Customer phones",
          "customer_email": "Customer e-mails", "patient_allergy": "Patient allergies"}

MAX_ROWS = 500

# Allowed values (the CHECK ... IN (...) rules of 01_schema.sql) -> drop-down lists in the forms
CHOICES = {("patient", "BLOOD_GROUP"): ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
           ("patient", "GENDER"): ["Male", "Female", "Other"],
           ("emergency_call", "IS_FALSE_ALARM"): ["Y", "N"],
           ("emergency_call", "URGENCY_LEVEL"): ["Critical", "High", "Medium", "Low"],
           ("billing", "PAYMENT_STATUS"): ["Paid", "Unpaid", "Partial"],
           ("billing", "PAYMENT_MODE"): ["Cash", "Card", "UPI"],
           ("ambulance", "STATUS"): ["Available", "On Duty", "Maintenance"],
           ("dispatch", "STATUS"): ["En Route", "At Scene", "To Hospital", "At Hospital", "Completed", "Cancelled"],
           ("call_center_agent", "SHIFT"): ["Day", "Evening", "Night"],
           ("call_center_agent", "IS_ACTIVE"): ["Y", "N"],
           ("driver", "IS_ACTIVE"): ["Y", "N"],
           ("paramedic", "IS_ACTIVE"): ["Y", "N"],
           ("hr_attendance", "STATUS"): ["Present", "Half Day", "Absent", "On Leave"],
           ("hr_leave", "LEAVE_TYPE"): ["Casual", "Sick", "Earned", "Unpaid"],
           ("hr_leave", "STATUS"): ["Pending", "Approved", "Rejected"],
           ("ambulance_insurance", "POLICY_TYPE"): ["Comprehensive", "Third Party"],
           ("ambulance_equipment", "EQUIPMENT_CONDITION"): ["Good", "Fair", "Needs Repair"]}


class FormError(Exception):
    """A value typed in a form could not be understood."""


_client_ready = False
_meta = None


def init_client():
    global _client_ready
    if _client_ready or not config.USE_THICK_MODE:
        return
    try:
        if config.ORACLE_CLIENT_DIR:
            oracledb.init_oracle_client(lib_dir=config.ORACLE_CLIENT_DIR)
        else:
            oracledb.init_oracle_client()
    except Exception as e:            # already started is fine
        if "already" not in str(e).lower():
            raise
    _client_ready = True


def connect(who=None):
    """Open the Oracle connection. `who` (the signed-in username) is stored on the connection so that database
    triggers can record who changed a dispatch."""
    init_client()
    conn = oracledb.connect(user=config.DB_USER, password=config.DB_PASSWORD, dsn=config.DB_DSN)
    if who:
        try:
            conn.client_identifier = who[:60]
        except Exception:
            pass
    return conn


# --------------------------------------------------------------------- metadata
def _kind(name, dtype, owner):
    if owner:
        return "list"                                    # VARRAY (multivalued attribute)
    if dtype in ("NUMBER", "FLOAT"):
        return "number"
    if dtype == "DATE":
        return "datetime" if name.endswith("_TIME") else "date"
    if dtype.startswith("TIMESTAMP"):
        return "datetime"
    return "text"


def meta(conn):
    """Read table structure once and keep it."""
    global _meta
    if _meta is not None:
        return _meta
    cur = conn.cursor()
    cur.execute("SELECT sequence_name FROM user_sequences")
    seqs = {r[0] for r in cur}
    out = {}
    for t in TABLES:
        T = t.upper()
        cur.execute("""SELECT column_name, data_type, data_type_owner, char_length, nullable, virtual_column
                       FROM user_tab_cols WHERE table_name = :t AND hidden_column = 'NO'
                       ORDER BY column_id""", t=T)
        cols = []
        for name, dtype, owner, clen, nullable, virt in cur.fetchall():
            cols.append({"name": name, "key": name.lower(), "label": name.replace("_", " ").title(),
                         "type": dtype, "kind": _kind(name, dtype, owner),
                         "required": nullable == "N", "virtual": virt == "YES",
                         "maxlen": clen or None, "choices": None, "fk": None})
        if not cols:
            raise RuntimeError("Table %s was not found in this schema. Did you run 01_schema.sql?" % T)
        cur.execute("""SELECT cc.column_name FROM user_constraints c
                       JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
                       WHERE c.table_name = :t AND c.constraint_type = 'P' ORDER BY cc.position""", t=T)
        pk = [r[0] for r in cur]
        cur.execute("""SELECT cc.column_name, rcc.table_name, rcc.column_name
                       FROM user_constraints c
                       JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
                       JOIN user_constraints rc ON rc.constraint_name = c.r_constraint_name
                       JOIN user_cons_columns rcc ON rcc.constraint_name = rc.constraint_name
                                                 AND rcc.position = cc.position
                       WHERE c.table_name = :t AND c.constraint_type = 'R'""", t=T)
        fks = {r[0]: (r[1], r[2]) for r in cur}
        for c in cols:
            c["fk"] = fks.get(c["name"])
            c["choices"] = CHOICES.get((t, c["name"]))
            if c["name"] in pk:
                c["pk"] = True
        out[t] = {"name": t, "label": LABELS[t], "cols": cols, "pk": pk,
                  "auto_pk": len(pk) == 1 and ("SEQ_" + T) in seqs}
    _meta = out
    return out


# --------------------------------------------------------------------- reading
def colsel(c):
    """SQL for one column. A list (VARRAY) column is turned into 'a, b, c' text by the database."""
    if c["kind"] == "list":
        return ('(SELECT LISTAGG(COLUMN_VALUE, \', \') WITHIN GROUP (ORDER BY COLUMN_VALUE) FROM TABLE(t."%s")) AS "%s"'
                % (c["name"], c["name"]))
    return 't."%s"' % c["name"]


def count(conn, t):
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM "%s"' % t.upper())
    return cur.fetchone()[0]


def list_rows(conn, t, q=""):
    m = meta(conn)[t]
    sel = ", ".join(colsel(c) for c in m["cols"])
    where, params = "", {}
    if q:
        parts = ['UPPER(TO_CHAR(t."%s")) LIKE :q' % c["name"] for c in m["cols"] if c["kind"] != "list"]
        where = " WHERE " + " OR ".join(parts)
        params["q"] = "%" + q.upper() + "%"
    order = ", ".join('"%s"' % p for p in m["pk"]) or "rid_"
    sql = ('SELECT * FROM (SELECT ROWIDTOCHAR(t.ROWID) AS rid_, %s FROM "%s" t%s ORDER BY %s) WHERE ROWNUM <= %d'
           % (sel, t.upper(), where, order, MAX_ROWS))
    cur = conn.cursor()
    cur.execute(sql, params)
    return [{"rid": r[0], "cells": list(r[1:])} for r in cur.fetchall()]


def get_row(conn, t, rid):
    m = meta(conn)[t]
    sel = ", ".join(colsel(c) for c in m["cols"])
    cur = conn.cursor()
    try:
        cur.execute('SELECT %s FROM "%s" t WHERE t.ROWID = CHARTOROWID(:r)' % (sel, t.upper()), r=rid)
    except oracledb.DatabaseError:
        return None
    r = cur.fetchone()
    return dict(zip([c["key"] for c in m["cols"]], r)) if r else None


def fk_options(conn, t):
    """For every foreign-key column: the existing parent keys (with a short label) for the drop-down list."""
    m = meta(conn)
    opts = {}
    cur = conn.cursor()
    for c in m[t]["cols"]:
        if not c["fk"] or c["virtual"]:
            continue
        ptable, pcol = c["fk"][0].lower(), c["fk"][1]
        pm = m.get(ptable)
        skip = {"AADHAR", "PINCODE", "STREET", "CITY", "STATE", "RECEIPT"}
        names = [x["name"] for x in pm["cols"]] if pm else []
        if "FIRST_NAME" in names and "LAST_NAME" in names:
            lab = ["FIRST_NAME", "LAST_NAME"]
        else:
            lab = [x["name"] for x in pm["cols"] if x["kind"] == "text" and x["name"] not in skip][:2] if pm else []
        sel = ", ".join(['"%s"' % pcol] + ['"%s"' % x for x in lab])
        cur.execute('SELECT %s FROM "%s" ORDER BY 1' % (sel, ptable.upper()))
        opts[c["key"]] = [(str(r[0]), " ".join(str(x) for x in r[1:] if x is not None))
                          for r in cur.fetchmany(MAX_ROWS)]
    return opts


# --------------------------------------------------------------------- writing
def parse_value(col, raw):
    k = col["kind"]
    try:
        if k == "number":
            n = decimal.Decimal(raw)
            if not n.is_finite():
                raise ValueError
            return n
        if k == "date":
            return datetime.datetime.strptime(raw, "%Y-%m-%d")
        if k == "datetime":
            for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.datetime.strptime(raw, f)
                except ValueError:
                    pass
            raise ValueError
        if k == "list":
            return [x.strip() for x in raw.split(",") if x.strip()]
    except (ValueError, decimal.InvalidOperation):
        raise FormError("%s: '%s' is not a valid value." % (col["label"], raw))
    return raw


def _value_sql(c, value, p, params):
    """SQL text for one value. Lists become  TYPE_NAME(:p_0, :p_1)  so no Oracle object handling is needed."""
    if c["kind"] != "list":
        params[p] = value
        return ":" + p
    marks = []
    for j, item in enumerate(value):
        params["%s_%d" % (p, j)] = item
        marks.append(":%s_%d" % (p, j))
    return "%s(%s)" % (c["type"], ", ".join(marks))


def insert_row(conn, t, form):
    m = meta(conn)[t]
    names, exprs, params = [], [], {}
    for i, c in enumerate(m["cols"]):
        if c["virtual"]:
            continue
        raw = (form.get(c["key"]) or "").strip()
        if raw == "":
            continue                                   # empty -> NULL (auto-numbered keys are filled by the trigger)
        value = parse_value(c, raw)
        if c["kind"] == "list" and not value:
            continue
        names.append('"%s"' % c["name"])
        exprs.append(_value_sql(c, value, "p%d" % i, params))
    if not names:
        raise FormError("Nothing to save: fill in at least one field.")
    cur = conn.cursor()
    cur.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (t.upper(), ", ".join(names), ", ".join(exprs)), params)
    conn.commit()


def update_row(conn, t, rid, form):
    m = meta(conn)[t]
    sets, params = [], {"rid_": rid}
    for i, c in enumerate(m["cols"]):
        if c["virtual"] or c["name"] in m["pk"]:
            continue
        raw = (form.get(c["key"]) or "").strip()
        value = parse_value(c, raw) if raw != "" else None
        if value is None or (c["kind"] == "list" and not value):
            sets.append('"%s" = NULL' % c["name"])
        else:
            sets.append('"%s" = %s' % (c["name"], _value_sql(c, value, "p%d" % i, params)))
    cur = conn.cursor()
    cur.execute('UPDATE "%s" SET %s WHERE ROWID = CHARTOROWID(:rid_)' % (t.upper(), ", ".join(sets)), params)
    conn.commit()


def delete_row(conn, t, rid):
    cur = conn.cursor()
    cur.execute('DELETE FROM "%s" WHERE ROWID = CHARTOROWID(:r)' % t.upper(), r=rid)
    conn.commit()


# --------------------------------------------------------------------- showing values
def num(v):
    s = format(v, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def show(v, col):
    """Value as text in a table cell."""
    if v is None:
        return ""
    if isinstance(v, oracledb.DbObject):
        return ", ".join(str(x) for x in v.aslist())
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d") if col["kind"] == "date" else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (int, float, decimal.Decimal)):
        return num(v)
    return str(v)


def input_value(v, col):
    """Value as text inside a form field."""
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d") if col["kind"] == "date" else v.strftime("%Y-%m-%dT%H:%M:%S")
    return show(v, col)


def friendly_error(e):
    """Turn an Oracle error into a short sentence a user can act on."""
    err = e.args[0] if e.args else e
    text = getattr(err, "message", None) or str(e)
    code = re.search(r"ORA-(\d{5})", text)
    code = code.group(1) if code else ""
    first = text.strip().splitlines()[0]
    if code.startswith("200") and len(code) == 5:                 # our RAISE_APPLICATION_ERROR rules
        return re.sub(r"^ORA-\d+:\s*", "", first)
    msgs = {"00001": "A record with the same unique value already exists (for example the same Aadhar, vehicle number or key).",
            "02290": "A value breaks a rule of the table (for example a date order, a range or an allowed list).",
            "02291": "The linked record does not exist. Choose an existing one from the list.",
            "02292": "This record is used by other records, so it cannot be deleted. Delete or change those first.",
            "01400": "A required field is empty.",
            "12899": "A value is too long for its field.",
            "01438": "A number has too many digits for its field.",
            "22909": "Too many items in a list field (phone, email or allergy).",
            "01722": "A number field has a value that is not a number.",
            "02296": "The change is not allowed by a rule on the table."}
    if code == "02290" and "CK_HOSP_BEDS" in text.upper():
        return "That hospital has no free bed."
    if code == "00001" and "UQ_ATTENDANCE" in text.upper():
        return "Attendance for this person is already recorded for that date."
    if code == "02290" and "CK_LEAVE_DATES" in text.upper():
        return "The last day of leave cannot be before the first day."
    if code == "02290" and "CK_BILL_PAID" in text.upper():
        return "The amount paid cannot be more than the bill total."
    base = msgs.get(code)
    return (base + "  [" + first + "]") if base else first
