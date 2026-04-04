import sqlite3

db_path = r"C:\Users\ask4b\OneDrive\Documents\BigShotsCapital\database\port_G.db"
con = sqlite3.connect(db_path)
tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("All tables in DB:", tables)

try:
    rows = con.execute("SELECT * FROM today_updates LIMIT 5").fetchall()
    print("Rows in today_updates:", rows)
except sqlite3.OperationalError as e:
    print("Table not found or error:", e)

con.close()