"""
take_position: the critical money rule.

GEN attached to a call is credited to the contract even if the call reverts.
So once value is attached this method must never revert - it either records the
stake or sends the GEN back. Every rejection test below asserts BOTH that the
call returned REFUNDED: and that the wei actually left the contract again.
"""

from conftest import ONE_GEN, stake

DAY = "2026-10-15"


def open_market(spike):
    return spike.create_market("KIND_DIRECTION", "CRYPTO", "ADA", DAY, -1)


def dominance_market(spike):
    return spike.create_market("KIND_DOMINANCE", "CRYPTO", "", DAY, 14)


# -- accepted amounts -------------------------------------------------------


def test_one_gen_accepted(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    assert stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice) == "STAKED:%d" % ONE_GEN
    assert transfers == []
    assert spike.get_market(mid)["pools"]["UP"] == str(ONE_GEN)


def test_five_gen_accepted(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    amt = 5 * ONE_GEN
    assert stake(direct_vm, spike, mid, "DOWN", amt, direct_alice) == "STAKED:%d" % amt
    assert transfers == []


def test_dominance_side_is_an_asset(spike, direct_vm, direct_alice):
    mid = dominance_market(spike)
    assert stake(direct_vm, spike, mid, "ZAMA", ONE_GEN, direct_alice).startswith("STAKED:")
    assert spike.get_market(mid)["pools"]["ZAMA"] == str(ONE_GEN)


# -- refused amounts, refunded not reverted ---------------------------------


def test_half_gen_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    out = stake(direct_vm, spike, mid, "UP", ONE_GEN // 2, direct_alice)
    assert out.startswith("REFUNDED:")
    assert "1 GEN" in out
    assert transfers.total_to(direct_alice) == ONE_GEN // 2
    assert spike.get_market(mid)["pools"]["UP"] == "0"


def test_six_gen_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    out = stake(direct_vm, spike, mid, "UP", 6 * ONE_GEN, direct_alice)
    assert out.startswith("REFUNDED:")
    assert transfers.total_to(direct_alice) == 6 * ONE_GEN
    assert spike.get_stats()["total_staked_wei"] == "0"


def test_zero_value_reverts_normally(spike, direct_vm):
    """Nothing was attached, so there is nothing to lose by reverting."""
    mid = open_market(spike)
    with direct_vm.expect_revert("EXPECTED:"):
        spike.take_position(mid, "UP")


def test_unknown_market_refunded(spike, direct_vm, direct_alice, transfers):
    out = stake(direct_vm, spike, "999", "UP", ONE_GEN, direct_alice)
    assert out == "REFUNDED:unknown market"
    assert transfers.total_to(direct_alice) == ONE_GEN


def test_invalid_side_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    out = stake(direct_vm, spike, mid, "SIDEWAYS", ONE_GEN, direct_alice)
    assert out == "REFUNDED:invalid side"
    assert transfers.total_to(direct_alice) == ONE_GEN


def test_wrong_asset_side_on_dominance_refunded(spike, direct_vm, direct_alice, transfers):
    mid = dominance_market(spike)
    out = stake(direct_vm, spike, mid, "GOLD", ONE_GEN, direct_alice)
    assert out == "REFUNDED:invalid side"
    assert transfers.total_to(direct_alice) == ONE_GEN


# -- top-ups and side switching ---------------------------------------------


def test_top_up_same_side_accumulates(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    out = stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_alice)
    assert out == "STAKED:%d" % (3 * ONE_GEN)
    assert transfers == []
    assert spike.get_position(mid, direct_alice.as_hex)["amount_wei"] == str(3 * ONE_GEN)


def test_top_up_may_be_below_the_minimum(spike, direct_vm, direct_alice):
    """The 1 GEN floor applies to opening a position, not to adding to one."""
    mid = open_market(spike)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    out = stake(direct_vm, spike, mid, "UP", ONE_GEN // 10, direct_alice)
    assert out == "STAKED:%d" % (ONE_GEN + ONE_GEN // 10)


def test_top_up_over_five_gen_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    stake(direct_vm, spike, mid, "UP", 4 * ONE_GEN, direct_alice)
    out = stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_alice)
    assert out.startswith("REFUNDED:")
    assert transfers.total_to(direct_alice) == 2 * ONE_GEN
    assert spike.get_position(mid, direct_alice.as_hex)["amount_wei"] == str(4 * ONE_GEN)


def test_side_switch_refunded_not_reverted(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    out = stake(direct_vm, spike, mid, "DOWN", ONE_GEN, direct_alice)
    assert out == "REFUNDED:side switch not allowed"
    assert transfers.total_to(direct_alice) == ONE_GEN
    pos = spike.get_position(mid, direct_alice.as_hex)
    assert pos["side"] == "UP"
    assert pos["amount_wei"] == str(ONE_GEN)
    assert spike.get_market(mid)["pools"]["DOWN"] == "0"


# -- phase gating -----------------------------------------------------------


def test_stake_after_cutoff_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    direct_vm.warp("2026-10-15T09:00:00Z")  # window is live, betting closed
    assert spike.get_market_phase(mid) == "WINDOW_LIVE"
    out = stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    assert out == "REFUNDED:market not open"
    assert transfers.total_to(direct_alice) == ONE_GEN


def test_stake_after_window_closed_refunded(spike, direct_vm, direct_alice, transfers):
    mid = open_market(spike)
    direct_vm.warp("2026-10-17T00:00:00Z")
    assert spike.get_market_phase(mid) == "READY_TO_SETTLE"
    out = stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    assert out == "REFUNDED:market not open"
    assert transfers.total_to(direct_alice) == ONE_GEN


# -- multiple stakers -------------------------------------------------------


def test_pools_track_each_side(spike, direct_vm, direct_alice, direct_bob, direct_charlie):
    mid = open_market(spike)
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_bob)
    stake(direct_vm, spike, mid, "DOWN", 3 * ONE_GEN, direct_charlie)

    m = spike.get_market(mid)
    assert m["pools"]["UP"] == str(3 * ONE_GEN)
    assert m["pools"]["DOWN"] == str(3 * ONE_GEN)
    assert m["total_pool"] == str(6 * ONE_GEN)
    assert spike.get_market_positions(mid, 0, 50)["total"] == 3


def test_user_positions_are_indexed(spike, direct_vm, direct_alice):
    a = open_market(spike)
    b = spike.create_market("KIND_DIRECTION", "CRYPTO", "ZEC", DAY, -1)
    stake(direct_vm, spike, a, "UP", ONE_GEN, direct_alice)
    stake(direct_vm, spike, b, "DOWN", ONE_GEN, direct_alice)
    got = spike.get_user_positions(direct_alice.as_hex, 0, 50)
    assert got["total"] == 2
    assert {p["market_id"] for p in got["items"]} == {a, b}


# -- no rejection path can trap GEN -----------------------------------------


def test_no_rejection_path_traps_gen(spike, direct_vm, direct_alice, direct_bob, transfers):
    """
    Every way a stake can be refused must leave the staker whole.

    Value attached to a call is credited to the contract even when the call
    reverts, so a refusal that neither records a position nor returns the GEN
    would silently swallow it. This walks all three refusal reasons and asserts
    the contract gave back exactly what it was sent, every time.
    """
    mid = open_market(spike)

    sent = 0
    # 1. below the minimum, with no position yet
    stake(direct_vm, spike, mid, "UP", ONE_GEN // 2, direct_alice)
    sent += ONE_GEN // 2
    assert transfers.total_to(direct_alice) == sent

    # 2. above the cap
    stake(direct_vm, spike, mid, "UP", 6 * ONE_GEN, direct_alice)
    sent += 6 * ONE_GEN
    assert transfers.total_to(direct_alice) == sent

    # now hold a real position so the side-switch and top-up rules can bite
    stake(direct_vm, spike, mid, "UP", 4 * ONE_GEN, direct_alice)
    assert transfers.total_to(direct_alice) == sent  # accepted, nothing returned

    # 3. side switch
    stake(direct_vm, spike, mid, "DOWN", ONE_GEN, direct_alice)
    sent += ONE_GEN
    assert transfers.total_to(direct_alice) == sent

    # 4. top-up that would breach the cap
    stake(direct_vm, spike, mid, "UP", 2 * ONE_GEN, direct_alice)
    sent += 2 * ONE_GEN
    assert transfers.total_to(direct_alice) == sent

    # 5. after the betting cutoff
    direct_vm.warp("2026-10-15T09:00:00Z")
    stake(direct_vm, spike, mid, "UP", ONE_GEN, direct_bob)
    assert transfers.total_to(direct_bob) == ONE_GEN

    # the only GEN the contract kept is the one stake it actually accepted
    assert spike.get_stats()["total_staked_wei"] == str(4 * ONE_GEN)
    assert spike.get_position(mid, direct_alice.as_hex)["amount_wei"] == str(4 * ONE_GEN)
    assert spike.get_position(mid, direct_bob.as_hex) == {}


def test_rejected_stake_is_recoverable_even_if_transfer_is_deferred(
    spike, direct_vm, direct_alice, transfers
):
    """
    The refund is emitted, not pushed synchronously.

    Outbound transfers execute on finality, so what the contract owes must be
    fully described by the emitted message - there is no second chance to
    re-derive it later. Assert the emitted value matches the attached value
    exactly, for the exact wallet that sent it.
    """
    mid = open_market(spike)
    out = stake(direct_vm, spike, mid, "SIDEWAYS", 3 * ONE_GEN, direct_alice)

    assert out.startswith("REFUNDED:")
    assert len(transfers) == 1
    recipient, amount = transfers[0]
    assert recipient == direct_alice.as_hex
    assert amount == 3 * ONE_GEN
