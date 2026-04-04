import os
import sys
import pandas as pd
from datetime import datetime
from kiteconnect import KiteConnect

# ==================== YOUR CONFIG ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from config.kite_config import API_KEY, API_SECRET

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "config", "access_token.txt")

NIFTY50 = ["RELIANCE", "TCS", "INFY"]
CAPITAL_PER_TRADE = 10000
FROM_DATE = "2024-01-01"      # ← change these
TO_DATE   = "2026-03-23"      # ← change these
# ====================================================

def get_kite():
    kite = KiteConnect(api_key=API_KEY)
    if os.path.exists(ACCESS_TOKEN_FILE):
        with open(ACCESS_TOKEN_FILE) as f:
            kite.set_access_token(f.read().strip())
            return kite
    # ... (same login flow as your original script - keep it)
    # (I kept your get_kite() exactly the same - just paste it here if you want)

kite = get_kite()

# Load instruments (same as yours)
instruments = kite.instruments("NSE")
instrument_map = {ins["tradingsymbol"]: ins["instrument_token"]
                  for ins in instruments if ins["tradingsymbol"] in NIFTY50}

def check_condition(df):
    if len(df) < 5: return False
    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    pct = ((c0["close"] - c1["close"]) / c1["close"]) * 100
    return pct >= -1 and c0["close"] < c0["open"] and c0["close"] < c0["ema20"]

def backtest_symbol(symbol):
    token = instrument_map[symbol]
    hist = kite.historical_data(token, FROM_DATE, TO_DATE, "30minute")
    df = pd.DataFrame(hist)
    df = df.rename(columns={"date": "time"})  # kite returns 'date'
    df["time"] = pd.to_datetime(df["time"])
    df = df[["time", "open", "high", "low", "close"]]
    
    df["ema20"] = df["close"].ewm(span=20).mean()
    
    active = None
    trades = []
    for i in range(4, len(df)):
        c_df = df.iloc[:i+1].copy()   # no lookahead
        if active is None:
            if check_condition(c_df):
                price = c_df.iloc[-1]["close"]
                qty = max(int(CAPITAL_PER_TRADE / price), 1)
                sl = c_df.iloc[-2]["high"]
                active = {"qty": qty, "entry": price, "sl": sl}
        else:
            new_sl = c_df.iloc[-2]["high"]
            if new_sl < active["sl"]:
                active["sl"] = new_sl
            if c_df.iloc[-1]["high"] >= active["sl"]:
                exit_price = c_df.iloc[-1]["close"]
                pnl = (active["entry"] - exit_price) * active["qty"]
                trades.append(pnl)
                active = None
    # close any open trade at last close
    if active:
        pnl = (active["entry"] - df.iloc[-1]["close"]) * active["qty"]
        trades.append(pnl)
    
    if not trades:
        return {"trades": 0, "win_rate": 0, "pnl": 0, "pf": 0}
    
    wins = [t for t in trades if t > 0]
    win_rate = len(wins) / len(trades) * 100
    total_pnl = sum(trades)
    gross_win = sum(wins)
    gross_loss = abs(sum(t for t in trades if t < 0))
    pf = gross_win / gross_loss if gross_loss else float('inf')
    
    return {
        "trades": len(trades),
        "win_rate": round(win_rate, 1),
        "pnl": round(total_pnl),
        "avg_pnl": round(total_pnl / len(trades)),
        "profit_factor": round(pf, 2)
    }

print("🚀 Starting REAL backtest...")
total_pnl = 0
for sym in NIFTY50:
    res = backtest_symbol(sym)
    print(f"\n{sym}:")
    print(f"  Trades: {res['trades']}")
    print(f"  Win rate: {res['win_rate']}%")
    print(f"  Total P&L: {res['pnl']} ₹")
    print(f"  Avg/trade: {res['avg_pnl']} ₹")
    print(f"  Profit Factor: {res['profit_factor']}")
    total_pnl += res["pnl"]

print(f"\n=== GRAND TOTAL (3 stocks) ===\nP&L: {total_pnl} ₹")