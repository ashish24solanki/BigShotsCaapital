# =====================================================
# MAIN ENGINE G — FINAL ERROR-FREE VERSION
# =====================================================

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import webbrowser

from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# =====================================================
# ENGINE IMPORTS
# =====================================================
from main.market_data import update_market_ohlc
from engines.momentum_engine import run_momentum_engine
from engines.etf_engine import run_etf_accumulator
from support.telegram import send_message
from config.kite_config import API_KEY, API_SECRET
from support.utils import calculate_sl_t10_ema20, check_pyramiding_signal

# =====================================================
# DATABASE PATHS
# =====================================================
DB_MOMENTUM    = os.path.join(BASE_DIR, "database", "momentum.db")
DB_OHLC        = os.path.join(BASE_DIR, "database", "market_ohlc.db")


LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
MAIN_LOG = os.path.join(LOG_DIR, "mainengine_g.log")

TODAY = date.today().isoformat()

# =====================================================
# MTF CONFIG
# =====================================================
MTF_FILE = os.path.join(BASE_DIR, "database", "Zerodha_MTF.csv")


def load_mtf_data():
    try:
        df = pd.read_csv(MTF_FILE)

        # normalize
        df.columns = [c.strip().lower() for c in df.columns]

        main_log(f"[MTF DEBUG] Columns: {df.columns.tolist()}")

        mtf_map = {}

        for _, row in df.iterrows():
            sym = str(row["tradingsymbol"]).strip().upper()
            margin = float(row["margin"])

            if sym and margin > 0:
                mtf_map[sym] = margin

        main_log(f"[MTF] Loaded {len(mtf_map)} symbols")
        return mtf_map

    except Exception as e:
        main_log(f"[MTF ERROR] {e}")
        return {}

