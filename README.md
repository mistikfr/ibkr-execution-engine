# Quantitative Execution Engine (Python/IBKR)

A robust, low-latency algorithmic trading engine designed for the Interactive Brokers (IBKR) Native API. This system implements a bi-directional **Trend-Filtered Mean Reversion** strategy, optimized for reliability in unstable network conditions.

## 🚀 v2.1 Updates (Latest Release)
* **Bi-Directional Execution:** Now capable of Short Selling (profiting from drops) as well as Long Buying.
* **Anti-Churn Logic:** Implemented a hysteresis gap (Entry at 30/70, Exit at 35/65) to prevent "signal flickering" and excessive commission costs.
* **Compliance:** Optimized for Spot FX execution, compatible with Swap-Free / Islamic accounts.

---

## ⚙️ Architecture & Reliability
Unlike standard retail bots that rely on fragile websocket streams (which often hang during packet loss), this engine uses a **Snapshot Polling Architecture**.

* **Crash-Proof Execution:** The system polls the TWS API in discrete 10-second cycles. This ensures that a dropped packet or API disconnect never freezes the main execution loop—the system simply retries on the next cycle.
* **Latency Optimization:** Contract IDs are pre-mapped (Hardcoded ConIDs) to bypass the TWS resolution server, reducing trade entry time by ~200ms and eliminating "Contract Ambiguity" errors.
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
* **SHORT Entry:** RSI Spikes above **70** (Overbought) while in Bear Regime.

### 3. The "Anti-Churn" Exit (Hysteresis)
To prevent the bot from buying and selling rapidly on the same signal (Churning), the exit targets are offset from the entry targets:
* **Long Exit:** Take profit at RSI **65** (Secure the bag before the reversal).
* **Short Exit:** Take profit at RSI **35**.
* *Result:* This creates a volatility gap that forces the bot to hold for the "meat" of the move rather than scalping noise.

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
