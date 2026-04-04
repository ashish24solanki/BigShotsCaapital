# =====================================================
# PORTFOLIO SUMMARY — ERROR-FREE VERSION (DB LOCK FIXED)
# =====================================================

import os
import sys
import sqlite3
import logging
import requests
import webbrowser
import pandas as pd
import time
from datetime import datetime, timedelta, date

from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET
from config.bot_config import PORT_BOT_TOKEN, PORT_BOT_CHAT_ID
from support.utils import (
    calculate_sl_t10_ema20,
    check_pyramiding_signal,
)

# =====================================================
# CONFIG
# =====================================================
PORTFOLIO_DB = r"C:\Users\ask4b\OneDrive\Documents\BigShotsCapital\database\port_G.db"
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

LOOKBACK_DAYS = 600
MIN_CANDLES = 200
MAX_PYRAMIDING = 10
TODAY = date.today().isoformat()

# =====================================================
# LOGGING
# =====================================================
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "portfolio_smry.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# =====================================================
# DATABASE CONNECTION HELPER (with lock handling)
# =====================================================
def get_db_connection():
    return sqlite3.connect(
        PORTFOLIO_DB,
        timeout=30,
        check_same_thread=False,
        isolation_level=None  # auto-commit mode
    )

def execute_with_retry(query, params=(), retries=3, delay=5):
    con = get_db_connection()
    for attempt in range(1, retries + 1):
        try:
            cur = con.cursor()
            cur.execute(query, params)
            con.commit()
            return cur
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries:
                log.warning(f"Database locked - retrying in {delay}s ({attempt}/{retries})...")
                time.sleep(delay)
                continue
            else:
                raise
        finally:
            con.close()

# =====================================================
# TELEGRAM
# =====================================================
def send_telegram(msg: str):
    if not msg.strip():
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{PORT_BOT_TOKEN}/sendMessage",
            data={"chat_id": PORT_BOT_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        log.info("📨 Telegram message sent")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

# =====================================================
# ZERODHA LOGIN
# =====================================================
def get_kite():
    kite = KiteConnect(api_key=API_KEY)

    if os.path.exists(ACCESS_TOKEN_FILE):
        try:
            with open(ACCESS_TOKEN_FILE, "r") as f:
                token = f.read().strip()
            kite.set_access_token(token)
            kite.profile()
            log.info("Zerodha logged in (cached token)")
            return kite
        except (TokenException, Exception) as e:
            log.warning(f"Cached token invalid/expired: {e}")

    log.info("Zerodha login required")
    webbrowser.open(kite.login_url())
    raw = input("Paste request_token or full URL: ").strip()
    request_token = raw.split("request_token=")[1].split("&")[0] if "request_token=" in raw else raw

    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    kite.set_access_token(access_token)
    log.info("Zerodha login successful (new token)")
    return kite

# =====================================================
# DB HELPERS
# =====================================================
def read_active_db():
    con = get_db_connection()
    try:
        df = pd.read_sql(
            """
            SELECT symbol, sl, pyramiding_count, e_sl, last_low, entry_date, pyramid_date
            FROM portfolio_holdings
            WHERE exit_date = '0'
            """,
            con,
        )
        return df
    finally:
        con.close()

def update_sl_full(symbol, sl, e_sl, last_low):
    execute_with_retry(
        """
        UPDATE portfolio_holdings
        SET sl=?, e_sl=?, last_low=?, updated_at=?
        WHERE symbol=? AND exit_date = '0'
        """,
        (
            round(sl, 1) if sl is not None else None,
            round(e_sl, 1) if e_sl is not None else None,
            round(last_low, 1) if last_low is not None else None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            symbol,
        )
    )

def inc_pyramiding(symbol):
    execute_with_retry(
        """
        UPDATE portfolio_holdings
        SET pyramiding_count = pyramiding_count + 1,
            pyramid_date = ?
        WHERE symbol=? AND pyramiding_count < ? AND exit_date = '0'
        """,
        (TODAY, symbol, MAX_PYRAMIDING)
    )

def log_update(update_type, symbol, value):
    execute_with_retry(
        """
        INSERT INTO today_updates 
        (update_date, update_timestamp, update_type, symbol, value)
        VALUES (?, ?, ?, ?, ?)
        """,
        (TODAY, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), update_type, symbol, value)
    )
    log.info(f"[DB LOG] {update_type} for {symbol}: {value}")

