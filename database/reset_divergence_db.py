# reset_divergence_db.py
# Clears all data from divergence_trades and divergence_scanner_history
# Keeps table structure intact
# Run once to remove old/noisy divergence states

import os
import sqlite3
import sys

# =====================================================
# PATH SETUP
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIV_DB = os.path.join(BASE_DIR, "database", "divergence.db")
HISTORY_DB = os.path.join(BASE_DIR, "database", "divergence_scanner_history.db")

print("=== Divergence DB Reset Tool ===")
print(f"Live DB:     {DIV_DB}")
print(f"History DB:  {HISTORY_DB}\n")

confirm = input("This will DELETE ALL divergence states and history. Continue? [y/N]: ").strip().lower()

if confirm != 'y':
    print("Cancelled. No changes made.")
    sys.exit(0)

# =====================================================
# FUNCTION TO CLEAR TABLE
# =====================================================
def clear_table(db_path, table_name):
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        
        # Check if table exists
        cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not cur.fetchone():
            print(f"Table {table_name} does not exist in {db_path} → skipping")
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
# EXECUTE RESET
# =====================================================
print("\nResetting live divergence states...")
clear_table(DIV_DB, "divergence_trades")

print("\nResetting divergence history...")
clear_table(HISTORY_DB, "divergence_scanner_history")

print("\n=== Reset Complete ===")
print("All previous divergence states and history removed.")
print("Next run of divergence engine will start fresh.")