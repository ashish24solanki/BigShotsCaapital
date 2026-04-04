# ==========================================================
# WEBSOCKET NIFTY 50 SHORT STRATEGY (STABLE VERSION)
# ==========================================================

import os
import sys
import time
import datetime as dt
import pandas as pd
import webbrowser

from kiteconnect import KiteConnect, KiteTicker
from kiteconnect.exceptions import TokenException

# =====================================================
# PATH SETUP
# =====================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

# =====================================================
# CONFIG
# =====================================================

NIFTY50 = ["RELIANCE", "TCS", "INFY"]
CAPITAL_PER_TRADE = 10000

mode = input("Run in PAPER trading mode? (y/n): ").lower()
PAPER_TRADING = True if mode == "y" else False

print("🧪 PAPER MODE" if PAPER_TRADING else "💰 LIVE MODE")

# =====================================================
# LOGIN
# =====================================================

def get_kite():
    kite = KiteConnect(api_key=API_KEY)

    if os.path.exists(ACCESS_TOKEN_FILE):
        try:
            with open(ACCESS_TOKEN_FILE, "r") as f:
                token = f.read().strip()
            kite.set_access_token(token)
            kite.profile()
            print("✅ Login successful (cached token)")
            return kite
        except:
            print("⚠️ Token expired")

    webbrowser.open(kite.login_url())
    redirected_url = input("Paste FULL redirected URL:\n").strip()

    request_token = redirected_url.split("request_token=")[1].split("&")[0]

    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    kite.set_access_token(access_token)
    print("✅ New login successful")

    return kite


kite = get_kite()
access_token = open(ACCESS_TOKEN_FILE).read().strip()

# =====================================================
# GLOBALS
# =====================================================

instrument_map = {}
reverse_map = {}

candles = {}
active_trades = {}
last_processed_candle = {}

# =====================================================
# LOAD INSTRUMENTS
# =====================================================

def load_instruments():
    instruments = kite.instruments("NSE")

    for ins in instruments:
        if ins["tradingsymbol"] in NIFTY50:
            instrument_map[ins["tradingsymbol"]] = ins["instrument_token"]
            reverse_map[ins["instrument_token"]] = ins["tradingsymbol"]

    print("✅ Instruments loaded")

load_instruments()

# =====================================================
# ORDER FUNCTION
# =====================================================

def place_order(symbol, side, qty, price):
    if PAPER_TRADING:
        print(f"🧪 PAPER → {side} {symbol} | Qty: {qty} | Price: {price}")
        return

    try:
        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange="NSE",
            tradingsymbol=symbol,
            transaction_type=side,
            quantity=qty,
            product="MIS",
            order_type="MARKET"
        )
        print(f"✅ REAL ORDER → {side} {symbol}")
    except Exception as e:
        print(f"❌ Order failed: {e}")

# =====================================================
# CANDLE BUILDER
# =====================================================

def get_candle_start(ts):
    minute = (ts.minute // 30) * 30
    return ts.replace(minute=minute, second=0, microsecond=0)


def update_candle(symbol, price, timestamp):
    candle_time = get_candle_start(timestamp)

    if symbol not in candles:
        candles[symbol] = []

    if not candles[symbol] or candles[symbol][-1]["time"] != candle_time:
        candles[symbol].append({
            "time": candle_time,
            "open": price,
            "high": price,
            "low": price,
            "close": price
        })
    else:
        c = candles[symbol][-1]
        c["high"] = max(c["high"], price)
        c["low"] = min(c["low"], price)
        c["close"] = price

# =====================================================
# STRATEGY
# =====================================================

def calculate_qty(price):
    return max(int(CAPITAL_PER_TRADE / price), 1)


def check_condition(df):
    if len(df) < 5:
        return False

    c0 = df.iloc[-1]
    c1 = df.iloc[-2]

    pct_change = ((c0["close"] - c1["close"]) / c1["close"]) * 100

    return (
        pct_change >= -1 and
        c0["close"] < c0["open"] and
        c0["close"] < c0["ema20"]
    )

# =====================================================
# STRATEGY EXECUTION
# =====================================================

def process_symbol(symbol):
    df = pd.DataFrame(candles[symbol])

    if len(df) < 5:
        return

    df["ema20"] = df["close"].ewm(span=20).mean()
    price = df.iloc[-1]["close"]

    # ENTRY
    if symbol not in active_trades:
        if check_condition(df):
            qty = calculate_qty(price)

            place_order(symbol, "SELL", qty, price)

            active_trades[symbol] = {
                "qty": qty,
                "sl": df.iloc[-2]["high"]
            }

            print(f"📉 ENTER SHORT {symbol}")

    # MANAGEMENT
    else:
        trade = active_trades[symbol]
        new_sl = df.iloc[-2]["high"]

        if new_sl < trade["sl"]:
            trade["sl"] = new_sl
            print(f"🔄 SL Trailed {symbol}: {new_sl}")

        if df.iloc[-1]["high"] >= trade["sl"]:
            place_order(symbol, "BUY", trade["qty"], price)

            print(f"🚪 EXIT {symbol}")
            del active_trades[symbol]

# =====================================================
# WEBSOCKET HANDLERS
# =====================================================

def create_ws():
    kws = KiteTicker(API_KEY, access_token)

    def on_ticks(ws, ticks):
        for tick in ticks:
            token = tick["instrument_token"]
            price = tick["last_price"]
            ts = dt.datetime.now()

            symbol = reverse_map.get(token)
            if not symbol:
                continue

            update_candle(symbol, price, ts)

            candle_time = get_candle_start(ts)

            if symbol not in last_processed_candle:
                last_processed_candle[symbol] = candle_time

            elif last_processed_candle[symbol] != candle_time:
                last_processed_candle[symbol] = candle_time
                process_symbol(symbol)

    def on_connect(ws, response):
        print("🔌 Connected")
        tokens = list(instrument_map.values())
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)

    def on_close(ws, code, reason):
        print(f"❌ Closed: {reason}")

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close

    return kws

# =====================================================
# AUTO RECONNECT (FIXED PROPERLY)
# =====================================================

def start():
    while True:
        try:
            print("🚀 Starting WebSocket...")
            kws = create_ws()
            kws.connect()
        except Exception as e:
            print("⚠️ Error:", e)

        print("🔄 Reconnecting in 5 sec...")
        time.sleep(5)

# =====================================================
# RUN
# =====================================================

start()