"""Test the CLI entry point and the markdown / JSON report generators."""

from __future__ import annotations

import json

import pytest

from mvcf import as_json, as_markdown, load_fixture, run_all_detectors, summarize
from mvcf.__main__ import build_parser, main


@pytest.fixture(scope="module")
def snap():
    return load_fixture("steakhouse_usdc_snapshot_demo")


@pytest.fixture(scope="module")
def results(snap):
    return run_all_detectors(snap)


# ──────────────────────────────────────────────────────────────────────
# Report module
# ──────────────────────────────────────────────────────────────────────


def test_summarize_text_includes_all_detectors(results):
    out = summarize(results)
    for r in results:
        assert r.name in out
        assert r.headline_unit in out


def test_json_report_is_valid_json(snap, results):
    out = as_json(snap, results)
    payload = json.loads(out)
    assert payload["vault_address"] == snap.vault_address
    assert payload["block"] == snap.block
    assert len(payload["detectors"]) == 6
    for d in payload["detectors"]:
        assert "headline_metric" in d
        assert "interpretation" in d


def test_markdown_report_well_formed(snap, results):
    md = as_markdown(snap, results)
    assert md.startswith("# Vault risk brief")
    assert "## Headline counterfactual risk" in md
    assert "## Per-detector findings" in md
    assert "## Suggested curator actions" in md
    # Each detector should be a level-3 heading
    for r in results:
        assert f"### {r.name}" in md


def test_distressed_fixture_loads():
    """Edge-case fixture: single-market hot vault."""
    snap = load_fixture("distressed_single_market_demo")
    assert len(snap.markets) == 1
    assert snap.top1_share > 0.5  # top depositor > 50%
    assert snap.markets[0].utilization > 0.95


def test_distressed_fixture_triggers_alarms():
    """The distressed fixture must light up multiple detectors."""
    snap = load_fixture("distressed_single_market_demo")
    results = run_all_detectors(snap)
    by_name = {r.name: r for r in results}
    # Utilization should be flagged (single market over 95%)
    assert by_name["UtilizationInversion"].headline_metric > 0.0
    # LTV distribution should show concentration near LLTV
    assert by_name["LTVDistributionStress"].headline_metric > 0.0


# ──────────────────────────────────────────────────────────────────────
# CLI surface
# ──────────────────────────────────────────────────────────────────────


def test_cli_parser_has_subcommands():
    p = build_parser()
    # Smoke: parsing without args should fail (subcommand required)
    with pytest.raises(SystemExit):
        p.parse_args([])


def test_cli_analyze_fixture_text_format(capsys):
    rc = main(["analyze", "--fixture", "steakhouse_usdc_snapshot_demo", "--format", "text"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OracleFreezeReplay" in out
    assert "CollateralCascade" in out


def test_cli_analyze_fixture_json_format(capsys):
    rc = main(["analyze", "--fixture", "steakhouse_usdc_snapshot_demo", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["n_markets"] == 5


def test_cli_analyze_fixture_markdown_format(capsys):
    rc = main(["analyze", "--fixture", "steakhouse_usdc_snapshot_demo", "--format", "markdown"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("# Vault risk brief")


def test_cli_analyze_rejects_both_vault_and_fixture(capsys):
    rc = main(["analyze", "--vault", "0xABC", "--fixture", "steakhouse_usdc_snapshot_demo"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_cli_analyze_rejects_neither_vault_nor_fixture(capsys):
    rc = main(["analyze"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "either" in err


def test_cli_sweep_collateral(capsys):
    # Use `=` syntax so argparse doesn't treat the leading `-` as a flag
    rc = main([
        "sweep", "collateral",
        "--fixture", "steakhouse_usdc_snapshot_demo",
        "--shocks=-0.05,-0.20,-0.50",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Collateral cascade sweep" in out
    assert "-5%" in out
    assert "-50%" in out


def test_cli_sweep_oracle(capsys):
    rc = main([
        "sweep", "oracle",
        "--fixture", "steakhouse_usdc_snapshot_demo",
        "--shocks=-0.05,-0.20",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Oracle freeze sweep" in out


def test_cli_writes_output_file(tmp_path, capsys):
    out_file = tmp_path / "brief.md"
    rc = main([
        "analyze", "--fixture", "steakhouse_usdc_snapshot_demo",
        "--format", "markdown", "--output", str(out_file),
    ])
    assert rc == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "# Vault risk brief" in content
