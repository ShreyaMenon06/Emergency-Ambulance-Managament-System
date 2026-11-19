-- =====================================================================
-- Emergency Ambulance Management System : Oracle schema, version 3
-- The ER diagram (16 entities) plus what a real service needs:
--   TARIFF (price per ambulance type), APP_USER (the logins), DISPATCH_STATUS_LOG (trip history),
--   HR_ATTENDANCE and HR_LEAVE (daily attendance and leave requests), AUDIT_LOG (who changed what, and when).
-- Four logins: ADMIN, AGENT, HR, MAINTENANCE.   Oracle 11g compatible.
-- Run in SQL*Plus or APEX SQL Scripts, connected as the project schema.
-- Re-runnable: it first drops the earlier versions of these tables (ALL DATA IN THEM IS LOST),
-- then run 02_sample_data.sql, then  py -3.12 setup_users.py  (creates the logins).
-- =====================================================================

BEGIN
  FOR t IN (SELECT table_name FROM user_tables WHERE table_name IN (
    'AUDIT_LOG','HR_ATTENDANCE','HR_LEAVE','DISPATCH_STATUS_LOG','APP_USER','LOCATION_LOG','PATIENT_VITALS_LOG','AMBULANCE_MAINTENANCE_LOG',
    'AMBULANCE_EQUIPMENT','AMBULANCE_INSURANCE','AMBULANCE_DRIVER','AMBULANCE_HOSPITAL','DISPATCH_AMBULANCE',
    'DISPATCH_PARAMEDIC','CUSTOMER_EMAIL','CUSTOMER_PHONE','AGENT_PHONE','AGENT_LANGUAGE','HOSPITAL_PHONE',
    'PATIENT_PHONE','PATIENT_ALLERGY','DRIVER_PHONE','PARAMEDIC_PHONE',
    'BILLING','PATIENT','DISPATCH','EMERGENCY_CALL','CUSTOMER','PARAMEDIC','DRIVER',
    'HOSPITAL','AMBULANCE','TARIFF','CALL_CENTER_AGENT','HR'))
  LOOP
    EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS';
  END LOOP;
  FOR q IN (SELECT sequence_name FROM user_sequences WHERE sequence_name IN (
    'SEQ_HR','SEQ_CALL_CENTER_AGENT','SEQ_AMBULANCE','SEQ_HOSPITAL','SEQ_CUSTOMER',
    'SEQ_EMERGENCY_CALL','SEQ_DRIVER','SEQ_PARAMEDIC','SEQ_DISPATCH','SEQ_BILLING','SEQ_PATIENT',
    'SEQ_APP_USER','SEQ_DISPATCH_STATUS_LOG','SEQ_HR_ATTENDANCE','SEQ_HR_LEAVE','SEQ_AUDIT_LOG'))
  LOOP
    EXECUTE IMMEDIATE 'DROP SEQUENCE ' || q.sequence_name;
  END LOOP;
  FOR v IN (SELECT view_name FROM user_views WHERE view_name IN
    ('V_AGENT','V_DRIVER','V_PARAMEDIC','V_PATIENT','V_DISPATCH_OVERVIEW'))
  LOOP
    EXECUTE IMMEDIATE 'DROP VIEW ' || v.view_name;
  END LOOP;
  FOR y IN (SELECT type_name FROM user_types WHERE type_name IN ('PHONE_LIST','EMAIL_LIST','ALLERGY_LIST'))
  LOOP
    EXECUTE IMMEDIATE 'DROP TYPE ' || y.type_name || ' FORCE';
  END LOOP;
END;
/

-- Notation: composite attribute -> split into columns | multivalued attribute -> its own table (first normal form: every column holds ONE value)
--           derived -> virtual column / view / trigger | total participation -> NOT NULL foreign key
--           weak entity -> primary key = owner key + partial key

-- NEW: price list. The fare of a trip depends on the type of ambulance (total = base_fare + km x rate_per_km).
CREATE TABLE tariff (
  ambulance_type  VARCHAR2(30) PRIMARY KEY,
  description     VARCHAR2(120),
  base_fare       NUMBER(10,2) NOT NULL CHECK (base_fare >= 0),
  rate_per_km     NUMBER(8,2)  NOT NULL CHECK (rate_per_km >= 0)
);

-- HR looks after the staff: one HR record per person (agent, driver or paramedic). Salary is kept only here.
-- Attendance is no longer a single number: it is worked out from HR_ATTENDANCE (below).
CREATE TABLE hr (
  hr_id             NUMBER PRIMARY KEY,
  salary            NUMBER(10,2) CHECK (salary >= 0),
  annual_leave_days NUMBER(3) DEFAULT 24 NOT NULL CHECK (annual_leave_days >= 0),
  leave_policy      VARCHAR2(200),
  staff_insurance   VARCHAR2(100)
);

