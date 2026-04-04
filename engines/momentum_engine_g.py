# =====================================================
# MOMENTUM ENGINE G — FIXED LAST TRADING DATE + DETAILED LOGS
# =====================================================
print("LOADING MOMENTUM ENGINE FILE:", __file__)
import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from support.utils import (
    calculate_ema_tv,
    calculate_rsi_tv,
    calculate_sl_t10_ema20,
    check_pyramiding_signal,
    calculate_supertrend,
    resample_ohlc
    
)

BASE_DIR = PROJECT_ROOT

DB_MOMENTUM = os.path.join(BASE_DIR, "database", "momentum.db")
DB_OHLC     = os.path.join(BASE_DIR, "database", "market_ohlc.db")
DB_HISTORY  = os.path.join(BASE_DIR, "database", "momentum_scanner_history.db")

NIFTY200_CSV = os.path.join(BASE_DIR, "database", "nifty200.csv")

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
MOMO_LOG = os.path.join(LOG_DIR, "momentum_engine_g.log")

LOOKBACK_DAYS = 100

MAX_WAIT_DAYS = 5
MAX_PYRAMID   = 10

TODAY = date.today().isoformat()      # <--- FIXED: define TODAY here
NOW   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =====================================================
# DETAILED LOGGER — FIXED TO WORK
# =====================================================
def momo_log(symbol, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{symbol}] {msg}"
    with open(MOMO_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)

# =====================================================
# DB HELPERS
# =====================================================
def load_live_db():
    con = sqlite3.connect(DB_MOMENTUM)
    df = pd.read_sql("SELECT * FROM momentum_trades", con)
    con.close()
    return df

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

def get_last_trading_date():
    con = sqlite3.connect(DB_OHLC)
    df = pd.read_sql("SELECT MAX(date) as last_date FROM market_ohlc", con)
    con.close()
    last_date = pd.to_datetime(df.iloc[0]['last_date']).date()
    momo_log("SYSTEM", f"Using last trading date: {last_date}")
    return last_date

def ensure_history_table():
    con = sqlite3.connect(DB_HISTORY)
    con.execute("""
        CREATE TABLE IF NOT EXISTS momentum_scanner_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT,
            symbol TEXT,
            event_type TEXT,
            from_state TEXT,
            to_state TEXT,
            buy_above REAL,
            sl REAL,
            remarks TEXT,
            created_at TEXT
        )
    """)
    con.commit()
    con.close()

