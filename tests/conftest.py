"""
Shared harness for Spike direct-mode tests.

Two things the stock gltest direct runner does not give us:

1. `EthSend` (the EVM external message behind `emit_transfer`) is not handled,
   so every payout and refund path would fail. We install a `_gl_call_hook`
   that accepts it and records it, which also lets tests assert that the right
   wei went to the right wallet.
2. Builders for each feed's wire format, so a test can construct an exact
   scenario (flat candle, sources disagreeing, a tie for first) without
   hand-writing JSON.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Both tests/direct and tests/consensus import these builders by name. Putting
# this directory on sys.path lets `from conftest import ...` resolve from either.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONTRACT = "contracts/Spike.py"

GMT1 = timezone(timedelta(hours=1))
ONE_GEN = 10**18
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


# --------------------------------------------------------------------------
# window math, mirrored independently of the contract so the tests are a
# genuine second opinion rather than a restatement
# --------------------------------------------------------------------------


def window_utc(category: str, kind: str, day: str, hour: int):
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=GMT1)
    if category == "CRYPTO" and kind == "KIND_DOMINANCE":
        start = d + timedelta(hours=hour)
        return int(start.timestamp()), int((start + timedelta(hours=1)).timestamp())
    return int(d.timestamp()), int((d + timedelta(days=1)).timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# wire-format builders
# --------------------------------------------------------------------------


def binance_body(t0: int, t1: int, open_px: str, close_px: str) -> str:
    """N consecutive 1h bars. Only the first open and the last close matter."""
    n = (t1 - t0) // 3600
    rows = []
    for i in range(n):
        o = open_px if i == 0 else close_px
        c = close_px
        rows.append(
            [(t0 + i * 3600) * 1000, o, c, o, c, "100.0",
             (t0 + (i + 1) * 3600) * 1000 - 1, "1000.0", 10, "50.0", "500.0", "0"]
        )
    return json.dumps(rows)


def gate_body(t0: int, t1: int, open_px: str, close_px: str) -> str:
    """Gate rows carry a different field order: [ts, qv, close, high, low, open, ...]."""
    n = (t1 - t0) // 3600
    rows = []
    for i in range(n):
        o = open_px if i == 0 else close_px
        rows.append([str(t0 + i * 3600), "1000.0", close_px, close_px, o, o, "100.0", "true"])
    return json.dumps(rows)


def yahoo_body(day: str, open_px: float, close_px: float, gmtoffset: int = -14400) -> str:
    """One 1d bar stamped at session open in the exchange timezone."""
    midnight = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    stamp = midnight - gmtoffset + 9 * 3600 + 30 * 60  # ~09:30 local
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"gmtoffset": gmtoffset, "exchangeTimezoneName": "America/New_York"},
                        "timestamp": [stamp],
                        "indicators": {"quote": [{"open": [open_px], "close": [close_px]}]},
                    }
                ],
                "error": None,
            }
        }
    )


def nasdaq_body(day: str, open_px: str, close_px: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    return json.dumps(
        {
            "data": {
                "symbol": "X",
                "tradesTable": {
                    "rows": [
                        {
                            "date": d.strftime("%m/%d/%Y"),
                            "open": "$" + open_px,
                            "close": close_px,
                            "high": close_px,
                            "low": open_px,
                            "volume": "1,000,000",
                        }
                    ]
                },
            },
            "message": None,
            "status": {"rCode": 200},
        }
    )


def load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read().decode("utf-8")


# --------------------------------------------------------------------------
# URL regexes matching what the contract builds
# --------------------------------------------------------------------------

BINANCE_RE = r"data-api\.binance\.vision.*symbol=%s&"
GATE_RE = r"api\.gateio\.ws.*currency_pair=%s&"
YAHOO_RE = r"query1\.finance\.yahoo\.com.*/chart/%s\?"
NASDAQ_RE = r"api\.nasdaq\.com/api/quote/%s/"

BINANCE_SYMBOL = {"ADA": "ADAUSDT", "ZEC": "ZECUSDT", "ZAMA": "ZAMAUSDT", "ARB": "ARBUSDT"}
GATE_PAIR = {"ADA": "ADA_USDT", "ZEC": "ZEC_USDT", "ZAMA": "ZAMA_USDT", "ARB": "ARB_USDT"}
PROXY = {"GOLD": "GLD", "SILVER": "SLV", "WTI": "USO", "COPPER": "CPER"}


def mock_crypto(vm, asset, t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"),
                gate_status=200, binance_status=200):
    """Mock both crypto sources for one asset. Pass a status to simulate failure."""
    vm.mock_web(
        GATE_RE % GATE_PAIR[asset],
        {"status": gate_status, "body": gate_body(t0, t1, gate[0], gate[1]) if gate_status == 200 else ""},
    )
    vm.mock_web(
        BINANCE_RE % BINANCE_SYMBOL[asset],
        {"status": binance_status, "body": binance_body(t0, t1, binance[0], binance[1]) if binance_status == 200 else ""},
    )


def mock_commodity(vm, asset, day, yahoo=(100.0, 110.0), nasdaq=("100.0", "110.0"),
                   yahoo_status=200, nasdaq_status=200):
    vm.mock_web(
        YAHOO_RE % PROXY[asset],
        {"status": yahoo_status, "body": yahoo_body(day, yahoo[0], yahoo[1]) if yahoo_status == 200 else ""},
    )
    vm.mock_web(
        NASDAQ_RE % PROXY[asset],
        {"status": nasdaq_status, "body": nasdaq_body(day, nasdaq[0], nasdaq[1]) if nasdaq_status == 200 else ""},
    )


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


class Transfers(list):
    """Records every outbound value transfer the contract emitted."""

    def total_to(self, addr) -> int:
        want = addr.as_hex if hasattr(addr, "as_hex") else str(addr)
        return sum(v for a, v in self if a == want)


@pytest.fixture
def transfers(direct_vm):
    """
    Installs an EthSend handler and returns the recorded (address_hex, wei) pairs.

    Direct mode has no EVM layer, so without this every emit_transfer would
    fail with 'Unknown gl_call request type'.
    """
    rec = Transfers()

    def hook(vm, request):
        if "EthSend" in request:
            d = request["EthSend"]
            addr = d.get("address")
            addr_hex = addr.as_hex if hasattr(addr, "as_hex") else str(addr)
            rec.append((addr_hex, int(d.get("value", 0))))
            return {"ok": None}
        return None

    direct_vm._gl_call_hook = hook
    return rec


@pytest.fixture
def spike(direct_vm, direct_deploy, transfers):
    """Deployed contract at a fixed, known time."""
    direct_vm.warp("2026-09-20T12:00:00Z")
    return direct_deploy(CONTRACT)


def stake(vm, contract, market_id, side, amount, sender=None):
    """Attach value to a take_position call, the way a wallet would."""
    prev_value, prev_sender = vm.value, vm.sender
    vm.value = amount
    if sender is not None:
        vm.sender = sender
    try:
        return contract.take_position(market_id, side)
    finally:
        vm.value = prev_value
        vm.sender = prev_sender
