import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


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

def save_debug_to_csv(data: dict, file_path="debug_results.csv"):
    df = pd.DataFrame([data])

    if os.path.exists(file_path):
        df.to_csv(file_path, mode='a', header=False, index=False, sep=",", float_format="%.2f")
    else:
        df.to_csv(file_path, mode='w', header=True, index=False, sep=",", float_format="%.2f")

def print_condition_block(name, status, checks):
    icon = "✅" if status else "❌"
    print(f"\n{name} {icon}")

    for k, v in checks.items():
        sub_icon = "✅" if v else "❌"
        print(f"  ├─ {k}: {sub_icon}")

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

    # RSI
    rsi10 = calculate_rsi_tv(df["close"], 10)
    rsi10_t = float(rsi10.iloc[t])
    rsi10_t1 = float(rsi10.iloc[t-1])

    # Supertrend
    st = calculate_supertrend(df["high"], df["low"], df["close"], 10, 2)
    st_t = float(st.iloc[t])
    st_t1 = float(st.iloc[t-1])

    # HTF
    df_reset = df.copy()
    weekly = resample_ohlc(df_reset, "W")
    monthly = resample_ohlc(df_reset, "M")
    test_dt = pd.to_datetime(test_date)
    
    monthly = monthly.copy()
    monthly["close"] = pd.to_numeric(monthly["close"], errors="coerce")
    monthly = monthly.dropna(subset=["close"])
    monthly = monthly.sort_index()
    monthly = monthly[monthly["date"] <= pd.to_datetime(test_date)]
    
    # 🔍 DEBUG LINE (ADD HERE)
    print("Weekly index check:", weekly.index[-2], weekly.index[-1])
    print("\n--- WEEK DEBUG ---")
    print("weekly[-2] close:", weekly.iloc[-2]['close'])
    print("weekly[-1] close:", weekly.iloc[-1]['close'])     
       
    
    if 'date' in weekly.columns:
        last_week_date = pd.to_datetime(weekly.iloc[-1]['date'])
    else:
        last_week_date = pd.to_datetime(weekly.index[-1])

    # If test date is same as last weekly candle → use current week
    if last_week_date.date() == test_dt.date():
        w_idx = -1
    else:
        w_idx = -2

    weekly_close = float(weekly.iloc[w_idx]['close'])
    weekly_rsi10_t1 = float(calculate_rsi_tv(weekly['close'], 10).iloc[w_idx])
    weekly_high_t1 = float(weekly.iloc[w_idx-1]['high'])
    weekly_ema_series = calculate_ema(weekly['close'], 9)
    weekly_ema9 = float(weekly_ema_series.iloc[w_idx])
    weekly_low_t1 = float(weekly.iloc[w_idx-1]['low'])

    # Detect if current month is usable
    
    test_dt = pd.to_datetime(test_date)
    ####################################################################
    last_month_date = last_month_date = monthly.iloc[-1]['date']    
    if len(monthly) < 2:
        print("❌ Not enough monthly data")
        return
    idx = -1
    prev_idx = -2
    
    # Matching previous candle index for comparison
    prev_idx = idx - 1
    monthly_low_t1 = float(monthly.iloc[prev_idx]['low'])

    monthly_close = float(monthly.iloc[idx]['close'])
    monthly_ema9 = float(calculate_ema(monthly['close'], 9).iloc[idx])
    monthly_rsi_series = calculate_rsi_tv(monthly['close'], 10)
    monthly_rsi10_t1 = float(monthly_rsi_series.iloc[idx])

    # EMA
    ema9 = calculate_ema(df["close"], 9)
    ema20 = calculate_ema(df["close"], 20)

    ema9_t = float(ema9.iloc[t])
    ema20_t = float(ema20.iloc[t])

    daily_high_t1 = float(df.iloc[t-1]["high"])
    low_t = float(df.iloc[t]["low"])

    high_3_prev = df.iloc[t-3:t]["high"].max()

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
        ((close_t >= st_t ) or 
        (close_t > st_t and close_t1 <= st_t1))
    )

    cond2 = (
        monthly_close > monthly_low_t1 and
        weekly_close > weekly_low_t1 and
        close_t >= max(
            float(df.iloc[t-1]["close"]),
            float(df.iloc[t-2]["close"]),
            float(df.iloc[t-3]["close"])
        ) and
        close_t <= ema20_t and
        monthly_rsi10_t1 >= 40 and
        close_t >= daily_high_t1
    )

    range_val = round(high_t - low_t, 2)

    if range_val == 0:
        cond_candle = False
    else:
        lower_ratio = round((open_t - low_t) / range_val, 4)
        upper_ratio = round((high_t - close_t) / range_val, 4)
        cond_candle = (
            lower_ratio <= 0.1 or
            upper_ratio <= 0.1
        )
        print("Lower ratio:", lower_ratio)
        print("Upper ratio:", upper_ratio)

    cond3 = (
        monthly_close > monthly_low_t1 and
        weekly_close > weekly_low_t1 and
        monthly_rsi10_t1 >= 40 and
        close_t > open_t and
        close_t > close_t1 and
        open_t <= ema9_t and
        cond_candle
    )

    final_condition = (
        cond_price_cap and cond_volume and cond_green and (cond1 or cond2 or cond3)
    )

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
            float(df.iloc[t-1]["close"]),
            float(df.iloc[t-2]["close"]),
            float(df.iloc[t-3]["close"])
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
    print("Monthly RSI used:", monthly_rsi10_t1)
    print("Month index used:", idx)
    print("Month date:", monthly.iloc[idx]['date'])

    if cond1:
        setup = "BREAKOUT"
    elif cond2:
        setup = "PULLBACK"
    elif cond3:
        setup = "CANDLE"
    else:
        setup = "NONE"
    

    #=======================================================
    failure_reasons = []

    # Common conditions
    if not cond_price_cap:
        failure_reasons.append("price > 10000")

    if not cond_volume:
        failure_reasons.append("volume < 500000")

    if not cond_green:
        failure_reasons.append("not bullish candle")
    #=======================================================
    if not cond1:
        if close_t < high_3_prev:
            failure_reasons.append("cond1: no breakout")

        if open_t < close_t1:
            failure_reasons.append("cond1: open < prev close")

        if monthly_close <= monthly_ema9:
            failure_reasons.append("cond1: monthly below EMA9")

        if weekly_close <= weekly_ema9:
            failure_reasons.append("cond1: weekly below EMA9")

        if weekly_rsi10_t1 < 45:
            failure_reasons.append("cond1: weekly RSI < 45")

        if monthly_rsi10_t1 < 40:
            failure_reasons.append("cond1: monthly RSI < 40")

    if not cond2:
        if monthly_close <= monthly_low_t1:
            failure_reasons.append("cond2: monthly weak")

        if weekly_close <= weekly_low_t1:
            failure_reasons.append("cond2: weekly weak")

        if close_t > ema20_t:
            failure_reasons.append("cond2: above EMA20")

        if monthly_rsi10_t1 < 40:
            failure_reasons.append("cond2: monthly RSI < 40")

    if not cond3:
        if close_t <= open_t:
            failure_reasons.append("cond3: not bullish")

        if close_t <= close_t1:
            failure_reasons.append("cond3: no momentum")

        if open_t > ema9_t:
            failure_reasons.append("cond3: open above EMA9")

        if not cond_candle:
            failure_reasons.append("cond3: candle structure weak")
    
    if final_condition:
        failure_reason = f"PASSED: {setup}"
    else:
        failure_reason = "FAILED: " + ", ".join(failure_reasons[:3])  # limit to top 3 reasons

    print("\n=== CONDITION BREAKDOWN ===")
    print_condition_block("cond1", cond1, cond1_checks)
    print_condition_block("cond2", cond2, cond2_checks)
    print_condition_block("cond3", cond3, cond3_checks)
    
    print("\nFINAL:", final_condition)
    print("REASON:", failure_reason)

    if not final_condition:
        print("\nFailure Breakdown:")
        for r in failure_reasons[:5]:
            print(" -", r)
    print("=====================================\n")
    
   
    close_t = round(close_t, 2)
    weekly_close = round(weekly_close, 2)
    monthly_close = round(monthly_close, 2)
    ema9_t = round(ema9_t, 2)
    ema20_t = round(ema20_t, 2)
    rsi10_t = round(rsi10_t, 2)
    weekly_rsi10_t1 = round(weekly_rsi10_t1, 2)
    monthly_rsi10_t1 = round(monthly_rsi10_t1, 2)


    # ================= SAVE TO CSV =================
    debug_data = {
        "symbol": symbol,
        "date": test_date,
        "close": close_t,
        "weekly_close": weekly_close,
        "monthly_close": monthly_close,
        "monthly_rsi": monthly_rsi10_t1,
        "weekly_rsi": weekly_rsi10_t1,
        "ema9": ema9_t,
        "ema20": ema20_t,
        "rsi": rsi10_t,
        "cond1": cond1,
        "cond2": cond2,
        "cond3": cond3,
        "setup": setup,
        "final_condition": final_condition,
        "failure_reason": failure_reason,

        
    }

    save_debug_to_csv(debug_data)


# ================= RUN =================
if __name__ == "__main__":

    print("\n=== DEBUG MOMENTUM TOOL ===")
    print("Type 'Y' anytime to stop.\n")

    while True:
        symbol = input("Enter symbol: ").strip().upper()

        if symbol == "Y":
            print("Exiting debug tool...")
            break

        test_date = input("Enter date (YYYY-MM-DD): ").strip()

        if test_date.lower() == "y":
            print("Exiting debug tool...")
            break

        # ✅ Basic validation
        if not symbol or not test_date:
            print("❌ Invalid input. Try again.\n")
            continue

        try:
            pd.to_datetime(test_date)
        except:
            print("❌ Invalid date format. Use YYYY-MM-DD\n")
            continue

        # ✅ Run debug
        debug_symbol(symbol, test_date)