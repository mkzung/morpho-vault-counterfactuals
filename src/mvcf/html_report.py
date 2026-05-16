"""HTML report generator — single-file, embedded Chart.js, no external assets.

Why this exists:
  A curator wants a self-contained `report.html` they can pipe into Slack,
  email, or open offline — not a notebook (heavy), not a JSON dump (raw).
  This module produces one HTML file with:
    - Headline metrics grid (color-coded by severity)
    - Chart.js bar chart of detector outputs
    - Collateral cascade sensitivity curve
    - Per-market state table
    - Borrower LTV distribution histogram
    - Suggested-action checklist

  Chart.js is loaded from a CDN inline so the file works offline once
  cached and serves as a portable artifact. No build step, no React,
  no `npm install`.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .detectors import (
    CollateralCascade,
    LiquidationLatency,
    OracleFreezeReplay,
)
from .runner import run_all_detectors
from .state import VaultSnapshot


def _severity(metric: float) -> tuple[str, str]:
    """Map metric in [0,1] to (color, label) — curator-friendly traffic light."""
    if metric < 0.05:
        return "#16a34a", "OK"
    if metric < 0.20:
        return "#eab308", "WATCH"
    if metric < 0.50:
        return "#f97316", "ALERT"
    return "#dc2626", "CRITICAL"


def _build_cascade_sweep(snap: VaultSnapshot) -> dict[str, list]:
    """Run the cascade sweep that feeds the sensitivity chart."""
    shocks = [-0.02, -0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40, -0.50]
    return {
        "labels": [f"{s:+.0%}" for s in shocks],
        "values": [
            round(CollateralCascade(shock_pct=s).run(snap).headline_metric * 100, 2) for s in shocks
        ],
    }


def _build_oracle_sweep(snap: VaultSnapshot) -> dict[str, list]:
    drifts = [-0.02, -0.05, -0.08, -0.10, -0.15, -0.20, -0.25]
    return {
        "labels": [f"{d:+.0%}" for d in drifts],
        "values": [
            round(OracleFreezeReplay(drift_pct=d).run(snap).headline_metric * 100, 2)
            for d in drifts
        ],
    }


def _build_ltv_histogram(snap: VaultSnapshot) -> dict[str, list]:
    markets_by_id = {m.market_id: m for m in snap.markets}
    bins = [0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.85, 0.90, 0.95, 1.0, 1.1]
    counts = [0] * (len(bins) - 1)
    for pos in snap.borrowers:
        mkt = markets_by_id.get(pos.market_id)
        if mkt is None:
            continue
        ltv = pos.ltv(mkt.oracle_price_36dec)
        for i in range(len(bins) - 1):
            if bins[i] <= ltv < bins[i + 1]:
                counts[i] += 1
                break
    return {
        "labels": [f"{bins[i]:.2f}-{bins[i + 1]:.2f}" for i in range(len(bins) - 1)],
        "values": counts,
    }


def _build_gas_sweep(snap: VaultSnapshot) -> dict[str, list]:
    gas_levels = [10, 20, 30, 50, 80, 120, 200, 400]
    return {
        "labels": [f"{g} gwei" for g in gas_levels],
        "values": [
            round(LiquidationLatency(gas_price_gwei=g).run(snap).headline_metric * 100, 2)
            for g in gas_levels
        ],
    }


# Single-file HTML template. Uses Chart.js CDN; everything else is inline.
_HTML_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Vault risk brief — {addr_short}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 24px 32px; max-width: 1200px; margin: 0 auto;
    color: #0f172a; background: #fafafa; line-height: 1.5;
  }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #64748b; font-size: 13px; margin-bottom: 24px; }}
  .meta {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
           gap: 12px; margin-bottom: 24px; }}
  .meta-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; }}
  .meta-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }}
  .meta-value {{ font-size: 18px; font-weight: 600; margin-top: 2px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .det-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px;
               padding: 16px; border-left: 4px solid #e2e8f0; }}
  .det-name {{ font-weight: 600; font-size: 13px; }}
  .det-metric {{ font-size: 28px; font-weight: 700; margin: 6px 0 2px; }}
  .det-unit {{ font-size: 11px; color: #64748b; }}
  .det-interp {{ font-size: 12px; color: #334155; margin-top: 8px; line-height: 1.4; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 10px;
            font-weight: 700; color: white; vertical-align: middle; margin-left: 6px; }}
  h2 {{ font-size: 16px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin: 32px 0 14px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  @media (max-width: 800px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-wrap {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; height: 320px; }}
  .chart-title {{ font-size: 12px; font-weight: 600; color: #334155; margin-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #e2e8f0;
           border-radius: 8px; overflow: hidden; font-size: 12px; }}
  th {{ background: #f1f5f9; padding: 8px 10px; text-align: left; font-weight: 600; }}
  td {{ padding: 8px 10px; border-top: 1px solid #f1f5f9; font-family: ui-monospace, monospace; }}
  .hot {{ color: #dc2626; font-weight: 700; }}
  ul {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 14px 14px 32px; font-size: 13px; }}
  ul li {{ margin-bottom: 6px; }}
  footer {{ color: #94a3b8; font-size: 11px; margin-top: 32px; text-align: center; }}
  code {{ background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>

<h1>Vault risk brief — <code>{addr_short}</code></h1>
<div class="sub">Generated {ts} · block <code>{block:,}</code> · {n_markets} markets · {n_borrowers} borrowers analyzed</div>

<div class="meta">
  <div class="meta-card"><div class="meta-label">Total assets</div><div class="meta-value">{total_assets_human}</div></div>
  <div class="meta-card"><div class="meta-label">HHI</div><div class="meta-value">{hhi:.3f}</div></div>
  <div class="meta-card"><div class="meta-label">Top-1 share</div><div class="meta-value">{top1:.1%}</div></div>
  <div class="meta-card"><div class="meta-label">Markets</div><div class="meta-value">{n_markets}</div></div>
</div>

<h2>Counterfactual risk dashboard</h2>
<div class="grid">
{detector_cards}
</div>

<h2>Sensitivity sweeps</h2>
<div class="charts">
  <div class="chart-wrap"><div class="chart-title">Collateral cascade — % debt liquidatable vs shock magnitude</div><canvas id="cascadeChart"></canvas></div>
  <div class="chart-wrap"><div class="chart-title">Oracle freeze — % bad debt vs collateral drift while stale</div><canvas id="oracleChart"></canvas></div>
  <div class="chart-wrap"><div class="chart-title">Borrower LTV histogram (count of positions)</div><canvas id="ltvChart"></canvas></div>
  <div class="chart-wrap"><div class="chart-title">Liquidation latency — % unprofitable vs gas price</div><canvas id="gasChart"></canvas></div>
</div>

<h2>Per-market state</h2>
<table>
<thead><tr>
<th>Market</th><th style="text-align:right">Supply</th><th style="text-align:right">Borrow</th>
<th style="text-align:right">Utilization</th><th style="text-align:right">LLTV</th><th style="text-align:right">Supply cap</th>
</tr></thead>
<tbody>
{market_rows}
</tbody>
</table>

<h2>Suggested curator actions</h2>
<ul>
{action_items}
</ul>

<footer>
Generated by <a href="https://github.com/mkzung/morpho-vault-counterfactuals">morpho-vault-counterfactuals</a> ·
counterfactual risk monitoring for Morpho MetaMorpho vaults
</footer>

<script>
const cascade = {cascade_data};
const oracle  = {oracle_data};
const ltv     = {ltv_data};
const gas     = {gas_data};

const common = {{
  responsive: true, maintainAspectRatio: false,
  plugins: {{ legend: {{ display: false }} }},
  scales: {{ y: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }} }} }},
             x: {{ ticks: {{ font: {{ size: 10 }} }} }} }},
}};

new Chart(document.getElementById('cascadeChart'), {{
  type: 'line',
  data: {{ labels: cascade.labels, datasets: [{{
    label: '% liquidatable', data: cascade.values, fill: true,
    backgroundColor: 'rgba(220,38,38,0.15)', borderColor: '#dc2626', tension: 0.25
  }}] }}, options: common
}});

new Chart(document.getElementById('oracleChart'), {{
  type: 'line',
  data: {{ labels: oracle.labels, datasets: [{{
    label: '% bad debt', data: oracle.values, fill: true,
    backgroundColor: 'rgba(249,115,22,0.15)', borderColor: '#f97316', tension: 0.25
  }}] }}, options: common
}});

new Chart(document.getElementById('ltvChart'), {{
  type: 'bar',
  data: {{ labels: ltv.labels, datasets: [{{
    label: '# positions', data: ltv.values,
    backgroundColor: '#1d4ed8'
  }}] }}, options: common
}});

new Chart(document.getElementById('gasChart'), {{
  type: 'line',
  data: {{ labels: gas.labels, datasets: [{{
    label: '% unprofitable', data: gas.values, fill: true,
    backgroundColor: 'rgba(2,132,199,0.15)', borderColor: '#0284c7', tension: 0.25
  }}] }}, options: common
}});
</script>
</body>
</html>
"""