def append_history(symbol, event_type, from_state, to_state, buy_above=None, sl=None, remarks=None):
    con = sqlite3.connect(DB_HISTORY)
    con.execute("""
        INSERT INTO momentum_scanner_history
        (event_date, symbol, event_type, from_state, to_state, buy_above, sl, remarks, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (TODAY, symbol, event_type, from_state, to_state, buy_above, sl, remarks, NOW))
    con.commit()
    con.close()

# =====================================================
# ENGINE
# =====================================================
def run_momentum_engine():
    print("FILE LOADED:", __file__)
    #print("EMA FUNC:", calculate_ema)   # 👈 ADD HERE
    TODAY = date.today().isoformat()
    NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    momo_log("SYSTEM", "Momentum engine started")
    ensure_history_table()

    LAST_TRADING_DATE = get_last_trading_date()
    momo_log("SYSTEM", f"Using last trading date: {LAST_TRADING_DATE}")
    nifty_df = pd.read_csv(NIFTY200_CSV)
    symbols = sorted(set(nifty_df.iloc[:, 0].astype(str).str.strip()))

    momo_log("SYSTEM", f"Scanning {len(symbols)} symbols from NIFTY 200")

    live_df = load_live_db()
    live_map = {r.symbol: r for r in live_df.itertuples()} if not live_df.empty else {}

    con = sqlite3.connect(DB_MOMENTUM)
    c = con.cursor()

    new_setups_count = 0

    for symbol in symbols:
        momo_log(symbol, "Checking symbol")

        df = load_ohlc(symbol)
        df = df[df['date'].dt.date <= LAST_TRADING_DATE]
        df = df.sort_values('date')
        df.set_index('date', inplace=True)

        if df.empty:
            momo_log(symbol, "Skipped: no data in DB")
            continue

        candle_count = len(df)
        if candle_count < 100:
            momo_log(symbol, f"Skipped: only {candle_count} candles (need at least 100)")
            continue

        # Use last trading date for conditions
        t = len(df) - 1
        if t < 2:
            momo_log(symbol, "Skipped: not enough candles for prev day")
            continue

        close_t = float(df.iloc[t]["close"])
        open_t = float(df.iloc[t]["open"])
        volume_t = float(df.iloc[t]["volume"])
        close_t1 = float(df.iloc[t-1]["close"])
        high_t = float(df.iloc[t]["high"])

        rsi10 = calculate_rsi_tv(df["close"], 10)
        rsi10_t = float(rsi10.iloc[t])
        rsi10_t1 = float(rsi10.iloc[t-1]) if t >= 1 else np.nan

        try:
            st = calculate_supertrend(df["high"], df["low"], df["close"], period=10, multiplier=2)
            st_t = float(st.iloc[t])
            st_t1 = float(st.iloc[t-1]) if t >= 1 else np.nan
        except Exception as e:
            momo_log(symbol, f"Supertrend calc failed: {str(e)} - skip symbol")
            continue

        # =====================================================
        # HTF RESAMPLING (USING UTILS - FIXED)
        # =====================================================
        

        try:
            df_reset = df.reset_index()  # convert back to column format for utils

            weekly = resample_ohlc(df_reset, "W")
            monthly = resample_ohlc(df_reset, "ME")

            if weekly is None or weekly.empty or monthly is None or monthly.empty:
                raise ValueError("Empty HTF data")

        except Exception as e:
            momo_log(symbol, f"Resampling failed: {str(e)} - skip HTF checks")
            weekly = pd.DataFrame()
            monthly = pd.DataFrame()


        if len(weekly) < 2 or len(monthly) < 2:
            momo_log(symbol, "Skipped: insufficient weekly/monthly data")
            continue

        # ================= MONTHLY / WEEKLY FIX =================
        test_dt = pd.to_datetime(LAST_TRADING_DATE)
        #last_month_date = pd.to_datetime(monthly.iloc[-1]['date'])
        if 'date' in monthly.columns:
            last_month_date = pd.to_datetime(monthly.iloc[-1]['date'])
        else:
            last_month_date = pd.to_datetime(monthly.index[-1])

        if last_month_date.month == test_dt.month and last_month_date.year == test_dt.year:
            m_idx = -1
        else:
            m_idx = -2

        m_prev = m_idx - 1

        #last_week_date = pd.to_datetime(weekly.iloc[-1]['date'])
        if 'date' in weekly.columns:
            last_week_date = pd.to_datetime(weekly.iloc[-1]['date'])
        else:
            last_week_date = pd.to_datetime(weekly.index[-1])
        
        w_idx = -1 if last_week_date.date() == test_dt.date() else -2



        weekly_close = float(weekly.iloc[w_idx]['close'])
        weekly_ema9 = float(calculate_ema_tv(weekly['close'], 9).iloc[-1])
        weekly_high_t1 = float(weekly.iloc[w_idx-1]['high'])
        weekly_low_t1 = float(weekly.iloc[w_idx]['low'])
        weekly_rsi10_t1 = float(calculate_rsi_tv(weekly['close'], 10).iloc[w_idx])

        monthly_close = float(monthly.iloc[m_idx]['close'])
        monthly_ema9 = float(calculate_ema_tv(monthly['close'], 9).iloc[m_idx])
        monthly_rsi_series = calculate_rsi_tv(monthly['close'], 10)
        monthly_rsi10_t1 = float(monthly_rsi_series.iloc[-1])
        monthly_low_t1 = float(monthly.iloc[m_prev]['low'])
        # =====================================================
        # EXTRA VALUES
        # =====================================================
        daily_high_t1 = float(df.iloc[t-1]["high"])
        low_t = float(df.iloc[t]["low"])

        high_3_prev = df.iloc[t-3:t]["high"].max()
      

        ema9 = calculate_ema_tv(df["close"], 9)
        ema20 = calculate_ema_tv(df["close"], 20)
        ema9_t = float(ema9.iloc[t])
        ema20_t = float(ema20.iloc[t])

        # =====================================================
        # COMMON CONDITIONS
        # =====================================================
        cond_price_cap = close_t <= 10000
        cond_volume = volume_t >= 500000
        cond_green = close_t > open_t

        # =====================================================
        # SETUP 1 (BREAKOUT)
        # =====================================================
        cond1 = (
            close_t >= high_3_prev and
            open_t >= close_t1 and
            monthly_close > monthly_ema9 and
            weekly_close > weekly_ema9 and
            close_t >= weekly_high_t1 and
            weekly_rsi10_t1 >= 45 and
            monthly_rsi10_t1 >= 40 and
            (
                (rsi10_t >= 60) or
                (rsi10_t > 60 and rsi10_t1 <= 60)
            ) and
            (
                (close_t >= st_t) or
                (close_t > st_t and close_t1 <= st_t1)
            )
        )

        # =====================================================
        # SETUP 2 (PULLBACK)
        # =====================================================
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

        # =====================================================
        # SETUP 3 (CANDLE STRUCTURE)
        # =====================================================
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

        cond3 = (
            monthly_close > monthly_low_t1 and
            weekly_close > weekly_low_t1 and
            monthly_rsi10_t1 >= 40 and
            close_t > open_t and
            close_t > close_t1 and
            open_t <= ema9_t and
            cond_candle
        )

        # =====================================================
        # FINAL CONDITION
        # =====================================================
        final_condition = (
            cond_price_cap and
            cond_volume and
            cond_green and
            (cond1 or cond2 or cond3)
        )
        ##################################################
        
        ##################################################
        if not final_condition:
            momo_log(symbol, "Skipped: final condition not met")
            continue

        sl_data = calculate_sl_t10_ema20(df.reset_index(), LAST_TRADING_DATE)
        if not sl_data or sl_data.get("final_sl") is None:
            momo_log(symbol, "Skipped: SL calc failed")
            continue

        sl = round(float(sl_data["final_sl"]), 1)
        buy_above = round(high_t * 1.002, 1)

        c.execute("""
            INSERT OR REPLACE INTO momentum_trades
            (symbol, buy_above, sl, signal_date, status,
             pyramid_count, state_changed_at)
            VALUES (?, ?, ?, ?, 'WAITING', 0, ?)
        """, (symbol, buy_above, sl, LAST_TRADING_DATE, NOW))

        append_history(
            symbol, "NEW_SETUP", None, "WAITING",
            buy_above=buy_above, sl=sl,
            remarks="Full momentum condition matched"
        )

        con.commit()
        momo_log(symbol, f"NEW SETUP - WAITING | Buy above {buy_above} | SL {sl}")
        new_setups_count += 1

    con.close()
    momo_log("SYSTEM", f"Momentum engine completed | New setups found: {new_setups_count}")
    print(">>> Momentum engine completed")

# =====================================================
if __name__ == "__main__":
    run_momentum_engine()