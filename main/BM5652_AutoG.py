# ==========================================================
# COMBINED: BM5652 - AUTO HEDGE (16:55) + POSITION LIMIT EXIT (10:45:05)
# SINGLE FILE | BANGKOK TIME | FULL LOGIC PRESERVED
# ==========================================================

import os
import sys
import time
import datetime as dt
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
# COMMON CONFIG
# =====================================================

EXECUTION_HEDGE_TIME = dt.time(16, 55, 0)      # 16:55 Bangkok - Hedge
CAPTURE_TIME_PO = dt.time(10, 45, 5)           # 10:45:05 Bangkok - Position Exit
MARKET_END = dt.time(17, 0, 0)

BUFFER_PCT = 0.2          # For PO script
TRIGGER_BUFFER_PCT = 0.002
LIMIT_BUFFER_PCT = 0.002


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
            print("Login successful (cached token)")
            return kite
        except:
            print("Token expired")

    webbrowser.open(kite.login_url())
    redirected_url = input("Paste FULL redirected URL:\n").strip()
    request_token = redirected_url.split("request_token=")[1].split("&")[0]

    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    with open(ACCESS_TOKEN_FILE, "w") as f:
        f.write(access_token)

    kite.set_access_token(access_token)
    return kite


# ======================================================
# EXPIRY LOGIC (HG)
# ======================================================

def get_correct_expiry(instruments, underlying):
    today = dt.datetime.now().date()

    expiries = sorted(set(
        i["expiry"] for i in instruments
        if i["name"] == underlying and i["segment"] == "NFO-OPT"
    ))

    if not expiries:
        return None

    if today.day > 20:
        return expiries[1] if len(expiries) > 1 else expiries[0]

    return expiries[0]


# =====================================================
# SPOT PRICE (HG)
# =====================================================

def get_spot_price(kite, underlying):
    try:
        index_map = {
            "NIFTY": "NSE:NIFTY 50",
            "BANKNIFTY": "NSE:NIFTY BANK",
            "FINNIFTY": "NSE:NIFTY FIN SERVICE",
            "MIDCPNIFTY": "NSE:NIFTY MID SELECT"
        }

        symbol = index_map.get(underlying, f"NSE:{underlying}")
        quote = kite.ltp(symbol)
        return list(quote.values())[0]["last_price"]

    except Exception as e:
        print(f"Failed to fetch spot price: {e}")
        return None


# =====================================================
# TICK SIZE ROUNDING (PO)
# =====================================================

def round_to_tick(price, tick_size):
    return round(round(price / tick_size) * tick_size, 2)


# =====================================================
# GET PREVIOUS DAY CLOSE (PO)
# =====================================================

def get_previous_day_close(kite, token):
    try:
        to_dt = dt.datetime.now()
        from_dt = to_dt - dt.timedelta(days=7)

        data = kite.historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval="day"
        )

        if len(data) < 2:
            return None

        return data[-2]["close"]

    except Exception as e:
        print("Failed to fetch previous close:", e)
        return None


# =====================================================
# FUTURE STOPLOSS ENGINE (PO)
# =====================================================