-- NEW: one row per person per day. Employees mark themselves (check_in = when); HR can correct and closes the day.
CREATE TABLE hr_attendance (
  attendance_id  NUMBER PRIMARY KEY,
  hr_id          NUMBER NOT NULL REFERENCES hr(hr_id) ON DELETE CASCADE,
  att_date       DATE NOT NULL,
  status         VARCHAR2(12) NOT NULL CHECK (status IN ('Present','Absent','Half Day','On Leave')),
  check_in       DATE,
  CONSTRAINT uq_attendance UNIQUE (hr_id, att_date)
);

-- NEW: leave requests. Approved days are counted against the person's annual_leave_days.
CREATE TABLE hr_leave (
  leave_id    NUMBER PRIMARY KEY,
  hr_id       NUMBER NOT NULL REFERENCES hr(hr_id) ON DELETE CASCADE,
  leave_type  VARCHAR2(10) NOT NULL CHECK (leave_type IN ('Casual','Sick','Earned','Unpaid')),
  start_date  DATE NOT NULL,
  end_date    DATE NOT NULL,
  reason      VARCHAR2(200),
  status      VARCHAR2(10) DEFAULT 'Pending' NOT NULL CHECK (status IN ('Pending','Approved','Rejected')),
  applied_on  DATE DEFAULT SYSDATE NOT NULL,
  decided_by  VARCHAR2(60),
  decided_on  DATE,
  CONSTRAINT ck_leave_dates CHECK (end_date >= start_date)
);

-- HR handles agent (1:1, agent total).  is_active = 'N' for someone who has left (kept for old records).
CREATE TABLE call_center_agent (
  agent_id         NUMBER PRIMARY KEY,
  first_name       VARCHAR2(50) NOT NULL,
  middle_name      VARCHAR2(50),
  last_name        VARCHAR2(50) NOT NULL,
  dob              DATE,
  aadhar           VARCHAR2(12) UNIQUE CHECK (REGEXP_LIKE(aadhar, '^[0-9]{12}$')),
  street           VARCHAR2(100),
  city             VARCHAR2(60),
  state            VARCHAR2(60),
  pincode          VARCHAR2(10) CHECK (REGEXP_LIKE(pincode, '^[0-9]{6}$')),
  phone_no         VARCHAR2(20),
  shift            VARCHAR2(30) CHECK (shift IN ('Day','Evening','Night')),
  agent_role       VARCHAR2(40),
  date_of_joining  DATE,
  is_active        CHAR(1) DEFAULT 'Y' NOT NULL CHECK (is_active IN ('Y','N')),
  hr_id            NUMBER NOT NULL UNIQUE REFERENCES hr(hr_id),
  CONSTRAINT ck_agent_join_age CHECK (date_of_joining >= ADD_MONTHS(dob, 216))   -- at least 18 on joining
);

CREATE TABLE ambulance (
  ambulance_id       NUMBER PRIMARY KEY,
  model              VARCHAR2(50),
  status             VARCHAR2(30) DEFAULT 'Available' NOT NULL CHECK (status IN ('Available','On Duty','Maintenance')),
  vehicle_no         VARCHAR2(20) NOT NULL UNIQUE,
  type_of_ambulance  VARCHAR2(30) NOT NULL REFERENCES tariff(ambulance_type),
  manufacture_year   NUMBER(4),
  current_location   VARCHAR2(200)
);

-- insured_by (ambulance 1:N insurance policy, policy total). Handled by Admin / Fleet Manager, not HR.
CREATE TABLE ambulance_insurance (
  policy_no     VARCHAR2(40) PRIMARY KEY,
  ambulance_id  NUMBER NOT NULL REFERENCES ambulance(ambulance_id) ON DELETE CASCADE,
  insurer       VARCHAR2(80),
  policy_type   VARCHAR2(30),
  start_date    DATE,
  expiry_date   DATE,
  premium       NUMBER(10,2) CHECK (premium >= 0),
  CONSTRAINT ck_ins_dates CHECK (expiry_date > start_date)
);

-- contacts (agent 1:N hospital); phone_no is multivalued: one row each in HOSPITAL_PHONE.
-- beds_available is confirmed by phone with the hospital and goes down by itself when a patient is taken there.
CREATE TABLE hospital (
  hospital_id      NUMBER PRIMARY KEY,
  hospital_name    VARCHAR2(120) NOT NULL,
  branch_name      VARCHAR2(80),
  street           VARCHAR2(100),
  city             VARCHAR2(60),
  state            VARCHAR2(60),
  pincode          VARCHAR2(10) CHECK (REGEXP_LIKE(pincode, '^[0-9]{6}$')),
  beds_available   NUMBER(5) DEFAULT 0 NOT NULL,
  beds_updated_on  DATE DEFAULT SYSDATE,
  latitude         NUMBER(9,6) CHECK (latitude BETWEEN -90 AND 90),      -- where the hospital is: the nearest one is offered at dispatch
  longitude        NUMBER(9,6) CHECK (longitude BETWEEN -180 AND 180),
  agent_id         NUMBER REFERENCES call_center_agent(agent_id),
  CONSTRAINT ck_hosp_beds CHECK (beds_available >= 0)
);

