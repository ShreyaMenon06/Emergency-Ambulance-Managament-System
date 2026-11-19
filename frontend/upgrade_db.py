"""py -3.12 upgrade_db.py  - brings a database made with an earlier version up to date (safe to run again).
Every employee gets their own login: Employee ID (EMP004) + a password they choose at their first sign-in.
Recreates APP_USER (admin_user, hr_user and maintenance_user are created again), creates the logins of all employees,
adds HR_ATTENDANCE.CHECK_IN and rebuilds three audit triggers (database\\upgrades\\05_upgrade_employee_logins.sql, only when not done yet),
then makes call-centre agents share one login (database\\upgrades\\07_upgrade_shared_agent_login.sql),
then first normal form: phone, e-mail, allergy and language lists become their own tables (database\\upgrades\\08_upgrade_first_normal_form.sql).
then hospital positions + nearest hospital at dispatch, bills made by the crew, no insurance payment (database\\upgrades\\09_upgrade_hospital_distance_crew_billing.sql),
then a driver's usual ambulance (database\\upgrades\\10_upgrade_driver_ambulance.sql),
then removes the attendance PIN (database\\upgrades\\11_upgrade_remove_attendance_pin.sql).
Ignored when already done: ORA-04080 (trigger gone), ORA-02443 (constraint gone), ORA-00904 (column gone), ORA-01430 (column there), ORA-02264 (constraint there)."""
from werkzeug.security import generate_password_hash

import db
import ops

SQL5 = r"""-- Upgrade for a database that already ran 01_schema.sql + 02_sample_data.sql (any of the earlier upgrades):
-- every employee now has their own login. Username = Employee ID (EMP004), the password is set by the employee at the first sign-in.
--  * APP_USER is recreated (new column HR_ID, PASSWORD_HASH may be empty, roles DRIVER and PARAMEDIC are single employees).
--    The old logins are removed: admin_user, hr_user and maintenance_user are created again by  py -3.12 upgrade_db.py
--  * three triggers create the login of every new agent / driver / paramedic automatically; existing employees get theirs now
--  * HR.PIN_HASH (an earlier idea, not used any more) is removed; HR_ATTENDANCE.CHECK_IN (time of marking) is added
--  * audit triggers of HR, HR_ATTENDANCE and APP_USER are rebuilt
-- New installs do not need this (01_schema.sql already has it). Normally run it with  py -3.12 upgrade_db.py
ALTER TABLE hr DROP COLUMN pin_hash
/
ALTER TABLE hr_attendance ADD (check_in DATE)
/
DROP TABLE app_user CASCADE CONSTRAINTS
/
CREATE TABLE app_user (
  user_id          NUMBER PRIMARY KEY,
  username         VARCHAR2(40) NOT NULL UNIQUE,
  password_hash    VARCHAR2(250),                       -- empty until the person sets it at the first sign-in
  full_name        VARCHAR2(80) NOT NULL,
  user_role        VARCHAR2(20) NOT NULL CHECK (user_role IN ('ADMIN','AGENT','HR','MAINTENANCE','DRIVER','PARAMEDIC')),
  agent_id         NUMBER REFERENCES call_center_agent(agent_id) ON DELETE CASCADE,
  hr_id            NUMBER UNIQUE REFERENCES hr(hr_id) ON DELETE CASCADE,
  is_active        CHAR(1) DEFAULT 'Y' NOT NULL CHECK (is_active IN ('Y','N')),
  failed_attempts  NUMBER(2) DEFAULT 0 NOT NULL,
  locked_until     DATE,
  last_login       DATE,
  created_on       DATE DEFAULT SYSDATE NOT NULL,
  CONSTRAINT ck_user_link CHECK (
       (user_role = 'AGENT' AND agent_id IS NOT NULL)
    OR (user_role IN ('DRIVER','PARAMEDIC') AND hr_id IS NOT NULL AND agent_id IS NULL)
    OR (user_role IN ('ADMIN','HR','MAINTENANCE') AND hr_id IS NULL AND agent_id IS NULL))
);
/
CREATE OR REPLACE TRIGGER trg_app_user_bi BEFORE INSERT ON app_user FOR EACH ROW WHEN (NEW.user_id IS NULL)
BEGIN SELECT seq_app_user.NEXTVAL INTO :NEW.user_id FROM dual; END;
/
-- Every new employee gets a login at once: username = Employee ID (EMP + HR number), no password yet.
-- The employee chooses the password at the first sign-in (Employee ID + date of birth); until then nobody can sign in as them.
CREATE OR REPLACE TRIGGER trg_agent_login AFTER INSERT ON call_center_agent FOR EACH ROW
BEGIN
  INSERT INTO app_user (username, full_name, user_role, agent_id, hr_id)
  VALUES ('EMP' || LPAD(:NEW.hr_id, 3, '0'), TRIM(:NEW.first_name || ' ' || :NEW.last_name), 'AGENT', :NEW.agent_id, :NEW.hr_id);
END;
/
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

INSERT INTO app_user (username, full_name, user_role, agent_id, hr_id)
SELECT 'EMP' || LPAD(e.hr_id, 3, '0'), e.name, e.role, e.agent_id, e.hr_id FROM (
  SELECT hr_id, TRIM(first_name || ' ' || last_name) AS name, 'AGENT' AS role, agent_id FROM call_center_agent WHERE is_active = 'Y'
  UNION ALL SELECT hr_id, TRIM(first_name || ' ' || last_name), 'DRIVER', NULL FROM driver WHERE is_active = 'Y'
  UNION ALL SELECT hr_id, TRIM(first_name || ' ' || last_name), 'PARAMEDIC', NULL FROM paramedic WHERE is_active = 'Y') e
/
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('hr','hr_attendance','app_user');
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
                AND NOT (table_name = 'APP_USER' AND column_name IN ('PASSWORD_HASH','FAILED_ATTEMPTS','LOCKED_UNTIL','LAST_LOGIN'))
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || CASE v_tabs(i) WHEN 'hr' THEN '03' WHEN 'hr_attendance' THEN '04' ELSE '19' END || ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
"""

