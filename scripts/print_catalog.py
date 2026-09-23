#!/usr/bin/env python3
"""
Print the frozen Spike catalog exactly as the contract compiles it.

The catalog lives in contracts/Spike.py as module-level constants. There is no
function anywhere in the contract that can add, remove or rename an asset, so
what this prints is what the deployment will settle on, forever.

    python scripts/print_catalog.py
    python scripts/print_catalog.py --urls --day 2026-09-22 --hour 14
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent.parent / "contracts" / "Spike.py"


def load_constants() -> dict:
    """
    Read the constants straight out of the contract source.

    Parsed rather than imported, because importing contracts/Spike.py needs the
    GenVM runtime. This keeps the script runnable with plain Python.
    """
    tree = ast.parse(CONTRACT.read_text(encoding="utf-8"))
    out: dict = {}

    def value(node):
        """Literals, plus the arithmetic and name references the catalog uses."""
        if isinstance(node, ast.Name):
            if node.id in out:
                return out[node.id]
            raise ValueError(node.id)
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Pow):
                return left**right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            raise ValueError("unsupported operator")
        return ast.literal_eval(node)

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    out[target.id] = value(node.value)
                except (ValueError, SyntaxError, TypeError):
                    pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", action="store_true", help="also print URL templates")
    ap.add_argument("--day", default="2026-09-22")
    ap.add_argument("--hour", type=int, default=14)
    args = ap.parse_args()

    c = load_constants()
    scale = c["PRICE_SCALE"]

    print("\nSpike catalog - frozen at compile time in contracts/Spike.py")
    print("=" * 70)

    print("\nCRYPTO   (two independent intraday sources, so hourly markets exist)")
    print(f"  source A: {c['SRC_GATE']}      source B: {c['SRC_BINANCE']}")
    print(f"  {'asset':<8}{'gate.io pair':<16}{'binance symbol':<16}")
    for a in c["CRYPTO_ASSETS"]:
        print(f"  {a:<8}{c['GATE_PAIR'][a]:<16}{c['BINANCE_SYMBOL'][a]:<16}")

    print("\nCOMMODITIES  (daily session only - no second keyless intraday feed)")
    print(f"  source A: {c['SRC_YAHOO']}       source B: {c['SRC_NASDAQ']}")
    print(f"  {'asset':<8}{'proxy':<8}{'label shown in the UI':<28}")
    for a in c["COMMODITY_ASSETS"]:
        print(f"  {a:<8}{c['COMMODITY_PROXY'][a]:<8}{c['COMMODITY_LABEL'][a]:<28}")

    print("\nWindow selector")
    print("  CRYPTO       KIND_DIRECTION   whole GMT+1 day        hour = -1")
    print("  CRYPTO       KIND_DOMINANCE   exact GMT+1 hour       hour = 0..23")
    print("  COMMODITIES  KIND_DIRECTION   US session on the day  hour = -1")
    print("  COMMODITIES  KIND_DOMINANCE   US session on the day  hour = -1")

    print("\nLimits")
    print(f"  stake              {c['MIN_STAKE_WEI'] // 10**18}-{c['MAX_STAKE_WEI'] // 10**18} GEN")
    print(f"  max forward days   {c['MAX_FORWARD_DAYS']}")
    print(f"  terminal refund    {c['TERMINAL_REFUND_DELAY_SECS'] // 86400} days after the window closes")
    print(f"  price scale        1e{len(str(scale)) - 1} (integers only, no floats in settlement)")
    print(f"  timezone           fixed GMT+1 (UTC+{c['GMT1_OFFSET'] // 3600:02d}:00), never DST")
    print("  page size          %d" % c["PAGE_LIMIT"])

    print("\nVerdict vocabulary")
    vocab = ["UP", "DOWN", "TIE", "MISSING"]
    vocab += ["WIN:" + a for a in c["CRYPTO_ASSETS"] + c["COMMODITY_ASSETS"]]
    print("  " + " | ".join(vocab))
    print("  final = INCONCLUSIVE unless both sources returned the same real verdict")

    if args.urls:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from probe_feeds import window_utc  # noqa: E402

        d0, d1 = window_utc(args.day, None)
        h0, h1 = window_utc(args.day, args.hour)
        print(f"\nURL templates  (day {args.day}, hour {args.hour:02d}:00 GMT+1)")
        print("-" * 70)
        a = c["CRYPTO_ASSETS"][0]
        print(f"  gate.io   https://api.gateio.ws/api/v4/spot/candlesticks"
              f"?currency_pair={c['GATE_PAIR'][a]}&interval=1h&from={h0}&to={h1 - 1}")
        print(f"  binance   https://data-api.binance.vision/api/v3/klines"
              f"?symbol={c['BINANCE_SYMBOL'][a]}&interval=1h"
              f"&startTime={h0 * 1000}&endTime={h1 * 1000 - 1}&limit=1000")
        g = c["COMMODITY_PROXY"]["GOLD"]
        print(f"  yahoo     https://query1.finance.yahoo.com/v8/finance/chart/{g}"
              f"?interval=1d&period1={d0 - 86400 * 5}&period2={d1 + 86400}")
        print(f"  nasdaq    https://api.nasdaq.com/api/quote/{g}/historical"
              f"?assetclass=etf&fromdate=...&todate=...&limit=20")
        print("\n  Both commodity hosts require a browser User-Agent header.")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
