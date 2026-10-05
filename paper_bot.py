import os
import time
import json
import csv
import logging
import requests
import ccxt
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("/home/vale/.env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

STATE_FILE = "/home/vale/paper_bot_state.json"
HISTORY_FILE = "/home/vale/paper_bot_history.csv"
TRADES_FILE = "/home/vale/paper_trades.csv"

# Simulated Pairs Configuration
# We track two top high-volatility & high-liquidity assets: SUI and PEPE
PAIRS = {
    "SUI/USDT": {
        "name": "SUI",
        "initial_usdt": 200.0,
        "take_profit_pct": 18.0,  # 18% swing target
        "rsi_buy": 25.0,
        "rsi_sell": 75.0
    },
    "PEPE/USDT": {
        "name": "PEPE",
        "initial_usdt": 200.0,
        "take_profit_pct": 20.0,  # 20% swing target for meme volatility
        "rsi_buy": 25.0,
        "rsi_sell": 75.0
    }
}

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Default initial state
    state = {}
    for symbol, cfg in PAIRS.items():
        state[symbol] = {
            "usdt_balance": cfg["initial_usdt"],
            "token_balance": 0.0,
            "buy_price": 0.0,
            "state": "WAITING_BUY",
            "trades_count": 0,
            "realized_pnl_usd": 0.0
        }
    save_state(state)
    return state

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving paper state: {e}")

def log_trade(symbol, action, price, amount, usdt_value, profit_pct=0.0):
    file_exists = os.path.isfile(TRADES_FILE)
    try:
        with open(TRADES_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'symbol', 'action', 'price', 'amount', 'usdt_value', 'profit_pct'])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol, action, f"{price:.8f}", f"{amount:.4f}", f"{usdt_value:.2f}", f"{profit_pct:.2f}%"
            ])
    except Exception as e:
        logging.error(f"Error logging trade: {e}")

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
            
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(prices)-1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)

def fetch_candles_and_rsi(exchange, symbol):
    try:
        # Fetch 15m OHLCV from Bitget
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        closes = [x[4] for x in ohlcv]
        current_price = closes[-1]
        rsi = calculate_rsi(closes)
        return current_price, rsi
    except Exception as e:
        logging.error(f"Error fetching OHLCV for {symbol}: {e}")
        return None, None