def place_future_sl_order(kite, pos, live=True):
    symbol = pos["tradingsymbol"]
    token = pos["instrument_token"]
    qty = abs(int(pos["quantity"]))
    product = pos.get("product", "NRML")

    try:
        quote = kite.ltp(f"NFO:{symbol}")
        ltp = quote[f"NFO:{symbol}"]["last_price"]
    except Exception as e:
        print(f"{symbol} LTP fetch failed:", e)
        return

    try:
        to_dt = dt.datetime.now()
        from_dt = to_dt - dt.timedelta(days=7)
        data = kite.historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval="day"
        )

        if len(data) < 2:
            print(f"{symbol} Not enough historical data")
            return

        prev_day = data[-2]
        prev_high = prev_day["high"]
        prev_low = prev_day["low"]

    except Exception as e:
        print(f"{symbol} Historical fetch failed:", e)
        return

    tick_size = 0.20
    buffer = 0.05
    limit_buffer_pct = 0.001

    # SHORT
    if pos["quantity"] < 0:
        print(f"\n{symbol} SHORT | LTP: {ltp} | PrevHigh: {prev_high}")

        if ltp < prev_high:
            trigger = round_to_tick(prev_high + buffer, tick_size)
            limit_price = round_to_tick(trigger * (1 + limit_buffer_pct), tick_size)
            print(f"{symbol} SL-LIMIT BUY | Trigger: {trigger} | Limit: {limit_price}")

            if live:
                kite.place_order(variety="regular", exchange="NFO", tradingsymbol=symbol,
                                 transaction_type="BUY", quantity=qty, order_type="SL",
                                 product=product, trigger_price=trigger, price=limit_price)
        else:
            limit_price = round_to_tick(ltp * (1 + 0.001), tick_size)
            print(f"{symbol} EMERGENCY LIMIT BUY @ {limit_price}")
            if live:
                kite.place_order(variety="regular", exchange="NFO", tradingsymbol=symbol,
                                 transaction_type="BUY", quantity=qty, order_type="LIMIT",
                                 product=product, price=limit_price)

    # LONG
    else:
        print(f"\n{symbol} LONG | LTP: {ltp} | PrevLow: {prev_low}")

        if ltp > prev_low:
            trigger = round_to_tick(prev_low - buffer, tick_size)
            limit_price = round_to_tick(trigger * (1 - limit_buffer_pct), tick_size)
            print(f"{symbol} SL-LIMIT SELL | Trigger: {trigger} | Limit: {limit_price}")

            if live:
                kite.place_order(variety="regular", exchange="NFO", tradingsymbol=symbol,
                                 transaction_type="SELL", quantity=qty, order_type="SL",
                                 product=product, trigger_price=trigger, price=limit_price)
        else:
            limit_price = round_to_tick(ltp * (1 - 0.001), tick_size)
            print(f"{symbol} EMERGENCY LIMIT SELL @ {limit_price}")
            if live:
                kite.place_order(variety="regular", exchange="NFO", tradingsymbol=symbol,
                                 transaction_type="SELL", quantity=qty, order_type="LIMIT",
                                 product=product, price=limit_price)


# =====================================================
# MAIN - 16:55 AUTO HEDGE (HG)
# =====================================================

