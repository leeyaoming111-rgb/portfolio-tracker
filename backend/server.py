"""
server.py — FastAPI backend for Portfolio Tracker

Proxies IBKR TWS/Gateway API calls (via ib_async) and manages:
- Portfolio data polling
- Target weight persistence (SQLite)
- Portfolio snapshots & trade log
- Drift calculations

Prerequisites:
  1. IB Gateway (or TWS) running and logged in
  2. API enabled in Gateway settings (Configure → Settings → API)
  3. Port 4001 (Gateway) or 7497 (TWS) open

Run: uvicorn server:app --port 8000
"""

import asyncio
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

# ── Toggle: True = use real IBKR API, False = demo data ──
USE_LIVE_API = True  # Set True once IB Gateway / TWS is running

if USE_LIVE_API:
    from ib_async import IB, Stock, Contract, util

# ── Configuration ──────────────────────────────────────────────
IBKR_HOST = "127.0.0.1"
IBKR_PORT = 4001        # IB Gateway default (use 7497 for TWS)
CLIENT_ID = 1            # Unique per concurrent connection
MARKET_DATA_TYPE = 3     # 3 = Delayed (free), 1 = Live (requires subscription)

# ── Live FX Rate ───────────────────────────────────────────────
import urllib.request

_fx_cache = {"rates": {"NZD": 1.0, "USD": 0.625, "JPY": 93.0}, "fetched_at": 0}

