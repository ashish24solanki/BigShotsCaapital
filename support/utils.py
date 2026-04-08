import pandas as pd
import numpy as np
import logging

log = logging.getLogger("PORTFOLIO")


# =====================================================
# EMA
# =====================================================
def calculate_ema_tv(series, period):
    alpha = 2 / (period + 1)
    ema = [series.iloc[0]]

    for price in series.iloc[1:]:
        ema.append((price - ema[-1]) * alpha + ema[-1])

    return pd.Series(ema, index=series.index)

calculate_ema = calculate_ema_tv
# =====================================================
# RSI (TradingView-style)
# =====================================================
def calculate_rsi_tv(series, period=10):
    if len(series) < 2:
        return pd.Series([np.nan] * len(series), index=series.index)

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Use ewm for very short series (more forgiving)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=1).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=1).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Fill initial NaNs with simple method if needed
    rsi = rsi.bfill() if rsi.isna().all() else rsi
    return rsi

# =====================================================
# RESAMPLING (WEEKLY + MONTHLY FIXED)
# =====================================================
def resample_ohlc(df: pd.DataFrame, timeframe: str):

    if df is None or df.empty:
        return None

    df = df.copy()

    if "date" not in df.columns:
        log.error("[SL CALC] 'date' column missing")
        return None

    df["date"] = pd.to_datetime(df["date"], errors='coerce')
    df = df.set_index("date")
    df = df.sort_index()
    
    ohlc_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }

    # 🔥 IMPORTANT FIX
    if timeframe == "W":
        timeframe = "W-FRI"   # Week ends Friday
    elif timeframe in ["M", "ME"]:
        timeframe = "ME"      # Month ends on calendar month

    # 🔴 FIX: REMOVE FUTURE / INCOMPLETE DATA

    resampled = df.resample(timeframe).agg(ohlc_dict)
    resampled = resampled[resampled['close'].notna()]   # only drop fully empty
    #if timeframe.startswith("W") and len(resampled) > 1:
        #resampled = resampled.iloc[:-1]
    resampled = resampled.reset_index()
    resampled = resampled.sort_values("date")
    # 🔴 CRITICAL FIX: REMOVE PARTIAL LAST CANDLE
    # ✅ DROP ONLY WEEKLY LAST CANDLE (NOT MONTHLY)  
    return resampled

#==============MULTI-TIMEFRAME RSI================================
def calculate_multi_tf_rsi(df: pd.DataFrame, period: int = 14):
    """
    Returns RSI for Daily, Weekly (Mon–Fri), Monthly
    """

    result = {}
    # Daily RSI
    daily = df.copy()
    daily[f"rsi{period}"] = calculate_rsi_tv(daily["close"], period)
    result["daily"] = daily

    # Weekly RSI (Mon–Fri)
    weekly = resample_ohlc(df, "W")
    if weekly is not None and not weekly.empty:
        weekly[f"rsi{period}"] = calculate_rsi_tv(weekly["close"], period)
    result["weekly"] = weekly

    # Monthly RSI
    monthly = resample_ohlc(df, "ME")
    if monthly is not None and not monthly.empty:
        ##########################################################################
        # 🔴 FIX: Monthly RSI using DAILY RSI (Chartink style)

        # 🔴 FIX: Monthly RSI using DAILY RSI (Chartink style)

        # Ensure date column exists
        df_local = df.copy()
        if "date" not in df_local.columns:
            df_local = df_local.reset_index()

        df_local = df.copy()
        df_local["date"] = pd.to_datetime(df_local["date"])
        monthly["date"] = pd.to_datetime(monthly["date"])

        # Daily RSI
        daily_rsi = calculate_rsi_tv(df_local["close"], period)

        monthly_rsi = []

        for m_date in monthly["date"]:
            subset = df_local[df_local["date"] <= m_date]

            if len(subset) >= period:
                val = daily_rsi.iloc[subset.index[-1]]
            else:
                val = np.nan

            monthly_rsi.append(val)

        monthly[f"rsi{period}"] = monthly_rsi
    ##################################################################################
    result["monthly"] = monthly

    return result

##============================================================

# =====================================================
# DAILY EMA
# =====================================================
def calculate_daily_ema(df: pd.DataFrame, period: int = 20):
    if df is None or df.empty:
        return None

    df = df.copy()
    df[f"ema{period}"] = calculate_ema(df["close"], period)

    return df


# =====================================================
# WEEKLY EMA (Mon–Fri)
# =====================================================
def calculate_weekly_ema(df: pd.DataFrame, period: int = 20):
    weekly_df = resample_ohlc(df, "W")

    if weekly_df is None or weekly_df.empty:
        return None

    weekly_df[f"ema{period}"] = calculate_ema(weekly_df["close"], period)

    return weekly_df


