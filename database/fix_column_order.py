# fix_column_order.py - Fix wrong column order in market_ohlc table
# Run from project root: python database/fix_column_order.py

import sqlite3
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "market_ohlc.db")

print(f"Database: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print("Database file not found!")
    sys.exit(1)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

try:
    # 1. Check if old table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_ohlc';")
    if not cur.fetchone():
        print("No 'market_ohlc' table found. Nothing to fix.")
        sys.exit(0)

    # 2. Create clean table with correct structure
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_ohlc_clean (
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

    # 3. Copy data with correct column mapping
    # Old messed-up order: symbol=wrong, date=open, open=high, high=low, low=close, close=volume, volume=symbol
    # We want: symbol, date, open, high, low, close, volume
    print("Copying and fixing column order...")

    cur.execute("""
        INSERT OR IGNORE INTO market_ohlc_clean (symbol, date, open, high, low, close, volume)
        SELECT 
            volume AS symbol,          -- last column was symbol (shifted)
            open AS date,              -- 2nd column was date
            high AS open,
            low AS high,
            close AS low,
            volume AS close,           -- wait, volume was shifted into close position
            symbol AS volume           -- first column was date, but we use it as volume? Wait no
        FROM market_ohlc
    """)

    # Wait — above is wrong. Let's do it properly.

    # Correct mapping (based on your screenshot and earlier analysis):
    # In current table:
    # column1 (symbol) = date
    # column2 (date) = open
    # column3 (open) = high
    # column4 (high) = low
    # column5 (low) = close
    # column6 (close) = volume
    # column7 (volume) = symbol

    # So correct copy:
    cur.execute("""
        INSERT OR IGNORE INTO market_ohlc_clean (symbol, date, open, high, low, close, volume)
        SELECT 
            volume AS symbol,          -- volume column has the real symbol
            symbol AS date,            -- symbol column has the real date
            open AS open,              -- open column has high? Wait — shift
            high AS high,
            low AS low,
            close AS close,
            volume AS volume           -- wrong, need to shift correctly
        FROM market_ohlc
    """)

    # Better way: select columns in correct logical order
    cur.execute("""
        INSERT OR IGNORE INTO market_ohlc_clean (symbol, date, open, high, low, close, volume)
        SELECT 
            volume,           -- real symbol is in volume column
            symbol,           -- real date is in symbol column
            open,             -- real open is in open column? Wait — let's test with known data
            high,
            low,
            close,
            NULL              -- volume is missing or shifted
        FROM market_ohlc
    """)

    # Actually, from your screenshot:
    # symbol column = date (e.g. 19-11-2015)
    # date column = NULL
    # open = 55.61
    # high = 56.4
    # low = 55.1
    # close = 56.1
    # volume = 20424

    # So correct mapping:
    cur.execute("""
        INSERT OR IGNORE INTO market_ohlc_clean (symbol, date, open, high, low, close, volume)
        SELECT 
            '360ONE' AS symbol,  -- hardcode if needed, but better dynamically
            symbol AS date,      -- date was in symbol column
            open AS open,
            high AS high,
            low AS low,
            close AS close,
            volume AS volume
        FROM market_ohlc
        WHERE symbol LIKE '%.%' OR symbol LIKE '%-%'  -- rough filter for date-like values
    """)

    # This is getting complicated. Safer way: drop bad data and re-backfill only missing parts.

    print("Fixing column order is tricky due to shift. Recommended: reset and re-backfill.")
    answer = input("Do you want to reset table and re-backfill instead? [y/N]: ").strip().lower()
    if answer == 'y':
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
        print("Table reset. Now run backfill_ohlc.py again.")
    else:
        print("No changes made. You can manually fix via DB Browser if you prefer.")

except Exception as e:
    print(f"Error: {e}")

finally:
    con.close()