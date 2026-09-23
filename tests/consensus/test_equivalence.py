"""
Equivalence-principle behaviour.

resolve_market wraps both feed fetches in `gl.eq_principle.strict_eq`, whose
validator is literally:

    my_res = vm.spawn_sandbox(fn)
    return my_res == leaders_res

So consensus is decided by **value equality of the payload** that the
non-deterministic block returns. These tests run that block (`_collect`) under
one set of feeds, then under another, and compare the payloads - which is
precisely the comparison a validator performs.

We drive `_collect` rather than `direct_vm.run_validator()` because the
in-process runner does not implement `spawn_sandbox` (it warns "gl.sandbox is
not fully isolated in direct test mode" and the sub-VM result fails to decode).
Comparing payloads tests the real property without depending on that gap.
"""

import sys

import pytest

from conftest import CONTRACT, mock_crypto, window_utc

DAY = "2026-10-15"
AFTER_CLOSE = "2026-10-16T01:00:00Z"
ASSETS = ["ADA", "ZEC", "ZAMA", "ARB"]


@pytest.fixture
def mod(direct_vm, direct_deploy):
    direct_vm.warp("2026-09-20T12:00:00Z")
    direct_deploy(CONTRACT)
    for name, m in sys.modules.items():
        if name.endswith("Spike") and hasattr(m, "_final_verdict"):
            return m
    raise AssertionError("contract module not found")


def day_window():
    return window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)


# -- validator agreement ----------------------------------------------------


def collect_direction(mod, vm, gate, binance, asset="ADA"):
    """Run the non-deterministic block once, as one node would."""
    t0, t1 = day_window()
    vm.clear_mocks()
    mock_crypto(vm, asset, t0, t1, gate=gate, binance=binance)
    return mod._collect("CRYPTO", "KIND_DIRECTION", [asset], DAY, -1, t0, t1)


def collect_dominance(mod, vm, moves):
    t0, t1 = window_utc("CRYPTO", "KIND_DOMINANCE", DAY, 14)
    vm.clear_mocks()
    for i, a in enumerate(ASSETS):
        mock_crypto(vm, a, t0, t1, gate=moves[i], binance=moves[i])
    return mod._collect("CRYPTO", "KIND_DOMINANCE", ASSETS, DAY, 14, t0, t1)


def test_two_nodes_seeing_the_same_feeds_agree(mod, direct_vm):
    leader = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    validator = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    assert leader == validator          # strict_eq accepts
    assert leader["final_verdict"] == "UP"


def test_a_node_seeing_a_different_market_disagrees(mod, direct_vm):
    """
    Consensus fails, the transaction is undetermined and no state changes -
    which is exactly what should happen.
    """
    leader = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    validator = collect_direction(mod, direct_vm, ("2.0", "1.0"), ("2.0", "1.0"))
    assert leader != validator          # strict_eq rejects
    assert leader["final_verdict"] == "UP"
    assert validator["final_verdict"] == "DOWN"


def test_one_unit_of_price_drift_breaks_equality(mod, direct_vm):
    """strict_eq means exact. There is no tolerance band to hide behind."""
    leader = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    validator = collect_direction(mod, direct_vm, ("1.0", "2.00000001"), ("1.0", "2.0"))
    assert leader != validator
    # the verdict is the same; it is the evidence that differs
    assert leader["final_verdict"] == validator["final_verdict"] == "UP"


def test_one_source_changing_breaks_equality(mod, direct_vm):
    leader = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    validator = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "0.5"))
    assert leader != validator
    assert validator["final_verdict"] == "INCONCLUSIVE"


def test_dominance_nodes_agree_on_the_same_feeds(mod, direct_vm):
    moves = [("1.0", "1.1"), ("1.0", "1.2"), ("1.0", "2.0"), ("1.0", "1.05")]
    leader = collect_dominance(mod, direct_vm, moves)
    validator = collect_dominance(mod, direct_vm, moves)
    assert leader == validator
    assert leader["final_verdict"] == "WIN:ZAMA"


