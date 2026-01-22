# Quantitative Execution Engine (The Hustler)

A robust, low-latency algorithmic trading engine designed for the Interactive Brokers (IBKR) Native API.

## 🚀 v2.9 Updates (Loop Protection)
* **Loop Guard:** Implemented `has_open_order` checks to prevent duplicate orders during API latency spikes.
* **Trend Buffer (0.1%):** Requires price to be significantly above the EMA to confirm a Bull Trend, preventing "Weak Support" entries.
* **Pacing Compliance:** Polling interval set to **20 seconds** to strictly adhere to IBKR's "15-second Identical Request" rule.
* **Silent Mode:** Removed external webhook dependencies for a lightweight, console-only footprint.

---

## ⚙️ Architecture
* **Strategy:** Mean Reversion (RSI 14) filtered by Trend (EMA 200).
* **Execution:** Snapshot Polling (20s interval) for crash-proof uptime.
* **Safety:** Hard-coded `LONG_ONLY` mode to block Short Selling risks.

## 🛠️ Configuration
* **API Connection:** Connects to local TWS/Gateway on port `7497` (Paper) or `7496` (Live).
* **Universe:** EURUSD, GBPUSD, USDJPY (Expandable via `SYMBOLS_MAP`).
* **Risk Management:** Fixed 33% equity allocation per trade.

## 📋 Requirements
* Python 3.10+
* `ib_insync`
* `pandas`

## ⚠️ Disclaimer
*This software is for educational purposes only. Algorithmic trading involves significant risk of loss.*
