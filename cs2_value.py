import argparse
import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from market_cache import MarketCache

STEAM_API_URL = "https://steamcommunity.com/inventory/{steamid}/730/2?l=english&count=5000"

def fetch_inventory(steamid: str, api_key: str | None = None) -> dict:
    url = STEAM_API_URL.format(steamid=steamid)
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"rate limited, retrying in {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print("rate limited by steam, try again later", file=sys.stderr)
            elif e.code == 403:
                print("inventory is private or steam blocked the request", file=sys.stderr)
            else:
                print(f"steam returned {e.code}", file=sys.stderr)
            sys.exit(1)
        except URLError as e:
            print(f"network error: {e.reason}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError:
            print("steam returned invalid json", file=sys.stderr)
            sys.exit(1)
    # unreachable but satisfies type checker
    sys.exit(1)

def _extract_wear(name: str) -> str | None:
    if "(Factory New)" in name:
        return "FN"
    if "(Minimal Wear)" in name:
        return "MW"
    if "(Field-Tested)" in name:
        return "FT"
    if "(Well-Worn)" in name:
        return "WW"
    if "(Battle-Scarred)" in name:
        return "BS"
    return None

def parse_inventory(data: dict) -> list[dict]:
    assets = data.get("assets", [])
    descriptions = data.get("descriptions", [])
    desc_map = {}
    for d in descriptions:
        key = (d.get("classid"), d.get("instanceid"))
        desc_map[key] = d

    items = []
    for asset in assets:
        key = (asset.get("classid"), asset.get("instanceid"))
        desc = desc_map.get(key, {})
        name = desc.get("market_hash_name") or desc.get("name", "Unknown")
        items.append({
            "name": name,
            "tradable": desc.get("tradable", 0) == 1,
            "marketable": desc.get("marketable", 0) == 1,
            "wear": _extract_wear(name),
        })
    return items

def calculate_value(items: list[dict], cache: MarketCache) -> tuple[float, dict]:
    total = 0.0
    priced = {}
    for item in items:
        if not item["marketable"]:
            continue
        price = cache.get_price(item["name"])
        if price:
            total += price
            priced[item["name"]] = price
    return total, priced

def main() -> int:
    parser = argparse.ArgumentParser(
        description="fetch and price a cs2 player's inventory",
        usage="python cs2_value.py <steamid> [--api-key KEY] [--refresh-cache] [--top N]",
    )
    parser.add_argument("steamid", help="steam64 id of the player")
    parser.add_argument("--api-key", default=os.environ.get("STEAM_API_KEY"),
                        help="steam web api key (optional, env fallback)")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="force refresh of market price cache")
    parser.add_argument("--top", type=int, default=10, metavar="N",
                        help="show top N most valuable items (default 10)")
    args = parser.parse_args()

    if not args.steamid.isdigit() or len(args.steamid) != 17:
        print("steamid must be a 17-digit steam64 id", file=sys.stderr)
        return 2

    cache = MarketCache(refresh=args.refresh_cache)
    print(f"fetching inventory for {args.steamid}...")
    data = fetch_inventory(args.steamid, args.api_key)
    items = parse_inventory(data)
    print(f"found {len(items)} items, {sum(1 for i in items if i['marketable'])} marketable")

    total, priced = calculate_value(items, cache)
    print(f"\ntotal estimated value: ${total:.2f} USD")
    if priced:
        print(f"\ntop {args.top} items by value:")
        for name, price in sorted(priced.items(), key=lambda x: -x[1])[:args.top]:
            print(f"  {name}: ${price:.2f}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit(130)