# =====================================================
# DATA FETCH
# =====================================================
def get_daily_df(kite, token):
    try:
        data = kite.historical_data(
            instrument_token=token,
            from_date=datetime.now() - timedelta(days=LOOKBACK_DAYS),
            to_date=datetime.now(),
            interval="day",
        )
        df = pd.DataFrame(data)
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df
    except Exception as e:
        log.error(f"Failed to fetch historical data for token {token}: {e}")
        return None

# =====================================================
# MAIN
# =====================================================
def main():
    log.info("========== PORTFOLIO SYNC START ==========")

    # Create/clean today_updates table
    execute_with_retry("""
        CREATE TABLE IF NOT EXISTS today_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            update_date TEXT,
            update_timestamp TEXT,
            update_type TEXT,
            symbol TEXT,
            value TEXT
        )
    """)
    execute_with_retry("DELETE FROM today_updates WHERE update_date < date('now', '-2 day')")

    kite = get_kite()


    # =================================================
    # STAGE 0 — CLEAN UNUSED SYMBOLS FROM DATABASE
    # =================================================
    log.info("STAGE 0 — DB CLEANUP")

    try:
        holdings = {h["tradingsymbol"] for h in kite.holdings()}
    except:
        holdings = set()

    try:
        pos_data = kite.positions()
        positions = {p["tradingsymbol"] for p in pos_data.get("net",[])}
    except:
        positions = set()

    active_symbols = holdings.union(positions)

    con = get_db_connection()
    try:
        cur = con.cursor()

        cur.execute("""
            SELECT symbol, exit_date
            FROM portfolio_holdings
        """)
        rows = cur.fetchall()

        delete_list = []

        for symbol, exit_date in rows:
            symbol = str(symbol).strip()

            # delete invalid symbols
            if not symbol or str(symbol).lower() == "nan":
                delete_list.append(symbol)
                continue
            # delete derivatives
            if any(x in symbol for x in ["FUT", "CE", "PE"]):
                delete_list.append(symbol)
                continue

            # delete only closed trades
            if str(exit_date) != '0':
                delete_list.append(symbol)
                continue

            # delete if Not in Kite holdings
            if symbol not in active_symbols:
                delete_list.append(symbol)
                

            
        
        delete_list = list(set(delete_list))

        for sym in delete_list:
            cur.execute(
                "DELETE FROM portfolio_holdings WHERE symbol = ?",
                (sym,)
            )
            log.info(f"[DB CLEAN] Removed -> {sym}")

        con.commit()

    except Exception as e:
        log.error(f"DB cleanup error: {e}")

    finally:
        con.close()

