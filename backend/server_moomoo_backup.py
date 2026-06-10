"""
server.py — FastAPI backend for Portfolio Tracker

Proxies Moomoo OpenD API calls and manages:
- Portfolio data polling
- Target weight persistence (SQLite)
- Portfolio snapshots & trade log
- Drift calculations

Run: uvicorn server:app --reload --port 8000
"""

import asyncio
import getpass
import json
import os
import sqlite3
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Screener (FMP proxy) ──
from screener import screener_router

# ── Toggle: True = use real Moomoo API, False = demo data ──
USE_LIVE_API = True  # Set True once OpenD is running

if USE_LIVE_API:
    from moomoo import *

# ── Configuration ──────────────────────────────────────────────
OPEND_HOST = "127.0.0.1"
OPEND_PORT = 11111

# ── Live FX Rate ───────────────────────────────────────────────
import urllib.request

_fx_cache = {"rate": 3.93, "fetched_at": 0}

def get_usd_myr_rate():
    """Fetch live USD/MYR rate, cached for 1 hour"""
    now = time.time()
    if now - _fx_cache["fetched_at"] < 3600:  # Cache 1 hour
        return _fx_cache["rate"]
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        req = urllib.request.Request(url, headers={"User-Agent": "PortfolioTracker/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            rate = data["rates"]["MYR"]
            _fx_cache["rate"] = rate
            _fx_cache["fetched_at"] = now
            print(f"📈 FX rate updated: USD/MYR = {rate}")
            return rate
    except Exception as e:
        print(f"⚠️  FX fetch failed, using cached rate {_fx_cache['rate']}: {e}")
        return _fx_cache["rate"]

# Prompt for trading password at startup (only when live)
if USE_LIVE_API:
    TRADING_PWD = getpass.getpass("Enter your 6-digit Moomoo trading password: ")
else:
    TRADING_PWD = ""
DB_PATH = Path(__file__).parent / "portfolio.db"

# ── Database Setup ─────────────────────────────────────────────

def init_db():
    """Create tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS target_weights (
            ticker TEXT PRIMARY KEY,
            target_pct REAL NOT NULL,
            tier TEXT DEFAULT 'medium',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            total_nav REAL,
            equity_nav REAL,
            cash_plus REAL,
            positions_json TEXT,
            weights_json TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            shares REAL,
            price REAL,
            notes TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            remark TEXT,
            direction TEXT,
            UNIQUE(date, amount, currency, remark)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            UNIQUE(ticker, date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS conviction (
            ticker TEXT PRIMARY KEY,
            thesis TEXT DEFAULT '',
            catalysts_json TEXT DEFAULT '[]',
            invalidations_json TEXT DEFAULT '[]',
            fair_value REAL DEFAULT 0,
            valuation_method TEXT DEFAULT '',
            valuation_notes TEXT DEFAULT '',
            last_reviewed TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert default settings
    defaults = {
        "concentration_cap": "10.0",
        "drift_threshold": "2.0",
        "poll_interval": "30",
    }
    for k, v in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
        )

    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Demo Data ──────────────────────────────────────────────────

DEMO_POSITIONS = [
    {"code": "US.AAPL", "stock_name": "Apple Inc", "qty": 50, "cost_price": 178.50, "price": 227.63, "val": 11381.50, "pl_val": 2456.50, "pl_ratio": 27.52},
    {"code": "US.MSFT", "stock_name": "Microsoft Corp", "qty": 30, "cost_price": 380.20, "price": 423.85, "val": 12715.50, "pl_val": 1309.50, "pl_ratio": 11.48},
    {"code": "US.NVDA", "stock_name": "NVIDIA Corp", "qty": 20, "cost_price": 450.00, "price": 131.88, "val": 2637.60, "pl_val": -6362.40, "pl_ratio": -70.69},
    {"code": "US.GOOGL", "stock_name": "Alphabet Inc", "qty": 40, "cost_price": 140.00, "price": 167.42, "val": 6696.80, "pl_val": 1096.80, "pl_ratio": 19.59},
    {"code": "US.AMZN", "stock_name": "Amazon.com Inc", "qty": 25, "cost_price": 155.00, "price": 203.98, "val": 5099.50, "pl_val": 1224.50, "pl_ratio": 31.60},
    {"code": "US.META", "stock_name": "Meta Platforms", "qty": 15, "cost_price": 330.00, "price": 612.77, "val": 9191.55, "pl_val": 4241.55, "pl_ratio": 85.69},
    {"code": "US.TSLA", "stock_name": "Tesla Inc", "qty": 35, "cost_price": 240.00, "price": 272.16, "val": 9525.60, "pl_val": 1125.60, "pl_ratio": 13.40},
    {"code": "MY.1155", "stock_name": "Maybank", "qty": 500, "cost_price": 9.80, "price": 10.42, "val": 5210.00, "pl_val": 310.00, "pl_ratio": 6.33},
    {"code": "MY.1295", "stock_name": "Public Bank", "qty": 400, "cost_price": 4.50, "price": 4.78, "val": 1912.00, "pl_val": 112.00, "pl_ratio": 6.22},
    {"code": "US.JPM", "stock_name": "JPMorgan Chase", "qty": 20, "cost_price": 185.00, "price": 252.93, "val": 5058.60, "pl_val": 1358.60, "pl_ratio": 36.69},
    {"code": "US.V", "stock_name": "Visa Inc", "qty": 18, "cost_price": 260.00, "price": 341.12, "val": 6140.16, "pl_val": 1460.16, "pl_ratio": 31.20},
    {"code": "US.UNH", "stock_name": "UnitedHealth", "qty": 8, "cost_price": 520.00, "price": 487.65, "val": 3901.20, "pl_val": -258.80, "pl_ratio": -6.22},
]

DEMO_FUND_ASSETS = 15420.00  # Cash Plus balance
DEMO_TOTAL_ASSETS = sum(p["val"] for p in DEMO_POSITIONS) + DEMO_FUND_ASSETS


# ── Moomoo API Layer ───────────────────────────────────────────

class MoomooClient:
    """Wraps Moomoo OpenD API calls"""

    def __init__(self):
        self.host = OPEND_HOST
        self.port = OPEND_PORT
        self._acc_id = None

    def _get_trade_ctx(self):
        return OpenSecTradeContext(
            host=self.host,
            port=self.port,
            security_firm=SecurityFirm.FUTUMY,
        )

    def _get_quote_ctx(self):
        return OpenQuoteContext(host=self.host, port=self.port)

    def get_acc_id(self):
        """Get the first REAL trading account ID"""
        if self._acc_id:
            return self._acc_id
        ctx = self._get_trade_ctx()
        try:
            ret, data = ctx.get_acc_list()
            if ret != RET_OK:
                raise Exception(f"get_acc_list failed: {data}")
            real = data[data["trd_env"] == "REAL"]
            if len(real) == 0:
                raise Exception("No REAL trading account found")
            self._acc_id = int(real.iloc[0]["acc_id"])
            return self._acc_id
        finally:
            ctx.close()

    def get_positions(self):
        """Fetch current stock holdings with full detail"""
        ctx = self._get_trade_ctx()
        try:
            acc_id = self.get_acc_id()
            ret, data = ctx.position_list_query(
                trd_env=TrdEnv.REAL, acc_id=acc_id
            )
            if ret != RET_OK:
                raise Exception(f"position_list_query failed: {data}")

            positions = []
            for _, row in data.iterrows():
                qty = float(row.get("qty", 0))
                avg_cost = float(row.get("average_cost", 0))
                diluted_cost = float(row.get("diluted_cost", row.get("cost_price", 0)))
                price = float(row.get("nominal_price", 0))
                val = float(row.get("market_val", 0))
                unrealized_pl = float(row.get("unrealized_pl", 0))
                realized_pl = float(row.get("realized_pl", 0))
                total_pl = float(row.get("pl_val", 0))
                pl_ratio_avg = float(row.get("pl_ratio_avg_cost", 0))
                today_pl = float(row.get("today_pl_val", 0))
                api_currency = str(row.get("currency", "N/A"))

                if val == 0 and qty > 0 and avg_cost > 0:
                    val = avg_cost * qty + unrealized_pl
                if price == 0 and qty > 0 and val > 0:
                    price = val / qty

                positions.append({
                    "code": row["code"],
                    "stock_name": row.get("stock_name", ""),
                    "qty": qty,
                    "cost_price": round(avg_cost, 4),
                    "diluted_cost": round(diluted_cost, 4),
                    "price": round(price, 4),
                    "val": round(val, 2),
                    "pl_val": round(total_pl, 2),
                    "unrealized_pl": round(unrealized_pl, 2),
                    "realized_pl": round(realized_pl, 2),
                    "pl_ratio": round(pl_ratio_avg, 2),
                    "today_pl": round(today_pl, 2),
                    "api_currency": api_currency,
                })
            return positions
        finally:
            ctx.close()

    def get_account_funds(self):
        """Fetch account info — captures MYR cash, fund assets, and USD cash"""
        ctx = self._get_trade_ctx()
        try:
            acc_id = self.get_acc_id()
            ret, data = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id)
            if ret != RET_OK:
                raise Exception(f"accinfo_query failed: {data}")

            row = data.iloc[0]
            return {
                "total_assets": float(row.get("total_assets", 0)),
                "market_val": float(row.get("market_val", 0)),
                "fund_assets": float(row.get("fund_assets", 0)),
                "securities_assets": float(row.get("securities_assets", 0)),
                "cash": float(row.get("cash", 0)),
                "power": float(row.get("power", 0)),
                "my_cash": float(row.get("my_cash", 0)),
                "myr_assets": float(row.get("myr_assets", 0)),
                "us_cash": float(row.get("us_cash", 0)),
                "usd_assets": float(row.get("usd_assets", 0)),
            }
        finally:
            ctx.close()

    def get_real_time_quotes(self, codes: list):
        """Get real-time quotes for a list of stock codes"""
        ctx = self._get_quote_ctx()
        try:
            ret, data = ctx.get_market_snapshot(codes)
            if ret != RET_OK:
                return {}
            quotes = {}
            for _, row in data.iterrows():
                quotes[row["code"]] = float(row["last_price"])
            return quotes
        finally:
            ctx.close()

    def get_cash_flows(self, from_date, to_date):
        """Fetch cash flows day-by-day from Moomoo API"""
        ctx = self._get_trade_ctx()
        flows = []
        try:
            acc_id = self.get_acc_id()
            current = from_date
            while current <= to_date:
                date_str = current.strftime("%Y-%m-%d")
                try:
                    ret, data = ctx.get_acc_cash_flow(
                        clearing_date=date_str,
                        trd_env=TrdEnv.REAL,
                        acc_id=acc_id,
                    )
                    if ret == RET_OK and data is not None and not data.empty:
                        for _, row in data.iterrows():
                            flows.append({
                                "date": date_str,
                                "cashflow_type": str(row.get("cashflow_type", "")),
                                "direction": str(row.get("cashflow_direction", "")),
                                "currency": str(row.get("currency", "MYR")),
                                "amount": float(row.get("cashflow_amount", 0)),
                                "remark": str(row.get("cashflow_remark", "")),
                            })
                except Exception as e:
                    print(f"⚠️  Cash flow fetch failed for {date_str}: {e}")
                current += timedelta(days=1)
        finally:
            ctx.close()
        return flows

    def get_history_kline(self, code, start_date, end_date, max_count=1000):
        """
        Fetch historical daily kline data from Moomoo OpenD.
        Returns list of {date, open, close, high, low, volume}.
        Handles pagination via page_req_key.
        """
        ctx = self._get_quote_ctx()
        all_rows = []
        try:
            page_req_key = None
            while True:
                ret, data, page_req_key = ctx.request_history_kline(
                    code=code,
                    start=start_date,
                    end=end_date,
                    ktype=KLType.K_DAY,
                    max_count=max_count,
                    page_req_key=page_req_key,
                )
                if ret != RET_OK:
                    print(f"⚠️  request_history_kline failed for {code}: {data}")
                    break
                if data is not None and not data.empty:
                    for _, row in data.iterrows():
                        time_key = str(row.get("time_key", ""))
                        # time_key format: "2025-03-14 00:00:00" — extract date
                        d = time_key[:10] if len(time_key) >= 10 else time_key
                        all_rows.append({
                            "date": d,
                            "open": float(row.get("open", 0)),
                            "close": float(row.get("close", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "volume": float(row.get("volume", 0)),
                        })
                if page_req_key is None:
                    break  # No more pages
        finally:
            ctx.close()
        return all_rows


# Global client (only initialized if USE_LIVE_API)
moomoo_client = MoomooClient() if USE_LIVE_API else None

SPY_CODE = "US.SPY"       # SPY ETF as S&P 500 proxy via Moomoo
BENCHMARK_KEY = "SPY"     # Key used in benchmark_cache table
CASHFLOW_SCAN_DAYS = 365

# ── Multi-Benchmark Configuration ────────────────────────────
BENCHMARKS = {
    "SPY":  {"moomoo": "US.SPY",  "fmp": "SPY",  "label": "S&P 500",           "color": "#d29922"},
    "ACWI": {"moomoo": "US.ACWI", "fmp": "ACWI", "label": "MSCI ACWI (Global)", "color": "#a371f7"},
    "QQQ":  {"moomoo": "US.QQQ",  "fmp": "QQQ",  "label": "Nasdaq 100",         "color": "#f778ba"},
    "EEM":  {"moomoo": "US.EEM",  "fmp": "EEM",  "label": "Emerging Markets",   "color": "#3fb950"},
}


# ── Deposit Scanning ──────────────────────────────────────────

def scan_and_store_deposits():
    """
    Scan cash flows for the past CASHFLOW_SCAN_DAYS days.
    Store only 'Bank Transfer Deposits' (IN direction) in SQLite.
    Fund subscriptions / money-market moves are excluded.
    """
    if not USE_LIVE_API or not moomoo_client:
        print("⚠️  Deposit scan skipped — not in live mode")
        return
    print(f"🔍 Scanning cash flows for deposits (past {CASHFLOW_SCAN_DAYS} days)...")
    try:
        to_d = date.today()
        from_d = to_d - timedelta(days=CASHFLOW_SCAN_DAYS)
        flows = moomoo_client.get_cash_flows(from_d, to_d)

        deposit_count = 0
        db = get_db()
        for f in flows:
            remark = f.get("remark", "")
            direction = f.get("direction", "")
            # Only count "Bank Transfer Deposits" with IN direction as real deposits
            if "Bank Transfer Deposit" in remark and "IN" in direction.upper():
                try:
                    db.execute(
                        """INSERT OR IGNORE INTO deposits (date, amount, currency, remark, direction)
                           VALUES (?, ?, ?, ?, ?)""",
                        (f["date"], f["amount"], f["currency"], remark, direction),
                    )
                    deposit_count += 1
                except sqlite3.IntegrityError:
                    pass
        db.commit()
        db.close()
        print(f"✅ Deposit scan complete. Found {deposit_count} deposit records.")

        # Store last scan timestamp
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("last_deposit_scan", datetime.now().isoformat()),
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"⚠️  Deposit scan failed: {e}")


def get_deposits_from_db():
    """Retrieve all stored deposits from SQLite."""
    db = get_db()
    rows = db.execute(
        "SELECT date, amount, currency, remark, direction FROM deposits ORDER BY date"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ── S&P 500 Benchmark (Moomoo first, FMP fallback) ────────────

FMP_KEY_FILE = os.path.expanduser("~/.fmp_api_key")

def _read_fmp_key():
    """Read FMP key from file or env var, return None if unavailable."""
    key = os.environ.get("FMP_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(FMP_KEY_FILE):
        with open(FMP_KEY_FILE) as f:
            key = f.read().strip()
        if key:
            return key
    return None


def _fetch_ticker_from_fmp(symbol, start_date, end_date):
    """Fetch daily prices for any ticker from FMP stable API."""
    key = _read_fmp_key()
    if not key:
        print(f"⚠️  No FMP API key — cannot fetch {symbol}")
        return []
    url = (
        f"https://financialmodelingprep.com/stable/historical-price-eod/full"
        f"?symbol={symbol}&from={start_date}&to={end_date}&apikey={key}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PortfolioTracker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list):
            historical = data
        else:
            historical = data.get("historical", [])
        return [{"date": h["date"], "close": h["close"]} for h in reversed(historical)]
    except Exception as e:
        print(f"⚠️  FMP {symbol} fetch failed: {e}")
        return []


def fetch_and_cache_benchmark(days=365):
    """Fetch daily data for all benchmarks. Tries Moomoo first, falls back to FMP."""
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    for bm_key, bm_cfg in BENCHMARKS.items():
        klines = []
        # Try Moomoo first
        if USE_LIVE_API and moomoo_client:
            print(f"📈 Fetching {bm_key} from Moomoo...")
            try:
                klines = moomoo_client.get_history_kline(
                    code=bm_cfg["moomoo"],
                    start_date=start_date,
                    end_date=end_date,
                )
                if klines:
                    print(f"✅ Got {len(klines)} {bm_key} data points from Moomoo")
            except Exception as e:
                print(f"⚠️  Moomoo {bm_key} fetch failed: {e}")

        # Fallback to FMP
        if not klines:
            print(f"📈 Falling back to FMP for {bm_key}...")
            klines = _fetch_ticker_from_fmp(bm_cfg["fmp"], start_date, end_date)
            if klines:
                print(f"✅ Got {len(klines)} {bm_key} data points from FMP")

        if not klines:
            print(f"⚠️  No {bm_key} data from any source")
            continue

        db = get_db()
        for k in klines:
            db.execute(
                "INSERT OR REPLACE INTO benchmark_cache (ticker, date, close) VALUES (?, ?, ?)",
                (bm_key, k["date"], k["close"]),
            )
        db.commit()
        db.close()
        print(f"✅ Cached {len(klines)} {bm_key} benchmark points")


def get_benchmark_data(from_date_str, to_date_str, ticker="SPY"):
    """Retrieve cached benchmark data for date range."""
    db = get_db()
    rows = db.execute(
        "SELECT date, close FROM benchmark_cache WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
        (ticker, from_date_str, to_date_str),
    ).fetchall()
    db.close()
    return [{"date": r["date"], "close": r["close"]} for r in rows]


# ── TWR Calculation ───────────────────────────────────────────

def calculate_twr(snapshots_list, deposits_list):
    """
    Calculate Time-Weighted Return series.
    Strips out deposit effects so chart shows pure investment performance.
    Uses Modified Dietz for sub-periods between deposits.
    Returns list of {date, twr_cumulative, twr_factor, portfolio_value, portfolio_indexed}.
    """
    if not snapshots_list:
        return []

    # Build deposit lookup: {date_str: total_deposit_amount_myr}
    deposit_map = {}
    for d in deposits_list:
        dt = d["date"]
        amt = d["amount"]
        deposit_map[dt] = deposit_map.get(dt, 0) + amt

    # Sort snapshots by date (use timestamp field, extract date part)
    sorted_snaps = sorted(snapshots_list, key=lambda s: s["date"])

    twr_series = []
    cumulative_factor = 1.0

    for i, snap in enumerate(sorted_snaps):
        if i == 0:
            twr_series.append({
                "date": snap["date"],
                "twr_cumulative": 0.0,
                "twr_factor": 1.0,
                "portfolio_value": snap["total_nav"],
                "portfolio_indexed": 100.0,
            })
            continue

        prev_snap = sorted_snaps[i - 1]
        prev_value = prev_snap["total_nav"]
        curr_value = snap["total_nav"]

        # Check if there was a deposit on this day
        deposit_today = deposit_map.get(snap["date"], 0)

        # Sub-period return: end_value / (start_value + deposit) - 1
        denominator = prev_value + deposit_today
        if denominator > 0:
            sub_return = (curr_value / denominator) - 1
        else:
            sub_return = 0

        cumulative_factor *= (1 + sub_return)

        twr_series.append({
            "date": snap["date"],
            "twr_cumulative": (cumulative_factor - 1) * 100,
            "twr_factor": cumulative_factor,
            "portfolio_value": curr_value,
            "portfolio_indexed": 100 * cumulative_factor,
        })

    return twr_series


def calculate_period_returns(twr_series):
    """Calculate 1D/1W/1M/3M/YTD/1Y returns from TWR series."""
    if not twr_series or len(twr_series) < 2:
        return {"1D": None, "1W": None, "1M": None, "3M": None, "YTD": None, "1Y": None}

    today = date.today()
    latest = twr_series[-1]
    latest_factor = latest["twr_factor"]

    def get_factor_at_date(target_date):
        target_str = target_date.isoformat()
        best = None
        for entry in twr_series:
            if entry["date"] <= target_str:
                best = entry
            else:
                break
        return best

    def period_return(days_ago=None, target_date=None):
        if target_date is None:
            target_date = today - timedelta(days=days_ago)
        ref = get_factor_at_date(target_date)
        if ref is None or ref["twr_factor"] == 0:
            return None
        return ((latest_factor / ref["twr_factor"]) - 1) * 100

    ytd_start = date(today.year, 1, 1)

    return {
        "1D": period_return(days_ago=1),
        "1W": period_return(days_ago=7),
        "1M": period_return(days_ago=30),
        "3M": period_return(days_ago=90),
        "YTD": period_return(target_date=ytd_start),
        "1Y": period_return(days_ago=365),
    }


# ── Pydantic Models ────────────────────────────────────────────

class TargetWeight(BaseModel):
    ticker: str
    target_pct: float
    tier: str = "medium"  # high, medium, watch

class TradeEntry(BaseModel):
    ticker: str
    action: str  # "trim" or "add"
    shares: float
    price: float
    notes: str = ""

class SettingUpdate(BaseModel):
    key: str
    value: str

class ConvictionUpdate(BaseModel):
    ticker: str
    thesis: str = ""
    catalysts: list = []          # [{text, date, status}]
    invalidations: list = []      # [{text, triggered}]
    fair_value: float = 0
    valuation_method: str = ""    # e.g. "DCF", "Comps", "Yield", "Gut"
    valuation_notes: str = ""
    last_reviewed: str = ""


# ── App ────────────────────────────────────────────────────────

async def auto_snapshot_task():
    """Take a snapshot every 24 hours automatically"""
    while True:
        await asyncio.sleep(60)  # Wait 1 min after startup
        while True:
            try:
                # Check if we already snapshotted today
                db = get_db()
                today = datetime.now().strftime("%Y-%m-%d")
                existing = db.execute(
                    "SELECT id FROM snapshots WHERE timestamp LIKE ?", (f"{today}%",)
                ).fetchone()
                db.close()

                if not existing:
                    # Take snapshot
                    take_snapshot()
                    print(f"📸 Auto-snapshot taken at {datetime.now().isoformat()}")
            except Exception as e:
                print(f"⚠️ Auto-snapshot failed: {e}")

            await asyncio.sleep(3600)  # Check every hour

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Background: scan deposits + fetch benchmark
    threading.Thread(target=scan_and_store_deposits, daemon=True).start()
    threading.Thread(target=fetch_and_cache_benchmark, daemon=True).start()
    task = asyncio.create_task(auto_snapshot_task())
    yield
    task.cancel()

app = FastAPI(title="Portfolio Tracker", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(screener_router)


# ── Portfolio Endpoints ────────────────────────────────────────

@app.get("/api/portfolio")
def get_portfolio():
    """
    Returns full portfolio state with proper currency conversion.
    All weights and NAV calculated in MYR.
    Each position includes native currency values AND MYR equivalents.
    """
    fx_rate = get_usd_myr_rate()

    # Fetch positions + funds
    if USE_LIVE_API:
        positions = moomoo_client.get_positions()
        funds = moomoo_client.get_account_funds()
        my_cash = funds.get("my_cash", 0)
        fund_assets = funds.get("fund_assets", 0)
        cash_plus = my_cash + fund_assets
    else:
        positions = DEMO_POSITIONS.copy()
        cash_plus = DEMO_FUND_ASSETS

    # Add currency info and MYR conversion to each position
    for p in positions:
        is_us = p["code"].startswith("US.")
        p["currency"] = "USD" if is_us else "MYR"
        p["fx_rate"] = fx_rate if is_us else 1.0
        p["val_myr"] = round(p["val"] * fx_rate, 2) if is_us else p["val"]
        p["pl_val_myr"] = round(p["pl_val"] * fx_rate, 2) if is_us else p["pl_val"]
        p["unrealized_pl_myr"] = round(p.get("unrealized_pl", 0) * (fx_rate if is_us else 1.0), 2)
        p["realized_pl_myr"] = round(p.get("realized_pl", 0) * (fx_rate if is_us else 1.0), 2)
        p["cost_total_myr"] = round(p["cost_price"] * p["qty"] * (fx_rate if is_us else 1.0), 2)

    # Split active (qty > 0) and closed (qty == 0) positions
    active_positions = [p for p in positions if p["qty"] > 0]
    closed_positions = [p for p in positions if p["qty"] == 0 and p.get("realized_pl", 0) != 0]

    # Calculate NAV in MYR (active positions only)
    equity_nav = sum(p["val_myr"] for p in active_positions)
    total_nav = equity_nav + cash_plus

    # Load target weights from DB
    db = get_db()
    weights = {
        row["ticker"]: {"target_pct": row["target_pct"], "tier": row["tier"]}
        for row in db.execute("SELECT * FROM target_weights").fetchall()
    }
    settings = {
        row["key"]: row["value"]
        for row in db.execute("SELECT * FROM settings").fetchall()
    }
    drift_threshold = float(settings.get("drift_threshold", "2.0"))
    concentration_cap = float(settings.get("concentration_cap", "10.0"))
    db.close()

    # Enrich positions — weights based on MYR values
    enriched = []
    for p in active_positions:
        ticker = p["code"]
        weight_pct = (p["val_myr"] / total_nav * 100) if total_nav > 0 else 0
        target = weights.get(ticker, {})
        target_pct = target.get("target_pct", 0)
        tier = target.get("tier", "unset")
        drift = weight_pct - target_pct if target_pct > 0 else 0

        enriched.append({
            **p,
            "weight_pct": round(weight_pct, 2),
            "target_pct": target_pct,
            "tier": tier,
            "drift": round(drift, 2),
            "drift_alert": abs(drift) > drift_threshold if target_pct > 0 else False,
            "concentration_alert": weight_pct > concentration_cap,
        })

    enriched.sort(key=lambda x: x["weight_pct"], reverse=True)

    # Daily P&L total (in MYR, active only)
    today_pl_total = sum(
        p.get("today_pl", 0) * (fx_rate if p["code"].startswith("US.") else 1.0)
        for p in active_positions
    )

    # Total realized P&L across all positions (active + closed)
    total_realized_myr = sum(p.get("realized_pl_myr", 0) for p in positions)

    return {
        "positions": enriched,
        "closed_positions": closed_positions,
        "cash_plus": round(cash_plus, 2),
        "cash_plus_pct": round((cash_plus / total_nav * 100) if total_nav > 0 else 0, 2),
        "equity_nav": round(equity_nav, 2),
        "total_nav": round(total_nav, 2),
        "today_pl_total": round(today_pl_total, 2),
        "total_realized_myr": round(total_realized_myr, 2),
        "fx_rate": fx_rate,
        "settings": settings,
        "timestamp": datetime.now().isoformat(),
        "is_live": USE_LIVE_API,
    }


@app.get("/api/rebalance")
def get_rebalance_actions():
    """
    Generate trim/deploy recommendations based on drift from targets.
    Returns an action table: what to sell/buy to return to target weights.
    """
    portfolio = get_portfolio()
    positions = portfolio["positions"]
    cash_plus = portfolio["cash_plus"]
    equity_nav = portfolio["equity_nav"]
    drift_threshold = float(portfolio["settings"].get("drift_threshold", "2.0"))

    actions = []
    running_cash = cash_plus

    for p in positions:
        if p["target_pct"] <= 0:
            continue

        drift = p["drift"]
        if abs(drift) <= drift_threshold:
            continue

        drift_value = drift / 100 * equity_nav
        current_price = p["price"]

        if drift > 0 and current_price > 0:
            # Overweight → trim
            shares_to_sell = int(abs(drift_value) / current_price)
            if shares_to_sell > 0:
                sell_value = shares_to_sell * current_price
                running_cash += sell_value
                actions.append({
                    "ticker": p["code"],
                    "stock_name": p["stock_name"],
                    "current_pct": p["weight_pct"],
                    "target_pct": p["target_pct"],
                    "drift": drift,
                    "action": "SELL",
                    "shares": shares_to_sell,
                    "value": round(sell_value, 2),
                    "running_cash": round(running_cash, 2),
                })
        elif drift < 0 and current_price > 0:
            # Underweight → deploy cash
            buy_value = min(abs(drift_value), running_cash)
            shares_to_buy = int(buy_value / current_price)
            if shares_to_buy > 0:
                actual_cost = shares_to_buy * current_price
                running_cash -= actual_cost
                actions.append({
                    "ticker": p["code"],
                    "stock_name": p["stock_name"],
                    "current_pct": p["weight_pct"],
                    "target_pct": p["target_pct"],
                    "drift": drift,
                    "action": "BUY",
                    "shares": shares_to_buy,
                    "value": round(actual_cost, 2),
                    "running_cash": round(running_cash, 2),
                })

    return {
        "actions": actions,
        "starting_cash": cash_plus,
        "ending_cash": round(running_cash, 2),
    }


# ── Target Weight Endpoints ────────────────────────────────────

@app.get("/api/weights")
def get_weights():
    db = get_db()
    rows = db.execute("SELECT * FROM target_weights ORDER BY target_pct DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/weights")
def set_weight(w: TargetWeight):
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO target_weights (ticker, target_pct, tier, updated_at)
           VALUES (?, ?, ?, ?)""",
        (w.ticker, w.target_pct, w.tier, datetime.now().isoformat()),
    )
    db.commit()
    db.close()
    return {"ok": True}


@app.delete("/api/weights/{ticker}")
def delete_weight(ticker: str):
    db = get_db()
    db.execute("DELETE FROM target_weights WHERE ticker = ?", (ticker,))
    db.commit()
    db.close()
    return {"ok": True}


@app.post("/api/weights/bulk")
def set_weights_bulk(weights: list[TargetWeight]):
    db = get_db()
    now = datetime.now().isoformat()
    for w in weights:
        db.execute(
            """INSERT OR REPLACE INTO target_weights (ticker, target_pct, tier, updated_at)
               VALUES (?, ?, ?, ?)""",
            (w.ticker, w.target_pct, w.tier, now),
        )
    db.commit()
    db.close()
    return {"ok": True, "count": len(weights)}


# ── Snapshot Endpoints ─────────────────────────────────────────

@app.post("/api/snapshot")
def take_snapshot():
    """Snapshot current portfolio state to SQLite"""
    portfolio = get_portfolio()
    db = get_db()
    db.execute(
        """INSERT INTO snapshots (timestamp, total_nav, equity_nav, cash_plus, positions_json, weights_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().isoformat(),
            portfolio["total_nav"],
            portfolio["equity_nav"],
            portfolio["cash_plus"],
            json.dumps(portfolio["positions"]),
            json.dumps({p["code"]: p["weight_pct"] for p in portfolio["positions"]}),
        ),
    )
    db.commit()
    db.close()
    return {"ok": True, "timestamp": datetime.now().isoformat()}


@app.get("/api/snapshots")
def get_snapshots(days: int = Query(default=30, ge=1, le=365)):
    """Get historical snapshots for drift charts"""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT * FROM snapshots WHERE timestamp > ? ORDER BY timestamp ASC",
        (cutoff,),
    ).fetchall()
    db.close()

    result = []
    for row in rows:
        entry = dict(row)
        entry["weights"] = json.loads(entry.pop("weights_json", "{}"))
        entry.pop("positions_json", None)
        result.append(entry)
    return result


# ── Trade Log Endpoints ────────────────────────────────────────

@app.get("/api/trades")
def get_trades(limit: int = Query(default=50, ge=1, le=500)):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM trade_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/trades")
def log_trade(t: TradeEntry):
    db = get_db()
    db.execute(
        """INSERT INTO trade_log (ticker, action, shares, price, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (t.ticker, t.action, t.shares, t.price, t.notes),
    )
    db.commit()
    db.close()
    return {"ok": True}


# ── Settings Endpoints ─────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    db = get_db()
    rows = db.execute("SELECT * FROM settings").fetchall()
    db.close()
    return {row["key"]: row["value"] for row in rows}


@app.post("/api/settings")
def update_setting(s: SettingUpdate):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (s.key, s.value),
    )
    db.commit()
    db.close()
    return {"ok": True}


# ── Conviction Endpoints ──────────────────────────────────────

@app.get("/api/conviction")
def get_all_conviction():
    """Get conviction data for all positions."""
    db = get_db()
    rows = db.execute("SELECT * FROM conviction ORDER BY ticker").fetchall()
    db.close()
    result = {}
    for r in rows:
        result[r["ticker"]] = {
            "ticker": r["ticker"],
            "thesis": r["thesis"],
            "catalysts": json.loads(r["catalysts_json"]),
            "invalidations": json.loads(r["invalidations_json"]),
            "fair_value": r["fair_value"],
            "valuation_method": r["valuation_method"],
            "valuation_notes": r["valuation_notes"],
            "last_reviewed": r["last_reviewed"],
            "updated_at": r["updated_at"],
        }
    return result


@app.get("/api/conviction/{ticker}")
def get_conviction(ticker: str):
    """Get conviction data for a single position."""
    db = get_db()
    row = db.execute("SELECT * FROM conviction WHERE ticker = ?", (ticker,)).fetchone()
    db.close()
    if not row:
        return {
            "ticker": ticker, "thesis": "", "catalysts": [],
            "invalidations": [], "fair_value": 0,
            "valuation_method": "", "valuation_notes": "",
            "last_reviewed": "", "updated_at": "",
        }
    return {
        "ticker": row["ticker"],
        "thesis": row["thesis"],
        "catalysts": json.loads(row["catalysts_json"]),
        "invalidations": json.loads(row["invalidations_json"]),
        "fair_value": row["fair_value"],
        "valuation_method": row["valuation_method"],
        "valuation_notes": row["valuation_notes"],
        "last_reviewed": row["last_reviewed"],
        "updated_at": row["updated_at"],
    }


@app.post("/api/conviction")
def set_conviction(c: ConvictionUpdate):
    """Create or update conviction data for a position."""
    now = datetime.now().isoformat()
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO conviction
           (ticker, thesis, catalysts_json, invalidations_json,
            fair_value, valuation_method, valuation_notes, last_reviewed, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            c.ticker,
            c.thesis,
            json.dumps(c.catalysts),
            json.dumps(c.invalidations),
            c.fair_value,
            c.valuation_method,
            c.valuation_notes,
            c.last_reviewed or now,
            now,
        ),
    )
    db.commit()
    db.close()
    return {"ok": True, "ticker": c.ticker}


