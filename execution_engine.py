# ==============================================================================
# Module: Quantitative Execution Engine (The Hustler v2.3)
# Strategy: Long-Only Trend-Filtered Mean Reversion (EMA-200 + RSI-14)
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
EMA_PERIOD = 200           # Soros Filter: Trend direction detector
BUY_ENTRY = 30             # Enter Long below this
SELL_ENTRY = 70            # Enter Short above this
EXIT_LONG_TARGET = 65      # Take Profit on Longs here 
EXIT_SHORT_TARGET = 35     # Take Profit on Shorts here
TRADE_ALLOCATION = 0.33    # Risk Sizing: 33% of Equity

# 2. SAFETY SWITCH
# 'BOTH'      = Allow Buys and Sells (Risky)
# 'LONG_ONLY' = Allow Buys only. Block all Shorts.
TRADING_MODE = 'LONG_ONLY' 

# 3. LATENCY OPTIMIZATION (PRE-MAPPED CONTRACTS)
# Pre-defining Contract IDs bypasses the IBKR resolution server.
SYMBOLS_MAP = {
    'EURUSD': 12087792,
    'GBPUSD': 12087797,
    'USDJPY': 15016059
}

# 4. CONNECTIVITY
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
    If 'size' is None -> Calculates 33% Entry Size. 
    If 'size' is Value -> Exits that specific amount.
    """
    qty = 0
    
    # 1. ENTRY LOGIC (Calculate Size)
    if size is None:
        total_cash = get_cash_balance()
        if total_cash < 1000:
             print(f"   ⚠️ SKIPPED: Insufficient liquidity (${total_cash:.2f})")
             return
        
        # Dynamic Sizing: 33% of account
        spendable = total_cash * TRADE_ALLOCATION
        
        if pair_name.startswith('USD'):
            qty = int(spendable) 
        else:
            qty = int(spendable / price)
    
    # 2. EXIT LOGIC (Use Existing Size)
    else:
        qty = size

    if qty > 0:
        print(f"   🚀 EXECUTING {action}: {qty} units of {pair_name} at {price:.5f}")
        order = MarketOrder(action, qty, tif='GTC') 
        ib.placeOrder(contract, order)
        print("   ✅ Order Routed Successfully.")

def get_trade_signal(rsi_prev, rsi_curr, trend, current_pos_size):
    """
    ENTRIES: Strict (30 / 70) with Safety Switch
    EXITS:   Easier (35 / 65)
    """
    signal = "HOLD"
    
    # --- LOGIC 1: ENTRIES (Open New Positions) ---
    if current_pos_size == 0:
        
        # LONG ENTRY: RSI Crosses UP past 30 + BULL Trend
        if rsi_prev < BUY_ENTRY and rsi_curr >= BUY_ENTRY:
            if trend == "BULL":
                signal = "ENTRY_LONG"
            else:
                print("   🛡️ Filtered: Buy signal ignored (Bear Trend)")
        
        # SHORT ENTRY: RSI Crosses DOWN past 70
        elif rsi_prev > SELL_ENTRY and rsi_curr <= SELL_ENTRY:
            # --- THE SAFETY SWITCH FIX ---
            if TRADING_MODE == 'LONG_ONLY':
                print("   🛡️ SAFETY SWITCH: Short Signal Blocked (Long Only Mode)")
            elif trend == "BEAR":
                signal = "ENTRY_SHORT"
            else:
                print("   🛡️ Filtered: Short signal ignored (Bull Trend)")

    # --- LOGIC 2: EXITS (Close Existing Positions) ---
    else:
        # EXIT LONG: Take profit at 65 (Don't wait for 70)
        if current_pos_size > 0: 
            if rsi_curr >= EXIT_LONG_TARGET:
                signal = "EXIT_LONG"
        
        # EXIT SHORT: Take profit at 35 (Don't wait for 30)
        elif current_pos_size < 0:
            if rsi_curr <= EXIT_SHORT_TARGET:
                signal = "EXIT_SHORT"
                
    return signal

def run_strategy_cycle():
    """
    Core Execution Loop.
    Utilizes Snapshot Polling with Pacing Protection.
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
            # Timeout set to 10s to prevent hanging
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr='5 D', 
                barSizeSetting=TIMEFRAME, whatToShow='MIDPOINT', useRTH=False,
                keepUpToDate=False, timeout=10 
            )

            if not bars:
                print(f"   ⚠️ {pair_name}: No Data Feed (Check Market Status)")
                continue

            df = util.df(bars)
            rsi_series, ema_series = calculate_indicators(df)
            
            if rsi_series is None or len(rsi_series) < 2:
                print(f"   ⏳ {pair_name}: Buffering Data for EMA-200...")
                continue

            # 3. ANALYZE MARKET STATE
            current_price = bars[-1].close
            current_rsi = rsi_series.iloc[-1]
            previous_rsi = rsi_series.iloc[-2]
            current_ema = ema_series.iloc[-1]
            
            trend = "BULL" if current_price > current_ema else "BEAR"
            trend_icon = "📈" if trend == "BULL" else "📉"
            
            print(f"   {pair_name} | Px: {current_price:.4f} | RSI: {current_rsi:.1f} | EMA: {current_ema:.4f} {trend_icon}")

            # 4. POSITION MANAGEMENT
            positions = ib.positions()
            current_pos = next((p for p in positions if p.contract.conId == con_id), None)
            position_size = current_pos.position if current_pos else 0

            # 5. EXECUTION LOGIC
            signal = get_trade_signal(previous_rsi, current_rsi, trend, position_size)

            if signal == "ENTRY_LONG":
                print(f"   ✅ SIGNAL: {pair_name} (Bullish Dip)")
                execute_trade(contract, pair_name, "BUY", current_price, size=None)

            elif signal == "ENTRY_SHORT":
                print(f"   ✅ SIGNAL: {pair_name} (Bearish Peak)")
                execute_trade(contract, pair_name, "SELL", current_price, size=None)

            elif signal == "EXIT_LONG":
                print(f"   🔻 SIGNAL: {pair_name} (Take Profit: RSI > {EXIT_LONG_TARGET})")
                execute_trade(contract, pair_name, "SELL", current_price, size=abs(position_size))

            elif signal == "EXIT_SHORT":
                print(f"   🔻 SIGNAL: {pair_name} (Take Profit: RSI < {EXIT_SHORT_TARGET})")
                execute_trade(contract, pair_name, "BUY", current_price, size=abs(position_size))

        except Exception as e:
            print(f"   ❌ EXCEPTION in {pair_name}: {e}")

    # FIX: Sleep 20s to strictly obey IBKR "15s Identical Request" Pacing Rule
    print("--- 💤 Cycle Complete. Sleeping 20s... ---")

# --- MAIN ENTRY POINT ---
def main():
    print("--- 🛠️ QUANT EXECUTION ENGINE v2.3 (LONG ONLY MODE) ---")
    
    try:
        if not ib.isConnected():
            ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=5)
        print("✅ API CONNECTION ESTABLISHED.")
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        return

    while True:
        run_strategy_cycle()
        time.sleep(20) # 20s Polling Interval

if __name__ == '__main__':
    main()
