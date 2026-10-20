import os
import time
import json
import requests
import csv
from datetime import datetime, timedelta
import logging
import ccxt
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv('/home/vale/.env')

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

STATE_FILE = "/home/vale/.pi_state.json"
BUY_PRICE_FILE = "/home/vale/.pi_buy_price"
CSV_FILE = "/home/vale/pibot_history.csv"
SYMBOL = "PI/USDT"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
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
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def load_state():
    # Backward compatibility with .pi_buy_price
    legacy_price = 0.0
    if os.path.exists(BUY_PRICE_FILE):
        try:
            with open(BUY_PRICE_FILE, "r") as f:
                legacy_price = float(f.read().strip())
        except Exception:
            pass

    state = {
        "buy_price": legacy_price,
        "buy_time": "2026-10-02 18:26:15" if legacy_price > 0 else None,
        "tranches_filled": 1 if legacy_price > 0 else 0,
        "max_pnl_seen": 0.0,
        "trailing_stop_pnl": None
    }
    
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                saved = json.load(f)
                state.update(saved)
        except Exception as e:
            logging.error(f"Error loading {STATE_FILE}: {e}")
            
    return state

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        # Keep .pi_buy_price updated for dashboard & daily_report
        with open(BUY_PRICE_FILE, "w") as f:
            f.write(str(state.get("buy_price", 0.0)))
    except Exception as e:
        logging.error(f"Error saving state: {e}")

