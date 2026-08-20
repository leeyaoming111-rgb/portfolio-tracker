# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend (requires IB Gateway/TWS running on port 4001)
cd backend && uvicorn server:app --port 8000 --reload

# Frontend
cd frontend && npm run dev

# Lint frontend
cd frontend && npm run lint
```

There is no test suite. The backend has no linting config; manual verification against a running server is the primary correctness check.

## Architecture

**Stack**: FastAPI backend (Python) + Vite/React frontend. Single-file design — `backend/server.py` is the entire backend (~2600 lines), `frontend/src/App.jsx` and `portfolio-dashboard.jsx` are the main frontend files.

**Database**: SQLite at `backend/portfolio.db`. Schema is created/migrated in `init_db()` at the top of `server.py`. New columns are added with `ALTER TABLE … ADD COLUMN` wrapped in a try/except to be idempotent.

**IBKR connectivity**: `IBKRClient` in `server.py` wraps `ib_async` in a dedicated background thread with its own event loop, avoiding conflicts with uvicorn's asyncio loop. `_run_coro()` bridges between the two loops via `asyncio.run_coroutine_threadsafe`. The connection is read-only. Toggle `USE_LIVE_API = True/False` at the top of `server.py` to switch between live IBKR data and hardcoded demo positions.

**Ticker format**: Internal tickers are `{CURRENCY_PREFIX}.{SYMBOL}` — e.g., `US.AAPL`, `NZ.SPK`, `JP.6315`. `CURRENCY_PREFIX` and `EXCHANGE_MAP` in `IBKRClient` define the mapping.

**Currency**: NZD is the base currency. All NAV, weights, and P&L are expressed in NZD. FX rates are fetched from `open.er-api.com` (1-hour cache). `to_nzd(value, currency)` and `fx_rate_for(currency)` are the conversion helpers.

**Data sources and priority**:
- Live positions/quotes: IBKR TWS API via `ib_async`
- Historical NAV (for TWR): IBKR Flex Web Service → local SQLite snapshots
- TWR: IBKR Client Portal API (`ibkr_cpapi.py`) → Flex daily NAV → snapshot-based calculation
- Benchmark prices: IBKR historical data → FMP API (`~/.fmp_api_key`)
- Screener discovery: Ollama (local) → Gemini (`~/.gemini_api_key`) → Perplexity (`~/.perplexity_api_key`) → Yahoo Finance → web scrape

**Flex Query** (IBKR's separate REST API for historical data): Two-step flow in `_fetch_flex_report()`. Requires `~/.ibkr_flex_token` and `~/.ibkr_flex_query_id`. Syncs deposits/withdrawals, all cash transactions (dividends, interest, fees), daily NAV, and realized P&L into SQLite. Runs automatically on startup and daily via `auto_snapshot_task()`.

**Returns methodology**: TWR matches IBKR PortfolioAnalyst conventions — deposits weighted at start of day, withdrawals at end. Only external flows (deposits/withdrawals) are stripped; dividends/interest/fees count as performance. Today's partial NAV is excluded from the series to avoid fake returns when a deposit and its Flex cash transaction record arrive on different days.

**Screener** (`screener.py`): Mounted as an `APIRouter` at prefix `/screener`. Thematic company discovery chains through LLM providers in priority order. FMP (`/stable/` API) provides financials for the batch enrichment step.

**Report generation**: `report_generator.py` generates monthly `.docx` factsheets. `report_docx.js` is a Node.js helper script used by the generator.

**Client Portal API** (`ibkr_cpapi.py`): Optional integration that pulls real TWR data from IBKR's PortfolioAnalyst via the CP Gateway (a local Java process at `https://localhost:5000`). Triggered via `POST /api/ibkr-twr/sync`.

## Key config files (all in `~/`)

| File | Purpose |
|---|---|
| `~/.ibkr_flex_token` | IBKR Flex Web Service token |
| `~/.ibkr_flex_query_id` | Flex Activity Query ID |
| `~/.fmp_api_key` | Financial Modeling Prep API key |
| `~/.gemini_api_key` | Gemini API key (also used by screener) |
| `~/.perplexity_api_key` | Perplexity API key (screener fallback) |

## Key API endpoints

See `README.md` for the full table. The most frequently touched ones are:

- `GET /api/portfolio` — main dashboard data; calls `get_portfolio()` which pulls live IBKR positions and enriches them with target weights, drift, and FX conversion
- `GET /api/returns` — TWR/MWR series with benchmark overlays; source priority is IBKR CP API → Flex NAV → snapshots
- `POST /api/deposits/scan` — re-triggers a full Flex sync
- `POST /api/ibkr-twr/sync` — pulls official TWR from Client Portal API
- `GET /api/returns/reconcile` — day-by-day TWR audit table for debugging against PortfolioAnalyst
