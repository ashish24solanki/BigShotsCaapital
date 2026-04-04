import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_MOMENTUM = os.path.join(BASE_DIR, "database", "momentum.db")

def reset_momentum_db():
    conn = sqlite3.connect(DB_MOMENTUM)
    cursor = conn.cursor()

    print("⚠️ Clearing momentum_trades table...")

    cursor.execute("DELETE FROM momentum_trades")
    conn.commit()

    print("✅ momentum_trades table cleared successfully")

    conn.close()

if __name__ == "__main__":
    confirm = input("Are you sure you want to reset momentum DB? (YES/NO): ")
    
    if confirm == "YES":
        reset_momentum_db()
    else:
        print("❌ Operation cancelled")