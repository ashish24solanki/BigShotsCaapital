# BigShots Capital AI Agent Instructions

## Architecture Overview

**BigShots Capital** is a trading strategy automation platform that detects momentum and divergence breakouts in NIFTY 500 stocks and sends signals via Telegram.

### Core Data Flow

1. **Market Data** → [market_data_updater.py](../main/market_data_updater.py) → SQLite (`market_ohlc.db`)
2. **Two Parallel Engines**:
   - [momentum_engine.py](../engines/momentum_engine.py): Tracks momentum breakouts, manages pyramiding (up to 5 adds)
   - [divergence_engine.py](../engines/divergence_engine.py): Detects RSI divergence patterns (40-candle lookback)
3. **Signal Management** → [strategy_engine.py](../main/strategy_engine.py) → Telegram broadcast
4. **GUI** → [launcher_gui.py](../launcher_gui.py): TK-based control panel for starting/stopping market updater, strategy engine, and membership bot

### Databases

- `database/market_ohlc.db`: Daily OHLC data (7-year history, 700-lookback)
- `database/momentum.db`: Active momentum trades (symbol, buy_above, SL, pyramid_count, GTT expiry)
- `database/divergence.db`: Active divergence trades (similar fields)
- `database/portfolio.db` & `gtt_anchor_levels.db`: Portfolio tracking (Zerodha Kite API integration)

## Critical Patterns & Conventions

### Path Resolution (Multi-Platform)

```python
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

Uses relative path from file location, works for both frozen EXE (PyInstaller) and source execution. **Always** import `BASE_DIR` from [config/paths.py](../config/paths.py) or recalculate—never hardcode absolute paths.

### Database Operations

- Use `sqlite3.connect()` directly; no ORM
- Schemas use PRIMARY KEYs to prevent duplicate OHLC inserts
- **Pattern**: Load → Transform → Insert/Update in batches
- Example: [momentum_engine.py#L82-L95](../engines/momentum_engine.py#L82-L95) (load_all_positions)

### Technical Indicators

Located in [support/utils.py](../support/utils.py):

- **EMA**: Exponential Moving Average (used for dynamic SL calculation)
- **RSI**: TradingView-style formula (14-period default, used for divergence confirmation)
- **Supertrend(10,2)**: Support/resistance for momentum entries
- All return pandas Series; match on index

### Pyramiding Logic

Both engines allow up to **5 pyramid adds** per position. Check [support/utils.py#check_pyramiding_signal](../support/utils.py):
- Space pyramid entries 5+ days apart
- Max close price: ₹10,000 (hard limit)
- Track `pyramid_count` and `last_pyramid_date` per symbol

### Logging

Standard pattern:
```python
from support.logger import log
log("INFO", "Message here", console=True)  # console=True prints to terminal too
```

Logs go to `logs/strategy.log`. No 3rd-party logging framework.

### Telegram Integration

- [support/telegram.py](../support/telegram.py): `send_trial()` and `send_pro()` (markdown formatting)
- Chat IDs in [config/bot_config.py](../config/bot_config.py)
- Exceptions silently fail; no retry logic needed
- **Format**: Use emojis + `*bold*` markdown for readability

## Common Workflows

### Adding a New Signal/Engine

1. Create engine in `engines/`
2. Add init_db() and load/save functions matching pattern in momentum_engine.py
3. Call from [strategy_engine.py](../main/strategy_engine.py#L123-L160)
4. Format results + broadcast to Telegram
5. Store signal data in dedicated `*.db` table

### Modifying Indicator Thresholds

- Momentum/Divergence settings are in engine file headers (MIN_CANDLES, LOOKBACK, MAX_CLOSE_PRICE)
- GTT_EXPIRY_DAYS = 5 (divergence timeout)
- RSI periods hardcoded; search `calculate_rsi_tv(series, 14)` to change

### Running in Test vs. Live

- [strategy_engine.py](../main/strategy_engine.py#L11): `TEST_MODE = True` → returns mock data, no DB writes
- For live: set `TEST_MODE = False` + ensure Kite API access_token is valid

### Bundling as EXE

PyInstaller spec: [launcher_gui.spec](../launcher_gui.spec)
- Copies `database/` and `config/` as data files
- Entry point: `launcher_gui.py`
- Build: `pyinstaller launcher_gui.spec`

## File Dependencies to Know

| File | Purpose | Key Functions |
|------|---------|---|
| [config/kite_config.py](../config/kite_config.py) | Zerodha API credentials | - |
| [main/portfolio_sync.py](../main/portfolio_sync.py) | Sync live holdings from Kite | - |
| [main/membership_bot.py](../main/membership_bot.py) | Telegram subscription management | - |
| [engines/etf_accumulator.py](../engines/etf_accumulator.py) | ETF tracking (separate from momentum/divergence) | - |
| [excel/](../excel/) | Export signals to momentum.csv / divergence.csv | - |

## Avoid These Pitfalls

- ❌ Hardcoded paths → Use [config/paths.py](../config/paths.py)
- ❌ Direct print() for critical data → Use [support/logger.py](../support/logger.py)
- ❌ Modifying DB schema without testing → Create test DB first
- ❌ Ignoring MIN_CANDLES check → Indicators need 200+ days for momentum, 120+ for divergence
- ❌ Forgetting to set `console=True` in logs when adding debug info
