import sqlite3
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "market_ohlc.db")

print(f"Resetting market_ohlc in: {DB_PATH}")

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# Drop and recreate the table (erases all data!)
cur.execute("DROP TABLE IF EXISTS market_ohlc")
cur.execute("""
    CREATE TABLE market_ohlc (
        symbol TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY (symbol, date)
    )
""")

con.commit()
con.close()

print("market_ohlc table reset — all old data erased. Ready for fresh backfill.")