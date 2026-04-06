from datetime import datetime, date, timedelta
import os
import sys  
import time
import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect import KiteTicker
from kiteconnect.exceptions import TokenException



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
        requests.post(url, data=data, timeout=3)
    except Exception as e:
        print("Telegram Error:", e)

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

def get_30min_candles(token):
    data = kite.historical_data(
        token,
        datetime.now() - timedelta(days=5),
        datetime.now(),
        "30minute"
    )
    df = pd.DataFrame(data)
    return df


def candle_condition(df):
    c0 = df.iloc[-2]
    c1 = df.iloc[-3]

    close = c0["close"]
    open_ = c0["open"]
    high = c0["high"]
    low = c0["low"]

    prev_close = c1["close"]

    # % change
    pct_change = ((close - prev_close) / prev_close) * 100

    # wick ratios
    range_ = high - low if high != low else 1

    lower_wick = (open_ - low) / range_
    upper_wick = (high - close) / range_

    bullish = (
        pct_change <= 1.3 and
        close > open_ and
        (lower_wick <= 0.1 or upper_wick <= 0.1)
    )

    bearish = (
        pct_change >= -1.3 and
        close < open_ and
        (
            ((close - low) / range_) <= 0.1 or
            ((high - open_) / range_) <= 0.1
        )
    )

    return bullish, bearish

def place_order(tradingsymbol, transaction, qty):
    quote = kite.ltp(f"NFO:{tradingsymbol}")
    ltp = quote[f"NFO:{tradingsymbol}"]["last_price"]

    if "NIFTY" in tradingsymbol or "BANKNIFTY" in tradingsymbol:
        buffer = 2
    else:
        buffer = 0.2

    price = ltp + buffer if transaction == "BUY" else ltp - buffer

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction,
        quantity=qty,
        order_type="LIMIT",
        price=round(price, 2),
        product=kite.PRODUCT_NRML
    )

def cancel_existing_sl(symbol):
    orders = kite.orders()

    for o in orders:
        if o["tradingsymbol"] == symbol and o["order_type"] == "SL":
            try:
                kite.cancel_order(variety=o["variety"], order_id=o["order_id"])
            except:
                pass

def place_sl(tradingsymbol, qty,trigger,limit, transaction):

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction,
        quantity=qty,
        order_type="SL",
        price=round(limit,2),
        trigger_price=round(trigger,2),
        product=kite.PRODUCT_NRML
    )


def place_sl_entry(tradingsymbol, qty, trigger, limit, transaction):

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction,
        quantity=qty,
        order_type="SL",
        price=round(limit, 2),
        trigger_price=round(trigger, 2),
        product=kite.PRODUCT_NRML
    )


def get_atm_option(kite, instruments, underlying, option_type):
    import datetime as dt

    today = dt.datetime.now().date()

    expiries = sorted(set(
        i["expiry"] for i in instruments
        if i["name"] == underlying and i["segment"] == "NFO-OPT"
    ))

    if not expiries:
        return None

    from datetime import timedelta

    # Default expiry
    expiry = expiries[0]

    # If near expiry (<= 2 days), shift to next expiry
    if (expiry - today).days <= 2 and len(expiries) > 1:
        expiry = expiries[1]

    options = [
        i for i in instruments
        if i["name"] == underlying
        and i["expiry"] == expiry
        and i["instrument_type"] == option_type
    ]
    
    if not options:
        return None

    strikes = sorted(set(i["strike"] for i in options))
    if len(strikes) < 2:
        return None
    step = min([strikes[i+1] - strikes[i] for i in range(len(strikes)-1)])

    symbol = underlying
    spot = live_prices.get(symbol)

    if spot is None:
        quote = kite.ltp(f"NSE:{symbol}")
        spot = quote[f"NSE:{symbol}"]["last_price"]


    atm = round(spot / step) * step

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

# ================= MAIN LOOP =================


