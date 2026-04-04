# clean_momentum_db.py
# Deletes all rows from momentum_trades table in momentum.db
# Keeps table structure intact
# Run once to remove old momentum states / noise

import os
import sqlite3
import sys

# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOMENTUM_DB = os.path.join(BASE_DIR, "database", "momentum.db")
HISTORY_DB = os.path.join(BASE_DIR, "database", "momentum_scanner_history.db")

print("=== Momentum DB Clean Tool ===")
print(f"Momentum DB: {MOMENTUM_DB}")
print(f"History DB:  {HISTORY_DB}\n")

confirm = input("This will DELETE ALL momentum trades and states. Continue? [y/N]: ").strip().lower()

if confirm != 'y':
    print("Cancelled. No changes made.")
    sys.exit(0)

# =====================================================
# CLEAR TABLE FUNCTION
# =====================================================
def clear_table(db_path, table_name):
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        
        # Check if table exists
        cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not cur.fetchone():
            print(f"Table {table_name} does not exist in {os.path.basename(db_path)} → skipping")
            return
        
        # Delete all rows
        cur.execute(f"DELETE FROM {table_name}")
        deleted = cur.rowcount
        con.commit()
        
        print(f"→ Cleared {deleted} rows from {table_name} in {os.path.basename(db_path)}")
        
    except Exception as e:
        print(f"Error clearing {table_name}: {e}")
    finally:
        if 'con' in locals():
            con.close()

# =====================================================
# EXECUTE CLEAN
# =====================================================
print("\nCleaning momentum trades...")
clear_table(MOMENTUM_DB, "momentum_trades")

# Optional: also clean history if you want (uncomment if needed)
# print("\nCleaning momentum history...")
# clear_table(HISTORY_DB, "momentum_scanner_history")

print("\n=== Clean Complete ===")
print("All previous momentum states removed.")
print("Next run of momentum engine will start fresh.")
print("You can now re-run mainengine_g.py")