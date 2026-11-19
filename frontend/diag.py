"""py -3.12 diag.py  - tests every page's database work and says which one fails."""
import traceback

import db

conn = db.connect()
bad = 0
for t in db.TABLES:
    step = "structure"
    try:
        m = db.meta(conn)[t]
        step = "list"
        rows = db.list_rows(conn, t, "")
        step = "search"
        db.list_rows(conn, t, "a")
        step = "edit form"
        if rows:
            db.get_row(conn, t, rows[0]["rid"])
        step = "drop-downs"
        db.fk_options(conn, t)
        print("OK    %-28s %d rows" % (t, len(rows)))
    except Exception as e:
        bad += 1
        print("FAIL  %-28s at %-10s %s" % (t, step, str(e).strip().splitlines()[0]))

# ---- the workflow screens (read-only: nothing is changed) ----
import ops
def first(rows, key):
    return rows[0][key] if rows else 0
checks = [
    ("dashboard numbers", lambda: ops.kpis(conn)),
    ("insurance alerts", lambda: ops.insurance_alerts(conn)),
    ("maintenance alerts", lambda: ops.maintenance_alerts(conn)),
    ("licence alerts", lambda: ops.license_alerts(conn)),
    ("staff counts", lambda: ops.staff_counts(conn)),
    ("calls list", lambda: ops.list_calls(conn, "", "")),
    ("calls waiting", lambda: ops.list_calls(conn, "Waiting", "")),
    ("one call", lambda: ops.get_call(conn, first(ops.list_calls(conn, "", ""), "call_id"))),
    ("agents", lambda: ops.agents(conn)),
    ("customers", lambda: ops.customers(conn)),
    ("dispatches", lambda: ops.list_dispatches(conn)),
    ("one dispatch", lambda: ops.get_dispatch(conn, first(ops.list_dispatches(conn), "dispatch_id"))),
    ("free ambulances", lambda: ops.free_ambulances(conn)),
    ("free drivers", lambda: ops.free_drivers(conn)),
    ("free paramedics", lambda: ops.free_paramedics(conn)),
    ("patients", lambda: ops.list_patients(conn, "")),
    ("one patient", lambda: ops.get_patient(conn, first(ops.list_patients(conn, ""), "patient_id"))),
    ("hospitals", lambda: ops.hospitals(conn)),
    ("hospital directory", lambda: ops.hospital_directory(conn)),
    ("dispatch history", lambda: ops.timeline(conn, first(ops.list_dispatches(conn), "dispatch_id"))),
    ("price list (tariff)", lambda: ops.tariff(conn, "ALS") or []),
    ("equipment alerts", lambda: ops.equipment_alerts(conn)),
    ("users", lambda: ops.list_users(conn)),
    ("sign-in lookup", lambda: ops.get_user_by_name(conn, "admin_user") or []),
    ("vitals", lambda: ops.vitals(conn, first(ops.list_patients(conn, ""), "patient_id"))),
    ("nearest hospital", lambda: ops.nearest_hospitals(conn, 12.97, 77.6)),
    ("bills", lambda: ops.list_bills(conn, "")),
    ("one bill", lambda: ops.get_bill(conn, first(ops.list_bills(conn, ""), "billing_id"))),
    ("fleet board", lambda: ops.fleet(conn)),
    ("staff list", lambda: ops.staff(conn)),
    ("HR summary", lambda: ops.hr_summary(conn)),
    ("people for leave list", lambda: ops.people_choices(conn)),
    ("attendance sheet", lambda: ops.attendance_sheet(conn, __import__("datetime").datetime.now())),
    ("leave requests", lambda: ops.list_leaves(conn)),
    ("one staff profile", lambda: ops.staff(conn, 1) or []),
    ("vehicle: insurance", lambda: ops.insurance_list(conn, 1)),
    ("vehicle: services", lambda: ops.service_list(conn, 1)),
    ("vehicle: equipment", lambda: ops.equipment_list(conn, 1)),
    ("vehicle: GPS pings", lambda: ops.recent_pings(conn, 1)),
    ("audit log", lambda: ops.audit_entries(conn, limit=20)),
    ("audit filter lists", lambda: ops.audit_users(conn)),
    ("HR owners", lambda: list(ops.hr_owners(conn))),
]
print()
for name, fn in checks:
    try:
        r = fn()
        print("OK    %-28s %s" % (name, ("%d rows" % len(r)) if isinstance(r, list) else "fine"))
    except Exception as e:
        bad += 1
        print("FAIL  %-28s %s" % (name, str(e).strip().splitlines()[0]))
conn.rollback()
print("\nEverything works." if not bad else "\n%d check(s) failed - send me a screenshot of this screen." % bad)
