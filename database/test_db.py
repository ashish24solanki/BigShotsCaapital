import sqlite3
from datetime import date

PORTFOLIO_DB = r"C:\Users\ask4b\OneDrive\Documents\BigShotsCapital\database\port_G.db"
TODAY = date.today().isoformat()

con = sqlite3.connect(PORTFOLIO_DB)
print("Connected successfully to:", PORTFOLIO_DB)

# Create table
con.execute("""
    CREATE TABLE IF NOT EXISTS today_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        update_date TEXT,
        update_timestamp TEXT,
        update_type TEXT,
        symbol TEXT,
        value TEXT
    )
""")
con.commit()

# Insert test row
con.execute("""
    INSERT INTO today_updates 
    (update_date, update_timestamp, update_type, symbol, value)
    VALUES (?, ?, ?, ?, ?)
""", (TODAY, "2026-02-14 01:00:00", "TEST", "TESTSYM", "Test value"))
con.commit()

print("Table created and test row inserted.")

# Verify
rows = con.execute("SELECT * FROM today_updates").fetchall()
print("Rows in table:", rows)

con.close()