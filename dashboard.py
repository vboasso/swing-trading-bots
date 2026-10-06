#!/usr/bin/env python3
"""
Netbook Trading Command Center - Dashboard
Lightweight, zero-dependency real-time web monitor for Swing Trading Bots:
- PI/USDT (Bitget - Real)
- RAVEN/BNB (PancakeSwap DEX - Real)
- SUI/USDT (Bitget - Paper Sim)
- PEPE/USDT (Bitget - Paper Sim)

Runs on Python's built-in ThreadingHTTPServer on port 5000.
"""

import os
import sys
import json
import time
from datetime import datetime
import http.server
import socketserver

PORT = 5000
BASE_DIR = "/home/vale"
PI_HISTORY = os.path.join(BASE_DIR, "pibot_history.csv")
PI_BUY_PRICE = os.path.join(BASE_DIR, ".pi_buy_price")
RAVEN_HISTORY = os.path.join(BASE_DIR, "bot_history.csv")
RAVEN_BUY_PRICE = os.path.join(BASE_DIR, ".raven_buy_price")
PAPER_STATE = os.path.join(BASE_DIR, "paper_bot_state.json")
PAPER_HISTORY = os.path.join(BASE_DIR, "paper_bot_history.csv")
CAPITAL_HISTORY = os.path.join(BASE_DIR, ".capital_history.json")
TUNNEL_FILE = os.path.join(BASE_DIR, "tunnel_url.txt")


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def read_last_lines(filepath, count=10):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
            return lines[-count:]
    except Exception:
        return []


def read_entry_price(filepath):
    if not os.path.exists(filepath):
        return 0.0
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return safe_float(f.read().strip())
    except Exception:
        return 0.0


