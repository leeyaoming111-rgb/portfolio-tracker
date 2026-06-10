"""
report_generator.py — LeeHong Capital Factsheet Generator

Orchestrates data export (Python) + document creation (Node.js docx-js).
Produces a branded .docx factsheet with performance charts.

Usage:
  python report_generator.py --month 2026-05 --commentary "..."

API:
  POST /api/report/generate {"month":"2026-05","commentary":"..."}
"""

import json, math, os, sqlite3, subprocess, tempfile
from datetime import datetime, date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

DB_PATH = Path(__file__).parent / "portfolio.db"
DOCX_SCRIPT = Path(__file__).parent / "report_docx.js"


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_data(month_str):
    """Fetch all report data from SQLite."""
    year, month = int(month_str[:4]), int(month_str[5:7])
    month_start = date(year, month, 1)
    month_end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)

    db = _get_db()
    snaps = [dict(r) for r in db.execute("SELECT * FROM snapshots ORDER BY timestamp").fetchall()]
    deposits = [dict(r) for r in db.execute("SELECT * FROM deposits ORDER BY date").fetchall()]
    spy = [dict(r) for r in db.execute(
        "SELECT date, close FROM benchmark_cache WHERE ticker='SPY' ORDER BY date").fetchall()]
    db.close()

    snap_by_date = {}
    for s in snaps:
        snap_by_date[s["timestamp"][:10]] = s
    sorted_dates = sorted(snap_by_date.keys())
    if not sorted_dates:
        return None

    # TWR
    deposit_map = {}
    for d in deposits:
        deposit_map[d["date"]] = deposit_map.get(d["date"], 0) + d["amount"]

    twr = []
    cum = 1.0
    for i, d in enumerate(sorted_dates):
        snap = snap_by_date[d]
        if i == 0:
            twr.append({"date": d, "factor": 1.0, "nav": snap["total_nav"]})
            continue
        prev = snap_by_date[sorted_dates[i - 1]]["total_nav"]
        curr = snap["total_nav"]
        dep = deposit_map.get(d, 0)
        denom = prev + dep
        cum *= (curr / denom) if denom > 0 else 1
        twr.append({"date": d, "factor": cum, "nav": curr})

    spy_map = {b["date"]: b["close"] for b in spy}
    spy_dates = sorted(spy_map.keys())

    def ret_since(target):
        ref = 1.0
        for t in twr:
            if t["date"] >= target:
                ref = t["factor"]
                break
        return round((twr[-1]["factor"] / ref - 1) * 100, 2) if ref > 0 else 0

    def bm_ret(target):
        ref = None
        for bd in spy_dates:
            if bd >= target:
                ref = spy_map[bd]
                break
        if not ref and spy_dates:
            ref = spy_map[spy_dates[0]]
        latest = spy_map[spy_dates[-1]] if spy_dates else 1
        return round((latest / ref - 1) * 100, 2) if ref else 0

    q_month = ((month - 1) // 3) * 3 + 1
    positions = json.loads(snap_by_date[sorted_dates[-1]].get("positions_json", "[]"))

    # Calendar year returns
    cal_years = {}
    for yr in range(int(sorted_dates[0][:4]), year + 1):
        start_f = end_f = bm_s = bm_e = None
        for t in twr:
            if t["date"] >= f"{yr}-01-01" and start_f is None:
                start_f = t["factor"]
            if t["date"] <= f"{yr}-12-31":
                end_f = t["factor"]
        for bd in spy_dates:
            if bd >= f"{yr}-01-01" and bm_s is None:
                bm_s = spy_map[bd]
            if bd <= f"{yr}-12-31":
                bm_e = spy_map[bd]
        cal_years[str(yr)] = {
            "portfolio": round((end_f / start_f - 1) * 100, 2) if start_f and end_f else None,
            "benchmark": round((bm_e / bm_s - 1) * 100, 2) if bm_s and bm_e else None,
        }

    # Volatility
    vol = {"beta": None, "r_squared": None, "sharpe": None, "std_dev": None}
    n = len(twr) - 1
    if n >= 20:
        pr = [twr[i]["factor"] / twr[i - 1]["factor"] - 1 for i in range(1, len(twr))]
        br = [spy_map.get(twr[i]["date"], 1) / spy_map.get(twr[i - 1]["date"], 1) - 1
              if twr[i - 1]["date"] in spy_map and twr[i]["date"] in spy_map else 0
              for i in range(1, len(twr))]
        pm, bm_ = sum(pr) / n, sum(br) / n
        pv = sum((r - pm) ** 2 for r in pr) / n
        bv = sum((r - bm_) ** 2 for r in br) / n
        cv = sum((pr[i] - pm) * (br[i] - bm_) for i in range(n)) / n
        dn = (pv ** 0.5) * (bv ** 0.5)
        corr = cv / dn if dn > 0 else 0
        vol["std_dev"] = round((pv ** 0.5) * (252 ** 0.5) * 100, 2)
        vol["beta"] = round(cv / bv, 2) if bv > 0 else None
        vol["r_squared"] = round(corr ** 2, 2)
        ann = (twr[-1]["factor"] ** (252 / n)) - 1 if n > 0 else 0
        vol["sharpe"] = round((ann - 0.045) / (vol["std_dev"] / 100), 2) if vol["std_dev"] else None

    # Allocation
    us = sum(p.get("val_nzd", p.get("val", 0)) for p in positions if p["code"].startswith("US."))
    nz = sum(p.get("val_nzd", p.get("val", 0)) for p in positions if p["code"].startswith("NZ."))
    cash = snap_by_date[sorted_dates[-1]].get("cash_plus", 0)
    total = us + nz + cash

    return {
        "fund_name": "LeeHong Capital",
        "month_display": month_end.strftime("%B %Y"),
        "as_of": month_end.strftime("%d/%m/%Y"),
        "latest_nav": round(twr[-1]["nav"], 2),
        "num_holdings": len([p for p in positions if p.get("qty", 0) > 0]),
        "period_returns": {
            "MTD": ret_since(month_start.isoformat()),
            "QTD": ret_since(date(year, q_month, 1).isoformat()),
            "YTD": ret_since(date(year, 1, 1).isoformat()),
            "ITD": round((cum - 1) * 100, 2),
        },
        "bm_returns": {
            "MTD": bm_ret(month_start.isoformat()),
            "QTD": bm_ret(date(year, q_month, 1).isoformat()),
            "YTD": bm_ret(date(year, 1, 1).isoformat()),
            "ITD": bm_ret(spy_dates[0]) if spy_dates else 0,
        },
        "cal_years": cal_years,
        "positions": positions[:10],
        "allocation": {
            "US Equities": round(us / total * 100, 1) if total else 0,
            "NZ Equities": round(nz / total * 100, 1) if total else 0,
            "Cash": round(cash / total * 100, 1) if total else 0,
        },
        "volatility": vol,
        "twr": twr,
        "spy_data": spy,
    }


def _generate_charts(data, tmpdir):
    """Generate chart PNGs in tmpdir."""
    # Performance chart
    fig, ax = plt.subplots(figsize=(6.2, 2.4), dpi=180)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    dates = [datetime.strptime(t["date"], "%Y-%m-%d") for t in data["twr"]]
    vals = [t["factor"] * 10000 for t in data["twr"]]
    ax.plot(dates, vals, color="#4C1D6B", linewidth=1.8,
            label=f'LeeHong Capital: ${vals[-1]:,.0f}', zorder=3)
    if data["spy_data"]:
        bd = [datetime.strptime(b["date"], "%Y-%m-%d") for b in data["spy_data"]]
        base = data["spy_data"][0]["close"]
        bv = [b["close"] / base * 10000 for b in data["spy_data"]]
        ax.plot(bd, bv, color="#d29922", linewidth=1.2, linestyle="--",
                label=f'S&P 500: ${bv[-1]:,.0f}', alpha=0.8, zorder=2)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1000:.1f}K"))
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    ax.grid(True, alpha=0.12); ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0"); ax.spines["bottom"].set_color("#e2e8f0")
    ax.tick_params(axis="both", labelsize=6.5, colors="#6b7280")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    plt.tight_layout(pad=0.4)
    plt.savefig(os.path.join(tmpdir, "chart_perf.png"), bbox_inches="tight", facecolor="white")
    plt.close()

    # Mark
    fig, ax = plt.subplots(figsize=(0.6, 0.6), dpi=200)
    fig.patch.set_alpha(0); ax.set_facecolor("none")
    ax.set_xlim(-1.1, 1.1); ax.set_ylim(-1.1, 1.1); ax.set_aspect("equal"); ax.axis("off")
    for r, alpha in [(0.28, 1.0), (0.55, 0.5), (0.82, 0.22)]:
        ax.add_patch(plt.Circle((0, 0), r, fill=False, color="#4C1D6B", linewidth=2.5, alpha=alpha))
    ax.plot(0, 0, "o", color="#4C1D6B", markersize=5)
    plt.savefig(os.path.join(tmpdir, "mark.png"), bbox_inches="tight", transparent=True, dpi=200)
    plt.close()