def as_html(snapshot: VaultSnapshot, results: list | None = None) -> str:
    """Render a single-file HTML report — embedded charts, no external assets except Chart.js CDN.

    Args:
        snapshot: vault state to analyze.
        results: optional pre-computed detector results (saves a re-run).

    Returns:
        Complete HTML document as a string. Save to disk, open in a browser,
        paste into Slack, attach to email. No build step required.
    """
    if results is None:
        results = run_all_detectors(snapshot)

    addr_short = snapshot.vault_address[:6] + "…" + snapshot.vault_address[-4:]
    total_assets_human = f"{snapshot.total_assets / 1e6:,.0f} (units / 1e6)"

    # Detector cards
    detector_cards_html = []
    for r in results:
        color, label = _severity(r.headline_metric)
        detector_cards_html.append(
            f'<div class="det-card" style="border-left-color:{color}">'
            f'<div class="det-name">{html.escape(r.name)} '
            f'<span class="badge" style="background:{color}">{label}</span></div>'
            f'<div class="det-metric" style="color:{color}">{r.headline_metric:.1%}</div>'
            f'<div class="det-unit">{html.escape(r.headline_unit)}</div>'
            f'<div class="det-interp">{html.escape(r.interpretation)}</div>'
            f"</div>"
        )

    # Market rows
    market_rows_html = []
    for m in snapshot.markets:
        util_class = ' class="hot"' if m.utilization > 0.92 else ""
        market_rows_html.append(
            f"<tr><td><code>{m.market_id[:14]}…</code></td>"
            f"<td style='text-align:right'>{m.total_supply_assets:,}</td>"
            f"<td style='text-align:right'>{m.total_borrow_assets:,}</td>"
            f"<td style='text-align:right'{util_class}>{m.utilization:.1%}</td>"
            f"<td style='text-align:right'>{m.lltv:.0%}</td>"
            f"<td style='text-align:right'>{m.supply_cap:,}</td></tr>"
        )

    # Action items (same logic as markdown report)
    actions = []
    for r in results:
        metric: float = r.headline_metric
        if r.name == "OracleFreezeReplay" and metric > 0.05:
            actions.append(
                "<li><b>OracleFreezeReplay > 5%</b> — review oracle update cadence; consider Chainlink fallback or oracle-router timeout.</li>"
            )
        if r.name == "CollateralCascade" and metric > 0.30:
            actions.append(
                "<li><b>CollateralCascade > 30%</b> — lower LLTV on the concentrated market(s) by 1-3 percentage points.</li>"
            )
        if r.name == "DepositorExitShock" and metric > 0.20:
            actions.append(
                "<li><b>DepositorExitShock > 20%</b> — reduce vault-level supply cap to free idle supply.</li>"
            )
        if r.name == "UtilizationInversion" and metric >= 0.5:
            actions.append(
                "<li><b>UtilizationInversion ≥ 50%</b> — raise IRM upper rate or reallocate via the MetaMorpho <code>reallocate()</code> flow.</li>"
            )
        if r.name == "LiquidationLatency" and metric > 0.05:
            actions.append(
                "<li><b>LiquidationLatency > 5%</b> — raise minimum-position-size threshold; cap supply on markets accumulating dust positions.</li>"
            )
        if r.name == "LTVDistributionStress" and metric > 0.40:
            actions.append(
                "<li><b>LTVDistributionStress > 40%</b> — lower LLTV proactively before the next adverse oracle move.</li>"
            )
    if not actions:
        actions = [
            "<li>All counterfactual metrics within safe bands at current parameters. No immediate action required.</li>"
        ]

    return _HTML_TMPL.format(
        addr_short=html.escape(addr_short),
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        block=snapshot.block,
        n_markets=len(snapshot.markets),
        n_borrowers=len(snapshot.borrowers),
        total_assets_human=total_assets_human,
        hhi=snapshot.hhi,
        top1=snapshot.top1_share,
        detector_cards="\n".join(detector_cards_html),
        market_rows="\n".join(market_rows_html),
        action_items="\n".join(actions),
        cascade_data=json.dumps(_build_cascade_sweep(snapshot)),
        oracle_data=json.dumps(_build_oracle_sweep(snapshot)),
        ltv_data=json.dumps(_build_ltv_histogram(snapshot)),
        gas_data=json.dumps(_build_gas_sweep(snapshot)),
    )
