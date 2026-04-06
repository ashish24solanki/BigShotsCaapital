# ==========================================================

# FINAL COMBINED TRADING BOT (10:45 + 16:55)

# ==========================================================

import os
import sys
import time
import threading
import requests
import datetime as dt
from kiteconnect import KiteConnect, KiteTicker


# =====================================================

# PATH SETUP

# =====================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET


from config.bot_config import DEMO_BOT_CHAT_ID, DEMO_BOT_TOKEN

TOKEN = DEMO_BOT_TOKEN
CHAT_ID = DEMO_BOT_CHAT_ID

# =====================================================

# Telegram Message
#======================================================

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    try:
        requests.post(url, data=data, timeout = 5)
    except Exception as e:
        print("Telegram error:", e)

# =====================================================

# GLOBAL CONFIG

# =====================================================

MARKET_END = dt.time(17, 0, 0)

# =====================================================

# LOGIN

# =====================================================

def get_kite():
    from kiteconnect import KiteConnect
    import subprocess
    import time

    kite = KiteConnect(api_key=API_KEY)

    def load_token():
        with open("/root/access_token.txt", "r") as f:
            return f.read().strip()

    # ===== 1. TRY EXISTING TOKEN =====
    try:
        token = load_token()
        kite.set_access_token(token)
        kite.profile()
        print("✅ Login successful (cached token)")
        send_telegram("✅ Bot Logged In Successfully (Cached Token)")
        return kite

    except Exception as e:
        print("⚠️ Token failed:", e)

    # ===== 2. AUTO LOGIN =====
    print("🔄 Running auto_login.py...")

    subprocess.run([
        "/root/tradingenv/bin/python",
        "/root/auto_login.py"
    ])

    time.sleep(3)

    # ===== 3. RETRY WITH NEW TOKEN =====
    try:
        token = load_token()
        kite.set_access_token(token)
        kite.profile()
        print("✅ Login successful (auto refreshed token)")
        send_telegram("🔄 Bot Auto Login Successful (New Token)")
        return kite

    except Exception as e:
        print("❌ Auto login failed:", e)
        exit()

    

# =====================================================

# COMMON UTILS

# =====================================================

def round_to_tick(price, tick_size):
    return round(round(price / tick_size) * tick_size, 2)


#=================PREV DAY HIGH LOW========================

def get_prev_day_high_low(kite, token):

    try:
        data = kite.historical_data(
            instrument_token=token,
            from_date=dt.datetime.now() - dt.timedelta(days=10),
            to_date=dt.datetime.now(),
            interval="day"
        )
        
        if not data:
            return None, None
        
        today = dt.datetime.now().date()



        for candle in reversed(data):
            if candle["date"].date() < today:
                return candle["high"], candle["low"]

        return None, None
    except Exception as e:
        print("Error fetching Prev HL", e)
        return None, None


# =====================================================

# ================= 10:45 ENGINE =======================

# =====================================================

