import os
import time
import requests
import csv
from datetime import datetime
import logging
import ccxt
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv('/home/vale/.env')

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

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

def get_last_buy():
    try:
        with open("/home/vale/.pi_buy_price", "r") as f:
            return float(f.read().strip())
    except:
        return 0.0

def set_last_buy(price):
    try:
        with open("/home/vale/.pi_buy_price", "w") as f:
            f.write(str(price))
    except:
        pass

def main():
    logging.info("Starting PI/USDT Swing Bot...")
    send_telegram_message("🤖 *Pi Bot Iniciado*\nEl bot gemelo de PI ha arrancado correctamente...")
    
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET'),
        'password': os.getenv('BITGET_PASSWORD'),
        'enableRateLimit': True,
    })
    
    symbol = 'PI/USDT'
    last_buy_price = get_last_buy()
    
    consecutive_errors = 0
    while True:
        try:
            # 1. Fetch Balances
            balance = exchange.fetch_balance()
            pi_balance = balance['total'].get('PI', 0)
            usdt_balance = balance['total'].get('USDT', 0)
            
            # 2. Determine State
            state = "WAITING_BUY"
            if pi_balance > 10: # If we have more than 10 PI, we want to sell
                state = "WAITING_SELL"
                
            # 3. Fetch OHLCV directly from Bitget
            ohlcv = exchange.fetch_ohlcv(symbol, '30m', limit=20)
            closes = [x[4] for x in ohlcv]
            
            if len(closes) > 15:
                rsi = calculate_rsi(closes)
                current_price = closes[-1]
                logging.info(f"Price: {current_price:.4f} | RSI: {rsi:.2f} | State: {state} | PI: {pi_balance:.2f} | USDT: {usdt_balance:.2f}")
                
                # Log to CSV
                csv_file = "/home/vale/pibot_history.csv"
                file_exists = os.path.isfile(csv_file)
                try:
                    with open(csv_file, mode='a', newline='') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(['timestamp', 'price', 'rsi', 'state', 'pi_balance', 'usdt_balance'])
                        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{current_price:.4f}", f"{rsi:.2f}", state, f"{pi_balance:.2f}", f"{usdt_balance:.2f}"])
                except Exception as e:
                    logging.error(f"Error CSV: {e}")
                
                # 4. Execute Logic
                if state == "WAITING_BUY":
                    if usdt_balance > 5: # Minimum $5 to trade
                        if rsi < 25:
                            logging.info("RSI below 25. Executing Buy...")
                            try:
                                # Buy using 98% of USDT to account for fees/slippage
                                limit_price = float(exchange.price_to_precision(symbol, current_price * 1.02))
                                amount_to_buy = (usdt_balance * 0.98) / limit_price
                                amount_to_buy = float(exchange.amount_to_precision(symbol, amount_to_buy))
                                order = exchange.create_limit_buy_order(symbol, amount_to_buy, limit_price)
                                last_buy_price = current_price
                                set_last_buy(last_buy_price)
                                logging.info(f"Buy Order Success: {order}")
                                send_telegram_message(f"🟢 *COMPRA DE PI EJECUTADA*\nSe compró PI exitosamente a ${current_price:.4f}.")
                            except Exception as e:
                                logging.error(f"Buy Error: {e}")
                                send_telegram_message(f"❌ *ERROR DE COMPRA PI*\nDetalle: `{e}`")
                    else:
                        logging.info("Not enough USDT to buy.")
                        
                elif state == "WAITING_SELL":
                    profit_pct = ((current_price - last_buy_price) / last_buy_price) * 100 if last_buy_price > 0 else 0
                    
                    if profit_pct >= 25 or (rsi > 75 and (last_buy_price == 0 or current_price > last_buy_price)):
                        logging.info(f"Sell condition met. Profit: {profit_pct:.2f}% | RSI: {rsi:.2f}")
                        try:
                            pi_balance = float(exchange.amount_to_precision(symbol, pi_balance))
                            limit_price = float(exchange.price_to_precision(symbol, current_price * 0.98))
                            order = exchange.create_limit_sell_order(symbol, pi_balance, limit_price)
                            last_buy_price = 0
                            set_last_buy(0)
                            logging.info(f"Sell Order Success: {order}")
                            send_telegram_message(f"🔴 *VENTA DE PI EJECUTADA*\nSe vendieron {pi_balance:.2f} PI por USDT a ${current_price:.4f}.")
                        except Exception as e:
                            logging.error(f"Sell Error: {e}")
                            send_telegram_message(f"❌ *ERROR DE VENTA PI*\nDetalle: `{e}`")
                    elif rsi > 75:
                        logging.info(f"RSI > 75 but price is lower than buy price ({last_buy_price}). HODLing to prevent loss.")
            else:
                logging.warning("Not enough data to calculate RSI.")
                
            consecutive_errors = 0
            consecutive_errors = 0
            time.sleep(900) # Wait 15 minutes between checks
            
        except Exception as e:
            error_msg = str(e)
            consecutive_errors += 1
            
            retry_delays = [2, 10, 60]
            
            if consecutive_errors == len(retry_delays) + 1:
                logging.error(f"Error persistente in main loop: {error_msg}")
                send_telegram_message(f"⚠️ *ALERTA (PI BOT)* ⚠️\nSe detectó un problema de red persistente:\n`{error_msg}`")
                time.sleep(60)
            elif consecutive_errors > len(retry_delays) + 1:
                time.sleep(60)
            else:
                delay = retry_delays[consecutive_errors - 1]
                logging.warning(f"Micro-corte de red detectado (intento {consecutive_errors}). Reintentando en {delay} segundos...")
                time.sleep(delay)

if __name__ == "__main__":
    main()