# =====================================================
# MTF QTY CALCULATION (₹10k–₹10.5k, multiple of 5)
# =====================================================
def calculate_mtf_qty(buy_price, margin, target_cap=10000, max_cap=10500):
    try:
        if margin <= 0 or buy_price <= 0:
            return 0

        best_qty = 0
        best_diff = float("inf")

        # Step 1: find best qty (multiple of 5)
        max_qty = int((target_cap / (margin / 100)) / buy_price) * 2
        max_qty = max(5, (max_qty // 5) * 5)

        for qty in range(5, max_qty + 1, 5):
            exposure = qty * buy_price
            used_cap = exposure * (margin / 100)

            diff = abs(used_cap - target_cap)

            if diff < best_diff:
                best_diff = diff
                best_qty = qty

        # Step 2: adjust if exceeding max_cap
        exposure = best_qty * buy_price
        used_cap = exposure * (margin / 100)

        if used_cap > max_cap:
            for reduce in [1, 2, 3, 4]:
                new_qty = best_qty - reduce
                if new_qty <= 0:
                    break

                exposure = new_qty * buy_price
                used_cap = exposure * (margin / 100)

                if used_cap <= max_cap:
                    return new_qty

        return best_qty

    except Exception as e:
        main_log(f"[MTF QTY ERROR] {e}")
        return 0


# =====================================================
# PORTFOLIO TELEGRAM (MTF SIGNALS)
# =====================================================
import requests
from config.bot_config import PORT_BOT_TOKEN, PORT_BOT_CHAT_ID


def send_portfolio_message(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{PORT_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": PORT_BOT_CHAT_ID,
                "text": msg,
                "parse_mode": "HTML"
            },
            timeout=10,
        )
        main_log("📨 Sent to PORTFOLIO BOT")

    except Exception as e:
        main_log(f"[PORT TELEGRAM ERROR] {e}")

# =====================================================
# LOGGER
# =====================================================
def main_log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(MAIN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# =====================================================
# INPUT HELPERS
# =====================================================
def ask_yes_no(q: str, default="y") -> bool:
    ans = input(f"{q} [Y/n]: ").strip().lower()
    if ans == "":
        return default.lower() == "y"
    return ans == "y"

# =====================================================
# ZERODHA LOGIN
# =====================================================

def get_kite():
    import requests

    kite = KiteConnect(api_key=API_KEY)

    try:
        url = "http://143.110.181.111:5000/token?key=BigShotsCapital_06"
        access_token = requests.get(url, timeout=3).text.strip()

        kite.set_access_token(access_token)
        kite.profile()

        main_log("Zerodha connected (VM token)")
        return kite

    except Exception as e:
        main_log(f"VM token fetch failed: {e}")
        raise Exception("❌ Cannot get access token from VM")

   
# =====================================================
# DB LOADERS
# =====================================================
def load_momentum():
    con = sqlite3.connect(DB_MOMENTUM)
    df = pd.read_sql("SELECT * FROM momentum_trades", con)
    con.close()
    return df


def get_symbol_ohlc_from_db(symbol):
    con = sqlite3.connect(DB_OHLC)
    df = pd.read_sql(
        """
        SELECT date, open, high, low, close, volume
        FROM market_ohlc
        WHERE symbol = ?
        ORDER BY date ASC
        """,
        con, params=(symbol,)
    )
    con.close()

    if df.empty:
        main_log(f"[OHLC] No data in market_ohlc.db for {symbol}")
        return None

    # Force date to date object
    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
    df = df.dropna(subset=['date'])
    df = df.sort_values("date")
    return df

# =====================================================
# ACTIVATION + SL HIT + DAILY SL/E-SL UPDATE
# =====================================================
def check_activate_and_update_active(send_telegram):
    main_log("Checking activations, SL hits & daily SL/E-SL updates (using market_ohlc.db)...")

    con = sqlite3.connect(DB_MOMENTUM)
    df = pd.read_sql(
        """
        SELECT symbol, buy_above, sl, status
        FROM momentum_trades
        WHERE status IN ('WAITING', 'ACTIVE')
        """,
        con
    )
    con.close()

    if df.empty:
        main_log("No WAITING or ACTIVE setups found")
        return

    activated_today = []
    sl_hit_today = []
    sl_updated_today = []
    activated_symbols = set()

    pyramid_triggered = set()
    for _, row in df.iterrows():
        sym = row['symbol']
        buy_above = row['buy_above']
        current_sl = row['sl'] if pd.notna(row['sl']) else None
        status = row['status']

        df_hist = get_symbol_ohlc_from_db(sym)
        if df_hist is None or df_hist.empty:
            main_log(f"[SKIP] No OHLC history for {sym}")
            continue

        if len(df_hist) < 3:
            main_log(f"[SKIP] Not enough candles for {sym}")
            continue

        latest_row = df_hist.iloc[-1]
        latest_high  = float(latest_row['high'])
        latest_low   = float(latest_row['low'])
        latest_close = float(latest_row['close'])

        try:
            # Activation
            if status == 'WAITING' and latest_high >= buy_above:
                main_log(f"[CHECK] {sym} High {latest_high} >= Buy {buy_above}")
                with sqlite3.connect(DB_MOMENTUM) as con:
                    con.execute(
                        "UPDATE momentum_trades SET status = 'ACTIVE' WHERE symbol = ? AND status = 'WAITING'",
                        (sym,)
                    )
                    con.commit()
                status = 'ACTIVE'
                activated_today.append(f"{sym} → Buy Above {buy_above} hit! SL now {current_sl}")
                activated_symbols.add(sym)
                main_log(f"[ACT] ACTIVATED TODAY: {sym} @ {buy_above}")
                continue

            # SL HIT
            if status == 'ACTIVE' and current_sl is not None and latest_low <= current_sl:
                with sqlite3.connect(DB_MOMENTUM) as con:
                    con.execute(
                        "DELETE FROM momentum_trades WHERE symbol = ? AND status = 'ACTIVE'",
                        (sym,)
                    )
                    con.commit()
                sl_hit_today.append(f"{sym} → SL HIT @ {current_sl}")
                main_log(f"[SL HIT] {sym} hit SL {current_sl} today → row deleted")
                continue

            # Trailing update
            if status == 'ACTIVE' and current_sl is not None:
                previous_low = float(df_hist.iloc[-2]["low"]) if len(df_hist) > 1 else None
                sl_data = calculate_sl_t10_ema20(
                    df_hist,
                    TODAY,
                    previous_e_sl= 0,
                    previous_low= previous_low,
                    previous_sl=current_sl
                )
                               
                
                if not sl_data or "final_sl" not in sl_data:
                    new_sl = round(latest_close * 0.90,1)
                    e_sl_calculated = 0
                    with sqlite3.connect(DB_MOMENTUM) as con:
                        con.execute(
                            "UPDATE momentum_trades SET sl = ? WHERE symbol = ?",
                            (new_sl, sym)
                        )
                        con.commit()
                    continue

                calculated_sl = sl_data["final_sl"]
                e_sl_calculated = sl_data.get("e_sl", 0)
                new_sl = max(calculated_sl, current_sl)
                if new_sl > current_sl:
                    sl_updated_today.append(f"{sym} → SL {new_sl}")


            # =====================================================
            # PYRAMIDING CHECK
            # =====================================================
            
            if status == 'ACTIVE' and sym not in activated_symbols and sym not in pyramid_triggered:
                try:
                    df_hist_reset = df_hist.copy()
                    df_hist_reset["date"] = pd.to_datetime(df_hist_reset["date"])

                    pyramid = check_pyramiding_signal(df_hist_reset)

                    if pyramid.get("passed") and sym not in pyramid_triggered:
                        buy_trigger = pyramid.get("buy_trigger")
                        pyramid_triggered.add(sym)

                        main_log(f"[PYRAMID] {sym} → Add position above {buy_trigger}")

                        if send_telegram:
                            send_message(f"📈 PYRAMID ADD: {sym} above {buy_trigger}")

                except Exception as e:
                    main_log(f"[PYRAMID ERROR] {sym}: {e}")    

        except Exception as e:
            main_log(f"[ERROR] Processing {sym}: {e}")

    today_str = datetime.now().strftime("%d-%b-%Y")
    msgs = []

    if activated_today:
        msgs.append(f"<b>🟢 ACTIVATED TODAY ({today_str})</b>\n" + "\n".join(activated_today))

    if sl_hit_today:
        msgs.append(f"<b>🔴 SL HIT TODAY ({today_str})</b>\n" + "\n".join(sl_hit_today))

    if sl_updated_today:
        msgs.append(f"<b>📊 SL UPDATED TODAY - ACTIVE ({today_str})</b>\n" + "\n".join(sl_updated_today))

    if msgs and send_telegram:
        for msg in msgs:
            try:
                send_message(msg)
                main_log("Sent activation/SL-hit/SL-update Telegram")
            except Exception as e:
                main_log(f"Telegram failed: {e}")

    main_log("Activation, SL hit & update check completed")
    



# =====================================================
# MAIN
# =====================================================
def main():
    main_log("=== MAIN ENGINE G STARTED ===")
    main_log(f"RUN DATE = {TODAY}")

    kite = get_kite()

    update_ohlc = ask_yes_no("Update market OHLC data from Zerodha?", default="y")
    if update_ohlc:
        main_log("Updating market OHLC data...")
        try:
            update_market_ohlc(kite)
            main_log("Market OHLC update completed")
        except Exception as e:
            main_log(f"OHLC update failed: {e} → continuing")
    else:
        main_log("Skipping OHLC update (data may be stale)")

    send_telegram = ask_yes_no("Send Telegram messages?", default="y")
    show_terminal = ask_yes_no("Show signals in terminal?", default="y")

    run_momentum = ask_yes_no("Run Momentum Engine?", default="y")
    if run_momentum:
        main_log("Running Momentum Engine G...")
        try:
            import engines.momentum_engine as m
            print("LOADED FILE:", m.__file__)
            m.run_momentum_engine()
            main_log("Momentum Engine G completed")

            check_activate_and_update_active(send_telegram)

        except Exception as e:
            main_log(f"Momentum Engine G failed: {e}")
    else:
        main_log("Momentum Engine skipped by user")


    main_log("Running ETF Accumulator Engine...")
    try:
        etf_result = run_etf_accumulator(kite)
        main_log("ETF Engine completed" if etf_result else "ETF Engine completed (no change)")
    except Exception as e:
        main_log(f"ETF Engine failed: {e}")

    momo = load_momentum()
    mtf_lines = []
    messages = []
    header = f"📅 {TODAY} — Strategy Summary\n"

    if not momo.empty:
        from engines.momentum_engine import get_last_trading_date
        last_trading_date = get_last_trading_date()
        recent_momo = momo[
            (momo.status == "WAITING") &
            (momo.signal_date == momo.signal_date.max())
        ]
        if not recent_momo.empty:
            count = len(recent_momo)
            main_log(f"Found {count} new momentum setups from the last 2 days")
            ##########################################################################
            #lines = [f"{r.symbol} | Buy Above {r.buy_above} | SL {r.sl}" for _, r in recent_momo.iterrows()]

            mtf_map = load_mtf_data()

            pro_lines = []       # for PRO channel (NO qty)
            mtf_lines = []       # for PORTFOLIO bot (WITH qty)

            for _, r in recent_momo.iterrows():
                sym = str(r.symbol).upper()
                sym = sym.replace("-EQ", "").replace(".NS", "").strip()
                buy_above = float(r.buy_above)
                sl = r.sl

                # =========================
                # PRO MESSAGE (NO QTY)
                # =========================
                pro_lines.append(f"{sym} | Buy {buy_above} | SL {sl}")

                # =========================
                # MTF MESSAGE (WITH QTY)
                # =========================
                margin = mtf_map.get(sym)

                if not margin:
                    main_log(f"[MTF SKIP] {sym} not in MTF list")
                    continue

                qty = calculate_mtf_qty(buy_above, margin)

                if qty == 0:
                    main_log(f"[MTF SKIP] {sym} no valid qty in 10k range")
                    continue

                mtf_lines.append(f"{sym} | Buy {buy_above} | Qty {qty} | SL {sl}")

            #########################################################################
            if show_terminal:
                print("\n" + "="*70)
                print(f"🟢 MOMENTUM — RECENT SETUPS TODAY ({count})")
                print("="*70)
                for line in pro_lines:
                    print(line)
            messages.append(header + f"🟢 RECENT MOMENTUM SETUPS ({count})\n" + "\n".join(pro_lines))
        else:
            main_log("No recent momentum setups found")

    if send_telegram and messages:
        full_msg = "\n\n".join(messages)
        try:
            send_message(full_msg)
            main_log("Telegram summary sent")
        except Exception as e:
            main_log(f"Telegram failed: {e}")
    
    # =====================================================
    # SEND MTF SIGNALS TO PORTFOLIO BOT
    # =====================================================
    if send_telegram and mtf_lines:
        try:
            port_msg = f"<b>📊 MTF SETUPS ({TODAY})</b>\n\n" + "\n".join(mtf_lines)
            send_portfolio_message(port_msg)
        except Exception as e:
            main_log(f"Portfolio Telegram failed: {e}")

    main_log("=== MAIN ENGINE G COMPLETED ===")

if __name__ == "__main__":
    main()