def run_1045(kite):


    print("\n========== 10:45 ENGINE START ==========\n")

    positions = kite.positions()["net"]

    tokens = []
    symbol_map = {}
    position_map = {}
    previous_close_map = {}
    latest_price = {}

    for pos in positions:

        if abs(pos["quantity"]) == 0:
            continue

        if pos["exchange"] != "NFO":
            continue

        symbol = pos["tradingsymbol"]
        #===================FUTURES SL=======================
        if symbol.endswith("FUT"):
            print(f"\nRunning FUTURE SL ENGINE for {symbol}")
            token = pos["instrument_token"]
            qty = abs(int(pos["quantity"]))
            if qty == 0:
                continue

            prev_high, prev_low = get_prev_day_high_low(kite, token )
            if prev_high is None or prev_low is None:
                print(f"{symbol} prev day data not found")
                continue

            try:
                quote = kite.ltp(f"NFO:{symbol}")
                ltp = quote[f"NFO:{symbol}"]["last_price"]
            except Exception as e:
                print(f"{symbol} LTP fetch failed: {e}")
                continue

            print(f"{symbol} | LTP: {ltp} | Prev High: {prev_high} | Prev Low: {prev_low}")

            tick_size = 0.20
            buffer = 0.05

            #============Short Position=======================
            if pos["quantity"] < 0:
                trigger = round_to_tick(prev_high + buffer, tick_size)
                limit_price = round_to_tick(trigger + 0.2, tick_size)
                print(f"{symbol} SHORT SL -> BUY @ {limit_price}")
                if qty <= 0:
                    continue
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="BUY",
                    quantity=qty,
                    order_type="SL",
                    trigger_price=trigger,
                    price=limit_price,
                    product=pos.get("product", "NRML"),
                )
            #============Long Position=======================
            else:
                trigger = round_to_tick(prev_low - buffer, tick_size)
                limit_price = round_to_tick(trigger - 0.1, tick_size)
                print(f"{symbol} LONG SL -> SELL @ {limit_price}")
                if qty <= 0:
                    continue
                kite.place_order(
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=symbol,
                    transaction_type="SELL",
                    quantity=qty,
                    order_type="SL",
                    trigger_price=trigger,
                    price=limit_price,
                    product=pos.get("product", "NRML"), 
                )
            continue
        #===================FUTURES SL END=======================

        if not symbol.endswith(("CE", "PE")):
            continue

        token = pos["instrument_token"]

        tokens.append(token)
        symbol_map[token] = symbol
        position_map[token] = pos

    if not tokens:
        print("No option positions found")
        return

    # Fetch previous close
    for token in tokens:
        try:
            data = kite.historical_data(
            instrument_token=token,
            from_date=dt.datetime.now() - dt.timedelta(days=10),
            to_date=dt.datetime.now(),
            interval="day"
            )
            
            if data:
                today = dt.datetime.now().date()

                #Find Last Completed trading day(Not today)
                for candle in reversed(data):
                    candle_date = candle["date"].date()
                    if candle_date < today:
                         previous_close_map[token] = candle["close"]
                         break
            
        except Exception as e:
            print("Error fetching previous close:", e)
            

    kws = KiteTicker(API_KEY, kite.access_token)

    executed = {"done": False}

    def on_ticks(ws, ticks):

        now = dt.datetime.now()

        for tick in ticks:
            latest_price[tick["instrument_token"]] = tick["last_price"]

        if now.time() >= dt.time(10, 45, 5) and not executed["done"]:

            print("\nExecuting 10:45 logic...\n")

            for token in tokens:

                if token not in latest_price or token not in previous_close_map:
                    continue

                ltp = latest_price[token]
                y_close = previous_close_map[token]
                symbol = symbol_map[token]
                pos = position_map[token]
                buffer = 0.1

                if pos["quantity"] == 0:
                    continue

                qty = abs(int(pos["quantity"]))

                if ltp < y_close:
                    limit_price = round_to_tick(ltp + buffer, 0.05)
                    order_type = "LIMIT"
                else:
                    trigger = round_to_tick(y_close , 0.05)
                    limit_price = round_to_tick(trigger - max(buffer,0.1), 0.05)
                    order_type = "SL"

                try:
                    params = dict(
                        variety="regular",
                        exchange="NFO",
                        tradingsymbol=symbol,
                        transaction_type="SELL",
                        quantity=qty,
                        product=pos.get("product", "NRML"),
                    )

                    if order_type == "SL":
                        params.update({
                            "order_type": "SL",
                            "trigger_price": trigger,
                            "price": limit_price
                        })
                        
                    else:
                        params.update({
                            "order_type": "LIMIT",
                            "price": limit_price
                        })

                    kite.place_order(**params)
                    print(f"{symbol} order placed")

                except Exception as e:
                    print(f"{symbol} error:", e)

                
            executed["done"] = True
            ws.close()

    def on_connect(ws, response):
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_LTP, tokens)

    def on_close(ws, code, reason):
        print("WebSocket closed")

    kws.on_ticks = on_ticks
    kws.on_connect = on_connect
    kws.on_close = on_close
    while True:
        try:
            kws.connect()
            break
        except Exception as e:
            print("WebSocket connection error, retrying..", e)
            time.sleep(5)




# =====================================================

# ================= 16:55 ENGINE =======================

# =====================================================

