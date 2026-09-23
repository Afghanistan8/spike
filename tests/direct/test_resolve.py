"""
resolve_market: two sources must independently agree, or nobody wins.

Every test here proves one of the guarantees in docs/SPEC.md section 4.
"""

import pytest

from conftest import (
    BINANCE_RE,
    ONE_GEN,
    YAHOO_RE,
    binance_body,
    mock_commodity,
    mock_crypto,
    stake,
    window_utc,
    yahoo_body,
)

# Mocks are matched in registration order, so a test that wants a source to
# fail must register that source's mock BEFORE the healthy one.


DAY = "2026-10-15"           # Thursday
AFTER_CLOSE = "2026-10-16T01:00:00Z"   # past settles_at, inside the 5-day window
AFTER_TERMINAL = "2026-10-22T00:00:00Z"  # past terminal_refund_at

CRYPTO_ASSETS = ["ADA", "ZEC", "ZAMA", "ARB"]
COMMODITY_ASSETS = ["GOLD", "SILVER", "WTI", "COPPER"]


def direction_market(spike, asset="ADA"):
    return spike.create_market("KIND_DIRECTION", "CRYPTO", asset, DAY, -1)


def day_window():
    return window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)


# -- direction --------------------------------------------------------------


def test_both_sources_up_settles_up(spike, direct_vm):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))

    assert spike.resolve_market(mid) == "UP"
    assert spike.get_market_phase(mid) == "SETTLED_UP"


def test_flat_candle_is_down(spike, direct_vm):
    """close == open is DOWN. A product rule, not an accident."""
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.5", "1.5"), binance=("1.5", "1.5"))

    assert spike.resolve_market(mid) == "DOWN"
    assert spike.get_market_phase(mid) == "SETTLED_DOWN"
    ev = spike.get_settlement_evidence(mid)
    assert ev["source_a_verdict"] == "DOWN"
    assert ev["source_b_verdict"] == "DOWN"


def test_sources_disagree_is_inconclusive(spike, direct_vm):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "0.5"))

    assert spike.resolve_market(mid) == "INCONCLUSIVE"
    assert spike.get_market_phase(mid) == "INCONCLUSIVE"
    ev = spike.get_settlement_evidence(mid)
    assert ev["source_a_verdict"] == "UP"
    assert ev["source_b_verdict"] == "DOWN"
    assert ev["refund_all"] is True


def test_evidence_records_both_sources_and_prices(spike, direct_vm):
    import json

    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    spike.resolve_market(mid)

    ev = spike.get_settlement_evidence(mid)
    assert ev["source_a_id"] == "gateio"
    assert ev["source_b_id"] == "binance"
    blob = json.loads(ev["evidence"])
    assert blob["source_a_prices"] == [10**8, 2 * 10**8]
    assert blob["source_b_prices"] == [10**8, 2 * 10**8]
    assert blob["final_verdict"] == "UP"
    # raw payloads never get persisted
    assert "chart" not in ev["evidence"]
    assert "<html" not in ev["evidence"]


# -- dominance --------------------------------------------------------------


def dominance_market(spike):
    return spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)


def hour_window():
    return window_utc("CRYPTO", "KIND_DOMINANCE", DAY, 14)


def mock_all_crypto(vm, t0, t1, returns_a, returns_b):
    """returns_* are (open, close) string pairs per asset in catalog order."""
    for i, asset in enumerate(CRYPTO_ASSETS):
        mock_crypto(vm, asset, t0, t1, gate=returns_a[i], binance=returns_b[i])


def test_dominance_agreed_winner(spike, direct_vm):
    mid = dominance_market(spike)
    t0, t1 = hour_window()
    direct_vm.warp(AFTER_CLOSE)
    # ZAMA is the clear winner on both sources: +100% vs +10%/+20%/+5%
    a = [("1.0", "1.1"), ("1.0", "1.2"), ("1.0", "2.0"), ("1.0", "1.05")]
    b = [("2.0", "2.2"), ("2.0", "2.4"), ("2.0", "4.0"), ("2.0", "2.1")]
    mock_all_crypto(direct_vm, t0, t1, a, b)

    assert spike.resolve_market(mid) == "WIN:ZAMA"
    assert spike.get_market_phase(mid) == "SETTLED_WINNER"


