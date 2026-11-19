# Emergency Ambulance Management System

Oracle 11g XE database + Python (Flask) web front end.

## Folders
- `database/`  01_schema.sql, 02_sample_data.sql, 03_queries.sql (+ `upgrades/` for databases made earlier)
- `frontend/`  the website (see `frontend/README.txt` for everything)

## Run it on your computer
1. Python 3.12 and Oracle 11g XE (own schema, e.g. your name).
2. In `database/`: run `01_schema.sql`, then `02_sample_data.sql` in your schema.
3. In `frontend/`: `pip install -r requirements.txt`
4. Create `config.py` in this top folder (next to `frontend/`, NOT inside it) with your own Oracle details:
   ```
   DB_USER = "YOURSCHEMA"
   DB_PASSWORD = "your-oracle-password"
   DB_DSN = "localhost:1521/XE"
   ```
   It is ignored by git, so your password is never uploaded. `frontend/config_example.py` shows all settings.
5. `py -3.12 setup_users.py` then `py -3.12 app.py` and open http://127.0.0.1:5000

## Working together
- Pull before you start, commit small changes, push often.
- Rules live in `frontend/ops.py`, pages in `frontend/app.py` and `frontend/templates/`.
- Database changes: edit `database/01_schema.sql` and add a numbered file in `database/upgrades/`; tell the group.
