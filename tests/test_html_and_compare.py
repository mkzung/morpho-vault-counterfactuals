"""Tests for the HTML report generator and the multi-vault compare command."""

from __future__ import annotations

import pytest

from mvcf import as_html, load_fixture, run_all_detectors
from mvcf.__main__ import main


@pytest.fixture(scope="module")
def snap():
    return load_fixture("steakhouse_usdc_snapshot_demo")


def test_html_report_is_valid_html(snap):
    out = as_html(snap)
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out
    assert "Chart" in out  # Chart.js is loaded
    # Each detector should appear as a card
    for det in [
        "OracleFreezeReplay",
        "CollateralCascade",
        "DepositorExitShock",
        "UtilizationInversion",
        "LiquidationLatency",
        "LTVDistributionStress",
    ]:
        assert det in out


def test_html_report_with_precomputed_results(snap):
    results = run_all_detectors(snap)
    out = as_html(snap, results)
    assert "Vault risk brief" in out
    # The four chart canvases should exist
    for chart_id in ("cascadeChart", "oracleChart", "ltvChart", "gasChart"):
        assert f'id="{chart_id}"' in out


def test_html_report_traffic_light_colors_present(snap):
    """The severity coloring is the curator-facing UX feature — must not regress."""
    out = as_html(snap)
    # Steakhouse demo has CRITICAL and OK detectors at default params → both colors must appear
    assert "#dc2626" in out  # CRITICAL red
    assert "#16a34a" in out  # OK green


def test_cli_compare_two_fixtures(capsys):
    rc = main(
        [
            "compare",
            "--fixtures",
            "steakhouse_usdc_snapshot_demo,distressed_single_market_demo",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Both vault addresses (shortened) should appear in the table header
    assert "0xBEEF" in out
    assert "0xDEAD" in out
    # All six detectors should be rows
    for det in [
        "OracleFreezeReplay",
        "CollateralCascade",
        "DepositorExitShock",
        "UtilizationInversion",
        "LiquidationLatency",
        "LTVDistributionStress",
    ]:
        assert det in out


def test_cli_compare_rejects_empty(capsys):
    rc = main(["compare"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "either" in err


def test_cli_analyze_html_writes_file(tmp_path):
    out_file = tmp_path / "report.html"
    rc = main(
        [
            "analyze",
            "--fixture",
            "steakhouse_usdc_snapshot_demo",
            "--format",
            "html",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    content = out_file.read_text()
    assert content.startswith("<!DOCTYPE html>")
    assert "Vault risk brief" in content
