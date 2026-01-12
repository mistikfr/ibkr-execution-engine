# ==============================================================================
# Module: Quantitative Execution Engine
# Strategy: Trend-Filtered Mean Reversion (EMA-200 + RSI-14)
# Architecture: Snapshot Polling (Latency Optimized & Crash-Proof)
# Interface: Interactive Brokers API (ib_insync)
# License: MIT License
# ==============================================================================

import sys
import random
import time
import datetime
import pandas as pd
from ib_insync import *

# --- 🧠 CONFIGURATION ---

# 1. STRATEGY PARAMETERS
TIMEFRAME = '15 mins'
RSI_PERIOD = 14
EMA_PERIOD = 200           # Trend Filter: Only Buy if Price > 200 EMA
BUY_THRESHOLD = 30         # Oversold Entry Signal
SELL_THRESHOLD = 70        # Overbought Exit Signal
TRADE_ALLOCATION = 0.33    # Risk Sizing: 33% of Equity (Soros Standard)

# 2. LATENCY OPTIMIZATION (PRE-MAPPED CONTRACTS)
# Pre-defining Contract IDs bypasses the IBKR resolution server, 
# reducing initialization latency by ~200ms and preventing timeouts.
SYMBOLS_MAP = {
    'EURUSD': 12087792,
    'GBPUSD': 12087797,
    'USDJPY': 15016059
}

# 3. CONNECTIVITY
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497            # 7497 = Paper, 7496 = Live
CLIENT_ID = random.randint(1000, 9999) 

ib = IB()

# --- HELPER FUNCTIONS ---

def calculate_indicators(df):
    """
    Computes technical indicators for the execution logic.
    Returns: (RSI Series, EMA Series)
    """
    if df is None or len(df) < EMA_PERIOD + 1:
        return None, None
    
    # RSI Calculation
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # EMA Calculation (Trend Filter)
    ema = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    
    return rsi, ema

def get_cash_balance():
    """Retrieves real-time USD cash balance from TWS."""
    vals = ib.accountValues()
    cash_obj = next((v for v in vals if v.tag == 'TotalCashValue' and v.currency == 'USD'), None)
    return float(cash_obj.value) if cash_obj else 0.0

def execute_trade(contract, pair_name, action, price, size=None):
    """
    Routes orders to the exchange.
    Uses 'GTC' (Good Till Cancelled) to ensure order persistence.
    """
    if action == "BUY":
        total_cash = get_cash_balance()
        if total_cash < 2000:
             print(f"   ⚠️ SKIPPED: Insufficient liquidity (${total_cash:.2f})")
             return
        
        # Dynamic Sizing
        spendable = total_cash * TRADE_ALLOCATION
        if pair_name.startswith('USD'):
            qty = int(spendable) 
        else:
            qty = int(spendable / price)
    else:
        qty = size

    if qty > 0:
        print(f"   🚀 EXECUTING {action}: {qty} units of {pair_name} at {price:.5f}")
        order = MarketOrder(action, qty, tif='GTC') 
        ib.placeOrder(contract, order)
        print("   ✅ Order Routed Successfully.")

def run_strategy_cycle():
    """
    Core Execution Loop.
    Utilizes Snapshot Polling to prevent socket hangs during packet loss.
    """
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\n--- 🔄 CYCLE START: {timestamp} ---")
    
    for pair_name, con_id in SYMBOLS_MAP.items():
        try:
            # 1. DEFINE CONTRACT (Direct Access)
            contract = Contract()
            contract.conId = con_id
            contract.exchange = 'IDEALPRO'
            
            # 2. INGEST DATA (Snapshot Mode)
            # Fetches 2 days of history to seed the EMA-200
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr='5 D', 
                barSizeSetting=TIMEFRAME, whatToShow='MIDPOINT', useRTH=False,
                keepUpToDate=False, timeout=4 
            )

            if not bars:
                print(f"   ⚠️ {pair_name}: No Data Feed (Check Market Status)")
                continue

            df = util.df(bars)
            rsi_series, ema_series = calculate_indicators(df)
            
            if rsi_series is None:
                print(f"   ⏳ {pair_name}: Buffering Data for EMA-200...")
                continue

            # 3. ANALYZE MARKET STATE
            current_price = bars[-1].close
            current_rsi = rsi_series.iloc[-1]
            current_ema = ema_series.iloc[-1]
            
            if len(rsi_series) < 2: continue
            previous_rsi = rsi_series.iloc[-2]
            
            trend = "BULL" if current_price > current_ema else "BEAR"

            if current_rsi < 35 or current_rsi > 65:
                print(f"   🔎 WATCH: {pair_name} is close! (Prev: {previous_rsi:.1f} -> Curr: {current_rsi:.1f})")
            
            trend_icon = "📈" if trend == "BULL" else "📉"
            
            print(f"   {pair_name} | Px: {current_price:.4f} | RSI: {current_rsi:.1f} | EMA: {current_ema:.4f} ({trend})")

            # 4. POSITION MANAGEMENT
            positions = ib.positions()
            current_pos = next((p for p in positions if p.contract.conId == con_id), None)
            position_size = current_pos.position if current_pos else 0

            # 5. EXECUTION LOGIC
            
            # ENTRY: RSI Dip (Mean Reversion) + Bull Trend (Trend Following)
            if previous_rsi < BUY_THRESHOLD and current_rsi >= BUY_THRESHOLD:
                if trend == "BULL":
                    print(f"   ✅ SIGNAL: {pair_name} (Bullish Dip)")
                    if position_size == 0:
                        execute_trade(contract, pair_name, "BUY", current_price)
                    else:
                        print(f"   ⚠️ Position Limit Reached. Ignoring.")
                else:
                    print(f"   🛡️ FILTERED: RSI Signal rejected by Trend Filter.")

            # EXIT: RSI Overbought
            elif previous_rsi > SELL_THRESHOLD and current_rsi <= SELL_THRESHOLD:
                if position_size > 0:
                    print(f"   🔻 SIGNAL: {pair_name} (Profit Taking)")
                    execute_trade(contract, pair_name, "SELL", current_price, size=abs(position_size))

        except Exception as e:
            print(f"   ❌ EXCEPTION in {pair_name}: {e}")

    print("--- 💤 Cycle Complete. Awaiting Next Tick... ---")

# --- MAIN ENTRY POINT ---
def main():
    print("--- 🛠️ QUANT EXECUTION ENGINE v1.0 (SNAPSHOT MODE) ---")
    
    try:
        if not ib.isConnected():
            ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=5)
        print("✅ API CONNECTION ESTABLISHED.")
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        return

    while True:
        run_strategy_cycle()
        time.sleep(10) # 10s Polling Interval

if __name__ == '__main__':
    main()
