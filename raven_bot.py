import os
import time
import requests
import csv
from datetime import datetime
import logging
from web3 import Web3
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

from eth_account import Account
Account.enable_unaudited_hdwallet_features()

MNEMONIC = os.getenv("MNEMONIC")
if MNEMONIC:
    account = Account.from_mnemonic(MNEMONIC)
    PRIVATE_KEY = account.key.hex()
else:
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
# Ensure the user has provided the contract address for RAVEN (BEP-20)
RAVEN_ADDRESS = os.getenv("RAVEN_ADDRESS", "0xcBd7A10B45C49887532A1f0BEcb54A51f28b49E1") 

BSC_RPC = "https://bsc-dataseed.binance.org/"
ROUTER_ADDRESS = "0x10ED43C718714eb63d5aA57B78B54704E256024E" # PancakeSwap V2
WBNB_ADDRESS = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

web3 = Web3(Web3.HTTPProvider(BSC_RPC))

ERC20_ABI = [
    {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]

ROUTER_ABI = [
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"payable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForETHSupportingFeeOnTransferTokens","outputs":[],"stateMutability":"nonpayable","type":"function"}
]

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
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
    
    # Simple Moving Average for first calculation
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # Smoothed for the rest
    for i in range(period, len(prices)-1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def fetch_dex_prices():
    try:
        # Use GeckoTerminal to fetch exact DEX prices (15 min aggregates)
        url = "https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x547037d9d7ac11cb2740727a7f4ca41111d7e608/ohlcv/minute?aggregate=15&limit=25"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        # Structure: {"data": {"attributes": {"ohlcv_list": [[time, open, high, low, close, volume], ...]}}}
        ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        
        # GeckoTerminal returns newest first. We need oldest first for RSI.
        closes = [item[4] for item in ohlcv_list]
        closes.reverse()
        
        # If low volume causes missing candles, pad with the last known price to keep RSI stable
        if len(closes) > 0 and len(closes) < 16:
            last_price = closes[-1]
            while len(closes) < 16:
                closes.append(last_price)
                
        return closes
    except Exception as e:
        logging.error(f"Error fetching DEX prices: {e}")
        return []

def fetch_and_log_macro():
    macro_file = "/home/vale/macro_history.csv"
    file_exists = os.path.isfile(macro_file)
    btc_price, btc_dominance, fng_value = 0, 0, 0
    
    # 1. BTC Price via Binance (More reliable, no Cloudflare blocks)
    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        btc_price = float(r1.json().get("price", 0))
    except Exception as e:
        logging.warning(f"Macro Warning (BTC): {e}")
        
    # 2. BTC Dominance via CoinGecko (May get 403, so handle softly)
    try:
        r2 = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r2.status_code == 200:
            btc_dominance = r2.json().get("data", {}).get("market_cap_percentage", {}).get("btc", 0)
    except Exception as e:
        pass # Ignore CG errors to prevent spam
        
    # 3. Fear & Greed Index
    try:
        r3 = requests.get("https://api.alternative.me/fng/", timeout=5)
        if r3.status_code == 200:
            fng_value = int(r3.json().get("data", [{}])[0].get("value", 0))
    except Exception as e:
        logging.warning(f"Macro Warning (FnG): {e}")
        
    # Write to CSV
    try:
        with open(macro_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'btc_price', 'btc_dominance', 'fear_and_greed'])
            writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{btc_price:.2f}", f"{btc_dominance:.2f}", fng_value])
    except Exception as e:
        logging.error(f"Error writing macro CSV: {e}")

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def execute_buy(current_price):
    if not PRIVATE_KEY or not WALLET_ADDRESS:
        logging.error("Missing credentials in .env")
        return False
    logging.info("Executing BUY (BNB -> RAVEN)")
    try:
        router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        account = web3.eth.account.from_key(PRIVATE_KEY)
        
        balance = web3.eth.get_balance(account.address)
        if balance == 0:
            logging.info("No BNB to buy.")
            return False
            
        # Use 90% of available BNB to keep enough for gas fees
        amount_to_buy = int(balance * 0.9)
        
        tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0, # Accept any amount of tokens (slippage protection can be added here)
            [web3.to_checksum_address(WBNB_ADDRESS), web3.to_checksum_address(RAVEN_ADDRESS)],
            account.address,
            int(time.time()) + 600
        ).build_transaction({
            'from': account.address,
            'value': amount_to_buy,
            'gas': 300000,
            'gasPrice': web3.to_wei(3, 'gwei'),
            'nonce': web3.eth.get_transaction_count(account.address)
        })
        signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logging.info(f"Buy TX Hash: {web3.to_hex(tx_hash)}")
        human_bnb = amount_to_buy / (10**18)
        send_telegram_message(f"🟢 *COMPRA DE RAVEN EJECUTADA*\nSe invirtieron {human_bnb:.4f} BNB a un precio aprox de ${current_price:.8f}.\nHash: `{web3.to_hex(tx_hash)}`")
        return True
    except Exception as e:
        logging.error(f"Buy execution failed: {e}")
        send_telegram_message(f"❌ *ERROR DE COMPRA*\nDetalle: `{e}`")
        return False

