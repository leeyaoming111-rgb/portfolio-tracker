"""
ibkr_cpapi.py — IBKR Client Portal API integration

Pulls real TWR, daily returns, and NAV data directly from IBKR's
PortfolioAnalyst system via the Client Portal Gateway REST API.

Setup:
  1. Download Client Portal Gateway from IBKR:
     https://www.interactivebrokers.com/en/trading/ib-api.php
     → "Client Portal API" → Download for macOS

  2. Unzip to ~/ibkr-cpgateway/

  3. Start the gateway:
     cd ~/ibkr-cpgateway && java -jar bin/run.jar root/conf.yaml

  4. Open browser → https://localhost:5000 → log in with IBKR credentials

  5. The gateway stays active for ~24 hours (resets at midnight NY time).
     Our backend auto-pings to keep the session alive.

Usage:
  from ibkr_cpapi import IBKRPortalClient
  client = IBKRPortalClient()
  perf = client.get_performance(period="1M", freq="D")
  print(perf["twr"])  # daily TWR returns
"""

import json
import os
import sqlite3
import time
import urllib.request
import ssl
from datetime import datetime, date, timedelta
from pathlib import Path

# CP Gateway runs on localhost with self-signed SSL cert
CP_BASE_URL = os.environ.get("IBKR_CP_URL", "https://localhost:5000/v1/api")
DB_PATH = Path(__file__).parent / "portfolio.db"

# Disable SSL verification for localhost self-signed cert
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


