#!/usr/bin/env python3
"""
Netbook Trading Data Lake Collector
Ultra-lightweight market data collector designed for Intel Atom N2600.
Captures 1m candles, orderbook depth, and macro metrics into an optimized SQLite WAL database.
Resource budget: <30MB RAM, <0.2% CPU average, batch WAL disk writes once per minute.
"""

import os
import sys
import time
import json
import sqlite3
import logging
from datetime import datetime, timezone
import requests
import ccxt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

DATA_DIR = "/home/vale/data"
DB_PATH = os.path.join(DATA_DIR, "market_datalake.db")

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Optimize SQLite for high-efficiency, low-wear flash/HDD storage
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("PRAGMA cache_size = -2000;")  # 2MB limit
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS candles_1m (
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            best_bid REAL NOT NULL,
            best_ask REAL NOT NULL,
            spread_bps REAL NOT NULL,
            bid_depth_usd REAL NOT NULL,
            ask_depth_usd REAL NOT NULL,
            PRIMARY KEY (symbol, timestamp)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS macro_metrics (
            timestamp TEXT PRIMARY KEY,
            btc_price REAL NOT NULL,
            btc_dominance REAL,
            fear_and_greed INTEGER
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_candles_time ON candles_1m (timestamp);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_time ON orderbook_snapshots (timestamp);")

    conn.commit()
    conn.close()
    logging.info(f"Database initialized in WAL mode at {DB_PATH}")

_last_macro_time = 0
_cached_macro = {"btc_dominance": None, "fear_and_greed": None}

def fetch_macro_data(btc_price):
    global _last_macro_time, _cached_macro
    now = time.time()
    if now - _last_macro_time > 900:  # Refresh dominance & sentiment every 15 min
        try:
            r = requests.get("https://api.coingecko.com/api/v3/global", timeout=4)
            if r.status_code == 200:
                _cached_macro["btc_dominance"] = round(r.json().get("data", {}).get("market_cap_percentage", {}).get("btc", 0), 2)
        except Exception:
            pass

        try:
            r = requests.get("https://api.alternative.me/fng/", timeout=4)
            if r.status_code == 200:
                _cached_macro["fear_and_greed"] = int(r.json().get("data", [{}])[0].get("value", 0))
        except Exception:
            pass

        _last_macro_time = now

    return {
        "btc_price": btc_price,
        "btc_dominance": _cached_macro["btc_dominance"],
        "fear_and_greed": _cached_macro["fear_and_greed"]
    }

def main():
    logging.info("Starting Netbook Trading Data Lake Collector (Low-Resource Engine)...")
    init_db()

    bitget = ccxt.bitget({
        'enableRateLimit': True,
        'timeout': 6000,
    })

    bitget_symbols = ['PEPE/USDT', 'SUI/USDT', 'PI/USDT']

    while True:
        cycle_start = time.time()
        now_dt = datetime.now()
        minute_str = now_dt.strftime("%Y-%m-%d %H:%M:00")

        candle_records = []
        orderbook_records = []
        btc_price = 0.0

        # 1. Collect Bitget Pairs
        for sym in bitget_symbols:
            try:
                # Fetch recent 1m OHLCV candle
                ohlcv = bitget.fetch_ohlcv(sym, timeframe='1m', limit=2)
                if ohlcv and len(ohlcv) >= 1:
                    last_c = ohlcv[-1]
                    c_time = datetime.fromtimestamp(last_c[0] / 1000.0).strftime("%Y-%m-%d %H:%M:00")
                    candle_records.append((c_time, sym, float(last_c[1]), float(last_c[2]), float(last_c[3]), float(last_c[4]), float(last_c[5])))

                # Fetch 5-level Orderbook
                ob = bitget.fetch_order_book(sym, limit=5)
                bids = ob.get('bids', [])
                asks = ob.get('asks', [])

                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread_bps = round(((best_ask - best_bid) / best_bid) * 10000, 2) if best_bid > 0 else 0.0
                    bid_depth = round(sum(p * a for p, a in bids[:5]), 2)
                    ask_depth = round(sum(p * a for p, a in asks[:5]), 2)

                    orderbook_records.append((minute_str, sym, best_bid, best_ask, spread_bps, bid_depth, ask_depth))

            except Exception as e:
                logging.warning(f"Error collecting Bitget data for {sym}: {e}")

        # 2. Collect BTC Price for Macro
        try:
            btc_ticker = bitget.fetch_ticker('BTC/USDT')
            btc_price = float(btc_ticker.get('last', 0.0))
        except Exception:
            try:
                r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=3).json()
                btc_price = float(r.get("price", 0.0))
            except Exception:
                pass

        # 3. Collect RAVEN / BNB DEX Pool Data
        try:
            dex_url = "https://api.geckoterminal.com/api/v2/networks/bsc/pools/0x547037d9d7ac11cb2740727a7f4ca41111d7e608"
            r = requests.get(dex_url, timeout=5).json()
            attr = r.get("data", {}).get("attributes", {})
            r_price = float(attr.get("base_token_price_usd", 0.0))
            r_vol = float(attr.get("volume_usd", {}).get("m5", 0.0)) / 5.0  # approximate 1m vol
            if r_price > 0:
                candle_records.append((minute_str, 'RAVEN/BNB', r_price, r_price, r_price, r_price, r_vol))
                orderbook_records.append((minute_str, 'RAVEN/BNB', r_price, r_price, 0.0, 0.0, 0.0))
        except Exception as e:
            logging.warning(f"Error collecting RAVEN DEX data: {e}")

        # 4. Atomic Batch Insert to SQLite
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            if candle_records:
                cur.executemany("""
                    INSERT OR REPLACE INTO candles_1m (timestamp, symbol, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, candle_records)

            if orderbook_records:
                cur.executemany("""
                    INSERT OR REPLACE INTO orderbook_snapshots (timestamp, symbol, best_bid, best_ask, spread_bps, bid_depth_usd, ask_depth_usd)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, orderbook_records)

            if btc_price > 0:
                macro = fetch_macro_data(btc_price)
                cur.execute("""
                    INSERT OR REPLACE INTO macro_metrics (timestamp, btc_price, btc_dominance, fear_and_greed)
                    VALUES (?, ?, ?, ?);
                """, (minute_str, macro["btc_price"], macro["btc_dominance"], macro["fear_and_greed"]))

            conn.commit()
            conn.close()
            import gc
            gc.collect()

        except Exception as e:
            logging.error(f"Database write error: {e}")

        # 5. Sleep until next minute mark (target 60s cadence)
        elapsed = time.time() - cycle_start
        sleep_time = max(5.0, 60.0 - elapsed)
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
