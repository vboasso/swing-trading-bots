# Swing Trading Bots (RSI Strategy)

This repository contains automated swing trading bots for **RAVEN (DEX - PancakeSwap)** and **PI Network (CEX - Bitget)**.
These bots were developed as a pair-programming project by Valentin Boasso and his Antigravity AI Assistant.

## Architecture

The ecosystem consists of three main components:
1.  **Raven Bot (\aven_bot.py\)**: Operates on the Binance Smart Chain (BSC) via Web3. Trades RAVEN/WBNB directly on the PancakeSwap router. It acts as a sniper reading 15-minute aggregate OHLCV data directly from the DEX pool via GeckoTerminal.
2.  **Pi Bot (\pi_bot.py\)**: Operates on Bitget using the CCXT library. Trades the PI/USDT spot pair.
3.  **Daily Report (\daily_report.py\)**: A scheduled script that reads the statuses of both bots and sends a consolidated Telegram notification at 21:00 hs every day.

## Trading Strategy

Both bots utilize a purely algorithmic RSI (Relative Strength Index) strategy on a **30-minute timeframe** (or 15-minute depending on the asset's liquidity):
*   **Buy Condition**: \RSI < 25\ (Extreme Oversold / Panic). The bot uses 90% of available base currency (BNB/USDT) to buy the dip, leaving 10% for future gas/fees.
*   **Sell Condition**: \RSI > 75\ (Extreme Overbought / Euphoria) OR \Profit >= 25%\.

### The " Capital Protection\ Lock
A critical mathematical safeguard was implemented to prevent the bots from trading against their own market impact (especially on illiquid micro-caps). 
When a buy is executed, the \last_buy_price\ is persistently recorded. 
Even if the RSI falsely spikes to 80+ due to low-volume volatility, the bot **will refuse to sell** if the current market price is lower than the recorded buy price, effectively holding the asset to prevent any capital loss.

## Infrastructure
* **Language**: Python 3
* **Libraries**: \web3\, \ccxt\, \equests\
* **Alerts**: Fully integrated with Telegram Bot API for real-time trade notifications and critical execution errors.
* **Environment**: Deployed as persistent \systemd\ background services on a dedicated Linux machine.
