# =====================================================
# MAIN ENGINE — STATE-DRIVEN (TERMINAL + TELEGRAM OPTIONAL)
# =====================================================
# • Runs ONLY for today
# • Orchestrates all engines
# • Optional terminal output (like Telegram toggle)
# =====================================================

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, date
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
from engines.divergence_engine import run_divergence_engine
from engines.etf_engine import run_etf_accumulator
from support.telegram import send_message
from config.kite_config import API_KEY, API_SECRET

# =====================================================
# DATABASE PATHS
# =====================================================
DB_MOMENTUM   = os.path.join(BASE_DIR, "database", "momentum.db")
DB_DIVERGENCE = os.path.join(BASE_DIR, "database", "divergence.db")

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
MAIN_LOG = os.path.join(LOG_DIR, "mainengine.log")

TODAY = date.today().isoformat()

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
def ask_yes_no(q: str) -> bool:
    return input(f"{q} [y/N]: ").strip().lower() == "y"

# =====================================================
# ZERODHA LOGIN
# =====================================================
def get_kite():
    kite = KiteConnect(api_key=API_KEY)

    if os.path.exists(ACCESS_TOKEN_FILE):
        token = open(ACCESS_TOKEN_FILE).read().strip()
        if token:
            kite.set_access_token(token)
            try:
                kite.profile()
                main_log("Zerodha logged in")
                return kite
            except TokenException:
                main_log("Zerodha token expired")

    main_log("Zerodha login required")
    webbrowser.open(kite.login_url())

    raw = input("Paste request_token or full URL: ").strip()
    request_token = (
        raw.split("request_token=")[1].split("&")[0]
        if "request_token=" in raw else raw
    )

    session = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = session["access_token"]

    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    kite.set_access_token(access_token)
    main_log("Zerodha login successful")
    return kite

# =====================================================
# DB LOADERS
# =====================================================
def load_momentum():
    con = sqlite3.connect(DB_MOMENTUM)
    df = pd.read_sql("SELECT * FROM momentum_trades", con)
    con.close()
    return df

def load_divergence_signals():
    con = sqlite3.connect(DB_DIVERGENCE)
    df = pd.read_sql("SELECT * FROM divergence_signals", con)
    con.close()
    return df

def load_divergence_trades():
    con = sqlite3.connect(DB_DIVERGENCE)
    df = pd.read_sql("SELECT * FROM divergence_trades", con)
    con.close()
    return df

# =====================================================
# TERMINAL PRINTER
# =====================================================
def print_block(title, lines):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    for line in lines:
        print(line)

# =====================================================
# MAIN
# =====================================================
def main():
    main_log("=== MAIN ENGINE STARTED ===")

    kite = get_kite()

    if ask_yes_no("Do you want to update OHLC data from Zerodha?"):
        main_log("Updating market OHLC data...")
        update_market_ohlc(kite)
        main_log("Market OHLC update completed")

    send_telegram = ask_yes_no("Do you want to send Telegram messages?")
    show_terminal = ask_yes_no("Do you want to see signals in terminal?")

    main_log(f"RUN DATE = {TODAY}")

    # ---------------- MOMENTUM ENGINE ----------------
    main_log("Running Momentum Engine")
    run_momentum_engine()
    main_log("Momentum Engine completed")

    # ---------------- DIVERGENCE ENGINE ----------------
    main_log("Running Divergence Engine")
    run_divergence_engine()
    main_log("Divergence Engine completed")

    # ---------------- ETF ENGINE ----------------
    main_log("Starting ETF accumulator engine")
    etf_result = run_etf_accumulator(kite)
    main_log("ETF engine completed" if etf_result else "ETF engine completed → no change")

    # ---------------- LOAD DATA ----------------
    momo = load_momentum()
    div_sig = load_divergence_signals()
    div_trd = load_divergence_trades()

    header = f"📅 Date: {TODAY}\n"
    messages = []

    # ---------------- MOMENTUM ----------------
    if not momo.empty:

        new_entries = momo[
            (momo.status == "ACTIVE") &
            (momo.entry_date == TODAY)
        ].sort_values("symbol")

        if not new_entries.empty:
            lines = [
                f"{r.symbol} | Buy: {round(float(r.buy_above),1)} | SL: {round(float(r.sl),1)}"
                for _, r in new_entries.iterrows()
            ]
            if show_terminal:
                print_block("🟢 MOMENTUM — NEW ENTRIES", lines)
            messages.append(header + "🟢 NEW ENTRIES\n" + "\n".join(lines))

        sl_updates = momo[
            (momo.status == "ACTIVE") &
            (momo.sl_updated_date == TODAY)
        ].sort_values("symbol")

        if not sl_updates.empty:
            lines = [
                f"{r.symbol} | SL: {round(float(r.sl),1)}"
                for _, r in sl_updates.iterrows()
            ]
            if show_terminal:
                print_block("🟡 MOMENTUM — SL UPDATED", lines)
            messages.append(header + "🟡 SL UPDATED\n" + "\n".join(lines))

        pyramids = momo[
            (momo.status == "ACTIVE") &
            (momo.pyramiding_date == TODAY)
        ].sort_values("symbol")

        if not pyramids.empty:
            lines = [
                f"{r.symbol} | Buy Above: {round(float(r.buy_above),1)}"
                for _, r in pyramids.iterrows()
            ]
            if show_terminal:
                print_block("📈 MOMENTUM — PYRAMIDING", lines)
            messages.append(header + "📈 PYRAMIDING\n" + "\n".join(lines))

        exited = momo[
            (momo.status == "EXITED") &
            (momo.exit_date == TODAY)
        ].sort_values("symbol")

        if not exited.empty:
            lines = [
                f"{r.symbol} | SL: {round(float(r.sl),1)}"
                for _, r in exited.iterrows()
            ]
            if show_terminal:
                print_block("🔴 MOMENTUM — SL HIT", lines)
            messages.append(header + "🔴 SL HIT\n" + "\n".join(lines))

    # ---------------- DIVERGENCE ----------------
    if not div_sig.empty:
        today_sig = div_sig[div_sig.signal_date == TODAY].sort_values("symbol")
        if not today_sig.empty:
            lines = [
                f"{r.symbol} | {r.divergence_type} | TF: {r.timeframe}"
                for _, r in today_sig.iterrows()
            ]
            if show_terminal:
                print_block("🟣 DIVERGENCE — NEW SIGNALS", lines)

    if not div_trd.empty:
        today_trd = div_trd[div_trd.entry_date == TODAY].sort_values("symbol")
        if not today_trd.empty:
            lines = [
                f"{r.symbol} | Entry: {round(float(r.entry_price),1)} | SL: {round(float(r.sl),1)}"
                for _, r in today_trd.iterrows()
            ]
            if show_terminal:
                print_block("🟢 DIVERGENCE — NEW TRADES", lines)

    # ---------------- TELEGRAM ----------------
    if send_telegram:
        for msg in messages:
            send_message(msg)
        main_log("Telegram messages sent")

    main_log("=== MAIN ENGINE COMPLETED ===")

# =====================================================
if __name__ == "__main__":
    main()