SQL7 = r"""-- Upgrade: call-centre agents share ONE login (e.g. agent_user); HR marks their attendance and enters their leave.
-- Drivers and paramedics keep their own Employee-ID logins (their trips, money collected, attendance, leave).
--  * the trigger that made a login for every new agent is dropped, and the personal agent logins are deleted
--  * APP_USER loses the column AGENT_ID; role AGENT is now a plain role login like ADMIN, HR and MAINTENANCE
--  * the audit trigger of APP_USER is rebuilt
-- The shared agent login itself (agent_user) is created by  py -3.12 upgrade_db.py  /  py -3.12 setup_users.py
-- New installs do not need this (01_schema.sql already has it). Normally run it with  py -3.12 upgrade_db.py
DROP TRIGGER trg_agent_login
/
DELETE FROM app_user WHERE user_role = 'AGENT' AND hr_id IS NOT NULL
/
ALTER TABLE app_user DROP CONSTRAINT ck_user_link
/
ALTER TABLE app_user DROP COLUMN agent_id CASCADE CONSTRAINTS
/
ALTER TABLE app_user ADD CONSTRAINT ck_user_link CHECK (
       (user_role IN ('DRIVER','PARAMEDIC') AND hr_id IS NOT NULL)
    OR (user_role IN ('ADMIN','AGENT','HR','MAINTENANCE') AND hr_id IS NULL))
/
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('app_user');
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || CASE v_tabs(i) WHEN 'hr' THEN '03' WHEN 'hr_attendance' THEN '04' ELSE '19' END || ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
"""