def test_dominance_tie_on_one_source_is_inconclusive(spike, direct_vm):
    mid = dominance_market(spike)
    t0, t1 = hour_window()
    direct_vm.warp(AFTER_CLOSE)
    # source A ties ZEC and ZAMA for first; source B has a clear ZAMA win
    a = [("1.0", "1.1"), ("1.0", "2.0"), ("1.0", "2.0"), ("1.0", "1.05")]
    b = [("2.0", "2.2"), ("2.0", "2.4"), ("2.0", "4.0"), ("2.0", "2.1")]
    mock_all_crypto(direct_vm, t0, t1, a, b)

    assert spike.resolve_market(mid) == "INCONCLUSIVE"
    assert spike.get_settlement_evidence(mid)["source_a_verdict"] == "TIE"


def test_dominance_different_winners_is_inconclusive(spike, direct_vm):
    mid = dominance_market(spike)
    t0, t1 = hour_window()
    direct_vm.warp(AFTER_CLOSE)
    a = [("1.0", "3.0"), ("1.0", "1.2"), ("1.0", "1.5"), ("1.0", "1.05")]  # ADA
    b = [("2.0", "2.2"), ("2.0", "2.4"), ("2.0", "9.0"), ("2.0", "2.1")]   # ZAMA
    mock_all_crypto(direct_vm, t0, t1, a, b)

    assert spike.resolve_market(mid) == "INCONCLUSIVE"
    ev = spike.get_settlement_evidence(mid)
    assert ev["source_a_verdict"] == "WIN:ADA"
    assert ev["source_b_verdict"] == "WIN:ZAMA"


def test_dominance_ranks_by_percentage_not_absolute(spike, direct_vm):
    """A cheap asset moving 1c beats an expensive one moving $1."""
    mid = dominance_market(spike)
    t0, t1 = hour_window()
    direct_vm.warp(AFTER_CLOSE)
    # ADA 0.10 -> 0.12 is +20%; ZEC 1000 -> 1100 is +10%
    a = [("0.10", "0.12"), ("1000.0", "1100.0"), ("1.0", "1.01"), ("1.0", "1.02")]
    mock_all_crypto(direct_vm, t0, t1, a, a)
    assert spike.resolve_market(mid) == "WIN:ADA"


# -- feed failures ----------------------------------------------------------


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_retryable_status_is_transient(spike, direct_vm, status):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, binance=("1.0", "2.0"), gate_status=status)

    with direct_vm.expect_revert("TRANSIENT:"):
        spike.resolve_market(mid)
    # market is untouched and still resolvable
    assert spike.get_market_phase(mid) == "READY_TO_SETTLE"
    assert spike.get_settlement_evidence(mid)["final_verdict"] == ""


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_other_4xx_is_external(spike, direct_vm, status):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, binance=("1.0", "2.0"), gate_status=status)

    with direct_vm.expect_revert("EXTERNAL:"):
        spike.resolve_market(mid)
    assert spike.get_market_phase(mid) == "READY_TO_SETTLE"


def test_one_source_429_never_settles_from_the_other(spike, direct_vm):
    """The whole point: a single reachable source cannot decide anything."""
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "9.0"), binance_status=429)

    with direct_vm.expect_revert("TRANSIENT:"):
        spike.resolve_market(mid)
    assert spike.get_settlement_evidence(mid)["final_verdict"] == ""


def test_malformed_body_is_external(spike, direct_vm):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    direct_vm.mock_web(r"api\.gateio\.ws", {"status": 200, "body": "not json at all"})
    direct_vm.mock_web(
        BINANCE_RE % "ADAUSDT", {"status": 200, "body": binance_body(t0, t1, "1.0", "2.0")}
    )

    with direct_vm.expect_revert("EXTERNAL:"):
        spike.resolve_market(mid)


def test_incomplete_window_is_external(spike, direct_vm):
    """23 bars is not a GMT+1 day. The contract refuses to guess."""
    import json

    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    short = [[str(t0 + i * 3600), "1", "2", "2", "1", "1", "1", "true"] for i in range(23)]
    direct_vm.mock_web(r"api\.gateio\.ws", {"status": 200, "body": json.dumps(short)})
    direct_vm.mock_web(
        BINANCE_RE % "ADAUSDT", {"status": 200, "body": binance_body(t0, t1, "1.0", "2.0")}
    )

    with direct_vm.expect_revert("EXTERNAL:"):
        spike.resolve_market(mid)


