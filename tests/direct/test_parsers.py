"""
Window reconstruction against REAL recorded bytes.

The fixtures in tests/fixtures/ were captured from the live feeds by
scripts/record_fixtures.py. These tests never touch the network; they prove the
parsers rebuild the same GMT+1 window from two different wire formats and land
on the same verdict.
"""

import json
import os
import sys

import pytest

from conftest import CONTRACT, load_fixture, window_utc

DAY = "2026-09-22"
HOUR = 14
SCALE = 10**8


@pytest.fixture
def mod(direct_vm, direct_deploy):
    """The loaded contract module, for exercising its pure helpers directly."""
    direct_vm.warp("2026-09-23T12:00:00Z")
    direct_deploy(CONTRACT)
    for name, m in sys.modules.items():
        if name.endswith("Spike") and hasattr(m, "_parse_binance_klines"):
            return m
    raise AssertionError("contract module not found in sys.modules")


def meta():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fixtures", "meta.json")) as f:
        return json.load(f)


# -- the GMT+1 window itself ------------------------------------------------


def test_recorded_window_is_gmt_plus_one(mod):
    m = meta()
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)
    assert [t0, t1] == m["day_window_utc"]
    # 2026-09-22 00:00 GMT+1 is 2026-09-21 23:00 UTC
    assert t0 % 86400 == 23 * 3600
    assert t1 - t0 == 86400


def test_hour_window_is_gmt_plus_one(mod):
    m = meta()
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DOMINANCE", DAY, HOUR)
    assert [t0, t1] == m["hour_window_utc"]
    assert t1 - t0 == 3600


def test_a_utc_day_is_not_a_gmt_plus_one_day(mod):
    """The one-hour trap that would silently settle the wrong candle."""
    t0, _ = mod._window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)
    utc_midnight = mod._day_utc_midnight(DAY)
    assert utc_midnight - t0 == 3600


def test_window_matches_an_independent_implementation(mod):
    """conftest computes the window with datetime; the contract uses integers."""
    for day in ["2026-01-01", "2026-02-28", "2026-03-15", "2026-12-31", "2028-02-29"]:
        assert mod._window_utc("CRYPTO", "KIND_DIRECTION", day, -1) == \
            window_utc("CRYPTO", "KIND_DIRECTION", day, -1)
    for hour in range(0, 24, 5):
        assert mod._window_utc("CRYPTO", "KIND_DOMINANCE", DAY, hour) == \
            window_utc("CRYPTO", "KIND_DOMINANCE", DAY, hour)


# -- crypto: two wire formats, one window -----------------------------------

CRYPTO_EXPECTED_DAY = {
    # values observed on the live feeds on 2026-09-22, scaled by 1e8
    "ADA":  ((24630000, 25310000), (24639000, 25312000)),
    "ZEC":  ((147160000000, 155320000000), (147175000000, 155308000000)),
    "ZAMA": ((9249000, 9410000), (9259000, 9410000)),
    "ARB":  ((22590000, 22550000), (22583000, 22550000)),
}


@pytest.mark.parametrize("asset", ["ADA", "ZEC", "ZAMA", "ARB"])
def test_daily_window_from_real_bytes(mod, asset):
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)
    binance = load_fixture(f"binance_{asset}_day_{DAY}.json").encode()
    gate = load_fixture(f"gate_{asset}_day_{DAY}.json").encode()

    b = mod._parse_binance_klines(binance, t0, t1)
    g = mod._parse_gate_candles(gate, t0, t1)
    assert b == CRYPTO_EXPECTED_DAY[asset][0]
    assert g == CRYPTO_EXPECTED_DAY[asset][1]


@pytest.mark.parametrize("asset", ["ADA", "ZEC", "ZAMA", "ARB"])
def test_real_sources_agree_on_direction(mod, asset):
    """Independent venues, independent parsers, same verdict."""
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)
    b = mod._parse_binance_klines(load_fixture(f"binance_{asset}_day_{DAY}.json").encode(), t0, t1)
    g = mod._parse_gate_candles(load_fixture(f"gate_{asset}_day_{DAY}.json").encode(), t0, t1)

    vb = mod._verdict_direction(b[0], b[1])
    vg = mod._verdict_direction(g[0], g[1])
    assert vb == vg
    assert mod._final_verdict(vg, vb) == vb


@pytest.mark.parametrize("asset", ["ADA", "ZEC", "ZAMA", "ARB"])
def test_hourly_window_from_real_bytes(mod, asset):
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DOMINANCE", DAY, HOUR)
    b = mod._parse_binance_klines(
        load_fixture(f"binance_{asset}_hour_{DAY}_{HOUR:02d}.json").encode(), t0, t1)
    g = mod._parse_gate_candles(
        load_fixture(f"gate_{asset}_hour_{DAY}_{HOUR:02d}.json").encode(), t0, t1)
    assert b[0] > 0 and b[1] > 0 and g[0] > 0 and g[1] > 0
    assert mod._verdict_direction(*b) == mod._verdict_direction(*g)


def test_real_dominance_winner_agrees_across_sources(mod):
    """The recorded hour: both venues must crown the same asset."""
    t0, t1 = mod._window_utc("CRYPTO", "KIND_DOMINANCE", DAY, HOUR)
    assets = ["ADA", "ZEC", "ZAMA", "ARB"]
    ob, cb, og, cg = [], [], [], []
    for a in assets:
        b = mod._parse_binance_klines(
            load_fixture(f"binance_{a}_hour_{DAY}_{HOUR:02d}.json").encode(), t0, t1)
        g = mod._parse_gate_candles(
            load_fixture(f"gate_{a}_hour_{DAY}_{HOUR:02d}.json").encode(), t0, t1)
        ob.append(b[0]); cb.append(b[1])
        og.append(g[0]); cg.append(g[1])

    vb = mod._verdict_dominance(assets, ob, cb)
    vg = mod._verdict_dominance(assets, og, cg)
    assert vb.startswith("WIN:")
    assert vb == vg
    assert mod._final_verdict(vg, vb) == vb