def run_hedge_1655(kite):
    print("\n=== Starting 16:55 Auto Hedge Logic ===")
    
    positions = kite.positions()["net"]
    instruments = kite.instruments("NFO")

    # NEGATIVE OPTIONS (Square off shorts)
    negative_options = [
        p for p in positions
        if p["exchange"] == "NFO"
        and p["quantity"] < 0
        and p["tradingsymbol"].endswith(("CE", "PE"))
    ]

    # Process Futures → Buy Options Hedge
    for pos in positions:
        if pos["quantity"] == 0 or pos["exchange"] != "NFO" or "FUT" not in pos["tradingsymbol"]:
            continue

        fut_symbol = pos["tradingsymbol"]
        print(f"\nProcessing {fut_symbol}")

        underlying = next((ins["name"] for ins in instruments if ins["tradingsymbol"] == fut_symbol), None)
        if not underlying:
            continue

        expiry = get_correct_expiry(instruments, underlying)
        if not expiry:
            continue

        option_type = "PE" if pos["quantity"] > 0 else "CE"

        matching_options = [ins for ins in instruments if ins["name"] == underlying and 
                           ins["expiry"] == expiry and ins["instrument_type"] == option_type]

        if not matching_options:
            continue

        strikes = sorted(set(i["strike"] for i in matching_options))
        step = min([strikes[i+1] - strikes[i] for i in range(len(strikes)-1)])

        spot_price = get_spot_price(kite, underlying)
        if not spot_price:
            continue

        atm = round(spot_price / step) * step
        target = atm - step if pos["quantity"] > 0 else atm + step

        closest = min(matching_options, key=lambda x: abs(x["strike"] - target))
        option_symbol = closest["tradingsymbol"]

        lot_size = closest.get("lot_size")
        if not lot_size:
            continue

        qty = (abs(pos["quantity"]) // lot_size) * lot_size
        if qty == 0:
            continue

        # Adjust for existing short
        existing_short = next((p for p in negative_options if p["tradingsymbol"] == option_symbol), None)
        if existing_short:
            qty += abs(existing_short["quantity"])

        if qty <= 0:
            continue

        # LTP
        try:
            opt_ltp = kite.ltp([f"NFO:{option_symbol}"])[f"NFO:{option_symbol}"]["last_price"]
        except:
            continue

        if opt_ltp <= 1:
            continue

        limit_price = round(round((opt_ltp * 1.01)/0.05)*0.05, 2)

        # Check existing long
        existing_long = next((p for p in positions if p["tradingsymbol"] == option_symbol and p["quantity"] > 0), None)
        if existing_long:
            if abs(existing_long["quantity"]) >= qty:
                print(f"{option_symbol} already hedged → skipping")
                continue
            qty -= abs(existing_long["quantity"])

        if qty <= 0:
            continue

        print(f"BUY {option_symbol} QTY {qty} @ {limit_price}")
        kite.place_order(
            tradingsymbol=option_symbol, exchange="NFO", transaction_type="BUY",
            quantity=qty, order_type="LIMIT", product="NRML", variety="regular", price=limit_price
        )
        print("Order placed successfully")

    # Square off all short options
    print("\nChecking short options for square off...\n")
    for opt in negative_options:
        symbol = opt["tradingsymbol"]
        qty = abs(opt["quantity"])

        try:
            ltp = kite.ltp([f"NFO:{symbol}"])[f"NFO:{symbol}"]["last_price"]
            limit_price = round(round(ltp*1.01/0.05)*0.05, 2)

            print(f"{symbol} BUYBACK {qty} @ {limit_price}")
            kite.place_order(
                tradingsymbol=symbol, exchange="NFO", transaction_type="BUY",
                quantity=qty, order_type="LIMIT", product="NRML", variety="regular", price=limit_price
            )
        except Exception as e:
            print(f"Error squaring {symbol}: {e}")


# =====================================================
# MAIN - 10:45:05 POSITION EXIT (PO)
# =====================================================

def run_position_exit_1045(kite):
    print("\n=== Starting 10:45:05 Position Limit Exit Logic ===")
    
    positions, kite = safe_get_positions(kite)
    wait_for_market_open()

    tokens = []
    symbol_map = {}
    position_map = {}
    previous_close_map = {}
    latest_price = {}

    for pos in positions:
        if pos["quantity"] == 0 or pos["exchange"] != "NFO":
            continue

        symbol = pos["tradingsymbol"]

        if symbol.endswith("FUT"):
            print(f"\nRunning FUTURE SL ENGINE for {symbol}")
            place_future_sl_order(kite, pos, live=True)
            continue

        if not symbol.endswith(("CE", "PE")):
            continue

        token = pos["instrument_token"]
        tokens.append(token)
        symbol_map[token] = symbol
        position_map[token] = pos

    if not tokens:
        print("No active NFO option positions.")
        return

    for token in tokens:
        close_price = get_previous_day_close(kite, token)
        if close_price:
            previous_close_map[token] = close_price

    print("Monitoring Options:", list(symbol_map.values()))
    
    executed_symbols = set()
    order_executed = False
    kws = KiteTicker(API_KEY, kite.access_token)

    def on_ticks(ws, ticks):
        nonlocal order_executed, executed_symbols
        now_dt = dt.datetime.now()

        for tick in ticks:
            latest_price[tick["instrument_token"]] = tick["last_price"]

        if not order_executed and now_dt >= dt.datetime.now().replace(hour=10, minute=45, second=5, microsecond=0):
            print(f"\nExecution window hit at {now_dt.strftime('%H:%M:%S')} — placing exits...\n")
            order_executed = True

            for token in tokens:
                if token not in latest_price or token not in previous_close_map:
                    continue

                ltp = latest_price[token]
                y_close = previous_close_map[token]
                symbol = symbol_map[token]
                pos = position_map[token]
                qty = abs(int(pos["quantity"]))

                if symbol in executed_symbols or pos["quantity"] <= 0 or qty <= 0:
                    continue

                print(f"{symbol} | LTP: {ltp} | Prev Close: {y_close}")

                if ltp < y_close:
                    buffer = ltp * (BUFFER_PCT / 100)
                    limit_price = round_to_tick(ltp - buffer, 0.05)
                    print(f"{symbol} BEARISH EXIT → LIMIT SELL @ {limit_price}")
                    order_params = {
                        "variety": "regular", "exchange": "NFO", "tradingsymbol": symbol,
                        "transaction_type": "SELL", "quantity": qty, "product": pos.get("product", "NRML"),
                        "order_type": "LIMIT", "price": limit_price
                    }
                else:
                    buffer = max(0.05, y_close * 0.002)
                    trigger_price = round_to_tick(y_close + buffer, 0.05)
                    limit_price = round_to_tick(y_close, 0.05)
                    print(f"{symbol} BULLISH → SL SELL | Trigger: {trigger_price}")
                    order_params = {
                        "variety": "regular", "exchange": "NFO", "tradingsymbol": symbol,
                        "transaction_type": "SELL", "quantity": qty, "product": pos.get("product", "NRML"),
                        "order_type": "SL", "trigger_price": trigger_price, "price": limit_price
                    }

                try:
                    kite.place_order(**order_params)
                    executed_symbols.add(symbol)
                    print(f"{symbol} Order Placed Successfully")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"{symbol} Order Failed:", e)

            ws.close()

        if now_dt.time() > MARKET_END:
            ws.close()

    def on_connect(ws, response):
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_LTP, tokens)
        print("WebSocket connected. Waiting for 10:45:05...")

    def on_close(ws, code, reason):
        print("WebSocket closed.")

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    kws.connect()


