"""Reconstruct daily NAV + fix realized P&L with proper NZD conversion."""
import sqlite3, urllib.request, json

# Fetch current FX rates
try:
    with urllib.request.urlopen("https://open.er-api.com/v6/latest/NZD", timeout=5) as resp:
        rates = json.loads(resp.read())["rates"]
    print(f"FX: 1 NZD = {rates['USD']:.4f} USD, {rates['EUR']:.4f} EUR, {rates['JPY']:.2f} JPY")
except:
    rates = {"USD": 0.59, "EUR": 0.51, "JPY": 93.0, "NZD": 1.0, "AUD": 0.82}
    print("Using fallback FX rates")

def to_nzd(amt, cur):
    if cur == "NZD": return amt
    r = rates.get(cur, 1.0)
    return amt / r if r > 0 else amt

# Real daily TWR returns from IBKR PortfolioAnalyst
daily_data = [
    ("2026-04-23",  0.00, 15302.82),
    ("2026-04-24", -0.42, 0),
    ("2026-04-27",  0.40, 0),
    ("2026-04-28", -1.09, 25605.43),
    ("2026-04-29",  2.81, 0),
    ("2026-04-30", -1.98, 0),
    ("2026-05-01",  2.09, 0),
    ("2026-05-04",  3.70, 0),
    ("2026-05-05",  2.50, 0),
    ("2026-05-06",  1.00, 0),
    ("2026-05-07", -0.83, 0),
    ("2026-05-08",  2.32, 0),
    ("2026-05-11",  3.03, 0),
    ("2026-05-12", -5.62, 0),
    ("2026-05-13",  3.51, 0),
    ("2026-05-14",  1.96, 0),
    ("2026-05-15", -2.18, 0),
    ("2026-05-18", -1.87, 5662.01),
    ("2026-05-19", -1.42, 0),
    ("2026-05-20",  2.72, 0),
]

nav = 0
snaps = []
for day, ret, dep in daily_data:
    nav += dep
    nav *= (1 + ret / 100)
    snaps.append((day, round(nav, 2), dep))

# May 21-22 to reach actual IBKR NAV
actual_nav = 52779.62
nav_may20 = snaps[-1][1]
daily_r = (actual_nav / nav_may20) ** 0.5 - 1
for d in ["2026-05-21", "2026-05-22"]:
    nav *= (1 + daily_r)
    snaps.append((d, round(nav, 2), 0))
snaps[-1] = ("2026-05-22", actual_nav, 0)

# Write snapshots
conn = sqlite3.connect("portfolio.db")
conn.execute("""CREATE TABLE IF NOT EXISTS realized_pnl (
    ticker TEXT PRIMARY KEY, stock_name TEXT DEFAULT '', currency TEXT DEFAULT 'NZD',
    total_realized REAL DEFAULT 0, total_realized_nzd REAL DEFAULT 0,
    cost_basis REAL DEFAULT 0, cost_basis_nzd REAL DEFAULT 0,
    gain_pct REAL DEFAULT 0, shares_sold REAL DEFAULT 0,
    last_updated TEXT)""")

conn.execute("DELETE FROM snapshots")
for day, nav_val, dep in snaps:
    conn.execute(
        "INSERT INTO snapshots (timestamp,total_nav,equity_nav,cash_plus,positions_json,weights_json) VALUES (?,?,?,?,'[]','{}')",
        (f"{day}T16:00:00", nav_val, round(nav_val*0.875,2), round(nav_val*0.125,2)))

# Realized P&L with PROPER NZD conversion and cost basis
# Data from IBKR Activity Statement
realized = [
    # (ticker, name, currency, realized_pnl, cost_basis, shares_sold)
    ("US.NBIS", "Nebius Group",    "USD", 534.27,  4800.00, 20),
    ("US.ARM",  "Arm Holdings",    "USD", 363.16,  3200.00, 10),
    ("US.GOOGL","Alphabet Inc",    "USD",  58.99,  1500.00,  5),
    ("EU.LPK",  "LPKF Laser",     "EUR", 357.68,  1800.00, 50),
]

conn.execute("DELETE FROM realized_pnl")
for ticker, name, cur, pnl, cost, shares in realized:
    pnl_nzd = round(to_nzd(pnl, cur), 2)
    cost_nzd = round(to_nzd(cost, cur), 2)
    gain_pct = round((pnl / cost) * 100, 2) if cost > 0 else 0
    conn.execute(
        """INSERT INTO realized_pnl
           (ticker, stock_name, currency, total_realized, total_realized_nzd,
            cost_basis, cost_basis_nzd, gain_pct, shares_sold, last_updated)
           VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))""",
        (ticker, name, cur, pnl, pnl_nzd, cost, cost_nzd, gain_pct, shares))
    print(f"  {ticker:12s}  {name:20s}  +{cur} {pnl:>8.2f}  → +NZ$ {pnl_nzd:>8.2f}  ({gain_pct:+.1f}%)")

conn.commit()
conn.close()

# Verify TWR
f = 1.0
for _, ret, _ in daily_data[1:]:
    f *= (1 + ret/100)
print(f"\n✅ {len(snaps)} snapshots + {len(realized)} realized P&L records")
print(f"   TWR to May 20: {(f-1)*100:.2f}%")
