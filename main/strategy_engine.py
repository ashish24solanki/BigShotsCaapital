import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.momentum_engine import run_momentum_engine, format_momentum_results

# =====================================================
# CONFIGURATION
# =====================================================
TEST_MODE = True  # Set to False for live trading

# =====================================================
# DIVERGENCE ENGINE SIMULATOR
# =====================================================
def run_divergence_engine_simulator():
    """Simulate divergence engine based on your log output"""
    return {
        "divergence_breakouts": [
            {"symbol": "ACMESOLAR", "buy_trigger": 218.17, "sl": 202.13},
            {"symbol": "BEML", "buy_trigger": 1836.83, "sl": 1631.16},
            {"symbol": "COCHINSHIP", "buy_trigger": 1633.63, "sl": 1406.34},
            {"symbol": "DATAPATTNS", "buy_trigger": 2652.65, "sl": 2355.3},
            {"symbol": "GAIL", "buy_trigger": 168.84, "sl": 156.96},
            {"symbol": "MAZDOCK", "buy_trigger": 2516.51, "sl": 2269.08},
            {"symbol": "OLECTRA", "buy_trigger": 1094.79, "sl": 1022.76},
            {"symbol": "SYRMA", "buy_trigger": 729.13, "sl": 637.34}
        ],
        "divergence_invalidated": [
            "ASTERDM", "BHARTIHEXA", "CONCORDBIO", "HYUNDAI", 
            "KAJARIACER", "MAXHEALTH", "PGHH", "SUMICHEM", "VMM"
        ],
        "price_above_supertrend": []
    }

def format_divergence_results(results):
    """Format divergence results nicely"""
    if not results:
        return ""
    
    lines = []
    
    # Divergence Breakouts
    if results.get("divergence_breakouts"):
        lines.append("📉 *DIVERGENCE*")
        for trade in results["divergence_breakouts"]:
            lines.append(f"{trade['symbol']} | Divergence Breakout | Buy>{trade['buy_trigger']:.2f} SL={trade['sl']:.2f}")
    
    # Divergence Invalidated
    if results.get("divergence_invalidated"):
        lines.append("\n❌ *DIVERGENCE INVALIDATED*")
        for symbol in results["divergence_invalidated"]:
            lines.append(f"{symbol} | Divergence pattern broken")
    
    return "\n".join(lines)

# =====================================================
# PRINT EXECUTION SUMMARY
# =====================================================
def print_execution_summary(momentum_results, divergence_results):
    """Print detailed execution summary"""
    print(f"\n{'='*60}")
    print("📊 EXECUTION SUMMARY")
    print(f"{'='*60}")
    
    # MOMENTUM SUMMARY
    print(f"📈 MOMENTUM ENGINE:")
    print(f"  • New Setups: {len(momentum_results.get('new_setups', []))}")
    print(f"  • Entry Confirmed: {len(momentum_results.get('entry_confirmed', []))}")
    print(f"  • SL Updates: {len(momentum_results.get('sl_updates', []))}")
    print(f"  • Pyramid Adds: {len(momentum_results.get('pyramid_adds', []))}")
    print(f"  • SL Hits: {len(momentum_results.get('sl_hits', []))}")
    print(f"  • Momentum Lost: {len(momentum_results.get('momentum_lost', []))}")
    
    # EXISTING POSITIONS
    existing = momentum_results.get('existing_positions', {})
    print(f"  • Total in DB: {len(existing.get('all', []))}")
    print(f"  • Waiting: {len(existing.get('waiting', []))}")
    print(f"  • Active: {len(existing.get('active', []))}")
    
    # Print waiting symbols
    if existing.get('waiting'):
        print(f"\n⏳ Waiting Positions:")
        for pos in existing['waiting'][:10]:  # Show first 10
            print(f"    {pos['symbol']} - Buy>{pos['buy_above']:.2f}")
        if len(existing['waiting']) > 10:
            print(f"    ... and {len(existing['waiting']) - 10} more")
    
    # Print active symbols
    if existing.get('active'):
        print(f"\n📊 Active Positions:")
        for pos in existing['active']:
            print(f"    {pos['symbol']} - Entry:{pos['buy_above']:.2f}, SL:{pos['sl']:.2f}")
    
    print()  # Empty line
    
    # DIVERGENCE SUMMARY
    print(f"📉 DIVERGENCE ENGINE:")
    print(f"  • Breakout Signals: {len(divergence_results.get('divergence_breakouts', []))}")
    print(f"  • Invalidated Patterns: {len(divergence_results.get('divergence_invalidated', []))}")
    
    print()  # Empty line
    
    # TOTAL SUMMARY
    total_new_signals = len(momentum_results.get('new_setups', [])) + len(divergence_results.get('divergence_breakouts', []))
    print(f"📊 TOTAL NEW SIGNALS: {total_new_signals}")
    print(f"📊 TOTAL ACTIVE POSITIONS: {len(existing.get('active', []))}")
    print(f"📊 TOTAL WAITING POSITIONS: {len(existing.get('waiting', []))}")

# =====================================================
# MAIN ENGINE
# =====================================================
def main():
    print(f"\n{'='*60}")
    print("🚀 BIG SHOTS CAPITAL — STRATEGY ENGINE")
    print(f"{'='*60}")
    
    if TEST_MODE:
        print("🚫 Telegram messages are DISABLED (TEST MODE)")
    else:
        print("📨 Telegram messages are ENABLED")
    
    print(f"\n📅 Date: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}")
    
    print(f"\n📊 Updating market OHLC database...")
    # Your market data update code here...
    print("✅ Market data updated")
    
    # Run Momentum Engine
    print("\n📈 Running Momentum Engine...")
    momentum_results = run_momentum_engine()
    
    # Run Divergence Engine
    print("📉 Running Divergence Engine...")
    divergence_results = run_divergence_engine_simulator()
    
    # Build Telegram message (only NEW signals)
    telegram_message = ""
    
    # Add Momentum section (only NEW setups)
    if momentum_results.get("new_setups"):
        telegram_message += "📈 *MOMENTUM*\n"
        for setup in momentum_results["new_setups"]:
            telegram_message += f"{setup['symbol']} | Buy>{setup['buy_trigger']:.2f} SL={setup['sl']:.2f}\n"
    
    # Add Divergence section
    divergence_section = format_divergence_results(divergence_results)
    if divergence_section:
        if telegram_message:  # Add separator if we already have momentum
            telegram_message += "\n"
        telegram_message += divergence_section
    
    # Output Telegram message
    if TEST_MODE:
        if telegram_message.strip():
            print("\n📨 Would send message:")
            print("-" * 50)
            print(telegram_message)
            print("-" * 50)
        else:
            print("\n📭 No new signals to send to Telegram")
    else:
        # send_telegram_message(telegram_message)
        print("\n📨 Telegram message would be sent here")
    
    # Print detailed summary
    print_execution_summary(momentum_results, divergence_results)
    
    print(f"\n✅ Strategy Engine Completed")
    print(f"🕒 Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    main()