# -- commodities ------------------------------------------------------------


# 2026-09-18 is a completed Friday session, present and final in both vendors'
# recorded payloads. 2026-09-22 was still settling when the fixtures were taken.
SETTLED_DAY = "2026-09-18"


@pytest.mark.parametrize("asset", ["GOLD", "SILVER", "WTI", "COPPER"])
def test_commodity_session_from_real_bytes(mod, asset):
    y = mod._parse_yahoo_daily(
        load_fixture(f"yahoo_{asset}_day_{DAY}.json").encode(), SETTLED_DAY)
    n = mod._parse_nasdaq_daily(
        load_fixture(f"nasdaq_{asset}_day_{DAY}.json").encode(), SETTLED_DAY)
    assert y[0] > 0 and y[1] > 0
    assert n[0] > 0 and n[1] > 0
    # Same instrument from two vendors. The prices differ in the last decimals -
    # Yahoo carries float precision, Nasdaq publishes rounded cents - which is
    # exactly why the VERDICT is what has to match, never the raw price.
    assert mod._verdict_direction(*y) == mod._verdict_direction(*n)
    assert y != n


def test_nasdaq_gold_matches_the_recorded_quote(mod):
    o, c = mod._parse_nasdaq_daily(load_fixture(f"nasdaq_GOLD_day_{DAY}.json").encode(), DAY)
    assert (o, c) == (39707000000, 40007000000)  # $397.07 -> $400.07


def test_yahoo_refuses_a_bar_that_has_not_settled(mod):
    """
    The recorded 2026-09-22 Yahoo bar has an open but a null close - the session
    had not been finalised. The contract must refuse it rather than invent a
    candle; the caller retries later.
    """
    with pytest.raises(Exception, match="null bar"):
        mod._parse_yahoo_daily(load_fixture(f"yahoo_GOLD_day_{DAY}.json").encode(), DAY)


def test_nasdaq_rejects_a_day_with_no_row(mod):
    with pytest.raises(Exception):
        mod._parse_nasdaq_daily(load_fixture(f"nasdaq_GOLD_day_{DAY}.json").encode(), "2026-09-19")


# -- price scaling ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,want",
    [
        ("1", SCALE),
        ("0.5", SCALE // 2),
        ("397.07", 39707000000),
        ("$397.07", 39707000000),
        ("1,234.5", 123450000000),
        (".25", 25000000),
        ("0.123456789", 12345678),   # truncated at 8dp, never rounded up
        (400.07, 40007000000),
    ],
)
def test_scale_price(mod, raw, want):
    assert mod._scale_price(raw) == want


@pytest.mark.parametrize("bad", ["", "abc", "1e5", "1.2.3", None, True])
def test_scale_price_refuses_junk(mod, bad):
    with pytest.raises(Exception):
        mod._scale_price(bad)


def test_scaling_never_uses_float_arithmetic(mod):
    """0.07 is not representable in binary; the string path must still be exact."""
    assert mod._scale_price("0.07") == 7000000
    assert mod._scale_price("1000000.07") == 100000007000000


# -- verdict rules ----------------------------------------------------------


def test_flat_is_down(mod):
    assert mod._verdict_direction(100, 100) == "DOWN"
    assert mod._verdict_direction(100, 101) == "UP"
    assert mod._verdict_direction(100, 99) == "DOWN"


def test_dominance_uses_percentage_not_absolute(mod):
    assets = ["A", "B"]
    # B gains 100 units but only 10%; A gains 2 units and 20%
    assert mod._verdict_dominance(assets, [10, 1000], [12, 1100]) == "WIN:A"


def test_dominance_tie_for_first(mod):
    assets = ["A", "B", "C", "D"]
    assert mod._verdict_dominance(assets, [10, 10, 10, 10], [12, 12, 11, 10]) == "TIE"
    # a tie for SECOND place is not a tie
    assert mod._verdict_dominance(assets, [10, 10, 10, 10], [15, 12, 12, 10]) == "WIN:A"


def test_final_verdict_requires_both_sources(mod):
    assert mod._final_verdict("UP", "UP") == "UP"
    assert mod._final_verdict("DOWN", "DOWN") == "DOWN"
    assert mod._final_verdict("WIN:ADA", "WIN:ADA") == "WIN:ADA"
    assert mod._final_verdict("UP", "DOWN") == "INCONCLUSIVE"
    assert mod._final_verdict("WIN:ADA", "WIN:ZEC") == "INCONCLUSIVE"
    assert mod._final_verdict("TIE", "TIE") == "INCONCLUSIVE"
    assert mod._final_verdict("MISSING", "MISSING") == "INCONCLUSIVE"
    assert mod._final_verdict("UP", "MISSING") == "INCONCLUSIVE"


def test_weekday_calculation(mod):
    assert mod._weekday("2026-10-15") == 3   # Thursday
    assert mod._weekday("2026-10-17") == 5   # Saturday
    assert mod._weekday("2026-10-18") == 6   # Sunday
    assert mod._weekday("2026-10-19") == 0   # Monday