SQL8 = r"""-- Upgrade to first normal form: every multivalued attribute gets its own table, one value per row.
--   CUSTOMER.PHONE_NO / EMAIL (lists)         -> CUSTOMER_PHONE, CUSTOMER_EMAIL
--   HOSPITAL.PHONE_NO (list)                  -> HOSPITAL_PHONE
--   PATIENT.KNOWN_ALLERGIES (list)            -> PATIENT_ALLERGY
--   CALL_CENTER_AGENT.LANGUAGES ("English, Hindi" in one text) -> AGENT_LANGUAGE
-- The existing values are copied first, then the old columns and the list types are removed, the four views and the audit triggers are rebuilt.
-- New installs do not need this (01_schema.sql already has it). Normally run it with  py -3.12 upgrade_db.py  (safe to run again).
CREATE TABLE agent_language (
  agent_id  NUMBER NOT NULL REFERENCES call_center_agent(agent_id) ON DELETE CASCADE,
  language  VARCHAR2(40) NOT NULL,
  CONSTRAINT pk_agent_language PRIMARY KEY (agent_id, language)
)
/
CREATE TABLE hospital_phone (
  hospital_id  NUMBER NOT NULL REFERENCES hospital(hospital_id) ON DELETE CASCADE,
  phone_no     VARCHAR2(20) NOT NULL,
  CONSTRAINT pk_hospital_phone PRIMARY KEY (hospital_id, phone_no)
)
/
CREATE TABLE customer_phone (
  customer_id  NUMBER NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
  phone_no     VARCHAR2(20) NOT NULL,
  CONSTRAINT pk_customer_phone PRIMARY KEY (customer_id, phone_no)
)
/
CREATE TABLE customer_email (
  customer_id  NUMBER NOT NULL REFERENCES customer(customer_id) ON DELETE CASCADE,
  email        VARCHAR2(100) NOT NULL,
  CONSTRAINT pk_customer_email PRIMARY KEY (customer_id, email)
)
/
CREATE TABLE patient_allergy (
  patient_id  NUMBER NOT NULL REFERENCES patient(patient_id) ON DELETE CASCADE,
  allergy     VARCHAR2(60) NOT NULL,
  CONSTRAINT pk_patient_allergy PRIMARY KEY (patient_id, allergy)
)
/
DECLARE
  PROCEDURE has_col(p_table VARCHAR2, p_col VARCHAR2, p_copy VARCHAR2) IS
    n NUMBER;
  BEGIN
    SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name = p_table AND column_name = p_col;
    IF n > 0 THEN
      IF p_copy IS NOT NULL THEN EXECUTE IMMEDIATE p_copy; END IF;
      EXECUTE IMMEDIATE 'ALTER TABLE ' || p_table || ' DROP COLUMN ' || p_col;
    END IF;
  END;
BEGIN
  has_col('CUSTOMER', 'PHONE_NO', 'INSERT INTO customer_phone (customer_id, phone_no) SELECT DISTINCT c.customer_id, t.COLUMN_VALUE FROM customer c, TABLE(c.phone_no) t WHERE t.COLUMN_VALUE IS NOT NULL');
  has_col('CUSTOMER', 'EMAIL', 'INSERT INTO customer_email (customer_id, email) SELECT DISTINCT c.customer_id, t.COLUMN_VALUE FROM customer c, TABLE(c.email) t WHERE t.COLUMN_VALUE IS NOT NULL');
  has_col('HOSPITAL', 'PHONE_NO', 'INSERT INTO hospital_phone (hospital_id, phone_no) SELECT DISTINCT h.hospital_id, t.COLUMN_VALUE FROM hospital h, TABLE(h.phone_no) t WHERE t.COLUMN_VALUE IS NOT NULL');
  has_col('PATIENT', 'KNOWN_ALLERGIES', 'INSERT INTO patient_allergy (patient_id, allergy) SELECT DISTINCT p.patient_id, t.COLUMN_VALUE FROM patient p, TABLE(p.known_allergies) t WHERE t.COLUMN_VALUE IS NOT NULL');
  has_col('CALL_CENTER_AGENT', 'LANGUAGES', 'INSERT INTO agent_language (agent_id, language) SELECT DISTINCT x.agent_id, x.lang FROM (SELECT a.agent_id, TRIM(REGEXP_SUBSTR(a.languages, ''[^,]+'', 1, n.l)) AS lang FROM call_center_agent a JOIN (SELECT LEVEL AS l FROM dual CONNECT BY LEVEL <= 15) n ON n.l <= REGEXP_COUNT(a.languages, '','') + 1 WHERE a.languages IS NOT NULL) x WHERE x.lang IS NOT NULL');
  COMMIT;
  FOR y IN (SELECT type_name FROM user_types WHERE type_name IN ('PHONE_LIST','EMAIL_LIST','ALLERGY_LIST')) LOOP
    EXECUTE IMMEDIATE 'DROP TYPE ' || y.type_name || ' FORCE';
  END LOOP;
END;
/
CREATE OR REPLACE VIEW v_agent AS
  SELECT a.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM call_center_agent a
/
CREATE OR REPLACE VIEW v_driver AS
  SELECT d.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM driver d
/
CREATE OR REPLACE VIEW v_paramedic AS
  SELECT p.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age,
         TRUNC(MONTHS_BETWEEN(SYSDATE, date_of_joining) / 12) AS experience
  FROM paramedic p
/
CREATE OR REPLACE VIEW v_patient AS
  SELECT p.*, TRUNC(MONTHS_BETWEEN(SYSDATE, dob) / 12) AS age FROM patient p
/
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('customer','call_center_agent','agent_language','hospital_phone','customer_phone','customer_email','patient_allergy');
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || CASE v_tabs(i) WHEN 'customer' THEN '01' WHEN 'call_center_agent' THEN '02' WHEN 'agent_language' THEN '20' WHEN 'hospital_phone' THEN '21' WHEN 'customer_phone' THEN '22' WHEN 'customer_email' THEN '23' ELSE '24' END || ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
"""

