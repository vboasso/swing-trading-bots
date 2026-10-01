import os
import time
import requests
import subprocess
import ccxt
from web3 import Web3
from dotenv import load_dotenv

load_dotenv("/home/vale/.env")

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
RAVEN_ADDRESS = os.getenv("RAVEN_ADDRESS", "0xcd7c5025753a49f1881b31c48caa7c517bb46308")
BSC_RPC = "https://bsc-dataseed.binance.org/"
ERC20_ABI = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]

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

def fetch_data():
    web3 = Web3(Web3.HTTPProvider(BSC_RPC))
    msg = "📊 *REPORTE DIARIO DE INVERSIONES* 📊\n\n"
    
    # --- RAVEN SECTION ---
    try:
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        balance_raven = raven_contract.functions.balanceOf(web3.to_checksum_address(WALLET_ADDRESS)).call() / (10**18)
        bnb_balance = web3.eth.get_balance(web3.to_checksum_address(WALLET_ADDRESS)) / (10**18)
        
        price_raven = 0
        try:
            # Fallback to geckoterminal since coingecko is slow
            res = requests.get("https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x5f0a719bf30fb649e79435b642e61df1ffed2ba8", timeout=10).json()
            price_raven = float(res['data']['attributes']['base_token_price_usd'])
        except: pass

        log_raven = get_last_log("ravenbot")

        msg += "🦅 *RAVEN BOT (Trust Wallet)*\n"
        msg += f"🔹 RAVEN: `{balance_raven:,.2f}`\n"
        msg += f"🔹 BNB: `{bnb_balance:.4f}`\n"
        msg += f"📈 Precio RAVEN: `${price_raven:.6f}`\n"
        msg += f"📝 Estado: `{log_raven}`\n\n"
    except Exception as e:
        msg += f"🦅 *RAVEN BOT:* Error al cargar ({e})\n\n"
        raise e  # Force retry

    # --- PI SECTION ---
    try:
        exchange = ccxt.bitget({
            'apiKey': os.getenv('BITGET_API_KEY'),
            'secret': os.getenv('BITGET_SECRET'),
            'password': os.getenv('BITGET_PASSWORD'),
            'enableRateLimit': True,
        })
        balance = exchange.fetch_balance()
        pi_balance = balance['total'].get('PI', 0)
        usdt_balance = balance['total'].get('USDT', 0)
        
        ticker = exchange.fetch_ticker('PI/USDT')
        price_pi = ticker['last']
        
        log_pi = get_last_log("pibot")
        
        msg += "🟣 *PI BOT (Bitget)*\n"
        msg += f"🔹 PI: `{pi_balance:,.2f}`\n"
        msg += f"🔹 USDT: `{usdt_balance:.2f}`\n"
        msg += f"📈 Precio PI: `${price_pi:.4f}`\n"
        msg += f"📝 Estado: `{log_pi}`\n"
    except Exception as e:
        msg += f"🟣 *PI BOT:* Error al cargar ({e})\n"
        raise e # Force retry

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
