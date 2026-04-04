# backfill_ohlc.py - Correct column order + clean logging

import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import time
import logging

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "backfill_ohlc.log")), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

try:
    from config.kite_config import API_KEY, API_SECRET
    from main.mainengine_g import get_kite
except ModuleNotFoundError:
    logger.warning("Import failed - fallback")
    API_KEY = "your_key_if_needed"
    API_SECRET = "your_secret_if_needed"
    def get_kite():
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=API_KEY)
        logger.info("Manual login")
        request_token = input("Paste request_token: ").strip()
        data = kite.generate_session(request_token, api_secret=API_SECRET)
        kite.set_access_token(data["access_token"])
        return kite

DB_OHLC = os.path.join(PROJECT_ROOT, "database", "market_ohlc.db")

MAX_DAYS_PER_REQUEST = 1500
MAX_RETRIES = 3
SLEEP_CHUNK = 0.5
SLEEP_SYMBOL = 1.2
MIN_CANDLES_TO_SKIP = 200

def get_existing_candles(cur, symbol):
    cur.execute("SELECT COUNT(*) FROM market_ohlc WHERE symbol = ?", (symbol,))
    return cur.fetchone()[0]

def backfill_daily_data(kite, symbols, years=10):
    con = sqlite3.connect(DB_OHLC)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_ohlc (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    con.commit()

    to_date = datetime.now().date()
    from_date = to_date - timedelta(days=365 * years + 90)

    logger.info(f"Backfill ~{from_date} to {to_date} | Symbols: {len(symbols)}")

    instruments = kite.instruments("NSE")
    
    token_map = {}

    for i in instruments:
        if (
            i["exchange"] == "NSE" and
            i["segment"] == "NSE" and
            i["instrument_type"] == "EQ"
        ):
            symbol = str(i["tradingsymbol"]).strip().upper()

            if symbol not in token_map:
                token_map[symbol] = i["instrument_token"]
    

    success = 0
    skipped = 0
    failed = []

    for idx, symbol in enumerate(symbols, 1):
        logger.info(f"[{idx}/{len(symbols)}] {symbol}")

        if symbol not in token_map:
            logger.warning(f"{symbol} - no token")
            failed.append(symbol)
            continue

        existing = get_existing_candles(cur, symbol)
        if existing >= MIN_CANDLES_TO_SKIP:
            logger.info(f"{symbol} - already {existing} candles - skip")
            skipped += 1
            continue

        token = token_map[symbol]
        current_from = from_date
        total_added = 0

        while current_from < to_date:
            chunk_to = min(current_from + timedelta(days=MAX_DAYS_PER_REQUEST - 1), to_date)
            chunk_str = f"{current_from} to {chunk_to}"

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    data = kite.historical_data(
                        instrument_token=token,
                        from_date=current_from.strftime("%Y-%m-%d"),
                        to_date=chunk_to.strftime("%Y-%m-%d"),
                        interval="day"
                    )

                    if not data:
                        logger.info(f"{symbol} - empty {chunk_str} - continue")
                        break

                    df = pd.DataFrame(data)[['date', 'open', 'high', 'low', 'close', 'volume']]
                    print("RAW DATE SAMPLE:", df['date'].head(3))
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values("date")
                    df = df.drop_duplicates(subset=["date"], keep="last")
                    df = df[df['date'].dt.dayofweek < 5]
                    if df.empty:
                        logger.warning(f"{symbol} - no valid trading data after cleaning")
                        continue

                    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                    df['symbol'] = symbol

                    # Reorder columns to match table: symbol, date, open, high, low, close, volume
                    df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]

                    cur.executemany(
                        "INSERT OR REPLACE INTO market_ohlc VALUES (?, ?, ?, ?, ?, ?, ?)",
                        df.itertuples(index=False, name=None)
                    )
                    con.commit()

                    added = len(df)
                    total_added += added
                    logger.info(f"{symbol} - {chunk_str} added {added} (total {total_added})")

                    break

                except Exception as e:
                    logger.error(f"{symbol} - {chunk_str} attempt {attempt} failed: {str(e)[:80]}")
                    if attempt == MAX_RETRIES:
                        failed.append(f"{symbol} ({chunk_str})")
                    time.sleep(2 ** attempt)

            current_from = chunk_to + timedelta(days=1)
            time.sleep(SLEEP_CHUNK)

        if total_added > 0:
            success += 1
            logger.info(f"{symbol} - SUCCESS ({total_added} candles)")
        else:
            logger.warning(f"{symbol} - NO DATA")
            failed.append(symbol)

        time.sleep(SLEEP_SYMBOL)

    con.close()

    logger.info("Backfill complete")
    logger.info(f"Success: {success}")
    logger.info(f"Skipped (already enough): {skipped}")
    logger.info(f"Failed: {len(failed)}")
    if failed:
        logger.info(f"Failed (first 10): {', '.join(failed[:10])}")

if __name__ == "__main__":
    logger.info("=== Backfill OHLC - Fixed Column Order ===")
    kite = get_kite()

    nifty_path = os.path.join(PROJECT_ROOT, "database", "nifty200.csv")
    if not os.path.exists(nifty_path):
        logger.error(f"Missing {nifty_path}")
        sys.exit(1)

    symbols = (pd.read_csv(nifty_path).iloc[:, 0].astype(str).str.strip().str.upper().tolist())
    logger.info(f"Loaded {len(symbols)} symbols")

    if input("Start backfill? [y/N]: ").strip().lower() != 'y':
        logger.info("Cancelled.")
        sys.exit(0)

    backfill_daily_data(kite, symbols, years=10)