-- Upgrade to first normal form: every multivalued attribute gets its own table, one value per row.
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
