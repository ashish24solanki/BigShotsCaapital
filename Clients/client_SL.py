import os
import sys
import sqlite3
import logging
import webbrowser
from datetime import datetime, timedelta, date

import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

# =====================================================
# PATH SETUP (MATCHING YOUR PROJECT STRUCTURE)
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET
from support.utils import calculate_sl_t10_ema20

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

CLIENT_DIR = os.path.join(BASE_DIR, "Clients")
OUTPUT_DIR = os.path.join(CLIENT_DIR, "Output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DB_PATH = os.path.join(CLIENT_DIR, "client_SL.db")

# =====================================================
# LOGGING
# =====================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

TODAY = date.today().isoformat()
LOOKBACK_DAYS = 600
MIN_CANDLES = 200

# =====================================================
# LOGIN (YOUR EXACT STYLE)
# =====================================================
def get_kite():
    kite = KiteConnect(api_key=API_KEY)

    if os.path.exists(ACCESS_TOKEN_FILE):
        token = open(ACCESS_TOKEN_FILE).read().strip()
        if token:
            kite.set_access_token(token)
            try:
                kite.profile()
                log.info("Login successful (cached token)")
                return kite
            except TokenException:
                log.info("Cached token invalid")

    webbrowser.open(kite.login_url())
    raw = input("Paste request_token or full URL: ").strip()
    request_token = raw.split("request_token=")[1].split("&")[0] if "request_token=" in raw else raw

    data = kite.generate_session(request_token, api_secret=API_SECRET)

    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(data["access_token"])

    kite.set_access_token(data["access_token"])
    log.info("Login successful (new token)")
    return kite

# =====================================================
# INIT DB
# =====================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS client_sl (
            symbol TEXT PRIMARY KEY,
            sl REAL DEFAULT 0,
            e_sl REAL DEFAULT 0,
            last_low REAL DEFAULT 0,
            updated_at TEXT
        )
    """)
    con.commit()
    con.close()

# =====================================================
# READ CSV
# =====================================================
def read_symbols_from_csv(csv_path):
    df = pd.read_csv(csv_path)
    symbols = df.iloc[:, 0].dropna().astype(str).str.strip().unique().tolist()
    return symbols

# =====================================================
# E-SL LOGIC
# =====================================================
def calculate_esl(symbol, final_sl, df, previous_esl, previous_low):
    current_close = float(df.iloc[-1]["close"])
    current_low = float(df.iloc[-1]["low"])

    if final_sl <= current_close:
        return 0, previous_low

    log.info(f"[E-SL] ACTIVATED -> SL {round(final_sl,2)} > Close {current_close}")

    if previous_esl == 0:
        new_esl = round(current_low * 0.98, 2)
        log.info(f"[E-SL] INIT -> {new_esl}")
        return new_esl, current_low

    if current_low < previous_low:
        log.info("[E-SL] LOW LOWER -> E-SL unchanged")
        return previous_esl, previous_low

    new_esl = round(current_low * 0.98, 2)

    if new_esl > previous_esl:
        log.info(f"[E-SL] TRAIL UP -> {previous_esl} -> {new_esl}")
        return new_esl, current_low

    log.info("[E-SL] NO CHANGE")
    return previous_esl, previous_low

# =====================================================
# ENGINE
# =====================================================
def run_engine():
    init_db()
    kite = get_kite()

    csv_path = input("Enter full path of client CSV: ").strip()
    symbols = read_symbols_from_csv(csv_path)

    instruments = kite.instruments("NSE")
    token_map = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}

    results = []

    for sym in symbols:
        log.info(f"========== {sym} ==========")

        token = token_map.get(sym)
        if not token:
            log.info("No instrument token")
            continue

        df = pd.DataFrame(
            kite.historical_data(
                token,
                datetime.now() - timedelta(days=LOOKBACK_DAYS),
                datetime.now(),
                "day",
            )
        )

        if df.empty or len(df) < MIN_CANDLES:
            log.info("Insufficient candles")
            continue

        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        sl_data = calculate_sl_t10_ema20(df, TODAY)
        if not sl_data:
            continue

        final_sl = round(sl_data["final_sl"], 1)

        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()

        cur.execute("SELECT e_sl, last_low FROM client_sl WHERE symbol=?", (sym,))
        row = cur.fetchone()

        if row:
            prev_esl, prev_low = row
        else:
            prev_esl, prev_low = 0, 0
            cur.execute("INSERT OR IGNORE INTO client_sl (symbol) VALUES (?)", (sym,))

        e_sl, new_low = calculate_esl(sym, final_sl, df, prev_esl, prev_low)

        cur.execute("""
            UPDATE client_sl
            SET sl=?, e_sl=?, last_low=?, updated_at=?
            WHERE symbol=?
        """, (
            final_sl,
            e_sl,
            new_low,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            sym
        ))

        con.commit()
        con.close()

        log.info(f"FINAL → SL={final_sl} | E-SL={e_sl}")

        results.append({
            "symbol": sym,
            "SL": final_sl,
            "E-SL": e_sl
        })

    # =====================================================
    # EXPORT CSV
    # =====================================================
    if results:
        output_df = pd.DataFrame(results)
        output_file = os.path.join(
            OUTPUT_DIR,
            f"client_SL_output_{date.today().strftime('%Y%m%d')}.csv"
        )
        output_df.to_csv(output_file, index=False)
        log.info(f"CSV EXPORTED → {output_file}")

    log.info("========== ENGINE COMPLETE ==========")

# =====================================================
if __name__ == "__main__":
    run_engine()
