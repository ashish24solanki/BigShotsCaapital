import sqlite3
import pandas as pd
import numpy as np
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

    if len(df) < 15:
        print(f"❌ Not enough data for {symbol}")
        return

    t = len(df) - 1

    close_t = float(df.iloc[t]["close"])
    open_t = float(df.iloc[t]["open"])
    volume_t = float(df.iloc[t]["volume"])
    close_t1 = float(df.iloc[t-1]["close"])
    high_t = float(df.iloc[t]["high"])
    low_t = float(df.iloc[t]["low"])

    # Daily indicators
    rsi10 = calculate_rsi_tv(df["close"], 10)
    rsi10_t = float(rsi10.iloc[t])
    rsi10_t1 = float(rsi10.iloc[t-1])

    st = calculate_supertrend(df["high"], df["low"], df["close"], 10, 2)
    st_t = float(st.iloc[t])
    st_t1 = float(st.iloc[t-1])

    # HTF
    df_reset = df.copy()
    weekly = resample_ohlc(df_reset, "W")
    monthly = resample_ohlc(df_reset, "M")

    test_dt = pd.to_datetime(test_date).date()

    # ====================== WEEKLY ======================
    print("\n--- WEEK DEBUG ---")
    print("Weekly last 3 dates:", weekly['date'].tail(3).tolist())

    last_week_date = pd.to_datetime(weekly.iloc[-1]['date']).date()
    w_idx = -1 if last_week_date == test_dt else -2

    weekly_close = float(weekly.iloc[w_idx]['close'])
    weekly_low_t1 = float(weekly.iloc[w_idx - 1]['low'])
    weekly_high_t1 = float(weekly.iloc[w_idx - 1]['high'])
    weekly_ema9 = float(calculate_ema(weekly['close'], 9).iloc[w_idx])
    weekly_rsi10_t1 = float(calculate_rsi_tv(weekly['close'], 10).iloc[w_idx])

    print(f"Weekly Close: {weekly_close:.2f} | Prev Weekly Low: {weekly_low_t1:.2f}")

    # ====================== MONTHLY ======================
    print("\n--- MONTH DEBUG ---")
    print("Monthly last 3 dates:", monthly['date'].tail(3).tolist())

    last_month_date = pd.to_datetime(monthly.iloc[-1]['date']).date()

    if last_month_date.month == test_dt.month and last_month_date.year == test_dt.year and test_dt.day >= 25:
        m_idx = -1
    else:
        m_idx = -2

    monthly_close = float(monthly.iloc[m_idx]['close'])
    monthly_low_t1 = float(monthly.iloc[m_idx - 1]['low'])
    monthly_ema9 = float(calculate_ema(monthly['close'], 9).iloc[m_idx])
    monthly_rsi10_t1 = float(calculate_rsi_tv(monthly['close'], 10).iloc[m_idx])

    print(f"Monthly Close: {monthly_close:.2f} | Prev Monthly Low: {monthly_low_t1:.2f}")
    print(f"Monthly RSI: {monthly_rsi10_t1:.2f}")

    # Daily EMA
    ema9_t = float(calculate_ema(df["close"], 9).iloc[t])
    ema20_t = float(calculate_ema(df["close"], 20).iloc[t])

    daily_high_t1 = float(df.iloc[t-1]["high"])
    high_3_prev = df.iloc[t-3:t]["high"].max()

    # Candle body check
    range_val = round(high_t - low_t, 2)
    cond_candle = False
    if range_val > 0:
        lower_ratio = round((open_t - low_t) / range_val, 4)
        upper_ratio = round((high_t - close_t) / range_val, 4)
        cond_candle = (lower_ratio <= 0.1 or upper_ratio <= 0.1)
        print(f"Lower ratio: {lower_ratio} | Upper ratio: {upper_ratio}")

    # ================= CONDITIONS (Strict as per Chartink) =================
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
        close_t >= max(float(df.iloc[t-1]["close"]), float(df.iloc[t-2]["close"]), float(df.iloc[t-3]["close"])) and
        close_t <= ema20_t and
        monthly_rsi10_t1 >= 40 and
        close_t >= daily_high_t1
    )

    cond3 = (
        monthly_close > monthly_low_t1 and
        weekly_close > weekly_low_t1 and
        monthly_rsi10_t1 >= 40 and        # Strict as per your original Chartink
        close_t > open_t and
        close_t > close_t1 and
        open_t <= ema9_t and
        cond_candle
    )

    final_condition = cond_price_cap and cond_volume and cond_green and (cond1 or cond2 or cond3)

    if cond1:
        setup = "BREAKOUT"
    elif cond2:
        setup = "PULLBACK"
    elif cond3:
        setup = "CANDLE"
    else:
        setup = "NONE"

    # ================= CONDITION DICTIONARIES =================
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
        "Close >= last 3 close": close_t >= max(float(df.iloc[t-1]["close"]), float(df.iloc[t-2]["close"]), float(df.iloc[t-3]["close"])),
        "Below EMA20": close_t <= ema20_t,
        "Monthly RSI >= 40": monthly_rsi10_t1 >= 40,
        "Close >= prev high": close_t >= daily_high_t1
    }

    cond3_checks = {
        "Monthly > 1M ago low": monthly_close > monthly_low_t1,
        "Weekly > 1W ago low": weekly_close > weekly_low_t1,
        "Monthly RSI >= 40": monthly_rsi10_t1 >= 40,
        "Bullish candle": close_t > open_t,
        "Close > prev close": close_t > close_t1,
        "Open <= EMA9": open_t <= ema9_t,
        "Strong candle body (<=10% shadow)": cond_candle
    }

    # ================= OUTPUT =================
    print(f"\n==== DEBUG {symbol} on {test_date} ====")
    print("Close:", round(close_t, 2))
    print("Weekly Close:", round(weekly_close, 2))
    print("Monthly Close:", round(monthly_close, 2))
    print("Monthly RSI used:", round(monthly_rsi10_t1, 2))

    print("\n=== CONDITION BREAKDOWN ===")
    print_condition_block("cond1", cond1, cond1_checks)
    print_condition_block("cond2", cond2, cond2_checks)
    print_condition_block("cond3", cond3, cond3_checks)

    print("\nFINAL:", final_condition)
    print("SETUP:", setup)

    if not final_condition:
        print("\nFailure Breakdown:")
        if monthly_close <= monthly_low_t1:
            print(f" - cond3: monthly close <= prev month low ({monthly_close:.2f} <= {monthly_low_t1:.2f})")
        if weekly_close <= weekly_low_t1:
            print(f" - cond3: weekly close <= prev week low ({weekly_close:.2f} <= {weekly_low_t1:.2f})")
        if monthly_rsi10_t1 < 40:
            print(f" - cond3: monthly RSI < 40 ({monthly_rsi10_t1:.2f})")
        if not cond_candle:
            print(" - cond3: weak candle body")

    print("=====================================\n")


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

        if not symbol or not test_date:
            print("❌ Invalid input. Try again.\n")
            continue

        try:
            pd.to_datetime(test_date)
        except:
            print("❌ Invalid date format. Use YYYY-MM-DD\n")
            continue

        debug_symbol(symbol, test_date)