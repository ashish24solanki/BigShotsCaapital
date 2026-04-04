import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, date
from contextlib import redirect_stdout

# =====================================================
# SWITCH
# =====================================================
SEND_TELEGRAM = True   # True = send telegram | False = silent

# =====================================================
# PATHS
# =====================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engines.momentum_engine import run_momentum_engine
from engines.divergence_engine import run_divergence_engine

# ---- SAFE TELEGRAM IMPORT ----
if SEND_TELEGRAM:
    try:
        from support.telegram import send_message
        from config.bot_config import PORT_BOT_CHAT_ID
    except Exception:
        SEND_TELEGRAM = False   # hard-disable telegram if import fails

DB_MOMENTUM = os.path.join(BASE_DIR, "database", "momentum.db")
DB_DIVERGENCE = os.path.join(BASE_DIR, "database", "divergence.db")

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

MOMENTUM_LOG = os.path.join(LOG_DIR, "momentum.log")
DIVERGENCE_LOG = os.path.join(LOG_DIR, "divergence.log")

EXCEL_FILE = "strategy_state_today.xlsx"
TODAY = date.today().isoformat()

# =====================================================
# HELPERS
# =====================================================
def load_trades(db_path, table):
    con = sqlite3.connect(db_path)
    df = pd.read_sql(f"SELECT * FROM {table}", con)
    con.close()

    if df.empty:
        return df

    if "signal_date" not in df.columns:
        df["signal_date"] = TODAY
    else:
        df["signal_date"] = df["signal_date"].astype(str)

    return df


def block(title, df, mode="BUY"):
    if df.empty:
        return ""
    lines = [title]
    for _, r in df.iterrows():
        if mode == "BUY":
            lines.append(f"{r.symbol} | Buy Above {r.buy_above} | SL {r.sl}")
        elif mode == "ACTIVE":
            lines.append(f"{r.symbol} | Entry {r.buy_above} | SL {r.sl}")
        elif mode == "SL":
            lines.append(f"{r.symbol} | New SL {r.sl}")
        elif mode == "PYR":
            lines.append(f"{r.symbol} | Pyramid Count {int(r.pyramid_count)}")
    return "\n".join(lines)

# =====================================================
# MAIN
# =====================================================
def main():
    print("\n🚀 STRATEGY MAIN ENGINE")
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n🔄 Running Momentum Engine...")
    with open(MOMENTUM_LOG, "w") as f:
        with redirect_stdout(f):
            run_momentum_engine()
    print("📄 Momentum log written")

    print("🔄 Running Divergence Engine...")
    with open(DIVERGENCE_LOG, "w") as f:
        with redirect_stdout(f):
            run_divergence_engine()
    print("📄 Divergence log written")

    momo = load_trades(DB_MOMENTUM, "momentum_trades")
    div  = load_trades(DB_DIVERGENCE, "divergence_trades")

    momo = momo[momo.buy_above.notna() & momo.sl.notna()]
    div  = div[div.buy_above.notna() & div.sl.notna()]

    momo_new    = momo[(momo.status == "WAITING") & (momo.signal_date == TODAY)]
    momo_wait   = momo[(momo.status == "WAITING") & (momo.signal_date < TODAY)]
    momo_active = momo[momo.status == "ACTIVE"]

    div_new     = div[(div.status == "WAITING") & (div.signal_date == TODAY)]
    div_wait    = div[(div.status == "WAITING") & (div.signal_date < TODAY)]
    div_active  = div[div.status == "ACTIVE"]

    momo_sl = momo[(momo.status == "ACTIVE") & (momo.updated_at.str.startswith(TODAY))]
    div_sl  = div[(div.status == "ACTIVE") & (div.updated_at.str.startswith(TODAY))]

    momo_pyr = momo[(momo.status == "ACTIVE") & (momo.pyramid_count > 0) & (momo.last_pyramid_date == TODAY)]
    div_pyr  = div[(div.status == "ACTIVE") & (div.pyramid_count > 0) & (div.last_pyramid_date == TODAY)]

    blocks = [
        block("📈 MOMENTUM – NEW SETUPS (TODAY)", momo_new),
        block("📈 MOMENTUM – ACTIVE", momo_active, "ACTIVE"),
        block("🔄 MOMENTUM – SL UPDATED", momo_sl, "SL"),
        block("➕ MOMENTUM – PYRAMIDING", momo_pyr, "PYR"),
        block("📉 DIVERGENCE – NEW SETUPS (TODAY)", div_new),
        block("📉 DIVERGENCE – ACTIVE", div_active, "ACTIVE"),
        block("🔄 DIVERGENCE – SL UPDATED", div_sl, "SL"),
        block("➕ DIVERGENCE – PYRAMIDING", div_pyr, "PYR"),
    ]

    message = "\n\n".join(b for b in blocks if b)

    print(message)

    if SEND_TELEGRAM and message:
        send_message(PORT_BOT_CHAT_ID, message)

    # ---------------- EXCEL (SAFE) ----------------
    with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
        pd.DataFrame({"generated_at": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]}).to_excel(
            writer, sheet_name="_SUMMARY", index=False
        )

        for name, df in [
            ("Momentum_New", momo_new),
            ("Momentum_Waiting", momo_wait),
            ("Momentum_Active", momo_active),
            ("Momentum_SL_Updated", momo_sl),
            ("Momentum_Pyramiding", momo_pyr),
            ("Divergence_New", div_new),
            ("Divergence_Waiting", div_wait),
            ("Divergence_Active", div_active),
            ("Divergence_SL_Updated", div_sl),
            ("Divergence_Pyramiding", div_pyr),
        ]:
            if not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)

    print(f"\n📊 Excel exported: {EXCEL_FILE}")
    print("\n✅ MAIN ENGINE COMPLETED CLEANLY\n")


if __name__ == "__main__":
    main()
