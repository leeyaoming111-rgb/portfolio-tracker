# LeeHong Capital — Portfolio Tracker

FastAPI + React dashboard for managing an active equity portfolio via Interactive Brokers. NZD base currency.

## Returns methodology (matches IBKR PortfolioAnalyst)

`/api/returns` reports **Time-Weighted Return (TWR)** using the same methodology
as IBKR PortfolioAnalyst:

- Valued daily against IBKR's official base-currency NAV series (synced from the
  Flex "Equity Summary in Base" section), falling back to local snapshots.
- Only external flows (deposits/withdrawals) are stripped out — dividends,
  interest and fees count as performance.
- Withdrawals are signed correctly, and flows are converted to NZD using IBKR's
  own `fxRateToBase` rate from the day of the transfer.
- IBKR's day-weighting convention: deposits at start of day, withdrawals at end
  of day; daily returns are geometrically linked.
- **MWR** (money-weighted return / IRR) is also reported, annualized only for
  periods over one year — same as PortfolioAnalyst.

Source priority: IBKR Client Portal `/pa/performance` TWR → Flex daily NAV → local snapshots.

## Flex Query setup (one-time)

In IBKR Client Portal → Performance & Reports → Flex Queries, create an
Activity Flex Query with these sections (all fields):

1. **Cash Transactions** — deposits/withdrawals, dividends, interest, fees
2. **Equity Summary in Base** (by report date) — daily NAV for exact TWR
3. **Trades** — realized P&L

Period: "Last 365 Calendar Days". Then save the Web Service token to
`~/.ibkr_flex_token` and the query ID to `~/.ibkr_flex_query_id`. Everything
syncs on startup and daily; re-trigger with `POST /api/deposits/scan`.

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/portfolio` | Positions, NAV, weights, drift, live daily P&L |
| `GET /api/returns` | TWR + MWR series with benchmark overlays, net contributions |
| `GET /api/account/summary` | Margin, buying power, excess liquidity, leverage, per-currency balances |
| `GET /api/orders/open` | Live open orders (incl. TWS/mobile-placed) |
| `GET /api/pnl/today` | Account-level daily realized/unrealized P&L |
| `GET /api/cash-transactions` | All cash movements (dividends, tax, interest, fees) |
| `GET /api/income/summary` | Dividend/interest income by symbol and month (NZD) |
| `GET /api/nav-history` | IBKR's official daily NAV in base currency |
| `GET /api/deposits` | Deposits/withdrawals with signed NZD totals |
| `POST /api/deposits/scan` | Re-sync everything from the Flex Web Service |
| `GET /api/rebalance` | Trim/deploy actions vs target weights |

## Run

```bash
# Backend (requires IB Gateway/TWS running, API enabled, port 4001)
cd backend && uvicorn server:app --port 8000

# Frontend
cd frontend && npm run dev
```
