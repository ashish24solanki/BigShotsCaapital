from datetime import datetime, date, timedelta
import os
import sys  
import time
import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect import KiteTicker
from kiteconnect.exceptions import TokenException

from datetime import datetime
import pytz

first_candle_done = False

def debug_time():
    

    # Timezones
    utc = pytz.utc
    ist = pytz.timezone("Asia/Kolkata")
    bkk = pytz.timezone("Asia/Bangkok")

    # Current times
    utc_now = datetime.now(utc)
    ist_now = utc_now.astimezone(ist)
    bkk_now = utc_now.astimezone(bkk)

    print(f"UTC: {utc_now}")
    print(f"IST: {ist_now}")
    print(f"BKK: {bkk_now}")





# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ================= CONFIG =================
from config.kite_config import API_KEY, API_SECRET
ACCESS_TOKEN_FILE = "/root/access_token.txt"

positions_closed = False
instruments_nfo = []
last_trade_time = {}

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
MAIN_LOG = os.path.join(LOG_DIR, "intraday.log")

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


SYMBOLS = ["RELIANCE", "HDFCBANK", "AXISBANK", "SBIN", "NIFTY", "BANKNIFTY"]

DEMO_MODE = True


import requests
from config.bot_config import DEMO_BOT_CHAT_ID, DEMO_BOT_TOKEN


BOT_TOKEN = DEMO_BOT_TOKEN
CHAT_ID = DEMO_BOT_CHAT_ID

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=data, timeout=5)
    except:
        pass


last_trade_time = {}
# ==========================================

kite = KiteConnect(api_key=API_KEY)

with open("/root/access_token.txt") as f:
    access_token = f.read().strip()

kite.set_access_token(access_token)

main_log("Zerodha connected (shared VM token)")
live_prices = {}
token_map = {}

# ================= HELPER FUNCTIONS =================

def get_30min_candles(symbol):
    data = kite.historical_data(
        symbol,
        datetime.now() - timedelta(days=5),
        datetime.now(),
        "30minute"
    )
    df = pd.DataFrame(data)
    return df


def candle_condition(df):
    if len(df) < 3:
        return False, False

    c0 = df.iloc[-2]   # latest completed candle
    c1 = df.iloc[-3]

    close = c0["close"]
    open_ = c0["open"]
    high = c0["high"]
    low = c0["low"]

    prev_close = c1["close"]

    pct_change = ((close - prev_close) / prev_close) * 100

    range_ = high - low if high != low else 1

    bullish = (
        pct_change <= 1.3 and
        close > open_ and
        ((open_ - low) / range_ <= 0.1 or (high - close) / range_ <= 0.1)
    )

    bearish = (
        pct_change >= -1.3 and
        close < open_ and
        ((close - low) / range_ <= 0.1 or (high - open_) / range_ <= 0.1)
    )

    return bullish, bearish


def place_order(tradingsymbol, transaction, qty):

    symbol = str(tradingsymbol)

    try:
        quote = kite.ltp([f"NFO:{symbol}"])
        ltp = quote.get(f"NFO:{symbol}", {}).get("last_price")
    except:
        ltp = None

    if not ltp:
        print(f"LTP missing for {symbol}")
        return

    buffer = 2 if ("NIFTY" in symbol or "BANKNIFTY" in symbol) else 0.2
    price = ltp + buffer if transaction == "BUY" else ltp - buffer

    # ================= DEMO MODE =================
    if DEMO_MODE:
        msg = f"""
🟡 DEMO ORDER

{transaction} {symbol}
Qty: {qty}
Price: {round(price,2)}
"""
        print(msg)
        send_telegram(msg)
        return

    # ================= LIVE MODE =================
    try:
        kite.place_order(
            variety="regular",
            exchange="NFO",
            tradingsymbol=symbol,
            transaction_type=transaction,
            quantity=qty,
            order_type="LIMIT",
            price=round(price, 2),
            product="NRML"
        )

        msg = f"✅ LIVE ORDER {transaction} {symbol} @ {round(price,2)}"
        print(msg)
        send_telegram(msg)

    except Exception as e:
        print(f"Order error {symbol}: {e}")


