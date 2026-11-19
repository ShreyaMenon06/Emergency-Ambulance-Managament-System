EMERGENCY AMBULANCE MANAGEMENT SYSTEM   (Oracle 11g XE database + Python/Flask web front end)
===================================================================================
database\  01_schema.sql, 02_sample_data.sql (+ upgrades)      frontend\ (this folder)

LOGINS
  Everybody signs in at the first page. DRIVERS and PARAMEDICS sign in with their EMPLOYEE ID (EMP + HR number,
  e.g. EMP004). Nobody gives them a password: at the FIRST sign-in they press "First time? Set your password", enter the
  Employee ID and their date of birth (as HR entered it) and choose their own password. From then on: Employee ID + that password.
    agent    -> SHARED login (agent_user): New call -> send ambulance -> trip status -> hospital/patient -> billing; ambulance status.
                Each form asks "Handled by agent" (the choice is remembered for the next form). HR marks agents' attendance and leave.
    driver / paramedic -> "My trips": the trips assigned to them (the agent updates the status). At the end of the trip THEY make the bill
                          (distance suggested from the map, Cash / Card / UPI, money received) and record any money collected later.
                          The agent only sees the bill status (Paid / Partial / Unpaid, or "Bill not made yet") on the Live board, Dispatches and Billing.
                          "Leave and attendance": mark own attendance (one tap: Mark present / Mark half day), apply for leave, see balance
  Shared role logins (created by setup_users.py):
  agent_user       / Agent@123    Calls, dispatch, bill status (all agents share it)
  hr_user          / Hr@12345     Staff (agents, drivers, paramedics): salary, attendance, leave, leave policy, staff insurance
  maintenance_user / Maint@123    Vehicles: insurance policies, service history, equipment checks, expiry alerts
  admin_user       / Admin@123    Everything + Users page + Audit log (who changed what, when, old/new values)
  5 wrong passwords lock a login for 15 minutes. HR can clear a forgotten password (Staff > the employee > Clear password) (the employee
  then sets a new one the same way).

STEP 1  DATABASE  (already loaded into schema SHREYA if I ran it for you; skip to STEP 2.  WARNING: 01_schema.sql DELETES the old tables and data)
  Open SQL*Plus and connect as your new schema (your workspace schema, SHREYA):
      connect / as sysdba
      ALTER USER shreya IDENTIFIED BY YourPassword1;
      GRANT CONNECT, RESOURCE, CREATE VIEW TO shreya;
      connect shreya/YourPassword1
  Copy the two .sql files to C:\ and run:
      SET DEFINE OFF
      @C:\01_schema.sql
      @C:\02_sample_data.sql
      COMMIT;
  Any line starting with "Warning: ... compiled with errors", or ORA-, must be sent to me as a screenshot.

STEP 2  FRONT END (in a Command Prompt, inside this folder; always py -3.12)
  py -3.12 -m pip install -r requirements.txt
  (config.py comes with this folder; your Oracle password goes in D:\config.py next to the folder, see SETTINGS below)
  py -3.12 check_db.py      -> "All tables found"
  py -3.12 setup_users.py   -> creates admin_user, agent_user, hr_user, maintenance_user and lists the Employee ID of every driver and paramedic
  py -3.12 diag.py          -> every line must say OK (send a screenshot of any FAIL)

SETTINGS (config.py): comes with the folder. To use different Oracle details, put your own config.py NEXT TO the frontend folder (e.g. D:\config.py); it wins over the one inside.