def get_system_stats():
    res = {
        "uptime": "N/A",
        "load": [0.0, 0.0, 0.0],
        "ram_total_mb": 0,
        "ram_used_mb": 0,
        "ram_pct": 0.0,
    }
    try:
        if hasattr(os, "getloadavg"):
            load = os.getloadavg()
            res["load"] = [round(x, 2) for x in load]
    except Exception:
        pass

    try:
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime", "r") as f:
                secs = float(f.readline().split()[0])
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                if h >= 24:
                    d = h // 24
                    h = h % 24
                    res["uptime"] = f"{d}d {h}h {m}m"
                else:
                    res["uptime"] = f"{h}h {m}m"
    except Exception:
        pass

    try:
        if os.path.exists("/proc/meminfo"):
            mem = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(parts[1].split()[0])
            total = mem.get("MemTotal", 0) // 1024
            avail = mem.get("MemAvailable", 0) // 1024
            used = max(0, total - avail)
            res["ram_total_mb"] = total
            res["ram_used_mb"] = used
            res["ram_pct"] = round((used / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        pass

    return res


def get_all_bot_data():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- 1. PI / USDT ---
    pi_data = {
        "id": "pi",
        "name": "Pi Network",
        "symbol": "PI/USDT",
        "mode": "REAL",
        "exchange": "Bitget",
        "price": 0.0,
        "price_formatted": "$0.00",
        "rsi": 50.0,
        "state": "UNKNOWN",
        "state_label": "Desconocido",
        "buy_price": 0.0,
        "buy_price_formatted": "$0.00",
        "pnl_pct": 0.0,
        "token_balance": 0.0,
        "quote_balance": 0.0,
        "token_symbol": "PI",
        "quote_symbol": "USDT",
        "last_update": "N/A",
        "history": [],
    }

    pi_entry = read_entry_price(PI_BUY_PRICE)
    pi_data["buy_price"] = pi_entry
    pi_data["buy_price_formatted"] = f"${pi_entry:.4f}" if pi_entry > 0 else "—"

    pi_lines = read_last_lines(PI_HISTORY, 15)
    if pi_lines:
        # Check header
        data_lines = [l for l in pi_lines if not l.startswith("timestamp")]
        if data_lines:
            last = data_lines[-1].split(",")
            if len(last) >= 6:
                pi_data["last_update"] = last[0]
                pi_data["price"] = safe_float(last[1])
                pi_data["price_formatted"] = f"${safe_float(last[1]):.4f}"
                pi_data["rsi"] = safe_float(last[2])
                pi_data["state"] = last[3]
                pi_data["token_balance"] = safe_float(last[4])
                pi_data["quote_balance"] = safe_float(last[5])

                if pi_data["state"] == "WAITING_SELL":
                    pi_data["state_label"] = "En Posición (Esperando Venta)"
                    if pi_entry > 0 and pi_data["price"] > 0:
                        pi_data["pnl_pct"] = round(((pi_data["price"] - pi_entry) / pi_entry) * 100, 2)
                elif pi_data["state"] == "WAITING_BUY":
                    pi_data["state_label"] = "En Liquidez (Esperando Compra)"
                    pi_data["pnl_pct"] = 0.0

            # Parse last 5 for history table
            for row_str in data_lines[-5:]:
                parts = row_str.split(",")
                if len(parts) >= 6:
                    pi_data["history"].append({
                        "time": parts[0].split(" ")[-1] if " " in parts[0] else parts[0],
                        "price": f"${safe_float(parts[1]):.4f}",
                        "rsi": safe_float(parts[2]),
                        "state": parts[3],
                    })

    # --- 2. RAVEN / BNB ---
    raven_data = {
        "id": "raven",
        "name": "Raven",
        "symbol": "RAVEN/BNB",
        "mode": "REAL",
        "exchange": "PancakeSwap DEX",
        "price": 0.0,
        "price_formatted": "0.00 BNB",
        "rsi": 50.0,
        "state": "UNKNOWN",
        "state_label": "Desconocido",
        "buy_price": 0.0,
        "buy_price_formatted": "0.00 BNB",
        "pnl_pct": 0.0,
        "token_balance": 0.0,
        "quote_balance": 0.0,
        "token_symbol": "RAVEN",
        "quote_symbol": "BNB",
        "last_update": "N/A",
        "history": [],
    }

    raven_entry = read_entry_price(RAVEN_BUY_PRICE)
    raven_data["buy_price"] = raven_entry
    raven_data["buy_price_formatted"] = f"{raven_entry:.8f} BNB" if raven_entry > 0 else "—"

    raven_lines = read_last_lines(RAVEN_HISTORY, 15)
    if raven_lines:
        data_lines = [l for l in raven_lines if not l.startswith("timestamp")]
        if data_lines:
            last = data_lines[-1].split(",")
            if len(last) >= 6:
                raven_data["last_update"] = last[0]
                raven_data["price"] = safe_float(last[1])
                raven_data["price_formatted"] = f"{safe_float(last[1]):.8f} BNB"
                raven_data["rsi"] = safe_float(last[2])
                raven_data["state"] = last[3]
                raven_data["token_balance"] = safe_float(last[4])
                raven_data["quote_balance"] = safe_float(last[5])

                if raven_data["state"] == "WAITING_SELL":
                    raven_data["state_label"] = "En Posición (Esperando Venta)"
                    if raven_entry > 0 and raven_data["price"] > 0:
                        raven_data["pnl_pct"] = round(((raven_data["price"] - raven_entry) / raven_entry) * 100, 2)
                elif raven_data["state"] == "WAITING_BUY":
                    raven_data["state_label"] = "En Liquidez (Esperando Compra)"
                    raven_data["pnl_pct"] = 0.0

            for row_str in data_lines[-5:]:
                parts = row_str.split(",")
                if len(parts) >= 6:
                    raven_data["history"].append({
                        "time": parts[0].split(" ")[-1] if " " in parts[0] else parts[0],
                        "price": f"{safe_float(parts[1]):.8f}",
                        "rsi": safe_float(parts[2]),
                        "state": parts[3],
                    })

    # --- 3 & 4. SUI & PEPE (Paper Bot) ---
    paper_state_data = {}
    if os.path.exists(PAPER_STATE):
        try:
            with open(PAPER_STATE, "r", encoding="utf-8") as f:
                paper_state_data = json.load(f)
        except Exception:
            pass

    sui_data = {
        "id": "sui",
        "name": "Sui Network",
        "symbol": "SUI/USDT",
        "mode": "PAPER",
        "exchange": "Bitget (Sim)",
        "price": 0.0,
        "price_formatted": "$0.00",
        "rsi": 50.0,
        "state": "WAITING_BUY",
        "state_label": "En Liquidez (Esperando Compra)",
        "buy_price": 0.0,
        "buy_price_formatted": "—",
        "pnl_pct": 0.0,
        "token_balance": 0.0,
        "quote_balance": 200.0,
        "token_symbol": "SUI",
        "quote_symbol": "USDT",
        "trades_count": 0,
        "realized_pnl_usd": 0.0,
        "last_update": "N/A",
        "history": [],
    }

    pepe_data = {
        "id": "pepe",
        "name": "Pepe Meme",
        "symbol": "PEPE/USDT",
        "mode": "PAPER",
        "exchange": "Bitget (Sim)",
        "price": 0.0,
        "price_formatted": "$0.00",
        "rsi": 50.0,
        "state": "WAITING_BUY",
        "state_label": "En Liquidez (Esperando Compra)",
        "buy_price": 0.0,
        "buy_price_formatted": "—",
        "pnl_pct": 0.0,
        "token_balance": 0.0,
        "quote_balance": 200.0,
        "token_symbol": "PEPE",
        "quote_symbol": "USDT",
        "trades_count": 0,
        "realized_pnl_usd": 0.0,
        "last_update": "N/A",
        "history": [],
    }

    # Populate from state json if present
    if "SUI/USDT" in paper_state_data:
        s_info = paper_state_data["SUI/USDT"]
        sui_data["state"] = s_info.get("state", "WAITING_BUY")
        sui_data["token_balance"] = safe_float(s_info.get("token_balance", 0.0))
        sui_data["quote_balance"] = safe_float(s_info.get("usdt_balance", 200.0))
        s_buy = safe_float(s_info.get("buy_price", 0.0))
        sui_data["buy_price"] = s_buy
        sui_data["buy_price_formatted"] = f"${s_buy:.4f}" if s_buy > 0 else "—"
        sui_data["trades_count"] = s_info.get("trades_count", 0)
        sui_data["realized_pnl_usd"] = safe_float(s_info.get("realized_pnl_usd", 0.0))

    if "PEPE/USDT" in paper_state_data:
        p_info = paper_state_data["PEPE/USDT"]
        pepe_data["state"] = p_info.get("state", "WAITING_BUY")
        pepe_data["token_balance"] = safe_float(p_info.get("token_balance", 0.0))
        pepe_data["quote_balance"] = safe_float(p_info.get("usdt_balance", 200.0))
        p_buy = safe_float(p_info.get("buy_price", 0.0))
        pepe_data["buy_price"] = p_buy
        pepe_data["buy_price_formatted"] = f"${p_buy:.8f}" if p_buy > 0 else "—"
        pepe_data["trades_count"] = p_info.get("trades_count", 0)
        pepe_data["realized_pnl_usd"] = safe_float(p_info.get("realized_pnl_usd", 0.0))

    # Read paper_bot_history.csv
    paper_lines = read_last_lines(PAPER_HISTORY, 30)
    if paper_lines:
        data_lines = [l for l in paper_lines if not l.startswith("timestamp")]
        for row_str in data_lines:
            parts = row_str.split(",")
            if len(parts) >= 7:
                sym = parts[1]
                t_str = parts[0]
                p_val = safe_float(parts[2])
                r_val = safe_float(parts[3])
                st_val = parts[4]

                if sym == "SUI/USDT":
                    sui_data["last_update"] = t_str
                    sui_data["price"] = p_val
                    sui_data["price_formatted"] = f"${p_val:.4f}"
                    sui_data["rsi"] = r_val
                    sui_data["state"] = st_val
                    sui_data["state_label"] = "En Posición (Esperando Venta)" if st_val == "WAITING_SELL" else "En Liquidez (Esperando Compra)"
                    if st_val == "WAITING_SELL" and sui_data["buy_price"] > 0:
                        sui_data["pnl_pct"] = round(((p_val - sui_data["buy_price"]) / sui_data["buy_price"]) * 100, 2)
                    sui_data["history"].append({
                        "time": t_str.split(" ")[-1] if " " in t_str else t_str,
                        "price": f"${p_val:.4f}",
                        "rsi": r_val,
                        "state": st_val,
                    })

                elif sym == "PEPE/USDT":
                    pepe_data["last_update"] = t_str
                    pepe_data["price"] = p_val
                    pepe_data["price_formatted"] = f"${p_val:.8f}"
                    pepe_data["rsi"] = r_val
                    pepe_data["state"] = st_val
                    pepe_data["state_label"] = "En Posición (Esperando Venta)" if st_val == "WAITING_SELL" else "En Liquidez (Esperando Compra)"
                    if st_val == "WAITING_SELL" and pepe_data["buy_price"] > 0:
                        pepe_data["pnl_pct"] = round(((p_val - pepe_data["buy_price"]) / pepe_data["buy_price"]) * 100, 2)
                    pepe_data["history"].append({
                        "time": t_str.split(" ")[-1] if " " in t_str else t_str,
                        "price": f"${p_val:.8f}",
                        "rsi": r_val,
                        "state": st_val,
                    })

        sui_data["history"] = sui_data["history"][-5:]
        pepe_data["history"] = pepe_data["history"][-5:]

    # --- Capital Portfolio ---
    capital_info = {
        "initial": 307.19,
        "current": 324.57,
        "pnl_usd": 17.38,
        "pnl_pct": 5.66,
    }
    if os.path.exists(CAPITAL_HISTORY):
        try:
            with open(CAPITAL_HISTORY, "r", encoding="utf-8") as f:
                c_json = json.load(f)
                c_init = safe_float(c_json.get("initial_capital", 307.19))
                history_dict = c_json.get("history", {})
                if history_dict:
                    last_date = sorted(history_dict.keys())[-1]
                    c_curr = safe_float(history_dict[last_date], c_init)
                    capital_info["initial"] = round(c_init, 2)
                    capital_info["current"] = round(c_curr, 2)
                    diff = c_curr - c_init
                    capital_info["pnl_usd"] = round(diff, 2)
                    capital_info["pnl_pct"] = round((diff / c_init) * 100, 2) if c_init > 0 else 0.0
        except Exception:
            pass

    tunnel_url = ""
    if os.path.exists(TUNNEL_FILE):
        try:
            with open(TUNNEL_FILE, "r", encoding="utf-8") as f:
                tunnel_url = f.read().strip()
        except Exception:
            pass

    return {
        "timestamp": now_str,
        "system": get_system_stats(),
        "capital": capital_info,
        "tunnel_url": tunnel_url,
        "bots": [pi_data, raven_data, sui_data, pepe_data],
    }


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Netbook Swing Bots - Command Center</title>
  <style>
    :root {
      --bg-main: #0a0e17;
      --bg-card: #111827;
      --bg-card-hover: #162032;
      --bg-subtle: #1e293b;
      --border-card: #1f293d;
      --border-accent: #334155;
      
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      
      --accent-green: #10b981;
      --accent-green-glow: rgba(16, 185, 129, 0.25);
      --accent-red: #ef4444;
      --accent-red-glow: rgba(239, 68, 68, 0.25);
      --accent-blue: #38bdf8;
      --accent-cyan: #06b6d4;
      --accent-amber: #f59e0b;
      --accent-purple: #a855f7;
      
      --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      background-color: var(--bg-main);
      color: var(--text-main);
      font-family: var(--font-family);
      line-height: 1.5;
      min-height: 100vh;
      padding: 16px 20px 40px;
      overflow-y: scroll;
      scrollbar-width: thin;
      scrollbar-color: #334155 #0a0e17;
    }

    ::-webkit-scrollbar {
      width: 8px;
    }
    ::-webkit-scrollbar-track {
      background: #0a0e17;
    }
    ::-webkit-scrollbar-thumb {
      background: #334155;
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: #475569;
    }

    /* Container */
    .container {
      max-width: 1400px;
      margin: 0 auto;
    }

    /* Header */
    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 16px 20px;
      background: linear-gradient(180deg, #131c2e 0%, var(--bg-card) 100%);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      margin-bottom: 24px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .brand-icon {
      width: 44px;
      height: 44px;
      background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.4);
    }

    .brand-title h1 {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #fff;
    }

    .brand-title p {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    /* Top stats */
    .header-stats {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 14px;
    }

    .stat-pill {
      background: var(--bg-subtle);
      border: 1px solid var(--border-accent);
      border-radius: 10px;
      padding: 6px 14px;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
    }

    .stat-pill .label {
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
    }

    .stat-pill .val {
      font-size: 0.95rem;
      font-weight: 600;
      font-family: var(--font-mono);
      color: var(--text-main);
    }

    .val-positive {
      color: var(--accent-green) !important;
    }

    .refresh-box {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .pulse-dot {
      width: 10px;
      height: 10px;
      background-color: var(--accent-green);
      border-radius: 50%;
      box-shadow: 0 0 8px var(--accent-green);
    }

    .btn-refresh {
      background: #1e293b;
      border: 1px solid var(--border-accent);
      color: #cbd5e1;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 0.85rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }

    .btn-refresh:hover {
      background: #334155;
      color: #fff;
      border-color: var(--accent-blue);
    }

    /* Grid of 4 Bots */
    .bots-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
      gap: 20px;
      margin-bottom: 28px;
    }

    /* Bot Card */
    .card {
      background-color: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      padding: 20px;
      position: relative;
      display: flex;
      flex-direction: column;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
      transition: transform 0.2s, border-color 0.2s, background-color 0.2s;
    }

    .card:hover {
      background-color: var(--bg-card-hover);
      border-color: #2b3952;
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }

    .card-symbol {
      display: flex;
      flex-direction: column;
    }

    .card-symbol .pair {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .card-symbol .sub {
      font-size: 0.75rem;
      color: var(--text-dim);
    }

    .badge-mode {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 6px;
      letter-spacing: 0.05em;
    }

    .mode-real {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }

    .mode-paper {
      background: rgba(168, 85, 247, 0.15);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.4);
    }

    /* Gauge Container */
    .gauge-wrapper {
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      margin: 2px 0 12px;
    }

    .gauge-svg {
      width: 250px;
      height: 135px;
      overflow: visible;
    }

    .gauge-needle {
      transform-origin: 125px 125px;
      transition: transform 1.2s cubic-bezier(0.34, 1.3, 0.64, 1);
    }

    .gauge-readout {
      margin-top: 2px;
      text-align: center;
    }

    .rsi-number {
      font-size: 2.1rem;
      font-weight: 800;
      font-family: var(--font-mono);
      line-height: 1;
      letter-spacing: -0.02em;
    }

    .rsi-desc {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-top: 3px;
    }

    .zone-buy {
      color: var(--accent-green);
      text-shadow: 0 0 12px var(--accent-green-glow);
    }

    .zone-sell {
      color: var(--accent-red);
      text-shadow: 0 0 12px var(--accent-red-glow);
    }

    .zone-neutral {
      color: var(--accent-blue);
    }

    /* State Pill */
    .state-banner {
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.8rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 14px;
      border: 1px solid transparent;
    }

    .state-waiting-sell {
      background: rgba(245, 158, 11, 0.12);
      border-color: rgba(245, 158, 11, 0.35);
      color: #fbbf24;
    }

    .state-waiting-buy {
      background: rgba(56, 189, 248, 0.12);
      border-color: rgba(56, 189, 248, 0.35);
      color: #38bdf8;
    }

    .state-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    .state-waiting-sell .state-dot {
      background: #fbbf24;
      box-shadow: 0 0 8px #fbbf24;
    }

    .state-waiting-buy .state-dot {
      background: #38bdf8;
      box-shadow: 0 0 8px #38bdf8;
    }

    /* Data Matrix */
    .data-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      background: #0d131f;
      border: 1px solid var(--border-card);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 14px;
    }

    .data-item {
      display: flex;
      flex-direction: column;
    }

    .data-label {
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
      margin-bottom: 2px;
    }

    .data-val {
      font-size: 0.95rem;
      font-weight: 600;
      font-family: var(--font-mono);
      color: #e2e8f0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pnl-badge {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 700;
      font-size: 0.85rem;
    }

    .pnl-pos {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }

    .pnl-neg {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
    }

    .pnl-zero {
      background: rgba(148, 163, 184, 0.1);
      color: #94a3b8;
    }

    /* Card Footer */
    .card-footer {
      margin-top: auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 10px;
      border-top: 1px solid #1a2333;
      font-size: 0.72rem;
      color: var(--text-dim);
    }

    /* History Log Section */
    .history-card {
      background-color: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
    }

    .history-title {
      font-size: 1rem;
      font-weight: 700;
      color: #fff;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .history-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }

    .history-col {
      background: #0d131f;
      border: 1px solid var(--border-card);
      border-radius: 12px;
      padding: 12px;
    }

    .history-col h4 {
      font-size: 0.82rem;
      color: var(--text-muted);
      border-bottom: 1px solid #1a2333;
      padding-bottom: 6px;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
    }

    .history-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.75rem;
      font-family: var(--font-mono);
    }

    .history-table th {
      text-align: left;
      color: var(--text-dim);
      font-weight: 600;
      padding: 3px 4px;
      font-size: 0.65rem;
      text-transform: uppercase;
    }

    .history-table td {
      padding: 4px 4px;
      border-top: 1px solid #141b29;
      color: #cbd5e1;
    }

    /* Scroll Navigation Button */
    .scroll-btn-wrap {
      display: flex;
      justify-content: center;
      margin: 4px 0 14px;
    }

    .btn-scroll-toggle {
      background: #1e293b;
      border: 1px solid var(--border-accent);
      color: var(--accent-blue);
      padding: 6px 16px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
      transition: all 0.2s;
    }

    .btn-scroll-toggle:hover {
      background: #334155;
      color: #fff;
      transform: translateY(-1px);
    }

    /* Netbook 1024x600 & Compact Screen Optimization */
    @media (max-height: 720px), (max-width: 1100px) {
      body {
        padding: 6px 12px 18px;
      }

      header {
        padding: 6px 12px;
        margin-bottom: 8px;
        border-radius: 10px;
        gap: 8px;
      }

      .brand {
        gap: 8px;
      }

      .brand-icon {
        width: 32px;
        height: 32px;
        font-size: 18px;
        border-radius: 8px;
      }

      .brand-title h1 {
        font-size: 0.95rem;
      }

      .brand-title p {
        display: none;
      }

      .header-stats {
        gap: 8px;
      }

      .stat-pill {
        padding: 2px 8px;
        border-radius: 6px;
      }

      .stat-pill .label {
        font-size: 0.58rem;
      }

      .stat-pill .val {
        font-size: 0.82rem;
      }

      .btn-refresh {
        padding: 4px 8px;
        font-size: 0.72rem;
      }

      .bots-grid {
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        margin-bottom: 8px;
      }

      .card {
        padding: 8px 10px 8px;
        border-radius: 12px;
      }

      .card-top {
        margin-bottom: 2px;
      }

      .card-symbol .pair {
        font-size: 0.95rem;
      }

      .card-symbol .sub {
        font-size: 0.65rem;
      }

      .badge-mode {
        font-size: 0.55rem;
        padding: 2px 5px;
      }

      .gauge-wrapper {
        margin: 0 0 4px;
      }

      .gauge-svg {
        width: 175px;
        height: 98px;
      }

      .gauge-readout {
        margin-top: 0px;
      }

      .rsi-number {
        font-size: 1.55rem;
        line-height: 1;
      }

      .rsi-desc {
        font-size: 0.6rem;
        margin-top: 1px;
      }

      .state-banner {
        padding: 4px 6px;
        font-size: 0.68rem;
        margin-bottom: 4px;
        border-radius: 6px;
      }

      .data-grid {
        padding: 6px;
        gap: 3px;
        margin-bottom: 4px;
        border-radius: 8px;
      }

      .data-label {
        font-size: 0.58rem;
      }

      .data-val {
        font-size: 0.78rem;
      }

      .pnl-badge {
        font-size: 0.7rem;
        padding: 1px 4px;
      }

      .card-footer {
        padding-top: 2px;
        font-size: 0.6rem;
      }

      .scroll-btn-wrap {
        margin: 2px 0 8px;
      }

      .btn-scroll-toggle {
        padding: 3px 12px;
        font-size: 0.7rem;
      }

      .history-card {
        padding: 12px;
        border-radius: 12px;
      }

      .history-title {
        font-size: 0.85rem;
        margin-bottom: 8px;
      }
    }

    @media (max-width: 768px) {
      body {
        padding: 10px;
      }
      header {
        flex-direction: column;
        align-items: stretch;
      }
      .header-stats {
        justify-content: space-between;
      }
      .bots-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>

<div class="container">
  <!-- Top Navigation & Summary -->
  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div class="brand-title">
        <h1>SWING BOTS COMMAND CENTER</h1>
        <p>Monitor en tiempo real • Intel Atom N2600 Netbook</p>
      </div>
    </div>

    <div class="header-stats">
      <div class="stat-pill">
        <span class="label">Capital Real Portfolio</span>
        <span class="val val-positive" id="cap-current">$324.57 <small>(+5.66%)</small></span>
      </div>

      <div class="stat-pill">
        <span class="label">Netbook RAM</span>
        <span class="val" id="sys-ram">-- / --</span>
      </div>

      <div class="stat-pill">
        <span class="label">Netbook Load / Up</span>
        <span class="val" id="sys-load">-- | --</span>
      </div>

      <div class="stat-pill" id="pill-tunnel" style="display:none">
        <span class="label">🌍 Remoto (Cloudflare)</span>
        <span class="val" style="font-size:0.75rem"><a href="#" id="tunnel-link" target="_blank" style="color:var(--accent-blue);text-decoration:none">...</a></span>
      </div>

      <div class="refresh-box">
        <div class="pulse-dot" title="Conexión en vivo activa"></div>
        <button class="btn-refresh" onclick="fetchData()">
          <span id="refresh-spin">🔄</span> Refrescar (<span id="countdown">20</span>s)
        </button>
      </div>
    </div>
  </header>

  <!-- 4 Speedometer Cards -->
  <div class="bots-grid" id="bots-container">
    <!-- Cards will be populated by JS -->
  </div>

  <!-- Scroll Navigation Helper -->
  <div class="scroll-btn-wrap">
    <button class="btn-scroll-toggle" id="scroll-toggle-btn" onclick="toggleScroll()">
      <span id="scroll-icon">▼</span> <span id="scroll-text">Ver Historial de Velas Recientes</span>
    </button>
  </div>

  <!-- Recent Logs Feed -->
  <div class="history-card">
    <div class="history-title">
      <span>📊 Actividad Reciente (Últimos chequeos cada 15m)</span>
      <span style="font-size: 0.75rem; color: var(--text-dim); font-weight: normal;">Sincronizado con CSVs locales</span>
    </div>
    <div class="history-grid" id="history-container">
      <!-- Populated by JS -->
    </div>
  </div>
</div>

<script>
  let countdownTimer = 20;

  function renderGaugeSvg(rsi, botId) {
    // RSI 0 -> -90 deg (left, emerald)
    // RSI 50 -> 0 deg (center, straight up, slate/neutral)
    // RSI 100 -> +90 deg (right, crimson/sell)
    const clampedRsi = Math.max(0, Math.min(100, rsi));
    const angle = (clampedRsi - 50) * 1.8;
    
    let zoneClass = "zone-neutral";
    let zoneText = "⚖️ NEUTRO";
    if (clampedRsi <= 25) {
      zoneClass = "zone-buy";
      zoneText = "🚀 COMPRA (≤25)";
    } else if (clampedRsi <= 35) {
      zoneClass = "zone-buy";
      zoneText = "🟢 ZONA BAJA";
    } else if (clampedRsi >= 75) {
      zoneClass = "zone-sell";
      zoneText = "🔥 VENTA (≥75)";
    } else if (clampedRsi >= 65) {
      zoneClass = "zone-sell";
      zoneText = "🟠 ZONA ALTA";
    }

    return `
      <div class="gauge-wrapper">
        <svg class="gauge-svg" viewBox="0 0 250 145">
          <defs>
            <!-- Gauge arc gradient: Green (left) -> Slate/Cyan (center 50) -> Red (right 100) -->
            <linearGradient id="arcGrad_${botId}" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#10b981" />
              <stop offset="25%" stop-color="#10b981" />
              <stop offset="42%" stop-color="#38bdf8" />
              <stop offset="50%" stop-color="#64748b" />
              <stop offset="58%" stop-color="#38bdf8" />
              <stop offset="75%" stop-color="#f97316" />
              <stop offset="100%" stop-color="#ef4444" />
            </linearGradient>
          </defs>

          <!-- Outer background track -->
          <path d="M 35 125 A 90 90 0 0 1 215 125" fill="none" stroke="#1f293d" stroke-width="14" stroke-linecap="round" />

          <!-- Colored active gradient arc -->
          <path d="M 35 125 A 90 90 0 0 1 215 125" fill="none" stroke="url(#arcGrad_${botId})" stroke-width="12" stroke-linecap="round" />

          <!-- Threshold ticks -->
          <!-- 0 Tick (Left) -->
          <line x1="35" y1="125" x2="25" y2="125" stroke="#10b981" stroke-width="2.5" />
          <text x="20" y="140" fill="#10b981" font-size="9" font-family="monospace" text-anchor="middle" font-weight="bold">0</text>

          <!-- 25 Buy threshold tick (-45 deg): cx=125, cy=125, r=90 -> x=61.36, y=61.36 -->
          <line x1="61.36" y1="61.36" x2="54.3" y2="54.3" stroke="#10b981" stroke-width="3" />
          <text x="44" y="50" fill="#10b981" font-size="9" font-family="monospace" font-weight="bold">25</text>

          <!-- 50 Center tick (0 deg): top center x=125, y=35 -->
          <line x1="125" y1="35" x2="125" y2="24" stroke="#94a3b8" stroke-width="3" />
          <text x="125" y="20" fill="#94a3b8" font-size="9.5" font-family="monospace" text-anchor="middle" font-weight="bold">50</text>

          <!-- 75 Sell threshold tick (+45 deg): x=188.64, y=61.36 -->
          <line x1="188.64" y1="61.36" x2="195.7" y2="54.3" stroke="#ef4444" stroke-width="3" />
          <text x="204" y="50" fill="#ef4444" font-size="9" font-family="monospace" font-weight="bold">75</text>

          <!-- 100 Tick (Right) -->
          <line x1="215" y1="125" x2="225" y2="125" stroke="#ef4444" stroke-width="2.5" />
          <text x="230" y="140" fill="#ef4444" font-size="9" font-family="monospace" text-anchor="middle" font-weight="bold">100</text>

          <!-- Target zone labels -->
          <text x="42" y="105" fill="#10b981" font-size="7.5" font-family="sans-serif" font-weight="700">COMPRA</text>
          <text x="180" y="105" fill="#ef4444" font-size="7.5" font-family="sans-serif" font-weight="700">VENTA</text>

          <!-- Needle -->
          <g class="gauge-needle" id="needle_${botId}" style="transform: rotate(${angle}deg);">
            <!-- Needle pointer -->
            <path d="M 122.5 125 L 125 42 L 127.5 125 Z" fill="#ffffff" />
            <polygon points="123.5,56 125,40 126.5,56" fill="${clampedRsi <= 35 ? '#10b981' : (clampedRsi >= 65 ? '#ef4444' : '#38bdf8')}" />
            <!-- Needle pivot base -->
            <circle cx="125" cy="125" r="7" fill="#1e293b" stroke="#ffffff" stroke-width="2" />
            <circle cx="125" cy="125" r="3.5" fill="${clampedRsi <= 35 ? '#10b981' : (clampedRsi >= 65 ? '#ef4444' : '#38bdf8')}" />
          </g>
        </svg>

        <div class="gauge-readout">
          <div class="rsi-number ${zoneClass}">${clampedRsi.toFixed(1)}</div>
          <div class="rsi-desc ${zoneClass}">${zoneText}</div>
        </div>
      </div>
    `;
  }

  function renderCard(b) {
    const isWaitingSell = b.state === "WAITING_SELL";
    const stateBannerClass = isWaitingSell ? "state-waiting-sell" : "state-waiting-buy";
    
    let pnlClass = "pnl-zero";
    let pnlText = "0.00%";
    if (b.pnl_pct > 0) {
      pnlClass = "pnl-pos";
      pnlText = `+${b.pnl_pct.toFixed(2)}%`;
    } else if (b.pnl_pct < 0) {
      pnlClass = "pnl-neg";
      pnlText = `${b.pnl_pct.toFixed(2)}%`;
    }

    // Relative time formatting
    let timeAgo = "reciente";
    if (b.last_update && b.last_update !== "N/A") {
      try {
        const parts = b.last_update.split(" ");
        if (parts.length === 2) {
          timeAgo = parts[1];
        }
      } catch (e) {}
    }

    return `
      <div class="card" id="card-${b.id}">
        <div class="card-top">
          <div class="card-symbol">
            <span class="pair">${b.symbol}</span>
            <span class="sub">${b.name} • ${b.exchange}</span>
          </div>
          <span class="badge-mode ${b.mode === 'REAL' ? 'mode-real' : 'mode-paper'}">
            ${b.mode === 'REAL' ? '● REAL' : '🧪 SIMULACIÓN'}
          </span>
        </div>

        ${renderGaugeSvg(b.rsi, b.id)}

        <div class="state-banner ${stateBannerClass}">
          <div class="state-dot"></div>
          <span>${b.state_label}</span>
        </div>

        <div class="data-grid">
          <div class="data-item">
            <span class="data-label">Precio Actual</span>
            <span class="data-val">${b.price_formatted}</span>
          </div>

          <div class="data-item">
            <span class="data-label">PnL Flotante</span>
            <span class="data-val">
              <span class="pnl-badge ${pnlClass}">${pnlText}</span>
            </span>
          </div>

          <div class="data-item">
            <span class="data-label">Precio Entrada</span>
            <span class="data-val">${b.buy_price_formatted}</span>
          </div>

          <div class="data-item">
            <span class="data-label">Tenencia Token</span>
            <span class="data-val">${Number(b.token_balance).toLocaleString('en-US', {maximumFractionDigits: 4})} ${b.token_symbol}</span>
          </div>

          <div class="data-item" style="grid-column: span 2;">
            <span class="data-label">Balance Base / USDT</span>
            <span class="data-val">${Number(b.quote_balance).toLocaleString('en-US', {maximumFractionDigits: 4})} ${b.quote_symbol}</span>
          </div>
        </div>

        <div class="card-footer">
          <span>Último ciclo: ${b.last_update}</span>
          <span>Ciclo: 15 min</span>
        </div>
      </div>
    `;
  }

  function renderHistory(bots) {
    const container = document.getElementById("history-container");
    let html = "";
    
    bots.forEach(b => {
      let rows = "";
      if (b.history && b.history.length > 0) {
        b.history.slice().reverse().forEach(h => {
          const rsiColor = h.rsi <= 25 ? 'color:#10b981;font-weight:bold' : (h.rsi >= 75 ? 'color:#ef4444;font-weight:bold' : 'color:#cbd5e1');
          rows += `
            <tr>
              <td>${h.time}</td>
              <td>${h.price}</td>
              <td style="${rsiColor}">${h.rsi.toFixed(2)}</td>
              <td><span style="font-size:0.65rem;color:${h.state === 'WAITING_SELL' ? '#fbbf24' : '#38bdf8'}">${h.state === 'WAITING_SELL' ? 'VENTA' : 'COMPRA'}</span></td>
            </tr>
          `;
        });
      } else {
        rows = `<tr><td colspan="4" style="text-align:center;color:var(--text-dim)">Sin registros</td></tr>`;
      }

      html += `
        <div class="history-col">
          <h4>
            <span>${b.symbol}</span>
            <span style="font-size:0.7rem;color:var(--text-dim)">${b.mode}</span>
          </h4>
          <table class="history-table">
            <thead>
              <tr>
                <th>Hora</th>
                <th>Precio</th>
                <th>RSI</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              ${rows}
            </tbody>
          </table>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  async function fetchData() {
    const spin = document.getElementById("refresh-spin");
    spin.style.display = "inline-block";
    spin.style.animation = "spin 0.6s linear";

    try {
      const res = await fetch("/api/data");
      if (!res.ok) throw new Error("HTTP error " + res.status);
      const data = await res.json();

      // Update System Stats
      if (data.system) {
        const ram = data.system;
        document.getElementById("sys-ram").textContent = `${ram.ram_used_mb}MB / ${ram.ram_total_mb}MB (${ram.ram_pct}%)`;
        const load = data.system.load.join(", ");
        document.getElementById("sys-load").textContent = `L: ${load} | Up: ${data.system.uptime}`;
      }

      // Update Capital Stats
      if (data.capital) {
        const c = data.capital;
        const sign = c.pnl_pct >= 0 ? "+" : "";
        document.getElementById("cap-current").innerHTML = `$${c.current.toFixed(2)} <small style="font-size:0.75rem">(${sign}${c.pnl_pct.toFixed(2)}%)</small>`;
      }

      // Update Remote Tunnel Link
      const pillTunnel = document.getElementById("pill-tunnel");
      const linkTunnel = document.getElementById("tunnel-link");
      if (pillTunnel && linkTunnel) {
        if (data.tunnel_url && data.tunnel_url.startsWith("http")) {
          pillTunnel.style.display = "flex";
          linkTunnel.href = data.tunnel_url;
          linkTunnel.textContent = data.tunnel_url.replace("https://", "");
        } else {
          pillTunnel.style.display = "none";
        }
      }

      // Render Cards
      if (data.bots && data.bots.length > 0) {
        const cardsHtml = data.bots.map(b => renderCard(b)).join("");
        document.getElementById("bots-container").innerHTML = cardsHtml;
        renderHistory(data.bots);
      }

      countdownTimer = 20;
    } catch (err) {
      console.error("Error fetching data:", err);
    } finally {
      setTimeout(() => {
        spin.style.animation = "";
      }, 600);
    }
  }

  // Timer loop
  setInterval(() => {
    countdownTimer--;
    const el = document.getElementById("countdown");
    if (el) el.textContent = countdownTimer;
    if (countdownTimer <= 0) {
      countdownTimer = 20;
      fetchData();
    }
  }, 1000);

  // Initial load
  fetchData();

  // Scroll toggle button logic
  function toggleScroll() {
    const hist = document.querySelector('.history-card');
    if (window.scrollY < 80) {
      if (hist) hist.scrollIntoView({ behavior: 'smooth' });
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  window.addEventListener('scroll', () => {
    const btnText = document.getElementById('scroll-text');
    const btnIcon = document.getElementById('scroll-icon');
    if (!btnText || !btnIcon) return;
    if (window.scrollY > 80) {
      btnIcon.textContent = '▲';
      btnText.textContent = 'Volver a Indicadores';
    } else {
      btnIcon.textContent = '▼';
      btnText.textContent = 'Ver Historial de Velas Recientes';
    }
  });

  // Keyboard navigation for Netbook keys (Arrows, PageUp/Down, Space, J/K, R)
  window.addEventListener('keydown', (e) => {
    // Prevent default scroll handling only if we handle it
    if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ' || e.key === 'j') {
      window.scrollBy({ top: 220, behavior: 'smooth' });
    } else if (e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'k') {
      window.scrollBy({ top: -220, behavior: 'smooth' });
    } else if (e.key === 'Home') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (e.key === 'End') {
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    } else if (e.key === 'r' || e.key === 'R') {
      fetchData();
    }
  });
</script>

</body>
</html>
"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Disable logging every request to keep stdout clean
        if self.path == "/" or self.path.startswith("/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))

        elif self.path.startswith("/api/data"):
            try:
                data = get_all_bot_data()
                body = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress routine GET logging to prevent log spamming
        pass


class ReusableThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_server():
    server_address = ("0.0.0.0", PORT)
    httpd = ReusableThreadingServer(server_address, DashboardHandler)
    print(f"🚀 Netbook Trading Dashboard running at http://0.0.0.0:{PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
