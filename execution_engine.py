import time
from datetime import datetime
import pandas as pd
import numpy as np
import sqlite3
import logging
from ib_insync import *

# =============================================================================
# ██╗  ██╗ ██████╗ ███╗   ██╗ █████╗ ██████╗  █████╗ ██╗   ██╗
# ██║ ██╔╝██╔═══██╗████╗  ██║██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝
# █████╔╝ ██║   ██║██╔██╗ ██║███████║██████╔╝███████║ ╚████╔╝
# ██╔═██╗ ██║   ██║██║╚██╗██║██╔══██║██╔══██╗██╔══██║  ╚██╔╝
# ██║  ██╗╚██████╔╝██║ ╚████║██║  ██║██║  ██║██║  ██║   ██║
# ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝
#  ARMORED QUANT ENGINE v14.0  |  CRUMB HUNTER  |  IBKR TWS
# =============================================================================

# ---------------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------------

TWS_HOST    = '127.0.0.1'
TWS_PORT    = 7497
CLIENT_ID   = 4448

SYMBOL_LIST      = ['GBPJPY', 'EURUSD', 'USDJPY']
TIMEFRAME        = '1 min'
FIXED_ORDER_SIZE = 15_000

# EMA periods
EMA_FAST   =  9
EMA_SLOW   = 21
EMA_TREND  = 200

# Risk filters — loosened for crumb hunting
MAX_SPREAD_PIPS = 3.0       # was 2.0; still protects against news spikes
MIN_TREND_SLOPE = 0.3       # was 1.0; allows gradual trends to pass

# Trailing stop distances per tier (price units, not pips)
# Tier 1 (crossover) gets the most room; Tier 3 (stack) is tight
TRAIL_TIERS = {
    'T1': {'JPY': 0.20, 'OTHER': 0.0020},   # crossover — full trail
    'T2': {'JPY': 0.12, 'OTHER': 0.0012},   # pullback bounce — snug
    'T3': {'JPY': 0.08, 'OTHER': 0.0008},   # EMA stack — tight crumb grab
}

# Pullback tolerance: how close price must get to fast EMA (in pips) for T2
PULLBACK_TOLERANCE_PIPS = 1.5

# Bars to wait after any trade fires (cooldown per pair)
COOLDOWN_BARS = 3

# ---------------------------------------------------------------------------
# 2. LOGGING
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('konaray.log', encoding='utf-8'),
    ]
)
log = logging.getLogger('KONARAY')

# ---------------------------------------------------------------------------
# 3. STATE
# ---------------------------------------------------------------------------

ib            = IB()
LATEST_PRICES = {}                  # pair → latest mid price (live display)
COOLDOWN      = {}                  # pair → bars remaining before next entry

# ---------------------------------------------------------------------------
# 4. DATABASE
# ---------------------------------------------------------------------------

DB_PATH = 'trading_log.db'