# =====================================================
# MONTHLY EMA (Calendar Month)
# =====================================================
def calculate_monthly_ema(df: pd.DataFrame, period: int = 20):
    monthly_df = resample_ohlc(df, "ME")

    if monthly_df is None or monthly_df.empty:
        return None

    monthly_df[f"ema{period}"] = calculate_ema(monthly_df["close"], period)

    return monthly_df


# =====================================================
# MULTI-TIMEFRAME EMA (BEST FUNCTION)
# =====================================================
def calculate_multi_tf_ema(df: pd.DataFrame, period: int = 20):

    result = {}

    # Daily
    daily = df.copy()
    daily[f"ema{period}"] = calculate_ema(daily["close"], period)
    result["daily"] = daily

    # Weekly
    weekly = resample_ohlc(df, "W")
    if weekly is not None and not weekly.empty:
        weekly[f"ema{period}"] = calculate_ema(weekly["close"], period)
    result["weekly"] = weekly

    # Monthly
    monthly = resample_ohlc(df, "ME")
    if monthly is not None and not monthly.empty:
        monthly[f"ema{period}"] = calculate_ema(monthly["close"], period)
    result["monthly"] = monthly

    return result
#######END HERE#######################################################




# =====================================================
# PYRAMIDING CORE
# =====================================================
def check_pyramiding_signal(
    df: pd.DataFrame,
    buffer_pct: float = 0.002,
    ema_distance_limit: float = 0.1
):
    result = {"passed": False, "buy_trigger": None, "conditions": {}}

    if df is None or len(df) < 10:
        return result

    df = df.copy().reset_index(drop=True)

    if "ema20" not in df.columns:
        df["ema20"] = calculate_ema(df["close"], 20)

    if "rsi" not in df.columns:
        df["rsi"] = calculate_rsi_tv(df["close"])

    t = len(df) - 1

    rsi_now = float(df.iloc[t]["rsi"])

    result["conditions"]["rsi_strengthening"] = (
        rsi_now > float(df.iloc[t - 1]["rsi"])
        and rsi_now > float(df.iloc[t - 3]["rsi"])
    )

    result["conditions"]["close_breaks_recent_high"] = (
        float(df.iloc[t]["close"])
        > float(df.iloc[t - 5:t - 1]["high"].max())
    )

    close_val = float(df.iloc[t]["close"])
    ema20_val = float(df.iloc[t]["ema20"])

    result["conditions"]["ema_distance_ok"] = (
        abs((close_val - ema20_val) / ema20_val) < ema_distance_limit
    )

    if all(result["conditions"].values()):
        result["passed"] = True
        result["buy_trigger"] = round(
            float(df.iloc[t]["high"]) * (1 + buffer_pct),
            1
        )

    return result