-- enters (agent 1:N customer, customer total)  and  notifies (hospital 1:N customer); phone_no, email are in CUSTOMER_PHONE / CUSTOMER_EMAIL
CREATE TABLE customer (
  customer_id  NUMBER PRIMARY KEY,
  first_name   VARCHAR2(50) NOT NULL,
  middle_name  VARCHAR2(50),
  last_name    VARCHAR2(50) NOT NULL,
  aadhar       VARCHAR2(12) UNIQUE CHECK (REGEXP_LIKE(aadhar, '^[0-9]{12}$')),
  street       VARCHAR2(100),
  city         VARCHAR2(60),
  state        VARCHAR2(60),
  pincode      VARCHAR2(10) CHECK (REGEXP_LIKE(pincode, '^[0-9]{6}$')),
  agent_id     NUMBER NOT NULL REFERENCES call_center_agent(agent_id),
  hospital_id  NUMBER REFERENCES hospital(hospital_id)
);

-- handled_by (agent 1:N emergency_call, call total)  and  calls (customer 1:N emergency_call, the caller)
CREATE TABLE emergency_call (
  call_id         NUMBER PRIMARY KEY,
  call_time       DATE DEFAULT SYSDATE NOT NULL,
  pick_location   VARCHAR2(200) NOT NULL,
  call_type       VARCHAR2(40) NOT NULL,
  is_false_alarm  CHAR(1) DEFAULT 'N' NOT NULL CHECK (is_false_alarm IN ('Y','N')),
  call_duration   NUMBER(6) CHECK (call_duration >= 0),
  urgency_level   VARCHAR2(20) NOT NULL CHECK (urgency_level IN ('Critical','High','Medium','Low')),
  description     VARCHAR2(400),
  pick_lat        NUMBER(9,6) CHECK (pick_lat BETWEEN -90 AND 90),       -- position of the pick-up area (from the Area chosen on the call)
  pick_lon        NUMBER(9,6) CHECK (pick_lon BETWEEN -180 AND 180),
  agent_id        NUMBER NOT NULL REFERENCES call_center_agent(agent_id),
  customer_id     NUMBER REFERENCES customer(customer_id)
);

-- HR handles driver (one HR record per driver, driver total)
CREATE TABLE driver (
  driver_id           NUMBER PRIMARY KEY,
  first_name          VARCHAR2(50) NOT NULL,
  middle_name         VARCHAR2(50),
  last_name           VARCHAR2(50) NOT NULL,
  dob                 DATE,
  aadhar              VARCHAR2(12) UNIQUE CHECK (REGEXP_LIKE(aadhar, '^[0-9]{12}$')),
  street              VARCHAR2(100),
  city                VARCHAR2(60),
  state               VARCHAR2(60),
  pincode             VARCHAR2(10) CHECK (REGEXP_LIKE(pincode, '^[0-9]{6}$')),
  phone_no            VARCHAR2(20),
  license_no          VARCHAR2(30) UNIQUE,
  license_expiry      DATE,
  driving_experience  NUMBER(3) CHECK (driving_experience >= 0),
  date_of_joining     DATE,
  is_active           CHAR(1) DEFAULT 'Y' NOT NULL CHECK (is_active IN ('Y','N')),
  hr_id               NUMBER NOT NULL UNIQUE REFERENCES hr(hr_id),
  ambulance_id        NUMBER REFERENCES ambulance(ambulance_id),     -- the driver's usual ambulance (crew)
  CONSTRAINT ck_driver_join_age CHECK (date_of_joining >= ADD_MONTHS(dob, 216))
);

-- HR handles paramedic (one HR record per paramedic, paramedic total)  and  attended_by (ambulance 1:N paramedic)
CREATE TABLE paramedic (
  paramedic_id         NUMBER PRIMARY KEY,
  first_name           VARCHAR2(50) NOT NULL,
  middle_name          VARCHAR2(50),
  last_name            VARCHAR2(50) NOT NULL,
  dob                  DATE,
  aadhar               VARCHAR2(12) UNIQUE CHECK (REGEXP_LIKE(aadhar, '^[0-9]{12}$')),
  street               VARCHAR2(100),
  city                 VARCHAR2(60),
  state                VARCHAR2(60),
  pincode              VARCHAR2(10) CHECK (REGEXP_LIKE(pincode, '^[0-9]{6}$')),
  phone_no             VARCHAR2(20),
  certification_no     VARCHAR2(30) UNIQUE,
  certification_level  VARCHAR2(30),
  date_of_joining      DATE,
  is_active            CHAR(1) DEFAULT 'Y' NOT NULL CHECK (is_active IN ('Y','N')),
  hr_id                NUMBER NOT NULL UNIQUE REFERENCES hr(hr_id),
  ambulance_id         NUMBER REFERENCES ambulance(ambulance_id),
  CONSTRAINT ck_paramedic_join_age CHECK (date_of_joining >= ADD_MONTHS(dob, 216))
);