######################################################################################

    # Fetch token map once
    log.info("Fetching NSE instruments...")
    try:
        instruments = kite.instruments("NSE")
        token_map = {i["tradingsymbol"]: i["instrument_token"] for i in instruments}
        log.info(f"Loaded {len(token_map)} instrument tokens")
    except Exception as e:
        log.error(f"Instruments fetch failed: {e}")
        token_map = {}

    # STAGE 1 — ORDER SYNC
    log.info("STAGE 1 — ORDER SYNC")
    try:
        orders = kite.orders()
    except Exception as e:
        log.error(f"Order fetch failed: {e}")
        orders = []

    for o in orders:
        if o["status"] != "COMPLETE":
            continue
        symbol = o["tradingsymbol"]
        if symbol.endswith(("FUT", "CE", "PE")):
            log.info(f"[ORDER] SKIP derivative -> {symbol}")
            continue
        txn = o["transaction_type"]
        order_date = pd.to_datetime(o["order_timestamp"]).date().isoformat()

        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT entry_date, pyramid_date FROM portfolio_holdings WHERE symbol = ? AND exit_date = '0'",
                (symbol,)
            )
            row = cur.fetchone()

            if txn == "BUY":
                if not row:
                    cur.execute(
                        """
                        INSERT INTO portfolio_holdings 
                        (symbol, entry_date, pyramid_date, exit_date, pyramiding_count) 
                        VALUES (?, ?, ?, '0', 0)
                        """,
                        (symbol, order_date, order_date)
                    )
                    con.commit()
                    log_update("BUY_NEW", symbol, "New Entry")
                    log.info(f"[ORDER] BUY NEW → {symbol}")
                else:
                    entry_date, pyramid_date = row
                    if entry_date == TODAY or pyramid_date == TODAY:
                        log.info(f"[ORDER] BUY SKIP (already processed today) -> {symbol}")
                    else:
                        cur.execute(
                            """
                            UPDATE portfolio_holdings 
                            SET entry_date=?, pyramid_date=?, pyramiding_count=pyramiding_count+1, exit_date='0' 
                            WHERE symbol=?
                            """,
                            (order_date, order_date, symbol)
                        )
                        con.commit()
                        log_update("BUY_ADD_ON", symbol, "Pyramid Entry")
                        log.info(f"[ORDER] BUY ADD-ON → Incremented pyramiding for {symbol}")
            elif txn == "SELL":
                cur.execute(
                    "UPDATE portfolio_holdings SET exit_date=? WHERE symbol=? AND exit_date='0'",
                    (order_date, symbol)
                )
                if cur.rowcount > 0:
                    con.commit()
                    log.info(f"[ORDER] SELL → Exited {symbol}")

        except Exception as e:
            log.error(f"Order processing error for {symbol}: {e}")
        finally:
            con.close()

    # STAGE 3 — SL CHECK & TRAILING
    log.info("STAGE 3 — SL CHECK & TRAILING")
    db_df = read_active_db()
    if db_df.empty:
        log.info("No active holdings to process for SL trailing")
    else:
        for _, rec in db_df.iterrows():
            sym = rec["symbol"]
            log.info(f"[SL] Checking -> {sym}")

            token = token_map.get(sym)
            if not token:
                log.info(f"[SL] SKIP -> no token for {sym}")
                continue

            df = get_daily_df(kite, token)
            if df is None or len(df) < 1:
                log.info(f"[SL] SKIP -> no/invalid data for {sym}")
                continue

            old_sl = rec["sl"] if pd.notna(rec["sl"]) else None
            previous_e_sl = rec["e_sl"] if pd.notna(rec["e_sl"]) else 0
            previous_low = rec["last_low"] if pd.notna(rec["last_low"]) else None

            new_sl = None
            new_e_sl = 0
            new_last_low = previous_low
            sl_data = None

            if len(df) < MIN_CANDLES:
                new_sl = round(df.iloc[-1]["close"] * 0.9, 1)
                log.info(f"[SL] Fallback SL (few candles) -> {new_sl}")
            else:
                sl_data = calculate_sl_t10_ema20(
                    df,
                    TODAY,
                    previous_e_sl = previous_e_sl,
                    previous_low = previous_low,
                    previous_sl = old_sl,
                )
                if sl_data and sl_data.get("final_sl") is not None:
                    new_sl = round(sl_data["final_sl"], 1)
                    new_e_sl = round(sl_data["e_sl"], 1)
                    new_last_low = round(sl_data["latest_low"], 1)

            if new_sl is None:
                log.info(f"[SL] No valid SL calculated for {sym}")
                continue

            if old_sl is not None and new_sl < old_sl:
                log.info(f"[SL SAFETY] Preventing SL decrease for {sym}: {new_sl} < {old_sl} → keeping {old_sl}")
                final_sl = old_sl
            else:
                final_sl = new_sl
            
                

            log.info(f"[SL] {sym} | Old: {old_sl} | Calc: {new_sl} | Final: {final_sl}")

            if final_sl != old_sl or (new_e_sl > 0 and new_e_sl != previous_e_sl):  
                update_sl_full(sym, final_sl, new_e_sl, new_last_low)

                if new_e_sl > 0:
                    value = f"old:{old_sl} → new:{final_sl} | E-SL:{new_e_sl}"
                else:
                    value = f"old:{old_sl} → new:{final_sl}" if old_sl is not None else f"new:{final_sl}"
                log_update("SL_UPDATE", sym, value)

            if new_e_sl > 0:
                log.info(f"[SL] E-SL active for {sym} -> {new_e_sl}")

    # STAGE 4 — PYRAMID CHECK
    log.info("STAGE 4 — PYRAMID CHECK")
    db_df = read_active_db()
    for _, rec in db_df.iterrows():
        sym = rec["symbol"]
        log.info(f"[PYR] Checking -> {sym}")

        if rec["pyramiding_count"] >= MAX_PYRAMIDING:
            log.info(f"[PYR] SKIP -> max pyramiding reached for {sym}")
            continue

        token = token_map.get(sym)
        if not token:
            log.info(f"[PYR] SKIP -> no token for {sym}")
            continue

        df = get_daily_df(kite, token)
        if df is None or len(df) < MIN_CANDLES:
            log.info(f"[PYR] SKIP -> insufficient data for {sym}")
            continue

        signal = check_pyramiding_signal(df)
        if not signal.get("passed", False):
            log.info(f"[PYR] FAIL for {sym}")
            continue

        buy_above = signal.get("buy_trigger")
        if df.iloc[-1]["high"] >= buy_above:
            inc_pyramiding(sym)
            log_update("PYRAMID_TRIGGER", sym, f"Buy Above {buy_above}")
            log.info(f"[PYR] TRIGGERED → Buy Above {buy_above} for {sym}")
        else:
            log.info(f"[PYR] WAIT → Trigger {buy_above} not hit for {sym}")

    # =================================================
    # TELEGRAM SUMMARY — 3 SEPARATE MESSAGES + LOGS
    # =================================================
    today_str = datetime.now().strftime("%d-%b-%Y")
    con = get_db_connection()
    try:
        df_updates = pd.read_sql(
            """
            SELECT update_type, symbol, value
            FROM today_updates
            WHERE update_date = ?
            ORDER BY symbol, update_timestamp
            """,
            con,
            params=(TODAY,)
        )
    finally:
        con.close()

    log.info(f"Found {len(df_updates)} updates in DB for today.")

    # 1. #today's entry
    entry_updates = df_updates[df_updates['update_type'].isin(['BUY_NEW', 'BUY_ADD_ON'])]
    if not entry_updates.empty:
        entry_updates = entry_updates.sort_values('symbol')
        lines = []
        for _, row in entry_updates.iterrows():
            symbol = row['symbol']
            con = get_db_connection()
            try:
                sl_row = con.execute("SELECT sl FROM portfolio_holdings WHERE symbol = ? AND exit_date = '0'", (symbol,)).fetchone()
                sl = sl_row[0] if sl_row and sl_row[0] is not None else 'N/A'
            finally:
                con.close()
            lines.append(f"{symbol} → SL {sl}")
        send_telegram(
            f"<b>#today's entry ({today_str})</b>\n\n" +
            "\n".join(lines)
        )
        log.info("today orders telegram sent")
    else:
        log.info("No today's entry updates - skipping telegram")

    # 2. #SL updated
    sl_updates = df_updates[df_updates['update_type'] == 'SL_UPDATE']
    if not sl_updates.empty:
        sl_updates = sl_updates.sort_values('symbol')
        lines = [f"{row['symbol']} → {row['value']}" for _, row in sl_updates.iterrows()]
        send_telegram(
            f"<b>#SL updated ({today_str})</b>\n\n" +
            "\n".join(lines)
        )
        log.info("SL updates telegram message sent")
    else:
        log.info("No SL updates - skipping telegram")

    # 3. #Pyramiding
    pyramid_triggers = df_updates[df_updates['update_type'] == 'PYRAMID_TRIGGER']
    if not pyramid_triggers.empty:
        pyramid_triggers = pyramid_triggers.sort_values('symbol')
        lines = [f"{row['symbol']} → {row['value']}" for _, row in pyramid_triggers.iterrows()]
        send_telegram(
            f"<b>#Pyramiding ({today_str})</b>\n\n" +
            "\n".join(lines)
        )
        log.info("Pyramiding message telegram sent")
    else:
        log.info("No pyramiding triggers - skipping telegram")

    # =================================================
    # FULL SUMMARY OPTION
    # =================================================
    full_summary = input("\nWould you like to send full summary on Telegram? (Y/N): ").strip().upper()
    if full_summary == "Y":
        con = get_db_connection()
        try:
            active_df = pd.read_sql(
                """
                SELECT symbol, sl
                FROM portfolio_holdings
                WHERE exit_date = '0' AND sl IS NOT NULL
                ORDER BY symbol
                """,
                con,
            )
        finally:
            con.close()

        if not active_df.empty:
            sl_lines = [f"{row['symbol']} → SL {row['sl']}" for _, row in active_df.iterrows()]
            send_telegram(
                f"<b>📊 ALL ACTIVE POSITIONS & SL ({today_str})</b>\n\n" +
                "\n".join(sl_lines)
            )
        else:
            send_telegram("<b>No active positions with SL found</b>")

        if not pyramid_triggers.empty:
            pyr_lines = [f"{row['symbol']} → {row['value']}" for _, row in pyramid_triggers.iterrows()]
            send_telegram(
                f"<b>📈 TODAY'S PYRAMIDING TRIGGERS ({today_str})</b>\n\n" +
                "\n".join(pyr_lines)
            )
        else:
            send_telegram("<b>No pyramid triggers today</b>")

        log.info("Full summary sent to Telegram")
    else:
        log.info("Full summary skipped")

    log.info("========== SCRIPT END ==========")

if __name__ == "__main__":
    main()