def safe_get_positions(kite, retries=3):
    for i in range(retries):
        try:
            return kite.positions()["net"], kite
        except Exception as e:
            print(f"[Retry {i+1}] positions fetch failed: {e}")
            try:
                kite = get_kite()
            except:
                pass
            time.sleep(1)
    raise Exception("Failed to fetch positions after retries")


def wait_for_market_open():
    market_open = dt.time(10, 45)
    while dt.datetime.now().time() < market_open:
        time.sleep(5)
    print("Market open. SL engine active.")


# =====================================================
# TEST MODE
# =====================================================

def run_test_mode():
    print("\nTEST MODE\n")
    kite = get_kite()
    positions = kite.positions()["net"]
    for pos in positions:
        print(pos)


# =====================================================
# MAIN ENTRY
# =====================================================

if __name__ == "__main__":
    print("\n=== BM5652 Combined Script Started ===")
    print("This script will handle both 10:45:05 and 16:55 Bangkok logic.\n")

    kite = get_kite()

    while True:
        now = dt.datetime.now().time()

        # Run 10:45 Position Exit
        if now >= CAPTURE_TIME_PO and now < dt.time(11, 0):
            try:
                run_position_exit_1045(kite)
            except Exception as e:
                print(f"Error in 10:45 logic: {e}")

        # Run 16:55 Hedge
        if now >= EXECUTION_HEDGE_TIME:
            try:
                run_hedge_1655(kite)
                print("16:55 Hedge execution completed.")
                break  # Exit after hedge (or you can continue if needed)
            except Exception as e:
                print(f"Error in 16:55 hedge: {e}")

        time.sleep(10)