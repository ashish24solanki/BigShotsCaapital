# ==========================================================
# OPTIONS AUTO BUY — MONTHLY EXPIRY + DELTA/GAMMA/IV FILTER
# ==========================================================

import os
import sys
import time
import pandas as pd
import numpy as np
import math
import datetime as dt
import webbrowser
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException
from scipy.stats import norm
from scipy.optimize import brentq
from kiteconnect import KiteTicker





# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

# ================= CONFIG =================

UNDERLYINGS = ["NIFTY", "BANKNIFTY"]

DELTA_MIN = 0.25
DELTA_MAX = 0.40

GAMMA_MIN = 0.001
GAMMA_MAX = 0.002

IV_MIN = 12
IV_MAX = 18

TIMEFRAME = "30minute"
QTY = 50


live_prices = {}

def on_ticks(ws, ticks):
    for tick in ticks:
        live_prices[tick['instrument_token']] = tick['last_price']

def on_connect(ws, response):
    print("WebSocket connected")
    ws.subscribe(subscribe_tokens)
    ws.set_mode(ws.MODE_LTP, subscribe_tokens)

def start_websocket():
    global kws

    kws = KiteTicker(API_KEY, kite.access_token)
    kws.on_ticks = on_ticks
    kws.on_connect = on_connect

    kws.connect(threaded=True)

kite = None


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

# ================= BLACK-SCHOLES =================
def bs_price(S, K, T, r, sigma, option_type="CE"):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)

    if option_type == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2)
    else:
        return K * math.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def bs_greeks(S, K, T, r, sigma, option_type="CE"):
    d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma*math.sqrt(T))

    if option_type == "CE":
        delta = norm.cdf(d1)
    else:
        delta = -norm.cdf(-d1)

    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    return delta, gamma

# ================= IMPLIED VOL =================
def implied_vol(price, S, K, T, r, option_type):
    try:
        func = lambda sigma: bs_price(S, K, T, r, sigma, option_type) - price
        return brentq(func, 0.01, 3)
    except:
        return None

# ================= GET SPOT =================
def get_spot(symbol):
    token = "NSE:NIFTY 50" if symbol == "NIFTY" else "NSE:NIFTY BANK"
    return kite.ltp(token)[token]["last_price"]

# ================= GET MONTHLY EXPIRY =================
def get_monthly_expiry(df):
    today = dt.date.today()

    expiries = sorted(df["expiry"].unique())

    monthly = []
    for exp in expiries:
        # monthly expiry = last Thursday of month
        if exp.month == today.month:
            monthly.append(exp)

    return max(monthly) if monthly else expiries[0]

# ================= OPTION CHAIN =================
def get_option_chain(symbol):
    instruments = kite.instruments("NFO")
    df = pd.DataFrame(instruments)

    df = df[
        (df["name"] == symbol) &
        (df["instrument_type"].isin(["CE", "PE"]))
    ]

    return df

# ================= CANDLES =================
def get_candles(token):
    to_date = dt.datetime.now()
    from_date = to_date - dt.timedelta(days=2)

    data = kite.historical_data(
        token, from_date, to_date, interval=TIMEFRAME
    )

    return pd.DataFrame(data)

# ================= MAIN LOGIC =================
def find_trade(symbol):

    if len(live_prices) == 0:
        print("No live prices yet, skipping cycle")
        return

    print(f"\nChecking {symbol}")

    spot = get_spot(symbol)
    df = get_option_chain(symbol)

    expiry = get_monthly_expiry(df)
    df = df[df["expiry"] == expiry]

    # 🎯 SMART STRIKE RANGE (ONLY NEAR ATM)
    step = 50 if symbol == "NIFTY" else 100
    atm = round(spot / step) * step

    strikes = [atm + i * step for i in range(-5, 6)]
    df = df[df["strike"].isin(strikes)]

    selected = []

    days = (expiry - dt.date.today()).days
    T = max(days / 365, 1/365)
    r = 0.06

    for _, row in df.iterrows():
        try:
            token = row["instrument_token"]

            if token not in live_prices:
                continue

            ltp = live_prices[token]

            if ltp < 5:
                continue

            K = row["strike"]
            opt_type = row["instrument_type"]

            iv = implied_vol(ltp, spot, K, T, r, opt_type)
            if iv is None:
                continue

            iv_pct = iv * 100
            

            delta, gamma = bs_greeks(spot, K, T, r, iv, opt_type)

            # Convert delta to absolute for comparison
            abs_delta = abs(delta)

            if (
                DELTA_MIN <= abs_delta <= DELTA_MAX and
                GAMMA_MIN <= gamma <= GAMMA_MAX and
                IV_MIN <= iv_pct <= IV_MAX
            ):
                selected.append((row, delta, gamma, iv_pct))

        except:
            continue

    if not selected:
        print("No match found")
        return

    # 🎯 TRUE DELTA TARGET PICKING
    # Prefer highest gamma (better movement)
    selected = sorted(selected, key=lambda x: x[2], reverse=True)

    row, delta, gamma, iv = selected[0]

    print(f"Selected: {row['tradingsymbol']} | Δ={delta:.2f} Γ={gamma:.4f} IV={iv:.2f}")

    # ================= BREAKOUT =================
    token = row["instrument_token"]
    candles = get_candles(token)

    if len(candles) < 2:
        return

    prev_high = candles.iloc[-2]["high"]

    if token not in live_prices:
        return

    ltp = live_prices[token]

    print(f"LTP={ltp}, PrevHigh={prev_high}")

    if ltp > prev_high:
        print("BUY SIGNAL")

        try:
            kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange="NFO",
                tradingsymbol=row["tradingsymbol"],
                transaction_type="BUY",
                quantity=QTY,
                product="NRML",
                order_type="MARKET"
            )
            print("Order placed")

        except Exception as e:
            print("Order failed:", e)


def prepare_subscription():
    global subscribe_tokens

    df = get_option_chain("NIFTY")
    df2 = get_option_chain("BANKNIFTY")

    df = pd.concat([df, df2])

    expiry = get_monthly_expiry(df)
    df = df[df["expiry"] == expiry]

    # Only near ATM options
    spot_nifty = get_spot("NIFTY")
    spot_bank = get_spot("BANKNIFTY")

    def get_near_tokens(df, spot, step):
        atm = round(spot / step) * step
        strikes = [atm + i * step for i in range(-5, 6)]
        return df[df["strike"].isin(strikes)]["instrument_token"].tolist()

    tokens_nifty = get_near_tokens(df[df["name"]=="NIFTY"], spot_nifty, 50)
    tokens_bank = get_near_tokens(df[df["name"]=="BANKNIFTY"], spot_bank, 100)

    subscribe_tokens = tokens_nifty + tokens_bank

def wait_for_data():
    print("Waiting for WebSocket data...")
    for _ in range(10):
        if len(live_prices) > 20:
            print("WebSocket ready")
            return
        time.sleep(1)
    print("Warning: WebSocket data may be incomplete")

# ================= SCHEDULER =================
def run():
    while True:
        now = dt.datetime.now()

        if now.minute % 30 == 0 and now.second < 5:
            for sym in UNDERLYINGS:
                find_trade(sym)

            time.sleep(60)

        time.sleep(1)

# ================= START =================
if __name__ == "__main__":

    kite = get_kite()

    prepare_subscription()
    start_websocket()

    wait_for_data() # allow WS to warm up

    run()