def run_strategy():
    now = datetime.now().time()

    # 🚫 No new trades after 16:45
    if now >= datetime.strptime("16:45", "%H:%M").time():
        print("⛔ Trade cutoff reached (16:45). Skipping new trades.")
        return

    global instruments_nfo
    instruments = instruments_nfo
    positions = kite.positions()["net"]

    index_map = {
        "NIFTY": "NSE:NIFTY 50",
        "BANKNIFTY": "NSE:NIFTY BANK"
    }

    for sym in SYMBOLS:
        try:
            print(f"\n🔎 Checking {sym} at {datetime.now()}")

            # ===== CONFIG =====
            if sym in ["NIFTY", "BANKNIFTY"]:
                trigger_buffer = 1
                base_limit = 2
                high_limit = 5
            else:
                trigger_buffer = 0.10
                base_limit = 0.20
                high_limit = 0.50

            # =====================================================
            # 🔥 GET UNDERLYING CANDLES
            # =====================================================
            instrument = next((i for i in instruments if i["tradingsymbol"] == sym), None)

            if instrument:
                df = get_30min_candles(instrument["instrument_token"])
            elif sym in index_map:
                df = pd.DataFrame(kite.historical_data(
                    index_map[sym],
                    datetime.now() - timedelta(days=5),
                    datetime.now(),
                    "30minute"
                ))
            else:
                continue

            if df is None or len(df) < 3:
                continue

            # ===== LAST COMPLETED CANDLE =====
            candle = df.iloc[-2]
            candle_time = candle["date"].strftime("%H:%M")

            print(f"📊 {sym} Candle {candle_time} | O:{candle['open']} H:{candle['high']} L:{candle['low']} C:{candle['close']}")

            if DEMO_MODE:
                send_telegram(
                    f"{sym} | {candle_time}\n"
                    f"O:{candle['open']} H:{candle['high']} L:{candle['low']} C:{candle['close']}"
                )

            # ===== SIGNAL =====
            bullish, bearish = candle_condition(df)
            print(f"{sym} → Bullish: {bullish}, Bearish: {bearish}")

            # =====================================================
            # 🔥 GET ATM OPTIONS
            # =====================================================
            ce = get_atm_option(kite, instruments, sym, "CE")
            pe = get_atm_option(kite, instruments, sym, "PE")

            if not ce or not pe:
                continue

            qty = ce["lot_size"]

            ce_symbol = ce["tradingsymbol"]
            pe_symbol = pe["tradingsymbol"]

            ce_token = ce["instrument_token"]
            pe_token = pe["instrument_token"]

            # =====================================================
            # 🔥 OPTION DATA
            # =====================================================
            ce_df = pd.DataFrame(kite.historical_data(
                ce_token,
                datetime.now() - timedelta(days=2),
                datetime.now(),
                "30minute"
            ))

            pe_df = pd.DataFrame(kite.historical_data(
                pe_token,
                datetime.now() - timedelta(days=2),
                datetime.now(),
                "30minute"
            ))

            if len(ce_df) < 3 or len(pe_df) < 3:
                continue

            ce_last = ce_df.iloc[-2]
            pe_last = pe_df.iloc[-2]

            ce_prev1, ce_prev2 = ce_df.iloc[-2], ce_df.iloc[-3]
            pe_prev1, pe_prev2 = pe_df.iloc[-2], pe_df.iloc[-3]

            # ===== DEBUG OPTION CANDLES =====
            print(f"📈 CE {ce_symbol} → O:{ce_last['open']} H:{ce_last['high']} L:{ce_last['low']} C:{ce_last['close']}")
            print(f"📉 PE {pe_symbol} → O:{pe_last['open']} H:{pe_last['high']} L:{pe_last['low']} C:{pe_last['close']}")

            if DEMO_MODE:
                send_telegram(f"📈 {ce_symbol} O:{ce_last['open']} H:{ce_last['high']} L:{ce_last['low']} C:{ce_last['close']}")
                send_telegram(f"📉 {pe_symbol} O:{pe_last['open']} H:{pe_last['high']} L:{pe_last['low']} C:{pe_last['close']}")

            # ===== POSITIONS =====
            ce_pos = get_position(positions, ce_symbol)
            pe_pos = get_position(positions, pe_symbol)

            total_ce_qty = qty + abs(ce_pos.get("quantity", 0)) if ce_pos else qty
            total_pe_qty = qty + abs(pe_pos.get("quantity", 0)) if pe_pos else qty

            ce_limit_buffer = high_limit if total_ce_qty >= 3 * qty else base_limit
            pe_limit_buffer = high_limit if total_pe_qty >= 3 * qty else base_limit

            # =====================================================
            # ===================== BULLISH =========================
            # =====================================================
            if bullish:
                print(f"{sym} BULLISH")

                ce_trigger = ce_last["high"] + trigger_buffer
                pe_trigger = pe_last["low"] - trigger_buffer

                if DEMO_MODE:
                    send_telegram(f"{sym} BULLISH → BUY CE / SELL PE")
                else:
                    place_sl_entry(ce_symbol, qty, ce_trigger, ce_trigger + ce_limit_buffer, "BUY")
                    place_sl_entry(pe_symbol, qty, pe_trigger, pe_trigger - pe_limit_buffer, "SELL")

            # =====================================================
            # ===================== BEARISH =========================
            # =====================================================
            elif bearish:
                print(f"{sym} BEARISH")

                pe_trigger = pe_last["low"] - trigger_buffer
                ce_trigger = ce_last["high"] + trigger_buffer

                if DEMO_MODE:
                    send_telegram(f"{sym} BEARISH → BUY PE / SELL CE")
                else:
                    place_sl_entry(pe_symbol, qty, pe_trigger, pe_trigger - pe_limit_buffer, "BUY")
                    place_sl_entry(ce_symbol, qty, ce_trigger, ce_trigger + ce_limit_buffer, "SELL")

        except Exception as e:
            print(f"❌ Error in {sym}: {e}")