def test_dominance_disagreement_breaks_equality(mod, direct_vm):
    moves = [("1.0", "1.1"), ("1.0", "1.2"), ("1.0", "2.0"), ("1.0", "1.05")]
    other = [("1.0", "9.0"), ("1.0", "1.2"), ("1.0", "2.0"), ("1.0", "1.05")]
    leader = collect_dominance(mod, direct_vm, moves)
    validator = collect_dominance(mod, direct_vm, other)
    assert leader != validator
    assert leader["final_verdict"] == "WIN:ZAMA"
    assert validator["final_verdict"] == "WIN:ADA"


def test_payload_is_calldata_encodable(mod, direct_vm):
    """strict_eq requires the return value to survive calldata encoding."""
    from genlayer.py import calldata

    payload = collect_direction(mod, direct_vm, ("1.0", "2.0"), ("1.0", "2.0"))
    assert calldata.decode(calldata.encode(payload)) == payload


def test_failure_is_returned_as_data_not_raised(mod, direct_vm):
    """
    A raised error inside the sandbox is compared by message and is easy to make
    node-specific. Spike returns the failure as part of the payload instead, so
    every node produces a comparable value and the revert happens
    deterministically after consensus.
    """
    t0, t1 = day_window()
    direct_vm.clear_mocks()
    mock_crypto(direct_vm, "ADA", t0, t1, binance=("1.0", "2.0"), gate_status=429)
    payload = mod._collect("CRYPTO", "KIND_DIRECTION", ["ADA"], DAY, -1, t0, t1)
    assert payload["error"] == "TRANSIENT"
    assert "final_verdict" not in payload


# -- the payload invariant --------------------------------------------------


def test_a_single_source_can_never_settle(mod):
    """
    Exhaustive over the whole verdict vocabulary: unless the two sources match
    AND the shared verdict is a real one, the answer is INCONCLUSIVE.
    """
    vocab = ["UP", "DOWN", "TIE", "MISSING"] + ["WIN:" + a for a in ASSETS]
    settled = 0
    for a in vocab:
        for b in vocab:
            out = mod._final_verdict(a, b)
            if a != b:
                assert out == "INCONCLUSIVE", f"{a} vs {b} settled as {out}"
            elif a in ("TIE", "MISSING"):
                assert out == "INCONCLUSIVE"
            else:
                assert out == a
                settled += 1
    assert settled == 6  # UP, DOWN, and the four WIN:* values


def test_missing_never_settles_even_against_itself(mod):
    assert mod._final_verdict("MISSING", "MISSING") == "INCONCLUSIVE"
    assert mod._final_verdict("TIE", "TIE") == "INCONCLUSIVE"


def test_is_settling_matches_final_verdict(mod):
    for v in ["UP", "DOWN", "WIN:ADA", "WIN:COPPER"]:
        assert mod._is_settling(v) is True
    for v in ["TIE", "MISSING", "INCONCLUSIVE", ""]:
        assert mod._is_settling(v) is False


# -- the payload the validators compare -------------------------------------


def test_payload_carries_only_canonical_fields(spike, direct_vm):
    """Raw HTML and raw JSON must never reach storage."""
    import json as _json

    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    t0, t1 = day_window()
    direct_vm.warp(AFTER_CLOSE)
    mock_crypto(direct_vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    spike.resolve_market(mid)

    blob = _json.loads(spike.get_settlement_evidence(mid)["evidence"])
    assert set(blob) == {
        "kind", "category", "asset", "target_day", "target_hour", "assets",
        "source_a_id", "source_b_id", "source_a_verdict", "source_b_verdict",
        "source_a_prices", "source_b_prices", "final_verdict",
    }
    for v in blob["source_a_prices"] + blob["source_b_prices"]:
        assert isinstance(v, int)


def test_error_classification(mod):
    assert mod._classify_status(200) == ""
    for s in (408, 425, 429, 500, 502, 503, 0):
        assert mod._classify_status(s) == "TRANSIENT"
    for s in (400, 401, 403, 404, 418):
        assert mod._classify_status(s) == "EXTERNAL"