def get_fx_rates():
    """Fetch all FX rates with NZD as base, cached 1 hour.
    Returns dict: {"USD": 0.625, "JPY": 93.5, "NZD": 1.0, ...}
    To convert X to NZD: value_in_x / rates[X]
    """
    now = time.time()
    if now - _fx_cache["fetched_at"] < 3600:
        return _fx_cache["rates"]
    try:
        url = "https://open.er-api.com/v6/latest/NZD"
        req = urllib.request.Request(url, headers={"User-Agent": "PortfolioTracker/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            rates = data["rates"]
            _fx_cache["rates"] = rates
            _fx_cache["fetched_at"] = now
            print(f"📈 FX updated: 1 NZD = {rates.get('USD',0):.4f} USD, {rates.get('JPY',0):.2f} JPY")
            return rates
    except Exception as e:
        print(f"⚠️  FX fetch failed: {e}")
        return _fx_cache["rates"]

def to_nzd(value, currency):
    """Convert any currency value to NZD."""
    if currency == "NZD":
        return value
    rates = get_fx_rates()
    rate = rates.get(currency, 1.0)
    return value / rate if rate > 0 else value

def fx_rate_for(currency):
    """Get the multiplier to convert 1 unit of currency to NZD."""
    if currency == "NZD":
        return 1.0
    rates = get_fx_rates()
    rate = rates.get(currency, 1.0)
    return 1.0 / rate if rate > 0 else 1.0

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

    c.execute("""
        CREATE TABLE IF NOT EXISTS realized_pnl (
            ticker TEXT PRIMARY KEY,
            stock_name TEXT DEFAULT '',
            currency TEXT DEFAULT 'NZD',
            total_realized REAL DEFAULT 0,
            total_realized_nzd REAL DEFAULT 0,
            cost_basis REAL DEFAULT 0,
            cost_basis_nzd REAL DEFAULT 0,
            gain_pct REAL DEFAULT 0,
            shares_sold REAL DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # All cash movements from IBKR Flex (dividends, interest, fees, taxes, …)
    c.execute("""
        CREATE TABLE IF NOT EXISTS cash_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            symbol TEXT DEFAULT '',
            description TEXT DEFAULT '',
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            amount_base REAL DEFAULT 0,
            UNIQUE(date, type, symbol, amount, currency, description)
        )
    """)

    # Daily NAV in base currency, as reported by IBKR (Flex Equity Summary).
    # This is the same valuation series PortfolioAnalyst uses for TWR.
    c.execute("""
        CREATE TABLE IF NOT EXISTS nav_history (
            date TEXT PRIMARY KEY,
            total REAL NOT NULL,
            cash REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            source TEXT DEFAULT 'flex'
        )
    """)

    # Migrate: add new columns to realized_pnl if missing
    for col, typ in [("cost_basis", "REAL DEFAULT 0"), ("cost_basis_nzd", "REAL DEFAULT 0"),
                     ("gain_pct", "REAL DEFAULT 0"), ("shares_sold", "REAL DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE realized_pnl ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Migrate: deposits gain amount_base (NZD value at IBKR's own FX rate on the day)
    try:
        c.execute("ALTER TABLE deposits ADD COLUMN amount_base REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Persistent company-name cache (filled from IBKR contract details only)
    c.execute("""
        CREATE TABLE IF NOT EXISTS name_cache (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL
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
    {"code": "NZ.SPK", "stock_name": "Spark New Zealand", "qty": 500, "cost_price": 4.80, "price": 5.12, "val": 2560.00, "pl_val": 160.00, "pl_ratio": 6.67},
    {"code": "NZ.AIR", "stock_name": "Air New Zealand", "qty": 800, "cost_price": 0.72, "price": 0.78, "val": 624.00, "pl_val": 48.00, "pl_ratio": 7.69},
    {"code": "US.JPM", "stock_name": "JPMorgan Chase", "qty": 20, "cost_price": 185.00, "price": 252.93, "val": 5058.60, "pl_val": 1358.60, "pl_ratio": 36.69},
    {"code": "US.V", "stock_name": "Visa Inc", "qty": 18, "cost_price": 260.00, "price": 341.12, "val": 6140.16, "pl_val": 1460.16, "pl_ratio": 31.20},
    {"code": "US.UNH", "stock_name": "UnitedHealth", "qty": 8, "cost_price": 520.00, "price": 487.65, "val": 3901.20, "pl_val": -258.80, "pl_ratio": -6.22},
]

DEMO_FUND_ASSETS = 15420.00  # Cash Plus balance
DEMO_TOTAL_ASSETS = sum(p["val"] for p in DEMO_POSITIONS) + DEMO_FUND_ASSETS


# ── IBKR API Layer ─────────────────────────────────────────────

class IBKRClient:
    """
    Wraps ib_async (Interactive Brokers) API calls.

    Runs the IB event loop in a background thread so it doesn't
    conflict with FastAPI / uvicorn's asyncio loop.  State queries
    (positions, account values) read from ib_async's auto-synced
    cache — no network call.  Request methods (historical data,
    executions) are scheduled on the IB loop via run_coroutine_threadsafe.
    """

    def __init__(self, host=IBKR_HOST, port=IBKR_PORT, client_id=CLIENT_ID):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self._loop = None
        self._thread = None
        self._name_cache = {}       # contract key → long company name
        self._connected = False
        self._pnl_sub = None        # account-level PnL subscription

    # ── Connection management ──────────────────────────────────

    def connect(self):
        """Start IB connection in a background daemon thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Wait for the initial sync to complete (up to 15 s)
        for _ in range(150):
            if self._connected:
                return True
            time.sleep(0.1)
        raise ConnectionError(
            f"Could not connect to IBKR on {self.host}:{self.port}. "
            "Is IB Gateway / TWS running and API enabled?"
        )

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_run())

    async def _async_run(self):
        """Connect, configure, then spin forever keeping the session alive."""
        await self.ib.connectAsync(
            self.host, self.port,
            clientId=self.client_id,
            readonly=True,          # read-only — no order placement
        )
        self.ib.reqMarketDataType(MARKET_DATA_TYPE)
        self._connected = True
        print(f"✅ Connected to IBKR on {self.host}:{self.port}")

        # Keep alive — reconnect if Gateway restarts
        while True:
            await asyncio.sleep(5)
            if not self.ib.isConnected():
                self._connected = False
                print("⚠️  IBKR disconnected, attempting reconnect...")
                try:
                    await self.ib.connectAsync(
                        self.host, self.port,
                        clientId=self.client_id,
                        readonly=True,
                    )
                    self.ib.reqMarketDataType(MARKET_DATA_TYPE)
                    self._connected = True
                    print("✅ IBKR reconnected")
                except Exception as e:
                    print(f"❌ IBKR reconnect failed: {e}")

    def _run_coro(self, coro, timeout=60):
        """Schedule an async operation on the IB event loop, wait for result."""
        if not self._loop or not self.ib.isConnected():
            raise ConnectionError("Not connected to IBKR")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Helpers ────────────────────────────────────────────────

    CURRENCY_PREFIX = {"NZD": "NZ", "USD": "US", "MYR": "MY", "JPY": "JP",
                       "AUD": "AU", "GBP": "UK", "EUR": "EU", "HKD": "HK",
                       "SGD": "SG", "CAD": "CA", "KRW": "KR", "TWD": "TW"}

    def _contract_to_code(self, contract):
        """Convert IBKR Contract to internal ticker: JP.6315, US.AAPL, NZ.SPK"""
        cur = getattr(contract, "currency", "USD")
        sym = getattr(contract, "symbol", "???")
        prefix = self.CURRENCY_PREFIX.get(cur, cur[:2])
        return f"{prefix}.{sym}"

    EXCHANGE_MAP = {"NZ": ("NZE", "NZD"), "US": ("SMART", "USD"), "MY": ("MYS", "MYR"),
                    "JP": ("TSEJ", "JPY"), "AU": ("ASX", "AUD"), "UK": ("LSE", "GBP"),
                    "EU": ("SBF", "EUR"), "HK": ("SEHK", "HKD"), "SG": ("SGX", "SGD"),
                    "CA": ("TSE", "CAD"), "KR": ("KSE", "KRW"), "TW": ("TWSE", "TWD")}

    def _code_to_contract(self, code):
        """Convert internal ticker back to IBKR Contract."""
        parts = code.split(".", 1)
        if len(parts) != 2:
            return Stock(code, "SMART", "USD")
        prefix, symbol = parts
        exchange, currency = self.EXCHANGE_MAP.get(prefix, ("SMART", "USD"))
        return Stock(symbol, exchange, currency)

    def _get_stock_name(self, contract):
        """
        Company name, from IBKR ONLY — never guessed.
        Lookup order: in-memory cache → SQLite name_cache → reqContractDetails.
        Never raises — returns contract.symbol on any failure.
        """
        symbol = getattr(contract, "symbol", "???")
        key = f"{symbol}_{getattr(contract, 'currency', 'USD')}"
        if key in self._name_cache:
            return self._name_cache[key]

        try:
            db = get_db()
            row = db.execute("SELECT name FROM name_cache WHERE key = ?", (key,)).fetchone()
            db.close()
            if row:
                self._name_cache[key] = row["name"]
                return row["name"]
        except Exception:
            pass

        name = None
        try:
            async def _fetch():
                details = await self.ib.reqContractDetailsAsync(contract)
                return details[0].longName if details else None
            name = self._run_coro(_fetch(), timeout=3)
        except Exception:
            pass

        if name:
            self._name_cache[key] = name
            try:
                db = get_db()
                db.execute("INSERT OR REPLACE INTO name_cache (key, name) VALUES (?, ?)", (key, name))
                db.commit()
                db.close()
            except Exception:
                pass
            return name

        return symbol

    # ── Portfolio / positions ──────────────────────────────────

    def get_positions(self):
        """
        Fetch current holdings from ib_async's auto-synced cache.

        ib.portfolio() returns PortfolioItem objects with:
          contract, position, marketPrice, marketValue,
          averageCost, unrealizedPNL, realizedPNL, account
        """
        items = self.ib.portfolio()
        positions = []
        for item in items:
            qty = float(item.position)
            avg_cost = float(item.averageCost)
            price = float(item.marketPrice)
            val = float(item.marketValue)
            unrealized_pl = float(item.unrealizedPNL)
            realized_pl = float(item.realizedPNL)
            total_pl = unrealized_pl + realized_pl

            # Compute P&L ratio vs average cost
            cost_basis = avg_cost * abs(qty) if avg_cost and qty else 0
            pl_ratio = (unrealized_pl / cost_basis * 100) if cost_basis > 0 else 0

            code = self._contract_to_code(item.contract)
            stock_name = self._get_stock_name(item.contract)
            api_currency = getattr(item.contract, "currency", "USD")

            positions.append({
                "code": code,
                "stock_name": stock_name,
                "qty": qty,
                "cost_price": round(avg_cost, 4),
                "diluted_cost": round(avg_cost, 4),   # IBKR only has averageCost
                "price": round(price, 4),
                "val": round(val, 2),
                "pl_val": round(total_pl, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "realized_pl": round(realized_pl, 2),
                "pl_ratio": round(pl_ratio, 2),
                "today_pl": 0,                         # Requires separate PnL subscription
                "api_currency": api_currency,
            })
        return positions

    def get_account_funds(self):
        """
        Extract account-level values from ib_async's auto-synced cache.

        accountValues() returns AccountValue(account, tag, value, currency, modelCode).
        We extract the key tags we need.
        """
        values = self.ib.accountValues()
        result = {
            "total_assets": 0,
            "market_val": 0,
            "cash": 0,
            "power": 0,
            "my_cash": 0,          # NZD cash (base currency)
            "fund_assets": 0,      # No money-market fund concept in IBKR
        }
        for v in values:
            tag = v.tag
            cur = v.currency
            try:
                val = float(v.value)
            except (ValueError, TypeError):
                continue

            if tag == "NetLiquidation" and cur == "BASE":
                result["total_assets"] = val
            elif tag == "GrossPositionValue" and cur == "BASE":
                result["market_val"] = val
            elif tag == "TotalCashBalance" and cur == "BASE":
                result["cash"] = val
                result["my_cash"] = val   # Base currency cash
            elif tag == "BuyingPower":
                result["power"] = val
            elif tag == "CashBalance" and cur == "NZD":
                result["my_cash"] = val
            elif tag == "CashBalance" and cur == "USD":
                result["us_cash"] = val

        return result

    def get_real_time_quotes(self, codes: list):
        """Get snapshot quotes for a list of our internal ticker codes."""
        contracts = [self._code_to_contract(c) for c in codes]
        try:
            async def _fetch():
                tickers = await self.ib.reqTickersAsync(*contracts)
                return {
                    self._contract_to_code(t.contract): float(t.last or t.close or 0)
                    for t in tickers
                }
            return self._run_coro(_fetch(), timeout=15)
        except Exception as e:
            print(f"⚠️  Quote fetch failed: {e}")
            return {}

    def get_history_kline(self, code, start_date, end_date, max_count=1000, exchange_override=None):
        """
        Fetch historical daily bar data from IBKR.
        Returns list of {date, open, close, high, low, volume}.
        """
        contract = self._code_to_contract(code)
        if exchange_override:
            contract.exchange = exchange_override

        # Calculate duration string from date range
        start_d = datetime.strptime(start_date, "%Y-%m-%d")
        end_d = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end_d - start_d).days + 1
        if days > 365:
            duration = f"{days // 30 + 1} M"
        else:
            duration = f"{days} D"

        for what_to_show in ["TRADES", "MIDPOINT"]:
            try:
                async def _fetch():
                    bars = await self.ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime=end_date.replace("-", "") + " 23:59:59",
                        durationStr=duration,
                        barSizeSetting="1 day",
                        whatToShow=what_to_show,
                        useRTH=True,
                        formatDate=1,
                    )
                    return bars

                bars = self._run_coro(_fetch(), timeout=30)
                if bars:
                    return [
                        {
                            "date": str(bar.date)[:10],
                            "open": float(bar.open),
                            "close": float(bar.close),
                            "high": float(bar.high),
                            "low": float(bar.low),
                            "volume": float(bar.volume),
                        }
                        for bar in bars
                    ]
            except Exception as e:
                if what_to_show == "TRADES":
                    print(f"⚠️  TRADES failed for {code}, trying MIDPOINT...")
                    continue
                print(f"⚠️  Historical data fetch failed for {code}: {e}")
        return []

    def get_deal_history(self, start_date, end_date):
        """
        Fetch executed trades from IBKR.

        NOTE: IBKR TWS API only provides executions from the *current session*
        via ib.executions(). For full history, use IBKR Flex Queries (web).
        We also store executions to SQLite as they arrive.
        """
        # Current session executions
        fills = self.ib.fills()
        deals = []
        for fill in fills:
            exec_obj = fill.execution
            contract = fill.contract
            create_time = exec_obj.time.strftime("%Y-%m-%d %H:%M:%S") if exec_obj.time else ""
            if create_time[:10] < start_date or create_time[:10] > end_date:
                continue
            deals.append({
                "code": self._contract_to_code(contract),
                "stock_name": getattr(contract, "symbol", ""),
                "deal_id": str(exec_obj.execId),
                "order_id": str(exec_obj.orderId),
                "qty": float(exec_obj.shares),
                "price": float(exec_obj.price),
                "trd_side": exec_obj.side,          # "BOT" or "SLD"
                "create_time": create_time,
                "dealt_avg_price": float(exec_obj.avgPrice),
            })
        return deals

    def get_order_history(self, start_date, end_date):
        """
        Fetch completed orders from IBKR.

        NOTE: reqCompletedOrders only returns orders from the last ~24 hours.
        For full history, use IBKR Flex Queries.
        """
        try:
            async def _fetch():
                trades = await self.ib.reqCompletedOrdersAsync(apiOnly=False)
                return trades

            trades = self._run_coro(_fetch(), timeout=15)
        except Exception:
            trades = []

        orders = []
        for trade in trades:
            contract = trade.contract
            order = trade.order
            status = trade.orderStatus
            fill_time = ""
            if trade.fills:
                fill_time = str(trade.fills[-1].execution.time)[:19]
            elif hasattr(status, "lastFillPrice"):
                fill_time = ""

            orders.append({
                "code": self._contract_to_code(contract),
                "stock_name": getattr(contract, "symbol", ""),
                "order_id": str(order.orderId),
                "order_type": order.orderType,
                "order_status": status.status,
                "qty": float(order.totalQuantity),
                "price": float(order.lmtPrice) if order.lmtPrice else 0,
                "dealt_qty": float(status.filled),
                "dealt_avg_price": float(status.avgFillPrice),
                "trd_side": order.action,            # "BUY" or "SELL"
                "create_time": fill_time,
                "updated_time": fill_time,
            })
        return orders

    # ── Account summary / margin / balances ────────────────────

    # Account-level tags worth surfacing (all reported in base currency)
    SUMMARY_TAGS = [
        "NetLiquidation", "EquityWithLoanValue", "GrossPositionValue",
        "TotalCashBalance", "TotalCashValue", "BuyingPower", "AvailableFunds",
        "ExcessLiquidity", "Cushion", "FullInitMarginReq", "FullMaintMarginReq",
        "InitMarginReq", "MaintMarginReq", "SMA", "Leverage",
        "AccruedCash", "AccruedDividend", "DayTradesRemaining",
        "LookAheadAvailableFunds", "LookAheadExcessLiquidity",
        "RealizedPnL", "UnrealizedPnL",
    ]

    def get_account_summary_full(self):
        """
        Full account-level metrics (margin, buying power, liquidity, accruals)
        plus per-currency cash and stock balances — mirrors what IBKR's
        Account window / Client Portal shows.
        """
        values = self.ib.accountValues()
        summary = {}
        balances = {}   # currency → {cash, stock, net}
        for v in values:
            try:
                val = float(v.value)
            except (ValueError, TypeError):
                continue
            tag, cur = v.tag, v.currency

            if tag in self.SUMMARY_TAGS and (cur in ("BASE", "", None) or tag not in summary):
                summary[tag] = val

            if cur and cur not in ("BASE", ""):
                bal = balances.setdefault(cur, {"cash": 0.0, "stock": 0.0, "net": 0.0})
                if tag == "CashBalance":
                    bal["cash"] = val
                elif tag == "StockMarketValue":
                    bal["stock"] = val
                elif tag == "NetLiquidationByCurrency":
                    bal["net"] = val

        return {"summary": summary, "balances_by_currency": balances}

    def get_open_orders(self):
        """Fetch all live/open orders (incl. those placed in TWS or mobile)."""
        async def _fetch():
            await self.ib.reqAllOpenOrdersAsync()
            return list(self.ib.openTrades())

        trades = self._run_coro(_fetch(), timeout=15)
        orders = []
        for trade in trades:
            order = trade.order
            status = trade.orderStatus
            orders.append({
                "code": self._contract_to_code(trade.contract),
                "stock_name": getattr(trade.contract, "symbol", ""),
                "order_id": str(order.orderId),
                "perm_id": str(order.permId),
                "order_type": order.orderType,
                "order_status": status.status,
                "trd_side": order.action,
                "qty": float(order.totalQuantity),
                "limit_price": float(order.lmtPrice) if order.lmtPrice else 0,
                "aux_price": float(order.auxPrice) if order.auxPrice else 0,
                "tif": order.tif,
                "filled": float(status.filled),
                "remaining": float(status.remaining),
                "avg_fill_price": float(status.avgFillPrice),
                "currency": getattr(trade.contract, "currency", "USD"),
            })
        return orders

    def get_daily_pnl(self):
        """
        Account-level daily P&L via the reqPnL subscription
        (same numbers as the TWS account header).
        """
        import math

        if self._pnl_sub is None:
            account = self.ib.managedAccounts()[0] if self.ib.managedAccounts() else ""

            async def _subscribe():
                pnl = self.ib.reqPnL(account)
                # Wait briefly for the first update to arrive
                for _ in range(20):
                    await asyncio.sleep(0.25)
                    if pnl.dailyPnL == pnl.dailyPnL:  # not NaN
                        break
                return pnl

            self._pnl_sub = self._run_coro(_subscribe(), timeout=10)

        p = self._pnl_sub
        clean = lambda x: 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
        return {
            "daily_pnl": round(clean(p.dailyPnL), 2),
            "unrealized_pnl": round(clean(p.unrealizedPnL), 2),
            "realized_pnl": round(clean(p.realizedPnL), 2),
        }


# Global client (only initialized if USE_LIVE_API)
ibkr_client = IBKRClient() if USE_LIVE_API else None

BENCHMARK_KEY = "SPY"
CASHFLOW_SCAN_DAYS = 365

# ── Multi-Benchmark Configuration ────────────────────────────
BENCHMARKS = {
    "SPY":  {"ibkr": "US.SPY",  "fmp": "SPY",  "label": "S&P 500",           "color": "#d29922",
             "exchange": "ARCA"},
    "ACWI": {"ibkr": "US.ACWI", "fmp": "ACWI", "label": "MSCI ACWI (Global)", "color": "#a371f7"},
    "QQQ":  {"ibkr": "US.QQQ",  "fmp": "QQQ",  "label": "Nasdaq 100",         "color": "#f778ba",
             "exchange": "NASDAQ"},
    "EEM":  {"ibkr": "US.EEM",  "fmp": "EEM",  "label": "Emerging Markets",   "color": "#3fb950",
             "exchange": "ARCA"},
}


# ── Deposit Management via IBKR Flex Queries ─────────────────
#
# IBKR's TWS API (what ib_async talks to) doesn't expose deposit
# history.  But the Flex Web Service — a separate REST API — does.
#
# One-time setup (in IBKR Client Portal):
#   1. Go to Performance & Reports → Flex Queries
#   2. Create a new Activity Flex Query
#   3. Include these sections (select all fields in each):
#        - "Cash Transactions"  → deposits/withdrawals, dividends, interest, fees
#        - "Net Asset Value (NAV) in Base" → daily NAV, so TWR is computed
#          on the exact valuations PortfolioAnalyst uses
#          (XML: EquitySummaryByReportDateInBase, one row per report date)
#        - "Trades" → realized P&L
#   4. Set date period to "Last 365 Calendar Days"
#   5. Save — note the Query ID
#   6. Go to Flex Web Service Configuration → generate a token
#   7. Save token to ~/.ibkr_flex_token
#   8. Save query ID to ~/.ibkr_flex_query_id
#
# Once configured, everything syncs automatically on startup and
# can be re-triggered via POST /api/deposits/scan.

import xml.etree.ElementTree as ET

FLEX_TOKEN_FILE = os.path.expanduser("~/.ibkr_flex_token")
FLEX_QUERY_ID_FILE = os.path.expanduser("~/.ibkr_flex_query_id")
FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


def _read_flex_config():
    """Read Flex token and query ID from config files."""
    token, query_id = None, None
    if os.path.exists(FLEX_TOKEN_FILE):
        with open(FLEX_TOKEN_FILE) as f:
            token = f.read().strip()
    if os.path.exists(FLEX_QUERY_ID_FILE):
        with open(FLEX_QUERY_ID_FILE) as f:
            query_id = f.read().strip()
    return token, query_id


def _fetch_flex_report():
    """
    Download a Flex report via the two-step Flex Web Service flow:
      1. GET SendRequest → reference code
      2. GET GetStatement → XML report (retry while it generates)
    Returns the raw XML text, or None.
    """
    token, query_id = _read_flex_config()
    if not token or not query_id:
        print("⚠️  Flex Query not configured — skipping deposit sync")
        print("   Create ~/.ibkr_flex_token and ~/.ibkr_flex_query_id")
        return None

    headers = {"User-Agent": "Python/3.12"}

    # Step 1: Request the report
    try:
        send_url = f"{FLEX_BASE_URL}/SendRequest?t={token}&q={query_id}&v=3"
        req = urllib.request.Request(send_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            send_xml = resp.read().decode()

        root = ET.fromstring(send_xml)
        status = root.findtext("Status")
        if status != "Success":
            error_msg = root.findtext("ErrorMessage", "Unknown error")
            print(f"⚠️  Flex SendRequest failed: {error_msg}")
            return None

        ref_code = root.findtext("ReferenceCode")
        if not ref_code:
            print("⚠️  No reference code in Flex response")
            return None

        print(f"📋 Flex report requested (ref: {ref_code}), waiting for generation...")
    except Exception as e:
        print(f"⚠️  Flex SendRequest error: {e}")
        return None

    # Step 2: Wait, then fetch the report (retry up to 5 times)
    report_xml = None
    for attempt in range(5):
        time.sleep(3 + attempt * 2)  # 3s, 5s, 7s, 9s, 11s
        try:
            get_url = f"{FLEX_BASE_URL}/GetStatement?t={token}&q={ref_code}&v=3"
            req = urllib.request.Request(get_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                report_xml = resp.read().decode()

            # Check if it's still being generated
            if "<Status>Warn</Status>" in report_xml or "<ErrorCode>1019</ErrorCode>" in report_xml:
                print(f"   Report not ready yet (attempt {attempt + 1}/5)...")
                continue

            break
        except Exception as e:
            print(f"   Fetch attempt {attempt + 1}/5 failed: {e}")

    if not report_xml or "<FlexQueryResponse" not in report_xml:
        print("⚠️  Could not retrieve Flex report after 5 attempts")
        return None

    _last_flex_report["xml"] = report_xml  # Cache for realized P&L parsing
    return report_xml


def _normalize_flex_date(raw):
    """Normalize IBKR's date formats (yyyyMMdd, yyyy-MM-dd, with ;HHMMSS suffix)."""
    if ";" in raw:
        raw = raw.split(";")[0]
    raw = raw[:10]
    if len(raw) == 8 and "-" not in raw:
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def parse_flex_report(report_xml):
    """
    Parse a Flex Activity report into:
      deposits   — external cash flows (deposits/withdrawals), signed info preserved
      cash_txns  — ALL cash transactions (dividends, interest, fees, taxes, …)
      nav        — daily NAV in base currency (Equity Summary / Change in NAV sections)

    fxRateToBase (IBKR's own FX rate on the transaction date) is used to express
    every flow in base currency — exactly what PortfolioAnalyst does.
    """
    deposits, cash_txns, nav = [], [], []
    try:
        root = ET.fromstring(report_xml)
        for stmt in root.iter("FlexStatement"):
            for txn in stmt.iter("CashTransaction"):
                txn_type = txn.get("type", "")
                amount = float(txn.get("amount", 0))
                currency = txn.get("currency", "NZD")
                txn_date = _normalize_flex_date(txn.get("dateTime", txn.get("reportDate", "")))
                description = txn.get("description", "")
                symbol = txn.get("symbol", "")
                try:
                    fx_to_base = float(txn.get("fxRateToBase", 0)) or None
                except (ValueError, TypeError):
                    fx_to_base = None
                amount_base = amount * fx_to_base if fx_to_base else amount * fx_rate_for(currency)

                cash_txns.append({
                    "date": txn_date, "type": txn_type, "symbol": symbol,
                    "description": description, "amount": amount,
                    "currency": currency, "amount_base": round(amount_base, 2),
                })

                if "Deposits" in txn_type or "Withdrawals" in txn_type:
                    deposits.append({
                        "date": txn_date,
                        "amount": abs(amount),
                        "currency": currency,
                        "remark": description or f"IBKR {txn_type}",
                        "direction": "IN" if amount > 0 else "OUT",
                        "amount_base": round(abs(amount_base), 2),
                    })

            # Daily NAV in base currency — the valuation series PortfolioAnalyst uses
            for eq in stmt.iter("EquitySummaryByReportDateInBase"):
                d = _normalize_flex_date(eq.get("reportDate", ""))
                total = float(eq.get("total", 0) or 0)
                if d and total > 0:
                    nav.append({
                        "date": d, "total": total,
                        "cash": float(eq.get("cash", 0) or 0),
                        "stock": float(eq.get("stock", 0) or 0),
                    })

        print(f"✅ Flex parsed: {len(deposits)} deposits/withdrawals, "
              f"{len(cash_txns)} cash transactions, {len(nav)} daily NAV records")
    except ET.ParseError as e:
        print(f"⚠️  Flex XML parse error: {e}")
    except Exception as e:
        print(f"⚠️  Flex processing error: {e}")

    return {"deposits": deposits, "cash_txns": cash_txns, "nav": nav}


def fetch_deposits_from_flex():
    """Fetch + parse the Flex report, returning deposit/withdrawal records."""
    report_xml = _fetch_flex_report()
    if not report_xml:
        return []
    return parse_flex_report(report_xml)["deposits"]


def scan_and_store_deposits():
    """
    Full Flex sync: deposits/withdrawals, all cash transactions (dividends,
    interest, fees), daily NAV history, and realized P&L.
    Skips duplicates via UNIQUE constraints.
    """
    report_xml = _fetch_flex_report()
    parsed = parse_flex_report(report_xml) if report_xml else {"deposits": [], "cash_txns": [], "nav": []}

    db = get_db()

    # Store deposits (update amount_base on existing rows that pre-date the column)
    new_count = 0
    for d in parsed["deposits"]:
        cur = db.execute(
            """INSERT OR IGNORE INTO deposits (date, amount, currency, remark, direction, amount_base)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (d["date"], d["amount"], d["currency"], d["remark"], d["direction"], d["amount_base"]),
        )
        if cur.rowcount > 0:
            new_count += 1
        else:
            db.execute(
                """UPDATE deposits SET amount_base = ?, direction = ?
                   WHERE date = ? AND amount = ? AND currency = ? AND (amount_base IS NULL OR amount_base = 0)""",
                (d["amount_base"], d["direction"], d["date"], d["amount"], d["currency"]),
            )
    if parsed["deposits"]:
        print(f"✅ Deposit sync complete. {new_count} new records stored.")

    # Store all cash transactions
    for t in parsed["cash_txns"]:
        db.execute(
            """INSERT OR IGNORE INTO cash_transactions
               (date, type, symbol, description, amount, currency, amount_base)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (t["date"], t["type"], t["symbol"], t["description"],
             t["amount"], t["currency"], t["amount_base"]),
        )

    # Store daily NAV history (IBKR's official base-currency valuations)
    for n in parsed["nav"]:
        db.execute(
            """INSERT OR REPLACE INTO nav_history (date, total, cash, stock, source)
               VALUES (?, ?, ?, ?, 'flex')""",
            (n["date"], n["total"], n["cash"], n["stock"]),
        )
    if parsed["nav"]:
        print(f"✅ Stored {len(parsed['nav'])} daily NAV records")

    db.commit()

    # Also parse realized P&L from the same Flex report (if section exists)
    _sync_realized_from_flex(db)

    # Store last scan timestamp
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("last_deposit_scan", datetime.now().isoformat()),
    )
    db.commit()
    db.close()


_last_flex_report = {"xml": None}  # Cache last Flex report for realized P&L parsing


def _sync_realized_from_flex(db):
    """Parse realized P&L from the cached Flex report XML.
    Aggregates all closing trades per ticker from scratch each run to avoid double-counting.
    """
    xml_text = _last_flex_report.get("xml")
    if not xml_text:
        return

    try:
        root = ET.fromstring(xml_text)
        # Aggregate all closing trades in memory first, then write once
        agg = {}  # ticker -> {realized, cost, shares, symbol, currency}
        for stmt in root.iter("FlexStatement"):
            for trade in stmt.iter("Trade"):
                code_str = trade.get("openCloseIndicator", "")
                if code_str not in ("C", "C;O"):
                    continue

                symbol = trade.get("symbol", "")
                currency = trade.get("currency", "USD")
                realized = float(trade.get("fifoPnlRealized", 0))
                cost = float(trade.get("cost", 0))
                qty = abs(float(trade.get("quantity", 0)))

                if realized == 0 or not symbol:
                    continue

                prefix_map = {"NZD": "NZ", "USD": "US", "MYR": "MY", "JPY": "JP",
                              "AUD": "AU", "GBP": "UK", "EUR": "EU"}
                prefix = prefix_map.get(currency, currency[:2])
                ticker = f"{prefix}.{symbol}"

                if ticker in agg:
                    agg[ticker]["realized"] += realized
                    agg[ticker]["cost"] += abs(cost)
                    agg[ticker]["shares"] += qty
                else:
                    agg[ticker] = {
                        "realized": realized,
                        "cost": abs(cost),
                        "shares": qty,
                        "symbol": symbol,
                        "currency": currency,
                    }

        if not agg:
            return

        # Clear old Flex-sourced records and write fresh aggregates
        db.execute("DELETE FROM realized_pnl")
        for ticker, d in agg.items():
            multiplier = fx_rate_for(d["currency"])
            realized_nzd = round(d["realized"] * multiplier, 2)
            cost_nzd = round(d["cost"] * multiplier, 2)
            gain_pct = round((d["realized"] / d["cost"]) * 100, 2) if d["cost"] > 0 else 0

            db.execute(
                """INSERT INTO realized_pnl
                   (ticker, stock_name, currency, total_realized, total_realized_nzd,
                    cost_basis, cost_basis_nzd, gain_pct, shares_sold, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (ticker, d["symbol"], d["currency"], d["realized"], realized_nzd,
                 d["cost"], cost_nzd, gain_pct, d["shares"]),
            )

        db.commit()
        print(f"✅ Synced {len(agg)} realized P&L records from Flex trades")
    except Exception as e:
        print(f"⚠️  Realized P&L sync error: {e}")


def get_deposits_from_db():
    """Retrieve all stored deposits from SQLite."""
    db = get_db()
    rows = db.execute(
        "SELECT date, amount, currency, remark, direction, amount_base FROM deposits ORDER BY date"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_external_flows():
    """
    Build per-date external cash flows in base currency (NZD):
      {date: {"in": deposits_nzd, "out": withdrawals_nzd}}

    Uses IBKR's own fxRateToBase when synced via Flex; falls back to the
    current FX rate for manually-entered records.
    """
    flows = {}
    seen = set()
    for d in get_deposits_from_db():
        # Normalize legacy rows with malformed dates (e.g., "20260423;1")
        d["date"] = _normalize_flex_date(d["date"])
        # Dedupe identical transfers recorded twice (e.g., entered manually
        # AND synced from Flex with a different remark)
        direction = (d.get("direction") or "IN").upper()
        key = (d["date"], d.get("currency", "NZD"), round(abs(d["amount"]), 2), direction)
        if key in seen:
            continue
        seen.add(key)

        base_amt = d.get("amount_base") or 0
        if not base_amt:
            base_amt = abs(d["amount"]) * fx_rate_for(d.get("currency", "NZD"))
        f = flows.setdefault(d["date"], {"in": 0.0, "out": 0.0})
        if direction == "OUT":
            f["out"] += base_amt
        else:
            f["in"] += base_amt
    return flows


# ── Benchmark Data (IBKR first, FMP fallback) ────────────────

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
    """Fetch daily data for all benchmarks. Tries IBKR first, falls back to FMP."""
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    for bm_key, bm_cfg in BENCHMARKS.items():
        klines = []
        # Try IBKR first
        if USE_LIVE_API and ibkr_client and ibkr_client._connected:
            print(f"📈 Fetching {bm_key} from IBKR...")
            try:
                klines = ibkr_client.get_history_kline(
                    code=bm_cfg["ibkr"],
                    start_date=start_date,
                    end_date=end_date,
                    exchange_override=bm_cfg.get("exchange"),
                )
                if klines:
                    print(f"✅ Got {len(klines)} {bm_key} data points from IBKR")
            except Exception as e:
                print(f"⚠️  IBKR {bm_key} fetch failed: {e}")

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


# ── TWR / MWR Calculation (PortfolioAnalyst methodology) ─────

def calculate_twr(snapshots_list, flows_by_date):
    """
    Time-Weighted Return series, matching IBKR PortfolioAnalyst:

      - Daily valuation points (NAV in base currency).
      - External flows only (deposits/withdrawals) — dividends, interest and
        fees are performance, not flows.
      - IBKR convention: deposits are weighted at the START of the day
        (added to the denominator), withdrawals at the END of the day
        (added back to the numerator).
      - Daily returns are geometrically linked.

      r_day = (EV + withdrawals) / (BV + deposits) - 1

    flows_by_date: {date: {"in": deposits_nzd, "out": withdrawals_nzd}}
    Returns list of {date, twr_cumulative, twr_factor, portfolio_value, portfolio_indexed}.
    """
    if not snapshots_list:
        return []

    sorted_snaps = sorted(snapshots_list, key=lambda s: s["date"])
    sorted_flow_dates = sorted(flows_by_date.keys())

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

        # All flows in (prev_date, curr_date] belong to this sub-period
        # (handles weekend/missing-day flows by rolling them forward)
        flow_in, flow_out = 0.0, 0.0
        for fd in sorted_flow_dates:
            if prev_snap["date"] < fd <= snap["date"]:
                flow_in += flows_by_date[fd]["in"]
                flow_out += flows_by_date[fd]["out"]
            elif fd > snap["date"]:
                break

        denominator = prev_value + flow_in
        if denominator > 0:
            sub_return = (curr_value + flow_out) / denominator - 1
        else:
            sub_return = 0

        cumulative_factor *= (1 + sub_return)

        twr_series.append({
            "date": snap["date"],
            "twr_cumulative": round((cumulative_factor - 1) * 100, 4),
            "twr_factor": round(cumulative_factor, 6),
            "portfolio_value": snap["total_nav"],
            "portfolio_indexed": round(100 * cumulative_factor, 2),
        })

    return twr_series


def calculate_mwr(snapshots_list, flows_by_date):
    """
    Money-Weighted Return (IRR), the second return metric PortfolioAnalyst
    reports. Solves the rate where NPV of all flows = 0:
      - t0: -starting NAV
      - each flow date: -deposits + withdrawals
      - end: +ending NAV
    Returns {"period_pct", "annualized_pct"} or None.
    """
    if not snapshots_list or len(snapshots_list) < 2:
        return None

    sorted_snaps = sorted(snapshots_list, key=lambda s: s["date"])
    start = sorted_snaps[0]
    end = sorted_snaps[-1]
    d0 = datetime.strptime(start["date"], "%Y-%m-%d").date()
    d1 = datetime.strptime(end["date"], "%Y-%m-%d").date()
    total_days = (d1 - d0).days
    if total_days <= 0:
        return None

    # Build dated cash flows (years from start, amount)
    cashflows = [(0.0, -start["total_nav"])]
    for fd in sorted(flows_by_date.keys()):
        if start["date"] < fd <= end["date"]:
            f = flows_by_date[fd]
            net = -f["in"] + f["out"]
            if net != 0:
                t = (datetime.strptime(fd, "%Y-%m-%d").date() - d0).days / 365.25
                cashflows.append((t, net))
    t_end = total_days / 365.25
    cashflows.append((t_end, end["total_nav"]))

    def npv(rate):
        return sum(cf / (1 + rate) ** t for t, cf in cashflows)

    # Bisection on the annualized rate; expand the upper bracket as needed
    # (short periods with gains imply huge annualized IRRs)
    lo, hi = -0.999999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    while f_lo * f_hi > 0 and hi < 1e9:
        hi *= 100
        f_hi = npv(hi)
    if f_lo * f_hi > 0:
        return None  # no sign change — IRR not solvable
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-8:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    rate = (lo + hi) / 2

    period = (1 + rate) ** t_end - 1
    return {
        # PortfolioAnalyst convention: only annualize periods longer than a year
        "annualized_pct": round(rate * 100, 2) if total_days > 365 else None,
        "period_pct": round(period * 100, 2),
    }


def calculate_period_returns(twr_series):
    """Calculate period returns (1W, 1M, 3M, 6M, 1Y, YTD, All) from TWR series."""
    if not twr_series or len(twr_series) < 2:
        return {}

    latest = twr_series[-1]

    def get_factor_at_date(target_date):
        # PortfolioAnalyst convention: a period's base is the last valuation
        # BEFORE the period starts (prior close), so the first day's return
        # is included in the period.
        prior = None
        for t in twr_series:
            if t["date"] < target_date:
                prior = t
            else:
                break
        return (prior or twr_series[0])["twr_factor"]

    def period_return(days_ago=None, target_date=None):
        if target_date:
            ref = target_date
        elif days_ago:
            ref = (date.today() - timedelta(days=days_ago)).isoformat()
        else:
            return 0
        ref_factor = get_factor_at_date(ref)
        if ref_factor <= 0:
            return 0
        return round((latest["twr_factor"] / ref_factor - 1) * 100, 2)

    # YTD = from Jan 1 of current year
    ytd_start = f"{date.today().year}-01-01"

    return {
        "1W": period_return(days_ago=7),
        "1M": period_return(days_ago=30),
        "3M": period_return(days_ago=90),
        "6M": period_return(days_ago=180),
        "1Y": period_return(days_ago=365),
        "YTD": period_return(target_date=ytd_start),
        "All": round((latest["twr_factor"] - 1) * 100, 2),
    }


# ── Pydantic Models ───────────────────────────────────────────

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

class DepositEntry(BaseModel):
    date: str
    amount: float
    currency: str = "NZD"
    remark: str = "Manual deposit"
    direction: str = "IN"


# ── App ────────────────────────────────────────────────────────

async def auto_snapshot_task():
    """Sync deposits + take a snapshot every 24 hours automatically."""
    while True:
        await asyncio.sleep(60)  # Wait 1 min after startup
        while True:
            try:
                # Always sync deposits FIRST (so TWR can strip them out)
                try:
                    scan_and_store_deposits()
                    print(f"🔄 Auto deposit sync at {datetime.now().strftime('%H:%M')}")
                except Exception as e:
                    print(f"⚠️ Auto deposit sync failed: {e}")

                # Check if we already snapshotted today
                db = get_db()
                today = datetime.now().strftime("%Y-%m-%d")
                existing = db.execute(
                    "SELECT id FROM snapshots WHERE timestamp LIKE ?", (f"{today}%",)
                ).fetchone()
                db.close()

                if not existing:
                    take_snapshot()
                    print(f"📸 Auto-snapshot taken at {datetime.now().isoformat()}")
            except Exception as e:
                print(f"⚠️ Auto-snapshot failed: {e}")

            await asyncio.sleep(3600)  # Check every hour

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Connect to IBKR
    if USE_LIVE_API and ibkr_client:
        try:
            ibkr_client.connect()
            print("🚀 IBKR connection established")
        except ConnectionError as e:
            print(f"⚠️  IBKR connection failed: {e}")
            print("   Running in fallback mode — live data unavailable")
    # Background: scan deposits via Flex + fetch benchmark
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
    All weights and NAV calculated in NZD.
    Each position includes native currency values AND NZD equivalents.
    """
    rates = get_fx_rates()

    # Fetch positions + funds
    if USE_LIVE_API and ibkr_client and ibkr_client._connected:
        try:
            positions = ibkr_client.get_positions()
            funds = ibkr_client.get_account_funds()
            cash_plus = funds.get("my_cash", 0)
        except Exception as e:
            print(f"⚠️  Live position fetch failed: {e}")
            positions = []
            cash_plus = 0
    else:
        positions = DEMO_POSITIONS.copy()
        cash_plus = DEMO_FUND_ASSETS

    # Add currency info and NZD conversion to each position (multi-currency)
    for p in positions:
        currency = p.get("api_currency", p.get("currency", "NZD"))
        multiplier = fx_rate_for(currency)
        p["currency"] = currency
        p["fx_rate"] = round(multiplier, 6)
        p["val_nzd"] = round(p["val"] * multiplier, 2)
        p["pl_val_nzd"] = round(p["pl_val"] * multiplier, 2)
        p["unrealized_pl_nzd"] = round(p.get("unrealized_pl", 0) * multiplier, 2)
        p["realized_pl_nzd"] = round(p.get("realized_pl", 0) * multiplier, 2)
        p["cost_total_nzd"] = round(p["cost_price"] * p["qty"] * multiplier, 2)

    # Split active (qty > 0) and closed (qty == 0) positions
    active_positions = [p for p in positions if p["qty"] > 0]
    closed_positions = [p for p in positions if p["qty"] == 0 and p.get("realized_pl", 0) != 0]

    # Persist realized P&L to SQLite (survives after positions are closed)
    db = get_db()
    for p in positions:
        realized = p.get("realized_pl", 0)
        if realized != 0:
            db.execute(
                """INSERT OR REPLACE INTO realized_pnl
                   (ticker, stock_name, currency, total_realized, total_realized_nzd, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (p["code"], p.get("stock_name", ""), p.get("currency", "NZD"),
                 realized, p.get("realized_pl_nzd", 0), datetime.now().isoformat()),
            )
    db.commit()

    # Load ALL stored realized P&L (includes fully closed positions like Nebius)
    stored_realized = [
        dict(r) for r in db.execute("SELECT * FROM realized_pnl ORDER BY total_realized_nzd DESC").fetchall()
    ]

    # Calculate NAV in NZD (active positions only)
    equity_nav = sum(p["val_nzd"] for p in active_positions)
    total_nav = equity_nav + cash_plus

    # Load target weights from DB
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

    # Enrich positions — weights based on NZD values
    enriched = []
    for p in active_positions:
        ticker = p["code"]
        weight_pct = (p["val_nzd"] / total_nav * 100) if total_nav > 0 else 0
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

    # Daily P&L total (in NZD) — account-level reqPnL when live
    today_pl_total = 0
    if USE_LIVE_API and ibkr_client and ibkr_client._connected:
        try:
            today_pl_total = ibkr_client.get_daily_pnl()["daily_pnl"]
        except Exception as e:
            print(f"⚠️  Daily PnL fetch failed: {e}")
    if not today_pl_total:
        today_pl_total = sum(
            p.get("today_pl", 0) * p.get("fx_rate", 1.0)
            for p in active_positions
        )

    # Total realized P&L from stored records (all-time, includes closed positions)
    total_realized_nzd = sum(r.get("total_realized_nzd", 0) for r in stored_realized)

    # Build FX summary for currencies in portfolio
    active_currencies = set(p["currency"] for p in active_positions)
    fx_summary = {c: round(fx_rate_for(c), 6) for c in active_currencies if c != "NZD"}

    return {
        "positions": enriched,
        "closed_positions": closed_positions,
        "stored_realized": stored_realized,
        "cash_plus": round(cash_plus, 2),
        "cash_plus_pct": round((cash_plus / total_nav * 100) if total_nav > 0 else 0, 2),
        "equity_nav": round(equity_nav, 2),
        "total_nav": round(total_nav, 2),
        "today_pl_total": round(today_pl_total, 2),
        "total_realized_nzd": round(total_realized_nzd, 2),
        "fx_rates": fx_summary,
        "settings": settings,
        "timestamp": datetime.now().isoformat(),
        "is_live": USE_LIVE_API and ibkr_client is not None and ibkr_client._connected,
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


# ── Deal / Order History (from IBKR) ──────────────────────────

@app.get("/api/deals")
def get_deal_history(days: int = Query(default=90, ge=1, le=365)):
    """
    Get executed deal history from IBKR.
    NOTE: Only current session fills are available via the TWS API.
    For full history, import from IBKR Flex Queries.
    """
    if not USE_LIVE_API or not ibkr_client or not ibkr_client._connected:
        return {"deals": [], "message": "Not in live mode"}
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    deals = ibkr_client.get_deal_history(start_date, end_date)
    # Enrich with currency + NZD values
    for d in deals:
        currency = d.get("currency", "USD")
        if not currency or currency == "":
            currency = "USD" if d["code"].startswith("US.") else "NZD"
        d["currency"] = currency
        multiplier = fx_rate_for(currency)
        d["total_value"] = round(d["qty"] * d["price"], 2)
        d["total_value_nzd"] = round(d["total_value"] * multiplier, 2)
    # Sort newest first
    deals.sort(key=lambda x: x.get("create_time", ""), reverse=True)
    return {"deals": deals, "count": len(deals)}


@app.get("/api/orders")
def get_order_history(days: int = Query(default=90, ge=1, le=365)):
    """
    Get order history from IBKR.
    NOTE: Only recent completed orders (~24h) are available via TWS API.
    """
    if not USE_LIVE_API or not ibkr_client or not ibkr_client._connected:
        return {"orders": [], "message": "Not in live mode"}
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    orders = ibkr_client.get_order_history(start_date, end_date)
    for o in orders:
        currency = o.get("currency", "USD")
        if not currency or currency == "":
            currency = "USD" if o["code"].startswith("US.") else "NZD"
        o["currency"] = currency
        multiplier = fx_rate_for(currency)
        o["total_value"] = round(o["dealt_qty"] * o["dealt_avg_price"], 2) if o["dealt_avg_price"] else 0
        o["total_value_nzd"] = round(o["total_value"] * multiplier, 2)
    orders.sort(key=lambda x: x.get("create_time", ""), reverse=True)
    return {"orders": orders, "count": len(orders)}


# ── Account / Orders / P&L (live IBKR) ────────────────────────

def _require_live():
    if not USE_LIVE_API or not ibkr_client or not ibkr_client._connected:
        raise HTTPException(status_code=503, detail="Not connected to IBKR")


@app.get("/api/account/summary")
def get_account_summary():
    """
    Full account metrics: net liquidation, equity with loan, buying power,
    available funds, excess liquidity, margin requirements, cushion, SMA,
    leverage, accrued cash/dividends — plus per-currency balances.
    """
    _require_live()
    data = ibkr_client.get_account_summary_full()
    summary = data["summary"]
    nlv = summary.get("NetLiquidation", 0)
    gross = summary.get("GrossPositionValue", 0)
    return {
        **data,
        "leverage": round(gross / nlv, 3) if nlv else 0,
        "base_currency": "NZD",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/orders/open")
def get_open_orders():
    """All live/open orders (incl. orders placed in TWS or the mobile app)."""
    _require_live()
    orders = ibkr_client.get_open_orders()
    for o in orders:
        multiplier = fx_rate_for(o["currency"])
        o["order_value"] = round(o["qty"] * (o["limit_price"] or o["avg_fill_price"]), 2)
        o["order_value_nzd"] = round(o["order_value"] * multiplier, 2)
    return {"orders": orders, "count": len(orders)}


@app.get("/api/pnl/today")
def get_today_pnl():
    """Account-level daily P&L (same numbers as the TWS account header)."""
    _require_live()
    try:
        return {**ibkr_client.get_daily_pnl(), "timestamp": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PnL subscription failed: {e}")


# ── Cash Transactions / Income (from Flex) ────────────────────

@app.get("/api/cash-transactions")
def get_cash_transactions(days: int = Query(default=365, ge=1, le=3650),
                          type: Optional[str] = Query(default=None)):
    """
    All cash movements from IBKR: dividends, withholding tax, broker
    interest, fees, deposits/withdrawals. Optional type filter (substring).
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    db = get_db()
    if type:
        rows = db.execute(
            "SELECT * FROM cash_transactions WHERE date >= ? AND type LIKE ? ORDER BY date DESC",
            (cutoff, f"%{type}%"),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM cash_transactions WHERE date >= ? ORDER BY date DESC", (cutoff,)
        ).fetchall()
    db.close()
    records = [dict(r) for r in rows]
    by_type = {}
    for r in records:
        by_type[r["type"]] = round(by_type.get(r["type"], 0) + r["amount_base"], 2)
    return {"transactions": records, "count": len(records), "totals_by_type_nzd": by_type}


@app.get("/api/income/summary")
def get_income_summary(days: int = Query(default=365, ge=1, le=3650)):
    """
    Investment income summary: dividends (gross & net of withholding tax),
    interest, and fees — by symbol and by month, in NZD.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM cash_transactions WHERE date >= ? ORDER BY date", (cutoff,)
    ).fetchall()
    db.close()

    dividends, tax, interest, fees = 0.0, 0.0, 0.0, 0.0
    by_symbol, by_month = {}, {}
    for r in rows:
        t, amt = r["type"], r["amount_base"]
        month = r["date"][:7]
        if "Dividend" in t:
            dividends += amt
            sym = r["symbol"] or "?"
            by_symbol[sym] = round(by_symbol.get(sym, 0) + amt, 2)
            m = by_month.setdefault(month, {"dividends": 0.0, "interest": 0.0})
            m["dividends"] = round(m["dividends"] + amt, 2)
        elif "Withholding Tax" in t:
            tax += amt
        elif "Interest" in t:
            interest += amt
            m = by_month.setdefault(month, {"dividends": 0.0, "interest": 0.0})
            m["interest"] = round(m["interest"] + amt, 2)
        elif "Fee" in t or "Commission Adjustment" in t:
            fees += amt

    return {
        "gross_dividends_nzd": round(dividends, 2),
        "withholding_tax_nzd": round(tax, 2),
        "net_dividends_nzd": round(dividends + tax, 2),  # tax amounts are negative
        "interest_nzd": round(interest, 2),
        "fees_nzd": round(fees, 2),
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda x: -x[1])),
        "by_month": dict(sorted(by_month.items())),
    }


@app.get("/api/nav-history")
def get_nav_history(days: int = Query(default=365, ge=1, le=3650)):
    """Daily NAV in base currency, as reported by IBKR (Flex Equity Summary)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    db = get_db()
    rows = db.execute(
        "SELECT * FROM nav_history WHERE date >= ? ORDER BY date", (cutoff,)
    ).fetchall()
    db.close()
    return {"nav": [dict(r) for r in rows], "count": len(rows)}


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


# ── Realized P&L ───────────────────────────────────────────────

@app.get("/api/realized-pnl")
def get_realized_pnl():
    """Get all stored realized P&L records (includes fully closed positions)."""
    db = get_db()
    rows = db.execute("SELECT * FROM realized_pnl ORDER BY total_realized_nzd DESC").fetchall()
    db.close()
    records = [dict(r) for r in rows]
    total = sum(r.get("total_realized_nzd", 0) for r in records)
    return {"records": records, "total_nzd": round(total, 2)}


@app.post("/api/realized-pnl/sync")
def sync_realized_pnl():
    """Re-fetch Flex report and re-sync realized P&L from scratch."""
    try:
        report_xml = _fetch_flex_report()
        if not report_xml:
            return {"status": "error", "message": "Could not fetch Flex report"}
        db = get_db()
        _sync_realized_from_flex(db)
        rows = db.execute("SELECT * FROM realized_pnl ORDER BY total_realized_nzd DESC").fetchall()
        db.close()
        records = [dict(r) for r in rows]
        total = sum(r.get("total_realized_nzd", 0) for r in records)
        return {"status": "ok", "records": records, "total_nzd": round(total, 2),
                "synced_at": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Health ─────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    connected = ibkr_client._connected if ibkr_client else False
    flex_token, flex_qid = _read_flex_config()
    return {
        "status": "ok",
        "mode": "live" if USE_LIVE_API else "demo",
        "ibkr_connected": connected,
        "flex_configured": bool(flex_token and flex_qid),
        "db": str(DB_PATH),
        "timestamp": datetime.now().isoformat(),
    }


# ── Deposit Endpoints ─────────────────────────────────────────

@app.get("/api/deposits")
def get_deposits():
    """Get all stored deposits/withdrawals with signed NZD totals."""
    deposits = get_deposits_from_db()
    flows = get_external_flows()
    total_in = sum(f["in"] for f in flows.values())
    total_out = sum(f["out"] for f in flows.values())
    return {
        "deposits": deposits,
        "total_deposited": round(total_in, 2),
        "total_withdrawn": round(total_out, 2),
        "net_contributions": round(total_in - total_out, 2),
    }


@app.post("/api/deposits")
def add_deposit(d: DepositEntry):
    """Manually add a deposit record (fallback if Flex Query isn't configured)."""
    amount_base = abs(d.amount) * fx_rate_for(d.currency)
    db = get_db()
    try:
        db.execute(
            """INSERT OR IGNORE INTO deposits (date, amount, currency, remark, direction, amount_base)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (d.date, abs(d.amount), d.currency, d.remark, d.direction, round(amount_base, 2)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass
    db.close()
    return {"ok": True}


@app.post("/api/deposits/scan")
def trigger_deposit_scan():
    """
    Trigger a fresh deposit sync from IBKR Flex Web Service.
    Requires ~/.ibkr_flex_token and ~/.ibkr_flex_query_id to be configured.
    """
    scan_and_store_deposits()
    deposits = get_deposits_from_db()
    return {
        "ok": True,
        "message": "Flex Query deposit sync complete",
        "deposits": deposits,
        "total": sum(d["amount"] for d in deposits),
    }


# ── Returns / TWR Endpoints ───────────────────────────────────

def _build_valuation_series(db, from_date, cutoff):
    """
    Build the daily NAV series for return calculations.

    IMPORTANT: never mix valuation sources within the series. IBKR's Flex NAV
    and local snapshots use different FX feeds, so a source switch mid-series
    shows up as a fake daily return. When IBKR NAV exists we use ONLY it.
    """
    # Exclude today: a Flex report generated intraday includes TODAY's partial
    # NAV (already containing any same-day deposit) while the deposit's cash
    # transaction record hasn't posted yet — that pairing shows up as a huge
    # fake daily return. PortfolioAnalyst likewise reports complete days only.
    today_str = date.today().isoformat()
    nav_rows = db.execute(
        "SELECT date, total FROM nav_history WHERE date >= ? AND date < ? ORDER BY date",
        (from_date, today_str),
    ).fetchall()
    snap_rows = db.execute(
        "SELECT timestamp, total_nav FROM snapshots WHERE timestamp > ? ORDER BY timestamp ASC",
        (cutoff,),
    ).fetchall()
    snap_by_date = {}
    for row in snap_rows:
        snap_by_date[row["timestamp"][:10]] = row["total_nav"]  # last of the day wins

    if nav_rows:
        # Use IBKR's NAV only, ending at IBKR's last reported day — exactly
        # like PortfolioAnalyst, which also lags to the last complete day.
        # No live tail point: NAV updates instantly on a deposit but the
        # Flex flow record lags a day, so a same-day deposit would show up
        # as a huge fake return.
        series = [{"date": r["date"], "total_nav": r["total"]} for r in nav_rows]
        return series, "flex_nav"

    series = [{"date": d, "total_nav": v} for d, v in sorted(snap_by_date.items())]
    return series, "snapshots"


@app.get("/api/returns")
def get_returns(days: int = Query(default=365, ge=1, le=3650)):
    """
    Get time-weighted returns series with multiple benchmark overlays.
    Prefers IBKR Client Portal TWR data when available (accurate).
    Falls back to snapshot-based TWR calculation.
    """
    today_str = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    db = get_db()

    # ── Try IBKR TWR first (PortfolioAnalyst data via Client Portal API),
    #    but only if it's FRESH — stale partial syncs must not win over Flex ──
    ibkr_twr_available = False
    try:
        ibkr_rows = db.execute(
            "SELECT date, daily_pct, cumulative_pct FROM ibkr_twr WHERE date >= ? ORDER BY date",
            (from_date,)
        ).fetchall()
        if ibkr_rows and len(ibkr_rows) > 3:
            freshness_cutoff = (date.today() - timedelta(days=7)).isoformat()
            ibkr_twr_available = ibkr_rows[-1]["date"] >= freshness_cutoff
    except Exception:
        ibkr_rows = []

    flows = get_external_flows()
    mwr = None
    valuation_series, twr_source = _build_valuation_series(db, from_date, cutoff)

    if ibkr_twr_available:
        # Use IBKR's real TWR data (Client Portal /pa/performance)
        nav_lookup = {s["date"]: s["total_nav"] for s in valuation_series}
        twr_series = []
        for r in ibkr_rows:
            cum_pct = r["cumulative_pct"]
            factor = 1 + cum_pct / 100
            twr_series.append({
                "date": r["date"],
                "twr_cumulative": cum_pct,
                "twr_factor": factor,
                "portfolio_value": nav_lookup.get(r["date"], 0),
                "portfolio_indexed": round(100 * factor, 2),
            })
        twr_source = "ibkr"
    else:
        twr_series = calculate_twr(valuation_series, flows)

    # Money-weighted return (PortfolioAnalyst's second metric)
    if len(valuation_series) >= 2:
        mwr = calculate_mwr(valuation_series, flows)

    db.close()

    # Get deposits for display
    deposits = get_deposits_from_db()

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
            "value": round(t.get("portfolio_value", 0), 2),
        }
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

    # Signed, NZD-converted contribution totals
    total_in = sum(f["in"] for f in flows.values())
    total_out = sum(f["out"] for f in flows.values())

    return {
        "series": merged,
        "period_returns": period_returns,
        "mwr": mwr,
        "twr_source": twr_source,
        "total_deposits": round(total_in, 2),
        "total_withdrawals": round(total_out, 2),
        "net_contributions": round(total_in - total_out, 2),
        "deposit_count": len(deposits),
        "snapshot_count": len(twr_series),
        "benchmarks": {
            bk: {"label": cfg["label"], "color": cfg["color"]}
            for bk, cfg in BENCHMARKS.items()
        },
    }


@app.get("/api/returns/reconcile")
def reconcile_returns(days: int = Query(default=90, ge=1, le=3650)):
    """
    Day-by-day TWR audit, for lining up against IBKR PortfolioAnalyst.
    For each day: beginning NAV, ending NAV, deposits, withdrawals, the
    daily return, and cumulative return. Also flags data problems
    (flows outside the valuation range, valuation source, suspicious days).
    """
    from_date = (date.today() - timedelta(days=days)).isoformat()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    db = get_db()
    valuation_series, source = _build_valuation_series(db, from_date, cutoff)
    db.close()

    flows = get_external_flows()
    twr_series = calculate_twr(valuation_series, flows)

    rows = []
    sorted_flow_dates = sorted(flows.keys())
    for i, t in enumerate(twr_series):
        if i == 0:
            continue
        prev = twr_series[i - 1]
        f_in = f_out = 0.0
        for fd in sorted_flow_dates:
            if prev["date"] < fd <= t["date"]:
                f_in += flows[fd]["in"]
                f_out += flows[fd]["out"]
        daily_pct = round((t["twr_factor"] / prev["twr_factor"] - 1) * 100, 4)
        rows.append({
            "date": t["date"],
            "begin_nav": round(prev["portfolio_value"], 2),
            "end_nav": round(t["portfolio_value"], 2),
            "deposits": round(f_in, 2),
            "withdrawals": round(f_out, 2),
            "daily_pct": daily_pct,
            "cumulative_pct": t["twr_cumulative"],
            # Big single-day moves with no flow usually mean a data problem
            "suspicious": abs(daily_pct) > 8 and f_in == 0 and f_out == 0,
        })

    first_d = valuation_series[0]["date"] if valuation_series else None
    last_d = valuation_series[-1]["date"] if valuation_series else None
    # Flows before the first valuation are already embedded in the opening
    # NAV — harmless. Flows after the last valuation are invisible to TWR
    # until the next Flex sync delivers that day's NAV.
    flows_before_start = [
        {"date": fd, **flows[fd]} for fd in sorted_flow_dates
        if first_d and fd <= first_d
    ]
    flows_after_end = [
        {"date": fd, **flows[fd]} for fd in sorted_flow_dates
        if last_d and fd > last_d
    ]

    return {
        "source": source,
        "valuation_points": len(valuation_series),
        "first_date": first_d,
        "last_date": last_d,
        "final_twr_pct": twr_series[-1]["twr_cumulative"] if twr_series else None,
        "days": rows,
        "suspicious_days": [r for r in rows if r["suspicious"]],
        "flows_before_start": flows_before_start,
        "flows_after_end": flows_after_end,
        "note": "Compare daily_pct/cumulative_pct with PortfolioAnalyst's daily "
                "performance detail. flows_before_start are embedded in the opening "
                "NAV (harmless); flows_after_end aren't covered by NAV history yet "
                "(wait for the next Flex sync). suspicious_days are large moves with "
                "no recorded flow — usually a missing deposit record or a bad NAV "
                "point. If valuation_points is small, increase the Flex Query date "
                "period (use 'Last 365 Calendar Days').",
    }


# ── IBKR Client Portal API (Real TWR) ─────────────────────────

@app.post("/api/ibkr-twr/sync")
def sync_ibkr_twr(period: str = Query(default="3M")):
    """Pull real TWR data from IBKR Client Portal API and store it."""
    try:
        from ibkr_cpapi import IBKRPortalClient
        client = IBKRPortalClient()
        if not client.check_auth():
            raise HTTPException(status_code=503,
                detail="CP Gateway not authenticated. Open https://localhost:5000 and log in.")
        ok = client.sync_twr_to_db(period=period)
        if not ok:
            raise HTTPException(status_code=500, detail="No TWR data returned")
        return {"ok": True, "period": period}
    except ImportError:
        raise HTTPException(status_code=500, detail="ibkr_cpapi.py not found in backend directory")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ibkr-twr")
def get_ibkr_twr(days: int = Query(default=90)):
    """Get stored IBKR TWR data (pulled via Client Portal API)."""
    db = get_db()
    try:
        db.execute("SELECT 1 FROM ibkr_twr LIMIT 1")
    except Exception:
        db.close()
        return {"available": False, "message": "No IBKR TWR data yet. Run POST /api/ibkr-twr/sync first."}

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT * FROM ibkr_twr WHERE date >= ? ORDER BY date", (cutoff,)
    ).fetchall()
    db.close()

    if not rows:
        return {"available": False, "series": []}

    return {
        "available": True,
        "series": [dict(r) for r in rows],
        "latest_date": rows[-1]["date"],
        "latest_twr": rows[-1]["cumulative_pct"],
        "count": len(rows),
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


# ── Report Generation ─────────────────────────────────────────

class ReportRequest(BaseModel):
    month: str                    # "2026-05"
    commentary: str = ""
    fund_name: str = ""
    manager_name: str = ""
    manager_email: str = ""
    manager_title: str = ""

@app.post("/api/report/generate")
def generate_report_endpoint(req: ReportRequest):
    """Generate a monthly factsheet (.docx)."""
    try:
        from report_generator import generate_report

        path = generate_report(
            month_str=req.month,
            commentary=req.commentary,
            config_overrides=None,
        )
        return {"ok": True, "path": path, "month": req.month}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


@app.get("/api/report/download/{filename}")
def download_report(filename: str):
    """Download a generated report."""
    from fastapi.responses import FileResponse
    reports_dir = Path(__file__).parent / "reports"
    path = reports_dir / filename
    if not path.exists() or path.suffix not in (".docx", ".pdf"):
        raise HTTPException(status_code=404, detail="Report not found")
    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if path.suffix == ".docx" else "application/pdf"
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/reports")
def list_reports():
    """List all generated reports."""
    reports_dir = Path(__file__).parent / "reports"
    if not reports_dir.exists():
        return {"reports": []}
    files = sorted([f for f in reports_dir.iterdir() if f.suffix in (".docx", ".pdf")], reverse=True)
    return {
        "reports": [
            {"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1),
             "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
            for f in files
        ]
    }
