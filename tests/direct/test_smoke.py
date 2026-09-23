"""Smoke test: the contract loads, deploys, and answers a view."""

CONTRACT = "contracts/Spike.py"


def test_deploys_and_reports_universe(direct_vm, direct_deploy):
    direct_vm.warp("2026-09-23T12:00:00Z")
    c = direct_deploy(CONTRACT)

    u = c.get_supported_universe()
    assert u["assets"]["CRYPTO"] == ["ADA", "ZEC", "ZAMA", "ARB"]
    assert u["assets"]["COMMODITIES"] == ["GOLD", "SILVER", "WTI", "COPPER"]
    assert u["min_stake_wei"] == str(10**18)
    assert u["max_stake_wei"] == str(5 * 10**18)
    assert u["hourly_categories"] == ["CRYPTO"]


def test_stats_start_empty(direct_vm, direct_deploy):
    direct_vm.warp("2026-09-23T12:00:00Z")
    c = direct_deploy(CONTRACT)
    s = c.get_stats()
    assert s["markets"] == 0
    assert s["total_staked_wei"] == "0"
