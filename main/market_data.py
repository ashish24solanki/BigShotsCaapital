# =====================================================
# MARKET DATA UPDATE (NIFTY 200 ONLY — CLEAN & SAFE)
# =====================================================

import os
import sqlite3
from datetime import timedelta, date
import pandas as pd
import time
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "database", "market_ohlc.db")
CSV_PATH = os.path.join(BASE_DIR, "database", "nifty200.csv")

# =====================================================
# DB INIT
# =====================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS market_ohlc (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    con.commit()
    con.close()

# =====================================================
# LAST DATE (SAFE)
# =====================================================
def get_last_date(symbol):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT MAX(date) FROM market_ohlc WHERE symbol=?", (symbol,))
    row = cur.fetchone()
    con.close()

    if not row or not row[0]:
        return None

    return pd.to_datetime(row[0], errors="coerce").date()

# =====================================================
# LOAD NIFTY 200 CSV
# =====================================================
def load_nifty200_symbols():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError("❌ nifty200.csv not found")

    df = pd.read_csv(CSV_PATH)
    return (
        df.iloc[:, 0]
        .astype(str)
        .str.strip()
        .str.upper()
        .tolist()
    )

# =====================================================
# UPDATE OHLC (VISIBLE PROGRESS)
# =====================================================
def update_market_ohlc(kite):
    init_db()

    symbols = load_nifty200_symbols()

    instruments = kite.instruments("NSE")
    token_map = {
        i["tradingsymbol"]: i["instrument_token"]
        for i in instruments
        if i["tradingsymbol"] in symbols
    }

    total = len(token_map)
    updated = 0
    failed = 0

    print("\n📊 MARKET DATA UPDATE STARTED")
    print(f"📊 NIFTY 200 universe size: {total}\n")

    for idx, (symbol, token) in enumerate(token_map.items(), start=1):

        # 🔹 ALWAYS SHOW PROGRESS FIRST
        sys.stdout.write(
            f"\r⏳ {idx}/{total} | Updated: {updated} | Failed: {failed}"
        )
        sys.stdout.flush()

        try:
            last_date = get_last_date(symbol)

            from_date = (
                last_date + timedelta(days=1)
                if last_date else
                date.today() - timedelta(days=400)
            )

            to_date = date.today()
            if from_date > to_date:
                continue

            data = kite.historical_data(token, from_date, to_date, "day")
            if not data:
                continue

            df = pd.DataFrame(data)
            df["symbol"] = symbol

            # ✅ DATE NORMALIZATION (NO TZ / NO TIME)
            df["date"] = (
                pd.to_datetime(df["date"], errors="coerce")
                .dt.date
                .astype(str)
            )

            con = sqlite3.connect(DB_PATH)
            df[["symbol", "date", "open", "high", "low", "close", "volume"]] \
                .to_sql("market_ohlc", con, if_exists="append", index=False)
            con.close()

            updated += 1

        except Exception:
            failed += 1

        time.sleep(0.25)

    print(f"\n\n✅ Market OHLC update completed | Symbols updated: {updated}")
