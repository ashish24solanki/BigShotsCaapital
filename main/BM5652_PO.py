# ==========================================================
# BANGKOK 10:45:05 OPTION POSITION LIMIT EXIT
# SINGLE FILE | CLEAN | SAFE EXECUTION
# ==========================================================

import os
import sys
import datetime as dt
import webbrowser
import time
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

BUFFER_PCT = 0.2  # 0.2% below LTP
CAPTURE_TIME = dt.time(10, 45, 5)
MARKET_END = dt.time(17, 0, 0)


# =====================================================
# TICK SIZE ROUNDING
# =====================================================

def round_to_tick(price, tick_size):
    return round(round(price / tick_size) * tick_size, 2)


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


# =====================================================
# WAIT FOR MARKET OPEN
# =====================================================

def wait_for_market_open():
    market_open = dt.time(10, 45)

    now = dt.datetime.now().time()

    if now < market_open:
        print("Market not open yet for SL orders. Waiting for 10:45 Bangkok...")

        while dt.datetime.now().time() < market_open:
            time.sleep(5)

    print("Market open. SL engine active.")


# =====================================================
# GET PREVIOUS DAY CLOSE
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
# FUTURE STOPLOSS ENGINE
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

    # ================= SHORT =================
    if pos["quantity"] < 0:

        print(f"\n{symbol} SHORT | LTP: {ltp} | PrevHigh: {prev_high}")

        if ltp < prev_high:

            trigger = round_to_tick(prev_high + buffer, tick_size)
            limit_price = round_to_tick(trigger * (1 + limit_buffer_pct), tick_size)

            print(f"{symbol} SL-LIMIT BUY | Trigger: {trigger} | Limit: {limit_price}")

            if live:
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="BUY",
                    quantity=qty,
                    order_type="SL",
                    product=product,
                    trigger_price=trigger,
                    price=limit_price
                )
            else:
                print("MOCK ORDER — No real execution")

        else:

            limit_price = round_to_tick(ltp * (1 + 0.001), tick_size)

            print(f"{symbol} EMERGENCY LIMIT BUY @ {limit_price}")

            if live:
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="BUY",
                    quantity=qty,
                    order_type="LIMIT",
                    product=product,
                    price=limit_price
                )
            else:
                print("MOCK ORDER — No real execution")

    # ================= LONG =================
    else:

        print(f"\n{symbol} LONG | LTP: {ltp} | PrevLow: {prev_low}")

        if ltp > prev_low:

            trigger = round_to_tick(prev_low - buffer, tick_size)
            limit_price = round_to_tick(trigger * (1 - limit_buffer_pct), tick_size)

            print(f"{symbol} SL-LIMIT SELL | Trigger: {trigger} | Limit: {limit_price}")

            if live:
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="SELL",
                    quantity=qty,
                    order_type="SL",
                    product=product,
                    trigger_price=trigger,
                    price=limit_price
                )
            else:
                print("MOCK ORDER — No real execution")

        else:

            limit_price = round_to_tick(ltp * (1 - 0.001), tick_size)

            print(f"{symbol} EMERGENCY LIMIT SELL @ {limit_price}")

            if live:
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="SELL",
                    quantity=qty,
                    order_type="LIMIT",
                    product=product,
                    price=limit_price
                )
            else:
                print("MOCK ORDER — No real execution")


def safe_get_positions(kite, retries=3):
    for i in range(retries):
        try:
            return kite.positions()["net"], kite

        except Exception as e:
            print(f"[Retry {i+1}] positions fetch failed: {e}")

            # Re-login on failure
            try:
                kite = get_kite()
            except:
                pass

            time.sleep(1)

    raise Exception("Failed to fetch positions after retries")


# =====================================================
# LIVE EXECUTION (OPTIONS ONLY)
# =====================================================