-- initiates (agent 1:N dispatch), uses (ambulance 1:N dispatch), results_in (call 1:N dispatch),
-- drives (driver 1:N dispatch), attends (paramedic 1:N dispatch), goes_to (hospital 1:N dispatch).
-- Steps:  En Route -> At Scene -> To Hospital -> At Hospital -> Completed   (or Cancelled before leaving the scene)
CREATE TABLE dispatch (
  dispatch_id            NUMBER PRIMARY KEY,
  status                 VARCHAR2(30) DEFAULT 'En Route' NOT NULL
                         CHECK (status IN ('En Route','At Scene','To Hospital','At Hospital','Completed','Cancelled')),
  dispatch_time          DATE DEFAULT SYSDATE NOT NULL,
  arrival_time           DATE,
  hospital_arrival_time  DATE,
  -- derived attribute (minutes from dispatch to arrival)
  response_time          NUMBER GENERATED ALWAYS AS (ROUND((arrival_time - dispatch_time) * 1440, 2)) VIRTUAL,
  call_id                NUMBER NOT NULL REFERENCES emergency_call(call_id),
  agent_id               NUMBER NOT NULL REFERENCES call_center_agent(agent_id),
  ambulance_id           NUMBER NOT NULL REFERENCES ambulance(ambulance_id),
  driver_id              NUMBER NOT NULL REFERENCES driver(driver_id),
  paramedic_id           NUMBER REFERENCES paramedic(paramedic_id),
  hospital_id            NUMBER REFERENCES hospital(hospital_id),
  CONSTRAINT ck_dispatch_arrival CHECK (arrival_time >= dispatch_time),
  CONSTRAINT ck_dispatch_hospital CHECK (hospital_arrival_time >= arrival_time),
  CONSTRAINT ck_dispatch_dest CHECK (status NOT IN ('To Hospital','At Hospital') OR hospital_id IS NOT NULL)
);

-- transports (dispatch 1:N patient, patient total)  and  taken_to (hospital 1:N patient, patient total)
-- allergies are multivalued: one row each in PATIENT_ALLERGY
CREATE TABLE patient (
  patient_id       NUMBER PRIMARY KEY,
  first_name       VARCHAR2(50) NOT NULL,
  middle_name      VARCHAR2(50),
  last_name        VARCHAR2(50),
  dob              DATE,
  blood_group      VARCHAR2(5) CHECK (blood_group IN ('A+','A-','B+','B-','AB+','AB-','O+','O-')),
  gender           VARCHAR2(10) CHECK (gender IN ('Male','Female','Other')),
  chief_complaint  VARCHAR2(200),
  dispatch_id      NUMBER NOT NULL REFERENCES dispatch(dispatch_id),
  hospital_id      NUMBER NOT NULL REFERENCES hospital(hospital_id)
);

-- Multivalued attributes, one value per row (first normal form). Primary key = owner key + the value; rows go when the owner goes.
CREATE TABLE agent_language (
  agent_id  NUMBER NOT NULL REFERENCES call_center_agent(agent_id) ON DELETE CASCADE,
  language  VARCHAR2(40) NOT NULL,
  CONSTRAINT pk_agent_language PRIMARY KEY (agent_id, language)
);
CREATE TABLE hospital_phone (
  hospital_id  NUMBER NOT NULL REFERENCES hospital(hospital_id) ON DELETE CASCADE,
  phone_no     VARCHAR2(20) NOT NULL,
  CONSTRAINT pk_hospital_phone PRIMARY KEY (hospital_id, phone_no)
);
CREATE TABLE customer_phone (
  customer_id  NUMBER NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
  phone_no     VARCHAR2(20) NOT NULL,
  CONSTRAINT pk_customer_phone PRIMARY KEY (customer_id, phone_no)
);
CREATE TABLE customer_email (
  customer_id  NUMBER NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
  email        VARCHAR2(100) NOT NULL,
  CONSTRAINT pk_customer_email PRIMARY KEY (customer_id, email)
);
CREATE TABLE patient_allergy (
  patient_id  NUMBER NOT NULL REFERENCES patient(patient_id) ON DELETE CASCADE,
  allergy     VARCHAR2(60) NOT NULL,
  CONSTRAINT pk_patient_allergy PRIMARY KEY (patient_id, allergy)
);