def modify_sl_order(sl_order, new_sl):

    symbol = sl_order["tradingsymbol"]

    if DEMO_MODE:
        msg = f"""
🟡 DEMO SL MODIFY

{symbol}
Old SL: {sl_order.get('trigger_price')}
New SL: {round(new_sl,2)}
"""
        print(msg)
        send_telegram(msg)
        return

    try:
        kite.modify_order(
            variety=sl_order["variety"],
            order_id=sl_order["order_id"],
            trigger_price=round(new_sl, 2),
            price=round(new_sl, 2)
        )

        print(f"SL UPDATED {symbol} → {new_sl}")
        send_telegram(f"🔄 SL UPDATED {symbol} → {round(new_sl,2)}")

    except Exception as e:
        print(f"SL modify error {symbol}: {e}")



def get_atm_option(kite, instruments, underlying, option_type):
    import datetime as dt

    today = dt.datetime.now().date()

    # ================= EXPIRY =================
    expiries = sorted(set(
        i["expiry"] for i in instruments
        if i["name"] == underlying and i["segment"] == "NFO-OPT"
    ))

    if not expiries:
        return None

    expiry = expiries[0]

    # 👉 shift expiry if near expiry (<=2 days)
    if (expiry - today).days <= 2 and len(expiries) > 1:
        expiry = expiries[1]

    # ================= OPTIONS =================
    options = [
        i for i in instruments
        if i["name"] == underlying
        and i["expiry"] == expiry
        and i["instrument_type"] == option_type
    ]

    if not options:
        return None

    # ================= STRIKE STEP =================
    strikes = sorted(set(i["strike"] for i in options))
    if not strikes:
        return None

    step = strikes[1] - strikes[0] if len(strikes) > 1 else 50

    # ================= SPOT =================
    symbol = underlying
    spot = live_prices.get(symbol)

    if not spot:
        # ===== FIX FOR INDEX =====
        if symbol == "NIFTY":
            key = "NSE:NIFTY 50"
        elif symbol == "BANKNIFTY":
            key = "NSE:NIFTY BANK"
        else:
            key = f"NSE:{symbol}"

        try:
            quote = kite.ltp([key])

            # SAFE HANDLING
            if not isinstance(quote, dict):
                print(f"Invalid quote for {symbol} → {quote}")
                return None

            spot_data = quote.get(key)
            if not spot_data:
                print(f"Spot missing for {symbol}")
                return None

            spot = spot_data.get("last_price")
            if spot is None:
                print(f"No last_price for {symbol}")
                return None

        except Exception as e:
            print(f"Spot fetch failed for {symbol}: {e}")
            return None

    # ================= ATM CALC =================
    atm = round(spot / step) * step

    # ================= CLOSEST STRIKE =================
    closest = min(options, key=lambda x: abs(x["strike"] - atm))

    return closest


def on_ticks(ws, ticks):
    for tick in ticks:
        token = tick["instrument_token"]
        price = tick["last_price"]

        symbol = token_map.get(token)
        if symbol:
            live_prices[symbol] = price


def on_connect(ws, response):
    print("WebSocket Connected")

    tokens = list(token_map.keys())
    if not tokens:
        print("No tokens found")
        return

    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_LTP, tokens)

def get_position(positions, symbol):
    for p in positions:
        if p["tradingsymbol"] == symbol:
            return p
    return None

def calculate_sl_15min(token, direction, symbol):
        buffer = 2 if ("NIFTY" in symbol or "BANKNIFTY" in symbol) else 0.2

        df15 = pd.DataFrame(kite.historical_data(
            token,
            datetime.now() - timedelta(days=2),
            datetime.now(),
            "15minute"
        ))

        if df15 is None or len(df15) < 2:
            return None

        prev = df15.iloc[-2]

        if direction == "BUY":
            return prev["low"] - buffer
        else:
            return prev["high"] + buffer