SQL9 = r"""-- Upgrade: nearest hospital at dispatch, bills made by the crew, no insurance payment.
--   HOSPITAL         + latitude, longitude          (where the hospital is)
--   EMERGENCY_CALL   + pick_lat, pick_lon           (position of the pick-up area chosen on the call)
--   BILLING          + billed_by (hr_id of the driver / paramedic who made the bill)
--                    - insurance_status             (removed)
--                    payment_mode now only Cash, Card, UPI (old 'Insurance' bills become 'Card')
--   Also: the hospital chosen at dispatch is already stored in DISPATCH.HOSPITAL_ID, set the known hospitals' positions,
--   and the audit triggers of HOSPITAL, EMERGENCY_CALL and BILLING are rebuilt for the new columns.
-- New installs do not need this (01_schema.sql already has it). Normally run it with  py -3.12 upgrade_db.py  (safe to run again).
ALTER TABLE hospital ADD (latitude NUMBER(9,6) CHECK (latitude BETWEEN -90 AND 90), longitude NUMBER(9,6) CHECK (longitude BETWEEN -180 AND 180))
/
ALTER TABLE emergency_call ADD (pick_lat NUMBER(9,6) CHECK (pick_lat BETWEEN -90 AND 90), pick_lon NUMBER(9,6) CHECK (pick_lon BETWEEN -180 AND 180))
/
ALTER TABLE billing ADD (billed_by NUMBER REFERENCES hr(hr_id))
/
UPDATE hospital SET latitude = 12.917, longitude = 77.623 WHERE latitude IS NULL AND (UPPER(branch_name) LIKE '%HOSUR%')
/
UPDATE hospital SET latitude = 12.986, longitude = 77.738 WHERE latitude IS NULL AND (UPPER(branch_name) LIKE '%WHITEFIELD%')
/
UPDATE hospital SET latitude = 12.895, longitude = 77.597 WHERE latitude IS NULL AND (UPPER(branch_name) LIKE '%BANNERGHATTA%')
/
UPDATE hospital SET latitude = 12.972, longitude = 77.641 WHERE latitude IS NULL AND (UPPER(branch_name) LIKE '%INDIRANAGAR%')
/
UPDATE billing SET payment_mode = 'Card' WHERE payment_mode = 'Insurance'
/
ALTER TABLE billing DROP COLUMN insurance_status
/
DECLARE
  v_cond VARCHAR2(4000);
BEGIN
  FOR c IN (SELECT constraint_name, search_condition FROM user_constraints WHERE table_name = 'BILLING' AND constraint_type = 'C') LOOP
    v_cond := c.search_condition;
    IF INSTR(v_cond, '''Insurance''') > 0 THEN
      EXECUTE IMMEDIATE 'ALTER TABLE billing DROP CONSTRAINT ' || c.constraint_name;
    END IF;
  END LOOP;
END;
/
ALTER TABLE billing ADD CONSTRAINT ck_bill_mode CHECK (payment_mode IN ('Cash','Card','UPI'))
/
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('hospital','emergency_call','billing');
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || CASE v_tabs(i) WHEN 'hospital' THEN '12' WHEN 'emergency_call' THEN '14' ELSE '18' END ||
             ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
"""

