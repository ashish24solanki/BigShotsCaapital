# add_div_trades_columns.py
# Adds missing columns to divergence_trades table

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIV_DB = os.path.join(BASE_DIR, "database", "divergence.db")

print(f"Fixing table in: {DIV_DB}")

con = sqlite3.connect(DIV_DB)
cur = con.cursor()

columns_to_add = [
    ("state", "TEXT"),
    ("detected_on", "TEXT"),
    ("updated_at", "TEXT"),
    ("divergence_low", "REAL"),
    ("divergence_rsi", "REAL"),
    ("buy_above", "REAL"),
    ("sl", "REAL")
]

for col_name, col_type in columns_to_add:
    try:
        cur.execute(f"ALTER TABLE divergence_trades ADD COLUMN {col_name} {col_type}")
        print(f"Added column: {col_name}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Column {col_name} already exists → skipping")
        else:
            print(f"Error adding {col_name}: {e}")

con.commit()
con.close()

print("\nFix complete. You can now re-run mainengine_g.py")