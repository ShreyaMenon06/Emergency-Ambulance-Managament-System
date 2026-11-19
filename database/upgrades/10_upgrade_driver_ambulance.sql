-- Upgrade: a driver has a usual ambulance (a crew = driver + paramedic of the same ambulance).
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
