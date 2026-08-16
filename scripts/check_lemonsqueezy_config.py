"""
Verify the Lemon Squeezy configuration in .env against the live Lemon Squeezy account.

Run: python scripts/check_lemonsqueezy_config.py

Checks that every value is present, that the API key and store id work, and : the reason
this exists : that LEMONSQUEEZY_BUY_URL points at a LIVE variant rather than a test-mode
one. Testing requires temporarily pointing that variable at a test-mode checkout, and
forgetting to point it back would send real customers to a test checkout that takes no
money. Nothing else in the app would notice.

Never prints secrets: keys are masked to first/last four characters.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import httpx

from app import config

LS_API = "https://api.lemonsqueezy.com/v1"
EXPECTED_WEBHOOK_HOST = "www."


def _mask(value: str) -> str:
    if not value:
        return "<EMPTY>"
    if len(value) <= 8:
        return f"**** (len {len(value)})"
    return f"{value[:4]}…{value[-4:]} (len {len(value)})"


def main() -> None:
    problems = []

    try:
        ls = config.get_lemonsqueezy_config()
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print("--- .env ---")
    print(f"  api_key             {_mask(ls['api_key'])}")
    print(f"  webhook_secret      {_mask(ls['webhook_secret'])}")
    print(f"  store_id            {ls['store_id']}")
    print(f"  beta_discount_code  {ls['beta_discount_code']}")
    print(f"  buy_url             {ls['buy_url']}")

    headers = {"Authorization": f"Bearer {ls['api_key']}", "Accept": "application/vnd.api+json"}

    print("\n--- Lemon Squeezy account ---")
    resp = httpx.get(f"{LS_API}/users/me", headers=headers, timeout=20.0)
    if resp.status_code != 200:
        print(f"  FAIL: API key rejected (HTTP {resp.status_code})")
        sys.exit(1)
    me = resp.json()["data"]["attributes"]
    print(f"  authenticated as    {me.get('name')} <{me.get('email')}>")

    resp = httpx.get(f"{LS_API}/stores/{ls['store_id']}", headers=headers, timeout=20.0)
    if resp.status_code != 200:
        problems.append(f"store_id {ls['store_id']} not readable (HTTP {resp.status_code})")
    else:
        store = resp.json()["data"]["attributes"]
        print(f"  store               {store.get('name')} ({store.get('currency')}, {store.get('country')})")

    # The API key is itself mode-scoped, so whatever it can see tells you which mode you are
    # reading. The hosted buy URL embeds a checkout UUID that Lemon Squeezy does not expose on
    # the variant object, so buy_url CANNOT be matched to a variant programmatically , an
    # earlier version of this script tried and reported a false failure. It is reported for a
    # human to eyeball instead.
    print("\n--- variants (as seen by this API key) ---")
    resp = httpx.get(f"{LS_API}/variants", headers=headers, timeout=20.0)
    if resp.status_code == 200:
        variants = resp.json().get("data", [])
        if not variants:
            problems.append("this API key sees no variants at all")
        test_variants = 0
        for variant in variants:
            attrs = variant["attributes"]
            is_test = bool(attrs.get("test_mode"))
            test_variants += is_test
            price = attrs.get("price")
            pretty = f"${price / 100:.2f}" if isinstance(price, int) else str(price)
            print(f"  id={variant['id']:<10} test_mode={str(is_test):<6} price={pretty:<8} "
                  f"interval={attrs.get('interval')}")
        if variants and test_variants == len(variants):
            problems.append("every variant this key can see is TEST MODE , the API key is a "
                            "test key, so live checkout and live webhooks will not work")
    else:
        problems.append(f"could not list variants (HTTP {resp.status_code})")

    print("\n  CHECK BY EYE: buy_url must be the LIVE checkout link.")
    print("    Lemon Squeezy does not expose the hosted-checkout UUID on the variant object,")
    print("    so this cannot be verified automatically. After any test-mode run, confirm")
    print("    LEMONSQUEEZY_BUY_URL was pointed back at the live product.")

    print("\n--- webhooks ---")
    resp = httpx.get(f"{LS_API}/webhooks", headers=headers,
                     params={"filter[store_id]": ls["store_id"]}, timeout=20.0)
    if resp.status_code == 200:
        hooks = resp.json().get("data", [])
        if not hooks:
            problems.append("no webhooks registered , subscriptions will never activate")
        for hook in hooks:
            attrs = hook["attributes"]
            url = attrs.get("url", "")
            print(f"  id={hook['id']} url={url}")
            print(f"    events={len(attrs.get('events') or [])} test_mode={attrs.get('test_mode')}")
            if EXPECTED_WEBHOOK_HOST not in url:
                problems.append(
                    f"webhook {hook['id']} is not on the www host , the bare domain 301s and "
                    f"this POST-only route would receive a 405"
                )
    else:
        problems.append(f"could not list webhooks (HTTP {resp.status_code})")

    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
