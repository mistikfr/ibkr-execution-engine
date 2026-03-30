# Quantitative Execution Engine (The Hustler) — Armored Quant Engine

A multi-tier algorithmic FX trading engine for Interactive Brokers (IBKR TWS), built around EMA momentum with a crumb-hunting signal stack.

---

## Architecture

- **Signal engine:** Three-tier EMA momentum system (crossover → pullback bounce → stack continuation)
- **Execution:** Event-driven bar callbacks via `ib_insync` `keepUpToDate` — no polling loop
- **Exit:** Trailing stop orders managed natively by IBKR, no bot-side monitoring needed
- **Ledger:** SQLite trade log with entry, exit, PnL per trade

---

## Signal Tiers

| Tier | Name | Condition | Trail |
|------|------|-----------|-------|
| T1 | Crossover | EMA 9 crosses EMA 21, aligned with EMA 200 | Full |
| T2 | Pullback bounce | Price kisses EMA 9 inside an established trend and reclaims it | Snug |
| T3 | EMA stack | All three EMAs ordered, fast EMA sloping, price on correct side | Tight |

RSI-14 guard prevents entries into overbought (>70 long) or oversold (<30 short) conditions.

---

## Risk Filters

| Filter | Value | Purpose |
|--------|-------|---------|
| Max spread | 3.0 pips | Blocks news spikes and illiquid sessions |
| Min 200-EMA slope | 0.3 pips / 5 bars | Blocks genuinely flat, choppy markets |
| Post-trade cooldown | 3 bars | Prevents re-entry into the same exhausted move |

---

## Configuration

All tunable parameters are at the top of `execution_engine.py`:

```python
SYMBOL_LIST      = ['GBPJPY', 'EURUSD', 'USDJPY']
TIMEFRAME        = '1 min'
FIXED_ORDER_SIZE = 20_000      # units — stay at or above IBKR IdealPro 20K minimum

EMA_FAST   =  9
EMA_SLOW   = 21
EMA_TREND  = 200

MAX_SPREAD_PIPS = 3.0
MIN_TREND_SLOPE = 0.3
COOLDOWN_BARS   = 3
```

---

## Setup

**Requirements:** Python 3.10+, IBKR TWS or IB Gateway running locally.

```bash
pip install -r requirements.txt
```

Connect TWS/Gateway on:
- Port `7497` — Paper trading (default)
- Port `7496` — Live trading

```bash
python execution_engine.py
```

---

## Trade Log

All trades are written to `trading_log.db` (SQLite). Schema:

| Column | Description |
|--------|-------------|
| `parent_id` | IBKR order ID of the entry limit order |
| `child_id` | IBKR order ID of the trailing stop |
| `opened_at` | Entry timestamp |
| `symbol` | Currency pair |
| `direction` | BUY or SELL |
| `tier` | Signal tier (T1 / T2 / T3) |
| `entry_price` | Limit price at entry |
| `ema_fast` / `ema_slow` | EMA values at signal time |
| `closed_at` | Exit timestamp (populated on fill) |
| `exit_price` | Fill price of trailing stop |
| `pnl_pips` | Realised PnL in pips |

---

## Notes

- Order size must be ≥ 20,000 units to route via IBKR IdealPro (best interbank pricing). Below this, orders route as odd lots with wider effective fills.
- `trading_log.db` is gitignored — keep your trade history local.
- Live trading requires enabling API access in TWS: *Edit → Global Configuration → API → Settings → Enable ActiveX and Socket Clients*.

---

## Disclaimer

This software is for educational purposes only. Algorithmic trading involves significant risk of loss. Past performance of any strategy does not guarantee future results.

---

MIT License — Copyright (c) 2026 Mustafa
