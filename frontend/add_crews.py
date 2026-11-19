"""py -3.12 add_crews.py  - adds staff so that every ambulance has its own crew: 12 drivers and 12 paramedics (one pair per ambulance,
ambulance 1 gets driver 1 and paramedic 1, and so on) and 3 call-centre agents (Day, Evening, Night).
Nothing is deleted. Anyone already in the system (same Aadhar number) is skipped, so it is safe to run again.
Run  py -3.12 upgrade_db.py  first (it adds DRIVER.AMBULANCE_ID). Run clear_data.py first if you want the ambulances (it adds 12).
Employee IDs are printed at the end: drivers and paramedics choose their own password at "First time? Set your password"
(Employee ID + the date of birth shown here); agents share the agent_user login."""
import db
import ops

DRIVERS = [  # first, last, dob, experience years
    ("Manoj", "Gowda", "1989-04-12", 12), ("Imran", "Pasha", "1990-08-23", 10), ("Suresh", "Naik", "1985-01-30", 15),
    ("Prakash", "Kumar", "1993-12-09", 8), ("Ramesh", "Reddy", "1988-03-17", 13), ("Venkatesh", "Murthy", "1991-06-25", 9),
    ("Faiz", "Ahmed", "1992-11-02", 7), ("Gopal", "Shetty", "1986-09-14", 14), ("Mahesh", "Babu", "1994-02-20", 6),
    ("Arjun", "Hegde", "1990-12-05", 10), ("Santosh", "Patil", "1987-07-19", 13), ("Kiran", "Rao", "1995-05-08", 5),
]
PARAMEDICS = [  # first, last, dob, level
    ("Divya", "Rao", "1993-09-30", "Advanced"), ("Nikhil", "Joshi", "1996-05-18", "Basic"), ("Sneha", "Pillai", "1994-03-02", "Intermediate"),
    ("Arun", "Menon", "1991-07-14", "Advanced"), ("Pooja", "Nair", "1995-01-22", "Intermediate"), ("Rahul", "Verma", "1993-10-11", "Basic"),
    ("Meera", "Iyer", "1992-04-27", "Advanced"), ("Vikram", "Singh", "1990-08-06", "Intermediate"), ("Anjali", "Das", "1996-12-15", "Basic"),
    ("Sandeep", "Kamath", "1991-02-09", "Advanced"), ("Lakshmi", "Bhat", "1994-06-30", "Intermediate"), ("Tarun", "Shah", "1997-03-21", "Basic"),
]
AGENTS = [  # first, last, dob, shift, languages
    ("Asha", "Krishnan", "1996-02-14", "Day", "English, Kannada, Hindi"),
    ("Bala", "Subramanian", "1994-09-03", "Evening", "English, Tamil, Kannada"),
    ("Chitra", "Reddy", "1995-11-28", "Night", "English, Telugu, Hindi"),
]
STREETS = ["Jayanagar", "Indiranagar", "Koramangala", "Malleshwaram", "Whitefield", "Hebbal", "BTM Layout", "HSR Layout", "Rajajinagar",
           "Marathahalli", "Yelahanka", "Banashankari"]


def person(n, first, last, dob, kind, salary):
    return {"kind": kind, "first_name": first, "last_name": last, "dob": dob, "date_of_joining": "2024-%02d-01" % (n % 12 + 1),
            "aadhar": "5555%s%04d" % ({"Agent": "1111", "Driver": "2222", "Paramedic": "3333"}[kind], n),
            "street": "%d %s" % (10 + n, STREETS[n % len(STREETS)]), "city": "Bengaluru", "state": "Karnataka", "pincode": "5600%02d" % (10 + n),
            "phone_no": "98451%05d" % ({"Agent": 30000, "Driver": 10000, "Paramedic": 20000}[kind] + n),
            "salary": str(salary), "annual_leave_days": "24", "leave_policy": "24 days per year"}


def main(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM user_tab_columns WHERE table_name = 'DRIVER' AND column_name = 'AMBULANCE_ID'")
    if not cur.fetchone()[0]:
        print("The database is not upgraded yet. Run  py -3.12 upgrade_db.py  first, then this again.")
        return 1
    cur.execute("SELECT ambulance_id FROM ambulance ORDER BY ambulance_id")
    ambs = [r[0] for r in cur.fetchall()]
    if not ambs:
        print("There are no ambulances yet. Run clear_data.py (it adds 12) or add ambulances first, then this again.")
        return 1
    people = []
    for n, (f, l, dob, exp) in enumerate(DRIVERS):
        p = person(n, f, l, dob, "Driver", 25000 + 500 * exp)
        p.update(license_no="KA01%d2019%07d" % (n % 9 + 1, 1234500 + n), license_expiry="2030-%02d-28" % (n % 12 + 1), driving_experience=str(exp))
        if n < len(ambs):
            p["ambulance_id"] = str(ambs[n])
        people.append(p)
    for n, (f, l, dob, level) in enumerate(PARAMEDICS):
        p = person(n, f, l, dob, "Paramedic", {"Basic": 28000, "Intermediate": 33000, "Advanced": 40000}[level])
        p.update(certification_no="PM-2024-%04d" % (n + 1), certification_level=level)
        if n < len(ambs):
            p["ambulance_id"] = str(ambs[n])
        people.append(p)
    for n, (f, l, dob, shift, langs) in enumerate(AGENTS):
        p = person(n, f, l, dob, "Agent", 27000)
        p.update(shift=shift, languages=langs, agent_role="Agent")
        people.append(p)
    added = []
    for p in people:
        cur.execute("SELECT COUNT(*) FROM (SELECT aadhar FROM driver UNION ALL SELECT aadhar FROM paramedic UNION ALL SELECT aadhar FROM call_center_agent) WHERE aadhar = :a", a=p["aadhar"])
        if cur.fetchone()[0]:
            print("skipped  (already there)", p["first_name"], p["last_name"])
            continue
        try:
            hr_id = ops.add_staff(conn, p)
        except Exception as e:
            conn.rollback()
            print("FAILED   ", p["first_name"], p["last_name"], "-", e)
            return 1
        added.append((ops.emp_id(hr_id), p["kind"], p["first_name"] + " " + p["last_name"], p["dob"], p.get("ambulance_id")))
    cur.execute("SELECT ambulance_id, vehicle_no FROM ambulance")
    veh = dict(cur.fetchall())
    print()
    print("%-9s %-10s %-22s %-12s %s" % ("Employee", "Role", "Name", "Born", "Ambulance"))
    for e, kind, name, dob, amb in added:
        print("%-9s %-10s %-22s %-12s %s" % (e, kind, name, dob, veh.get(int(amb), "") if amb else ""))
    print("\nAdded %d employees. Drivers and paramedics: sign in page > 'First time? Set your password' with the Employee ID and the date of birth above." % len(added))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(db.connect("add_crews")))
