import sqlite3
from turtle import setup
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from support.debug_momentum import print_condition_block
from support.utils import (
    calculate_ema_tv as calculate_ema,
    calculate_rsi_tv,
    calculate_supertrend,
    resample_ohlc
)

DB_OHLC = "database/market_ohlc.db"


def load_ohlc(symbol):
    con = sqlite3.connect(DB_OHLC)
    df = pd.read_sql("""
        SELECT date, open, high, low, close, volume
        FROM market_ohlc
        WHERE symbol = ?
        ORDER BY date
    """, con, params=(symbol,))
    con.close()
    df['date'] = pd.to_datetime(df['date'])
    return df


def debug_symbol(symbol, test_date):

    df = load_ohlc(symbol)

    df = df[df["date"] <= pd.to_datetime(test_date)]
    df = df.sort_values("date")

    t = len(df) - 1

    close_t = float(df.iloc[t]["close"])
    open_t = float(df.iloc[t]["open"])
    volume_t = float(df.iloc[t]["volume"])
    close_t1 = float(df.iloc[t-1]["close"])
    high_t = float(df.iloc[t]["high"])
    low_t = float(df.iloc[t]["low"])

    # ================= RSI =================
    rsi10 = calculate_rsi_tv(df["close"], 10)

    if pd.isna(rsi10.iloc[t]):
        print("❌ RSI NaN — skipping")
        return

    rsi10_t = float(rsi10.iloc[t])
    rsi10_t1 = float(rsi10.iloc[t-1])

    # ================= SUPER TREND =================
    st = calculate_supertrend(df["high"], df["low"], df["close"], 10, 2)
    st_t = float(st.iloc[t])
    st_t1 = float(st.iloc[t-1])

    # ================= HTF =================
    df_reset = df.copy()

    weekly = resample_ohlc(df_reset, "W")
    monthly = resample_ohlc(df_reset, "M")
    # ADD CURRENT RUNNING MONTH MANUALLY (Chartink behavior)
    current_month_df = df[df["date"].dt.to_period("M") == pd.to_datetime(test_date).to_period("M")]

    if len(current_month_df) > 0:
        current_month_candle = {
            "date": pd.to_datetime(test_date),
            "open": current_month_df.iloc[0]["open"],
            "high": current_month_df["high"].max(),
            "low": current_month_df["low"].min(),
            "close": current_month_df.iloc[-1]["close"],
            "volume": current_month_df["volume"].sum()
        }

        monthly = pd.concat([monthly, pd.DataFrame([current_month_candle])], ignore_index=True)

    # CLEAN AGAIN
    monthly = monthly.sort_values("date").reset_index(drop=True)
    monthly = monthly[monthly["date"] <= pd.to_datetime(test_date)]
    monthly = monthly.sort_values("date")
        # CLEAN MONTHLY (NO FILTERING!)
    monthly = monthly.copy()
    monthly["close"] = pd.to_numeric(monthly["close"], errors="coerce")
    monthly = monthly.dropna(subset=["close"])
    monthly = monthly.sort_values("date")

    # ================= WEEK LOGIC =================
    test_dt = pd.to_datetime(test_date)

    last_week_date = pd.to_datetime(weekly.iloc[-1]["date"])
    w_idx = -1

    weekly_close = float(weekly.iloc[-1]["close"])
    weekly_high_t1 = float(weekly.iloc[-2]["high"])
    weekly_low_t1 = float(weekly.iloc[-2]["low"])
    print("\n--- WEEK DEBUG ---")
    print("Current week close:", weekly_close)
    print("Previous week low:", weekly_low_t1)
    print("Condition (weekly_close > weekly_low_t1):", weekly_close > weekly_low_t1)
    print("\nWeekly DF tail:")
    print(weekly.tail(3)[["date", "open", "high", "low", "close"]])

    weekly_rsi = calculate_rsi_tv(weekly["close"], 10)
    weekly_rsi10_t1 = float(weekly_rsi.iloc[w_idx])

    weekly_ema = calculate_ema(weekly["close"], 9)
    weekly_ema9 = float(weekly_ema.iloc[w_idx])

    # ================= MONTH LOGIC =================
    if len(monthly) < 2:
        print("❌ Not enough monthly data")
        return

    idx = -1
    prev_idx = -2

    monthly_close = float(monthly.iloc[idx]["close"])
    monthly_low_t1 = float(monthly.iloc[prev_idx]["low"])

    monthly_ema = calculate_ema(monthly["close"], 9)
    monthly_ema9 = float(monthly_ema.iloc[idx])

    rsi_daily = calculate_rsi_tv(df["close"], 10)
    # get last RSI value of current month
    current_month = pd.to_datetime(test_date).to_period("M")
    monthly_rsi_series = rsi_daily[df["date"].dt.to_period("M") == current_month]
  
    if len(monthly_rsi_series) == 0:
        print("❌ Monthly RSI empty")
        return
    monthly_rsi10_t1 = float(monthly_rsi_series.iloc[-1])

    print("RSI:", rsi10_t)
    print("Monthly RSI:", monthly_rsi10_t1)
    print("Weekly RSI:", weekly_rsi10_t1)

    if pd.isna(monthly_rsi10_t1):
        print("❌ Monthly RSI NaN — skipping")
        return

    # ================= EMA =================
    ema9 = calculate_ema(df["close"], 9)
    ema20 = calculate_ema(df["close"], 20)

    ema9_t = float(ema9.iloc[t])
    ema20_t = float(ema20.iloc[t])

    daily_high_t1 = float(df.iloc[t-1]["high"])
    high_3_prev = df.iloc[t-3:t]["high"].max()

    # ================= CANDLE CONDITION =================
    range_val = high_t - low_t

    if range_val <= 0:
        cond_candle = False
    else:
        lower_ratio = (open_t - low_t) / range_val
        upper_ratio = (high_t - close_t) / range_val

        cond_candle = (lower_ratio <= 0.1 or upper_ratio <= 0.1)

        print("Lower ratio:", round(lower_ratio, 4))
        print("Upper ratio:", round(upper_ratio, 4))

    # ================= CONDITIONS =================
    cond_price_cap = close_t <= 10000
    cond_volume = volume_t >= 500000 if not pd.isna(volume_t) else False
    cond_green = close_t > open_t
    

    cond1 = (
        close_t >= high_3_prev and
        open_t >= close_t1 and
        monthly_close > monthly_ema9 and
        weekly_close > weekly_ema9 and
        close_t >= weekly_high_t1 and
        weekly_rsi10_t1 >= 45 and
        monthly_rsi10_t1 >= 40 and
        (rsi10_t >= 60 or (rsi10_t > 60 and rsi10_t1 <= 60)) and
        ((close_t >= st_t) or (close_t > st_t and close_t1 <= st_t1))
    )

    cond2 = (
        monthly_close > monthly_low_t1 and
        weekly_close > weekly_low_t1 and
        close_t >= max(df.iloc[t-1]["close"], df.iloc[t-2]["close"], df.iloc[t-3]["close"]) and
        close_t <= ema20_t and
        monthly_rsi10_t1 >= 40 and
        close_t >= daily_high_t1
    )

    cond3 = (
        monthly_close > monthly_low_t1 and
        weekly_close > weekly_low_t1 and
        monthly_rsi10_t1 >= 40 and
        close_t > open_t and
        close_t > close_t1 and
        open_t <= ema9_t and
        cond_candle
    )

    final_condition = cond_price_cap and cond_volume and cond_green and (cond1 or cond2 or cond3)
    
    # ================= CONDITION BREAKDOWN =================

    cond1_checks = {
        "Breakout (close >= prev 3 high)": close_t >= high_3_prev,
        "Open >= prev close": open_t >= close_t1,
        "Monthly > EMA9": monthly_close > monthly_ema9,
        "Weekly > EMA9": weekly_close > weekly_ema9,
        "Close >= prev week high": close_t >= weekly_high_t1,
        "Weekly RSI >= 45": weekly_rsi10_t1 >= 45,
        "Monthly RSI >= 40": monthly_rsi10_t1 >= 40,
        "RSI strength": (rsi10_t >= 60 or (rsi10_t > 60 and rsi10_t1 <= 60)),
        "Supertrend support": (close_t >= st_t or (close_t > st_t and close_t1 <= st_t1))
    }

    cond2_checks = {
        "Monthly > prev low": monthly_close > monthly_low_t1,
        "Weekly > prev low": weekly_close > weekly_low_t1,
        "Close >= last 3 close": close_t >= max(
            df.iloc[t-1]["close"],
            df.iloc[t-2]["close"],
            df.iloc[t-3]["close"]
        ),
        "Below EMA20": close_t <= ema20_t,
        "Monthly RSI >= 40": monthly_rsi10_t1 >= 40,
        "Close >= prev high": close_t >= daily_high_t1
    }

    cond3_checks = {
        "Monthly > prev low": monthly_close > monthly_low_t1,
        "Weekly > prev low": weekly_close > weekly_low_t1,
        "Monthly RSI >= 40": monthly_rsi10_t1 >= 40,
        "Bullish candle": close_t > open_t,
        "Momentum close > prev": close_t > close_t1,
        "Open <= EMA9": open_t <= ema9_t,
        "Strong candle body": cond_candle
    }

    # ================= OUTPUT =================
    print(f"\n==== DEBUG {symbol} on {test_date} ====")
    print("Close:", close_t)
    print("Weekly Close:", weekly_close)
    print("Monthly Close:", monthly_close)
    print("RSI:", rsi10_t)
    print("Monthly RSI:", monthly_rsi10_t1)

    print("\n=== CONDITION BREAKDOWN ===")
    print_condition_block("cond1", cond1, cond1_checks)
    print_condition_block("cond2", cond2, cond2_checks)
    print_condition_block("cond3", cond3, cond3_checks)
         

    

    # ================= FAILURE LOGIC =================

    failure_reasons = []
    if not cond_price_cap:
        failure_reasons.append("price > 10000")

    if not cond_volume:
        failure_reasons.append("volume < 500000")

    if not cond_green:
        failure_reasons.append("not bullish candle")
    

    if not cond1:
        if close_t < high_3_prev:
            failure_reasons.append("cond1: no breakout")
        if open_t < close_t1:
            failure_reasons.append("cond1: open < prev close")
        if monthly_close <= monthly_ema9:
            failure_reasons.append("cond1: monthly below EMA9")

    if not cond2:
        if monthly_close <= monthly_low_t1:
            failure_reasons.append("cond2: monthly weak")
        if weekly_close <= weekly_low_t1:
            failure_reasons.append("cond2: weekly weak")

    if not cond3:
        if close_t <= open_t:
            failure_reasons.append("cond3: not bullish")

        if close_t <= close_t1:
            failure_reasons.append("cond3: no momentum")

        if open_t > ema9_t:
            failure_reasons.append("cond3: open above EMA9")

        if not cond_candle:
            failure_reasons.append("cond3: candle weak")

        if monthly_rsi10_t1 < 40:
            failure_reasons.append("cond3: monthly RSI < 40")

        if weekly_close <= weekly_low_t1:
            failure_reasons.append("cond3: weekly weak")

        if monthly_close <= monthly_low_t1:
            failure_reasons.append("cond3: monthly weak")

    # Setup label
    

    if cond1:
        setup = "BREAKOUT"
    elif cond2:
        setup = "PULLBACK"
    elif cond3:
        setup = "CANDLE"
    else:
        setup = "NONE"

    if final_condition:
        failure_reason = f"PASSED: {setup}"
    else:
        failure_reason = "FAILED: " + ", ".join(failure_reasons[:3])
    
    print("\nFINAL:", final_condition)

    if final_condition:
        print("REASON: PASSED:", setup)
    else:
        print("REASON:", failure_reason)

        print("\nFailure Breakdown:")
        for r in failure_reasons[:5]:
            print(" -", r)

    print("=====================================")


# ================= RUN =================
if __name__ == "__main__":

    print("\n=== DEBUG MOMENTUM TOOL ===")

    while True:
        symbol = input("Enter symbol: ").strip().upper()
        if symbol == "Y":
            break

        test_date = input("Enter date (YYYY-MM-DD): ").strip()
        if test_date.lower() == "y":
            break

        debug_symbol(symbol, test_date)

