import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.momentum_engine import run_momentum_engine

# =====================================================
# CONFIG
# =====================================================
TEST_MODE = True  # False for live trading

# =====================================================
# DIVERGENCE ENGINE (SIMULATOR)
# =====================================================
def run_divergence_engine_simulator():
    return {}

def format_divergence_results(results):
    if not results:
        return ""

    lines = []

    if results.get("divergence_breakouts"):
        lines.append("📉 *DIVERGENCE*")
        for t in results["divergence_breakouts"]:
            lines.append(
                f"{t['symbol']} | Divergence Breakout | Buy>{t['buy_trigger']:.2f} SL={t['sl']:.2f}"
            )

    if results.get("divergence_invalidated"):
        lines.append("\n❌ *DIVERGENCE INVALIDATED*")
        for s in results["divergence_invalidated"]:
            lines.append(f"{s} | Divergence pattern broken")

    return "\n".join(lines)

# =====================================================
# SUMMARY
# =====================================================
def print_execution_summary(momentum, divergence):
    existing = momentum.get("existing_positions", {})

    print("\n📊 EXECUTION SUMMARY")
    print("📈 MOMENTUM ENGINE")
    print(f"  New Setups      : {len(momentum.get('new_setups', []))}")
    print(f"  Entry Confirmed : {len(momentum.get('entry_confirmed', []))}")
    print(f"  SL Updates      : {len(momentum.get('sl_updates', []))}")
    print(f"  Pyramid Adds    : {len(momentum.get('pyramid_adds', []))}")
    print(f"  SL Hits         : {len(momentum.get('sl_hits', []))}")
    print(f"  Momentum Lost   : {len(momentum.get('momentum_lost', []))}")

    print("\n📂 PORTFOLIO")
    print(f"  Active  : {len(existing.get('active', []))}")
    print(f"  Waiting : {len(existing.get('waiting', []))}")

    print("\n📉 DIVERGENCE ENGINE")
    print(f"  Breakouts   : {len(divergence.get('divergence_breakouts', []))}")
    print(f"  Invalidated : {len(divergence.get('divergence_invalidated', []))}")

# =====================================================
# MAIN
# =====================================================
def main():
    now = datetime.now()

    print("\n🚀 BIG SHOTS CAPITAL — STRATEGY ENGINE")
    print("TEST MODE" if TEST_MODE else "LIVE MODE")
    print(f"📅 {now.strftime('%Y-%m-%d')} | ⏰ {now.strftime('%H:%M:%S')}")

    print("\n📈 Running Momentum Engine...")
    momentum_results = run_momentum_engine()

    print("📉 Running Divergence Engine...")
    divergence_results = run_divergence_engine_simulator()

    telegram_message = ""

    if momentum_results.get("new_setups"):
        telegram_message += "📈 *MOMENTUM*\n"
        for s in momentum_results["new_setups"]:
            telegram_message += (
                f"{s['symbol']} | Buy>{s['buy_trigger']:.2f} SL={s['sl']:.2f}\n"
            )

    divergence_text = format_divergence_results(divergence_results)
    if divergence_text:
        telegram_message += ("\n" if telegram_message else "") + divergence_text

    if TEST_MODE:
        if telegram_message.strip():
            print("\n📨 Telegram Preview\n" + "-" * 40)
            print(telegram_message)
            print("-" * 40)
        else:
            print("\n📭 No new signals")
    else:
        pass  # send_telegram_message(telegram_message)

    print_execution_summary(momentum_results, divergence_results)

    print("\n✅ Strategy Engine Completed")

# =====================================================
if __name__ == "__main__":
    main()
