"""
backfill_nav.py — Pull daily NAV history from IBKR Flex Query and populate snapshots.

One-time setup:
  1. In IBKR Client Portal → Performance & Reports → Flex Queries
  2. Create (or edit) an Activity Flex Query
  3. Add the "Change in NAV" section — select all fields
  4. Set period to "Last 60 Calendar Days"
  5. Save — note the Query ID
  6. Save the query ID: echo "YOUR_QUERY_ID" > ~/.ibkr_flex_nav_query_id
     (Reuse the same token from ~/.ibkr_flex_token)

  OR if you already have a Flex Query, just add "Change in NAV" to it
  and reuse the same query ID in ~/.ibkr_flex_query_id

Usage:
  python backfill_nav.py
"""

import json, os, sqlite3, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "portfolio.db")
FLEX_TOKEN_FILE = os.path.expanduser("~/.ibkr_flex_token")
FLEX_NAV_QID_FILE = os.path.expanduser("~/.ibkr_flex_nav_query_id")
FLEX_QID_FILE = os.path.expanduser("~/.ibkr_flex_query_id")  # fallback to deposits query
FLEX_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


def read_config():
    token = open(FLEX_TOKEN_FILE).read().strip() if os.path.exists(FLEX_TOKEN_FILE) else None
    # Try nav-specific query first, fall back to general query
    qid = None
    if os.path.exists(FLEX_NAV_QID_FILE):
        qid = open(FLEX_NAV_QID_FILE).read().strip()
    elif os.path.exists(FLEX_QID_FILE):
        qid = open(FLEX_QID_FILE).read().strip()
        print(f"ℹ️  Using deposits query ID ({qid}). For best results, add 'Change in NAV' to this query.")
    return token, qid


def fetch_flex_report(token, query_id):
    """Two-step Flex Web Service fetch."""
    headers = {"User-Agent": "Python/3.12"}

    # Step 1: Request
    print("📋 Requesting Flex report...")
    url = f"{FLEX_URL}/SendRequest?t={token}&q={query_id}&v=3"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as resp:
        xml_text = resp.read().decode()

    root = ET.fromstring(xml_text)
    if root.findtext("Status") != "Success":
        print(f"❌ Request failed: {root.findtext('ErrorMessage')}")
        return None

    ref = root.findtext("ReferenceCode")
    print(f"   Reference: {ref}")

    # Step 2: Fetch (with retry)
    for attempt in range(6):
        time.sleep(3 + attempt * 2)
        print(f"   Fetching (attempt {attempt + 1}/6)...")
        url2 = f"{FLEX_URL}/GetStatement?t={token}&q={ref}&v=3"
        try:
            with urllib.request.urlopen(urllib.request.Request(url2, headers=headers), timeout=30) as resp:
                report = resp.read().decode()
            if "<FlexQueryResponse" in report or "<FlexStatements" in report:
                return report
            if "1019" in report:  # Still generating
                continue
        except Exception as e:
            print(f"   Error: {e}")

    print("❌ Could not retrieve report after 6 attempts")
    return None


def parse_nav_data(xml_text):
    """Parse Change in NAV or account info from Flex report."""
    root = ET.fromstring(xml_text)
    nav_records = []

    # Try "ChangeInNAV" section first
    for stmt in root.iter("FlexStatement"):
        for nav in stmt.iter("ChangeInNAV"):
            record = {
                "date": nav.get("fromDate", nav.get("reportDate", "")),
                "end_nav": float(nav.get("endingValue", 0)),
                "start_nav": float(nav.get("startingValue", 0)),
                "deposits": float(nav.get("depositsWithdrawals", nav.get("deposits", 0))),
            }
            # Normalize date
            d = record["date"]
            if len(d) == 8 and "-" not in d:
                record["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if record["end_nav"] > 0:
                nav_records.append(record)

    if nav_records:
        print(f"✅ Found {len(nav_records)} daily NAV records from Change in NAV")
        return nav_records

    # Fallback: try "EquitySummaryInBase" or "EquitySummaryByReportDateInBase"
    for stmt in root.iter("FlexStatement"):
        for eq in stmt.iter("EquitySummaryByReportDateInBase"):
            d = eq.get("reportDate", "")
            if len(d) == 8 and "-" not in d:
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            total = float(eq.get("total", 0))
            if total > 0:
                nav_records.append({"date": d, "end_nav": total, "start_nav": 0, "deposits": 0})

    if nav_records:
        print(f"✅ Found {len(nav_records)} daily NAV records from Equity Summary")
        return nav_records

    # Last resort: try to get from AccountInformation
    for stmt in root.iter("FlexStatement"):
        # Check statement-level attributes
        d = stmt.get("toDate", stmt.get("whenGenerated", ""))[:10]
        nav = float(stmt.get("netLiquidation", 0) or 0)
        if nav > 0:
            if len(d) == 8 and "-" not in d:
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            nav_records.append({"date": d, "end_nav": nav, "start_nav": 0, "deposits": 0})

    if nav_records:
        print(f"✅ Found {len(nav_records)} NAV records from statement attributes")
    else:
        print("⚠️  No NAV data found in report. Make sure your Flex Query includes 'Change in NAV'.")
        # Debug: print what sections ARE in the report
        sections = set()
        for elem in root.iter():
            sections.add(elem.tag)
        print(f"   Available sections: {', '.join(sorted(sections)[:20])}")

    return nav_records


def backfill_snapshots(nav_records):
    """Insert NAV records into snapshots table, skipping duplicates."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check existing snapshot dates
    existing = set(
        row[0][:10] for row in c.execute("SELECT timestamp FROM snapshots").fetchall()
    )

    inserted = 0
    for rec in sorted(nav_records, key=lambda r: r["date"]):
        d = rec["date"]
        if d in existing:
            continue
        nav = rec["end_nav"]
        # Estimate equity vs cash split (assume 93% equity, 7% cash if unknown)
        c.execute(
            """INSERT INTO snapshots (timestamp, total_nav, equity_nav, cash_plus, positions_json, weights_json)
               VALUES (?, ?, ?, ?, '[]', '{}')""",
            (f"{d}T16:00:00", nav, round(nav * 0.93, 2), round(nav * 0.07, 2)),
        )
        inserted += 1
        print(f"   {d}  NAV = {nav:>12,.2f}")

    conn.commit()
    conn.close()
    print(f"\n✅ Inserted {inserted} new snapshots ({len(existing)} already existed)")


def main():
    token, qid = read_config()
    if not token:
        print("❌ No Flex token found at ~/.ibkr_flex_token")
        return
    if not qid:
        print("❌ No query ID found. Save it:")
        print("   echo 'YOUR_QUERY_ID' > ~/.ibkr_flex_nav_query_id")
        return

    report = fetch_flex_report(token, qid)
    if not report:
        return

    records = parse_nav_data(report)
    if not records:
        return

    backfill_snapshots(records)
    print("\n📊 You can now generate your report:")
    print("   python report_generator.py --month 2026-05 --commentary '...'")


if __name__ == "__main__":
    main()
