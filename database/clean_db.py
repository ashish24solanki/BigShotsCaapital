# clean_db.py - Merge ohlc_daily into market_ohlc, drop extra tables
# Run from project root: python database/clean_db.py

import os
import sqlite3
import sys

# =====================================================
# PATH SETUP
# =====================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "market_ohlc.db")

print(f"Database path: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print(f"ERROR: Database file not found at {DB_PATH}")
    sys.exit(1)

try:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # 1. Check existing tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cur.fetchall()]
    print("Tables found:", tables)

    # 2. Ensure market_ohlc exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_ohlc (
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

    # 3. Merge data from ohlc_daily → market_ohlc (skip duplicates)
    if 'ohlc_daily' in tables:
        print("Merging ohlc_daily into market_ohlc...")
        cur.execute("""
            INSERT OR IGNORE INTO market_ohlc
            SELECT symbol, date, open, high, low, close, volume
            FROM ohlc_daily
        """)
        merged_rows = cur.rowcount
        print(f"Merged {merged_rows} rows (duplicates skipped)")
    else:
        print("No ohlc_daily table found → skipping merge")

    # 4. Drop extra tables
    for table in ['ohlc_daily', 'nykaa']:
        if table in tables:
            print(f"Dropping table: {table}")
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        else:
            print(f"Table {table} does not exist → skip")

    con.commit()
    print("Database cleaned successfully!")

    # 5. Optional: Show row counts after cleanup
    cur.execute("SELECT COUNT(*) FROM market_ohlc")
    total_rows = cur.fetchone()[0]
    print(f"Total rows in market_ohlc now: {total_rows}")

    # Optional: Show first few rows of NYKAA
    cur.execute("SELECT * FROM market_ohlc WHERE symbol = 'NYKAA' ORDER BY date LIMIT 5")
    nykaa_rows = cur.fetchall()
    if nykaa_rows:
        print("\nFirst 5 rows for NYKAA:")
        for row in nykaa_rows:
            print(row)
    else:
        print("\nNo data for NYKAA yet in market_ohlc")

except sqlite3.Error as e:
    print(f"SQLite error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")

finally:
    if 'con' in locals():
        con.close()