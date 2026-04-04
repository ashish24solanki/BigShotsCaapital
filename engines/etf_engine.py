# =====================================================
# ETF ACCUMULATOR — FINAL STABLE VERSION (FIXED)
# =====================================================

import os
import sqlite3
import math
import requests
import pandas as pd
import time
from datetime import datetime, timedelta

# =====================================================
# PATHS
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "database", "gtt_anchor_levels.db")

# =====================================================
# TELEGRAM CONFIG (READ ONLY)
# =====================================================
try:
    from config.bot_config import (
        BOT_TOKEN as TELEGRAM_BOT_TOKEN,
        PRO_CHAT_ID as TELEGRAM_CHAT_ID
    )
except ImportError as e:
    print(f"⚠️ Error importing Telegram config: {e}")
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""

# =====================================================
# ETF CONFIG
# =====================================================
INDEX_ETF_MAP = {
    "NIFTY 50": ("NIFTY 50", "NIFTYBEES"),
    "BANK NIFTY": ("NIFTY BANK", "BANKBEES"),
    "NIFTY MID SELECT 150": ("NIFTY MID SELECT", "MID150BEES")
}

CAPITAL = {3: 10000, 6: 10000, 9: 20000}

# =====================================================
# TELEGRAM (RETRY SAFE)
# =====================================================
def send_telegram(msg: str):
    if not msg.strip():
        return

    for attempt in range(3):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=10
            )
            if response.status_code == 200:
                return
            else:
                print(f"⚠️ Telegram failed: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Telegram retry {attempt+1}: {e}")
            time.sleep(2)

# =====================================================
# DB INIT
# =====================================================
def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    c = db.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS etf_gtt_levels (
        index_name TEXT PRIMARY KEY,
        etf_symbol TEXT,
        index_high_close REAL,
        high_date TEXT,
        etf_close_on_high REAL,
        buy_3 REAL,
        qty_3 INTEGER,
        buy_6 REAL,
        qty_6 INTEGER,
        buy_9 REAL,
        qty_9 INTEGER,
        created_at TEXT
    )
    """)

    db.commit()
    db.close()

# =====================================================
# HELPERS
# =====================================================
def get_token(token_map, symbol):
    token = token_map.get(symbol)
    if not token:
        raise Exception(f"Instrument token not found: {symbol}")
    return token

def index_high_close_last_30(kite, token):
    to_d = datetime.now()
    from_d = to_d - timedelta(days=30)

    data = kite.historical_data(token, from_d, to_d, "day")
    if not data:
        raise Exception("No index data")

    df = pd.DataFrame(data).tail(30)

    row = df.loc[df["close"].idxmax()]
    return round(row["close"], 2), row["date"].date()

def etf_close_on_date(kite, token, date):
    data = kite.historical_data(token, date, date, "day")
    if not data:
        raise Exception(f"No ETF data for {date}")
    return round(data[0]["close"], 2)

# =====================================================
# MAIN ENTRY
# =====================================================
def run_etf_accumulator(kite):
    init_db()
    print(">>> ETF accumulator engine started")

    # =========================
    # SAFE INSTRUMENT FETCH (FIX)
    # =========================
    token_map = {}

    for attempt in range(3):
        try:
            instruments = kite.instruments("NSE")
            token_map = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}
            break
        except Exception as e:
            print(f"⚠️ Instrument fetch failed (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(3)
            else:
                raise

    db = sqlite3.connect(DB_FILE)
    cur = db.cursor()

    msg_new = "📌 NEW ETF GTT LEVELS (INDEX HIGH UPDATED)\n\n"
    new_high_found = False

    for display_name, (index_symbol, etf_symbol) in INDEX_ETF_MAP.items():

        try:
            idx_token = get_token(token_map, index_symbol)
            etf_token = get_token(token_map, etf_symbol)

            high_close, high_date = index_high_close_last_30(kite, idx_token)

            cur.execute("""
                SELECT index_high_close FROM etf_gtt_levels
                WHERE index_name=?
            """, (display_name,))
            row = cur.fetchone()

            # ---------------- NO CHANGE ----------------
            if row and float(row[0]) == high_close:
                continue

            # ---------------- NEW HIGH ----------------
            etf_close = etf_close_on_date(kite, etf_token, high_date)

            buy_3 = round(etf_close * 0.97, 2)
            buy_6 = round(etf_close * 0.94, 2)
            buy_9 = round(etf_close * 0.91, 2)

            qty_3 = math.floor(CAPITAL[3] / buy_3)
            qty_6 = math.floor(CAPITAL[6] / buy_6)
            qty_9 = math.floor(CAPITAL[9] / buy_9)

            cur.execute("""
            INSERT OR REPLACE INTO etf_gtt_levels
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                display_name,
                etf_symbol,
                high_close,
                str(high_date),
                etf_close,
                buy_3, qty_3,
                buy_6, qty_6,
                buy_9, qty_9,
                datetime.now().isoformat()
            ))
            db.commit()

            new_high_found = True

            msg_new += (
                f"{display_name}\n"
                f"{etf_symbol} (High on {high_date})\n"
                f"3% ₹{buy_3} | Qty {qty_3}\n"
                f"6% ₹{buy_6} | Qty {qty_6}\n"
                f"9% ₹{buy_9} | Qty {qty_9}\n\n"
            )

        except Exception as e:
            print(f"⚠️ Error processing {display_name}: {e}")
            continue

    db.close()

    if new_high_found:
        send_telegram(msg_new)
        print(">>> ETF accumulator engine completed (new levels found)")
        return True

    print(">>> ETF accumulator engine completed (no change)")
    return False