"""Views are read-only, and every list caps at 50."""

import pytest

from conftest import ONE_GEN, mock_crypto, stake, window_utc

DAY_BASE = 10  # markets are created on 2026-10-10 .. 2026-11-xx


def make_markets(spike, n):
    """n distinct crypto direction markets on consecutive days."""
    ids = []
    assets = ["ADA", "ZEC", "ZAMA", "ARB"]
    day = 0
    while len(ids) < n:
        d = "2026-%02d-%02d" % (10 + day // 28, 1 + day % 28)
        for a in assets:
            if len(ids) >= n:
                break
            try:
                ids.append(spike.create_market("KIND_DIRECTION", "CRYPTO", a, d, -1))
            except Exception:
                pass
        day += 1
    return ids


def test_pagination_caps_at_fifty(spike):
    make_markets(spike, 60)
    got = spike.get_markets(0, 1000)
    assert got["total"] == 60
    assert len(got["items"]) == 50


def test_pagination_walks_the_whole_list(spike):
    ids = make_markets(spike, 60)
    first = spike.get_markets(0, 50)["items"]
    second = spike.get_markets(50, 50)["items"]
    assert len(first) == 50
    assert len(second) == 10
    assert [m["market_id"] for m in first + second] == ids


def test_pagination_past_the_end_is_empty(spike):
    make_markets(spike, 5)
    got = spike.get_markets(100, 50)
    assert got["total"] == 5
    assert got["items"] == []


@pytest.mark.parametrize("offset,limit", [(-5, 10), (0, -1), (-1, -1), (0, 0)])
def test_pagination_bounds_are_clamped(spike, offset, limit):
    make_markets(spike, 5)
    got = spike.get_markets(offset, limit)
    assert got["total"] == 5
    assert 0 <= len(got["items"]) <= 5


def test_markets_by_category(spike):
    spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1)
    spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", "2026-10-15", -1)
    spike.create_market("KIND_DIRECTION", "COMMODITIES", "SILVER", "2026-10-15", -1)

    assert spike.get_markets_by_category("CRYPTO", 0, 50)["total"] == 1
    assert spike.get_markets_by_category("COMMODITIES", 0, 50)["total"] == 2
    assert spike.get_markets_by_category("NOPE", 0, 50)["total"] == 0


def test_open_markets_excludes_settled(spike, direct_vm):
    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1)
    spike.create_market("KIND_DIRECTION", "CRYPTO", "ZEC", "2026-11-15", -1)
    assert spike.get_open_markets(0, 50)["total"] == 2

    t0, t1 = window_utc("CRYPTO", "KIND_DIRECTION", "2026-10-15", -1)
    direct_vm.warp("2026-10-16T01:00:00Z")
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    spike.resolve_market(mid)

    assert spike.get_open_markets(0, 50)["total"] == 1


def test_user_markets_and_positions(spike, direct_vm, direct_alice, direct_bob):
    with direct_vm.prank(direct_alice):
        a = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1)
    with direct_vm.prank(direct_bob):
        spike.create_market("KIND_DIRECTION", "CRYPTO", "ZEC", "2026-10-15", -1)

    assert spike.get_user_markets(direct_alice.as_hex, 0, 50)["total"] == 1
    assert spike.get_user_markets(direct_bob.as_hex, 0, 50)["total"] == 1

    stake(direct_vm, spike, a, "UP", ONE_GEN, direct_bob)
    assert spike.get_user_positions(direct_bob.as_hex, 0, 50)["total"] == 1
    assert spike.get_user_positions(direct_alice.as_hex, 0, 50)["total"] == 0


def test_missing_lookups_return_empty(spike):
    assert spike.get_market("999") == {}
    assert spike.get_market_phase("999") == ""
    assert spike.get_position("999", "0x" + "11" * 20) == {}
    assert spike.get_claimable("999", "0x" + "11" * 20) == "0"
    assert spike.get_settlement_evidence("999") == {}
    assert spike.get_user_markets("0x" + "11" * 20, 0, 50)["total"] == 0


def test_stats_track_the_protocol(spike, direct_vm, direct_alice, direct_charlie):
    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", 2 * ONE_GEN, direct_charlie)

    s = spike.get_stats()
    assert s["markets"] == 1
    assert s["open_markets"] == 1
    assert s["resolved_markets"] == 0
    assert s["total_staked_wei"] == str(3 * ONE_GEN)

    t0, t1 = window_utc("CRYPTO", "KIND_DIRECTION", "2026-10-15", -1)
    direct_vm.warp("2026-10-16T01:00:00Z")
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    spike.resolve_market(mid)
    with direct_vm.prank(direct_alice):
        spike.claim(mid)

    s = spike.get_stats()
    assert s["resolved_markets"] == 1
    assert s["open_markets"] == 0
    assert s["total_paid_out_wei"] == str(3 * ONE_GEN)


def test_activity_is_newest_first(spike, direct_vm, direct_alice):
    a = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1)
    stake(direct_vm, spike, a, "UP", ONE_GEN, direct_alice)

    act = spike.get_activity(0, 50)
    assert act["total"] == 2
    assert act["items"][0].startswith("STAKE|")
    assert act["items"][1].startswith("CREATE|")


def test_universe_labels_commodities_as_proxies(spike):
    labels = spike.get_supported_universe()["labels"]["COMMODITIES"]
    assert labels["GOLD"] == "GOLD (GLD proxy)"
    assert labels["WTI"] == "WTI (USO proxy)"
    # crypto is the real asset, so no proxy wording
    assert spike.get_supported_universe()["labels"]["CRYPTO"]["ADA"] == "ADA"


def test_market_view_labels_commodity_asset(spike):
    mid = spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", "2026-10-15", -1)
    assert spike.get_market(mid)["asset_label"] == "GOLD (GLD proxy)"
