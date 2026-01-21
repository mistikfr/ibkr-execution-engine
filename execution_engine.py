# ==============================================================================
# Module: Quantitative Execution Engine (The Hustler v2.3)
# Strategy: Trend-Filtered Mean Reversion + Panic Override Protocol
# Architecture: Snapshot Polling (Latency Optimized)
# Interface: Interactive Brokers API (ib_insync)
# ==============================================================================

import sys
import random
import time
import datetime
import pandas as pd
from ib_insync import *

# --- 🧠 CONFIGURATION: THE HUSTLER v2.8 (Silent Pro) ---

# 1. STRATEGY SETTINGS
TIMEFRAME = '15 mins'
RSI_PERIOD = 14
EMA_PERIOD = 200           # Soros Filter
BUY_ENTRY = 30             # Enter Long below this
SELL_ENTRY = 70            # Enter Short above this
EXIT_LONG_TARGET = 65      # Take Profit on Longs
EXIT_SHORT_TARGET = 35     # Take Profit on Shorts
TRADE_ALLOCATION = 0.33    # 33% of Equity

# 2. SAFETY SWITCHES
TRADING_MODE = 'LONG_ONLY' 

# Trend Buffer: 0.001 = 0.1% (approx 10-15 pips).
# Requires Price to be > EMA + 0.1% to confirm a Strong Bull trend.
TREND_BUFFER_PCT = 0.001 

# 3. INSTRUMENT MAP
SYMBOLS_MAP = {
    'EURUSD': 12087792,
    'GBPUSD': 12087797,
    'USDJPY': 15016059
}

# 4. CONNECTIVITY
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497            
CLIENT_ID = random.randint(1000, 9999) 

ib = IB()

# --- HELPER FUNCTIONS ---

def calculate_indicators(df):
    """Calculates RSI and EMA-200."""
    if df is None or len(df) < EMA_PERIOD + 1:
        return None, None
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    ema = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    return rsi, ema

def get_cash_balance():
    vals = ib.accountValues()
    cash_obj = next((v for v in vals if v.tag == 'TotalCashValue' and v.currency == 'USD'), None)
    return float(cash_obj.value) if cash_obj else 0.0

def execute_trade(contract, pair_name, action, price, size=None):
    qty = 0
    
    # 1. ENTRY LOGIC
    if size is None:
        total_cash = get_cash_balance()
        if total_cash < 1000:
             print(f"   ⚠️ SKIPPED: Low Cash (${total_cash:.2f})")
             return
        spendable = total_cash * TRADE_ALLOCATION
        if pair_name.startswith('USD'): qty = int(spendable) 
        else: qty = int(spendable / price)
    
    # 2. EXIT LOGIC
    else:
        qty = size

    if qty > 0:
        print(f"   🚀 EXECUTING {action}: {qty} units of {pair_name} at {price:.5f}")
        order = MarketOrder(action, qty, tif='GTC') 
        ib.placeOrder(contract, order)
        print("   ✅ Order Sent.")