def run_simulation_cycle(exchange, state):
    file_exists = os.path.isfile(HISTORY_FILE)
    
    for symbol, cfg in PAIRS.items():
        price, rsi = fetch_candles_and_rsi(exchange, symbol)
        if price is None or rsi is None:
            continue
            
        p_state = state[symbol]
        token_name = cfg["name"]
        
        # Log 15m cycle
        try:
            with open(HISTORY_FILE, mode='a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['timestamp', 'symbol', 'price', 'rsi', 'state', 'token_bal', 'usdt_bal'])
                    file_exists = True
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    symbol, f"{price:.8f}", f"{rsi:.2f}", p_state["state"],
                    f"{p_state['token_balance']:.4f}", f"{p_state['usdt_balance']:.2f}"
                ])
        except Exception as e:
            logging.error(f"Error writing history: {e}")

        # Strategy Logic
        if p_state["state"] == "WAITING_BUY":
            if rsi < cfg["rsi_buy"] and p_state["usdt_balance"] > 5.0:
                # Simulate Buy: invest 98% of USDT, deduct 0.1% simulated fee
                usdt_to_spend = p_state["usdt_balance"] * 0.98
                simulated_fee = usdt_to_spend * 0.001
                effective_usdt = usdt_to_spend - simulated_fee
                tokens_bought = effective_usdt / price
                
                p_state["usdt_balance"] -= usdt_to_spend
                p_state["token_balance"] = tokens_bought
                p_state["buy_price"] = price
                p_state["state"] = "WAITING_SELL"
                p_state["trades_count"] += 1
                save_state(state)
                
                log_trade(symbol, "BUY", price, tokens_bought, usdt_to_spend)
                logging.info(f"🧪 [SIMULACIÓN {token_name}] COMPRA a ${price:.6f} | RSI: {rsi:.2f}")
                send_telegram(
                    f"🧪 *[SIMULADOR DE ALTO VOLUMEN]*\n"
                    f"🟢 *COMPRA SIMULADA: {token_name}*\n"
                    f"🔹 Precio de entrada: `${price:.6f}`\n"
                    f"🔹 RSI (15m): `{rsi:.2f}` (Sobreventa < {cfg['rsi_buy']})\n"
                    f"🔹 Inversión: `${usdt_to_spend:.2f} USDT`\n"
                    f"🔹 Tokens adquiridos: `{tokens_bought:,.2f} {token_name}`\n"
                    f"🎯 Target de ganancia: `+{cfg['take_profit_pct']}%`"
                )
            else:
                logging.info(f"🧪 [SIM {token_name}] {price:.6f} | RSI: {rsi:.2f} | WAITING_BUY | USDT: ${p_state['usdt_balance']:.2f}")

        elif p_state["state"] == "WAITING_SELL":
            buy_price = p_state["buy_price"]
            profit_pct = ((price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
            
            # Exit rules: Target reached OR (Overbought RSI > 75 and in profit)
            target_reached = profit_pct >= cfg["take_profit_pct"]
            overbought_exit = (rsi > cfg["rsi_sell"]) and (profit_pct > 0.0)
            
            if target_reached or overbought_exit:
                tokens_to_sell = p_state["token_balance"]
                gross_usdt = tokens_to_sell * price
                simulated_fee = gross_usdt * 0.001
                net_usdt = gross_usdt - simulated_fee
                
                pnl_usd = net_usdt - (p_state["buy_price"] * tokens_to_sell)
                p_state["usdt_balance"] += net_usdt
                p_state["token_balance"] = 0.0
                p_state["buy_price"] = 0.0
                p_state["state"] = "WAITING_BUY"
                p_state["realized_pnl_usd"] += pnl_usd
                p_state["trades_count"] += 1
                save_state(state)
                
                log_trade(symbol, "SELL", price, tokens_to_sell, net_usdt, profit_pct)
                reason = f"Target alcanzado (+{cfg['take_profit_pct']}%)" if target_reached else f"Sobrecompra RSI ({rsi:.2f} > {cfg['rsi_sell']})"
                logging.info(f"🧪 [SIMULACIÓN {token_name}] VENTA a ${price:.6f} | PnL: {profit_pct:.2f}%")
                send_telegram(
                    f"🧪 *[SIMULADOR DE ALTO VOLUMEN]*\n"
                    f"🔴 *VENTA SIMULADA: {token_name}*\n"
                    f"🔹 Precio de venta: `${price:.6f}`\n"
                    f"🔹 RSI (15m): `{rsi:.2f}`\n"
                    f"🔹 Motivo: `{reason}`\n"
                    f"📈 *Rendimiento:* `+{profit_pct:.2f}%` 🟢\n"
                    f"💵 PnL neto: `+${pnl_usd:.2f} USDT`\n"
                    f"💰 Saldo actual sim: `${p_state['usdt_balance']:.2f} USDT`"
                )
            else:
                logging.info(f"🧪 [SIM {token_name}] {price:.6f} | RSI: {rsi:.2f} | WAITING_SELL | PnL actual: {profit_pct:+.2f}%")

def main():
    logging.info("Iniciando Bot de Simulación (Side Project)...")
    send_telegram("🧪 *Bot de Simulación Iniciado*\nMonitoreando SUI y PEPE en Bitget con la estrategia de Swing RSI...")
    
    # Public exchange instance (no API keys required for paper trading)
    exchange = ccxt.bitget({'enableRateLimit': True})
    
    state = load_state()
    
    while True:
        try:
            run_simulation_cycle(exchange, state)
            time.sleep(900)  # 15 minutes between cycles
        except Exception as e:
            logging.error(f"Error en ciclo de simulación: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
