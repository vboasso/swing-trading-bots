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

# Configuration for Multi-Pair Bot (SUI & PEPE)
# Modes: "PAPER" (simulation) or "REAL" (Bitget Spot API)
PAIRS = {
    "SUI/USDT": {
        "name": "SUI",
        "mode": os.getenv("SUI_MODE", "REAL"),
        "initial_usdt": 110.0,
        "take_profit_pct": 8.0,      # Dynamic TP milestone (+8%)
        "trailing_trigger_pct": 5.0, # Activate trailing stop at +5%
        "trailing_delta_pct": 2.5,   # Trailing distance (peak - 2.5%)
        "rsi_buy": 28.0,             # Relaxed from 25
        "rsi_sell": 70.0,
        "dca_tranches": [0.40, 0.30, 0.30], # 40% initial, 30% dip 1, 30% dip 2
        "dca_drops": [0.0, 4.0, 8.0]        # Entry, -4%, -8%
    },
    "PEPE/USDT": {
        "name": "PEPE",
        "mode": os.getenv("PEPE_MODE", "REAL"),
        "initial_usdt": 80.0,
        "take_profit_pct": 12.0,     # Dynamic TP milestone (+12%)
        "trailing_trigger_pct": 7.0, # Activate trailing stop at +7%
        "trailing_delta_pct": 3.5,   # Trailing distance (peak - 3.5%)
        "rsi_buy": 28.0,             # Relaxed from 25
        "rsi_sell": 72.0,
        "dca_tranches": [0.40, 0.30, 0.30],
        "dca_drops": [0.0, 4.5, 9.0]
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
                state = json.load(f)
                # Ensure all fields exist
                for symbol, cfg in PAIRS.items():
                    if symbol not in state:
                        state[symbol] = {
                            "mode": cfg["mode"],
                            "usdt_balance": cfg["initial_usdt"],
                            "token_balance": 0.0,
                            "buy_price": 0.0,
                            "state": "WAITING_BUY",
                            "trades_count": 0,
                            "realized_pnl_usd": 0.0,
                            "tranches_filled": 0,
                            "max_pnl_seen": 0.0,
                            "trailing_stop_pnl": None,
                            "buy_time": None
                        }
                    else:
                        state[symbol]["mode"] = cfg["mode"]
                return state
        except Exception as e:
            logging.error(f"Error loading state: {e}")

    state = {}
    for symbol, cfg in PAIRS.items():
        state[symbol] = {
            "mode": cfg["mode"],
            "usdt_balance": cfg["initial_usdt"],
            "token_balance": 0.0,
            "buy_price": 0.0,
            "state": "WAITING_BUY",
            "trades_count": 0,
            "realized_pnl_usd": 0.0,
            "tranches_filled": 0,
            "max_pnl_seen": 0.0,
            "trailing_stop_pnl": None,
            "buy_time": None
        }
    save_state(state)
    return state

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving paper state: {e}")

def log_trade(symbol, action, price, amount, usdt_value, profit_pct=0.0, mode="PAPER"):
    file_exists = os.path.isfile(TRADES_FILE)
    try:
        with open(TRADES_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'symbol', 'action', 'price', 'amount', 'usdt_value', 'profit_pct', 'mode'])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol, action, f"{price:.8f}", f"{amount:.4f}", f"{usdt_value:.2f}", f"{profit_pct:.2f}%", mode
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
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        closes = [x[4] for x in ohlcv]
        current_price = closes[-1]
        rsi = calculate_rsi(closes)
        return current_price, rsi
    except Exception as e:
        logging.error(f"Error fetching OHLCV for {symbol}: {e}")
        return None, None

def execute_real_order(exchange, symbol, side, amount, price):
    try:
        base_coin = symbol.split('/')[0]
        if side == "BUY":
            limit_price = float(exchange.price_to_precision(symbol, price * 1.01))
            amt = float(exchange.amount_to_precision(symbol, amount))
            order = exchange.create_limit_buy_order(symbol, amt, limit_price)
        else:
            try:
                b = exchange.fetch_balance()
                actual_free = float(b['free'].get(base_coin, 0.0))
                amount = min(amount, actual_free)
            except Exception as e:
                logging.warning(f"Could not verify free balance for {symbol}: {e}")
                
            amt = float(exchange.amount_to_precision(symbol, amount))
            limit_price = float(exchange.price_to_precision(symbol, price * 0.99))
            try:
                order = exchange.create_limit_sell_order(symbol, amt, limit_price)
            except Exception as e:
                logging.warning(f"Limit sell failed for {symbol} ({e}), trying market sell...")
                order = exchange.create_market_sell_order(symbol, amt)
            
        time.sleep(2)
        try:
            order_info = exchange.fetch_order(order['id'], symbol)
            raw = order_info.get('info', {})
            if raw.get('avgPrice') and float(raw['avgPrice']) > 0:
                real_p = float(raw['avgPrice'])
            elif raw.get('cumExecValue') and raw.get('cumExecQty') and float(raw.get('cumExecQty', 0)) > 0:
                real_p = float(raw['cumExecValue']) / float(raw['cumExecQty'])
            else:
                real_p = float(order_info.get('average') or order_info.get('price') or price)
        except Exception:
            raw = order.get('info', {})
            if raw.get('avgPrice') and float(raw['avgPrice']) > 0:
                real_p = float(raw['avgPrice'])
            else:
                real_p = float(order.get('average') or order.get('price') or price)
        return real_p, amt
    except Exception as e:
        logging.error(f"Bitget Real Order Failed for {symbol} ({side}): {e}")
        return None, 0.0

def run_multi_bot_cycle(exchange, state):
    file_exists = os.path.isfile(HISTORY_FILE)
    
    for symbol, cfg in PAIRS.items():
        price, rsi = fetch_candles_and_rsi(exchange, symbol)
        if price is None or rsi is None:
            continue
            
        p_state = state[symbol]
        token_name = cfg["name"]
        mode = cfg["mode"]
        
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

        # --- STRATEGY LOGIC ---
        
        # 1. WAITING_BUY (Initial Entry / Tranche 1)
        if p_state["state"] == "WAITING_BUY":
            if rsi < cfg["rsi_buy"] and p_state["usdt_balance"] > 5.0:
                # DCA Tranche 1: 40% of total allocation
                tranche_pct = cfg["dca_tranches"][0]
                usdt_to_spend = p_state["usdt_balance"] * tranche_pct
                
                real_p = price
                tokens_bought = 0.0
                
                if mode == "REAL":
                    # Check real Bitget USDT balance
                    try:
                        b = exchange.fetch_balance()
                        free_usdt = b['free'].get('USDT', 0.0)
                        if free_usdt >= 5.0:
                            actual_spend = min(usdt_to_spend, free_usdt * 0.98)
                            target_tokens = actual_spend / price
                            real_p, tokens_bought = execute_real_order(exchange, symbol, "BUY", target_tokens, price)
                            if not real_p:
                                logging.error(f"Real buy order failed for {symbol}")
                                continue
                            usdt_to_spend = actual_spend
                        else:
                            logging.warning(f"[REAL {token_name}] Free USDT in Bitget is ${free_usdt:.2f} (< $5). Waiting for funds.")
                            continue
                    except Exception as e:
                        logging.error(f"Error checking real balance: {e}")
                        continue
                else:
                    # Simulated Paper Buy
                    sim_fee = usdt_to_spend * 0.001
                    tokens_bought = (usdt_to_spend - sim_fee) / price
                    
                p_state["usdt_balance"] -= usdt_to_spend
                p_state["token_balance"] = tokens_bought
                p_state["buy_price"] = real_p
                p_state["tranches_filled"] = 1
                p_state["buy_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                p_state["max_pnl_seen"] = 0.0
                p_state["trailing_stop_pnl"] = None
                p_state["state"] = "WAITING_SELL"
                p_state["trades_count"] += 1
                save_state(state)
                
                log_trade(symbol, "BUY", real_p, tokens_bought, usdt_to_spend, mode=mode)
                logging.info(f"🟢 [{mode} {token_name}] COMPRA Tramo 1/3 a ${real_p:.6f} | RSI: {rsi:.2f}")
                send_telegram(
                    f"🟢 *[{mode} {token_name}] COMPRA (Tramo 1/3 EJECUTADO)*\n"
                    f"🔹 Inversión: `${usdt_to_spend:.2f} USDT`\n"
                    f"🔹 Precio: `${real_p:.6f}`\n"
                    f"🔹 RSI: `{rsi:.2f}` (Sobreventa < {cfg['rsi_buy']})\n"
                    f"🎯 Target: `+{cfg['take_profit_pct']}%` (Trailing desde `+{cfg['trailing_trigger_pct']}%`)"
                )
            else:
                logging.info(f"[{mode} {token_name}] ${price:.6f} | RSI: {rsi:.2f} | WAITING_BUY | USDT: ${p_state['usdt_balance']:.2f}")

        # 2. WAITING_SELL (Tranche 2 & 3 DCA + Dynamic Exits)
        elif p_state["state"] == "WAITING_SELL":
            buy_price = p_state["buy_price"]
            profit_pct = ((price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
            tranches = p_state.get("tranches_filled", 1)
            
            # --- DCA SCALE-IN (Tranches 2 & 3) ---
            if tranches < 3 and p_state["usdt_balance"] >= 5.0:
                next_tranche_idx = tranches # 1 for 2nd tranche, 2 for 3rd tranche
                drop_target = cfg["dca_drops"][next_tranche_idx]
                
                # Trigger DCA if price dropped past threshold and RSI is low (< 35) or capitulating (< 25)
                if (profit_pct <= -drop_target and rsi < 35) or rsi < 25:
                    tranche_pct = cfg["dca_tranches"][next_tranche_idx] / sum(cfg["dca_tranches"][next_tranche_idx:])
                    usdt_to_spend = p_state["usdt_balance"] * tranche_pct
                    
                    real_p = price
                    tokens_bought = 0.0
                    
                    if mode == "REAL":
                        try:
                            b = exchange.fetch_balance()
                            free_usdt = b['free'].get('USDT', 0.0)
                            if free_usdt >= 5.0:
                                actual_spend = min(usdt_to_spend, free_usdt * 0.98)
                                target_tokens = actual_spend / price
                                real_p, tokens_bought = execute_real_order(exchange, symbol, "BUY", target_tokens, price)
                                if not real_p:
                                    continue
                                usdt_to_spend = actual_spend
                            else:
                                logging.warning(f"[REAL {token_name}] Free USDT is ${free_usdt:.2f} (< $5) for DCA.")
                                continue
                        except Exception as e:
                            logging.error(f"Error checking balance: {e}")
                            continue
                    else:
                        sim_fee = usdt_to_spend * 0.001
                        tokens_bought = (usdt_to_spend - sim_fee) / price
                        
                    old_tokens = p_state["token_balance"]
                    old_price = p_state["buy_price"]
                    total_tokens = old_tokens + tokens_bought
                    new_avg = ((old_tokens * old_price) + (tokens_bought * real_p)) / total_tokens if total_tokens > 0 else real_p
                    
                    p_state["usdt_balance"] -= usdt_to_spend
                    p_state["token_balance"] = total_tokens
                    p_state["buy_price"] = new_avg
                    p_state["tranches_filled"] = tranches + 1
                    save_state(state)
                    
                    log_trade(symbol, "BUY", real_p, tokens_bought, usdt_to_spend, mode=mode)
                    logging.info(f"🟢 [{mode} {token_name}] COMPRA DCA Tramo {tranches+1}/3 a ${real_p:.6f} | Nuevo Promedio: ${new_avg:.6f}")
                    send_telegram(
                        f"🟢 *[{mode} {token_name}] COMPRA DCA (Tramo {tranches+1}/3)*\n"
                        f"🔹 Inversión: `${usdt_to_spend:.2f} USDT`\n"
                        f"🔹 Precio nuevo tramo: `${real_p:.6f}`\n"
                        f"📊 *Nuevo Precio Promedio:* `${new_avg:.6f}`\n"
                        f"🔹 Reducción de coste: `{((new_avg - old_price)/old_price)*100:+.2f}%`"
                    )
                    profit_pct = ((price - new_avg) / new_avg) * 100

            # --- DYNAMIC TRAILING STOP TRACKING ---
            if profit_pct > p_state.get("max_pnl_seen", 0.0):
                p_state["max_pnl_seen"] = profit_pct
                if profit_pct >= cfg["trailing_trigger_pct"]:
                    new_trailing = profit_pct - cfg["trailing_delta_pct"]
                    p_state["trailing_stop_pnl"] = max(p_state.get("trailing_stop_pnl") or 0.0, new_trailing)
                save_state(state)

            # --- EVALUATE EXIT CONDITIONS ---
            exit_reason = None
            
            # Rule 1: Fixed Take Profit milestone reached
            if profit_pct >= cfg["take_profit_pct"]:
                exit_reason = f"Target alcanzado (+{profit_pct:.2f}% >= +{cfg['take_profit_pct']}%)"
                
            # Rule 2: Trailing Stop Triggered
            elif p_state.get("trailing_stop_pnl") is not None and profit_pct <= p_state["trailing_stop_pnl"]:
                exit_reason = f"Trailing Stop Activado (+{profit_pct:.2f}%, pico fue +{p_state['max_pnl_seen']:.2f}%)"
                
            # Rule 3: Technical Overbought Exit (RSI > sell_threshold and profit > +1.5%)
            elif rsi >= cfg["rsi_sell"] and profit_pct >= 1.5:
                exit_reason = f"Sobrecompra Técnica RSI ({rsi:.2f} >= {cfg['rsi_sell']} y PnL +{profit_pct:.2f}%)"
                
            if exit_reason:
                tokens_to_sell = p_state["token_balance"]
                real_sell_p = price
                net_usdt = tokens_to_sell * price
                
                if mode == "REAL":
                    real_sell_p, executed_amt = execute_real_order(exchange, symbol, "SELL", tokens_to_sell, price)
                    if not real_sell_p:
                        logging.error(f"Real sell order failed for {symbol}")
                        continue
                    tokens_to_sell = executed_amt
                    net_usdt = executed_amt * real_sell_p
                else:
                    sim_fee = net_usdt * 0.001
                    net_usdt -= sim_fee
                    
                pnl_usd = net_usdt - (p_state["buy_price"] * tokens_to_sell)
                p_state["usdt_balance"] += net_usdt
                p_state["token_balance"] = 0.0
                p_state["buy_price"] = 0.0
                p_state["tranches_filled"] = 0
                p_state["max_pnl_seen"] = 0.0
                p_state["trailing_stop_pnl"] = None
                p_state["buy_time"] = None
                p_state["state"] = "WAITING_BUY"
                p_state["realized_pnl_usd"] += pnl_usd
                p_state["trades_count"] += 1
                save_state(state)
                
                log_trade(symbol, "SELL", real_sell_p, tokens_to_sell, net_usdt, profit_pct, mode=mode)
                logging.info(f"🔴 [{mode} {token_name}] VENTA a ${real_sell_p:.6f} | Motivo: {exit_reason}")
                send_telegram(
                    f"🔴 *[{mode} {token_name}] VENTA EJECUTADA*\n"
                    f"🔹 Precio de venta: `${real_sell_p:.6f}`\n"
                    f"🔹 Motivo: `{exit_reason}`\n"
                    f"📈 *Rendimiento:* `{profit_pct:+.2f}%` 🟢\n"
                    f"💵 PnL neto: `+${pnl_usd:.2f} USDT`\n"
                    f"💰 Saldo actual: `${p_state['usdt_balance']:.2f} USDT`"
                )
            else:
                t_info = f" (Tranches: {tranches}/3, Peak: +{p_state.get('max_pnl_seen', 0.0):.1f}%)"
                logging.info(f"[{mode} {token_name}] ${price:.6f} | RSI: {rsi:.2f} | WAITING_SELL | PnL: {profit_pct:+.2f}%{t_info}")

def main():
    logging.info("Starting Multi-Pair Swing Bot (SUI & PEPE Enhanced with DCA & Trailing TP)...")
    send_telegram("🤖 *Bot Multi-Par (SUI & PEPE) Iniciado (Motor Optimizado)*\n"
                  "🔹 Entradas escalonadas (DCA 3 tramos: 40% / 30% / 30%)\n"
                  "🔹 Trailing Take-Profit activo\n"
                  "🔹 Soporte dual REAL / SIM integrado.")
    
    # Initialize exchange with keys from .env
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET'),
        'password': os.getenv('BITGET_PASSWORD'),
        'enableRateLimit': True
    })
    
    state = load_state()
    
    while True:
        try:
            run_multi_bot_cycle(exchange, state)
            time.sleep(900)
        except Exception as e:
            logging.error(f"Error in multi-pair cycle: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
