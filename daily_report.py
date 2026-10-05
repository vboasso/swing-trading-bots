import os
import json
import time
import requests
import subprocess
import ccxt
from web3 import Web3
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv("/home/vale/.env")

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
RAVEN_ADDRESS = os.getenv("RAVEN_ADDRESS", "0xcd7c5025753a49f1881b31c48caa7c517bb46308")
BSC_RPC = "https://bsc-dataseed.binance.org/"
ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]

CAPITAL_FILE = "/home/vale/.capital_history.json"

def send_telegram_message(text):
    for attempt in range(3):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=10)
            break
        except:
            time.sleep(30)

def get_last_log(service_name):
    try:
        cmd = f"journalctl -u {service_name} -n 1 --no-pager"
        last_log = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        if "INFO -" in last_log:
            return last_log.split("INFO - ")[-1]
        return last_log
    except:
        return "No se pudo leer el log."

def calculate_variations(current_capital):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Load or initialize history
    if os.path.exists(CAPITAL_FILE):
        with open(CAPITAL_FILE, 'r') as f:
            data = json.load(f)
    else:
        data = {"initial_capital": current_capital, "history": {}}

    history = data.get("history", {})
    initial_capital = data.get("initial_capital", current_capital)

    # Calculate metrics
    def calc_pct(old, new):
        if not old or old == 0: return 0.0
        return ((new - old) / old) * 100

    # Sort recorded dates
    prev_dates = [d for d in sorted(history.keys()) if d < today]
    cap_previous = history[prev_dates[-1]] if prev_dates else initial_capital

    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_candidates = [d for d in sorted(history.keys()) if d <= seven_days_ago]
    cap_last_week = history[week_candidates[-1]] if week_candidates else initial_capital

    pct_daily = calc_pct(cap_previous, current_capital)
    pct_weekly = calc_pct(cap_last_week, current_capital)
    pct_total = calc_pct(initial_capital, current_capital)

    # Save today's capital
    history[today] = current_capital
    data["history"] = history
    with open(CAPITAL_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    return pct_daily, pct_weekly, pct_total, initial_capital

def fetch_data():
    web3 = Web3(Web3.HTTPProvider(BSC_RPC))
    msg = "📊 *REPORTE DIARIO DE INVERSIONES* 📊\n\n"
    
    total_capital = 0.0

    # Initialize CCXT for Bitget early to get BNB price
    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET'),
        'password': os.getenv('BITGET_PASSWORD'),
        'enableRateLimit': True,
    })

    try:
        price_bnb = exchange.fetch_ticker('BNB/USDT')['last']
    except:
        price_bnb = 600.0  # Fallback

    # --- RAVEN SECTION ---
    try:
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        balance_raven = raven_contract.functions.balanceOf(web3.to_checksum_address(WALLET_ADDRESS)).call() / (10**18)
        bnb_balance = web3.eth.get_balance(web3.to_checksum_address(WALLET_ADDRESS)) / (10**18)
        
        price_raven = 0
        try:
            # Fetch RAVEN price from GeckoTerminal pool
            res = requests.get("https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x547037d9d7ac11cb2740727a7f4ca41111d7e608", timeout=10).json()
            price_raven = float(res['data']['attributes']['base_token_price_usd'])
        except Exception as e:
            pass

        capital_raven = (balance_raven * price_raven) + (bnb_balance * price_bnb)
        total_capital += capital_raven

        log_raven = get_last_log("ravenbot")

        msg += "🦅 *RAVEN BOT (PancakeSwap)*\n"
        msg += f"🔹 RAVEN: `{balance_raven:,.2f}`\n"
        msg += f"🔹 BNB: `{bnb_balance:.4f}`\n"
        msg += f"📈 Precio RAVEN: `${price_raven:.6f}`\n"
        msg += f"📝 Estado: `{log_raven}`\n\n"
    except Exception as e:
        msg += f"🦅 *RAVEN BOT:* Error al cargar ({e})\n\n"
        raise e  # Force retry

    # --- PI SECTION ---
    try:
        balance = exchange.fetch_balance()
        pi_balance = balance['total'].get('PI', 0)
        usdt_balance = balance['total'].get('USDT', 0)
        
        ticker = exchange.fetch_ticker('PI/USDT')
        price_pi = ticker['last']
        
        capital_pi = (pi_balance * price_pi) + usdt_balance
        total_capital += capital_pi

        log_pi = get_last_log("pibot")
        
        msg += "🟣 *PI BOT (Bitget)*\n"
        msg += f"🔹 PI: `{pi_balance:,.2f}`\n"
        msg += f"🔹 USDT: `{usdt_balance:.2f}`\n"
        msg += f"📈 Precio PI: `${price_pi:.4f}`\n"
        msg += f"📝 Estado: `{log_pi}`\n\n"
    except Exception as e:
        msg += f"🟣 *PI BOT:* Error al cargar ({e})\n"
        raise e # Force retry

    # --- PORTFOLIO SUMMARY ---
    pct_daily, pct_weekly, pct_total, initial_cap = calculate_variations(total_capital)
    
    def fmt_pct(val):
        return f"+{val:.2f}% 🟢" if val > 0 else f"{val:.2f}% 🔴" if val < 0 else "0.00% ⚪"

    msg += "💰 *RESUMEN DE CAPITAL* 💰\n"
    msg += f"💵 *Total USD:* `${total_capital:,.2f}`\n"
    msg += f"📅 24 Horas: `{fmt_pct(pct_daily)}`\n"
    msg += f"📆 7 Días: `{fmt_pct(pct_weekly)}`\n"
    msg += f"📈 Histórico: `{fmt_pct(pct_total)}` (Base: ${initial_cap:,.2f})\n"

    return msg

def main():
    # Retry logic up to 3 times with 60s delay
    for attempt in range(3):
        try:
            msg = fetch_data()
            send_telegram_message(msg)
            return
        except Exception as e:
            time.sleep(60)
            
    # If it completely fails 3 times, send the error report
    send_telegram_message("⚠️ *ERROR EN REPORTE DIARIO* ⚠️\nNo se pudo conectar a la red después de 3 intentos.")

if __name__ == "__main__":
    main()
