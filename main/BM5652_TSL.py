# =====================================================
# EMA CALCULATION FOR OPEN POSITIONS
# =====================================================

from datetime import time
import os
import sys

import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

from main.BM5652_HG import get_kite

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config.kite_config import API_KEY, API_SECRET

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

EMA_INTERVAL = "30minute"
EMA_LOOKBACK_DAYS = 5


def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()


def run_ema_check(kite):

    kite = get_kite()   # ✅ using YOUR login exactly

    def safe_get_positions(kite, retries=3):
        for i in range(retries):
            try:
                return kite.positions()["net"]
            except Exception as e:
                print(f"Positions fetch failed (attempt {i+1}): {e}")
                time.sleep(1)

    raise Exception("Failed to fetch positions after retries")
    positions = safe_get_positions(kite)

    print("\n========== EMA CHECK (FUT + OPTIONS) ==========\n")

    found = False

    for pos in positions:

        if pos["quantity"] == 0:
            continue

        if pos["exchange"] != "NFO":
            continue

        symbol = pos["tradingsymbol"]

        # Only FUT / CE / PE
        if not (symbol.endswith("FUT") or symbol.endswith("CE") or symbol.endswith("PE")):
            continue

        found = True

        token = pos["instrument_token"]
        qty = pos["quantity"]

        try:
            to_dt = dt.datetime.now()
            from_dt = to_dt - dt.timedelta(days=EMA_LOOKBACK_DAYS)

            data = kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval=EMA_INTERVAL
            )

            if not data or len(data) < 20:
                print(f"{symbol} → Not enough data")
                continue

            df = pd.DataFrame(data)

            df["ema9"] = calculate_ema(df, 9)
            df["ema20"] = calculate_ema(df, 20)

            latest = df.iloc[-1]

            ema9 = round(latest["ema9"], 2)
            ema20 = round(latest["ema20"], 2)
            close = round(latest["close"], 2)

            print("--------------------------------------------------")
            print(f"Symbol   : {symbol}")
            print(f"Position : {'LONG' if qty > 0 else 'SHORT'}")
            print(f"LTP      : {close}")
            print(f"EMA 9    : {ema9}")
            print(f"EMA 20   : {ema20}")

            if ema9 > ema20:
                print("Trend    : BULLISH")
            else:
                print("Trend    : BEARISH")

            print("--------------------------------------------------\n")

        except Exception as e:
            print(f"{symbol} EMA error:", e)

    if not found:
        print("No open NFO FUT/OPTIONS positions.")

    print("========== EMA CHECK COMPLETE ==========\n")