# =====================================================
# STOP LOSS CORE (200 CANDLE MINIMUM + T10 STRUCTURE)
# =====================================================
def calculate_sl_t10_ema20(
    df: pd.DataFrame,
    as_of_date,
    lookback: int = 10,
    min_candles: int = 200,
    capital_sl_pct: float = 0.07,
    structure_sl_pct: float = 0.01,
    previous_e_sl: float = 0,
    previous_low: float = None,
    previous_sl: float = None,
    today_close=None
):

    # ===============================
    # BASIC VALIDATION
    # ===============================
    if df is None or df.empty:
        log.error("[SL] Empty dataframe")
        return None

    df = df.copy()

    if "date" not in df.columns:
        log.error("[SL] 'date' column missing")
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    try:
        as_of = pd.to_datetime(as_of_date).date()
    except:
        log.error(f"[SL] Invalid as_of_date: {as_of_date}")
        return None

    # Remove today candle
    df = df[df["date"] < as_of]

    if df.empty:
        log.error("[SL] No data after removing today")
        return None

    df = df.sort_values("date")

    if len(df) < min_candles:
        log.error(f"[SL] Not enough candles: {len(df)}")
        return None

    # ===============================
    # EMA CALC
    # ===============================
    if "ema20" not in df.columns:
        df["ema20"] = calculate_ema(df["close"], 20)

    df = df.dropna(subset=["ema20"])

    if df.empty:
        log.error("[SL] EMA removed all rows")
        return None

    # ===============================
    # T10 (YESTERDAY -10 candles)
    # ===============================
    t10 = df.tail(lookback)

    if len(t10) < lookback:
        log.error("[SL] Not enough T10 candles")
        return None

    # ===============================
    # CURRENT PRICE
    # ===============================
    try:
        if today_close is not None and pd.notna(today_close):
            last_close = float(today_close)
        else:
            last_close = float(df.iloc[-1]["close"])
    except:
        log.error("[SL] Invalid price")
        return None

    last_ema20 = float(df.iloc[-1]["ema20"])

    # ===============================
    # BREAKDOWN LOGIC (YOUR NEW RULE)
    # ===============================
    condition_breakdown = (
        last_close < last_ema20 and
        last_close < float(t10["close"].min())
    )

    if condition_breakdown:

        log.info("[SL MODE] Breakdown SL")

        lowest_low = float(t10["low"].min())
        prev_close = float(df.iloc[-1]["close"])

        option1 = lowest_low * 0.98
        option2 = prev_close * (1 - capital_sl_pct)

        calculated_sl = max(option1, option2)

    else:
        # ===============================
        # NORMAL LOGIC
        # ===============================
        highest_close = float(t10["close"].max())
        sl1 = highest_close * (1 - capital_sl_pct)

        below_ema = t10[t10["low"] < t10["ema20"]]

        if not below_ema.empty:
            if previous_low is not None:
                structure_low = max(previous_low, float(below_ema["low"].min()))
            else:
                structure_low = float(below_ema["low"].min())

            sl2 = structure_low * (1 - structure_sl_pct)
            calculated_sl = max(sl1, sl2)
        else:
            calculated_sl = sl1

    # ===============================
    # NO SL DOWNGRADE
    # ===============================
    if previous_sl:
        final_sl = max(calculated_sl, previous_sl)
    else:
        final_sl = calculated_sl

    final_sl = round(float(final_sl), 1)

    latest_close = float(df.iloc[-1]["close"])
    latest_low = float(df.iloc[-1]["low"])

    # ===============================
    # PRO E-SL
    # ===============================
    e_sl = previous_e_sl if previous_e_sl else 0

    activation_zone = latest_close <= final_sl * 1.02

    if activation_zone or previous_e_sl > 0:

        recent = df.tail(3)

        if len(recent) < 3:
            return {
                "final_sl": final_sl,
                "e_sl": 0,
                "latest_low": latest_low
            }

        recent_low = float(recent["low"].min())

        if previous_e_sl == 0:
            e_sl = recent_low * 0.98
        else:
            if previous_low is None or recent_low > previous_low:
                e_sl = max(previous_e_sl, recent_low * 0.98)

        e_sl = min(e_sl, latest_close * 0.995)

        if e_sl > final_sl:
            e_sl = previous_e_sl

    else:
        e_sl = previous_e_sl

    # ===============================
    # FINAL OUTPUT
    # ===============================
    return {
        "final_sl": round(final_sl, 1),
        "e_sl": round(e_sl, 1),
        "latest_low": round(latest_low, 1),
    }


# =====================================================
# SUPER TREND (ATR-based, standard implementation)
# =====================================================
def calculate_supertrend(high, low, close, period=10, multiplier=2):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR (Wilder)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()

    # Basic bands
    hl2 = (high + low) / 2
    upperband = hl2 + multiplier * atr
    lowerband = hl2 - multiplier * atr

    # Final bands
    final_upper = upperband.copy()
    final_lower = lowerband.copy()

    for i in range(1, len(close)):
        if upperband.iloc[i] < final_upper.iloc[i-1] or close.iloc[i-1] > final_upper.iloc[i-1]:
            final_upper.iloc[i] = upperband.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i-1]

        if lowerband.iloc[i] > final_lower.iloc[i-1] or close.iloc[i-1] < final_lower.iloc[i-1]:
            final_lower.iloc[i] = lowerband.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i-1]

    # Trend
    supertrend = pd.Series(index=close.index, dtype=float)
    trend = pd.Series(0, index=close.index, dtype=int)
    trend.iloc[0] = 1   # ✅ initialize first trend

    for i in range(1, len(close)):

        prev_trend = trend.iloc[i-1]

        if close.iloc[i] > final_upper.iloc[i-1]:
            trend.iloc[i] = 1

        elif close.iloc[i] < final_lower.iloc[i-1]:
            trend.iloc[i] = -1

        else:
            trend.iloc[i] = prev_trend

            if prev_trend == 1 and final_lower.iloc[i] < final_lower.iloc[i-1]:
                final_lower.iloc[i] = final_lower.iloc[i-1]

            if prev_trend == -1 and final_upper.iloc[i] > final_upper.iloc[i-1]:
                final_upper.iloc[i] = final_upper.iloc[i-1]

        if trend.iloc[i] == 1:
            supertrend.iloc[i] = final_lower.iloc[i]
        else:
            supertrend.iloc[i] = final_upper.iloc[i]

    return supertrend