import os
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# ==================================================
# PATHS
# ==================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_DIR = os.path.join(BASE_DIR, "database")
DATA_DIR = os.path.join(BASE_DIR, "database")

DB_FILE = os.path.join(DB_DIR, "market_ohlc.db")
# Define the base NIFTY500_FILE path
NIFTY500_BASE_FILE = os.path.join(DATA_DIR, "nifty500.csv")

LOOKBACK_DAYS = 700

# ==================================================
# DB INIT
# ==================================================
def init_db():
    os.makedirs(DB_DIR, exist_ok=True)

    db = sqlite3.connect(DB_FILE)
    c = db.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS ohlc_daily (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)

    db.commit()
    db.close()

# ==================================================
# HELPERS
# ==================================================
def get_last_date(db, symbol):
    c = db.cursor()
    c.execute(
        "SELECT MAX(date) FROM ohlc_daily WHERE symbol=?",
        (symbol,)
    )
    row = c.fetchone()
    return row[0] if row and row[0] else None


def save_ohlc(db, symbol, df):
    c = db.cursor()

    rows = [
        (
            symbol,
            r["date"].strftime("%Y-%m-%d"),
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(r["volume"]),
        )
        for _, r in df.iterrows()
    ]

    c.executemany("""
        INSERT OR REPLACE INTO ohlc_daily
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)

    db.commit()

# ==================================================
# MAIN UPDATE FUNCTION (CALLED BY STRATEGY ENGINE)
# ==================================================
def update_market_ohlc(kite):
    print("\n📊 MARKET DATA UPDATE STARTED")

    init_db()

    # ------------------------------
    # LOAD NIFTY 200 SYMBOLS ONLY
    # ------------------------------
    try:
        # First, find the correct file with proper case handling
        nifty200_file = None
        
        # Check different case variations
        file_variations = [
            os.path.join(DATA_DIR, "nifty200.csv"),
            os.path.join(DATA_DIR, "NIFTY200.csv"),
            os.path.join(DATA_DIR, "Nifty200.csv"),
            os.path.join(DATA_DIR, "Nifty_200.csv"),
        ]
        
        for file_path in file_variations:
            if os.path.exists(file_path):
                nifty200_file = file_path
                break
        
        if not nifty200_file:
            print(f"❌ NIFTY200 CSV file not found in {DATA_DIR}")
            print(f"📂 Looking for files: nifty200.csv, NIFTY200.csv, Nifty200.csv")
            print(f"📂 Directory contents: {os.listdir(DATA_DIR)}")
            return
        
        print(f"📂 Using file: {nifty200_file}")
        
        symbols_df = pd.read_csv(nifty200_file)
        
        # Check column names
        print(f"📋 CSV columns: {list(symbols_df.columns)}")
        
        # Try different possible column names
        symbol_column = None
        possible_columns = ['symbol', 'SYMBOL', 'Symbol', 'tradingsymbol', 'TradingSymbol', 'Ticker', 'ticker']
        
        for col in possible_columns:
            if col in symbols_df.columns:
                symbol_column = col
                print(f"✓ Found symbol column: '{symbol_column}'")
                break
        
        if not symbol_column:
            print("❌ Could not find symbol column in CSV file")
            print(f"Available columns: {list(symbols_df.columns)}")
            return
        
        symbols = (
            symbols_df[symbol_column]
            .astype(str)
            .str.strip()
            .str.upper()
            .unique()
            .tolist()
        )

        print(f"📊 NIFTY 200 universe size: {len(symbols)}")
        
        # Show first few symbols
        print(f"📋 First 5 symbols: {symbols[:5]}")

    except Exception as e:
        print(f"❌ Error loading NIFTY200 symbols: {e}")
        print(f"📂 Data directory: {DATA_DIR}")
        if os.path.exists(DATA_DIR):
            print(f"📂 Directory contents: {os.listdir(DATA_DIR)}")
        return

    instruments = pd.DataFrame(kite.instruments("NSE"))
    token_map = {}
    for _, r in instruments.iterrows():
        if (
            r["exchange"] == "NSE" and 
            r["segment"] == "NSE" and
            r["instrument_type"] == "EQ"):
            symbol = str(r["tradingsymbol"]).strip().upper()

            if symbol not in token_map:
                token_map[symbol] = r["instrument_token"]

    print("Total EQ tokens:", len(token_map))
    # Debug one symbol
    if "AXISBANK" in token_map:
        print("AXISBANK TOKEN:", token_map["AXISBANK"])

    # Check token mapping for some symbols
    print(f"\n📊 Checking token mapping...")
    found_tokens = 0
    for symbol in symbols[:5]:  # Check first 5 symbols
        if symbol in token_map:
            found_tokens += 1
            print(f"  ✓ {symbol}: Token found")
        else:
            print(f"  ✗ {symbol}: Token NOT found")
    
    print(f"\n📊 Token mapping success rate: {found_tokens}/5")

    db = sqlite3.connect(DB_FILE)

    total = len(symbols)
    done = 0
    updated_symbols = 0

    for symbol in symbols:
        done += 1

        if symbol not in token_map:
            # Uncomment this line if you want to see which symbols are skipped
            # print(f"\n⚠️ Skipping {symbol}: No token found")
            continue

        token = token_map[symbol]
        last_date = get_last_date(db, symbol)

        if last_date:
            # Convert last_date string to datetime
            last_date_dt = datetime.strptime(last_date, "%Y-%m-%d")
            # Start from next day
            from_date = last_date_dt + timedelta(days=1)
        else:
            # No data yet, fetch last LOOKBACK_DAYS
            from_date = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        
        # Always fetch at least yesterday's data
        to_date = datetime.now() - timedelta(days=1)
        
        # Don't fetch if we already have today's data
        if last_date and last_date >= to_date.strftime("%Y-%m-%d"):
            # Uncomment for verbose output
            # print(f"\r⏳ Skipping {symbol}: Already have latest data ({last_date})", end="")
            continue

        try:
            # Uncomment for verbose output
            # print(f"\n📥 Fetching {symbol} from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")
            
            data = kite.historical_data(
                token,
                from_date,
                to_date,
                interval="day"
            )

            if data:
                df = pd.DataFrame(data)
                if symbol == "AXISBANK":
                    print("\nDEBUG AXISBANK DATA:")
                    print(df.tail(3))
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                
                # Filter out dates we already have (just in case)
                if last_date:
                    df = df[df["date"] > pd.Timestamp(last_date_dt)]
                
                if not df.empty:
                    save_ohlc(db, symbol, df)
                    updated_symbols += 1
                    # Uncomment for verbose output
                    # print(f"  ✓ Saved {len(df)} new records")
                else:
                    # Uncomment for verbose output
                    # print(f"  ⓘ No new data")
                    pass
            else:
                # Uncomment for verbose output
                # print(f"  ⓘ No data returned from API")
                pass

        except Exception as e:
            print(f"\n❌ Error updating {symbol}: {str(e)}")

        print(
            f"\r⏳ Progress: {done}/{total} ({int(done / total * 100)}%) | Updated: {updated_symbols}",
            end=""
        )

    db.close()
    print(f"\n\n✅ Market OHLC database updated: {updated_symbols} symbols updated")

    # Print some statistics
    db = sqlite3.connect(DB_FILE)
    c = db.cursor()
    
    # Get count of records
    c.execute("SELECT COUNT(*) FROM ohlc_daily")
    total_records = c.fetchone()[0]
    
    # Get latest date in database
    c.execute("SELECT MAX(date) FROM ohlc_daily")
    latest_date = c.fetchone()[0]
    
    # Get count of symbols with data
    c.execute("SELECT COUNT(DISTINCT symbol) FROM ohlc_daily")
    symbols_with_data = c.fetchone()[0]
    
    db.close()
    
    print(f"📊 Database Statistics:")
    print(f"  • Total records: {total_records}")
    print(f"  • Symbols with data: {symbols_with_data}")
    print(f"  • Latest date in DB: {latest_date}")