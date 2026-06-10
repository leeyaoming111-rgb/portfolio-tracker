# Moomoo API Research — Malaysia Live Account on macOS

## TL;DR Recommendation

**Use the local OpenD desktop gateway** with the `moomoo-api` Python SDK.
There is no standalone cloud REST API — OpenD is the only integration path.

---

## Option Comparison

| Criterion | OpenD (Local Gateway) | Cloud API |
|---|---|---|
| **What it is** | Desktop app (macOS native) that runs locally, exposes a TCP interface on `127.0.0.1:11111` | Does not exist as a separate product — OpenD can be deployed on a cloud server, but it's the same software |
| **Real-time data** | Yes — subscribe to quotes, tick-by-tick, order book via TCP push | Same (OpenD on cloud) |
| **Auth setup** | Login with moomoo ID + password in OpenD GUI; unlock trade with a 6-digit trading password | Same |
| **Rate limits** | 30 req/s for most endpoints; 10 subscriptions per security; max 128 connections | Same |
| **macOS support** | Native .app — download from moomoo.com/download/OpenAPI | Yes |
| **Dev experience** | `pip install moomoo-api` → connect to localhost — very simple | Same SDK, just point to remote host |

**Verdict**: OpenD on your Mac is the right choice. It's the only gateway to Moomoo's servers.
Running it locally avoids SSL/networking complexity and gives you the lowest latency.

---

## Critical Malaysia-Specific Finding

### SecurityFirm Enum Gap

The `SecurityFirm` enum in the current API (v9.6) only lists:

- `FUTUSECURITIES` — Futu HK
- `FUTUINC` — Moomoo US
- `FUTUSG` — Moomoo SG
- `FUTUAU` — Moomoo AU

**Malaysia (`MOOMOOFINMY`) is NOT in the enum.**

However:
- The `Currency` enum includes `MYR` (Malaysian Ringgit) — value 8
- Moomoo Malaysia launched in Feb 2024 with universal accounts
- The `TrdMarket` enum includes `MY` in newer SDK versions

### What This Means for You

When you log into OpenD with your Malaysia moomoo ID, OpenD will authenticate
against Moomoo Malaysia's servers. The SDK should auto-detect your security firm.
You have two approaches:

1. **Try `SecurityFirm.NONE` or omit** — let OpenD auto-detect
2. **Use `security_firm=SecurityFirm.MOOMOOFINMY`** — if your SDK version 
   includes it (v9.4+)

If neither works, you can list accounts first without specifying a firm,
then use the returned `acc_id` directly for all subsequent calls.

### Cash Plus (Money Market Fund)

Cash Plus is Moomoo's in-app money market product. It is **NOT** exposed as a
standard position via `position_list_query()`. Instead:

- `accinfo_query()` returns `fund_assets` — this is your Cash Plus balance
- For universal accounts, this field shows total fund assets
- Alternatively, Cash Plus may appear in `position_list_query()` as a fund
  position with a special code prefix

**Strategy**: Query both `accinfo_query()` for fund_assets AND 
`position_list_query()` and check for any fund-type holdings.

### Market Codes

Malaysian stocks on Bursa use the prefix `MY.` (e.g., `MY.1155` for Maybank).
US stocks use `US.` prefix. HK stocks use `HK.` prefix.

---

## Setup Instructions

### 1. Install OpenD

```bash
# Download from: https://www.moomoo.com/download/OpenAPI
# Choose: moomoo OpenD for macOS
# Install the .dmg like any Mac app
```

### 2. Configure OpenD

Launch OpenD → Login with your moomoo Malaysia ID and password.
First-time login requires a questionnaire. After login:

- API Port: 11111 (default)
- Listening Address: 127.0.0.1
- Enable trading: Yes
- Set your 6-digit trading unlock password

### 3. Install Python SDK

```bash
pip install moomoo-api
```

### 4. Test Connection

See `backend/test_connection.py` for a minimal working script.

---

## Rate Limits & Quotas

- Quote subscriptions: 100 simultaneous (more than enough for <20 positions)
- Request frequency: 30/s for quote, 15/s for trade
- Connection limit: 128 per OpenD instance
- Historical data: 60 requests per 30 seconds
- Market hours polling at 30s intervals is well within limits
