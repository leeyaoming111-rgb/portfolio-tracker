"""
test_connection.py — Find your Malaysia real account

Tries every SecurityFirm and TrdMarket combination to locate
your real trading account.
"""

from moomoo import *

OPEND_HOST = "127.0.0.1"
OPEND_PORT = 11111

print("🐄 Moomoo Malaysia Account Finder")
print("=" * 60)

# ── Step 1: Check what SecurityFirm values exist in your SDK ──
print("\n1. CHECKING SDK VERSION")
print("-" * 40)
print(f"   Available SecurityFirm values:")
for name in dir(SecurityFirm):
    if not name.startswith("_"):
        try:
            val = getattr(SecurityFirm, name)
            print(f"   - SecurityFirm.{name} = {val}")
        except:
            pass

print(f"\n   Available TrdMarket values:")
for name in dir(TrdMarket):
    if not name.startswith("_"):
        try:
            val = getattr(TrdMarket, name)
            print(f"   - TrdMarket.{name} = {val}")
        except:
            pass

# ── Step 2: Try each SecurityFirm ──
print("\n2. TRYING EACH SECURITY FIRM")
print("-" * 40)

firms_to_try = []
for name in dir(SecurityFirm):
    if not name.startswith("_") and name != "NONE":
        try:
            val = getattr(SecurityFirm, name)
            firms_to_try.append((name, val))
        except:
            pass

# Also try NONE
firms_to_try.insert(0, ("NONE", SecurityFirm.NONE))

for firm_name, firm_val in firms_to_try:
    try:
        ctx = OpenSecTradeContext(
            host=OPEND_HOST,
            port=OPEND_PORT,
            security_firm=firm_val,
        )
        ret, data = ctx.get_acc_list()
        if ret == RET_OK and len(data) > 0:
            real_accounts = data[data["trd_env"] == "REAL"]
            sim_accounts = data[data["trd_env"] == "SIMULATE"]
            print(f"\n   SecurityFirm.{firm_name}:")
            print(f"   -> Found {len(real_accounts)} REAL + {len(sim_accounts)} SIMULATE accounts")
            if len(real_accounts) > 0:
                print(f"   ✅ REAL ACCOUNT FOUND!")
                print(data.to_string(index=True))
        else:
            print(f"   SecurityFirm.{firm_name}: {data if ret != RET_OK else 'No accounts'}")
        ctx.close()
    except Exception as e:
        print(f"   SecurityFirm.{firm_name}: Error -- {e}")
        try:
            ctx.close()
        except:
            pass

# ── Step 3: Try with different TrdMarket filters ──
print("\n\n3. TRYING DIFFERENT MARKET FILTERS")
print("-" * 40)

markets_to_try = []
for name in dir(TrdMarket):
    if not name.startswith("_"):
        try:
            val = getattr(TrdMarket, name)
            markets_to_try.append((name, val))
        except:
            pass

for mkt_name, mkt_val in markets_to_try:
    try:
        ctx = OpenSecTradeContext(
            filter_trdmarket=mkt_val,
            host=OPEND_HOST,
            port=OPEND_PORT,
        )
        ret, data = ctx.get_acc_list()
        if ret == RET_OK and len(data) > 0:
            real_accounts = data[data["trd_env"] == "REAL"]
            if len(real_accounts) > 0:
                print(f"\n   TrdMarket.{mkt_name}:")
                print(f"   ✅ REAL ACCOUNT FOUND!")
                print(data.to_string(index=True))
        ctx.close()
    except Exception as e:
        try:
            ctx.close()
        except:
            pass

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
print("\nIf no REAL account was found:")
print("1. Open the OpenD app and check you're logged in with your REAL account")
print("   (not paper trading mode)")
print("2. Check that your Malaysia account has been fully approved")
print("3. In OpenD settings, make sure 'Enable Trading' is checked")
print("4. Try logging out of OpenD and logging back in")
