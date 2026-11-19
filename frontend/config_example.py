# Copy this file to config.py and fill in your Oracle password.
DB_USER = "SHREYA"                  # the schema of your new workspace
DB_PASSWORD = "type-your-password-here"
DB_DSN = "localhost:1521/XE"           # host:port/service of your Oracle 11g XE

# Oracle 11g needs the Oracle client libraries ("thick" mode); Python finds them by itself.
# If it cannot, put the folder that contains oci.dll here, e.g. r"C:\app\oracle\product\11.2.0\server\bin"
ORACLE_CLIENT_DIR = None
USE_THICK_MODE = True

SECRET_KEY = "change-this-to-any-long-random-text"
