# ==========================================================
# AUTO HEDGE OPTIONS AT 16:55 (BANGKOK TIME)
# ==========================================================

import os
import sys
import time
import datetime as dt
import webbrowser
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

EXECUTION_TIME = dt.time(16, 55, 0)
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
# EXPIRY LOGIC
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
# SPOT PRICE
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
# MAIN
# =====================================================

def main():

    kite = get_kite()
    print("Login done. Waiting for 16:55 Bangkok time...")

    while True:
        if dt.datetime.now().time() >= EXECUTION_TIME:
            print("Execution time reached")
            break
        time.sleep(1)

    try:
        kite.profile()
    except:
        print("Session expired - Relogin")
        kite = get_kite()

    positions = kite.positions()["net"]
    instruments = kite.instruments("NFO")

    # =====================================================
    # NEGATIVE OPTIONS
    # =====================================================

    negative_options = [
        p for p in positions
        if p["exchange"] == "NFO"
        and p["quantity"] < 0
        and p["tradingsymbol"].endswith(("CE", "PE"))
    ]

    for pos in positions:

        if pos["quantity"] == 0:
            continue

        if pos["exchange"] != "NFO":
            continue

        if "FUT" not in pos["tradingsymbol"]:
            continue

        fut_symbol = pos["tradingsymbol"]
        print(f"\nProcessing {fut_symbol}")

        underlying = None
        for ins in instruments:
            if ins["tradingsymbol"] == fut_symbol:
                underlying = ins["name"]
                break
        
        if not underlying:
            print(f"{fut_symbol} → underlying not found")
            continue
        
        expiry = get_correct_expiry(instruments, underlying)

        if not expiry or not underlying:
            print("Expiry or underlying not found")
            continue

        option_type = "PE" if pos["quantity"] > 0 else "CE"

        matching_options = [
            ins for ins in instruments
            if ins["name"] == underlying
            and ins["expiry"] == expiry
            and ins["instrument_type"] == option_type
        ]

        if not matching_options:
            continue

        strikes = sorted(set(i["strike"] for i in matching_options))
        if len(strikes) < 2:
            print("Not enough strikes found")
            continue
        step = min([strikes[i+1] - strikes[i] for i in range(len(strikes)-1)])

        print("Detected Strike Step:", step)

        spot_price = get_spot_price(kite, underlying)
        if not spot_price:
            continue

        atm = round(spot_price / step) * step
        target = atm - step if pos["quantity"] > 0 else atm + step

        closest = min(matching_options, key=lambda x: abs(x["strike"] - target))
        option_symbol = closest["tradingsymbol"]

        print("Selected Option:", option_symbol)

        # ================= QTY =================
        lot_size = closest.get("lot_size")
        
        if not lot_size:
            print(f"{option_symbol} invalid lot size")
            continue

        qty = (abs(pos["quantity"])//lot_size) * lot_size
        if qty == 0:
            print(f"{option_symbol} -> qty mismatch (lot size) ")
            continue

        existing_short = next(
            (p for p in negative_options if p["tradingsymbol"] == option_symbol),
            None
        )

        if existing_short:
            extra_qty = abs(existing_short["quantity"])
            print("Existing short:", extra_qty)
            qty += extra_qty

        if qty <= 0:
            continue

        # ================= LTP =================
        try:
            quote = kite.ltp([f"NFO:{option_symbol}"])
            opt_ltp = quote[f"NFO:{option_symbol}"]["last_price"]
        except:
            print("LTP Fetch Failed ")
            continue

        if opt_ltp is None:
            print("Invalid LTP")
            continue

        if opt_ltp <= 1:
            continue

        limit_price = round(round((opt_ltp * 1.01)/0.05)*0.05, 2)

        # ================= EXISTING LONG =================
        existing_long = next(
            (p for p in positions if p["tradingsymbol"] == option_symbol and p["quantity"] > 0),
            None
        )

        if existing_long:
            existing_qty = abs(existing_long["quantity"])
            if existing_qty >= qty:
                print("Already hedged")
                continue
            else:
                qty -= existing_qty

        if existing_long and not existing_short:
            print(f"{option_symbol} already hedged → skipping")
            continue
        if qty <= 0:
            print(f"{option_symbol} → no additional hedge needed")
            continue

        # ================= ORDER =================
        print(f"BUY {option_symbol} QTY {qty} @ {limit_price}")

        kite.place_order(
            tradingsymbol=option_symbol,
            exchange="NFO",
            transaction_type="BUY",
            quantity=qty,
            order_type="LIMIT",
            product="NRML",
            variety="regular",
            price=limit_price
        )

        print("Order placed successfully")

    # =====================================================
    # SQUARE OFF SHORT OPTIONS
    # =====================================================

    print("\nChecking short options...\n")

    for opt in negative_options:

        symbol = opt["tradingsymbol"]
        qty = abs(opt["quantity"])

        try:
            try:
                quote = kite.ltp([f"NFO:{symbol}"])
                ltp = quote[f"NFO:{symbol}"]["last_price"]
            except:
                print(f"{symbol} LTP Fetch Failed ")
                continue

            limit_price = round(round(ltp*1.01/0.05)*0.05, 2)

            print(f"{symbol} BUYBACK {qty} @ {limit_price}")

            kite.place_order(
                tradingsymbol=symbol,
                exchange="NFO",
                transaction_type="BUY",
                quantity=qty,
                order_type="LIMIT",
                product="NRML",
                variety="regular",
                price=limit_price
            )

        except Exception as e:
            print("Error:", e)


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
# ENTRY
# =====================================================

if __name__ == "__main__":

    print("\nEnable TEST MODE? (Y/N)")
    mode = input().strip().upper()

    if mode == "Y":
        run_test_mode()
    else:
        main()