NEW IN THIS VERSION
  - Agents apply for leave on the shared agent login: menu "Apply for leave" -> Employee ID (EMP + HR number, shown on Staff) + dates. The request waits for HR (Leave page) to approve.
  - py -3.12 clear_data.py deletes ALL data (asks you to type DELETE ALL first), then adds 12 ambulances and 10 hospitals only. Kept: table structure, price list (tariff), admin_user / agent_user / hr_user / maintenance_user.
  - NEAREST HOSPITAL: on a new call the agent picks the Area (or it is read from the address, e.g. "Hebbal Flyover"). When sending the ambulance, the
    hospitals are listed nearest first (km, free beds) and the nearest one with a free bed is pre-selected; the choice is saved on the dispatch and the
    "Heading to hospital" step uses it (it can still be changed there if that hospital fills up). Areas are listed in settings.py (AREAS); hospital
    positions are the Latitude / Longitude of the Hospital records. New columns: HOSPITAL.LATITUDE, LONGITUDE; EMERGENCY_CALL.PICK_LAT, PICK_LON.
  - BILLING BY THE CREW: the driver / paramedic makes the bill under My trips (BILLING.BILLED_BY = their HR id); if the call had no caller, they enter the
    payer's name and phone, which is saved as a customer and linked to the call. Agents see the status only; only the Administrator can also make a bill.
  - NO INSURANCE PAYMENT: payment mode is Cash, Card or UPI only (BILLING.PAYMENT_MODE check). BILLING.INSURANCE_STATUS is removed.
    Old 'Insurance' bills become 'Card'.
  - New call form: optional Street / City / State / Pincode of the caller, saved on the CUSTOMER row (a known caller only gets empty parts filled).
  - The ambulance's CURRENT_LOCATION now follows the trip (scene address, then the hospital).
  - FIRST NORMAL FORM: no table has a list or comma-separated column any more. Phone numbers, e-mails, allergies and languages are rows of their
    own tables (CUSTOMER_PHONE, CUSTOMER_EMAIL, HOSPITAL_PHONE, PATIENT_ALLERGY, AGENT_LANGUAGE), so they show in APEX and can be queried with
    a plain join. upgrade_db.py copies your existing values across first. 27 tables now.
  - Staff on approved leave, or marked On Leave / Absent today, are not offered for dispatch (drivers, paramedics) or as the agent on a form.
  - Attendance (drivers and paramedics): signed in with their own password, under "Leave and attendance" they press Mark present or Mark half day
    (once a day; HR corrects anything else). HR marks AGENTS' attendance on HR > Attendance. HR, Maintenance, Admin and Agents use shared role logins.
  - Only agents enter trip status; the crew make the bills. Any agent can update any trip, so a free agent covers one who is on a call.
  - Live board: a trip with no update for STALE_MINUTES (settings.py, 15) turns red and shows the driver's and paramedic's phone numbers to ring;
    a banner lists completed trips where the crew has not made the bill.
  - Every driver and paramedic has their own login, made automatically when they are added (Staff > "+ Add employee", or any other way:
    database triggers create it). The Employee ID is shown after saving and on the Staff page.
  - HR > Attendance: drivers and paramedics mark themselves (time saved), HR marks agents; "Close the day" marks everybody still unmarked as Absent, or On Leave
    when an approved leave covers the day. A person on approved leave cannot mark Present.
  - Users page (administrator) is only for administrator / HR / maintenance logins.
  - CREWS: every ambulance has its own driver and paramedic (DRIVER.AMBULANCE_ID and PARAMEDIC.AMBULANCE_ID = "usual ambulance", set in Staff > + Add employee or
    Records > Driver / Paramedic > Edit). On "Send an ambulance" the free ambulances are listed closest to the pick-up first (km; the position is the latest
    location ping, or the area in its Current location, e.g. "Whitefield") and the nearest is pre-selected; picking an ambulance fills in its driver and paramedic.
    If one of them is on leave, absent or busy they are not in the list, so choose a substitute. New column for old databases: py -3.12 upgrade_db.py (upgrade 10).
  - Upgrade of an existing database:  py -3.12 upgrade_db.py   (safe to run again: recreates APP_USER with the new login columns only if that
    was not done yet, creates the logins of drivers and paramedics, makes agents share one login, adds HR_ATTENDANCE.CHECK_IN and DRIVER.AMBULANCE_ID, rebuilds the audit triggers,
    creates admin_user / hr_user / maintenance_user). A brand-new 01_schema.sql already has all this.
    database\upgrades\ (05, 07 to 11) hold the same changes as SQL.
  - New emergency call: no "existing or new caller" question. Phone, first name and last name are all optional; a known phone
    number finds the caller, otherwise a caller is saved from what was typed (nothing typed = no caller).
  - Staff > "+ Add employee": adds an agent, driver or paramedic with salary, leave and insurance in one form.
  - Paramedics now have a phone number (database\upgrades\03_upgrade_paramedic_phone.sql adds it to a database created earlier;
    a brand-new 01_schema.sql already includes it, so 03 is then not needed).
  - Dispatching: the form asks which agent is handling the call; the audit log records the login that acted (agent_user or the admin).

RUN    py -3.12 app.py     then open http://127.0.0.1:5000

IF check_db.py FAILS
 - DPI-1050: py -3.12 -m pip install oracledb==2.5.1
 - DPI-1047: set ORACLE_CLIENT_DIR in config.py (folder containing oci.dll)
 - ORA-01017: wrong DB_USER / DB_PASSWORD   - ORA-12541/12514: database service not running or DB_DSN wrong
