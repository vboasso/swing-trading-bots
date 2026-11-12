import os
import sys
import sqlite3
import requests
from datetime import datetime

TELEGRAM_TOKEN = "8864696569:AAH77c3tRbpYpDdaccF2q_pVtwf6pXy1U5A"
TELEGRAM_CHAT_ID = "305025287"
DB_PATH = "/home/vale/data/market_datalake.db"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error sending telegram: {e}")
        return False

def generate_report():
    if not os.path.exists(DB_PATH):
        return "Data Lake DB not found"

    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    candles = cur.execute("SELECT count(*) FROM candles_1m").fetchone()[0]
    orderbooks = cur.execute("SELECT count(*) FROM orderbook_snapshots").fetchone()[0]
    macros = cur.execute("SELECT count(*) FROM macro_metrics").fetchone()[0]
    
    first_ts = cur.execute("SELECT min(timestamp) FROM candles_1m").fetchone()[0]
    last_ts = cur.execute("SELECT max(timestamp) FROM candles_1m").fetchone()[0]
    conn.close()

    days_collected = 0.0
    if first_ts and last_ts:
        try:
            d1 = datetime.fromisoformat(first_ts)
            d2 = datetime.fromisoformat(last_ts)
            days_collected = round((d2 - d1).total_seconds() / 86400, 2)
        except Exception:
            pass

    msg = (
        "🎯 *RECORDATORIO DE RECALIBRACIÓN DE BOTS* 🎯\n\n"
        f"El *Market Data Lake* ha alcanzado el hito de evaluación programada ({days_collected} días acumulados):\n\n"
        f"📊 *Velas 1m capturadas:* `{candles:,}`\n"
        f"📖 *Snapshots Orderbook:* `{orderbooks:,}`\n"
        f"🌐 *Métricas Macro:* `{macros:,}`\n"
        f"💾 *Tamaño en Disco:* `{size_mb:.2f} MB`\n\n"
        "💡 *Objetivos de optimización:*\n"
        "1. **SUI & PEPE:** Volatilidad real empírica vs espaciado de tranches DCA.\n"
        "2. **RAVEN/BNB:** Profundidad de liquidez en PancakeSwap, spread real y slippage.\n"
        "3. **SOL/USDT:** Evaluar velas de 5m vs 15m, Trailing Stop y gatillos RSI.\n\n"
        "🚀 _Listo para correr el análisis cuantitativo con Antigravity._"
    )
    return msg

def main():
    msg = generate_report()
    if len(sys.argv) > 1 and sys.argv[1] == "--preview":
        print(msg)
    else:
        success = send_telegram_message(msg)
        print("Sent successfully!" if success else "Failed to send.")

if __name__ == "__main__":
    main()
