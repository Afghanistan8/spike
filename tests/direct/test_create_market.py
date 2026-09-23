"""create_market: the catalog is closed and the calendar rules are enforced."""

import pytest

from conftest import window_utc

DAY = "2026-10-15"  # a Thursday, safely in the future of the deploy warp
SAT = "2026-10-17"
SUN = "2026-10-18"


def test_creates_a_crypto_direction_market(spike):
    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    assert mid == "1"
    m = spike.get_market(mid)
    assert m["category"] == "CRYPTO"
    assert m["asset"] == "ADA"
    assert m["target_hour"] == -1
    assert m["phase"] == "OPEN"
    assert m["sides"] == ["UP", "DOWN"]
    assert m["window_open"], m["window_close"] == window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)


def test_creates_a_crypto_dominance_market_with_an_hour(spike):
    mid = spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)
    m = spike.get_market(mid)
    assert m["target_hour"] == 14
    assert m["sides"] == ["ADA", "ZEC", "ZAMA", "ARB"]
    assert m["window_close"] - m["window_open"] == 3600


def test_commodity_dominance_uses_the_daily_session(spike):
    mid = spike.create_market("KIND_DOMINANCE", "COMMODITIES", "", DAY, -1)
    m = spike.get_market(mid)
    assert m["target_hour"] == -1
    assert m["window_close"] - m["window_open"] == 86400
    assert m["sides"] == ["GOLD", "SILVER", "WTI", "COPPER"]


# -- catalog is closed ------------------------------------------------------


@pytest.mark.parametrize("asset", ["BTC", "ETH", "DOGE", "ada", "", "GOLD"])
def test_unknown_crypto_asset_rejected(spike, direct_vm, asset):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", asset, DAY, -1)


@pytest.mark.parametrize("asset", ["PLATINUM", "OIL", "ADA", ""])
def test_unknown_commodity_asset_rejected(spike, direct_vm, asset):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "COMMODITIES", asset, DAY, -1)


@pytest.mark.parametrize("category", ["FOREX", "STOCKS", "crypto", ""])
def test_unknown_category_rejected(spike, direct_vm, category):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", category, "ADA", DAY, -1)


def test_unknown_kind_rejected(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_SOMETHING", "CRYPTO", "ADA", DAY, -1)


def test_dominance_takes_no_asset(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DOMINANCE", "CRYPTO", "ADA", DAY, 14)


# -- calendar rules ---------------------------------------------------------


@pytest.mark.parametrize("day", [SAT, SUN])
def test_commodity_weekend_rejected(spike, direct_vm, day):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", day, -1)


@pytest.mark.parametrize("day", [SAT, SUN])
def test_crypto_weekend_allowed(spike, day):
    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", day, -1)
    assert spike.get_market(mid)["phase"] == "OPEN"


def test_past_window_rejected(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-09-01", -1)


def test_window_already_started_rejected(spike, direct_vm):
    # deploy warp is 2026-09-20T12:00Z, so the GMT+1 day 2026-09-20 is live
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-09-20", -1)


def test_too_far_ahead_rejected(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2028-01-01", -1)


def test_bad_day_format_rejected(spike, direct_vm):
    for bad in ["2026-13-01", "2026-02-30", "15-10-2026", "2026-10-1", "nope"]:
        with direct_vm.expect_revert("EXPECTED:"):
            spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", bad, -1)


# -- hour rules -------------------------------------------------------------


@pytest.mark.parametrize("hour", [-1, 24, 99])
def test_crypto_dominance_needs_valid_hour(spike, direct_vm, hour):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, hour)


def test_direction_rejects_a_meaningful_hour(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, 14)


def test_commodity_dominance_rejects_an_hour(spike, direct_vm):
    """There is no second intraday commodity source, so an hour is meaningless."""
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DOMINANCE", "COMMODITIES", "", DAY, 14)


# -- uniqueness -------------------------------------------------------------


def test_duplicate_market_rejected(spike, direct_vm):
    spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    with direct_vm.expect_revert("EXPECTED:"):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)


def test_same_day_different_asset_is_not_a_duplicate(spike):
    a = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    b = spike.create_market("KIND_DIRECTION", "CRYPTO", "ZEC", DAY, -1)
    assert a != b


def test_same_day_different_hour_is_not_a_duplicate(spike):
    a = spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 9)
    b = spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 10)
    assert a != b


def test_unique_key_lookup(spike):
    mid = spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)
    found = spike.get_market_by_unique_key("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)
    assert found["market_id"] == mid
    assert found["unique_key"] == "KIND_DOMINANCE|CRYPTO||%s|14" % DAY
    assert spike.get_market_by_unique_key("KIND_DOMINANCE", "CRYPTO", "", DAY, 15) == {}


def test_anyone_can_create(spike, direct_vm, direct_alice, direct_bob):
    with direct_vm.prank(direct_alice):
        a = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    with direct_vm.prank(direct_bob):
        b = spike.create_market("KIND_DIRECTION", "CRYPTO", "ZEC", DAY, -1)
    assert spike.get_market(a)["creator"] == direct_alice.as_hex
    assert spike.get_market(b)["creator"] == direct_bob.as_hex
