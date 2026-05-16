"""Snapshot diff — week-over-week curator review.

A curator's weekly question is: *what changed about this vault's risk
profile since last week, and which detector(s) drove the change?*

This module pairs two `VaultSnapshot` instances (or two pre-computed
detector result sets) and produces a delta report. Used by:

  - `mvcf diff old.json new.json` (CLI)
  - The nightly snapshot pipeline (see `.github/workflows/live-snapshot.yml`)
  - Streamlit dashboard for inline trend visualization
"""

from __future__ import annotations

from dataclasses import dataclass

from .detectors import DetectorResult
from .runner import run_all_detectors
from .state import VaultSnapshot


@dataclass(frozen=True)
class DetectorDelta:
    """One detector's metric change between two snapshots."""

    name: str
    metric_old: float
    metric_new: float
    delta: float
    direction: str  # "up" / "down" / "flat"

    @property
    def pp_change(self) -> float:
        """Change in percentage points (× 100)."""
        return self.delta * 100


@dataclass(frozen=True)
class VaultDiff:
    """The full delta report between two vault snapshots."""

    vault_address: str
    block_old: int
    block_new: int
    deltas: list[DetectorDelta]
    total_assets_old: int
    total_assets_new: int
    n_markets_old: int
    n_markets_new: int
    n_borrowers_old: int
    n_borrowers_new: int

    @property
    def total_assets_pct_change(self) -> float:
        if self.total_assets_old == 0:
            return 0.0
        return (self.total_assets_new - self.total_assets_old) / self.total_assets_old

    def biggest_movers(self, n: int = 3) -> list[DetectorDelta]:
        """Top N detectors ranked by |delta|, descending."""
        return sorted(self.deltas, key=lambda d: abs(d.delta), reverse=True)[:n]


def diff_snapshots(
    old: VaultSnapshot,
    new: VaultSnapshot,
    old_results: list[DetectorResult] | None = None,
    new_results: list[DetectorResult] | None = None,
) -> VaultDiff:
    """Compute the delta between two vault snapshots.

    Args:
        old, new: the two snapshots to compare.
        old_results, new_results: optional pre-computed detector outputs.
            Passing them avoids re-running the detectors twice when the
            caller already has them (e.g., the Streamlit dashboard).

    Returns:
        A `VaultDiff` with per-detector deltas + vault-level changes.
    """
    if old.vault_address.lower() != new.vault_address.lower():
        raise ValueError(
            f"Cannot diff snapshots of different vaults: {old.vault_address} vs {new.vault_address}"
        )

    if old_results is None:
        old_results = run_all_detectors(old)
    if new_results is None:
        new_results = run_all_detectors(new)

    old_by_name = {r.name: r for r in old_results}
    new_by_name = {r.name: r for r in new_results}

    deltas: list[DetectorDelta] = []
    for name in old_by_name:
        if name not in new_by_name:
            continue
        m_old = old_by_name[name].headline_metric
        m_new = new_by_name[name].headline_metric
        delta = m_new - m_old
        direction = "flat" if abs(delta) < 1e-6 else ("up" if delta > 0 else "down")
        deltas.append(
            DetectorDelta(
                name=name,
                metric_old=m_old,
                metric_new=m_new,
                delta=delta,
                direction=direction,
            )
        )

    return VaultDiff(
        vault_address=new.vault_address,
        block_old=old.block,
        block_new=new.block,
        deltas=deltas,
        total_assets_old=old.total_assets,
        total_assets_new=new.total_assets,
        n_markets_old=len(old.markets),
        n_markets_new=len(new.markets),
        n_borrowers_old=len(old.borrowers),
        n_borrowers_new=len(new.borrowers),
    )


def summarize_diff(diff: VaultDiff) -> str:
    """Plain-text rendering of a vault diff — week-over-week curator brief."""
    lines = [
        "── Vault diff ──",
        f"Vault:   {diff.vault_address}",
        f"Blocks:  {diff.block_old:,} → {diff.block_new:,}",
        f"Assets:  {diff.total_assets_old:,} → {diff.total_assets_new:,} "
        f"({diff.total_assets_pct_change:+.1%})",
        f"Markets: {diff.n_markets_old} → {diff.n_markets_new}",
        f"Borrowers: {diff.n_borrowers_old} → {diff.n_borrowers_new}",
        "",
        "Detector deltas (sorted by absolute change):",
        "",
    ]
    arrow = {"up": "▲", "down": "▼", "flat": "·"}
    for d in sorted(diff.deltas, key=lambda x: abs(x.delta), reverse=True):
        lines.append(
            f"  {arrow[d.direction]} {d.name:<24} "
            f"{d.metric_old:>6.1%} → {d.metric_new:>6.1%}  "
            f"({d.pp_change:+5.1f} pp)"
        )
    lines.append("")
    movers = diff.biggest_movers(3)
    if movers and abs(movers[0].delta) > 0.05:
        lines.append("Top movers (≥ 5 pp change):")
        for m in movers:
            if abs(m.delta) >= 0.05:
                lines.append(f"  → {m.name}: {m.pp_change:+.1f} pp ({m.direction})")
    else:
        lines.append("No detector moved more than 5 pp — vault risk profile stable.")
    return "\n".join(lines)
