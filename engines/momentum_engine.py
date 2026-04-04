# =====================================================
# MOMENTUM ENGINE — FAST, STATE-DRIVEN (NIFTY 500 ONLY)
# =====================================================

import os
import sqlite3
import pandas as pd
from datetime import datetime, date

from support.utils import (
    calculate_ema,
    calculate_rsi_tv,
    calculate_sl_t10_ema20,
    check_pyramiding_signal
)

# =====================================================
# PATHS & CONFIG
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_MOMENTUM = os.path.join(BASE_DIR, "database", "momentum.db")
DB_OHLC     = os.path.join(BASE_DIR, "database", "market_ohlc.db")
DB_HISTORY  = os.path.join(BASE_DIR, "database", "momentum_scanner_history.db")

NIFTY500_CSV = os.path.join(BASE_DIR, "database", "nifty500.csv")

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
MOMO_LOG = os.path.join(LOG_DIR, "momentum_engine.log")

LOOKBACK_DAYS = 200
MAX_WAIT_DAYS = 5
MAX_PYRAMID   = 10

TODAY = date.today().isoformat()
NOW   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =====================================================
# LOGGER
# =====================================================
def log(symbol, msg):
    with open(MOMO_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{NOW}] {symbol} | {msg}\n")

# =====================================================
# DB HELPERS
# =====================================================
def load_live_db():
    con = sqlite3.connect(DB_MOMENTUM)
    df = pd.read_sql("SELECT * FROM momentum_trades", con)
    con.close()
    return df

def load_ohlc(symbol):
    con = sqlite3.connect(DB_OHLC)
    df = pd.read_sql(
        """
        SELECT date, open, high, low, close
        FROM market_ohlc
        WHERE symbol = ?
        ORDER BY date
        """,
        con,
        params=(symbol,)
    )
    con.close()
    return df

def ensure_history_table():
    con = sqlite3.connect(DB_HISTORY)
    con.execute("""
        CREATE TABLE IF NOT EXISTS momentum_scanner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT,
            symbol TEXT,
            event_type TEXT,
            from_state TEXT,
            to_state TEXT,
            buy_above REAL,
            sl REAL,
            remarks TEXT,
            created_at TEXT
        )
    """)
    con.commit()
    con.close()

def append_history(symbol, event_type, from_state, to_state,
                   buy_above=None, sl=None, remarks=None):
    con = sqlite3.connect(DB_HISTORY)
    con.execute("""
        INSERT INTO momentum_scanner_history
        (event_date, symbol, event_type, from_state, to_state,
         buy_above, sl, remarks, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        TODAY, symbol, event_type, from_state, to_state,
        buy_above, sl, remarks, NOW
    ))
    con.commit()
    con.close()

# =====================================================
# ENGINE
# =====================================================
def run_momentum_engine():
    print(">>> Momentum engine started")
    ensure_history_table()

    nifty_df = pd.read_csv(NIFTY500_CSV)
    symbols = sorted(set(nifty_df.iloc[:, 0].astype(str).str.strip()))

    live_df = load_live_db()
    live_map = {r.symbol: r for r in live_df.itertuples()} if not live_df.empty else {}

    con = sqlite3.connect(DB_MOMENTUM)
    c = con.cursor()

    for symbol in symbols:

        df = load_ohlc(symbol)
        if df.empty or len(df) < LOOKBACK_DAYS:
            continue

        df["ema20"] = calculate_ema(df["close"], 20)
        df["rsi"]   = calculate_rsi_tv(df["close"])

        t = len(df) - 1
        high  = round(float(df.iloc[t]["high"]), 1)
        low   = round(float(df.iloc[t]["low"]), 1)
        close = round(float(df.iloc[t]["close"]), 1)
        ema20 = round(float(df.iloc[t]["ema20"]), 1)
        rsi   = round(float(df.iloc[t]["rsi"]), 1)

        # =================================================
        # EXISTING SYMBOL
        # =================================================
        if symbol in live_map:
            row = live_map[symbol]
            state = row.status

            # ---------- ACTIVE ----------
            if state == "ACTIVE":

                if low < row.sl:
                    c.execute("""
                        UPDATE momentum_trades
                        SET status='EXITED', exit_date=?, state_changed_at=?
                        WHERE symbol=?
                    """, (TODAY, NOW, symbol))

                    append_history(
                        symbol, "SL_HIT", "ACTIVE", "EXITED",
                        sl=row.sl, remarks="Daily low < SL"
                    )
                    con.commit()
                    continue

                # 🔒 SAFE SL CALCULATION (FIX)
                sl_data = calculate_sl_t10_ema20(df, TODAY)
                if not sl_data or sl_data.get("final_sl") is None:
                    log(symbol, "SL calc skipped (insufficient data)")
                    continue

                new_sl = round(float(sl_data["final_sl"]), 1)

                if round(row.sl, 1) != new_sl:
                    c.execute("""
                        UPDATE momentum_trades
                        SET sl=?, sl_updated_date=?, state_changed_at=?
                        WHERE symbol=?
                    """, (new_sl, TODAY, NOW, symbol))

                    append_history(
                        symbol, "SL_UPDATE", "ACTIVE", "ACTIVE", sl=new_sl
                    )

                if (row.pyramid_count or 0) < MAX_PYRAMID:
                    pyr = check_pyramiding_signal(df)
                    if pyr and pyr.get("passed"):
                        c.execute("""
                            UPDATE momentum_trades
                            SET pyramid_count=pyramid_count+1,
                                pyramiding_date=?, state_changed_at=?
                            WHERE symbol=?
                        """, (TODAY, NOW, symbol))

                        append_history(
                            symbol, "PYRAMID", "ACTIVE", "ACTIVE",
                            buy_above=row.buy_above,
                            remarks="Add-on confirmed"
                        )

                con.commit()
                continue

        # =================================================
        # NEW SYMBOL
        # =================================================
        cond1 = close > ema20
        cond2 = close > df.iloc[t-20:t]["high"].max()
        cond3 = rsi > 55

        if not (cond1 and cond2 and cond3):
            continue

        sl_data = calculate_sl_t10_ema20(df, TODAY)
        if not sl_data or sl_data.get("final_sl") is None:
            continue

        buy_above = round(high * 1.002, 1)
        sl = round(float(sl_data["final_sl"]), 1)

        c.execute("""
            INSERT OR REPLACE INTO momentum_trades
            (symbol, buy_above, sl, signal_date, status,
             pyramid_count, state_changed_at)
            VALUES (?, ?, ?, ?, 'WAITING', 0, ?)
        """, (symbol, buy_above, sl, TODAY, NOW))

        append_history(
            symbol, "NEW_SETUP", None, "WAITING",
            buy_above=buy_above, sl=sl
        )

        con.commit()

    con.close()
    print(">>> Momentum engine completed")

# =====================================================
if __name__ == "__main__":
    run_momentum_engine()
