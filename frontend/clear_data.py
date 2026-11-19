"""py -3.12 clear_data.py  - deletes ALL the data (calls, dispatches, patients, bills, staff, vehicles, hospitals, customers, history)
so you can enter your own, and then adds a set of ambulances and hospitals to start with. Kept: the table structure, the price list (TARIFF) and the logins admin_user, agent_user, hr_user, maintenance_user.
The logins of drivers and paramedics go with their staff records. Numbering (ids, receipts) starts again at 1.
Everything is done in one go: if anything fails, nothing is deleted."""
import db

# children first, so that no foreign key blocks a delete
ORDER = ["billing", "patient_vitals_log", "patient_allergy", "patient", "dispatch_status_log", "dispatch", "emergency_call",
         "customer_phone", "customer_email", "customer", "location_log", "ambulance_equipment", "ambulance_maintenance_log",
         "ambulance_insurance", "paramedic", "driver", "hospital_phone", "hospital", "agent_language", "call_center_agent",
         "hr_attendance", "hr_leave", "APP_USER_STAFF", "hr", "ambulance"]
KEEP_SEQ = ("SEQ_APP_USER", "SEQ_TARIFF")

# What is added afterwards (nothing else): 12 ambulances and 10 hospitals. Edit the lists if you like.
# (model, type, vehicle_no, manufacture_year, current_location) - the type must be in the price list (ALS, BLS, ICU)
AMBULANCES = [
    ("Force Traveller", "BLS", "KA01AB1001", 2022, "MG Road, Bengaluru"),
    ("Tata Winger", "BLS", "KA01AB1002", 2021, "Indiranagar, Bengaluru"),
    ("Mahindra Bolero", "BLS", "KA02CD2003", 2023, "Jayanagar, Bengaluru"),
    ("Force Traveller", "ALS", "KA02CD2004", 2022, "Hebbal, Bengaluru"),
    ("Tata Winger", "ALS", "KA03EF3005", 2023, "Whitefield, Bengaluru"),
    ("Mahindra Bolero", "ALS", "KA03EF3006", 2021, "Koramangala, Bengaluru"),
    ("Force Traveller", "ICU", "KA04GH4007", 2023, "Bannerghatta Road, Bengaluru"),
    ("Tata Winger", "ICU", "KA04GH4008", 2022, "Frazer Town, Bengaluru"),
    ("Force Traveller", "BLS", "KA05JK5009", 2020, "Malleshwaram, Bengaluru"),
    ("Mahindra Bolero", "BLS", "KA05JK5010", 2022, "Yelahanka, Bengaluru"),
    ("Tata Winger", "ALS", "KA05LM6011", 2024, "Electronic City, Bengaluru"),
    ("Force Traveller", "ICU", "KA05LM6012", 2024, "HSR Layout, Bengaluru"),
]
# (name, branch, street, pincode, free beds, latitude, longitude)
HOSPITALS = [
    ("City General Hospital", "Hosur Road", "5 Hosur Road", "560029", 20, 12.917, 77.623),
    ("Sunrise Medical Centre", "Whitefield", "22 ITPL Road", "560066", 15, 12.986, 77.738),
    ("Lakeside Hospital", "Bannerghatta", "154 Bannerghatta Road", "560076", 25, 12.895, 77.597),
    ("St Marys Hospital", "Indiranagar", "8 100 Feet Road", "560038", 10, 12.972, 77.641),
    ("Hebbal Care Hospital", "Hebbal", "14 Bellary Road", "560024", 18, 13.036, 77.597),
    ("Jayanagar Medical Centre", "Jayanagar", "30 4th Block", "560011", 12, 12.930, 77.584),
    ("Malleshwaram Community Hospital", "Malleshwaram", "9 Sampige Road", "560003", 8, 13.003, 77.571),
    ("Electronic City Hospital", "Electronic City", "77 Hosur Main Road", "560100", 14, 12.845, 77.660),
    ("Koramangala Trauma Centre", "Koramangala", "100 Feet Road", "560034", 16, 12.935, 77.624),
    ("Yelahanka General Hospital", "Yelahanka", "3 Ballari Road", "560064", 11, 13.101, 77.596),
]

conn = db.connect("clear_data")
cur = conn.cursor()
print("This will DELETE all data (staff, vehicles, hospitals, customers, calls, dispatches, patients, bills, history),")
print("then add 12 ambulances and 10 hospitals so that you can start straight away.")
print("Kept: the table structure, the price list (tariff) and the logins admin_user / agent_user / hr_user / maintenance_user.")
if input('Type DELETE ALL and press Enter to continue (anything else cancels): ').strip() != "DELETE ALL":
    print("Cancelled. Nothing was deleted.")
    raise SystemExit(0)
try:
    for t in ORDER:
        if t == "APP_USER_STAFF":
            cur.execute("DELETE FROM app_user WHERE hr_id IS NOT NULL")      # drivers' and paramedics' personal logins
            t = "app_user (driver / paramedic logins)"
        else:
            cur.execute("DELETE FROM " + t)
        print("  cleared %-40s %d rows" % (t, cur.rowcount))
    conn.commit()
except Exception as e:
    conn.rollback()
    print("\nFAILED - nothing was deleted:\n ", str(e).splitlines()[0])
    raise SystemExit(1)
try:        # a sequence can only be restarted by dropping it, which Oracle commits on its own, so this is the last step
    cur.execute("SELECT sequence_name FROM user_sequences WHERE sequence_name LIKE 'SEQ\\_%' ESCAPE '\\'")
    for (s,) in cur.fetchall():
        if s not in KEEP_SEQ:
            cur.execute("DROP SEQUENCE " + s)
            cur.execute("CREATE SEQUENCE %s START WITH 1 INCREMENT BY 1 NOCACHE" % s)
except Exception as e:
    print("\nThe data is deleted, but the numbering could not be restarted at 1:\n ", str(e).splitlines()[0])
try:        # the starting set: ambulances and hospitals only
    for model, typ, no, year, where in AMBULANCES:
        cur.execute("INSERT INTO ambulance (model, status, vehicle_no, type_of_ambulance, manufacture_year, current_location) "
                    "VALUES (:1, 'Available', :2, :3, :4, :5)", [model, no, typ, year, where])
    for name, branch, street, pin, beds, lat, lon in HOSPITALS:
        cur.execute("INSERT INTO hospital (hospital_name, branch_name, street, city, state, pincode, beds_available, latitude, longitude) "
                    "VALUES (:1, :2, :3, 'Bengaluru', 'Karnataka', :4, :5, :6, :7)", [name, branch, street, pin, beds, lat, lon])
    cur.execute("DELETE FROM audit_log")          # last, so that the history starts empty
    conn.commit()
    print("  added %d ambulances and %d hospitals" % (len(AMBULANCES), len(HOSPITALS)))
except Exception as e:
    conn.rollback()
    print("\nThe data is deleted, but the ambulances and hospitals could not be added:\n ", str(e).splitlines()[0])
    raise SystemExit(1)
print("\nDone. Only the ambulances and hospitals are filled in. Now enter your people:")
print("  1. Staff > + Add employee: the agents, drivers and paramedics (this makes their Employee IDs). Add at least one agent first.")
print("  2. Then work as normal: New call > send ambulance ...")
print("  (Hospital phones and ambulance insurance can be added under Records.)")
