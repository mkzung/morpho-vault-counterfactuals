"""Test the six counterfactual detectors.

These tests run fully offline against the checked-in fixture, and assert
both correctness (known-good outputs) and adversarial inputs (extreme
parameters do not crash).
"""

import pytest

from mvcf.detectors import (
    CollateralCascade,
    DepositorExitShock,
    LiquidationLatency,
    LTVDistributionStress,
    OracleFreezeReplay,
    UtilizationInversion,
)
from mvcf.fetch import load_fixture
from mvcf.runner import run_all_detectors


@pytest.fixture(scope="module")
def snap():
    return load_fixture("steakhouse_usdc_snapshot_demo")


def test_fixture_loads_clean(snap):
    """Bedrock invariant: the demo fixture is well-formed."""
    assert snap.total_assets > 0
    assert snap.total_shares > 0
    assert len(snap.markets) == 5
    assert len(snap.borrowers) >= 5


def test_oracle_freeze_returns_bounded_fraction(snap):
    """Headline metric is always a valid fraction in [0,1]."""
    res = OracleFreezeReplay(drift_pct=-0.10).run(snap)
    assert res.headline_unit == "fraction_bad_debt"
    assert 0.0 <= res.headline_metric <= 1.0
    assert res.evidence["drift_pct"] == -0.10


def test_oracle_freeze_monotone_in_drift(snap):
    """Larger collateral drift ⟹ more bad debt (or at least non-decreasing)."""
    light = OracleFreezeReplay(drift_pct=-0.05).run(snap).headline_metric
    heavy = OracleFreezeReplay(drift_pct=-0.30).run(snap).headline_metric
    assert heavy >= light


def test_oracle_freeze_rejects_bad_drift():
    with pytest.raises(ValueError):
        OracleFreezeReplay(drift_pct=2.0)
    with pytest.raises(ValueError):
        OracleFreezeReplay(drift_pct=-1.5)


def test_collateral_cascade_monotone(snap):
    """Deeper shock ⟹ more liquidatable debt."""
    mild = CollateralCascade(shock_pct=-0.05).run(snap).headline_metric
    severe = CollateralCascade(shock_pct=-0.50).run(snap).headline_metric
    assert severe >= mild


def test_collateral_cascade_rejects_positive_shock():
    """The cascade is a downside scenario; positive shocks are nonsensical."""
    with pytest.raises(ValueError):
        CollateralCascade(shock_pct=0.05)


def test_depositor_exit_rationing_fraction_in_unit(snap):
    res = DepositorExitShock(top_n=1).run(snap)
    assert 0.0 <= res.headline_metric <= 1.0
    assert res.headline_unit == "fraction_rationed"


def test_depositor_exit_top_n_must_be_positive():
    with pytest.raises(ValueError):
        DepositorExitShock(top_n=0)


def test_utilization_inversion_bounded(snap):
    res = UtilizationInversion(target_util_max=0.92).run(snap)
    assert 0.0 <= res.headline_metric <= 1.0


def test_utilization_inversion_rejects_bad_band():
    with pytest.raises(ValueError):
        UtilizationInversion(target_util_max=1.5)


def test_liquidation_latency_runs(snap):
    res = LiquidationLatency(gas_price_gwei=50, eth_price_usd=3500).run(snap)
    assert 0.0 <= res.headline_metric <= 1.0
    assert "cost_per_liquidation_usd" in res.evidence
    # Sanity: at 50 gwei × 350k gas × $3500/ETH, cost should be ~$61
    assert 20 < res.evidence["cost_per_liquidation_usd"] < 150


def test_ltv_distribution_finds_near_lltv_positions(snap):
    """The fixture deliberately includes one ezETH/USDC position underwater -
    detector should report some debt within 5pp of LLTV."""
    res = LTVDistributionStress().run(snap)
    assert res.headline_metric > 0.0


def test_run_all_returns_six_results(snap):
    """Acceptance test: orchestrator wires up all six detectors with sane defaults."""
    results = run_all_detectors(snap)
    assert len(results) == 6
    names = [r.name for r in results]
    assert set(names) == {
        "OracleFreezeReplay",
        "CollateralCascade",
        "DepositorExitShock",
        "UtilizationInversion",
        "LiquidationLatency",
        "LTVDistributionStress",
    }
    # All metrics finite, no NaN slip-through
    for r in results:
        assert r.headline_metric == r.headline_metric  # NaN check
        assert isinstance(r.interpretation, str)
        assert len(r.interpretation) > 20  # Non-trivial copy