def get_trade_signal(rsi_prev, rsi_curr, current_price, current_ema, current_pos_size):
    """Decides based on RSI, EMA Trend, and Safety Buffer."""
    signal = "HOLD"
    
    # Determine Strict Trend with Buffer
    strong_bull_line = current_ema * (1 + TREND_BUFFER_PCT)
    strong_bear_line = current_ema * (1 - TREND_BUFFER_PCT)

    is_strong_bull = current_price > strong_bull_line
    is_strong_bear = current_price < strong_bear_line
    
    # --- LOGIC 1: ENTRIES ---
    if current_pos_size == 0:
        # LONG ENTRY
        if rsi_prev < BUY_ENTRY and rsi_curr >= BUY_ENTRY:
            # SCENARIO A: Strong Trend (Buy the Dip)
            if is_strong_bull:
                signal = "ENTRY_LONG"
            # SCENARIO B: Panic Crash (Buy the Blood)
            elif rsi_prev < 15:
                signal = "ENTRY_LONG"
                print("   ⚠️ PANIC OVERRIDE: Buying the crash (RSI < 15)")
            # SCENARIO C: Weak Trend (The "Hugging EMA" Trap)
            elif current_price > current_ema and not is_strong_bull:
                print(f"   🛡️ Buffer Protect: Price too close to EMA ({current_price:.4f} vs {current_ema:.4f})")
            else:
                print("   🛡️ Filtered: Buy signal ignored (Bear Trend)")
        
        # SHORT ENTRY (Blocked by LONG_ONLY mode usually)
        elif rsi_prev > SELL_ENTRY and rsi_curr <= SELL_ENTRY:
            if TRADING_MODE == 'LONG_ONLY': pass 
            elif is_strong_bear or rsi_prev > 85: signal = "ENTRY_SHORT"
            else: print("   🛡️ Filtered: Short signal ignored (Bull Trend)")

    # --- LOGIC 2: EXITS ---
    else:
        if current_pos_size > 0: 
            if rsi_curr >= EXIT_LONG_TARGET:
                signal = "EXIT_LONG"
        elif current_pos_size < 0:
            if rsi_curr <= EXIT_SHORT_TARGET:
                signal = "EXIT_SHORT"
                
    return signal

def run_strategy_cycle():
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"\n--- 🔄 CYCLE START: {timestamp} ---")
    
    for pair_name, con_id in SYMBOLS_MAP.items():
        try:
            contract = Contract()
            contract.conId = con_id
            contract.exchange = 'IDEALPRO'
            
            bars = ib.reqHistoricalData(
                contract, endDateTime='', durationStr='5 D', 
                barSizeSetting=TIMEFRAME, whatToShow='MIDPOINT', useRTH=False,
                keepUpToDate=False, timeout=10 
            )

            if not bars:
                print(f"   ⚠️ {pair_name}: No Data")
                continue

            df = util.df(bars)
            rsi_series, ema_series = calculate_indicators(df)
            
            if rsi_series is None or len(rsi_series) < 2:
                continue

            current_price = bars[-1].close
            current_rsi = rsi_series.iloc[-1]
            previous_rsi = rsi_series.iloc[-2]
            current_ema = ema_series.iloc[-1]
            
            trend_icon = "📈" if current_price > current_ema else "📉"
            
            print(f"   {pair_name} | Px:{current_price:.4f} | RSI:{current_rsi:.1f} | EMA:{current_ema:.4f} {trend_icon}")

            positions = ib.positions()
            current_pos = next((p for p in positions if p.contract.conId == con_id), None)
            position_size = current_pos.position if current_pos else 0

            signal = get_trade_signal(previous_rsi, current_rsi, current_price, current_ema, position_size)

            if signal == "ENTRY_LONG":
                print(f"   ✅ GOING LONG: {pair_name}")
                execute_trade(contract, pair_name, "BUY", current_price, size=None)

            elif signal == "ENTRY_SHORT":
                print(f"   ✅ GOING SHORT: {pair_name}")
                execute_trade(contract, pair_name, "SELL", current_price, size=None)

            elif signal == "EXIT_LONG":
                print(f"   💰 TAKE PROFIT: Closing Long on {pair_name} (RSI hit {EXIT_LONG_TARGET})")
                execute_trade(contract, pair_name, "SELL", current_price, size=abs(position_size))

            elif signal == "EXIT_SHORT":
                print(f"   💰 TAKE PROFIT: Closing Short on {pair_name} (RSI hit {EXIT_SHORT_TARGET})")
                execute_trade(contract, pair_name, "BUY", current_price, size=abs(position_size))

        except Exception as e:
            print(f"   ❌ ERROR {pair_name}: {e}")

    print("--- 💤 Cycle Complete. Sleeping 20s... ---")

def main():
    print("--- 🛠️ THE HUSTLER v2.8: SILENT MODE ---")
    try:
        if not ib.isConnected():
            ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID, timeout=5)
        print("✅ CONNECTED to TWS.")
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        return

    while True:
        run_strategy_cycle()
        time.sleep(10) 

if __name__ == '__main__':
    main()