-- pays (customer 1:N billing, billing total), notifies (agent 1:N billing), billed_for (dispatch 1:1 billing)
-- total_amount (derived in the diagram) = base_fare + distance_km x rate_per_km of the ambulance type (set by the application).
-- amount_paid is what has been received so far; payment_status is worked out from it by a trigger.
CREATE TABLE billing (
  billing_id        NUMBER PRIMARY KEY,
  payment_mode      VARCHAR2(30) CONSTRAINT ck_bill_mode CHECK (payment_mode IN ('Cash','Card','UPI')),
  bill_date         DATE DEFAULT SYSDATE NOT NULL,
  receipt           VARCHAR2(60) UNIQUE,
  total_amount      NUMBER(10,2) NOT NULL CHECK (total_amount >= 0),
  amount_paid       NUMBER(10,2) DEFAULT 0 NOT NULL CHECK (amount_paid >= 0),
  distance_km       NUMBER(7,2) CHECK (distance_km >= 0),
  base_fare         NUMBER(10,2) CHECK (base_fare >= 0),
  payment_status    VARCHAR2(20) CHECK (payment_status IN ('Paid','Unpaid','Partial')),
  customer_id       NUMBER NOT NULL REFERENCES customer(customer_id),
  dispatch_id       NUMBER NOT NULL UNIQUE REFERENCES dispatch(dispatch_id),
  agent_id          NUMBER REFERENCES call_center_agent(agent_id),      -- the agent who handled the dispatch (sees the bill status)
  billed_by         NUMBER REFERENCES hr(hr_id),                         -- the driver / paramedic who made the bill at the end of the trip
  CONSTRAINT ck_bill_paid CHECK (amount_paid <= total_amount)
);

-- Weak entities (identifying relationships, total participation)
CREATE TABLE patient_vitals_log (            -- has
  patient_id   NUMBER NOT NULL REFERENCES patient(patient_id) ON DELETE CASCADE,
  log_time     TIMESTAMP NOT NULL,
  temperature  NUMBER(4,1),
  o2           NUMBER(3) CHECK (o2 BETWEEN 0 AND 100),
  systolic     NUMBER(3),                    -- blood_pressure (composite)
  diastolic    NUMBER(3),
  heart_rate   NUMBER(3),
  CONSTRAINT pk_patient_vitals PRIMARY KEY (patient_id, log_time),
  CONSTRAINT ck_vitals_bp CHECK (systolic > diastolic)
);
CREATE TABLE location_log (                  -- records
  ambulance_id  NUMBER NOT NULL REFERENCES ambulance(ambulance_id) ON DELETE CASCADE,
  log_time      TIMESTAMP NOT NULL,
  speed         NUMBER(5,1) CHECK (speed >= 0),
  longitude     NUMBER(9,6) CHECK (longitude BETWEEN -180 AND 180),
  latitude      NUMBER(9,6) CHECK (latitude BETWEEN -90 AND 90),
  CONSTRAINT pk_location_log PRIMARY KEY (ambulance_id, log_time)
);
CREATE TABLE ambulance_maintenance_log (     -- undergoes ; handled by the Maintenance team, not HR
  ambulance_id      NUMBER NOT NULL REFERENCES ambulance(ambulance_id) ON DELETE CASCADE,
  maintenance_date  DATE NOT NULL,
  maintenance_type  VARCHAR2(40),
  description       VARCHAR2(400),
  workshop          VARCHAR2(80),
  handled_by        VARCHAR2(80),
  cost              NUMBER(10,2) CHECK (cost >= 0),
  next_due_date     DATE,
  CONSTRAINT pk_amb_maintenance PRIMARY KEY (ambulance_id, maintenance_date),
  CONSTRAINT ck_maint_due CHECK (next_due_date >= maintenance_date)
);
CREATE TABLE ambulance_equipment (           -- holds
  ambulance_id         NUMBER NOT NULL REFERENCES ambulance(ambulance_id) ON DELETE CASCADE,
  equipment_no         NUMBER NOT NULL,
  equipment_name       VARCHAR2(80),
  equipment_condition  VARCHAR2(30),
  expiry_date          DATE,
  quantity             NUMBER(4) CHECK (quantity >= 0),
  CONSTRAINT pk_amb_equipment PRIMARY KEY (ambulance_id, equipment_no)
);

-- NEW: history of every status change of a dispatch (who changed it and when). Filled by a trigger.
CREATE TABLE dispatch_status_log (
  log_id       NUMBER PRIMARY KEY,
  dispatch_id  NUMBER NOT NULL REFERENCES dispatch(dispatch_id) ON DELETE CASCADE,
  status       VARCHAR2(30) NOT NULL,
  changed_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  changed_by   VARCHAR2(60)
);

-- NEW: the people who sign in. Every employee (agent, driver, paramedic) gets a login automatically when the employee is added:
-- username = Employee ID (EMP + HR number, e.g. EMP004), password empty until the employee sets it at the first sign-in
-- (with the Employee ID and date of birth). Passwords are stored hashed, never as text.
-- Roles: ADMIN (everything), HR (staff, attendance, leave, salary), MAINTENANCE (vehicles, insurance, servicing, equipment),
-- AGENT (calls, dispatch, billing), DRIVER and PARAMEDIC (own trips, money collected, attendance and leave).
CREATE TABLE app_user (
  user_id          NUMBER PRIMARY KEY,
  username         VARCHAR2(40) NOT NULL UNIQUE,
  password_hash    VARCHAR2(250),                       -- empty until the person sets it at the first sign-in
  full_name        VARCHAR2(80) NOT NULL,
  user_role        VARCHAR2(20) NOT NULL CHECK (user_role IN ('ADMIN','AGENT','HR','MAINTENANCE','DRIVER','PARAMEDIC')),
  hr_id            NUMBER UNIQUE REFERENCES hr(hr_id) ON DELETE CASCADE,
  is_active        CHAR(1) DEFAULT 'Y' NOT NULL CHECK (is_active IN ('Y','N')),
  failed_attempts  NUMBER(2) DEFAULT 0 NOT NULL,
  locked_until     DATE,
  last_login       DATE,
  created_on       DATE DEFAULT SYSDATE NOT NULL,
  CONSTRAINT ck_user_link CHECK (
       (user_role IN ('DRIVER','PARAMEDIC') AND hr_id IS NOT NULL)
    OR (user_role IN ('ADMIN','AGENT','HR','MAINTENANCE') AND hr_id IS NULL))
);

