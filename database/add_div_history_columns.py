import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DB = os.path.join(BASE_DIR, "database", "divergence_scanner_history.db")

con = sqlite3.connect(HISTORY_DB)
cur = con.cursor()

try:
    # Add missing columns
    cur.execute("ALTER TABLE divergence_scanner_history ADD COLUMN prev_date TEXT")
    cur.execute("ALTER TABLE divergence_scanner_history ADD COLUMN prev_low REAL")
    cur.execute("ALTER TABLE divergence_scanner_history ADD COLUMN prev_rsi REAL")
    con.commit()
    print("Columns added successfully: prev_date, prev_low, prev_rsi")
except sqlite3.OperationalError as e:
    print(f"Error (maybe columns already exist): {e}")
finally:
    con.close()