def generate_report(month_str, commentary="", output_path=None, config_overrides=None):
    """Generate a .docx factsheet for the given month."""
    data = _fetch_data(month_str)
    if not data:
        raise ValueError(f"No snapshot data for {month_str}")

    data["commentary"] = commentary

    if not output_path:
        reports_dir = Path(__file__).parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        output_path = str(reports_dir / f"{month_str}_factsheet.docx")

    # Generate charts in a temp directory, then run node from there
    tmpdir = tempfile.mkdtemp()
    _generate_charts(data, tmpdir)

    # Export data JSON
    json_path = os.path.join(tmpdir, "report_data.json")
    with open(json_path, "w") as f:
        json.dump(data, f)

    # Copy the docx generator script to tmpdir
    import shutil
    docx_script = Path(__file__).parent / "report_docx.js"
    shutil.copy(docx_script, tmpdir)

    # Check for node_modules
    nm_src = Path(__file__).parent / "node_modules"
    if nm_src.exists():
        os.symlink(str(nm_src), os.path.join(tmpdir, "node_modules"))
    else:
        # Install docx in tmpdir
        subprocess.run(["npm", "install", "docx"], cwd=tmpdir, capture_output=True)

    # Run node
    abs_output = os.path.abspath(output_path)
    result = subprocess.run(
        ["node", "report_docx.js", "report_data.json", commentary, abs_output],
        cwd=tmpdir, capture_output=True, text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"docx generation failed: {result.stderr}")

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)
    return output_path


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--month", required=True)
    p.add_argument("--commentary", default="")
    p.add_argument("--output", default=None)
    args = p.parse_args()
    path = generate_report(args.month, commentary=args.commentary, output_path=args.output)
    print(f"✅ Factsheet: {path}")
