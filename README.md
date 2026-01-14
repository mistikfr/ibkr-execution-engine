# Quantitative Execution Engine (The Hustler)

A robust, low-latency algorithmic trading engine designed for the Interactive Brokers (IBKR) Native API. This system implements a **Trend-Filtered Mean Reversion** strategy, optimized for reliability in unstable network conditions.

## 🚀 v2.3 Updates (Safe Mode)
* **Safety Switch:** Hard-coded `LONG_ONLY` mode to block short selling during high-volatility "Bear Trap" market conditions.
* **Soros Filter (EMA-200):** Regime detection filter that blocks buying in Bear trends and selling in Bull trends.
* **Pacing Compliance:** Polling interval increased to **20 seconds** to strictly adhere to IBKR's "15-second Identical Request" rule, preventing Error 162 Pacing Violations.

---

## ⚙️ Architecture & Reliability
Unlike standard retail bots that rely on fragile websocket streams (which often hang during packet loss), this engine uses a **Snapshot Polling Architecture**.

* **Crash-Proof Execution:** The system polls the TWS API in discrete 20-second cycles. This ensures that a dropped packet or API disconnect never freezes the main execution loop—the system simply retries on the next cycle.
* **Latency Optimization:** Contract IDs are pre-mapped (Hardcoded ConIDs) to bypass the TWS resolution server, reducing trade entry time by ~200ms.
* **Data Integrity:** Enforces a "Snapshot" model (`keepUpToDate=False`) with a 5-day buffer to ensure atomic data processing for moving averages.

## 🧠 Strategy Logic (Soros Hybrid)
The engine implements a multi-factor model combining a Macro Trend Filter with Micro Momentum Triggers:

### 1. The Trend Filter (EMA-200)
Acts as a regime filter to prevent counter-trend trading ("catching a falling knife").
* **Bull Regime:** Price > EMA-200 (Only Longs allowed).
* **Bear Regime:** Price < EMA-200 (Only Shorts allowed).

### 2. The Trigger (RSI-14)
Identifies overextended conditions within the confirmed trend.
* **LONG Entry:** RSI Dips below **30** (Oversold) while in Bull Regime.
* **SHORT Entry:** RSI Spikes above **70** (Overbought) while in Bear Regime (Currently Blocked by Safety Switch).

### 3. The "Anti-Churn" Exit (Hysteresis)
To prevent the bot from buying and selling rapidly on the same signal (Churning), the exit targets are offset from the entry targets:
* **Long Exit:** Take profit at RSI **65** (Secure the bag before the reversal).
* **Short Exit:** Take profit at RSI **35**.

## 🛠️ Configuration
* **API Connection:** Connects to local TWS/Gateway on port `7497` (Paper) or `7496` (Live).
* **Universe:** EURUSD, GBPUSD, USDJPY (Expandable via `SYMBOLS_MAP`).
* **Risk Management:** Fixed 33% equity allocation per trade.

## 📋 Requirements
* Python 3.10+
* `ib_insync`
* `pandas`
* Interactive Brokers TWS or IB Gateway

## ⚠️ Disclaimer
*This software is for educational purposes only. Algorithmic trading involves significant risk of loss.*