def test_empty_body_is_transient(spike, direct_vm):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    direct_vm.mock_web(r"api\.gateio\.ws", {"status": 200, "body": ""})
    direct_vm.mock_web(
        BINANCE_RE % "ADAUSDT", {"status": 200, "body": binance_body(t0, t1, "1.0", "2.0")}
    )

    with direct_vm.expect_revert("TRANSIENT:"):
        spike.resolve_market(mid)


# -- phase gating -----------------------------------------------------------


def test_resolve_before_close_rejected(spike, direct_vm):
    mid = direction_market(spike)
    direct_vm.warp("2026-10-15T09:00:00Z")
    with direct_vm.expect_revert("EXPECTED:"):
        spike.resolve_market(mid)


def test_double_resolve_rejected(spike, direct_vm):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    spike.resolve_market(mid)
    with direct_vm.expect_revert("EXPECTED:"):
        spike.resolve_market(mid)


def test_unknown_market_rejected(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.resolve_market("999")


def test_anyone_can_resolve(spike, direct_vm, direct_bob):
    mid = direction_market(spike)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    with direct_vm.prank(direct_bob):
        assert spike.resolve_market(mid) == "UP"


# -- terminal refund --------------------------------------------------------


def test_terminal_refund_never_touches_the_web(spike, direct_vm, direct_alice):
    """
    No web mocks are registered. If resolve_market made a single request the
    harness would raise MockNotFoundError, so this passing proves it did not.
    """
    mid = direction_market(spike)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    direct_vm.warp(AFTER_TERMINAL)

    assert spike.resolve_market(mid) == "TERMINAL_REFUND"
    ev = spike.get_settlement_evidence(mid)
    assert ev["final_verdict"] == "INCONCLUSIVE"
    assert ev["refund_all"] is True
    assert ev["source_a_verdict"] == ""
    assert ev["source_b_verdict"] == ""
    assert spike.get_claimable(mid, direct_alice.as_hex) == str(ONE_GEN)


# -- commodities ------------------------------------------------------------


def test_commodity_direction_settles_from_yahoo_and_nasdaq(spike, direct_vm):
    mid = spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", DAY, -1)
    direct_vm.warp(AFTER_CLOSE)
    mock_commodity(direct_vm, "GOLD", DAY, yahoo=(397.07, 400.07), nasdaq=("397.07", "400.07"))

    assert spike.resolve_market(mid) == "UP"
    ev = spike.get_settlement_evidence(mid)
    assert ev["source_a_id"] == "yahoo"
    assert ev["source_b_id"] == "nasdaq"


def test_commodity_sources_disagree_is_inconclusive(spike, direct_vm):
    mid = spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", DAY, -1)
    direct_vm.warp(AFTER_CLOSE)
    mock_commodity(direct_vm, "GOLD", DAY, yahoo=(397.07, 400.07), nasdaq=("400.07", "397.07"))
    assert spike.resolve_market(mid) == "INCONCLUSIVE"


def test_commodity_no_session_is_external(spike, direct_vm):
    """A holiday has no bar. The contract must not invent a candle."""
    import json

    mid = spike.create_market("KIND_DIRECTION", "COMMODITIES", "GOLD", DAY, -1)
    direct_vm.warp(AFTER_CLOSE)
    direct_vm.mock_web(
        r"api\.nasdaq\.com",
        {"status": 200, "body": json.dumps({"data": None, "status": {"rCode": 200}})},
    )
    direct_vm.mock_web(
        YAHOO_RE % "GLD", {"status": 200, "body": yahoo_body(DAY, 397.07, 400.07)}
    )
    with direct_vm.expect_revert("EXTERNAL:"):
        spike.resolve_market(mid)


def test_commodity_dominance_over_the_daily_session(spike, direct_vm):
    mid = spike.create_market("KIND_DOMINANCE", "COMMODITIES", "", DAY, -1)
    direct_vm.warp(AFTER_CLOSE)
    # SILVER is the clear winner on both vendors
    moves = {"GOLD": (100.0, 101.0), "SILVER": (100.0, 110.0),
             "WTI": (100.0, 100.5), "COPPER": (100.0, 99.0)}
    for asset, (o, c) in moves.items():
        mock_commodity(direct_vm, asset, DAY, yahoo=(o, c), nasdaq=(str(o), str(c)))

    assert spike.resolve_market(mid) == "WIN:SILVER"
    assert spike.get_market_phase(mid) == "SETTLED_WINNER"
