#!/usr/bin/env python3
"""
One-time seed script: imports realized P&L data into the backend.
Run: python3 backend/seed_realized.py

This calls PUT /api/realized-pnl/import on the local backend.
Data was extracted from IBKR account trades (90-day window, June 2026).
"""
import json
import urllib.request

API = "http://localhost:8000/api/realized-pnl/import"

RECORDS = [
    {"ticker": "US.MU", "stock_name": "MICRON TECHNOLOGY INC", "currency": "USD", "total_realized": 701.16, "cost_basis": 875.84, "shares_sold": 1.5},
    {"ticker": "EU.LPK", "stock_name": "LPKF LASER & ELECTRONICS SE", "currency": "EUR", "total_realized": 675.49, "cost_basis": 1526.11, "shares_sold": 88.0},
    {"ticker": "US.FPS", "stock_name": "FORGENT POWER SOLUTIONS INC", "currency": "USD", "total_realized": 594.13, "cost_basis": 944.32, "shares_sold": 25.0},
    {"ticker": "US.NVTS", "stock_name": "NAVITAS SEMICONDUCTOR CORP", "currency": "USD", "total_realized": 386.28, "cost_basis": 537.17, "shares_sold": 30.0},
    {"ticker": "US.NBIS", "stock_name": "NEBIUS GROUP NV", "currency": "USD", "total_realized": 313.61, "cost_basis": 873.61, "shares_sold": 6.0},
    {"ticker": "US.DRAM", "stock_name": "ROUNDHILL MEMORY ETF", "currency": "USD", "total_realized": 225.48, "cost_basis": 382.28, "shares_sold": 8.0},
    {"ticker": "US.ARM", "stock_name": "ARM HOLDINGS PLC-ADR", "currency": "USD", "total_realized": 213.17, "cost_basis": 1002.88, "shares_sold": 5.0},
    {"ticker": "US.RDDT", "stock_name": "REDDIT INC-CL A", "currency": "USD", "total_realized": 151.53, "cost_basis": 1150.37, "shares_sold": 7.0},
    {"ticker": "US.NOW", "stock_name": "SERVICENOW INC", "currency": "USD", "total_realized": 137.68, "cost_basis": 271.1, "shares_sold": 3.0},
    {"ticker": "US.HIMS", "stock_name": "HIMS & HERS HEALTH INC", "currency": "USD", "total_realized": 77.84, "cost_basis": 957.33, "shares_sold": 35.0},
    {"ticker": "US.AAPL", "stock_name": "APPLE INC", "currency": "USD", "total_realized": 52.17, "cost_basis": 540.38, "shares_sold": 2.0},
    {"ticker": "US.GOOGL", "stock_name": "ALPHABET INC-CL A", "currency": "USD", "total_realized": 34.63, "cost_basis": 354.94, "shares_sold": 1.0},
    {"ticker": "US.SHOP", "stock_name": "SHOPIFY INC - CLASS A", "currency": "USD", "total_realized": 15.98, "cost_basis": 732.46, "shares_sold": 7.0},
    {"ticker": "US.MELI", "stock_name": "MERCADOLIBRE INC", "currency": "USD", "total_realized": 9.5, "cost_basis": 664.75, "shares_sold": 0.4},
    {"ticker": "US.JFB", "stock_name": "JFB CONSTRUCTION HOLDIN-CL A", "currency": "USD", "total_realized": 4.72, "cost_basis": 583.85, "shares_sold": 100.0},
]

if __name__ == "__main__":
    body = json.dumps(RECORDS).encode()
    req = urllib.request.Request(API, data=body, method="PUT",
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            print(f"Imported {result.get('imported', 0)} records")
            print(f"Total realized (NZD): {result.get('total_nzd', 0):,.2f}")
            print(f"Status: {result.get('status')}")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the backend is running at http://localhost:8000")