def execute_sell(current_price):
    if not PRIVATE_KEY or not WALLET_ADDRESS:
        return False
    logging.info("Executing SELL (RAVEN -> BNB)")
    try:
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        account = web3.eth.account.from_key(PRIVATE_KEY)
        
        balance = raven_contract.functions.balanceOf(account.address).call()
        if balance == 0:
            logging.info("No RAVEN to sell.")
            return False
            
        # Check allowance
        allowance = raven_contract.functions.allowance(account.address, web3.to_checksum_address(ROUTER_ADDRESS)).call()
        if allowance < balance:
            logging.info("Approving Router to spend RAVEN...")
            approve_tx = raven_contract.functions.approve(web3.to_checksum_address(ROUTER_ADDRESS), balance).build_transaction({
                'from': account.address,
                'gas': 100000,
                'gasPrice': web3.to_wei(3, 'gwei'),
                'nonce': web3.eth.get_transaction_count(account.address)
            })
            signed_approve = web3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
            web3.eth.send_raw_transaction(signed_approve.raw_transaction)
            time.sleep(10) # Wait for confirmation
            
        tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            balance,
            0,
            [web3.to_checksum_address(RAVEN_ADDRESS), web3.to_checksum_address(WBNB_ADDRESS)],
            account.address,
            int(time.time()) + 600
        ).build_transaction({
            'from': account.address,
            'gas': 300000,
            'gasPrice': web3.to_wei(3, 'gwei'),
            'nonce': web3.eth.get_transaction_count(account.address)
        })
        signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logging.info(f"Sell TX Hash: {web3.to_hex(tx_hash)}")
        human_raven = balance / (10**18)
        send_telegram_message(f"🔴 *VENTA DE RAVEN EJECUTADA*\nSe vendieron {human_raven:,.0f} RAVEN a un precio aprox de ${current_price:.8f}.\nHash: `{web3.to_hex(tx_hash)}`")
        return True
    except Exception as e:
        logging.error(f"Sell execution failed: {e}")
        send_telegram_message(f"❌ *ERROR DE VENTA*\nDetalle: `{e}`")
        return False

def get_last_buy():
    try:
        with open("/home/vale/.raven_buy_price", "r") as f:
            return float(f.read().strip())
    except:
        return 0.0

def set_last_buy(price):
    try:
        with open("/home/vale/.raven_buy_price", "w") as f:
            f.write(str(price))
    except:
        pass

def main():
    logging.info("Starting RAVEN/BNB Swing Bot...")
    send_telegram_message("🤖 *Bot Iniciado*\nEl bot de RAVEN ha arrancado correctamente...")
    last_buy_price = get_last_buy()
    
    consecutive_errors = 0
    while True:
        try:
            account = web3.eth.account.from_key(PRIVATE_KEY)
            
            # Detect state dynamically based on balances
            raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
            raven_wei = raven_contract.functions.balanceOf(account.address).call()
            raven_balance = raven_wei / (10**18)
            
            bnb_wei = web3.eth.get_balance(account.address)
            bnb_balance = bnb_wei / (10**18)
            
            state = "WAITING_BUY"
            if raven_balance > 100000: # If we have more than 100k RAVEN, we focus on selling
                state = "WAITING_SELL"
            
            closes = fetch_dex_prices()
            if len(closes) > 15:
                rsi = calculate_rsi(closes)
                current_price = closes[-1]
                logging.info(f"Price: {current_price:.8f} | RSI: {rsi:.2f} | State: {state} | RAVEN: {raven_balance:.0f} | BNB: {bnb_balance:.4f}")
                
                # Log to CSV
                csv_file = "/home/vale/bot_history.csv"
                file_exists = os.path.isfile(csv_file)
                try:
                    with open(csv_file, mode='a', newline='') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(['timestamp', 'price', 'rsi', 'state', 'raven_balance', 'bnb_balance'])
                        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{current_price:.8f}", f"{rsi:.2f}", state, f"{raven_balance:.0f}", f"{bnb_balance:.4f}"])
                except Exception as e:
                    logging.error(f"Error writing to CSV: {e}")
                
                # Fetch and log Macro factors
                fetch_and_log_macro()
                
                if state == "WAITING_BUY":
                    if bnb_balance > 0.01: # Minimum BNB to trade
                        if rsi < 25:
                            logging.info("RSI below 25. Executing Buy...")
                            if execute_buy(current_price):
                                last_buy_price = current_price
                                set_last_buy(last_buy_price)
                    else:
                        logging.info("Not enough BNB to buy.")
                elif state == "WAITING_SELL":
                    profit_pct = ((current_price - last_buy_price) / last_buy_price) * 100 if last_buy_price > 0 else 0
                    
                    if profit_pct >= 25 or (rsi > 75 and (last_buy_price == 0 or current_price > last_buy_price)):
                        logging.info(f"Sell condition met. Profit: {profit_pct:.2f}% | RSI: {rsi:.2f}")
                        if execute_sell(current_price):
                            last_buy_price = 0
                            set_last_buy(0)
                    elif rsi > 75:
                        logging.info(f"RSI > 75 but price is lower than buy price ({last_buy_price}). HODLing to prevent loss.")
            else:
                logging.warning("Not enough data to calculate RSI yet.")
                
            consecutive_errors = 0
            consecutive_errors = 0
            time.sleep(900) # Wait 15 minutes between checks
        except Exception as e:
            error_msg = str(e)
            consecutive_errors += 1
            
            retry_delays = [2, 10, 60]
            
            if consecutive_errors > len(retry_delays):
                logging.error(f"Error persistente in main loop: {error_msg}")
                send_telegram_message(f"⚠️ *ALERTA (RAVEN BOT)* ⚠️\nSe detectó un problema de red persistente:\n`{error_msg}`")
                time.sleep(60)
            else:
                delay = retry_delays[consecutive_errors - 1]
                logging.warning(f"Micro-corte de red detectado (intento {consecutive_errors}). Reintentando en {delay} segundos...")
                time.sleep(delay)

if __name__ == "__main__":
    main()
