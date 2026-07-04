"""Run all detectors on a snapshot and produce a summary report."""

from __future__ import annotations

from .detectors import (
    CollateralCascade,
    DepositorExitShock,
    DetectorResult,
    LiquidationLatency,
    LTVDistributionStress,
    OracleFreezeReplay,
    UtilizationInversion,
)
from .state import VaultSnapshot


def run_all_detectors(
    snapshot: VaultSnapshot,
    *,
    oracle_drift: float = -0.10,
    collateral_shock: float = -0.20,
    top_n_exit: int = 1,
    util_band: float = 0.92,
    gas_gwei: float = 30.0,
) -> list[DetectorResult]:
    """Run the six counterfactual detectors with default Re7-style parameters."""
    return [
        OracleFreezeReplay(drift_pct=oracle_drift).run(snapshot),
        CollateralCascade(shock_pct=collateral_shock).run(snapshot),
        DepositorExitShock(top_n=top_n_exit).run(snapshot),
        UtilizationInversion(target_util_max=util_band).run(snapshot),
        LiquidationLatency(gas_price_gwei=gas_gwei).run(snapshot),
        LTVDistributionStress().run(snapshot),
    ]


def summarize(results: list[DetectorResult]) -> str:
    """Plain-text summary of detector results - for CLI / curator handoff."""
    lines = ["=== Vault counterfactual risk summary ===", ""]
    for r in results:
        lines.append(f"[{r.name}]  {r.headline_metric:.3f} {r.headline_unit}")
        lines.append(f"  -> {r.interpretation}")
        lines.append("")
    return "\n".join(lines)