CREATE TABLE audit_log (
  audit_id    NUMBER PRIMARY KEY,
  changed_at  TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  changed_by  VARCHAR2(60),
  table_name  VARCHAR2(30) NOT NULL,
  record_id   VARCHAR2(60),
  action      VARCHAR2(6) NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
  details     VARCHAR2(2000)
);
CREATE INDEX ix_audit_time ON audit_log (changed_at);
CREATE INDEX ix_audit_table ON audit_log (table_name, record_id);

-- Auto-numbering of primary keys (sequence + trigger; needed on 11g)
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(60);
  v_tabs t_list := t_list('hr','call_center_agent','ambulance','hospital','customer','emergency_call',
                          'driver','paramedic','dispatch','billing','patient','app_user','dispatch_status_log',
                          'hr_attendance','hr_leave','audit_log');
  v_pks  t_list := t_list('hr_id','agent_id','ambulance_id','hospital_id','customer_id','call_id',
                          'driver_id','paramedic_id','dispatch_id','billing_id','patient_id','user_id','log_id',
                          'attendance_id','leave_id','audit_id');
BEGIN
  FOR i IN 1 .. v_tabs.COUNT LOOP
    EXECUTE IMMEDIATE 'CREATE SEQUENCE seq_' || v_tabs(i) || ' START WITH 1 INCREMENT BY 1 NOCACHE';
    EXECUTE IMMEDIATE 'CREATE OR REPLACE TRIGGER trg_' || v_tabs(i) || '_bi BEFORE INSERT ON ' || v_tabs(i) ||
      ' FOR EACH ROW WHEN (NEW.' || v_pks(i) || ' IS NULL) BEGIN SELECT seq_' || v_tabs(i) ||
      '.NEXTVAL INTO :NEW.' || v_pks(i) || ' FROM dual; END;';
  END LOOP;
END;
/

-- One HR record per person: a record used by an agent, a driver or a paramedic cannot be used by another kind.
CREATE OR REPLACE TRIGGER trg_agent_hr_chk BEFORE INSERT OR UPDATE OF hr_id ON call_center_agent FOR EACH ROW
DECLARE n NUMBER;
BEGIN
  SELECT (SELECT COUNT(*) FROM driver WHERE hr_id = :NEW.hr_id) + (SELECT COUNT(*) FROM paramedic WHERE hr_id = :NEW.hr_id)
    INTO n FROM dual;
  IF n > 0 THEN RAISE_APPLICATION_ERROR(-20001, 'This HR record already belongs to a driver or paramedic'); END IF;
END;
/
CREATE OR REPLACE TRIGGER trg_driver_hr_chk BEFORE INSERT OR UPDATE OF hr_id ON driver FOR EACH ROW
DECLARE n NUMBER;
BEGIN
  SELECT (SELECT COUNT(*) FROM call_center_agent WHERE hr_id = :NEW.hr_id) + (SELECT COUNT(*) FROM paramedic WHERE hr_id = :NEW.hr_id)
    INTO n FROM dual;
  IF n > 0 THEN RAISE_APPLICATION_ERROR(-20002, 'This HR record already belongs to an agent or paramedic'); END IF;
END;
/
CREATE OR REPLACE TRIGGER trg_paramedic_hr_chk BEFORE INSERT OR UPDATE OF hr_id ON paramedic FOR EACH ROW
DECLARE n NUMBER;
BEGIN
  SELECT (SELECT COUNT(*) FROM call_center_agent WHERE hr_id = :NEW.hr_id) + (SELECT COUNT(*) FROM driver WHERE hr_id = :NEW.hr_id)
    INTO n FROM dual;
  IF n > 0 THEN RAISE_APPLICATION_ERROR(-20003, 'This HR record already belongs to an agent or driver'); END IF;
END;
/

-- Every new driver and paramedic gets a login at once: username = Employee ID (EMP + HR number), no password yet.
-- They choose the password at the first sign-in (Employee ID + date of birth); until then nobody can sign in as them.
-- Call-centre agents share one login (role AGENT, e.g. agent_user); HR marks their attendance.
CREATE OR REPLACE TRIGGER trg_driver_login AFTER INSERT ON driver FOR EACH ROW
BEGIN
  INSERT INTO app_user (username, full_name, user_role, hr_id)
  VALUES ('EMP' || LPAD(:NEW.hr_id, 3, '0'), TRIM(:NEW.first_name || ' ' || :NEW.last_name), 'DRIVER', :NEW.hr_id);