def calculate_sl_30min(df, direction, symbol):
        buffer = 2 if ("NIFTY" in symbol or "BANKNIFTY" in symbol) else 0.2

        if len(df) < 5:
            return None

        c3 = df.iloc[-4]
        c2 = df.iloc[-3]
        c1 = df.iloc[-2]

        today = datetime.now().date()
        if not (c3["date"].date() == today and c2["date"].date() == today and c1["date"].date() == today):
            return None

        if direction == "BUY":
            lows = [c3["low"], c2["low"], c1["low"]]

            # tight range
            if max(lows) - min(lows) < 1:
                return min(lows) - buffer

            # expansion
            return max(c2["low"], c1["low"]) - buffer

        else:
            highs = [c3["high"], c2["high"], c1["high"]]

            if max(highs) - min(highs) < 1:
                return max(highs) + buffer

            return max(c2["high"], c1["high"]) + buffer


# ================= MAIN LOOP =================


def run_strategy():

    def get_ltp(symbol):
        try:
            q = kite.ltp([f"NFO:{symbol}"])
            data = q.get(f"NFO:{symbol}")
            if data:
                return data.get("last_price")
        except:
            return None

    def get_qty(symbol):
        try:
            positions = kite.positions()["net"]
            for p in positions:
                if p["tradingsymbol"] == symbol:
                    return abs(p["quantity"])
        except:
            return 0
        return 0

    
    

    for sym in SYMBOLS:
        try:
            now_str = datetime.now().strftime('%H:%M')
            print(f"Checking {sym}")
            send_telegram(f"⏱ Checking {sym} at {now_str}")

            # ================= SPOT =================
            if sym == "NIFTY":
                key = "NSE:NIFTY 50"
            elif sym == "BANKNIFTY":
                key = "NSE:NIFTY BANK"
            else:
                key = f"NSE:{sym}"

            quote = kite.ltp([key])
            spot_data = quote.get(key)
            if not spot_data:
                continue

            # ================= TOKEN =================
            if sym == "NIFTY":
                token = next((i["instrument_token"] for i in nse_instruments if i["name"] == "NIFTY 50"), None)
            elif sym == "BANKNIFTY":
                token = next((i["instrument_token"] for i in nse_instruments if i["name"] == "NIFTY BANK"), None)
            else:
                token = nse_map.get(sym)

            if not token:
                continue

            # ================= OHLC =================
            df = pd.DataFrame(kite.historical_data(
                token,
                datetime.now() - timedelta(days=5),
                datetime.now(),
                "30minute"
            ))

            if df is None or len(df) < 3:
                continue

            bullish, bearish = candle_condition(df)

            if not bullish and not bearish:
                continue

            # ================= OPTIONS =================
            ce = get_atm_option(kite, instruments_nfo, sym, "CE")
            pe = get_atm_option(kite, instruments_nfo, sym, "PE")

            if not ce or not pe:
                continue

            ce_symbol = ce["tradingsymbol"]
            pe_symbol = pe["tradingsymbol"]

            ce_df = pd.DataFrame(kite.historical_data(
                ce["instrument_token"],
                datetime.now() - timedelta(days=2),
                datetime.now(),
                "30minute"
            ))

            pe_df = pd.DataFrame(kite.historical_data(
                pe["instrument_token"],
                datetime.now() - timedelta(days=2),
                datetime.now(),
                "30minute"
            ))

            if len(ce_df) < 5 or len(pe_df) < 5:
                continue

            # ================= QTY =================
            ce_qty = get_qty(ce_symbol)
            pe_qty = get_qty(pe_symbol)

            # ================= SL LOGIC =================
            if bullish:

                # BUY CE
                if ce_qty >= 3:
                    ce_sl = calculate_sl_15min(ce["instrument_token"], "BUY", ce_symbol)
                else:
                    ce_sl = calculate_sl_30min(ce_df, "BUY", ce_symbol)

                # SELL PE
                if pe_qty >= 3:
                    pe_sl = calculate_sl_15min(pe["instrument_token"], "SELL", pe_symbol)
                else:
                    pe_sl = calculate_sl_30min(pe_df, "SELL", pe_symbol)

            else:

                # BUY PE
                if pe_qty >= 3:
                    pe_sl = calculate_sl_15min(pe["instrument_token"], "BUY", pe_symbol)
                else:
                    pe_sl = calculate_sl_30min(pe_df, "BUY", pe_symbol)

                # SELL CE
                if ce_qty >= 3:
                    ce_sl = calculate_sl_15min(ce["instrument_token"], "SELL", ce_symbol)
                else:
                    ce_sl = calculate_sl_30min(ce_df, "SELL", ce_symbol)

            # ================= LTP =================
            ce_ltp = get_ltp(ce_symbol)
            pe_ltp = get_ltp(pe_symbol)

            # ================= MESSAGE =================
            if bullish:
                msg = f"""
{sym} BULLISH

BUY CE: {ce_symbol} @ {round(ce_ltp,2) if ce_ltp else '-'}
SL: {round(ce_sl,2) if ce_sl else '-'}

SELL PE: {pe_symbol} @ {round(pe_ltp,2) if pe_ltp else '-'}
SL: {round(pe_sl,2) if pe_sl else '-'}
"""
            else:
                msg = f"""
{sym} BEARISH

BUY PE: {pe_symbol} @ {round(pe_ltp,2) if pe_ltp else '-'}
SL: {round(pe_sl,2) if pe_sl else '-'}

SELL CE: {ce_symbol} @ {round(ce_ltp,2) if ce_ltp else '-'}
SL: {round(ce_sl,2) if ce_sl else '-'}
"""

            print(msg)
            send_telegram(msg)

        except Exception as e:
            print(f"Error {sym}: {e}")