def run_1655(kite):


    print("\n========== 16:55 HEDGE START ==========\n")
    try:
        send_telegram("🚀 16:55 Hedge Started")
    except Exception as e:
        pass


    positions = kite.positions()["net"]
    if not positions:
        print("No positions for hedge")
        return
    instruments = kite.instruments("NFO")

    valid_positions = [p for p in positions if p["exchange"] == "NFO" and "FUT" in p["tradingsymbol"]]

    if not valid_positions:
        print("No FUT positions for hedging")
        send_telegram("⚠️ No FUT positions for hedge")
        return

    for pos in valid_positions:

        if pos["quantity"] == 0:
            continue

        underlying = next(
            (i["name"] for i in instruments if i["tradingsymbol"] == pos["tradingsymbol"]),
            None
            )
    

        if not underlying:
            continue

        matching = [i for i in instruments if i["name"] == underlying]

        if not matching:
            continue

        strikes = sorted(set(i["strike"] for i in matching if i["strike"] > 0))
        if not strikes:
            continue
        
        step = strikes[1] - strikes[0]

        try:
            spot = kite.ltp(f"NSE:{underlying}")
            if not spot:
                continue 
            spot_price = list(spot.values())[0]["last_price"]
            

        except Exception as e:
            print(f"Error: {e}")
            continue

        atm = round(spot_price / step) * step
        option_type = "PE" if pos["quantity"] > 0 else "CE"

        selected = [
            i for i in matching
            if i["strike"] == atm and i["instrument_type"] == option_type
        ]

        if not selected:
            continue

        option_symbol = selected[0]["tradingsymbol"]
        qty = abs(pos["quantity"])

        try:
            quote = kite.ltp([f"NFO:{option_symbol}"])
            if f"NFO:{option_symbol}" not in quote:
                print(f"LTP missing for {option_symbol}")
                continue
            ltp = quote[f"NFO:{option_symbol}"]["last_price"]
        except Exception as e:
            print(f"Error: {e}")
            continue

        price = round_to_tick(ltp * 1.01, 0.05)
        print(f"Placing hedge → {option_symbol} | Qty: {qty} | LTP: {ltp} | Price: {price}")
        try:
            send_telegram(f"⚡ Hedge Order: {option_symbol} | Qty: {qty}")
        except Exception as e:
            print(f"Telegram error (entry): {e}")

        

        def place_order_safe():
            try:
                kite.place_order(
                    tradingsymbol=option_symbol,
                    exchange="NFO",
                    transaction_type="BUY",
                    quantity=qty,
                    order_type="LIMIT",
                    product="NRML",
                    variety="regular",
                    price=price
                )

                print(f"✅ Hedge placed: {option_symbol}")

                # ✅ SAFE TELEGRAM (non-blocking safe)
                try:
                    send_telegram(f"✅ Hedge placed: {option_symbol}")
                except Exception as te:
                    print(f"Telegram error (success msg): {te}")

            except Exception as e:
                print(f"❌ Hedge error: {option_symbol} {e}")

                # ✅ SAFE TELEGRAM (error case)
                try:
                    send_telegram(f"❌ Hedge error: {option_symbol}")
                except Exception as te:
                    print(f"Telegram error (error msg): {te}")


        # ===== THREAD EXECUTION =====
        t = threading.Thread(target=place_order_safe)
        t.daemon = True   # ✅ ensures no zombie threads
        t.start()

        t.join(timeout=5)

        # ===== TIMEOUT HANDLING =====
        if t.is_alive():
            print(f"⏳ Timeout placing: {option_symbol}")

            try:
                send_telegram(f"⚠️ Timeout placing: {option_symbol}")
            except Exception as te:
                print(f"Telegram error (timeout): {te}")

            # ✅ DO NOT wait further → move to next
            # thread will auto-kill because daemon=True

        # ===== API RATE SAFETY =====
        time.sleep(0.5)

    print("✅ 16:55 Hedge Completed")
    try:
        send_telegram("✅ Hedge Execution Completed")
    except:
        pass


# =====================================================

# ================= SCHEDULER ==========================

# =====================================================

def scheduler():


    kite = get_kite()

    # ================= SHOW POSITIONS IMMEDIATELY =================
    try:
        positions = kite.positions()["net"]

        print("\n📊 CURRENT OPEN POSITIONS:\n")

        has_position = False

        for pos in positions:
            if pos["quantity"] != 0:
                has_position = True
                print(f"{pos['tradingsymbol']} | Qty: {pos['quantity']}")

        if not has_position:
            print("No open positions")

        print("\n=====================================\n")

    except Exception as e:
        print("Error fetching positions:", e)



    executed_1045 = False
    executed_1655 = False

    print("\n🚀 BOT STARTED (Bangkok Time)\n")

    printed_1045_missed = False
    printed_1655_wait = False

    while True:
        try:
            kite.profile()
        except Exception:
            print("Session expired, Re login")
            kite = get_kite()

        now = dt.datetime.now().time()

        if not (
            dt.time(10, 45) <= now <= dt.time(11, 30)
            or dt.time(16, 55) <= now <= dt.time(17, 15)):
            time.sleep(5)
            continue

        

        #=============== 10:45=========================
        if dt.time(10, 45) <= now <= dt.time(11, 0) and not executed_1045:
            print("\n⏰ Executing 10:45 Exit\n")
            run_1045(kite)
            executed_1045 = True
        elif now > dt.time(11, 0) and not executed_1045 and not printed_1045_missed:
            print("\n Missed 10:45 window\n")
            printed_1045_missed = True

        #=============== 16:55=========================
        if dt.time(16, 55) <= now <= dt.time(17, 0) and not executed_1655:
            print("\n⏰ Executing 16:55 Hedge\n")
            run_1655(kite)
            executed_1655 = True
        elif now < dt.time(16, 55) and not executed_1655 and not printed_1655_wait:
            print("\n Waiting for 16:55 window\n")
            printed_1655_wait = True
        elif now > dt.time(17, 5) and not executed_1655:
            print("\n Market closed \n")


        # reset next day
        if now.hour == 0 and now.minute == 1:
            executed_1045 = False
            executed_1655 = False
            printed_1045_missed = False
            printed_1655_wait = False


        time.sleep(5)


# =====================================================

# ENTRY

# =====================================================

if __name__ == "__main__":
    scheduler()