END;
/
CREATE OR REPLACE TRIGGER trg_paramedic_login AFTER INSERT ON paramedic FOR EACH ROW
BEGIN
  INSERT INTO app_user (username, full_name, user_role, hr_id)
  VALUES ('EMP' || LPAD(:NEW.hr_id, 3, '0'), TRIM(:NEW.first_name || ' ' || :NEW.last_name), 'PARAMEDIC', :NEW.hr_id);
END;
/

-- Every status change of a dispatch is written to the history, and the ambulance follows the dispatch:
-- On Duty while the trip is running, Available again when it is completed or cancelled.
CREATE OR REPLACE TRIGGER trg_dispatch_status AFTER INSERT OR UPDATE OF status ON dispatch FOR EACH ROW
BEGIN
  IF INSERTING OR :OLD.status IS NULL OR :NEW.status <> :OLD.status THEN
    INSERT INTO dispatch_status_log (dispatch_id, status, changed_by)
      VALUES (:NEW.dispatch_id, :NEW.status, NVL(SYS_CONTEXT('USERENV','CLIENT_IDENTIFIER'), USER));
    IF :NEW.status IN ('En Route','At Scene','To Hospital','At Hospital') THEN
      UPDATE ambulance SET status = 'On Duty' WHERE ambulance_id = :NEW.ambulance_id AND status <> 'On Duty';
    ELSIF :NEW.status IN ('Completed','Cancelled') THEN
      UPDATE ambulance SET status = 'Available' WHERE ambulance_id = :NEW.ambulance_id AND status = 'On Duty';
    END IF;
  END IF;
END;
/

-- Taking a patient to a hospital uses one of its beds; removing the patient (or moving to another hospital) gives it back.
CREATE OR REPLACE TRIGGER trg_patient_beds AFTER INSERT OR DELETE OR UPDATE OF hospital_id ON patient FOR EACH ROW
BEGIN
  IF INSERTING THEN
    UPDATE hospital SET beds_available = beds_available - 1 WHERE hospital_id = :NEW.hospital_id;
  ELSIF DELETING THEN
    UPDATE hospital SET beds_available = beds_available + 1 WHERE hospital_id = :OLD.hospital_id;
  ELSIF :NEW.hospital_id <> :OLD.hospital_id THEN
    UPDATE hospital SET beds_available = beds_available + 1 WHERE hospital_id = :OLD.hospital_id;
    UPDATE hospital SET beds_available = beds_available - 1 WHERE hospital_id = :NEW.hospital_id;
  END IF;
END;
/

-- The date the bed count was last changed
CREATE OR REPLACE TRIGGER trg_hospital_beds_date BEFORE UPDATE OF beds_available ON hospital FOR EACH ROW
BEGIN
  :NEW.beds_updated_on := SYSDATE;
END;
/

-- payment_status follows the money received
CREATE OR REPLACE TRIGGER trg_billing_status BEFORE INSERT OR UPDATE OF amount_paid, total_amount ON billing FOR EACH ROW
BEGIN
  IF :NEW.amount_paid >= :NEW.total_amount THEN :NEW.payment_status := 'Paid';
  ELSIF :NEW.amount_paid > 0 THEN :NEW.payment_status := 'Partial';
  ELSE :NEW.payment_status := 'Unpaid';
  END IF;
END;
/

