"""Test the domain models — invariants on VaultSnapshot / MarketState / BorrowerPosition."""

import pytest
from pydantic import ValidationError

from mvcf.state import BorrowerPosition, MarketState, VaultHistory, VaultSnapshot


def make_market(**overrides) -> MarketState:
    defaults = dict(
        market_id="0xabc",
        block=1,
        timestamp=1000,
        collateral_token="0xC",
        loan_token="0xL",
        total_supply_assets=1_000_000_000,
        total_borrow_assets=500_000_000,
        total_collateral_assets=10**21,
        oracle_price_36dec=10**36,
        lltv_wad=860 * 10**15,
        supply_cap=2_000_000_000,
    )
    defaults.update(overrides)
    return MarketState(**defaults)


def test_market_utilization_half():
    m = make_market(total_supply_assets=100, total_borrow_assets=50)
    assert m.utilization == 0.5


def test_market_utilization_capped_at_one():
    # Defensive: shouldn't happen on-chain (borrow ≤ supply by protocol invariant),
    # but the model should not panic if it does.
    m = make_market(total_supply_assets=100, total_borrow_assets=150)
    assert m.utilization == 1.0


def test_market_utilization_zero_supply():
    m = make_market(total_supply_assets=0, total_borrow_assets=0)
    assert m.utilization == 0.0


def test_lltv_must_be_under_wad():
    with pytest.raises(ValidationError):
        make_market(lltv_wad=10**18)  # >= 1 is invalid


def test_oracle_price_must_be_positive():
    with pytest.raises(ValidationError):
        make_market(oracle_price_36dec=0)


def test_borrower_ltv_basic():
    # collateral = 1e18 (1 WETH), debt = 1000e6 USDC, oracle 3300 USDC/WETH
    pos = BorrowerPosition(
        market_id="0xabc",
        borrower="0xb1",
        collateral=10**18,
        debt_assets=1000 * 10**6,
    )
    # price encodes 3300 USDC per WETH at 36 + 6 - 18 = 24 decimals
    price = 3300 * 10**24
    ltv = pos.ltv(price)
    # 1000 USDC / 3300 USDC of collateral ≈ 0.303
    assert abs(ltv - 1000 / 3300) < 1e-6


def test_borrower_ltv_zero_collateral():
    pos = BorrowerPosition(market_id="x", borrower="y", collateral=0, debt_assets=100)
    assert pos.ltv(10**36) == 0.0


def test_vault_snapshot_hhi_concentrated():
    snap = VaultSnapshot(
        vault_address="0xv",
        block=1,
        timestamp=1,
        total_assets=100,
        total_shares=100,
        top_depositors=[("0xa", 90), ("0xb", 10)],
    )
    # Top depositor 0.9 → 0.81, second 0.1 → 0.01, total = 0.82
    assert abs(snap.hhi - 0.82) < 1e-6
    assert snap.top1_share == 0.9


def test_vault_snapshot_hhi_diversified():
    snap = VaultSnapshot(
        vault_address="0xv",
        block=1,
        timestamp=1,
        total_assets=100,
        total_shares=100,
        top_depositors=[("0xa", 10)] * 10,
    )
    # 10 equal depositors at 10% each: 10 * 0.01 = 0.1
    assert abs(snap.hhi - 0.1) < 1e-6


def test_vault_history_latest():
    s1 = VaultSnapshot(
        vault_address="0xv",
        block=1,
        timestamp=1,
        total_assets=100,
        total_shares=100,
    )
    s2 = VaultSnapshot(
        vault_address="0xv",
        block=2,
        timestamp=2,
        total_assets=200,
        total_shares=200,
    )
    h = VaultHistory(vault_address="0xv", snapshots=[s2, s1])
    assert h.latest().block == 2
    assert h.by_block(1) is s1
    assert h.by_block(99) is None


def test_vault_history_empty_raises():
    h = VaultHistory(vault_address="0xv", snapshots=[])
    with pytest.raises(ValueError):
        h.latest()
