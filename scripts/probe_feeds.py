#!/usr/bin/env python3
"""
Spike - live feed probe.

Hits every candidate feed URL used (or considered) for settlement, reconstructs the
exact GMT+1 window from each source independently, and prints status + parsed
open/close so the catalog can be frozen against observed reality rather than memory.

This script is the ONLY place in the repo that touches the live network.
Unit tests use recorded fixtures under tests/fixtures/ instead.

Usage:
    python scripts/probe_feeds.py                 # yesterday's GMT+1 day + hour 14
    python scripts/probe_feeds.py --day 2026-09-22
    python scripts/probe_feeds.py --day 2026-09-22 --hour 14
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# Spike settles on a FIXED GMT+1 offset. Never DST, never browser-local time.
GMT1 = timezone(timedelta(hours=1))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpikeProbe/0.1"

# Prices are carried as integers scaled by 10^8 so settlement never touches a float.
SCALE = 10**8


def to_scaled(x) -> int:
    """Canonical price scaling: 8 decimal places, then integer."""
    return int(round(float(x) * SCALE))


def window_utc(day: str, hour):
    """
    Return (open_instant_utc, close_instant_utc) as unix seconds for a GMT+1 window.

    hour is None  -> the whole GMT+1 calendar day  [00:00, next 00:00)
    hour is 0..23 -> that exact GMT+1 hour         [HH:00, HH+1:00)
    """
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=GMT1)
    if hour is None:
        start, end = d, d + timedelta(days=1)
    else:
        start = d + timedelta(hours=hour)
        end = start + timedelta(hours=1)
    return int(start.timestamp()), int(end.timestamp())


def fetch(url: str, headers=None, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # DNS, TLS, timeout
        return 0, str(e).encode()


def show(label: str, status: int, op, cl, note: str = ""):
    if op is not None and cl is not None:
        pct = (cl - op) / op * 100 if op else 0.0
        verdict = "UP" if cl > op else "DOWN"
        print(f"  {label:<26} HTTP {status:<4} open={op:<15} close={cl:<15} {pct:+7.3f}%  {verdict}  {note}")
    else:
        print(f"  {label:<26} HTTP {status:<4} -- no window --  {note}")


# --------------------------------------------------------------------------
# CRYPTO
# --------------------------------------------------------------------------

def binance_window(symbol: str, t0: int, t1: int, host: str = "data-api.binance.vision"):
    """
    Reconstruct a GMT+1 window from 1h klines.

    Binance DAILY bars are UTC-aligned, which is one hour off GMT+1, so we never use
    them. We always rebuild from 1h klines: open = open of the bar starting at t0,
    close = close of the bar ending at t1.
    """
    url = (f"https://{host}/api/v3/klines?symbol={symbol}&interval=1h"
           f"&startTime={t0 * 1000}&endTime={t1 * 1000 - 1}&limit=1000")
    status, body = fetch(url)
    if status != 200:
        return status, None, None, body[:80].decode("utf-8", "replace")
    try:
        ks = json.loads(body)
    except Exception as e:
        return status, None, None, f"parse {e}"
    if not ks:
        return status, None, None, "empty"
    if int(ks[0][0]) != t0 * 1000:
        return status, None, None, f"first bar {ks[0][0]} != {t0 * 1000}"
    expected = (t1 - t0) // 3600
    if len(ks) != expected:
        return status, None, None, f"incomplete {len(ks)}/{expected}"
    return status, to_scaled(ks[0][1]), to_scaled(ks[-1][4]), ""


def gate_window(pair: str, t0: int, t1: int):
    """Gate.io v4 candlesticks: [ts, quote_vol, close, high, low, open, base_vol, closed]."""
    url = (f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}"
           f"&interval=1h&from={t0}&to={t1 - 1}")
    status, body = fetch(url)
    if status != 200:
        return status, None, None, body[:80].decode("utf-8", "replace")
    try:
        ks = json.loads(body)
    except Exception as e:
        return status, None, None, f"parse {e}"
    if not ks:
        return status, None, None, "empty"
    if int(ks[0][0]) != t0:
        return status, None, None, f"first bar {ks[0][0]} != {t0}"
    expected = (t1 - t0) // 3600
    if len(ks) != expected:
        return status, None, None, f"incomplete {len(ks)}/{expected}"
    return status, to_scaled(ks[0][5]), to_scaled(ks[-1][2]), ""


def coingecko_window(coin: str, t0: int, t1: int):
    """
    CoinGecko market_chart/range returns SAMPLED SPOT PRICES, not OHLC.
    We require a sample exactly on each boundary instant.
    """
    url = (f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart/range"
           f"?vs_currency=usd&from={t0}&to={t1}")
    status, body = fetch(url)
    if status != 200:
        return status, None, None, body[:80].decode("utf-8", "replace")
    try:
        pts = json.loads(body).get("prices", [])
    except Exception as e:
        return status, None, None, f"parse {e}"
    if not pts:
        return status, None, None, "empty"
    by_ms = {int(ms): px for ms, px in pts}
    o, c = by_ms.get(t0 * 1000), by_ms.get(t1 * 1000)
    if o is None or c is None:
        step = (pts[1][0] - pts[0][0]) // 1000 if len(pts) > 1 else 0
        return status, None, None, f"no boundary sample (n={len(pts)} step={step}s)"
    return status, to_scaled(o), to_scaled(c), ""


# --------------------------------------------------------------------------
# COMMODITIES
# --------------------------------------------------------------------------

def yahoo_window(symbol: str, t0: int, t1: int, interval: str = "1h"):
    """
    Yahoo Finance chart API. Keyless, needs a browser User-Agent.
    We pad the request window, then require bars exactly on our instants.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval={interval}&period1={t0 - 86400}&period2={t1 + 86400}")
    status, body = fetch(url)
    if status != 200:
        return status, None, None, body[:80].decode("utf-8", "replace")
    try:
        res = json.loads(body)["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
    except Exception as e:
        return status, None, None, f"parse {e}"
    idx = {t: i for i, t in enumerate(ts)}
    step = 3600 if interval == "1h" else 86400
    io_, ic = idx.get(t0), idx.get(t1 - step)
    if io_ is None or ic is None:
        return status, None, None, f"no bar on instant (n={len(ts)})"
    o, c = q["open"][io_], q["close"][ic]
    if o is None or c is None:
        return status, None, None, "null bar (no session)"
    return status, to_scaled(o), to_scaled(c), ""


def nasdaq_daily(symbol: str, day: str):
    """Nasdaq ETF daily OHLC. Keyless with a browser User-Agent. DAILY ONLY."""
    url = (f"https://api.nasdaq.com/api/quote/{symbol}/historical?assetclass=etf"
           f"&fromdate={day}&todate={day}&limit=5")
    status, body = fetch(url)
    if status != 200:
        return status, None, None, body[:80].decode("utf-8", "replace")
    try:
        rows = json.loads(body)["data"]["tradesTable"]["rows"]
    except Exception as e:
        return status, None, None, f"parse {e} (no session?)"
    want = datetime.strptime(day, "%Y-%m-%d").strftime("%m/%d/%Y")
    for r in rows:
        if r["date"] == want:
            def money(s):
                return to_scaled(s.replace("$", "").replace(",", ""))
            return status, money(r["open"]), money(r["close"]), ""
    return status, None, None, "day not in series"


# --------------------------------------------------------------------------

CRYPTO = {
    "ADA":  {"cg": "cardano",  "binance": "ADAUSDT",  "gate": "ADA_USDT"},
    "ZEC":  {"cg": "zcash",    "binance": "ZECUSDT",  "gate": "ZEC_USDT"},
    "ZAMA": {"cg": "zama",     "binance": "ZAMAUSDT", "gate": "ZAMA_USDT"},
    "ARB":  {"cg": "arbitrum", "binance": "ARBUSDT",  "gate": "ARB_USDT"},
}

COMMODITIES = {
    "GOLD":   {"yahoo_fut": "GC=F", "yahoo_etf": "GLD",  "nasdaq_etf": "GLD"},
    "SILVER": {"yahoo_fut": "SI=F", "yahoo_etf": "SLV",  "nasdaq_etf": "SLV"},
    "WTI":    {"yahoo_fut": "CL=F", "yahoo_etf": "USO",  "nasdaq_etf": "USO"},
    "COPPER": {"yahoo_fut": "HG=F", "yahoo_etf": "CPER", "nasdaq_etf": "CPER"},
}


def main():
    ap = argparse.ArgumentParser()
    yesterday = (datetime.now(GMT1) - timedelta(days=1)).strftime("%Y-%m-%d")
    ap.add_argument("--day", default=yesterday, help="target GMT+1 day YYYY-MM-DD")
    ap.add_argument("--hour", type=int, default=None, help="target GMT+1 hour 0..23")
    ap.add_argument("--skip-coingecko", action="store_true")
    args = ap.parse_args()

    hour = args.hour if args.hour is not None else 14
    d0, d1 = window_utc(args.day, None)
    h0, h1 = window_utc(args.day, hour)

    print("\nSpike feed probe - GMT+1 fixed offset (never DST)")
    print(f"  day  {args.day}       -> UTC [{d0}, {d1})  "
          f"{datetime.fromtimestamp(d0, timezone.utc):%Y-%m-%d %H:%M}Z .. "
          f"{datetime.fromtimestamp(d1, timezone.utc):%Y-%m-%d %H:%M}Z")
    print(f"  hour {args.day} {hour:02d}:00 -> UTC [{h0}, {h1})  "
          f"{datetime.fromtimestamp(h0, timezone.utc):%H:%M}Z .. "
          f"{datetime.fromtimestamp(h1, timezone.utc):%H:%M}Z")

    print("\n" + "=" * 96)
    print("CRYPTO - completed GMT+1 daily candle (KIND_DIRECTION)")
    print("=" * 96)
    for asset, ids in CRYPTO.items():
        print(f"\n{asset}")
        show("binance 1h->day", *binance_window(ids["binance"], d0, d1))
        show("gate.io 1h->day", *gate_window(ids["gate"], d0, d1))
        if not args.skip_coingecko:
            show("coingecko range", *coingecko_window(ids["cg"], d0, d1))
            time.sleep(6)  # public tier rate limit

    print("\n" + "=" * 96)
    print(f"CRYPTO - exact GMT+1 hour {hour:02d}:00 (KIND_DOMINANCE)")
    print("=" * 96)
    for asset, ids in CRYPTO.items():
        print(f"\n{asset}")
        show("binance 1h", *binance_window(ids["binance"], h0, h1))
        show("gate.io 1h", *gate_window(ids["gate"], h0, h1))
        if not args.skip_coingecko:
            show("coingecko range", *coingecko_window(ids["cg"], h0, h1))
            time.sleep(6)

    print("\n" + "=" * 96)
    print("COMMODITIES - completed GMT+1 daily candle")
    print("=" * 96)
    for asset, ids in COMMODITIES.items():
        print(f"\n{asset}")
        show("yahoo futures 1h->day", *yahoo_window(ids["yahoo_fut"], d0, d1))
        show("yahoo etf 1d", *yahoo_window(ids["yahoo_etf"], d0, d1, interval="1d"))
        show("nasdaq etf 1d", *nasdaq_daily(ids["nasdaq_etf"], args.day))

    print("\n" + "=" * 96)
    print(f"COMMODITIES - exact GMT+1 hour {hour:02d}:00")
    print("=" * 96)
    for asset, ids in COMMODITIES.items():
        print(f"\n{asset}")
        show("yahoo futures 1h", *yahoo_window(ids["yahoo_fut"], h0, h1))
        show("yahoo etf 1h", *yahoo_window(ids["yahoo_etf"], h0, h1))
        print(f"  {'nasdaq etf 1h':<26} -- NO INTRADAY ENDPOINT (daily only) --")

    print()


if __name__ == "__main__":
    sys.exit(main())
