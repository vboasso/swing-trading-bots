import os
import time
import json
import requests
import csv
from datetime import datetime
import logging
from web3 import Web3
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv('/home/vale/.env')

from eth_account import Account
Account.enable_unaudited_hdwallet_features()

MNEMONIC = os.getenv("MNEMONIC")
if MNEMONIC:
    account = Account.from_mnemonic(MNEMONIC)
    PRIVATE_KEY = account.key.hex()
else:
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
RAVEN_ADDRESS = os.getenv("RAVEN_ADDRESS", "0xcd7c5025753a49f1881b31c48caa7c517bb46308") 

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

STATE_FILE = "/home/vale/.raven_state.json"
BUY_PRICE_FILE = "/home/vale/.raven_buy_price"

_last_bnb_usd = 740.0
_last_bnb_time = 0

def get_bnb_usd():
    global _last_bnb_usd, _last_bnb_time
    now = time.time()
    if now - _last_bnb_time > 45:
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT", timeout=4).json()
            _last_bnb_usd = float(r.get("price", _last_bnb_usd))
            _last_bnb_time = now
        except Exception:
            pass
    return _last_bnb_usd

def fetch_onchain_spot_price():
    try:
        router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        out = router.functions.getAmountsOut(
            10**18,
            [web3.to_checksum_address(RAVEN_ADDRESS), web3.to_checksum_address(WBNB_ADDRESS)]
        ).call()
        bnb_per_raven = out[1] / (10**18)
        bnb_usd = get_bnb_usd()
        return bnb_per_raven * bnb_usd
    except Exception as e:
        logging.warning(f"Error fetching on-chain spot price: {e}")
        return None

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

def fetch_dex_prices():
    try:
        url = "https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x547037d9d7ac11cb2740727a7f4ca41111d7e608/ohlcv/minute?aggregate=15&limit=25"
        response = requests.get(url, timeout=10)
        data = response.json()
        ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        closes = [item[4] for item in ohlcv_list]
        closes.reverse()
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
    try:
        r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        btc_price = float(r1.json().get("price", 0))
    except Exception:
        pass
    try:
        r2 = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r2.status_code == 200:
            btc_dominance = r2.json().get("data", {}).get("market_cap_percentage", {}).get("btc", 0)
    except Exception:
        pass
    try:
        r3 = requests.get("https://api.alternative.me/fng/", timeout=5)
        if r3.status_code == 200:
            fng_value = int(r3.json().get("data", [{}])[0].get("value", 0))
    except Exception:
        pass
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

