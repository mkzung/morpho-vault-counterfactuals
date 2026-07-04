"""Report generators - curator handoff in JSON or Markdown.

A curator's actual workflow is: read the report, decide on (a) lower LLTV,
(b) reduce supply cap, (c) reallocate, or (d) raise alert thresholds. The
markdown report is built for that decision shape - headline metrics on top,
per-market evidence in a table, recommended action stub at the bottom.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .detectors import DetectorResult
from .state import VaultSnapshot


def humanize_amount(units: int, decimals: int, symbol: str = "") -> str:
    """Render a raw loan-unit integer as a human-readable amount.

    e.g. ``(95_340_290_886_683, 6, "USDC") -> "95.34M USDC"``. Falls back to
    the raw integer (with a ``units`` suffix) when decimals are unknown, so the
    output is never silently wrong for a non-6-decimal asset.
    """
    if decimals <= 0:
        return f"{units:,} units"
    value = units / 10**decimals
    suffix = f" {symbol}".rstrip()
    for threshold, tag in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            return f"{value / threshold:,.2f}{tag}{suffix}"
    return f"{value:,.2f}{suffix}"


def as_json(snapshot: VaultSnapshot, results: list[DetectorResult]) -> str:
    """Emit a single JSON blob of the snapshot + all detector results.

    Suitable for piping into downstream alerting (Datadog, OpsGenie,
    PagerDuty) or for batch comparison across multiple vaults.
    """
    market_borrow = sum(m.total_borrow_assets for m in snapshot.markets)
    borrower_debt = sum(b.debt_assets for b in snapshot.borrowers)
    payload = {
        "vault_address": snapshot.vault_address,
        "block": snapshot.block,
        "timestamp": snapshot.timestamp,
        "loan_symbol": snapshot.loan_symbol,
        "loan_decimals": snapshot.loan_decimals,
        "total_assets_loan_units": snapshot.total_assets,
        "total_assets_human": humanize_amount(
            snapshot.total_assets, snapshot.loan_decimals, snapshot.loan_symbol
        ),
        "hhi": snapshot.hhi,
        "top1_share": snapshot.top1_share,
        "n_markets": len(snapshot.markets),
        "n_borrowers": len(snapshot.borrowers),
        # fraction of open market debt captured by the fetched borrower sample
        "borrower_debt_coverage": (
            borrower_debt / market_borrow if market_borrow else None
        ),
        "detectors": [asdict(r) for r in results],
    }
    return json.dumps(payload, indent=2, default=str)


def as_markdown(snapshot: VaultSnapshot, results: list[DetectorResult]) -> str:
    """Render a curator-style markdown brief.

    Format follows the in-house brief shape used by Risk DAO, Block Analitica,
    and similar curators: headline grid, per-detector deep-dives, suggested
    next actions. Designed to be paste-ready into Slack/email/Notion.
    """
    lines: list[str] = []
    sym = snapshot.loan_symbol or "loan-asset"
    dec = snapshot.loan_decimals
    addr_short = snapshot.vault_address[:6] + "..." + snapshot.vault_address[-4:]
    lines.append(f"# Vault risk brief: `{addr_short}`")
    lines.append("")
    # Block is None / 0 when sourced from the Morpho Blue API (which does not
    # expose the indexer block); only fixtures pin to a real block.
    if snapshot.block:
        lines.append(f"- **Block:** {snapshot.block:,}")
    else:
        lines.append("- **Block:** n/a (Blue API response is not block-pinned)")
    lines.append(
        f"- **Total assets:** {humanize_amount(snapshot.total_assets, dec, sym)} "
        f"(`{snapshot.total_assets:,}` {sym} units)"
    )
    lines.append(f"- **Markets:** {len(snapshot.markets)}")
    if snapshot.borrowers:
        market_borrow = sum(m.total_borrow_assets for m in snapshot.markets)
        borrower_debt = sum(b.debt_assets for b in snapshot.borrowers)
        coverage = borrower_debt / market_borrow if market_borrow else 1.0
        # The Blue API returns at most 1000 positions per query; when we hit
        # that ceiling the sample is the largest-by-debt, so we report the debt
        # coverage to show how complete it is.
        capped = " (largest by debt; API max 1000/query)" if len(
            snapshot.borrowers
        ) >= 1000 else ""
        lines.append(
            f"- **Borrowers analyzed:** {len(snapshot.borrowers):,}{capped}, "
            f"covering {coverage:.1%} of the "
            f"{humanize_amount(market_borrow, dec, sym)} of open debt in the "
            "markets this vault lends into."
        )
        lines.append(
            "  Borrower positions are *market-wide*: a MetaMorpho vault supplies "
            "into shared Morpho Blue markets, so these are all borrowers of "
            "those markets, not only debt funded by this vault. That is why "
            "market debt can exceed the vault's own assets."
        )
    else:
        lines.append(
            "- **Borrowers analyzed:** 0 - no borrower positions were returned "
            "for this vault (position enrichment disabled, or the markets carry "
            "no open debt). Market-level detectors still run."
        )
    lines.append(
        f"- **HHI (depositor concentration):** `{snapshot.hhi:.3f}` "
        f"(top-1 = {snapshot.top1_share:.1%})"
    )
    lines.append("")

    # Headline table
    lines.append("## Headline counterfactual risk")
    lines.append("")
    lines.append("| Detector | Metric | Unit |")
    lines.append("|---|---:|---|")
    for r in results:
        lines.append(f"| `{r.name}` | `{r.headline_metric:.3f}` | {r.headline_unit} |")
    lines.append("")

    # Per-detector interpretation + evidence
    lines.append("## Per-detector findings")
    lines.append("")
    for r in results:
        lines.append(f"### {r.name}")
        lines.append("")
        lines.append(r.interpretation)
        lines.append("")
        # Compact evidence block (skip if empty)
        if r.evidence:
            lines.append("<details><summary>Evidence</summary>")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(r.evidence, indent=2, default=str))
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # Suggested next actions
    lines.append("## Suggested curator actions")
    lines.append("")
    lines.append(
        "- If `OracleFreezeReplay` headline > 5% - review oracle update cadence + "
        "consider Chainlink fallback or oracle-router timeout."
    )
    lines.append(
        "- If `CollateralCascade` headline > 30% at -20% shock - lower LLTV on the "
        "concentrated market(s) by 1-3 percentage points."
    )
    lines.append(
        "- If `DepositorExitShock` headline > 20% rationing - reduce vault-level "
        "supply cap to that market to free idle supply."
    )
    lines.append(
        "- If `UtilizationInversion` flags ≥ 50% of markets - raise IRM upper "
        "rate or reallocate via the MetaMorpho `reallocate()` flow."
    )
    lines.append(
        "- If `LiquidationLatency` headline > 5% - raise the minimum-position-size "
        "threshold (cap supply on markets where dust positions accumulate)."
    )
    lines.append(
        "- If `LTVDistributionStress` shows >40% of debt within 5pp of LLTV - "
        "lower LLTV proactively before the next adverse oracle move."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by [morpho-vault-counterfactuals]"
        "(https://github.com/mkzung/morpho-vault-counterfactuals).*"
    )
    return "\n".join(lines)
