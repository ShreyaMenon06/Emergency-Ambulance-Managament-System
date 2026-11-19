"""py -3.12 setup_users.py  - creates the shared role logins (administrator, agents, HR, maintenance) (run once, after 01_schema.sql and 02_sample_data.sql).
Drivers and paramedics do not need this: each gets a login automatically, with the Employee ID
(EMP + HR number, like EMP004). They choose their own password at their first sign-in. Passwords are stored as hashes, never as text."""
from werkzeug.security import generate_password_hash

import db
import ops

DEMO = [  # username, full name, role, password
    ("admin_user", "System Administrator", "ADMIN", "Admin@123"),
    ("agent_user", "Call-centre agents (shared)", "AGENT", "Agent@123"),
    ("hr_user", "HR officer", "HR", "Hr@12345"),
    ("maintenance_user", "Maintenance supervisor", "MAINTENANCE", "Maint@123"),
]


def main(conn=None):
    conn = conn or db.connect("setup_users")
    for username, full, role, pw in DEMO:
        if ops.get_user_by_name(conn, username):
            print("exists   ", username)
            continue
        ops.create_user(conn, {"username": username, "full_name": full, "user_role": role, "password": pw}, generate_password_hash)
        print("created  ", username, "  password:", pw, "  (", role, ")")
    try:
        people = ops.rows(conn, """SELECT u.username, u.full_name, u.user_role, u.password_hash, e.dob
                                   FROM app_user u JOIN (SELECT hr_id, dob FROM driver
                                                         UNION ALL SELECT hr_id, dob FROM paramedic) e ON e.hr_id = u.hr_id
                                   ORDER BY u.hr_id""")
    except Exception as e:
        print("Could not read the employee logins - did upgrade_db.py or 01_schema.sql run?", str(e).strip().splitlines()[0])
        raise SystemExit(1)
    print("\nEmployee logins (they choose their own password at the first sign-in with the Employee ID and date of birth):")
    for p in people:
        print("  %-7s %-26s %-10s born %s  %s" % (p["username"], p["full_name"], p["user_role"], p["dob"].strftime("%d-%m-%Y") if p["dob"] else "?",
                                              ("password set" if p["password_hash"] else "waiting for first sign-in")))
    print("\nDone. Sign in at http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
