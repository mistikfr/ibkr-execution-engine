# Quantitative Execution Engine (Python/IBKR)

A robust, low-latency trading execution engine designed for the Interactive Brokers (IBKR) TWS API. This system implements a hybrid mean-reversion/trend-following strategy with specific architectural choices made for reliability in unstable network conditions.

## ⚙️ Architecture & Reliability
Unlike standard retail bots that rely on fragile websocket streams (which often hang during packet loss), this engine uses a **Snapshot Polling Architecture**.

* **Crash-Proof Execution:** The system polls the TWS API in discrete 10-second cycles. This ensures that a dropped packet or API disconnect never freezes the main execution loop—the system simply retries on the next cycle.
* **Latency Optimization:** Contract IDs are pre-mapped (Hardcoded ConIDs) to bypass the TWS resolution server, reducing trade entry time by ~200ms and eliminating "Contract Ambiguity" errors.
* **Data Integrity:** Enforces a "Snapshot" model (`keepUpToDate=False`) to ensure atomic data processing, preventing race conditions common in async streaming.

## 🧠 Strategy Logic (Soros Hybrid)
The engine implements a multi-factor model combining Trend Filtering with Mean Reversion:

1.  **The Trend Filter (EMA-200):**
    * Logic: `IF Price > EMA_200 THEN Market = BULL`
    * Purpose: Prevents "catching a falling knife." The bot will reject all Buy signals if the long-term trend is Bearish.

2.  **The Trigger (RSI-14):**
    * Logic: `IF RSI Crosses Above 30 AND Market = BULL THEN Buy`
    * Purpose: Identifies short-term oversold conditions (dips) within a confirmed uptrend.

3.  **Risk Management:**
    * Allocation: Fixed 33% equity allocation per trade.
    * Exit: Dynamic profit taking on RSI overbought conditions (>70).

## 🛠️ Configuration
* **API Connection:** Connects to local TWS/Gateway on port `7497` (Paper) or `7496` (Live).
* **Universe:** EURUSD, GBPUSD, USDJPY (Expandable via `SYMBOLS_MAP`).

## 📋 Requirements
* Python 3.9+
* `ib_insync`
* `pandas`
* Interactive Brokers TWS or IB Gateway
