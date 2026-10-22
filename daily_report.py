import os
import sys
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
PAPER_STATE_FILE = "/home/vale/paper_bot_state.json"
PI_STATE_FILE = "/home/vale/.pi_state.json"
RAVEN_STATE_FILE = "/home/vale/.raven_state.json"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        res = requests.post(url, json=payload, timeout=8)
        return res.json().get("ok", False)
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def safe_float(val, default=0.0):
    try:
        return float(val)
    except:
        return default

def get_last_clean_log(service_name):
    try:
        res = subprocess.run(
            ["journalctl", "-u", service_name, "-n", "1", "--no-pager", "-o", "cat"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5
        )
        line = res.stdout.strip()
        if " - INFO - " in line:
            line = line.split(" - INFO - ")[-1]
        elif " - WARNING - " in line:
            line = line.split(" - WARNING - ")[-1]
        elif " - ERROR - " in line:
            line = line.split(" - ERROR - ")[-1]
        line = line.replace("`", "")
        if len(line) > 55:
            line = line[:52] + "..."
        return line if line else "Operando normalmente"
    except Exception:
        return "Operando normalmente"

def calculate_variations(current_capital):
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(CAPITAL_FILE):
        with open(CAPITAL_FILE, 'r') as f:
            data = json.load(f)
    else:
        data = {"initial_capital": current_capital, "history": {}}

    history = data.get("history", {})
    initial_capital = data.get("initial_capital", current_capital)

    def calc_pct(old, new):
        if not old or old == 0: return 0.0
        return ((new - old) / old) * 100

    prev_dates = [d for d in sorted(history.keys()) if d < today]
    cap_previous = history[prev_dates[-1]] if prev_dates else initial_capital

    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week_candidates = [d for d in sorted(history.keys()) if d <= seven_days_ago]
    cap_last_week = history[week_candidates[-1]] if week_candidates else initial_capital

    pct_daily = calc_pct(cap_previous, current_capital)
    pct_weekly = calc_pct(cap_last_week, current_capital)
    pct_total = calc_pct(initial_capital, current_capital)

    history[today] = current_capital
    data["history"] = history
    with open(CAPITAL_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    return pct_daily, pct_weekly, pct_total, initial_capital

def fetch_data():
    web3 = Web3(Web3.HTTPProvider(BSC_RPC))
    msg = "📊 *REPORTE DIARIO DE INVERSIONES* 📊\n\n"
    total_capital = 0.0

    exchange = ccxt.bitget({
        'apiKey': os.getenv('BITGET_API_KEY'),
        'secret': os.getenv('BITGET_SECRET'),
        'password': os.getenv('BITGET_PASSWORD'),
        'enableRateLimit': True,
    })

    try:
        price_bnb = exchange.fetch_ticker('BNB/USDT')['last']
    except:
        price_bnb = 740.0

    # ================= 1. RAVEN BOT (PancakeSwap DEX) =================
    try:
        raven_contract = web3.eth.contract(address=web3.to_checksum_address(RAVEN_ADDRESS), abi=ERC20_ABI)
        balance_raven = raven_contract.functions.balanceOf(web3.to_checksum_address(WALLET_ADDRESS)).call() / (10**18)
        bnb_balance = web3.eth.get_balance(web3.to_checksum_address(WALLET_ADDRESS)) / (10**18)
        
        price_raven = 0.0
        try:
            res = requests.get("https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x547037d9d7ac11cb2740727a7f4ca41111d7e608", timeout=8).json()
            price_raven = float(res['data']['attributes']['base_token_price_usd'])
        except Exception:
            pass

        if price_raven == 0:
            try:
                router_address = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
                wbnb_address = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
                router_abi = [{"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}]
                router = web3.eth.contract(address=web3.to_checksum_address(router_address), abi=router_abi)
                out = router.functions.getAmountsOut(10**18, [web3.to_checksum_address(RAVEN_ADDRESS), web3.to_checksum_address(wbnb_address)]).call()
                bnb_per_raven = out[1] / (10**18)
                price_raven = bnb_per_raven * price_bnb
            except Exception:
                pass

        val_raven_usd = balance_raven * price_raven
        val_bnb_usd = bnb_balance * price_bnb
        capital_raven = val_raven_usd + val_bnb_usd
        total_capital += capital_raven

        log_raven = get_last_clean_log("ravenbot")

        msg += "🦅 *RAVEN BOT (PancakeSwap)*\n"
        if balance_raven > 100000:
            msg += f"🔹 RAVEN: `{balance_raven:,.2f}` (${val_raven_usd:,.2f} USD)\n"
            msg += f"🔹 BNB Gas: `{bnb_balance:.4f}` (${val_bnb_usd:,.2f} USD)\n"
        else:
            msg += f"🔹 Estado: `En Liquidez (Esperando Compra)`\n"
            msg += f"🔹 Capital: `{bnb_balance:.4f} BNB` (${val_bnb_usd:,.2f} USD)\n"
        msg += f"📈 Precio: `${price_raven:.8f}`\n"
        msg += f"📝 Estado: `{log_raven}`\n\n"
    except Exception as e:
        msg += f"🦅 *RAVEN BOT:* Error al cargar (`{e}`)\n\n"

    # ================= 2. PI BOT (Bitget Spot) =================
    try:
        balance = exchange.fetch_balance()
        pi_balance = balance['total'].get('PI', 0.0)
        usdt_total_free = balance['total'].get('USDT', 0.0)
        
        ticker_pi = exchange.fetch_ticker('PI/USDT')
        price_pi = ticker_pi['last']
        val_pi_usdt = pi_balance * price_pi
        total_capital += val_pi_usdt
        
        buy_p_pi = 0.0
        days_held_pi = 0.0
        tranches_pi = 1
        if os.path.exists(PI_STATE_FILE):
            try:
                with open(PI_STATE_FILE) as f:
                    p_st = json.load(f)
                    buy_p_pi = safe_float(p_st.get("buy_price", 0.0))
                    tranches_pi = p_st.get("tranches_filled", 1)
                    if p_st.get("buy_time"):
                        b_dt = datetime.strptime(p_st["buy_time"].split(".")[0], "%Y-%m-%d %H:%M:%S")
                        days_held_pi = (datetime.now() - b_dt).total_seconds() / 86400.0
            except:
                pass
                
        pnl_pi = ((price_pi - buy_p_pi) / buy_p_pi) * 100 if buy_p_pi > 0 else 0.0
        log_pi = get_last_clean_log("pibot")
        
        msg += "🟣 *PI BOT (Bitget Spot)*\n"
        if pi_balance > 10:
            pnl_icon = "🟢" if pnl_pi >= 0 else "🔴"
            msg += f"🔹 PI: `{pi_balance:,.2f}` (${val_pi_usdt:,.2f} USDT) [Tramo {tranches_pi}/2]\n"
            msg += f"🔹 PnL Posición: `{pnl_pi:+.2f}%` {pnl_icon} (Entrada: ${buy_p_pi:.4f})\n"
            if days_held_pi > 0:
                msg += f"⏱ Retención: `{days_held_pi:.1f} días`\n"
        else:
            msg += f"🔹 Estado: `En Liquidez (Esperando Compra)`\n"
            msg += f"🔹 Presupuesto Asignado: `65.00 USDT`\n"
        msg += f"📈 Precio: `${price_pi:.4f}`\n"
        msg += f"📝 Estado: `{log_pi}`\n\n"
    except Exception as e:
        msg += f"🟣 *PI BOT:* Error al cargar (`{e}`)\n\n"

    # ================= 3 & 4. SUI & PEPE BOTS (Bitget Spot) =================
    paper_state = {}
    if os.path.exists(PAPER_STATE_FILE):
        try:
            with open(PAPER_STATE_FILE) as f:
                paper_state = json.load(f)
        except:
            pass

    # --- 3. SUI BOT ---
    try:
        sui_balance = balance['total'].get('SUI', 0.0)
        ticker_sui = exchange.fetch_ticker('SUI/USDT')
        price_sui = ticker_sui['last']
        val_sui = sui_balance * price_sui
        total_capital += val_sui
        
        sui_st = paper_state.get("SUI/USDT", {})
        sui_mode = sui_st.get("mode", "REAL")
        sui_buy_p = safe_float(sui_st.get("buy_price", 0.0))
        sui_tranches = sui_st.get("tranches_filled", 0)
        sui_usdt_alloc = safe_float(sui_st.get("usdt_balance", 110.0))
        
        msg += f"🟢 *SUI BOT (Bitget Spot - {sui_mode})*\n"
        if sui_balance > 1.0 or (sui_st.get("state") == "WAITING_SELL" and sui_buy_p > 0):
            pnl_sui = ((price_sui - sui_buy_p) / sui_buy_p) * 100 if sui_buy_p > 0 else 0.0
            pnl_icon = "🟢" if pnl_sui >= 0 else "🔴"
            msg += f"🔹 SUI: `{sui_balance:,.2f}` (${val_sui:,.2f} USDT) [Tramo {sui_tranches}/3]\n"
            msg += f"🔹 PnL Posición: `{pnl_sui:+.2f}%` {pnl_icon} (Entrada: ${sui_buy_p:.4f})\n"
        else:
            msg += f"🔹 Estado: `En Liquidez (Esperando Compra)`\n"
            msg += f"🔹 Presupuesto Asignado: `${sui_usdt_alloc:,.2f} USDT`\n"
        msg += f"📈 Precio: `${price_sui:.4f}`\n\n"
    except Exception as e:
        msg += f"🟢 *SUI BOT:* Error al cargar (`{e}`)\n\n"

    # --- 4. PEPE BOT ---
    try:
        pepe_balance = balance['total'].get('PEPE', 0.0)
        ticker_pepe = exchange.fetch_ticker('PEPE/USDT')
        price_pepe = ticker_pepe['last']
        val_pepe = pepe_balance * price_pepe
        total_capital += val_pepe
        
        pepe_st = paper_state.get("PEPE/USDT", {})
        pepe_mode = pepe_st.get("mode", "REAL")
        pepe_buy_p = safe_float(pepe_st.get("buy_price", 0.0))
        pepe_tranches = pepe_st.get("tranches_filled", 0)
        pepe_usdt_alloc = safe_float(pepe_st.get("usdt_balance", 80.0))
        
        msg += f"🐸 *PEPE BOT (Bitget Spot - {pepe_mode})*\n"
        if pepe_balance > 1000 or (pepe_st.get("state") == "WAITING_SELL" and pepe_buy_p > 0):
            pnl_pepe = ((price_pepe - pepe_buy_p) / pepe_buy_p) * 100 if pepe_buy_p > 0 else 0.0
            pnl_icon = "🟢" if pnl_pepe >= 0 else "🔴"
            msg += f"🔹 PEPE: `{pepe_balance:,.0f}` (${val_pepe:,.2f} USDT) [Tramo {pepe_tranches}/3]\n"
            msg += f"🔹 PnL Posición: `{pnl_pepe:+.2f}%` {pnl_icon} (Entrada: ${pepe_buy_p:.8f})\n"
        else:
            msg += f"🔹 Estado: `En Liquidez (Esperando Compra)`\n"
            msg += f"🔹 Presupuesto Asignado: `${pepe_usdt_alloc:,.2f} USDT`\n"
        msg += f"📈 Precio: `${price_pepe:.8f}`\n\n"
    except Exception as e:
        msg += f"🐸 *PEPE BOT:* Error al cargar (`{e}`)\n\n"

    # ================= 5. LIQUIDEZ Y PORTFOLIO SUMMARY =================
    total_capital += usdt_total_free
    msg += f"💵 *USDT Total en Bitget:* `${usdt_total_free:,.2f} USDT`\n"
    msg += f"   *(Asignado: $110.00 SUI | $80.00 PEPE)*\n\n"

    pct_daily, pct_weekly, pct_total, initial_cap = calculate_variations(total_capital)
    
    def fmt_pct(val):
        return f"+{val:.2f}% 🟢" if val > 0 else f"{val:.2f}% 🔴" if val < 0 else "0.00% ⚪"

    msg += "💰 *RESUMEN DE CAPITAL* 💰\n"
    msg += f"💵 *Total USD Cartera:* `${total_capital:,.2f}`\n"
    msg += f"📅 24 Horas: `{fmt_pct(pct_daily)}`\n"
    msg += f"📆 7 Días: `{fmt_pct(pct_weekly)}`\n"
    msg += f"📈 Rendimiento Total: `{fmt_pct(pct_total)}` (Base: ${initial_cap:,.2f})\n"

    return msg

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        msg = fetch_data()
        print(msg)
        return

    for attempt in range(3):
        try:
            msg = fetch_data()
            if send_telegram_message(msg):
                return
            time.sleep(10)
        except Exception:
            time.sleep(60)
            
    send_telegram_message("⚠️ *ERROR EN REPORTE DIARIO* ⚠️\nNo se pudo conectar a la red después de 3 intentos.")

if __name__ == "__main__":
    main()
