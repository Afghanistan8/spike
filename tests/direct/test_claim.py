"""claim: winners split the whole pool pro-rata, refunds return the exact stake."""

from conftest import ONE_GEN, mock_crypto, stake, window_utc

DAY = "2026-10-15"
AFTER_CLOSE = "2026-10-16T01:00:00Z"
AFTER_TERMINAL = "2026-10-22T00:00:00Z"


def settled(spike, vm, gate, binance):
    """Create a direction market, stake nothing yet, and return (mid, t0, t1)."""
    mid = spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)
    t0, t1 = window_utc("CRYPTO", "KIND_DIRECTION", DAY, -1)
    return mid, t0, t1


def resolve_up(spike, vm, mid, t0, t1):
    vm.warp(AFTER_CLOSE)
    mock_crypto(vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "2.0"))
    return spike.resolve_market(mid)


def resolve_inconclusive(spike, vm, mid, t0, t1):
    vm.warp(AFTER_CLOSE)
    mock_crypto(vm, "ADA", t0, t1, gate=("1.0", "2.0"), binance=("1.0", "0.5"))
    return spike.resolve_market(mid)


# -- winner math ------------------------------------------------------------


def test_winners_split_the_whole_pool(spike, direct_vm, direct_alice, direct_bob,
                                      direct_charlie, transfers):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", 1 * ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_bob)
    stake(direct_vm, spike, mid, "DOWN", 3 * ONE_GEN, direct_charlie)
    assert resolve_up(spike, direct_vm, mid, t0, t1) == "UP"

    # pool 6 GEN, winning side 3 GEN -> each winner doubles
    assert spike.get_claimable(mid, direct_alice.as_hex) == str(2 * ONE_GEN)
    assert spike.get_claimable(mid, direct_bob.as_hex) == str(4 * ONE_GEN)
    assert spike.get_claimable(mid, direct_charlie.as_hex) == "0"

    with direct_vm.prank(direct_alice):
        assert spike.claim(mid) == "CLAIMED:%d" % (2 * ONE_GEN)
    with direct_vm.prank(direct_bob):
        assert spike.claim(mid) == "CLAIMED:%d" % (4 * ONE_GEN)

    assert transfers.total_to(direct_alice) == 2 * ONE_GEN
    assert transfers.total_to(direct_bob) == 4 * ONE_GEN


def test_floor_division_leaves_dust_in_the_contract(spike, direct_vm, direct_alice,
                                                    direct_bob, direct_charlie):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", 1 * ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_bob)
    stake(direct_vm, spike, mid, "DOWN", 1 * ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)

    # pool 4 GEN, winning side 3 GEN
    a = int(spike.get_claimable(mid, direct_alice.as_hex))
    b = int(spike.get_claimable(mid, direct_bob.as_hex))
    assert a == 1 * ONE_GEN * 4 * ONE_GEN // (3 * ONE_GEN)
    assert b == 2 * ONE_GEN * 4 * ONE_GEN // (3 * ONE_GEN)
    # never over-pays: the sum is at most the pool, and the remainder stays put
    assert a + b <= 4 * ONE_GEN
    assert 4 * ONE_GEN - (a + b) == 1


def test_loser_cannot_claim(spike, direct_vm, direct_alice, direct_charlie):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)

    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("EXPECTED:"):
            spike.claim(mid)


def test_sole_winner_takes_the_pool(spike, direct_vm, direct_alice, direct_charlie):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", 3 * ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)
    assert spike.get_claimable(mid, direct_alice.as_hex) == str(5 * ONE_GEN)


def test_nobody_on_the_winning_side_refunds_everyone(spike, direct_vm, direct_charlie):
    """Stakes are never burned just because the winning side was empty."""
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "DOWN", 3 * ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)

    assert spike.get_settlement_evidence(mid)["refund_all"] is True
    assert spike.get_claimable(mid, direct_charlie.as_hex) == str(3 * ONE_GEN)


# -- refund math ------------------------------------------------------------


def test_inconclusive_refunds_exact_stakes(spike, direct_vm, direct_alice,
                                           direct_charlie, transfers):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", 1 * ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", 4 * ONE_GEN, direct_charlie)
    assert resolve_inconclusive(spike, direct_vm, mid, t0, t1) == "INCONCLUSIVE"

    assert spike.get_claimable(mid, direct_alice.as_hex) == str(1 * ONE_GEN)
    assert spike.get_claimable(mid, direct_charlie.as_hex) == str(4 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        spike.claim(mid)
    with direct_vm.prank(direct_charlie):
        spike.claim(mid)
    assert transfers.total_to(direct_alice) == 1 * ONE_GEN
    assert transfers.total_to(direct_charlie) == 4 * ONE_GEN


def test_terminal_refund_is_claimable(spike, direct_vm, direct_alice, transfers):
    mid, _, _ = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_alice)
    direct_vm.warp(AFTER_TERMINAL)
    spike.resolve_market(mid)

    with direct_vm.prank(direct_alice):
        spike.claim(mid)
    assert transfers.total_to(direct_alice) == 2 * ONE_GEN


# -- guards -----------------------------------------------------------------


def test_double_claim_rejected(spike, direct_vm, direct_alice, direct_charlie, transfers):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)

    with direct_vm.prank(direct_alice):
        spike.claim(mid)
    paid_once = transfers.total_to(direct_alice)

    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("EXPECTED:"):
            spike.claim(mid)
    assert transfers.total_to(direct_alice) == paid_once


def test_claim_before_resolve_rejected(spike, direct_vm, direct_alice):
    mid, _, _ = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("EXPECTED:"):
            spike.claim(mid)


def test_claim_without_a_position_rejected(spike, direct_vm, direct_alice, direct_bob):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    resolve_up(spike, direct_vm, mid, t0, t1)
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("EXPECTED:"):
            spike.claim(mid)


def test_claim_unknown_market_rejected(spike, direct_vm):
    with direct_vm.expect_revert("EXPECTED:"):
        spike.claim("999")


def test_position_reports_claimed(spike, direct_vm, direct_alice, direct_charlie):
    mid, t0, t1 = settled(spike, direct_vm, None, None)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "DOWN", ONE_GEN, direct_charlie)
    resolve_up(spike, direct_vm, mid, t0, t1)
    with direct_vm.prank(direct_alice):
        spike.claim(mid)

    pos = spike.get_position(mid, direct_alice.as_hex)
    assert pos["claimed"] is True
    assert pos["claimable_wei"] == "0"


def test_dominance_winner_payout(spike, direct_vm, direct_alice, direct_bob):
    mid = spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)
    t0, t1 = window_utc("CRYPTO", "KIND_DOMINANCE", DAY, 14)
    stake(direct_vm, spike, mid, "ZAMA", 2 * ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "ADA", 3 * ONE_GEN, direct_bob)

    direct_vm.warp(AFTER_CLOSE)
    moves = [("1.0", "1.1"), ("1.0", "1.2"), ("1.0", "2.0"), ("1.0", "1.05")]
    for i, asset in enumerate(["ADA", "ZEC", "ZAMA", "ARB"]):
        mock_crypto(direct_vm, asset, t0, t1, gate=moves[i], binance=moves[i])
    assert spike.resolve_market(mid) == "WIN:ZAMA"

    assert spike.get_claimable(mid, direct_alice.as_hex) == str(5 * ONE_GEN)
    assert spike.get_claimable(mid, direct_bob.as_hex) == "0"
