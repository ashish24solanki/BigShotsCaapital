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

lock_file ="/tmp/hedge.lock"
if os.path.exists(lock_file):
    print(" Hedge Already Running. Removing stale lock...")
    try:
        os.remove(lock_file)
    except:
        sys.exit()
open(lock_file, "w").close()
from flask import Flask, request

app = Flask(__name__)

SECRET_KEY = "BigShotsCapital_06"   # change this

@app.route("/token")
def get_token():
    try:
        if request.args.get("key") != SECRET_KEY:
            return "Unauthorized", 403

        with open("/root/access_token.txt") as f:
            return f.read().strip()
    except Exception as e:
        return str(e), 500


def start_token_server():
    app.run(host="0.0.0.0", port=5000, threaded=True)


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
        send_telegram("❌ Token Failed. Trying to auto login...")

    # ===== 2. AUTO LOGIN =====
    print("🔄 Running auto_login.py...")
    msg = "🔄 Running auto login..."
    print(msg)
    send_telegram(msg)

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
    msg = "🚀 10:45 Engine Started"
    print(msg)
    send_telegram(msg)

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
                msg = f"🔻 SHORT SL: {symbol} BUY @ {limit_price}"
                print(msg)
                send_telegram(msg)
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
                msg = f"🔺 LONG SL: {symbol} SELL @ {limit_price}"
                print(msg)
                send_telegram(msg)
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
                    msg = f"✅ Order Placed: {symbol}"
                    print(msg)
                    send_telegram(msg)

                except Exception as e:
                    print(f"{symbol} error:", e)
                    msg = f"❌ Order Failed: {symbol} | {e}"
                    print(msg)
                    send_telegram(msg)

                
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
            time.sleep(10)




# =====================================================

# ================= 16:55 ENGINE =======================

# =====================================================

def run_1655(kite):

    print("\n========== 16:55 HEDGE START ==========\n")

    try:
        send_telegram("🚀 16:55 Hedge Started")
    except:
        pass

    # ===== FETCH POSITIONS =====
    try:
        positions = kite.positions()["net"]
    except Exception as e:
        print("Error fetching positions:", e)
        return

    if not positions:
        msg = "⚠️ No positions for hedge"
        print(msg)
        send_telegram(msg)
        return

    # ===== FETCH INSTRUMENTS =====
    try:
        instruments = kite.instruments("NFO")
    except Exception as e:
        print("Error fetching instruments:", e)
        return

    # ===== FILTER FUTURES ONLY =====
    valid_positions = [
        p for p in positions
        if p["exchange"] == "NFO" and "FUT" in p["tradingsymbol"] and p["quantity"] != 0
    ]

    if not valid_positions:
        msg = "⚠️ No FUT positions for hedge"
        print(msg)
        send_telegram(msg)
        return

    # =========================================================
    # ================= MAIN LOOP ==============================
    # =========================================================
    for pos in valid_positions:

        underlying = pos["tradingsymbol"].split("FUT")[0]

        if not underlying:
            continue

        # ===== GET ALL OPTIONS =====
        matching = [
            i for i in instruments
            if i["name"] == underlying and i["segment"] == "NFO-OPT"
        ]

        if not matching:
            print(f"No options found for {underlying}")
            continue

        strikes = sorted(set(i["strike"] for i in matching if i["strike"] > 0))

        if len(strikes) < 2:
            print(f"Strike issue for {underlying}")
            continue

        step = strikes[1] - strikes[0]

        # ===== GET SPOT PRICE =====
        try:
            spot = kite.ltp(f"NSE:{underlying}")
            if not spot:
                print(f"Spot not found for {underlying}")
                continue

            spot_price = list(spot.values())[0]["last_price"]

        except Exception as e:
            print(f"Spot error: {underlying} {e}")
            continue

        # ===== FIND ATM =====
        atm = round(spot_price / step) * step

        # ===== OPTION TYPE =====
        option_type = "PE" if pos["quantity"] > 0 else "CE"

        selected = [
            i for i in matching
            if i["strike"] == atm and i["instrument_type"] == option_type
        ]

        if not selected:
            print(f"No ATM option found for {underlying}")
            continue

        option = selected[0]
        option_symbol = option["tradingsymbol"]
        qty = abs(pos["quantity"])

        # ===== GET OPTION LTP =====
        try:
            quote = kite.ltp([f"NFO:{option_symbol}"])

            if f"NFO:{option_symbol}" not in quote:
                print(f"LTP missing for {option_symbol}")
                continue

            ltp = quote[f"NFO:{option_symbol}"]["last_price"]

        except Exception as e:
            print(f"LTP error: {option_symbol} {e}")
            continue

        # ===== PRICE CALC =====
        price = round_to_tick(ltp * 1.01, 0.05)

        msg = f"⚡ Hedge Placing: {option_symbol} | Qty: {qty} | LTP: {ltp} | Price: {price}"
        print(msg)
        send_telegram(msg)

        # =====================================================
        # ================ ORDER FUNCTION =====================
        # =====================================================
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

                success_msg = f"✅ Hedge placed: {option_symbol}"
                print(success_msg)
                send_telegram(success_msg)

            except Exception as e:
                error_msg = f"❌ Hedge error: {option_symbol} | {e}"
                print(error_msg)
                send_telegram(error_msg)

        # ===== THREAD EXECUTION =====
        t = threading.Thread(target=place_order_safe)
        t.start()
        t.join(timeout=3)

        # ===== TIMEOUT HANDLING =====
        if t.is_alive():
            msg = f"⚠️ Timeout placing: {option_symbol}"
            print(msg)
            send_telegram(msg)

        # ===== API SAFETY =====
        time.sleep(0.5)

    # =====================================================
    # ================= COMPLETION ========================
    # =====================================================
    msg = "✅ 16:55 Hedge Completed"
    print(msg)
    send_telegram(msg)

    try:
        send_telegram("✅ Hedge Execution Completed")
    except:
        pass