@app.delete("/api/conviction/{ticker}")
def delete_conviction(ticker: str):
    """Delete conviction data for a position."""
    db = get_db()
    db.execute("DELETE FROM conviction WHERE ticker = ?", (ticker,))
    db.commit()
    db.close()
    return {"ok": True}


# ── Health ─────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "live" if USE_LIVE_API else "demo",
        "db": str(DB_PATH),
        "timestamp": datetime.now().isoformat(),
    }


# ── Deposit Endpoints ─────────────────────────────────────────

@app.get("/api/deposits")
def get_deposits():
    """Get all stored deposits."""
    deposits = get_deposits_from_db()
    total = sum(d["amount"] for d in deposits)
    return {"deposits": deposits, "total_deposited": total}


@app.post("/api/deposits/scan")
def trigger_deposit_scan():
    """Trigger a fresh deposit scan."""
    scan_and_store_deposits()
    deposits = get_deposits_from_db()
    return {"ok": True, "deposits": deposits, "total": sum(d["amount"] for d in deposits)}


# ── Returns / TWR Endpoints ───────────────────────────────────

@app.get("/api/returns")
def get_returns(days: int = Query(default=365, ge=1, le=3650)):
    """
    Get time-weighted returns series with multiple benchmark overlays.
    Returns both indexed (base 100) and absolute price data.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    today_str = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()

    # Get snapshots
    db = get_db()
    snap_rows = db.execute(
        "SELECT * FROM snapshots WHERE timestamp > ? ORDER BY timestamp ASC",
        (cutoff,),
    ).fetchall()
    db.close()

    # Normalize snapshots
    snapshots_for_twr = []
    seen_dates = set()
    for row in snap_rows:
        ts = row["timestamp"]
        d = ts[:10]
        if d not in seen_dates:
            seen_dates.add(d)
            snapshots_for_twr.append({
                "date": d,
                "total_nav": row["total_nav"],
                "equity_nav": row["equity_nav"],
                "cash_plus": row["cash_plus"],
            })

    # Get deposits
    deposits = get_deposits_from_db()

    # Calculate TWR
    twr_series = calculate_twr(snapshots_for_twr, deposits)

    # Get ALL benchmark data
    all_benchmarks = {}
    for bm_key in BENCHMARKS:
        bm_data = get_benchmark_data(from_date, today_str, ticker=bm_key)
        if bm_data:
            base = bm_data[0]["close"]
            bm_map = {}
            for b in bm_data:
                bm_map[b["date"]] = {
                    "indexed": 100 * b["close"] / base if base else 100,
                    "close": b["close"],
                }
            all_benchmarks[bm_key] = bm_map

    # Merge into unified series
    merged = []
    last_bm_vals = {bk: {"indexed": 100, "close": 0} for bk in BENCHMARKS}
    for t in twr_series:
        row = {
            "date": t["date"],
            "portfolio": round(t["portfolio_indexed"], 2),
            "twr_pct": round(t["twr_cumulative"], 2),
            "value": round(t["portfolio_value"], 2),
        }
        # Add each benchmark
        for bm_key in BENCHMARKS:
            bm_map = all_benchmarks.get(bm_key, {})
            bm_day = bm_map.get(t["date"])
            if bm_day:
                last_bm_vals[bm_key] = bm_day
            row[f"{bm_key.lower()}_indexed"] = round(last_bm_vals[bm_key]["indexed"], 2)
            row[f"{bm_key.lower()}_close"] = round(last_bm_vals[bm_key]["close"], 2)
        merged.append(row)

    # Period returns
    period_returns = calculate_period_returns(twr_series)

    return {
        "series": merged,
        "period_returns": period_returns,
        "total_deposits": sum(d["amount"] for d in deposits),
        "deposit_count": len(deposits),
        "snapshot_count": len(snapshots_for_twr),
        "benchmarks": {
            bk: {"label": cfg["label"], "color": cfg["color"]}
            for bk, cfg in BENCHMARKS.items()
        },
    }


# ── Benchmark Endpoints ───────────────────────────────────────

@app.post("/api/benchmark/refresh")
def refresh_benchmark():
    """Force refresh all benchmark data."""
    fetch_and_cache_benchmark(days=365)
    return {"ok": True, "benchmarks": list(BENCHMARKS.keys())}


@app.get("/api/benchmark")
def get_benchmark(days: int = Query(default=365), ticker: str = Query(default="SPY")):
    """Get benchmark data for a specific ticker."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    today_str = date.today().isoformat()
    data = get_benchmark_data(cutoff, today_str, ticker=ticker)
    return {"data": data, "count": len(data), "ticker": ticker}


