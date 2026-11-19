"""Run this first:  python check_db.py   - it tells you if Python can reach your Oracle tables."""
import sys

import db

try:
    conn = db.connect()
except Exception as e:
    text = str(e)
    print("COULD NOT CONNECT TO ORACLE:\n ", text, "\n")
    if "DPI-1047" in text or "DPY-3015" in text or "Cannot locate" in text:
        print("-> Python cannot find the Oracle client. Set ORACLE_CLIENT_DIR in config.py to the folder that contains oci.dll.")
        print("   Python and Oracle must both be 32-bit or both 64-bit.")
    elif "DPI-1050" in text:
        print("-> The Oracle client (11g) is too old for this version of the Python Oracle driver.")
        print("   Install the older driver:  py -3.12 -m pip install oracledb==2.5.1   (needs Python 3.8 to 3.13, not 3.14)")
    elif "DPY-3010" in text:
        print("-> Your Oracle is old (11g). Keep USE_THICK_MODE = True in config.py.")
    elif "ORA-01017" in text:
        print("-> Wrong user name or password in config.py (DB_USER / DB_PASSWORD).")
        print("   Also try DB_USER without the extra quotes:  DB_USER = \"BL.EN.U4EAC24067\"")
    elif "ORA-12541" in text or "ORA-12514" in text or "DPY-6005" in text:
        print("-> Oracle is not reachable. Start the Oracle database service and check DB_DSN in config.py.")
    sys.exit(1)

cur = conn.cursor()
cur.execute("SELECT USER FROM dual")
print("Connected as:", cur.fetchone()[0])
missing = []
for t in db.TABLES + ["app_user", "dispatch_status_log", "audit_log"]:
    try:
        cur.execute('SELECT COUNT(*) FROM "%s"' % t.upper())
        print("  %-28s %3d rows" % (t, cur.fetchone()[0]))
    except Exception:
        missing.append(t)
if missing:
    print("\nMissing tables:", ", ".join(missing), "\n-> run 01_schema.sql and 02_sample_data.sql first.")
else:
    print("\nAll tables found. Now run:  python app.py")
