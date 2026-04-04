# =====================================================
# DIVERGENCE ENGINE — LIVE + IMMUTABLE HISTORY
# ALL NUMERIC VALUES ROUNDED TO 2 DECIMAL PLACES
# =====================================================

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, date

# =====================================================
# PATH FIX
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from support.utils import (
    calculate_rsi_tv,
    calculate_supertrend
)
from support.logger import log

# =====================================================
# DATABASE PATHS
# =====================================================
DATA_DB = os.path.join(BASE_DIR, "database", "market_ohlc.db")
DIV_DB  = os.path.join(BASE_DIR, "database", "divergence.db")
HISTORY_DB = os.path.join(BASE_DIR, "database", "divergence_scanner_history.db")

# =====================================================
# SETTINGS
# =====================================================
MIN_CANDLES = 120
LOOKBACK = 40

TODAY = date.today().isoformat()
NOW_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =====================================================
# DB INIT — LIVE TABLE
# =====================================================
def init_divergence_db():
    db = sqlite3.connect(DIV_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS divergence_trades (
            symbol TEXT PRIMARY KEY,
            detected_on TEXT,
            updated_at TEXT
        )
    """)
    db.commit()
    db.close()

# =====================================================
# DB INIT — IMMUTABLE HISTORY
# =====================================================
def init_divergence_history_db():
    db = sqlite3.connect(HISTORY_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS divergence_scanner_history (
            symbol TEXT,
            signal_date TEXT,
            created_at TEXT,

            divergence_type TEXT,
            divergence_low REAL,
            divergence_rsi_low REAL,

            buy_above REAL,
            sl REAL,

            PRIMARY KEY (symbol, signal_date)
        )
    """)
    db.commit()
    db.close()

# =====================================================
# LOAD OHLC (SAFE + 2 DECIMAL NORMALIZATION)
# =====================================================
def load_ohlc(symbol, as_of_date=None):
    con = sqlite3.connect(DATA_DB)

    query = """
        SELECT date, open, high, low, close, volume
        FROM market_ohlc
        WHERE symbol = ?
    """
    params = [symbol]

    if as_of_date:
        query += " AND date <= ?"
        params.append(as_of_date)

    query += " ORDER BY date"

    df = pd.read_sql(query, con, params=params)
    con.close()

    if df.empty or len(df) < MIN_CANDLES:
        return None

    df["date"] = pd.to_datetime(df["date"])

    # 🔒 FORCE 2 DECIMAL PRECISION
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).round(2)

    return df

# =====================================================
# DIVERGENCE LOGIC (UNCHANGED)
# =====================================================
def detect_bullish_divergence(df):
    recent = df.tail(LOOKBACK)
    low_idx = recent["low"].idxmin()

    return (
        recent["low"].iloc[-1] < recent["low"].min()
        and recent["rsi"].iloc[-1] > recent["rsi"].loc[low_idx]
    )

# =====================================================
# ENGINE
# =====================================================
def run_divergence_engine(as_of_date=None):
    init_divergence_db()
    init_divergence_history_db()

    print(">>> Divergence engine started")

    signal_date = as_of_date if as_of_date else TODAY
    log("INFO", f"Divergence Engine STARTED | DATE={signal_date}")

    # -------- SYMBOL UNIVERSE --------
    symbols = pd.read_sql(
        "SELECT DISTINCT symbol FROM market_ohlc",
        sqlite3.connect(DATA_DB)
    )["symbol"].tolist()

    db = sqlite3.connect(DIV_DB)
    c = db.cursor()

    hist_db = sqlite3.connect(HISTORY_DB)
    hc = hist_db.cursor()

    for symbol in symbols:
        df = load_ohlc(symbol, signal_date)
        if df is None:
            continue

        # ===== INDICATORS (2 DECIMALS) =====
        df["rsi"] = calculate_rsi_tv(df["close"]).round(2)

        df_st = df.set_index("date").copy()
        df_st["supertrend"] = calculate_supertrend(df_st, 10, 2).round(2)
        df["supertrend"] = df_st["supertrend"].values

        last = df.iloc[-1]

        if not detect_bullish_divergence(df):
            continue

        if last["close"] > last["supertrend"]:
            continue

        # -------- LIVE DB --------
        c.execute("""
            INSERT OR REPLACE INTO divergence_trades
            (symbol, detected_on, updated_at)
            VALUES (?, ?, ?)
        """, (symbol, signal_date, NOW_TS))
        db.commit()

        # -------- HISTORY DB --------
        try:
            recent = df.tail(LOOKBACK)
            low_idx = recent["low"].idxmin()

            hc.execute("""
                INSERT INTO divergence_scanner_history (
                    symbol, signal_date, created_at,
                    divergence_type,
                    divergence_low, divergence_rsi_low,
                    buy_above, sl
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                signal_date,
                NOW_TS,
                "BULLISH",
                round(float(recent["low"].iloc[-1]), 2),
                round(float(recent["rsi"].iloc[-1]), 2),
                None,
                None
            ))
            hist_db.commit()
        except sqlite3.IntegrityError:
            pass  # duplicate (symbol, date)

        log("INFO", f"[{symbol}] BULLISH DIVERGENCE")

    db.close()
    hist_db.close()

    print(">>> Divergence engine completed")
    log("INFO", "Divergence Engine COMPLETED")

# =====================================================
if __name__ == "__main__":
    run_divergence_engine()
