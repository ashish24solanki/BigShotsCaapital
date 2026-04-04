# =====================================================
# DIVERGENCE ENGINE G — WITH CANDIDATE DATE LOGGING
# =====================================================

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta

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

# =====================================================
# LOGGING
# =====================================================
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
DIV_LOG = os.path.join(LOG_DIR, "divergence_engine_g.log")

def div_log(symbol, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{symbol}] {msg}"
    with open(DIV_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)

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
SKIP_CANDLES = 5
DIVERGENCE_EXPIRY_DAYS = 15
WAITING_MAX_DAYS = 5
RSI_PERIOD = 10

TODAY = date.today().isoformat()
NOW_TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =====================================================
# DB INIT
# =====================================================
def init_divergence_db():
    db = sqlite3.connect(DIV_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS divergence_trades (
            symbol TEXT PRIMARY KEY,
            state TEXT,
            detected_on TEXT,
            updated_at TEXT,
            divergence_low REAL,
            divergence_rsi REAL,
            buy_above REAL,
            sl REAL
        )
    """)
    db.commit()
    db.close()

def init_divergence_history_db():
    db = sqlite3.connect(HISTORY_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS divergence_scanner_history (
            symbol TEXT,
            signal_date TEXT,
            created_at TEXT,
            event TEXT,
            details TEXT,
            PRIMARY KEY (symbol, signal_date, created_at)
        )
    """)
    db.commit()
    db.close()

# =====================================================
# LOAD OHLC
# =====================================================
def load_ohlc(symbol):
    con = sqlite3.connect(DATA_DB)
    df = pd.read_sql("""
        SELECT date, open, high, low, close, volume
        FROM market_ohlc
        WHERE symbol = ?
        ORDER BY date
    """, con, params=(symbol,))
    con.close()

    if df.empty or len(df) < MIN_CANDLES:
        return None

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).round(2)

    return df

# =====================================================
# DIVERGENCE DETECTION WITH CANDIDATE LOGGING
# =====================================================
def detect_bullish_divergence(df, symbol):
    if len(df) < LOOKBACK + SKIP_CANDLES + 10:
        div_log(symbol, f"Skipped: not enough history ({len(df)} candles)")
        return False, None

    today_low = df["low"].iloc[-1]
    today_rsi = df["rsi"].iloc[-1]

    # Skip last 5 candles (including today)
    window = df.iloc[-(LOOKBACK + SKIP_CANDLES):-SKIP_CANDLES]

    if len(window) < LOOKBACK:
        div_log(symbol, f"Skipped: window too small ({len(window)})")
        return False, None

    window_min_low = window["low"].min()
    lowest_low_idx = window["low"].idxmin()
    rsi_at_lowest_low = window.loc[lowest_low_idx, "rsi"]
    date_at_lowest_low = window.loc[lowest_low_idx, "date"].date()

    is_lower_low = today_low < window_min_low
    is_higher_rsi = today_rsi > rsi_at_lowest_low
    today_rsi_above_35 = today_rsi > 35
    prev_rsi_below_30 = rsi_at_lowest_low < 30

    div_log(symbol, f"Today ({TODAY}) Low: {today_low:.2f} | RSI(10): {today_rsi:.2f}")
    div_log(symbol, f"Window min low: {window_min_low:.2f} on {date_at_lowest_low} | RSI: {rsi_at_lowest_low:.2f}")

    # Log candidate even if not full divergence
    candidate_info = None
    if window_min_low > today_low and rsi_at_lowest_low < 30:
        div_log(symbol, f"**CANDIDATE DATE** → {date_at_lowest_low} | Low: {window_min_low:.2f} | RSI: {rsi_at_lowest_low:.2f} (prev low > today low + RSI < 30)")
        candidate_info = f"Candidate date: {date_at_lowest_low}, low: {window_min_low:.2f}, RSI: {rsi_at_lowest_low:.2f}"

    # Full condition: ALL must be true
    if is_lower_low and is_higher_rsi and today_rsi_above_35 and prev_rsi_below_30:
        div_log(symbol, f"BULLISH DIVERGENCE CONFIRMED at {date_at_lowest_low}")
        div_log(symbol, f"  Prev low: {window_min_low:.2f} | RSI: {rsi_at_lowest_low:.2f}")
        return True, {
            "divergence_low": round(today_low, 2),
            "divergence_rsi": round(today_rsi, 2),
            "prev_date": str(date_at_lowest_low),
            "prev_low": round(window_min_low, 2),
            "prev_rsi": round(rsi_at_lowest_low, 2),
            "candidate_info": candidate_info
        }

    reason = []
    if not is_lower_low: reason.append("no new lower low")
    if not is_higher_rsi: reason.append("today RSI not > prev RSI")
    if not today_rsi_above_35: reason.append("today RSI <= 35")
    if not prev_rsi_below_30: reason.append("prev RSI >= 30")
    div_log(symbol, f"No divergence: {', '.join(reason)}")

    return False, {"candidate_info": candidate_info}