def send_positions_snapshot(kite):
    try:
        positions = kite.positions()["net"]

        msg = "📊 OPEN POSITIONS:\n\n"

        has_pos = False

        for pos in positions:
            if pos["quantity"] != 0 and pos["exchange"] == "NFO":
                has_pos = True
                msg += f"{pos['tradingsymbol']} | Qty: {pos['quantity']}\n"

        if not has_pos:
            msg += "No open positions"

        send_telegram(msg)

    except Exception as e:
        print("Snapshot error:", e)


def damage_control(kite):
    print("Running Damage Control...")
    msg = "🛡 Running Damage Control..."
    print(msg)
    send_telegram(msg)

    positions = kite.positions()["net"]

    for pos in positions:

        if pos["exchange"] != "NFO":
            continue

        # Only check hedge options
        if not pos["tradingsymbol"].endswith(("CE", "PE")):
            continue

        qty = abs(pos["quantity"])

        # If hedge order not executed (qty still 0 or mismatch)
        if abs(pos["quantity"]) > 0:
            symbol = pos["tradingsymbol"]

            try:
                quote = kite.ltp(f"NFO:{symbol}")
                if f"NFO:{symbol}" not in quote:
                    continue

                ltp = quote[f"NFO:{symbol}"]["last_price"]

                price = round(ltp + 0.5, 2)

                print(f"⚠️ Replacing order: {symbol} @ {price}")
                msg = f"⚠️ Replacing Order: {symbol} @ {price}"
                print(msg)
                send_telegram(msg)

                kite.place_order(
                    tradingsymbol=symbol,
                    exchange="NFO",
                    transaction_type="BUY",
                    quantity= abs(pos["quantity"]),
                    order_type="LIMIT",
                    product="NRML",
                    variety="regular",
                    price=price
                )

                send_telegram(f"⚠️ Damage Control Order: {symbol} @ {price}")

            except Exception as e:
                print(f"Damage control error: {symbol} {e}")
                msg = f"❌ Damage Control Failed: {symbol} | {e}"
                print(msg)
                send_telegram(msg)
                

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
    damage_done = False

    print("\n🚀 BOT STARTED (Bangkok Time)\n")
    msg = "🚀 Hedge Bot Started (VM Running)"
    print(msg)
    send_telegram(msg)


    snapshot_1030_sent = False
    snapshot_1645_sent = False
    printed_1045_missed = False
    printed_1655_wait = False
    while True:
        try:
            kite.profile()
        except Exception:
            print("Session expired, Re login")
            kite = get_kite()

        now = dt.datetime.now().time()
        # ===== SEND POSITIONS SNAPSHOT =====
        if now.hour == 10 and now.minute == 30 and now.second < 20 and not snapshot_1030_sent:            
            send_positions_snapshot(kite)
            snapshot_1030_sent = True

        if now.hour == 16 and now.minute == 45 and now.second < 20 and not snapshot_1645_sent:            
            send_positions_snapshot(kite)
            snapshot_1645_sent = True


        if not (
            dt.time(10, 45) <= now <= dt.time(11, 30)
            or dt.time(16, 55) <= now <= dt.time(17, 15)):
            time.sleep(10)
            continue


        #=============== 10:45=========================
        if dt.time(10, 45) <= now <= dt.time(11, 0) and not executed_1045:
            print("\n⏰ Executing 10:45 Exit\n")
            msg = "⏰ Executing 10:45 Exit"
            print(msg)
            send_telegram(msg)

            run_1045(kite)
            executed_1045 = True
        elif now > dt.time(11, 0) and not executed_1045 and not printed_1045_missed:
            print("\n Missed 10:45 window\n")
            printed_1045_missed = True

        #=============== 16:55=========================
        if now >= dt.time(16, 55) and not executed_1655:
            print("\n⏰ Executing 16:55 Hedge\n")
            msg = "⏰ Executing 16:55 Hedge"
            print(msg)
            send_telegram(msg)

            run_1655(kite)
            executed_1655 = True
        elif now < dt.time(16, 55) and not executed_1655 and not printed_1655_wait:
            print("\n Waiting for 16:55 window\n")
            printed_1655_wait = True
        elif now > dt.time(17, 5) and not executed_1655:
            print("\n Market closed \n")

        # ===== DAMAGE CONTROL =====
        if now.hour == 16 and now.minute >= 57 and not damage_done:
            damage_control(kite)
            damage_done = True

        
        # reset next day
        if now.hour == 0 and now.minute == 1:
            executed_1045 = False
            executed_1655 = False
            printed_1045_missed = False
            printed_1655_wait = False
            snapshot_1030_sent = False
            snapshot_1645_sent = False
            damage_done = False


        time.sleep(10)


# =====================================================

# ENTRY

# =====================================================

if __name__ == "__main__":

    try:
        # 🔥 START TOKEN SERVER IN BACKGROUND
        server_thread = threading.Thread(target=start_token_server)
        server_thread.daemon = True
        server_thread.start()

        print("🌐 Token server running on port 5000")

        scheduler()
    finally:
        if os.path.exists(lock_file):
            os.remove(lock_file)

# =====================================================