def wait_for_next_candle():
    while True:
        now = datetime.now()

        base = now.replace(hour=9, minute=15, second=0, microsecond=0)

        mins = int((now - base).total_seconds() // 1800)
        next_candle = base + timedelta(minutes=30 * (mins + 1))

        seconds_left = int((next_candle - now).total_seconds())
        minutes_left = (seconds_left + 59) // 60

        print(f"Next candle at {next_candle.strftime('%H:%M')} ({minutes_left} min left)")

        if seconds_left <= 1:
            print("New candle started")
            break

        time.sleep(30)

# ================= RUN =================


def ensure_session():
    global kite
    try:
        kite.profile()
    except:
        main_log("Session expired → refreshing token")

        import subprocess
        subprocess.run([
            "/root/tradingenv/bin/python",
            "/root/auto_login.py"
        ])

        time.sleep(3)

        with open("/root/access_token.txt") as f:
            access_token = f.read().strip()

        kite.set_access_token(access_token)
        time.sleep(1)
        main_log("Session refreshed")


def wait_for_market_start():
    while True:
        now = datetime.now()

        start_time = now.replace(hour=10, minute=40, second=0, microsecond=0)

        if now >= start_time:
            print("Market pre-start reached (10:40)")
            break

        print(f"Waiting for 10:40... Current: {now}", end="\r")
        time.sleep(20)


def wait_for_first_candle():
    now = datetime.now()
    print(f"Starting immediately at {now.strftime('%H:%M')}")



def close_all_positions():
    print("🔴 Closing all OPTION positions (16:50)...")
    send_telegram("🔴 Closing ALL OPTION positions (16:50)")

    closed_symbols = set()
    positions = kite.positions()["net"]

    for pos in positions:
        try:
            # ✅ ONLY NFO OPTIONS (skip FUT)
            if pos["exchange"] != "NFO":
                continue

            symbol = str(pos["tradingsymbol"])

            # ❌ SKIP FUTURES
            if "FUT" in symbol:
                continue

            # ✅ ONLY OPTIONS (extra safety)
            if not ("CE" in symbol or "PE" in symbol):
                continue

            qty = pos["quantity"]
            if qty == 0:
                continue

            if symbol in closed_symbols:
                continue

            closed_symbols.add(symbol)

            # ===== GET LTP =====
            try:
                quote = kite.ltp([f"NFO:{symbol}"])
                key = f"NFO:{symbol}"

                if not isinstance(quote, dict):
                    print(f"Invalid LTP response for {symbol}")
                    continue

                ltp_data = quote.get(key)
                if not ltp_data:
                    print(f"LTP missing for {symbol}")
                    continue

                ltp = ltp_data.get("last_price")
                if ltp is None:
                    print(f"No last_price for {symbol}")
                    continue

            except Exception as e:
                print(f"LTP error {symbol}: {e}")
                continue

            # ===== PRICE =====
            buffer = 2 if ("NIFTY" in symbol or "BANKNIFTY" in symbol) else 0.2

            if qty > 0:
                transaction = "SELL"
                price = ltp - buffer
            else:
                transaction = "BUY"
                price = ltp + buffer

            # ===== ORDER =====
            kite.place_order(
                variety="regular",
                exchange="NFO",
                tradingsymbol=symbol,
                transaction_type=transaction,
                quantity=abs(qty),
                order_type="LIMIT",
                price=round(price, 2),
                product=pos.get("product", "NRML"),
            )

            print(f"Closed OPTION {symbol} @ {round(price,2)}")
            send_telegram(f"Closed OPTION {symbol} @ {round(price,2)}")

        except Exception as e:
            print(f"Error closing {symbol}: {e}")


def damage_control():
    pass



def trailing_sl_engine():

    try:
        positions = kite.positions()["net"]
        orders = kite.orders()

        for pos in positions:

            if pos["exchange"] != "NFO":
                continue

            qty = pos["quantity"]
            if qty == 0:
                continue

            symbol = pos["tradingsymbol"]
            direction = "BUY" if qty > 0 else "SELL"

            # ===== GET TOKEN =====
            token = None
            for i in instruments_nfo:
                if i["tradingsymbol"] == symbol:
                    token = i["instrument_token"]
                    break

            if not token:
                continue

            # ===== CALCULATE NEW SL =====
            if abs(qty) >= 3:
                new_sl = calculate_sl_15min(token, direction, symbol)
            else:
                df = pd.DataFrame(kite.historical_data(
                    token,
                    datetime.now() - timedelta(days=2),
                    datetime.now(),
                    "30minute"
                ))
                new_sl = calculate_sl_30min(df, direction, symbol)

            if new_sl is None:
                continue

            # ===== FIND SL ORDER =====
            sl_order = None

            for o in orders:
                if (
                    o["tradingsymbol"] == symbol
                    and o["order_type"] == "SL"
                    and o["status"] == "OPEN"
                ):
                    sl_order = o
                    break

            if not sl_order:
                continue

            old_sl = sl_order.get("trigger_price")

            # ===== ONLY MOVE FORWARD =====
            if direction == "BUY":
                if new_sl <= old_sl:
                    continue
            else:
                if new_sl >= old_sl:
                    continue

            # ===== APPLY =====
            modify_sl_order(sl_order, new_sl)

    except Exception as e:
        print("Trailing SL error:", e)


def emergency_sl_check():

    try:
        positions = kite.positions()["net"]
        orders = kite.orders()

        for pos in positions:

            if pos["exchange"] != "NFO":
                continue

            qty = pos["quantity"]
            if qty == 0:
                continue

            symbol = pos["tradingsymbol"]

            # ===== GET LTP =====
            try:
                quote = kite.ltp([f"NFO:{symbol}"])
                ltp = quote.get(f"NFO:{symbol}", {}).get("last_price")
            except:
                continue

            if not ltp:
                continue

            # ===== FIND SL ORDER =====
            sl_order = None

            for o in orders:
                if (
                    o["tradingsymbol"] == symbol
                    and o["order_type"] == "SL"
                    and o["status"] == "OPEN"
                ):
                    sl_order = o
                    break

            if not sl_order:
                continue

            sl_price = sl_order.get("trigger_price")

            if not sl_price:
                continue

            # ================= EMERGENCY CONDITION =================

            # BUY POSITION
            if qty > 0 and ltp < sl_price:

                print(f"🚨 EMERGENCY EXIT BUY {symbol}")
                send_telegram(f"🚨 EMERGENCY EXIT BUY {symbol}")

                # Cancel old SL
                if not DEMO_MODE:
                    kite.cancel_order(
                        variety=sl_order["variety"],
                        order_id=sl_order["order_id"]
                    )

                # Place exit order
                exit_price = ltp - 1

                if DEMO_MODE:
                    send_telegram(f"🟡 DEMO EXIT SELL {symbol} @ {round(exit_price,2)}")
                else:
                    kite.place_order(
                        variety="regular",
                        exchange="NFO",
                        tradingsymbol=symbol,
                        transaction_type="SELL",
                        quantity=abs(qty),
                        order_type="LIMIT",
                        price=round(exit_price, 2),
                        product=pos.get("product", "NRML"),
                    )

            # SELL POSITION
            elif qty < 0 and ltp > sl_price:

                print(f"🚨 EMERGENCY EXIT SELL {symbol}")
                send_telegram(f"🚨 EMERGENCY EXIT SELL {symbol}")

                # Cancel old SL
                if not DEMO_MODE:
                    kite.cancel_order(
                        variety=sl_order["variety"],
                        order_id=sl_order["order_id"]
                    )

                # Place exit order
                exit_price = ltp + 1

                if DEMO_MODE:
                    send_telegram(f"🟡 DEMO EXIT BUY {symbol} @ {round(exit_price,2)}")
                else:
                    kite.place_order(
                        variety="regular",
                        exchange="NFO",
                        tradingsymbol=symbol,
                        transaction_type="BUY",
                        quantity=abs(qty),
                        order_type="LIMIT",
                        price=round(exit_price, 2),
                        product=pos.get("product", "NRML"),
                    )

    except Exception as e:
        print("Emergency SL error:", e)


# ================= MAIN =================
if __name__ == "__main__":

    now_vm = datetime.now()
    msg = f"""🚀 Intraday Options Bot Started

    VM Time: {now_vm.strftime('%Y-%m-%d %H:%M:%S')}
    """

    print(msg)
    send_telegram(msg)
    debug_time()

    nse_instruments = kite.instruments("NSE")
    nse_map = {i["tradingsymbol"]: i["instrument_token"] for i in nse_instruments}

    for i in kite.instruments("NSE"):
        if i["tradingsymbol"] in SYMBOLS:
            token_map[i["instrument_token"]] = i["tradingsymbol"]

    instruments_nfo = kite.instruments("NFO")

    kws = KiteTicker(API_KEY, kite.access_token)
    kws.on_ticks = lambda ws, ticks: None
    kws.on_connect = lambda ws, res: ws.subscribe(list(token_map.keys()))
    kws.connect(threaded=True)

    time.sleep(5)

    last_execution_candle = None


    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)

    if now_ist.time() > datetime.strptime("09:45", "%H:%M").time():
        first_candle_done = True

    while True:



        now_ist = datetime.now(ist)

        if now_ist.time() < datetime.strptime("09:15", "%H:%M").time():
            time.sleep(30)
            continue

        if now_ist.time() > datetime.strptime("15:10", "%H:%M").time():
            print("Stopping bot (EOD)")
            break

        minute = now_ist.minute
        second = now_ist.second
        hour = now_ist.hour

        # ===== FIRST CANDLE =====
        if not first_candle_done:

            if hour == 9 and minute == 45 and second >= 5:

                print("🔥 First candle ready")
                send_telegram("🔥 First Candle Ready")

                run_strategy()

                first_candle_done = True
                last_execution_candle = "FIRST"

        # ===== NORMAL EXECUTION =====
        elif minute % 30 == 15 and 5 <= second <= 15:

            current_candle = now_ist.replace(second=0, microsecond=0)

            if last_execution_candle != current_candle:

                print(f"⏱ Running strategy {current_candle}")
                send_telegram(f"⏱ Running IST {current_candle}")

                run_strategy()

                last_execution_candle = current_candle

        trailing_sl_engine()

        # run emergency check every 60 sec
        if int(time.time()) % 60 < 5:
            emergency_sl_check()

        time.sleep(5)
    

        