@app.get("/api/benchmarks/list")
def list_benchmarks():
    """Return available benchmarks with metadata and cached row counts."""
    db = get_db()
    result = {}
    for bk, cfg in BENCHMARKS.items():
        count = db.execute(
            "SELECT COUNT(*) as cnt FROM benchmark_cache WHERE ticker = ?", (bk,)
        ).fetchone()["cnt"]
        result[bk] = {**cfg, "cached_points": count}
    db.close()
    return result


@app.get("/api/benchmarks/daily")
def get_benchmark_daily_returns():
    """
    Return latest price + 1-day return for each benchmark.
    Used on the Dashboard for a market overview strip.
    """
    db = get_db()
    results = {}
    for bk, cfg in BENCHMARKS.items():
        rows = db.execute(
            "SELECT date, close FROM benchmark_cache WHERE ticker = ? ORDER BY date DESC LIMIT 2",
            (bk,),
        ).fetchall()
        if len(rows) >= 2:
            latest = rows[0]
            prev = rows[1]
            change = latest["close"] - prev["close"]
            change_pct = (change / prev["close"]) * 100 if prev["close"] else 0
            results[bk] = {
                "label": cfg["label"],
                "color": cfg["color"],
                "close": round(latest["close"], 2),
                "prev_close": round(prev["close"], 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "date": latest["date"],
            }
        elif len(rows) == 1:
            results[bk] = {
                "label": cfg["label"],
                "color": cfg["color"],
                "close": round(rows[0]["close"], 2),
                "prev_close": None,
                "change": None,
                "change_pct": None,
                "date": rows[0]["date"],
            }
    db.close()
    return results

