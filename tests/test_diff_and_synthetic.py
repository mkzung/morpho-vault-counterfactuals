"""Tests for diff command, synthetic generator, and scaling behavior."""

from __future__ import annotations

import pytest

from mvcf import diff_snapshots, load_fixture, run_all_detectors, summarize_diff
from mvcf.__main__ import main
from mvcf.synthetic import generate_synthetic_vault

# ──────────────────────────────────────────────────────────────────────
# Diff module
# ──────────────────────────────────────────────────────────────────────


def test_diff_same_snapshot_is_flat():
    """Diffing a snapshot against itself produces all-zero deltas."""
    snap = load_fixture("steakhouse_usdc_snapshot_demo")
    diff = diff_snapshots(snap, snap)
    for d in diff.deltas:
        assert abs(d.delta) < 1e-12
        assert d.direction == "flat"
    assert diff.total_assets_pct_change == 0.0


def test_diff_different_vaults_raises():
    a = load_fixture("steakhouse_usdc_snapshot_demo")
    b = load_fixture("distressed_single_market_demo")
    with pytest.raises(ValueError, match="different vaults"):
        diff_snapshots(a, b)


def test_diff_biggest_movers_sorted():
    snap = load_fixture("steakhouse_usdc_snapshot_demo")
    # Mutate detector results synthetically to ensure ordering test
    new_results = run_all_detectors(snap)
    old_results = run_all_detectors(snap)
    # Manually alter one result to create a synthetic delta
    from dataclasses import replace

    new_results[0] = replace(new_results[0], headline_metric=new_results[0].headline_metric + 0.30)
    new_results[2] = replace(new_results[2], headline_metric=new_results[2].headline_metric + 0.05)
    diff = diff_snapshots(snap, snap, old_results=old_results, new_results=new_results)
    movers = diff.biggest_movers(2)
    assert abs(movers[0].delta) >= abs(movers[1].delta)


def test_diff_summarize_includes_arrows():
    snap = load_fixture("steakhouse_usdc_snapshot_demo")
    diff = diff_snapshots(snap, snap)
    out = summarize_diff(diff)
    assert "Vault diff" in out
    assert "stable" in out.lower() or "no detector" in out.lower()


def test_cli_diff_same_fixture(capsys):
    rc = main(["diff", "steakhouse_usdc_snapshot_demo", "steakhouse_usdc_snapshot_demo"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Vault diff" in out


# ──────────────────────────────────────────────────────────────────────
# Synthetic generator + scaling
# ──────────────────────────────────────────────────────────────────────


def test_synthetic_vault_basic():
    snap = generate_synthetic_vault(n_markets=3, n_borrowers=50)
    assert len(snap.markets) == 3
    assert len(snap.borrowers) <= 50  # Some may be filtered out (zero debt)
    assert snap.total_assets > 0
    # All detectors must run successfully
    results = run_all_detectors(snap)
    assert len(results) == 6
    for r in results:
        assert 0.0 <= r.headline_metric <= 1.0


def test_synthetic_vault_deterministic():
    """Same seed → bit-for-bit identical snapshot."""
    a = generate_synthetic_vault(n_markets=4, n_borrowers=100, seed=42)
    b = generate_synthetic_vault(n_markets=4, n_borrowers=100, seed=42)
    assert a.total_assets == b.total_assets
    assert len(a.borrowers) == len(b.borrowers)
    for ba, bb in zip(a.borrowers, b.borrowers, strict=True):
        assert ba.collateral == bb.collateral
        assert ba.debt_assets == bb.debt_assets


def test_synthetic_vault_scales_to_1000_borrowers():
    """Sanity check: detectors complete on a 1000-borrower vault in reasonable time."""
    import time

    snap = generate_synthetic_vault(n_markets=10, n_borrowers=1000, seed=7)
    t0 = time.perf_counter()
    results = run_all_detectors(snap)
    elapsed = time.perf_counter() - t0
    # 1000 borrowers × 10 markets × 6 detectors should comfortably run in < 1s
    assert elapsed < 1.0, f"1000-borrower run took {elapsed:.2f}s (target < 1s)"
    assert len(results) == 6