def main():
    logging.info("Starting PI/USDT Swing Bot (Enhanced Engine with 2-Tranche DCA & Dynamic Trailing TP)...")
    send_telegram_message("🤖 *Pi Bot Iniciado (Motor Optimizado)*\n"
                          "🔹 Entradas escalonadas (DCA 2 tramos)\n"
                          "🔹 Take-Profit dinámico (+8% objetivo, trailing stop desde +5%)\n"
                          "🔹 Salida por estancamiento técnico activada (>7 días)")
    
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET'),
        'password': os.getenv('BITGET_PASSWORD'),
        'enableRateLimit': True,
    })
    
    state_data = load_state()
    consecutive_errors = 0
    
    while True:
        try:
            # 1. Fetch Balances
            balance = exchange.fetch_balance()
            pi_balance = balance['free'].get('PI', 0)
            usdt_balance = balance['free'].get('USDT', 0)
            
            # 2. Determine State
            state = "WAITING_BUY"
            if pi_balance > 10: # If we have more than 10 PI, we are in position
                state = "WAITING_SELL"
            else:
                if state_data["buy_price"] > 0 and state_data["tranches_filled"] > 0:
                    # Reset state if balance is zero
                    state_data = {
                        "buy_price": 0.0,
                        "buy_time": None,
                        "tranches_filled": 0,
                        "max_pnl_seen": 0.0,
                        "trailing_stop_pnl": None
                    }
                    save_state(state_data)
                
            # 3. Fetch OHLCV directly from Bitget
            ohlcv = exchange.fetch_ohlcv(SYMBOL, '30m', limit=20)
            closes = [x[4] for x in ohlcv]
            
            if len(closes) > 15:
                rsi = calculate_rsi(closes)
                current_price = closes[-1]
                buy_price = state_data.get("buy_price", 0.0)
                profit_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                
                logging.info(f"PI: ${current_price:.4f} | RSI: {rsi:.2f} | State: {state} (Tranches: {state_data.get('tranches_filled', 0)}/2) | PnL: {profit_pct:+.2f}% | PI: {pi_balance:.2f} | USDT: {usdt_balance:.2f}")
                
                # Log to CSV
                file_exists = os.path.isfile(CSV_FILE)
                try:
                    with open(CSV_FILE, mode='a', newline='') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(['timestamp', 'price', 'rsi', 'state', 'pi_balance', 'usdt_balance'])
                        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{current_price:.4f}", f"{rsi:.2f}", state, f"{pi_balance:.2f}", f"{usdt_balance:.2f}"])
                except Exception as e:
                    logging.error(f"Error CSV: {e}")
                
                # 4. Execute Logic
                
                # --- WAITING_BUY / TRANCHE 1 ---
                if state == "WAITING_BUY":
                    MAX_PI_BUDGET = 65.0
                    allocated_usdt = min(usdt_balance, MAX_PI_BUDGET)
                    if allocated_usdt > 5:
                        # Relaxed RSI threshold to 28 (from 25) for initial entry
                        if rsi < 28:
                            logging.info("RSI below 28. Executing Tranche 1 Buy (50% of PI budget)...")
                            try:
                                # Spend 50% of allocated USDT for Tranche 1
                                usdt_to_spend = (allocated_usdt * 0.50) if allocated_usdt >= 15 else (allocated_usdt * 0.98)
                                limit_price = float(exchange.price_to_precision(SYMBOL, current_price * 1.02))
                                amount_to_buy = (usdt_to_spend * 0.98) / limit_price
                                amount_to_buy = float(exchange.amount_to_precision(SYMBOL, amount_to_buy))
                                
                                order = exchange.create_limit_buy_order(SYMBOL, amount_to_buy, limit_price)
                                time.sleep(2)
                                try:
                                    order_info = exchange.fetch_order(order['id'], SYMBOL)
                                    real_price = float(order_info.get('average') or order_info.get('price') or current_price)
                                except Exception:
                                    real_price = float(order.get('average') or order.get('price') or current_price)
                                
                                state_data["buy_price"] = real_price
                                state_data["buy_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                state_data["tranches_filled"] = 1
                                state_data["max_pnl_seen"] = 0.0
                                state_data["trailing_stop_pnl"] = None
                                save_state(state_data)
                                
                                logging.info(f"Tranche 1 Buy Success: {order['id']} at price: ${real_price:.4f}")
                                send_telegram_message(
                                    f"🟢 *COMPRA PI (Tramo 1/2 EJECUTADO)*\n"
                                    f"🔹 Inversión: `${usdt_to_spend:.2f} USDT`\n"
                                    f"🔹 Tokens comprados: `{amount_to_buy:,.2f} PI`\n"
                                    f"🔹 Precio de entrada: `${real_price:.4f}`\n"
                                    f"🔹 RSI: `{rsi:.2f}`\n"
                                    f"🎯 Objetivo: `+8.0%` con Trailing Stop activo."
                                )
                            except Exception as e:
                                logging.error(f"Buy Tranche 1 Error: {e}")
                                send_telegram_message(f"❌ *ERROR DE COMPRA PI (Tramo 1)*\nDetalle: `{e}`")
                                
                # --- WAITING_SELL / TRANCHE 2 & EXITS ---
                elif state == "WAITING_SELL":
                    # Check if Tranche 2 should be executed (DCA scale-in)
                    tranches = state_data.get("tranches_filled", 1)
                    MAX_PI_BUDGET = 65.0
                    allocated_usdt = min(usdt_balance, MAX_PI_BUDGET * 0.50)
                    if tranches < 2 and allocated_usdt >= 5:
                        # Trigger Tranche 2 if price dipped >= 4.5% below initial entry OR RSI < 25 again
                        if (profit_pct <= -4.5 and rsi < 35) or rsi < 25:
                            logging.info(f"DCA condition met for Tranche 2. PnL: {profit_pct:.2f}% | RSI: {rsi:.2f}. Executing Buy...")
                            try:
                                usdt_to_spend = allocated_usdt * 0.98
                                limit_price = float(exchange.price_to_precision(SYMBOL, current_price * 1.02))
                                amount_to_buy = usdt_to_spend / limit_price
                                amount_to_buy = float(exchange.amount_to_precision(SYMBOL, amount_to_buy))
                                
                                order = exchange.create_limit_buy_order(SYMBOL, amount_to_buy, limit_price)
                                time.sleep(2)
                                try:
                                    order_info = exchange.fetch_order(order['id'], SYMBOL)
                                    real_price = float(order_info.get('average') or order_info.get('price') or current_price)
                                except Exception:
                                    real_price = float(order.get('average') or order.get('price') or current_price)
                                    
                                # Recalculate weighted average buy price
                                old_price = state_data.get("buy_price", real_price)
                                total_tokens = pi_balance + amount_to_buy
                                if total_tokens > 0:
                                    new_avg_price = ((pi_balance * old_price) + (amount_to_buy * real_price)) / total_tokens
                                else:
                                    new_avg_price = real_price
                                    
                                state_data["buy_price"] = new_avg_price
                                state_data["tranches_filled"] = 2
                                save_state(state_data)
                                
                                logging.info(f"Tranche 2 Buy Success: {order['id']} at price: ${real_price:.4f}. New Avg: ${new_avg_price:.4f}")
                                send_telegram_message(
                                    f"🟢 *COMPRA PI (Tramo 2/2 DCA EJECUTADO)*\n"
                                    f"🔹 Inversión: `${usdt_to_spend:.2f} USDT`\n"
                                    f"🔹 Tokens agregados: `{amount_to_buy:,.2f} PI`\n"
                                    f"🔹 Precio nuevo tramo: `${real_price:.4f}`\n"
                                    f"📊 *Precio Promedio Ponderado:* `${new_avg_price:.4f}`\n"
                                    f"🔹 Reducción de coste: `{((new_avg_price - old_price)/old_price)*100:+.2f}%`"
                                )
                                # Recalculate profit_pct with new average price
                                profit_pct = ((current_price - new_avg_price) / new_avg_price) * 100
                            except Exception as e:
                                logging.error(f"Buy Tranche 2 Error: {e}")
                                
                    # Update Trailing Stop high-water mark
                    if profit_pct > state_data.get("max_pnl_seen", 0.0):
                        state_data["max_pnl_seen"] = profit_pct
                        # Activate trailing stop when profit crosses +5.0%
                        if profit_pct >= 5.0:
                            state_data["trailing_stop_pnl"] = max(state_data.get("trailing_stop_pnl") or 0.0, profit_pct - 2.5)
                        save_state(state_data)

                    # Determine Holding Time for Stagnation Exit
                    days_held = 0
                    if state_data.get("buy_time"):
                        try:
                            b_date = datetime.strptime(state_data["buy_time"].split(".")[0], "%Y-%m-%d %H:%M:%S")
                            days_held = (datetime.now() - b_date).total_seconds() / 86400.0
                        except Exception:
                            days_held = 0

                    # --- EVALUATE EXIT CONDITIONS ---
                    sell_reason = None
                    
                    # Rule 1: Fixed Take-Profit reached (+8.0%)
                    if profit_pct >= 8.0:
                        sell_reason = f"Target de ganancia alcanzado (+{profit_pct:.2f}% >= +8.0%)"
                        
                    # Rule 2: Dynamic Trailing Stop Triggered
                    elif state_data.get("trailing_stop_pnl") is not None and profit_pct <= state_data["trailing_stop_pnl"]:
                        sell_reason = f"Trailing Stop Activado (+{profit_pct:.2f}%, pico fue +{state_data['max_pnl_seen']:.2f}%)"
                        
                    # Rule 3: Technical Overbought Exit (RSI >= 70 and in positive profit > 1.5%)
                    elif rsi >= 70 and profit_pct >= 1.5:
                        sell_reason = f"Sobrecompra Técnica (RSI {rsi:.2f} >= 70 y PnL positivo +{profit_pct:.2f}%)"
                        
                    # Rule 4: Stagnation / Time-Stop Exit (> 7 days held and technical bounce near breakeven >= -2.0% with RSI >= 65)
                    elif days_held >= 7.0 and rsi >= 65 and profit_pct >= -2.0:
                        sell_reason = f"Salida por Estancamiento ({days_held:.1f} días retenido, RSI {rsi:.2f} >= 65 en rebote técnico)"
                        
                    if sell_reason:
                        logging.info(f"Sell condition met: {sell_reason}")
                        try:
                            pi_balance = float(exchange.amount_to_precision(SYMBOL, pi_balance))
                            limit_price = float(exchange.price_to_precision(SYMBOL, current_price * 0.98))
                            order = exchange.create_limit_sell_order(SYMBOL, pi_balance, limit_price)
                            time.sleep(2)
                            try:
                                order_info = exchange.fetch_order(order['id'], SYMBOL)
                                real_sell_price = order_info.get('average') or order_info.get('price') or current_price
                            except Exception:
                                real_sell_price = order.get('average') or order.get('price') or current_price
                                
                            real_pnl_usd = (float(real_sell_price) - buy_price) * pi_balance
                            
                            # Reset state
                            state_data = {
                                "buy_price": 0.0,
                                "buy_time": None,
                                "tranches_filled": 0,
                                "max_pnl_seen": 0.0,
                                "trailing_stop_pnl": None
                            }
                            save_state(state_data)
                            
                            logging.info(f"Sell Order Success: {order['id']} at real price: {real_sell_price}")
                            send_telegram_message(
                                f"🔴 *VENTA DE PI EJECUTADA*\n"
                                f"🔹 Tokens vendidos: `{pi_balance:,.2f} PI`\n"
                                f"🔹 Precio de venta: `${float(real_sell_price):.4f}`\n"
                                f"🔹 Motivo: `{sell_reason}`\n"
                                f"📈 *Rendimiento:* `{profit_pct:+.2f}%`\n"
                                f"💵 PnL neto estimado: `${real_pnl_usd:+.2f} USDT`\n"
                                f"⏱ Días de retención: `{days_held:.1f} días`"
                            )
                        except Exception as e:
                            logging.error(f"Sell Error: {e}")
                            send_telegram_message(f"❌ *ERROR DE VENTA PI*\nDetalle: `{e}`")
                    else:
                        if rsi >= 70:
                            logging.info(f"RSI {rsi:.2f} >= 70 but PnL ({profit_pct:+.2f}%) below trigger. HODLing (Held: {days_held:.1f}d).")
            else:
                logging.warning("Not enough data to calculate RSI.")
                
            consecutive_errors = 0
            time.sleep(900) # Wait 15 minutes between checks
            
        except Exception as e:
            error_msg = str(e)
            consecutive_errors += 1
            retry_delays = [2, 10, 60]
            if consecutive_errors == len(retry_delays) + 1:
                logging.error(f"Persistent error in PI loop: {error_msg}")
                send_telegram_message(f"⚠️ *ALERTA (PI BOT)* ⚠️\n`{error_msg}`")
                time.sleep(60)
            elif consecutive_errors > len(retry_delays) + 1:
                time.sleep(60)
            else:
                delay = retry_delays[consecutive_errors - 1]
                time.sleep(delay)

if __name__ == "__main__":
    main()
