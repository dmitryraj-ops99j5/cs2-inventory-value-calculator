import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CACHE_DIR = Path.home() / ".cache" / "cs2_value"
CACHE_DB = CACHE_DIR / "prices.db"
MARKET_URL = "https://steamcommunity.com/market/priceoverview/"

class MarketCache:
    def __init__(self, refresh: bool = False):
        self._conn = None
        self._hit_count = 0
        self._miss_count = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if refresh:
            self._clear_all()

    def _init_db(self):
        self._conn = sqlite3.connect(CACHE_DB, timeout=10)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                name TEXT PRIMARY KEY,
                price REAL,
                updated INTEGER
            )"""
        )
        self._conn.commit()

    def _clear_all(self):
        self._conn.execute("DELETE FROM prices")
        self._conn.commit()

    def get_price(self, name: str) -> float | None:
        row = self._conn.execute(
            "SELECT price, updated FROM prices WHERE name = ?", (name,)
        ).fetchone()
        if row:
            price, updated = row
            if time.time() - updated < 86400:
                self._hit_count += 1
                return price
        self._miss_count += 1
        return self._fetch_price(name)

    def _fetch_price(self, name: str) -> float | None:
        encoded = quote(name, safe="")
        url = f"{MARKET_URL}?appid=730&currency=1&market_hash_name={encoded}"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError):
            return None

        lowest = data.get("lowest_price")
        if lowest and isinstance(lowest, str) and lowest.startswith("$"):
            try:
                price = float(lowest[1:].replace(",", ""))
            except ValueError:
                return None
        elif data.get("median_price"):
            median = data["median_price"]
            if isinstance(median, str) and median.startswith("$"):
                try:
                    price = float(median[1:].replace(",", ""))
                except ValueError:
                    return None
            else:
                return None
        else:
            # some items only have volume_price from bulk listings
            volume = data.get("volume_price")
            if volume and isinstance(volume, str) and volume.startswith("$"):
                try:
                    price = float(volume[1:].replace(",", ""))
                except ValueError:
                    return None
            else:
                return None

        self._conn.execute(
            "INSERT OR REPLACE INTO prices (name, price, updated) VALUES (?, ?, ?)",
            (name, price, int(time.time())),
        )
        self._conn.commit()
        return price