def setup_database() -> None:
    """Initialise the SQLite trade ledger (idempotent)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                parent_id   INTEGER PRIMARY KEY,
                child_id    INTEGER UNIQUE,
                opened_at   TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                direction   TEXT    NOT NULL,
                tier        TEXT    NOT NULL,
                entry_price REAL    NOT NULL,
                ema_fast    REAL    NOT NULL,
                ema_slow    REAL    NOT NULL,
                closed_at   TEXT,
                exit_price  REAL,
                pnl_pips    REAL
            )
        ''')
        conn.commit()
    log.info("Database ready: %s", DB_PATH)


def log_entry(parent_id: int, child_id: int, symbol: str, direction: str,
              tier: str, entry_price: float, ema_fast: float, ema_slow: float) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT OR IGNORE INTO trades
                (parent_id, child_id, opened_at, symbol, direction, tier,
                 entry_price, ema_fast, ema_slow)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (parent_id, child_id, _now(), symbol, direction, tier,
              entry_price, ema_fast, ema_slow))
        conn.commit()


def log_exit(child_id: int, exit_price: float, pnl_pips: float) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            UPDATE trades
            SET closed_at = ?, exit_price = ?, pnl_pips = ?
            WHERE child_id = ?
        ''', (_now(), exit_price, pnl_pips, child_id))
        conn.commit()

# ---------------------------------------------------------------------------
# 5. HELPERS
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _is_jpy(identifier: str) -> bool:
    return 'JPY' in identifier.upper()

def _pip_multiplier(identifier: str) -> int:
    return 100 if _is_jpy(identifier) else 10_000

def _pair(contract) -> str:
    return f"{contract.symbol}{contract.currency}"

def _trail(tier: str, pair: str) -> float:
    key = 'JPY' if _is_jpy(pair) else 'OTHER'
    return TRAIL_TIERS[tier][key]

# ---------------------------------------------------------------------------
# 6. SAFETY CHECKS
# ---------------------------------------------------------------------------

def has_pending_order(contract) -> bool:
    for trade in ib.openTrades():
        c = trade.contract
        if (c.symbol == contract.symbol
                and c.currency == contract.currency
                and not trade.isDone()):
            return True
    return False


def get_open_position(contract) -> float:
    for p in ib.positions():
        if (p.contract.symbol == contract.symbol
                and p.contract.currency == contract.currency):
            return p.position
    return 0.0


def _check_spread(contract) -> bool:
    ticker = ib.ticker(contract)
    pair   = _pair(contract)
    mult   = _pip_multiplier(pair)

    if not ticker or ticker.bid <= 0 or ticker.ask <= 0:
        log.warning("⏳ No live bid/ask for %s — skipping bar", pair)
        return False

    spread_pips = (ticker.ask - ticker.bid) * mult
    if spread_pips > MAX_SPREAD_PIPS:
        log.warning("⚠️  Spread kill-switch %s | %.1f pips", pair, spread_pips)
        return False

    log.debug("   Spread %s: %.2f pips ✓", pair, spread_pips)
    return True


def _check_trend_slope(trend_series: pd.Series, pair: str) -> bool:
    if len(trend_series) < 5:
        return True
    slope = abs(trend_series.iloc[-1] - trend_series.iloc[-5]) * _pip_multiplier(pair)
    if slope < MIN_TREND_SLOPE:
        log.info("🛑 Flat market %s | slope %.3f pips", pair, slope)
        return False
    log.debug("   Slope %s: %.3f pips ✓", pair, slope)
    return True

# ---------------------------------------------------------------------------
# 7. INDICATORS
# ---------------------------------------------------------------------------

def calculate_indicators(df: pd.DataFrame) -> dict:
    """
    Computes EMAs and RSI. Returns a dict of named values for clean access.
    All series are computed over the full dataframe; callers read iloc[-1] etc.
    """
    close = df['close']

    fast  = close.ewm(span=EMA_FAST,  adjust=False).mean()
    slow  = close.ewm(span=EMA_SLOW,  adjust=False).mean()
    trend = close.ewm(span=EMA_TREND, adjust=False).mean()

    # RSI-14 — used to avoid entries into overbought/oversold extremes
    delta   = close.diff()
    gain    = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss    = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rs      = gain / loss.replace(0, np.nan)
    rsi     = 100 - (100 / (1 + rs))

    return {
        'fast_now':  fast.iloc[-1],
        'fast_prev': fast.iloc[-2],
        'slow_now':  slow.iloc[-1],
        'slow_prev': slow.iloc[-2],
        'trend_now': trend.iloc[-1],
        'trend_s':   trend,              # full series for slope check
        'rsi':       rsi.iloc[-1],
        'price':     close.iloc[-1],
    }

# ---------------------------------------------------------------------------
# 8. SIGNAL ENGINE  (the crumb detector)
# ---------------------------------------------------------------------------

def evaluate_signal(ind: dict, pair: str) -> tuple[str | None, str | None]:
    """
    Returns (direction, tier) or (None, None) if no signal.

    Three tiers, checked in priority order:
      T1 — Classic EMA crossover aligned with trend (strongest conviction)
      T2 — Pullback to fast EMA inside an established trend (crumb bounce)
      T3 — Full EMA stack alignment, no cross needed (mid-trend continuation)

    RSI guard: skip any long entry above 70, any short entry below 30.
    This avoids chasing at momentum extremes.
    """
    fast_now   = ind['fast_now']
    fast_prev  = ind['fast_prev']
    slow_now   = ind['slow_now']
    slow_prev  = ind['slow_prev']
    trend_now  = ind['trend_now']
    price      = ind['price']
    rsi        = ind['rsi']
    mult       = _pip_multiplier(pair)

    # ── Tier 1: Crossover ──────────────────────────────────────────────────
    crossed_up   = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_up and price > trend_now and rsi < 70:
        return 'BUY', 'T1'
    if crossed_down and price < trend_now and rsi > 30:
        return 'SELL', 'T1'

    # ── Tier 2: Pullback bounce ────────────────────────────────────────────
    # Uptrend established: fast > slow > trend. Price dips near fast EMA then
    # closes back above it. A classic "kiss and go" crumb.
    pullback_zone = PULLBACK_TOLERANCE_PIPS / mult

    in_uptrend   = fast_now > slow_now > trend_now
    in_downtrend = fast_now < slow_now < trend_now

    # For a BUY bounce: previous bar touched near or below fast EMA, current
    # bar closes above it — and RSI has room to run (not overbought)
    if in_uptrend and rsi < 65:
        prev_close = ind.get('prev_price', price)   # fallback safe
        near_fast  = abs(prev_close - fast_prev) <= pullback_zone
        reclaimed  = price > fast_now
        if near_fast and reclaimed:
            return 'BUY', 'T2'

    if in_downtrend and rsi > 35:
        prev_close = ind.get('prev_price', price)
        near_fast  = abs(prev_close - fast_prev) <= pullback_zone
        reclaimed  = price < fast_now
        if near_fast and reclaimed:
            return 'SELL', 'T2'

    # ── Tier 3: EMA stack continuation ────────────────────────────────────
    # All three EMAs in order, fast EMA itself is sloping, price on the right
    # side. No crossover needed — we're already in the move. Tight trail.
    fast_sloping_up   = fast_now > fast_prev
    fast_sloping_down = fast_now < fast_prev

    if in_uptrend and fast_sloping_up and price > fast_now and rsi < 60:
        return 'BUY', 'T3'
    if in_downtrend and fast_sloping_down and price < fast_now and rsi > 40:
        return 'SELL', 'T3'

    return None, None

# ---------------------------------------------------------------------------
# 9. ORDER EXECUTION
# ---------------------------------------------------------------------------

def place_trade(contract, direction: str, tier: str, price: float,
                ema_fast: float, ema_slow: float) -> None:
    pair       = _pair(contract)
    trail_dist = _trail(tier, pair)
    exit_side  = 'SELL' if direction == 'BUY' else 'BUY'

    parent          = LimitOrder(direction, FIXED_ORDER_SIZE, price)
    parent.orderId  = ib.client.getReqId()
    parent.tif      = 'GTC'
    parent.transmit = False

    trail = Order(
        action        = exit_side,
        orderType     = 'TRAIL',
        totalQuantity = FIXED_ORDER_SIZE,
        auxPrice      = trail_dist,
        parentId      = parent.orderId,
        tif           = 'GTC',
        transmit      = True,
    )
    trail.orderId = ib.client.getReqId()

    ib.placeOrder(contract, parent)
    ib.placeOrder(contract, trail)

    log_entry(parent.orderId, trail.orderId, pair, direction,
              tier, price, ema_fast, ema_slow)

    COOLDOWN[pair] = COOLDOWN_BARS

    log.info("🚀 [%s] %s %s | Entry: %.5f | Trail: %.5f",
             tier, direction, pair, price, trail_dist)

# ---------------------------------------------------------------------------
# 10. BAR CALLBACK
# ---------------------------------------------------------------------------

# Store previous close per pair for T2 pullback detection
_PREV_CLOSE: dict[str, float] = {}

def on_bar_update(bars, hasNewBar: bool) -> None:
    contract = bars.contract
    pair     = _pair(contract)
    df       = util.df(bars)
    price    = df.iloc[-1]['close']

    # Live tick display
    if not hasNewBar:
        LATEST_PRICES[pair] = price
        ticker_str = ' | '.join(f"{k}: {v:.5f}" for k, v in LATEST_PRICES.items())
        print(f"   📡 {ticker_str}" + ' ' * 12, end='\r')
        return

    # ── New bar closed ──
    ind = calculate_indicators(df)
    # Inject previous close for T2 pullback check
    ind['prev_price'] = _PREV_CLOSE.get(pair, ind['price'])
    _PREV_CLOSE[pair] = price

    log.info("📊 [BAR] %s | Price: %.5f | EMA9: %.5f | EMA21: %.5f | EMA200: %.5f | RSI: %.1f",
             pair, price,
             ind['fast_now'], ind['slow_now'], ind['trend_now'], ind['rsi'])

    # ── Cooldown ──
    if COOLDOWN.get(pair, 0) > 0:
        COOLDOWN[pair] -= 1
        log.info("   ⏸  Cooldown %s — %d bars remaining", pair, COOLDOWN[pair])
        return

    # ── Hard guards (unchanged) ──
    if has_pending_order(contract):
        return
    if get_open_position(contract) != 0:
        return
    if not _check_spread(contract):
        return
    if not _check_trend_slope(ind['trend_s'], pair):
        return

    # ── Signal ──
    direction, tier = evaluate_signal(ind, pair)

    if direction and tier:
        log.info("✅ [%s] %s signal on %s", tier, direction, pair)
        place_trade(contract, direction, tier, price,
                    ind['fast_now'], ind['slow_now'])
    else:
        log.debug("   No signal on %s this bar", pair)

# ---------------------------------------------------------------------------
# 11. FILL CALLBACK
# ---------------------------------------------------------------------------

def on_fill(trade, fill) -> None:
    order_id   = fill.execution.orderId
    fill_price = fill.execution.price

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            'SELECT direction, entry_price, symbol, tier FROM trades WHERE child_id = ?',
            (order_id,)
        ).fetchone()

    if not row:
        return

    direction, entry_price, symbol, tier = row
    mult     = _pip_multiplier(symbol)
    pnl_pips = (
        (fill_price - entry_price) * mult if direction == 'BUY'
        else (entry_price - fill_price) * mult
    )

    log_exit(order_id, fill_price, pnl_pips)
    log.info("💰 [CLOSED][%s] %s | PnL: %+.1f pips | Exit: %.5f",
             tier, symbol, pnl_pips, fill_price)

# ---------------------------------------------------------------------------
# 12. ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    setup_database()

    ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
    log.info("✅ Connected — Konaray v14.0 Crumb Hunter")
    log.info("   Tiers active: T1 (crossover) | T2 (pullback) | T3 (stack)")
    log.info("   Spread cap: %.1f pips | Slope min: %.2f pips | Cooldown: %d bars",
             MAX_SPREAD_PIPS, MIN_TREND_SLOPE, COOLDOWN_BARS)

    ib.execDetailsEvent += on_fill

    for symbol in SYMBOL_LIST:
        contract = Forex(symbol)
        ib.qualifyContracts(contract)
        ib.reqMktData(contract, '', False, False)

        log.info("⏳ Loading history for %s …", symbol)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime    = '',
            durationStr    = '1 D',
            barSizeSetting = TIMEFRAME,
            whatToShow     = 'MIDPOINT',
            useRTH         = False,
            keepUpToDate   = True,
            timeout        = 60,
        )
        bars.updateEvent += on_bar_update
        ib.sleep(2)

    log.info("🟢 Engine live — hunting crumbs on %s", ', '.join(SYMBOL_LIST))
    ib.run()