def load_state():
    legacy_price = 0.0
    if os.path.exists(BUY_PRICE_FILE):
        try:
            with open(BUY_PRICE_FILE, "r") as f:
                legacy_price = float(f.read().strip())
        except Exception:
            pass

    state = {
        "buy_price": legacy_price,
        "buy_time": None,
        "tranches_filled": 1 if legacy_price > 0 else 0,
        "max_pnl_seen": 0.0,
        "trailing_stop_pnl": None,
        "total_bnb_spent": 0.0
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
        with open(BUY_PRICE_FILE, "w") as f:
            f.write(str(state.get("buy_price", 0.0)))
    except Exception as e:
        logging.error(f"Error saving state: {e}")

def execute_buy(current_price, pct_of_balance=0.60, tranche_idx=1):
    if not PRIVATE_KEY or not WALLET_ADDRESS:
        logging.error("Missing credentials in .env")
        return None, 0.0, 0.0
    logging.info(f"Executing BUY (BNB -> RAVEN) - Tranche {tranche_idx}")
    try:
        router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        account = web3.eth.account.from_key(PRIVATE_KEY)
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        
        balance = web3.eth.get_balance(account.address)
        gas_reserve = web3.to_wei(0.015, 'ether') # 0.015 BNB kept for gas
        
        if balance <= gas_reserve:
            logging.info("Not enough BNB above gas reserve to buy.")
            return None, 0.0, 0.0
            
        tradeable_bnb = balance - gas_reserve
        amount_to_buy = int(tradeable_bnb * pct_of_balance)
        if amount_to_buy <= 0:
            return None, 0.0, 0.0
            
        raven_before = raven_contract.functions.balanceOf(account.address).call() / (10**18)
        
        tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            0,
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
        
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt['status'] != 1:
            raise Exception("Transacción fallida en la blockchain.")
            
        raven_after = raven_contract.functions.balanceOf(account.address).call() / (10**18)
        tokens_received = raven_after - raven_before
        human_bnb = amount_to_buy / (10**18)
        bnb_usd = get_bnb_usd()
            
        if tokens_received > 0:
            usd_spent = human_bnb * bnb_usd
            real_price = usd_spent / tokens_received
        else:
            real_price = current_price
            usd_spent = human_bnb * bnb_usd
            
        logging.info(f"Real buy price Tranche {tranche_idx}: ${real_price:.8f} (Tokens: {tokens_received:,.2f})")
        send_telegram_message(
            f"🟢 *COMPRA DE RAVEN EJECUTADA (Tramo {tranche_idx}/2)*\n"
            f"🔹 Inversión: `{human_bnb:.4f} BNB` (${usd_spent:.2f} USD)\n"
            f"🔹 Recibidos: `{tokens_received:,.2f} RAVEN`\n"
            f"📈 *Precio real tramo:* `${real_price:.8f}`\n"
            f"🔗 Hash: `{web3.to_hex(tx_hash)}`"
        )
        return real_price, tokens_received, human_bnb
    except Exception as e:
        logging.error(f"Buy execution failed: {e}")
        send_telegram_message(f"❌ *ERROR DE COMPRA RAVEN*\nDetalle: `{e}`")
        return None, 0.0, 0.0

def execute_sell(current_price, reason="Take Profit"):
    if not PRIVATE_KEY or not WALLET_ADDRESS:
        return False
    logging.info(f"Executing SELL (RAVEN -> BNB) | Reason: {reason}")
    try:
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        router = web3.eth.contract(address=web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        account = web3.eth.account.from_key(PRIVATE_KEY)
        
        balance = raven_contract.functions.balanceOf(account.address).call()
        if balance == 0:
            logging.info("No RAVEN to sell.")
            return False
            
        bnb_before = web3.eth.get_balance(account.address) / (10**18)

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
            time.sleep(10)
            
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
        
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt['status'] != 1:
            raise Exception("Transacción de venta fallida en la blockchain.")
            
        bnb_after = web3.eth.get_balance(account.address) / (10**18)
        bnb_received = bnb_after - bnb_before
        human_raven = balance / (10**18)
        bnb_usd = get_bnb_usd()
            
        usd_received = bnb_received * bnb_usd
        real_sell_price = (usd_received / human_raven) if human_raven > 0 else current_price
        
        send_telegram_message(
            f"🔴 *VENTA DE RAVEN EJECUTADA*\n"
            f"🔹 Motivo: `{reason}`\n"
            f"🔹 Tokens vendidos: `{human_raven:,.2f} RAVEN`\n"
            f"🔹 BNB recibido: `{bnb_received:.4f} BNB` (${usd_received:.2f} USD)\n"
            f"📈 *Precio real de venta:* `${real_sell_price:.8f}`\n"
            f"🔗 Hash: `{web3.to_hex(tx_hash)}`"
        )
        return True
    except Exception as e:
        logging.error(f"Sell execution failed: {e}")
        send_telegram_message(f"❌ *ERROR DE VENTA RAVEN*\nDetalle: `{e}`")
        return False

def main():
    logging.info("Starting RAVEN/BNB Swing Bot (Enhanced Engine with 2-Tranche DCA & Dynamic 15% / Trailing TP)...")
    send_telegram_message("🤖 *Raven Bot Iniciado (Motor Optimizado)*\n"
                          "🔹 Entrada flexible (RSI < 28, DCA en 2 tramos)\n"
                          "🔹 Take-Profit dinámico (+15% objetivo, trailing stop desde +10%)\n"
                          "🔹 Monitoreo On-Chain 15s de alta frecuencia activo.")
    
    state_data = load_state()
    consecutive_errors = 0
    
    while True:
        try:
            account = web3.eth.account.from_key(PRIVATE_KEY)
            
            raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
            raven_wei = raven_contract.functions.balanceOf(account.address).call()
            raven_balance = raven_wei / (10**18)
            
            bnb_wei = web3.eth.get_balance(account.address)
            bnb_balance = bnb_wei / (10**18)
            
            state = "WAITING_BUY"
            if raven_balance > 100000:
                state = "WAITING_SELL"
            else:
                if state_data.get("buy_price", 0.0) > 0 and state_data.get("tranches_filled", 0) > 0:
                    state_data = {
                        "buy_price": 0.0,
                        "buy_time": None,
                        "tranches_filled": 0,
                        "max_pnl_seen": 0.0,
                        "trailing_stop_pnl": None,
                        "total_bnb_spent": 0.0
                    }
                    save_state(state_data)
            
            closes = fetch_dex_prices()
            if len(closes) > 15:
                rsi = calculate_rsi(closes)
                current_price = closes[-1]
                buy_price = state_data.get("buy_price", 0.0)
                profit_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0
                
                logging.info(f"RAVEN: ${current_price:.8f} | RSI: {rsi:.2f} | State: {state} (Tranches: {state_data.get('tranches_filled', 0)}/2) | PnL: {profit_pct:+.2f}% | RAVEN: {raven_balance:.0f} | BNB: {bnb_balance:.4f}")
                
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
                
                fetch_and_log_macro()
                
                # --- WAITING_BUY (Tranche 1) ---
                if state == "WAITING_BUY":
                    if bnb_balance > 0.03: # Minimum BNB to trade safely with gas
                        # Relaxed threshold to 28 (from 25)
                        if rsi < 28:
                            logging.info("RSI below 28. Executing Tranche 1 Buy (60% of BNB)...")
                            real_price, tokens, bnb_spent = execute_buy(current_price, pct_of_balance=0.60, tranche_idx=1)
                            if real_price:
                                state_data["buy_price"] = real_price
                                state_data["buy_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                state_data["tranches_filled"] = 1
                                state_data["max_pnl_seen"] = 0.0
                                state_data["trailing_stop_pnl"] = None
                                state_data["total_bnb_spent"] = bnb_spent
                                save_state(state_data)
                                state = "WAITING_SELL"
                    else:
                        logging.info("Not enough BNB above gas reserve to trade.")
                        
                # --- WAITING_SELL (Tranche 2 & Exits) ---
                elif state == "WAITING_SELL":
                    # Check Tranche 2 scale-in
                    tranches = state_data.get("tranches_filled", 1)
                    if tranches < 2 and bnb_balance > 0.03:
                        if (profit_pct <= -6.0 and rsi < 35) or rsi < 25:
                            logging.info(f"DCA condition met for RAVEN Tranche 2. PnL: {profit_pct:.2f}% | RSI: {rsi:.2f}. Executing Buy...")
                            real_price2, tokens2, bnb_spent2 = execute_buy(current_price, pct_of_balance=0.90, tranche_idx=2)
                            if real_price2:
                                old_price = state_data.get("buy_price", real_price2)
                                old_tokens = raven_balance
                                new_total_tokens = old_tokens + tokens2
                                new_avg_price = ((old_tokens * old_price) + (tokens2 * real_price2)) / new_total_tokens if new_total_tokens > 0 else real_price2
                                
                                state_data["buy_price"] = new_avg_price
                                state_data["tranches_filled"] = 2
                                state_data["total_bnb_spent"] = state_data.get("total_bnb_spent", 0.0) + bnb_spent2
                                save_state(state_data)
                                
                                logging.info(f"Tranche 2 RAVEN Success: New Avg Price: ${new_avg_price:.8f}")
                                send_telegram_message(
                                    f"🟢 *COMPRA RAVEN (Tramo 2/2 DCA EJECUTADO)*\n"
                                    f"🔹 Inversión: `{bnb_spent2:.4f} BNB`\n"
                                    f"🔹 Tokens agregados: `{tokens2:,.2f} RAVEN`\n"
                                    f"📊 *Precio Promedio Ponderado:* `${new_avg_price:.8f}`"
                                )
                                profit_pct = ((current_price - new_avg_price) / new_avg_price) * 100

                    # Standard 15m candle exit evaluation
                    sell_reason = None
                    if profit_pct >= 15.0:
                        sell_reason = f"Target de ganancia alcanzado (+{profit_pct:.2f}% >= +15.0%)"
                    elif rsi >= 72 and profit_pct >= 3.0:
                        sell_reason = f"Sobrecompra RSI ({rsi:.2f} >= 72 y PnL +{profit_pct:.2f}%)"
                        
                    if sell_reason:
                        logging.info(f"15m Sell condition met: {sell_reason}")
                        if execute_sell(current_price, reason=sell_reason):
                            state_data = {
                                "buy_price": 0.0,
                                "buy_time": None,
                                "tranches_filled": 0,
                                "max_pnl_seen": 0.0,
                                "trailing_stop_pnl": None,
                                "total_bnb_spent": 0.0
                            }
                            save_state(state_data)
                            state = "WAITING_BUY"
            else:
                logging.warning("Not enough data to calculate RSI yet.")
                
            consecutive_errors = 0
            
            # --- High-Frequency On-Chain Monitoring (15s spot check) ---
            if state == "WAITING_SELL":
                buy_price = state_data.get("buy_price", 0.0)
                logging.info(f"⚡ Holding RAVEN: Entering 15s high-frequency on-chain monitoring (Entry: ${buy_price:.8f})...")
                start_cycle = time.time()
                check_count = 0
                while (time.time() - start_cycle) < 900:
                    time.sleep(15)
                    check_count += 1
                    try:
                        spot_price = fetch_onchain_spot_price()
                        if spot_price and buy_price > 0:
                            profit_pct = ((spot_price - buy_price) / buy_price) * 100
                            
                            # Track high water mark
                            if profit_pct > state_data.get("max_pnl_seen", 0.0):
                                state_data["max_pnl_seen"] = profit_pct
                                if profit_pct >= 10.0:
                                    state_data["trailing_stop_pnl"] = max(state_data.get("trailing_stop_pnl") or 0.0, profit_pct - 4.0)
                                save_state(state_data)
                            
                            if check_count % 4 == 0:
                                t_stop = f" | Trailing Stop: +{state_data['trailing_stop_pnl']:.1f}%" if state_data.get('trailing_stop_pnl') else ""
                                logging.info(f"[On-Chain Monitor] Spot: ${spot_price:.8f} | Profit: {profit_pct:+.2f}% (Peak: +{state_data.get('max_pnl_seen', 0.0):.2f}%{t_stop})")
                            
                            fast_exit_reason = None
                            if profit_pct >= 15.0:
                                fast_exit_reason = f"Take-Profit en tiempo real (+{profit_pct:.2f}% >= +15%)"
                            elif state_data.get("trailing_stop_pnl") is not None and profit_pct <= state_data["trailing_stop_pnl"]:
                                fast_exit_reason = f"Trailing Stop Activado (+{profit_pct:.2f}%, pico fue +{state_data['max_pnl_seen']:.2f}%)"
                                
                            if fast_exit_reason:
                                logging.info(f"🎯 TRIGGER DISPARADO ON-CHAIN: {fast_exit_reason}")
                                send_telegram_message(
                                    f"⚡ *TAKE PROFIT DISPARADO EN TIEMPO REAL*\n"
                                    f"Mechazo detectado on-chain en PancakeSwap.\n"
                                    f"🔹 Motivo: `{fast_exit_reason}`\n"
                                    f"🔹 Precio Spot: `${spot_price:.8f}`\n"
                                    f"🔹 Precio de Entrada: `${buy_price:.8f}`\n"
                                    f"📈 Ganancia: `+{profit_pct:.2f}%`\n"
                                    f"🚀 Ejecutando venta inmediata..."
                                )
                                if execute_sell(spot_price, reason=fast_exit_reason):
                                    state_data = {
                                        "buy_price": 0.0,
                                        "buy_time": None,
                                        "tranches_filled": 0,
                                        "max_pnl_seen": 0.0,
                                        "trailing_stop_pnl": None,
                                        "total_bnb_spent": 0.0
                                    }
                                    save_state(state_data)
                                    state = "WAITING_BUY"
                                    break
                    except Exception as e_fast:
                        logging.warning(f"Warning in fast on-chain check: {e_fast}")
            else:
                time.sleep(900)
                
        except Exception as e:
            error_msg = str(e)
            consecutive_errors += 1
            retry_delays = [2, 10, 60]
            if consecutive_errors == len(retry_delays) + 1:
                logging.error(f"Error persistente in main loop: {error_msg}")
                send_telegram_message(f"⚠️ *ALERTA (RAVEN BOT)* ⚠️\n`{error_msg}`")
                time.sleep(60)
            elif consecutive_errors > len(retry_delays) + 1:
                time.sleep(60)
            else:
                delay = retry_delays[consecutive_errors - 1]
                time.sleep(delay)

if __name__ == "__main__":
    main()