# =====================================================
# ENGINE — YOUR 7 STEPS + CANDIDATE STORAGE
# =====================================================
def run_divergence_engine():
    init_divergence_db()
    init_divergence_history_db()

    print(">>> Divergence engine started")
    div_log("SYSTEM", "Divergence engine started")

    symbols = pd.read_sql(
        "SELECT DISTINCT symbol FROM market_ohlc",
        sqlite3.connect(DATA_DB)
    )["symbol"].tolist()

    div_log("SYSTEM", f"Scanning {len(symbols)} symbols")

    db = sqlite3.connect(DIV_DB)
    c = db.cursor()
    hist_db = sqlite3.connect(HISTORY_DB)
    hc = hist_db.cursor()

    found_count = 0

    for symbol in symbols:
        div_log(symbol, "=== START CHECKING ===")

        df = load_ohlc(symbol)
        if df is None:
            div_log(symbol, "Skipped: insufficient candles")
            continue

        df["rsi"] = calculate_rsi_tv(df["close"], 10).round(2)
        df["supertrend"] = calculate_supertrend(
            df["high"], df["low"], df["close"], period=10, multiplier=2
        ).round(2)

        today = df.iloc[-1]
        today_low = today["low"]
        today_close = today["close"]
        today_high = today["high"]
        today_super = today["supertrend"]

        # Step 1–3: Detect new divergence
        found, details = detect_bullish_divergence(df, symbol)
        if found:
            div_log(symbol, "NEW DIVERGENCE → State = DIVERGENCE")
            c.execute("""
                INSERT OR REPLACE INTO divergence_trades 
                (symbol, state, detected_on, updated_at, divergence_low, divergence_rsi)
                VALUES (?, 'DIVERGENCE', ?, ?, ?, ?)
            """, (symbol, TODAY, NOW_TS, details["divergence_low"], details["divergence_rsi"]))
            db.commit()
            found_count += 1

            # Save to history
            try:
                hc.execute("""
                    INSERT INTO divergence_scanner_history (
                        symbol, signal_date, created_at,
                        event, details
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    symbol, TODAY, NOW_TS,
                    "NEW_DIVERGENCE",
                    f"Low: {details['divergence_low']}, RSI: {details['divergence_rsi']}. "
                    f"Prev date: {details.get('prev_date', 'N/A')}, "
                    f"{details.get('candidate_info', '')}"
                ))
                hist_db.commit()
            except Exception as e:
                div_log(symbol, f"History insert failed: {e}")

            continue

        # === EXISTING STATE CHECK ===
        c.execute("SELECT state, detected_on, divergence_low, buy_above, updated_at FROM divergence_trades WHERE symbol = ?", (symbol,))
        row = c.fetchone()

        if not row:
            div_log(symbol, "No previous record")
            continue

        state, detected_on, div_low, buy_above, last_update = row

        days_since = (datetime.now().date() - datetime.strptime(detected_on, "%Y-%m-%d").date()).days

        # Step 4: Expiry >15 days
        if days_since > 15:
            div_log(symbol, f"Expired ({days_since} days) → removing")
            c.execute("DELETE FROM divergence_trades WHERE symbol = ?", (symbol,))
            db.commit()
            continue

        # Step 5: Invalidation (new lower low)
        if state == "DIVERGENCE" and today_low < div_low:
            div_log(symbol, f"Invalidated: new lower low → removing")
            c.execute("DELETE FROM divergence_trades WHERE symbol = ?", (symbol,))
            db.commit()
            continue

        # Step 6: DIVERGENCE → WAITING
        if state == "DIVERGENCE" and today_close > today_super:
            buy_above = round(today_high * 1.002, 2)
            div_log(symbol, f"Supertrend crossed → State = WAITING | Buy Above {buy_above}")

            c.execute("""
                UPDATE divergence_trades 
                SET state='WAITING', buy_above=?, updated_at=?
                WHERE symbol=?
            """, (buy_above, NOW_TS, symbol))
            db.commit()
            continue

        # Step 7: WAITING → ACTIVE or remove
        if state == "WAITING":
            days_waiting = (datetime.now().date() - datetime.strptime(last_update, "%Y-%m-%d %H:%M:%S").date()).days

            if days_waiting > 5:
                div_log(symbol, f"Waiting expired ({days_waiting} days) → removing")
                c.execute("DELETE FROM divergence_trades WHERE symbol = ?", (symbol,))
                db.commit()
                continue

            if today_close > buy_above:
                div_log(symbol, f"Price crossed buy_above → State = ACTIVE")
                c.execute("UPDATE divergence_trades SET state='ACTIVE', updated_at=? WHERE symbol=?", (NOW_TS, symbol))
                db.commit()
                continue

        div_log(symbol, f"Current state: {state} → no action today")

    db.close()
    hist_db.close()

    print(f">>> Divergence engine completed | Found {found_count} new signals")
    div_log("SYSTEM", f"Divergence engine completed | Found {found_count} new signals")

# =====================================================
if __name__ == "__main__":
    run_divergence_engine()