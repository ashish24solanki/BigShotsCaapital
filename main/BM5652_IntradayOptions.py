from datetime import datetime, date, timedelta
import webbrowser
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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ================= CONFIG =================
from config.kite_config import API_KEY, API_SECRET
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")


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
                main_log("Zerodha logged in (cached token)")
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
    main_log("Zerodha login successful (new token)")
    return kite

SYMBOLS = ["RELIANCE", "HDFCBANK", "AXISBANK", "SBIN", "NIFTY", "BANKNIFTY"]

DEMO_MODE = True

import requests

BOT_TOKEN = "8774306075:AAEhPX4wKO9pC6mo0wzXiVlDcGnrFUiRMrk"
CHAT_ID = "-1003819611851"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram Error:", e)

last_trade_time = {}
# ==========================================

kite = get_kite()
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
    c0 = df.iloc[-1]
    c1 = df.iloc[-2]

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

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NFO,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction,
        quantity=qty,
        order_type=kite.ORDER_TYPE_MARKET,
        product=kite.PRODUCT_MIS
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
        product=kite.PRODUCT_MIS
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
        product=kite.PRODUCT_MIS
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

    expiry = expiries[1] if today.day > 22 and len(expiries) > 1 else expiries[0]

    options = [
        i for i in instruments
        if i["name"] == underlying
        and i["expiry"] == expiry
        and i["instrument_type"] == option_type
    ]

    strikes = sorted(set(i["strike"] for i in options))
    step = min([strikes[i+1] - strikes[i] for i in range(len(strikes)-1)])

    symbol = underlying
    if symbol not in live_prices:
        print(f"{symbol} no live price yet")
        return None

    spot = live_prices[symbol]

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
    instruments = kite.instruments("NFO")

    for sym in SYMBOLS:
        try:
            # ===== CONFIG =====
            if sym in ["NIFTY", "BANKNIFTY"]:
                trigger_buffer = 1
                base_limit = 2
                high_limit = 5
            else:
                trigger_buffer = 0.10
                base_limit = 0.20
                high_limit = 0.50

            positions = kite.positions()["net"]
            time.sleep(0.3)
            instrument = next((i for i in instruments if i["tradingsymbol"] == sym), None)
            if not instrument:
                continue

            token = instrument["instrument_token"]

            df = get_30min_candles(token)
            if df is None or len(df) < 3:
                continue

            candle_time = df.iloc[-1]["date"]

            if last_trade_time.get(sym) == candle_time:
                continue

            last_trade_time[sym] = candle_time

            bullish, bearish = candle_condition(df)

            ce = get_atm_option(kite, instruments, sym, "CE")
            pe = get_atm_option(kite, instruments, sym, "PE")

            if not ce or not pe:
                continue

            qty = ce["lot_size"]

            ce_symbol = ce["tradingsymbol"]
            pe_symbol = pe["tradingsymbol"]

            ce_token = ce["instrument_token"]
            pe_token = pe["instrument_token"]

            # ===== OPTION DATA =====
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

            ce_candle = ce_df.iloc[-1]
            pe_candle = pe_df.iloc[-1]

            ce_prev1, ce_prev2 = ce_df.iloc[-2], ce_df.iloc[-3]
            pe_prev1, pe_prev2 = pe_df.iloc[-2], pe_df.iloc[-3]

            ce_pos = get_position(positions, ce_symbol)
            pe_pos = get_position(positions, pe_symbol)

            # ===== POSITION SIZE =====
            total_ce_qty = qty + abs(ce_pos["quantity"]) if ce_pos else qty
            total_pe_qty = qty + abs(pe_pos["quantity"]) if pe_pos else qty

            ce_limit_buffer = high_limit if total_ce_qty >= 3 * qty else base_limit
            pe_limit_buffer = high_limit if total_pe_qty >= 3 * qty else base_limit

            # =========================================================
            # ===================== BULLISH ============================
            # =========================================================
            if bullish:
                print(f"{sym} BULLISH")

                ce_trigger = ce_candle["high"] + trigger_buffer
                pe_trigger = pe_candle["low"] - trigger_buffer

                ce_limit = ce_trigger + ce_limit_buffer
                pe_limit = pe_trigger - pe_limit_buffer

                entry_msg = f"""{sym} BULLISH

                BUY CE: {ce_symbol} @ {round(ce_trigger,2)}
                SELL PE: {pe_symbol} @ {round(pe_trigger,2)}
                Qty: {qty}
                """

                if DEMO_MODE:
                    send_telegram(entry_msg)
                else:
                    place_sl_entry(ce_symbol, qty, ce_trigger, ce_limit, "BUY")
                    place_sl_entry(pe_symbol, qty, pe_trigger, pe_limit, "SELL")

                # ===== SL =====
                ce_sl_trigger = (
                    ce_prev1["low"] - trigger_buffer
                    if total_ce_qty >= 3 * qty
                    else min(ce_prev1["low"], ce_prev2["low"])
                )

                pe_sl_trigger = (
                    pe_prev1["high"] + trigger_buffer
                    if total_pe_qty >= 3 * qty
                    else max(pe_prev1["high"], pe_prev2["high"])
                )

                ce_sl_limit = ce_sl_trigger - ce_limit_buffer
                pe_sl_limit = pe_sl_trigger + pe_limit_buffer

                ce_sl_msg = f"""SL CE:
                {ce_symbol}
                Trigger: {round(ce_sl_trigger,2)} | Limit: {round(ce_sl_limit,2)}
                Qty: {total_ce_qty}
                """

                pe_sl_msg = f"""SL PE:
                {pe_symbol}
                Trigger: {round(pe_sl_trigger,2)} | Limit: {round(pe_sl_limit,2)}
                Qty: {total_pe_qty}
                """

                if DEMO_MODE:
                    send_telegram(ce_sl_msg)
                    send_telegram(pe_sl_msg)
                else:
                    cancel_existing_sl(ce_symbol)
                    cancel_existing_sl(pe_symbol)
                    place_sl(ce_symbol, total_ce_qty, ce_sl_trigger, ce_sl_limit, "SELL")
                    place_sl(pe_symbol, total_pe_qty, pe_sl_trigger, pe_sl_limit, "BUY")

            # =========================================================
            # ===================== BEARISH ============================
            # =========================================================
            elif bearish:
                print(f"{sym} BEARISH")

                pe_trigger = pe_candle["low"] - trigger_buffer
                ce_trigger = ce_candle["high"] + trigger_buffer

                pe_limit = pe_trigger - pe_limit_buffer
                ce_limit = ce_trigger + ce_limit_buffer

                entry_msg = f"""{sym} BEARISH

                BUY PE: {pe_symbol} @ {round(pe_trigger,2)}
                SELL CE: {ce_symbol} @ {round(ce_trigger,2)}
                Qty: {qty}
                """

                if DEMO_MODE:
                    send_telegram(entry_msg)
                else:
                    place_sl_entry(pe_symbol, qty, pe_trigger, pe_limit, "BUY")
                    place_sl_entry(ce_symbol, qty, ce_trigger, ce_limit, "SELL")

                pe_sl_trigger = (
                    pe_prev1["high"] + trigger_buffer
                    if total_pe_qty >= 3 * qty
                    else max(pe_prev1["high"], pe_prev2["high"])
                )

                ce_sl_trigger = (
                    ce_prev1["low"] - trigger_buffer
                    if total_ce_qty >= 3 * qty
                    else min(ce_prev1["low"], ce_prev2["low"])
                )

                pe_sl_limit = pe_sl_trigger + pe_limit_buffer
                ce_sl_limit = ce_sl_trigger - ce_limit_buffer

                pe_sl_msg = f"""SL PE:
                {pe_symbol}
                Trigger: {round(pe_sl_trigger,2)} | Limit: {round(pe_sl_limit,2)}
                Qty: {total_pe_qty}
                """

                ce_sl_msg = f"""SL CE:
                {ce_symbol}
                Trigger: {round(ce_sl_trigger,2)} | Limit: {round(ce_sl_limit,2)}
                Qty: {total_ce_qty}
                """

                if DEMO_MODE:
                    send_telegram(pe_sl_msg)
                    send_telegram(ce_sl_msg)
                else:
                    cancel_existing_sl(pe_symbol)
                    cancel_existing_sl(ce_symbol)
                    place_sl(pe_symbol, total_pe_qty, pe_sl_trigger, pe_sl_limit, "SELL")
                    place_sl(ce_symbol, total_ce_qty, ce_sl_trigger, ce_sl_limit, "BUY")

        except Exception as e:
            print(f"Error in {sym}: {e}")

def wait_for_next_candle():
        while True:
            now = datetime.now()
            seconds_left = ((29 - now.minute % 30) * 60) + (60 - now.second)
            print(f"Next candle in {seconds_left} sec", end="\r")
            if now.minute % 30 == 0 and now.second == 0:
                print("\nNew candle started")
                break
            time.sleep(1)


# ================= RUN =================

if __name__ == "__main__":
    send_telegram("✅ Telegram Test: Bot is working!")
    import time
    #==============LOAD TOKEN===================
    spot_instruments = kite.instruments("NSE")
    for ins in spot_instruments:
        if ins["tradingsymbol"] in SYMBOLS:
            token_map[ins["instrument_token"]] = ins["tradingsymbol"] 

    kws = KiteTicker(API_KEY, kite.access_token)
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.connect(threaded=True)
    time.sleep(5)       

    while True:
        wait_for_next_candle()
        run_strategy()




    

        