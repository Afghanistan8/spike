#!/usr/bin/env python3
"""
Record real feed responses into tests/fixtures/.

Unit tests must never touch the live web, but they should be parsing bytes that
a real source actually produced. This script captures those bytes once; the
tests replay them forever.

    python scripts/record_fixtures.py --day 2026-09-22 --hour 14
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from probe_feeds import (  # noqa: E402
    COMMODITIES,
    CRYPTO,
    fetch,
    window_utc,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures")


def save(name: str, status: int, body: bytes) -> None:
    path = os.path.join(OUT, name)
    if status != 200:
        print(f"  SKIP {name} (HTTP {status})")
        return
    with open(path, "wb") as f:
        f.write(body)
    print(f"  wrote {name}  ({len(body)} bytes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-09-22")
    ap.add_argument("--hour", type=int, default=14)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    d0, d1 = window_utc(args.day, None)
    h0, h1 = window_utc(args.day, args.hour)

    print(f"Recording fixtures for {args.day} (day) and {args.hour:02d}:00 (hour)")

    print("\ncrypto - daily window")
    for asset, ids in CRYPTO.items():
        s, b = fetch(
            f"https://data-api.binance.vision/api/v3/klines?symbol={ids['binance']}"
            f"&interval=1h&startTime={d0 * 1000}&endTime={d1 * 1000 - 1}&limit=1000"
        )
        save(f"binance_{asset}_day_{args.day}.json", s, b)
        s, b = fetch(
            f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={ids['gate']}"
            f"&interval=1h&from={d0}&to={d1 - 1}"
        )
        save(f"gate_{asset}_day_{args.day}.json", s, b)

    print("\ncrypto - hourly window")
    for asset, ids in CRYPTO.items():
        s, b = fetch(
            f"https://data-api.binance.vision/api/v3/klines?symbol={ids['binance']}"
            f"&interval=1h&startTime={h0 * 1000}&endTime={h1 * 1000 - 1}&limit=1000"
        )
        save(f"binance_{asset}_hour_{args.day}_{args.hour:02d}.json", s, b)
        s, b = fetch(
            f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={ids['gate']}"
            f"&interval=1h&from={h0}&to={h1 - 1}"
        )
        save(f"gate_{asset}_hour_{args.day}_{args.hour:02d}.json", s, b)

    print("\ncommodities - daily session")
    for asset, ids in COMMODITIES.items():
        sym = ids["nasdaq_etf"]
        s, b = fetch(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
            f"?interval=1d&period1={d0 - 86400 * 5}&period2={d1 + 86400}"
        )
        save(f"yahoo_{asset}_day_{args.day}.json", s, b)
        s, b = fetch(
            f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=etf"
            f"&fromdate=2026-09-15&todate=2026-09-23&limit=20"
        )
        save(f"nasdaq_{asset}_day_{args.day}.json", s, b)

    meta = {
        "day": args.day,
        "hour": args.hour,
        "day_window_utc": [d0, d1],
        "hour_window_utc": [h0, h1],
    }
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    print("\n  wrote meta.json")


if __name__ == "__main__":
    sys.exit(main())