def wait_for_next_candle():
    while True:
        now = datetime.now()

        # Anchor at 11:15
        base = now.replace(hour=11, minute=15, second=0, microsecond=0)

        # If before 11:15 → wait for it
        if now < base:
            next_candle = base
        else:
            # Calculate next 1-hour interval from 11:15
            delta_hours = int((now - base).total_seconds() // 3600) + 1
            next_candle = base + timedelta(hours=delta_hours)

        # Time left
        seconds_left = int((next_candle - now).total_seconds())
        minutes_left = (seconds_left + 59) // 60

        print(f"Next candle at {next_candle.strftime('%H:%M')} ({minutes_left} min left)")

        if seconds_left <= 1:
            print("New candle started")
            break

        time.sleep(60)

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
    print("🔴 Closing all positions (16:50)...")
    send_telegram("🔴 Closing ALL positions (16:50)")
    closed_symbols = set()

    positions = kite.positions()["net"]

    for pos in positions:
        try:
            if pos["exchange"] != "NFO":
                continue

            qty = pos["quantity"]
            if qty == 0:
                continue

            symbol = pos["tradingsymbol"]

            if symbol in closed_symbols:
                continue

            closed_symbols.add(symbol)

            # ===== GET LTP =====
            quote = kite.ltp(f"NFO:{symbol}")
            ltp = quote[f"NFO:{symbol}"]["last_price"]

            if "NIFTY" in symbol or "BANKNIFTY" in symbol:
                buffer = 2
            else:
                buffer = 0.2

            if qty > 0:
                transaction = "SELL"
                price = ltp - buffer
            else:
                transaction = "BUY"
                price = ltp + buffer

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

            print(f"Closed {symbol} @ {price}")

        except Exception as e:
            print(f"Error closing {symbol}: {e}")


def damage_control():
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
            quote = kite.ltp(f"NFO:{symbol}")
            ltp = quote[f"NFO:{symbol}"]["last_price"]

            # ===== FIND EXISTING SL =====
            
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

            # ===== DAMAGE CONTROL LOGIC =====
            if qty > 0:
                # BUY POSITION → SL below price
                new_trigger = ltp - 1
                new_limit = new_trigger - 0.2

                if new_trigger > sl_order["trigger_price"]:
                    if abs(new_trigger - sl_order["trigger_price"]) > 0.5:

                        kite.modify_order(
                            variety=sl_order["variety"],
                            order_id=sl_order["order_id"],
                            trigger_price=round(new_trigger, 2),
                            price=round(new_limit, 2)
                        )

                        print(f"Updated SL BUY {symbol} → {new_trigger}")
                        send_telegram(f"🛡 SL Updated BUY {symbol} → {round(new_trigger,2)}")
            else:
                # SELL POSITION → SL above price
                new_trigger = ltp + 1
                new_limit = new_trigger + 0.2

                if new_trigger < sl_order["trigger_price"]:
                    if abs(new_trigger - sl_order["trigger_price"]) > 0.5:

                        kite.modify_order(
                            variety=sl_order["variety"],
                            order_id=sl_order["order_id"],
                            trigger_price=round(new_trigger, 2),
                            price=round(new_limit, 2)
                        )

                        print(f"Updated SL SELL {symbol} → {new_trigger}")
                        send_telegram(f"🛡 SL Updated SELL {symbol} → {round(new_trigger,2)}")

    except Exception as e:
        print("Damage control error:", e)


if __name__ == "__main__":
    send_telegram("✅ Intraday Bot Ready")

    # WAIT UNTIL 10:40
    wait_for_market_start()
    send_telegram("🔐 Logging in and preparing...")

    # Load tokens
    spot_instruments = kite.instruments("NSE")
    for ins in spot_instruments:
        if ins["tradingsymbol"] in SYMBOLS:
            token_map[ins["instrument_token"]] = ins["tradingsymbol"]

    if not token_map:
        print("No tokens loaded → exiting")
        exit()

    # Start websocket
    kws = KiteTicker(API_KEY, kite.access_token)
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.connect(threaded=True)

    time.sleep(5)

    send_telegram("🚀 Intraday Bot Started")

    last_damage_check = 0
    positions_closed = False

    # Load instruments
    instruments_nfo = kite.instruments("NFO")

    # 🔥 Track last execution candle
    last_execution_candle = None

    while True:

        ensure_session()

        # Refresh instruments every 30 min
        if int(time.time()) % 1800 < 2:
            instruments_nfo = kite.instruments("NFO")

        now_dt = datetime.now()
        now = now_dt.time()

        # 🔴 FORCE EXIT AT 16:50
        if now >= datetime.strptime("16:50", "%H:%M").time() and not positions_closed:
            close_all_positions()
            positions_closed = True
            print("🛑 Positions closed. Stopping bot.")
            send_telegram("🛑 Intraday Bot Stopped (Day End)")
            break

        # 🛡 DAMAGE CONTROL (every 60 sec)
        if time.time() - last_damage_check > 60:
            damage_control()
            last_damage_check = time.time()

        # ⛔ NO TRADES AFTER 16:45
        if now >= datetime.strptime("16:45", "%H:%M").time():
            time.sleep(30)
            continue

        # =====================================================
        # 🔥 CORRECT 30-MIN CANDLE LOGIC (KEY FIX)
        # =====================================================
        base = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)

        if now_dt < base:
            next_candle = base
        else:
            minutes_passed = int((now_dt - base).total_seconds() // 1800)
            next_candle = base + timedelta(minutes=30 * (minutes_passed + 1))

        current_candle = next_candle - timedelta(minutes=30)

        print(f"🕒 Current Candle: {current_candle.strftime('%H:%M')} | Now: {now_dt.strftime('%H:%M:%S')}")

        # =====================================================
        # 🔥 EXECUTE ONCE PER CANDLE (BULLETPROOF)
        # =====================================================
        if last_execution_candle != current_candle:

            print(f"🚀 New Candle Detected: {current_candle.strftime('%H:%M')}")

            send_telegram(f"🧠 Running strategy at {now_dt.strftime('%H:%M:%S')}")
            send_telegram(f"⏱ Checking signals for candle {current_candle.strftime('%H:%M')}")

            run_strategy()

            last_execution_candle = current_candle

        time.sleep(5)


    

        