-- AUDIT TRAIL: one row-level trigger per business table, generated from the data dictionary so that no column is forgotten.
-- The application sets the signed-in user's name as the database CLIENT_IDENTIFIER, so changed_by shows the real person.
-- Passwords are never written; for APP_USER only "password changed" is recorded.
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('customer','call_center_agent','hr','hr_attendance','hr_leave','driver','paramedic',
                          'ambulance','ambulance_insurance','ambulance_maintenance_log','ambulance_equipment',
                          'hospital','tariff','emergency_call','dispatch','patient','patient_vitals_log',
                          'billing','app_user','agent_language','hospital_phone','customer_phone','customer_email','patient_allergy');
  v_ins  VARCHAR2(12000); v_upd VARCHAR2(12000); v_del VARCHAR2(12000); v_new VARCHAR2(500); v_old VARCHAR2(500);
  v_sql  VARCHAR2(32000);
  FUNCTION fmt(p_ref VARCHAR2, p_type VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    IF p_type = 'DATE' THEN RETURN 'TO_CHAR(' || p_ref || ',''YYYY-MM-DD HH24:MI'')';
    ELSIF p_type LIKE 'TIMESTAMP%' THEN RETURN 'TO_CHAR(' || p_ref || ',''YYYY-MM-DD HH24:MI:SS'')';
    ELSIF p_type IN ('VARCHAR2','CHAR') THEN RETURN p_ref;
    ELSE RETURN 'TO_CHAR(' || p_ref || ')'; END IF;
  END;
BEGIN
  FOR i IN 1 .. v_tabs.COUNT LOOP
    v_ins := ''; v_upd := ''; v_del := ''; v_new := ''; v_old := '';
    FOR k IN (SELECT cc.column_name FROM user_constraints c JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
              WHERE c.constraint_type = 'P' AND c.table_name = UPPER(v_tabs(i)) ORDER BY cc.position) LOOP
      IF v_new IS NOT NULL THEN v_new := v_new || '||''/''||'; v_old := v_old || '||''/''||'; END IF;
      v_new := v_new || 'TO_CHAR(:NEW.' || k.column_name || ')';
      v_old := v_old || 'TO_CHAR(:OLD.' || k.column_name || ')';
    END LOOP;
    FOR c IN (SELECT column_name, data_type FROM user_tab_cols
              WHERE table_name = UPPER(v_tabs(i)) AND virtual_column = 'NO' AND hidden_column = 'NO' AND data_type_owner IS NULL
                AND NOT (table_name = 'APP_USER' AND column_name IN ('PASSWORD_HASH','PIN_HASH','FAILED_ATTEMPTS','LOCKED_UNTIL','LAST_LOGIN'))
              ORDER BY column_id) LOOP
      v_ins := v_ins || ' IF :NEW.' || c.column_name || ' IS NOT NULL THEN v := v || ''' || LOWER(c.column_name) || '=''||' ||
               fmt(':NEW.' || c.column_name, c.data_type) || '||''; ''; END IF;';
      v_del := v_del || ' IF :OLD.' || c.column_name || ' IS NOT NULL THEN v := v || ''' || LOWER(c.column_name) || '=''||' ||
               fmt(':OLD.' || c.column_name, c.data_type) || '||''; ''; END IF;';
      v_upd := v_upd || ' IF (:OLD.' || c.column_name || ' IS NULL AND :NEW.' || c.column_name || ' IS NOT NULL) OR (:OLD.' ||
               c.column_name || ' IS NOT NULL AND :NEW.' || c.column_name || ' IS NULL) OR :OLD.' || c.column_name || ' <> :NEW.' ||
               c.column_name || ' THEN v := v || ''' || LOWER(c.column_name) || ': ''||NVL(' || fmt(':OLD.' || c.column_name, c.data_type) ||
               ',''-'')||'' -> ''||NVL(' || fmt(':NEW.' || c.column_name, c.data_type) || ',''-'')||''; ''; END IF;';
    END LOOP;
    IF v_tabs(i) = 'app_user' THEN
      v_upd := v_upd || ' IF NVL(:OLD.password_hash,''-'') <> NVL(:NEW.password_hash,''-'') THEN v := v || ''password changed; ''; END IF;';
    END IF;
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || LPAD(i, 2, '0') || ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
             ' FOR EACH ROW DECLARE v VARCHAR2(4000); who VARCHAR2(60) := NVL(SYS_CONTEXT(''USERENV'',''CLIENT_IDENTIFIER''), USER); BEGIN' ||
             ' IF INSERTING THEN' || v_ins ||
             '  INSERT INTO audit_log (changed_by, table_name, record_id, action, details) VALUES (who, ''' || UPPER(v_tabs(i)) || ''', ' || v_new || ', ''INSERT'', SUBSTR(v,1,2000));' ||
             ' ELSIF UPDATING THEN' || v_upd ||
             '  IF v IS NOT NULL THEN INSERT INTO audit_log (changed_by, table_name, record_id, action, details) VALUES (who, ''' || UPPER(v_tabs(i)) || ''', ' || v_new || ', ''UPDATE'', SUBSTR(v,1,2000)); END IF;' ||
             ' ELSE' || v_del ||
             '  INSERT INTO audit_log (changed_by, table_name, record_id, action, details) VALUES (who, ''' || UPPER(v_tabs(i)) || ''', ' || v_old || ', ''DELETE'', SUBSTR(v,1,2000));' ||
             ' END IF; END;';
    EXECUTE IMMEDIATE v_sql;
  END LOOP;
  FOR e IN (SELECT name, text FROM user_errors WHERE name LIKE 'TRG_AUD_%' AND type = 'TRIGGER' AND ROWNUM = 1) LOOP
    RAISE_APPLICATION_ERROR(-20100, 'Audit trigger ' || e.name || ' did not compile: ' || e.text);
  END LOOP;
END;
/

-- Derived attributes age and experience (the diagram's dotted ovals), computed when queried
CREATE OR REPLACE VIEW v_agent AS
  SELECT a.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM call_center_agent a;
CREATE OR REPLACE VIEW v_driver AS
  SELECT d.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM driver d;
CREATE OR REPLACE VIEW v_paramedic AS
  SELECT p.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM paramedic p;
CREATE OR REPLACE VIEW v_patient AS
  SELECT p.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age FROM patient p;