def main():

    kite = get_kite()
    
    positions, kite = safe_get_positions(kite)
    wait_for_market_open()   

    try:
        kite.profile()
    except:
        kite = get_kite()
    
    now_init = dt.datetime.now()
    target = now_init.replace(hour=10, minute=45, second=5, microsecond=0)

    if now_init > target:
        target = now_init
        window_end = target + dt.timedelta(seconds=10)
    else:
        window_end = target + dt.timedelta(seconds=55)

    tokens = []
    symbol_map = {}
    position_map = {}
    previous_close_map = {}
    latest_price = {}

    # Collect ONLY open NFO OPTION positions
    for pos in positions:

        if pos["quantity"] == 0:
            continue

        if pos["exchange"] != "NFO":
            continue

        symbol = pos["tradingsymbol"]

        # ================= FUTURES =================
        if symbol.endswith("FUT"):
            print(f"\nRunning FUTURE SL ENGINE for {symbol}")
            place_future_sl_order(kite, pos, live=True)
            continue

        # ================= OPTIONS =================
        if not symbol.endswith(("CE", "PE")):
            continue

        token = pos["instrument_token"]

        tokens.append(token)
        symbol_map[token] = symbol
        position_map[token] = pos

    if not tokens:
        print("No active NFO option positions.")
        return

    # Fetch yesterday close
    for token in tokens:
        close_price = get_previous_day_close(kite, token)
        if close_price:
            previous_close_map[token] = close_price

    print("Monitoring Options:", list(symbol_map.values()))
    
    executed_symbols = set()
    order_executed = False
    kws = KiteTicker(API_KEY, kite.access_token)

    # -------------------------------------------------
    # ON TICKS
    # -------------------------------------------------

    def on_ticks(ws, ticks):
        nonlocal order_executed, executed_symbols

        now_dt = dt.datetime.now()

        # Update latest prices
        for tick in ticks:
            latest_price[tick["instrument_token"]] = tick["last_price"]

        # Execute only once after target time
        if not order_executed and now_dt >= target:

            print(f"\nExecution window hit at {now_dt.strftime('%H:%M:%S')} — checking conditions...\n")

            order_executed = True

            for token in tokens:

                if token not in latest_price:
                    continue

                if token not in previous_close_map:
                    continue

                ltp = latest_price[token]
                y_close = previous_close_map[token]
                symbol = symbol_map[token]

                if symbol in executed_symbols:
                    continue

                pos = position_map[token]
                qty = abs(int(pos["quantity"]))

                print(f"{symbol} | LTP: {ltp} | Prev Close: {y_close}")

                # ================================
                # CASE 1: LTP BELOW PREV CLOSE → DIRECT EXIT
                # ================================
                if ltp < y_close:

                    buffer = ltp * (BUFFER_PCT / 100)
                    limit_price = round_to_tick(ltp - buffer, 0.05)

                    print(f"{symbol} BEARISH EXIT → LIMIT SELL @ {limit_price}")

                    order_type = "LIMIT"
                    trigger_price = None

                # ================================
                # CASE 2: LTP ABOVE PREV CLOSE → SL PROTECTION
                # ================================
                else:

                    buffer = max(0.05, y_close * 0.002)
                    trigger_price = round_to_tick(y_close + buffer, 0.05)
                    limit_price = round_to_tick(y_close, 0.05)

                    print(f"{symbol} BULLISH → SL SELL")
                    print(f"Trigger: {trigger_price} | Limit: {limit_price}")

                    order_type = "SL"

                # ================================
                # ORDER EXECUTION
                # ================================
                try:
                    if pos["quantity"] <= 0:
                        print(f"{symbol} not a long hedge → skipping")
                        continue

                    if qty <= 0:
                        print(f"{symbol} invalid qty → skipping")
                        continue

                    print(f"{symbol} Placing {order_type} SELL @ {limit_price}")

                    order_params = dict(
                        variety="regular",
                        exchange="NFO",
                        tradingsymbol=symbol,
                        transaction_type="SELL",
                        quantity=qty,
                        product=pos.get("product", "NRML"),
                    )

                    if order_type == "SL":
                        order_params.update({
                            "order_type": "SL",
                            "trigger_price": trigger_price,
                            "price": limit_price
                        })
                    else:
                        order_params.update({
                            "order_type": "LIMIT",
                            "price": limit_price
                        })

                    kite.place_order(**order_params)

                    executed_symbols.add(symbol)

                    print(f"{symbol} Order Placed Successfully\n")

                    time.sleep(0.2)

                except Exception as e:
                    print(f"{symbol} Order Failed:", e)

            # ✅ CLOSE WS AFTER ALL ORDERS
            print("Execution complete. Closing WebSocket.")
            ws.close()

        # Safety exit
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


# =====================================================
# TEST MODE WITH MOCK SIMULATION (NO ORDERS)
# =====================================================

def run_test_mode():

    kite = get_kite()
    positions = kite.positions()["net"]

    print("\n========== TEST MODE (MOCK SIMULATION) ==========\n")

    found = False

    for pos in positions:

        if pos["quantity"] == 0:
            continue

        if pos["exchange"] != "NFO":
            continue

        symbol = pos["tradingsymbol"]

        # ================= FUTURES =================
        if symbol.endswith("FUT"):
            print(f"\nRunning FUTURE SL ENGINE for {symbol}")
            place_future_sl_order(kite, pos, live=False)
            continue

        # ================= OPTIONS =================
        if not symbol.endswith(("CE", "PE")):
            continue

        found = True

        token = pos["instrument_token"]
        qty = abs(int(pos["quantity"]))

        prev_close = get_previous_day_close(kite, token)

        try:
            quote = kite.ltp(f"NFO:{symbol}")
            ltp = quote[f"NFO:{symbol}"]["last_price"]
        except Exception as e:
            print(f"{symbol} LTP fetch failed:", e)
            continue

        print("--------------------------------------------------")
        print(f"Symbol         : {symbol}")
        print(f"Quantity       : {qty}")
        print(f"Yesterday Close: {prev_close}")
        print(f"Current LTP    : {ltp}")

        if prev_close is None:
            print("Previous close not available.")
            print("--------------------------------------------------\n")
            continue

        if ltp < prev_close:
            buffer = ltp * (BUFFER_PCT / 100)
            limit_price = round_to_tick(ltp - buffer, 0.05)

            print("Condition      : LTP < Yesterday Close ✅")
            print("MOCK ORDER     : LIMIT SELL")
            print(f"Limit Price    : {limit_price}")

        else:
            print("Condition      : LTP >= Yesterday Close ❌")
            print("No trade would be placed.")

        print("--------------------------------------------------\n")

    if not found:
        print("No open NFO option positions found.")

    print("========== TEST COMPLETE — NO ORDERS PLACED ==========\n")


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":

    print("\nSelect Mode:")
    print("1 - Live Execution")
    print("2 - Test Mode (Mock Simulation)")

    choice = input("Enter choice: ").strip()

    if choice == "1":
        main()
    else:
        run_test_mode()