SQL10 = r"""-- Upgrade: a driver has a usual ambulance (a crew = driver + paramedic of the same ambulance).
--   DRIVER  + ambulance_id  (FK to AMBULANCE, optional; same idea as PARAMEDIC.ambulance_id)
--   and the audit trigger of DRIVER is rebuilt for the new column.
-- Existing drivers keep no ambulance until HR / Admin sets one (Records > Driver > Edit).
-- New installs do not need this (01_schema.sql already has it). Normally run it with  py -3.12 upgrade_db.py  (safe to run again).
ALTER TABLE driver ADD (ambulance_id NUMBER REFERENCES ambulance(ambulance_id))
/
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('driver');
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || '06' ||
             ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
"""

SQL11 = r"""-- Upgrade: the attendance PIN is gone. Drivers and paramedics are already signed in with their own password, so they just press
-- "Mark present" or "Mark half day". APP_USER.PIN_HASH is removed and the audit trigger of APP_USER is rebuilt without it.
-- New installs do not need this (01_schema.sql no longer has the column). Normally run it with  py -3.12 upgrade_db.py  (safe to run again).
DECLARE
  TYPE t_list IS TABLE OF VARCHAR2(30);
  v_tabs t_list := t_list('app_user');
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
    v_sql := 'CREATE OR REPLACE TRIGGER trg_aud_' || CASE v_tabs(i) WHEN 'hr' THEN '03' WHEN 'hr_attendance' THEN '04' ELSE '19' END || ' AFTER INSERT OR UPDATE OR DELETE ON ' || v_tabs(i) ||
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
/
ALTER TABLE app_user DROP COLUMN pin_hash
/
"""

import setup_users

conn = db.connect("upgrade_db")
cur = conn.cursor()
IGNORE = {"ORA-00904": "was already removed", "ORA-01430": "already there", "ORA-00942": "did not exist",
          "ORA-04080": "was already removed", "ORA-02443": "was already removed", "ORA-00955": "already exists", "ORA-02264": "already exists"}
cur.execute("SELECT COUNT(*) FROM user_tab_columns WHERE table_name = 'APP_USER' AND column_name = 'HR_ID'")
done5 = cur.fetchone()[0] > 0
if done5:
    print("skipped   employee-login upgrade (already done, the logins are kept)")
SQL = ("" if done5 else SQL5 + "\n/\n") + SQL7 + "\n/\n" + SQL8 + "\n/\n" + SQL9 + "\n/\n" + SQL10 + "\n/\n" + SQL11
for stmt in [x.strip() for x in SQL.replace("\r\n", "\n").split("\n/\n") if x.strip()]:
    lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
    while lines and lines[0].strip() in ("", "/"):          # a lone "/" left over between two scripts is not a statement
        lines.pop(0)
    while lines and lines[-1].strip() in ("", "/"):
        lines.pop()
    body = "\n".join(lines).strip()
    if not body:
        continue
    if body.endswith(";") and not body.upper().endswith("END;"):
        body = body[:-1].rstrip()            # plain statements must not end with a semicolon (blocks ending in END; must)
    first = body.split("\n")[0][:72]
    try:
        cur.execute(body)
        print("done     ", first)
    except Exception as e:
        msg = str(e).strip().splitlines()[0]
        hit = [k for k in IGNORE if k in msg]
        if hit:
            print("skipped  ", first, "(%s)" % IGNORE[hit[0]])
        else:
            print("FAILED   ", first, "\n   ", msg)
            raise SystemExit(1)
conn.commit()
cur.execute("SELECT COUNT(*) FROM user_errors WHERE type = 'TRIGGER'")
print("trigger errors:", cur.fetchone()[0])
print()
setup_users.main(conn)