class IBKRPortalClient:
    """Client for IBKR's Client Portal REST API."""

    def __init__(self, base_url=CP_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.account_id = None
        self._last_ping = 0

    def _request(self, method, path, data=None, timeout=15):
        """Make an authenticated request to the CP Gateway."""
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json", "User-Agent": "PortfolioTracker/1.0"}

        if data is not None:
            body = json.dumps(data).encode()
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
        else:
            req = urllib.request.Request(url, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            print(f"⚠️  CP API {method} {path} → {e.code}: {body[:200]}")
            return None
        except Exception as e:
            print(f"⚠️  CP API error: {e}")
            return None

    # ── Authentication ─────────────────────────────────────────

    def check_auth(self):
        """Check if the CP Gateway session is authenticated."""
        result = self._request("GET", "/iserver/auth/status")
        if result and result.get("authenticated"):
            print("✅ CP Gateway authenticated")
            return True
        print("⚠️  CP Gateway not authenticated — open https://localhost:5000 and log in")
        return False

    def ping(self):
        """Keep the session alive (must be called every ~5 minutes)."""
        now = time.time()
        if now - self._last_ping < 240:  # Don't ping more than every 4 min
            return
        self._request("POST", "/tickle")
        self._last_ping = now

    def get_accounts(self):
        """Get list of account IDs."""
        result = self._request("GET", "/portfolio/accounts")
        if result and isinstance(result, list):
            self.account_id = result[0].get("accountId")
            return [a.get("accountId") for a in result]
        return []

    # ── Performance (TWR) ──────────────────────────────────────

    def get_performance(self, period="1M", freq="D", account_id=None):
        """
        Get portfolio performance from PortfolioAnalyst.

        Args:
            period: "7D", "1M", "3M", "6M", "1Y", "MTD", "YTD"
            freq: "D" (daily), "M" (monthly), "Q" (quarterly)
            account_id: IBKR account ID (auto-detected if not provided)

        Returns dict with:
            twr: list of {date, return_pct, cumulative_pct}
            nav: list of {date, value}
            benchmarks: dict of benchmark returns
        """
        self.ping()
        if not account_id:
            if not self.account_id:
                self.get_accounts()
            account_id = self.account_id

        if not account_id:
            print("⚠️  No account ID available")
            return None

        result = self._request("POST", "/pa/performance", data={
            "acctIds": [account_id],
            "freq": freq,
        })

        if not result:
            return None

        # Parse the response
        try:
            return self._parse_performance(result, account_id)
        except Exception as e:
            print(f"⚠️  Error parsing performance data: {e}")
            # Return raw for debugging
            return {"raw": result}

    def _parse_performance(self, data, account_id):
        """Parse IBKR's /pa/performance response into clean daily returns."""
        # IBKR returns performance data in nested arrays
        # The exact structure varies, so we handle multiple formats
        twr_data = []
        nav_data = []

        # Try to find the account's data in the response
        if isinstance(data, dict):
            # Look for cumulative returns data
            for key in ["currencyType", "cps", data.get("id", "")]:
                if key in data:
                    pass

            # Handle the nested structure
            perf = data
            if "twr" in perf:
                # Direct TWR data
                twr_raw = perf["twr"]
                if isinstance(twr_raw, dict):
                    dates = twr_raw.get("dates", [])
                    returns = twr_raw.get("returns", {}).get(account_id, [])
                    for i, d in enumerate(dates):
                        if i < len(returns):
                            twr_data.append({
                                "date": self._parse_ibkr_date(d),
                                "cumulative_pct": returns[i],
                            })

            if "nav" in perf:
                nav_raw = perf["nav"]
                if isinstance(nav_raw, dict):
                    dates = nav_raw.get("dates", [])
                    values = nav_raw.get("data", {}).get(account_id, [])
                    for i, d in enumerate(dates):
                        if i < len(values):
                            nav_data.append({
                                "date": self._parse_ibkr_date(d),
                                "value": values[i],
                            })

            # Try alternative format (array-based)
            if not twr_data and isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "dates" in item:
                        dates = item["dates"]
                        returns_arr = item.get("returns", [])
                        for i, d in enumerate(dates):
                            if i < len(returns_arr):
                                twr_data.append({
                                    "date": self._parse_ibkr_date(d),
                                    "cumulative_pct": returns_arr[i],
                                })

        # Compute daily returns from cumulative
        for i in range(1, len(twr_data)):
            prev = 1 + twr_data[i - 1]["cumulative_pct"] / 100
            curr = 1 + twr_data[i]["cumulative_pct"] / 100
            twr_data[i]["daily_pct"] = round((curr / prev - 1) * 100, 4) if prev > 0 else 0
        if twr_data:
            twr_data[0]["daily_pct"] = 0

        return {
            "twr": twr_data,
            "nav": nav_data,
            "account_id": account_id,
            "raw": data,  # Include raw for debugging
        }

    def _parse_ibkr_date(self, d):
        """Parse IBKR date format (could be timestamp or string)."""
        if isinstance(d, (int, float)):
            # Unix timestamp in milliseconds
            return datetime.fromtimestamp(d / 1000).strftime("%Y-%m-%d")
        if isinstance(d, str):
            # Try various formats
            for fmt in ["%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"]:
                try:
                    return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return str(d)[:10]

    # ── Summary ────────────────────────────────────────────────

    def get_summary(self, account_id=None):
        """Get performance summary (MTD, QTD, YTD, ITD returns)."""
        self.ping()
        if not account_id:
            if not self.account_id:
                self.get_accounts()
            account_id = self.account_id

        result = self._request("POST", "/pa/summary", data={
            "acctIds": [account_id],
        })
        return result

    # ── Store to DB ────────────────────────────────────────────

    def sync_twr_to_db(self, period="3M"):
        """Pull TWR from IBKR and store in snapshot-compatible format."""
        perf = self.get_performance(period=period, freq="D")
        if not perf or not perf.get("twr"):
            print("⚠️  No TWR data returned from CP API")
            if perf and perf.get("raw"):
                print(f"   Raw response keys: {list(perf['raw'].keys()) if isinstance(perf['raw'], dict) else type(perf['raw'])}")
            return False

        twr = perf["twr"]
        nav = {n["date"]: n["value"] for n in perf.get("nav", [])}

        conn = sqlite3.connect(DB_PATH)

        # Store in a dedicated table for IBKR TWR data
        conn.execute("""CREATE TABLE IF NOT EXISTS ibkr_twr (
            date TEXT PRIMARY KEY,
            daily_pct REAL,
            cumulative_pct REAL,
            nav REAL,
            source TEXT DEFAULT 'cpapi',
            synced_at TEXT
        )""")

        count = 0
        for t in twr:
            d = t["date"]
            conn.execute(
                """INSERT OR REPLACE INTO ibkr_twr
                   (date, daily_pct, cumulative_pct, nav, source, synced_at)
                   VALUES (?, ?, ?, ?, 'cpapi', datetime('now'))""",
                (d, t.get("daily_pct", 0), t.get("cumulative_pct", 0), nav.get(d, 0)),
            )
            count += 1

        conn.commit()
        conn.close()
        print(f"✅ Synced {count} daily TWR records from IBKR")
        if twr:
            latest = twr[-1]
            print(f"   Latest: {latest['date']} → {latest['cumulative_pct']:.2f}% cumulative")
        return True


# ── CLI ────────────────────────────────────────────────────────

def main():
    """CLI tool to pull TWR from IBKR Client Portal API."""
    import argparse
    p = argparse.ArgumentParser(description="Pull TWR from IBKR Client Portal API")
    p.add_argument("--period", default="3M", help="Period: 7D, 1M, 3M, 6M, 1Y, MTD, YTD")
    p.add_argument("--check", action="store_true", help="Just check auth status")
    p.add_argument("--sync", action="store_true", help="Sync TWR data to SQLite")
    p.add_argument("--raw", action="store_true", help="Print raw API response")
    args = p.parse_args()

    client = IBKRPortalClient()

    if args.check:
        client.check_auth()
        accounts = client.get_accounts()
        print(f"   Accounts: {accounts}")
        return

    if not client.check_auth():
        print("\n📋 Setup instructions:")
        print("  1. Start CP Gateway: cd ~/ibkr-cpgateway && java -jar bin/run.jar root/conf.yaml")
        print("  2. Open https://localhost:5000 in your browser")
        print("  3. Log in with your IBKR credentials")
        print("  4. Run this script again")
        return

    if args.sync:
        client.sync_twr_to_db(period=args.period)
        return

    perf = client.get_performance(period=args.period)
    if not perf:
        return

    if args.raw:
        print(json.dumps(perf.get("raw", {}), indent=2))
        return

    # Print daily returns
    print(f"\nDaily TWR returns ({args.period}):")
    print(f"{'Date':12s}  {'Daily':>8s}  {'Cumulative':>10s}")
    for t in perf.get("twr", []):
        print(f"  {t['date']}  {t.get('daily_pct', 0):>+7.2f}%  {t.get('cumulative_pct', 0):>+9.2f}%")

    # Print summary
    summary = client.get_summary()
    if summary:
        print(f"\nSummary: {json.dumps(summary, indent=2)[:500]}")


if __name__ == "__main__":
    main()
