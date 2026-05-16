"""Streamlit dashboard for morpho-vault-counterfactuals.

Run locally:
    pip install streamlit
    streamlit run streamlit_app.py

Curator workflow: pick a fixture (or paste a vault address for live fetch),
adjust the detector parameters in the sidebar, see metrics update live.
This is the same content as the HTML report but interactive — for the
weekly curator review session where you sweep parameters by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mvcf import (  # noqa: E402
    diff_snapshots,
    fetch_vault_snapshot,
    load_fixture,
    run_all_detectors,
    summarize_diff,
)
from mvcf.detectors import CollateralCascade, OracleFreezeReplay  # noqa: E402

st.set_page_config(
    page_title="Morpho Vault Counterfactuals",
    page_icon="🏛",
    layout="wide",
)

st.title("Morpho MetaMorpho — counterfactual risk monitor")
st.caption(
    "Pure-function counterfactual detectors on a Morpho vault snapshot. "
    "Adjust parameters in the sidebar; metrics update live."
)

# ── Sidebar: source + parameters ──
with st.sidebar:
    st.header("Snapshot source")
    source = st.radio("Source", ["Fixture", "Live (Morpho Blue API)"], index=0)
    if source == "Fixture":
        fixture_name = st.selectbox(
            "Fixture",
            ["steakhouse_usdc_snapshot_demo", "distressed_single_market_demo"],
        )
        snap_loader = lambda: load_fixture(fixture_name)
    else:
        vault_addr = st.text_input(
            "Vault address (0x…)",
            value="0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
        )
        snap_loader = lambda: fetch_vault_snapshot(vault_addr)

    st.divider()
    st.header("Detector parameters")
    oracle_drift = st.slider("Oracle drift (%)", -30, -1, -10) / 100
    collateral_shock = st.slider("Collateral shock (%)", -50, -1, -20) / 100
    top_n_exit = st.slider("Top-N depositor exit", 1, 5, 1)
    util_band = st.slider("Utilization band (%)", 80, 99, 92) / 100
    gas_gwei = st.slider("Gas price (gwei)", 5, 200, 30)

# ── Main: snapshot summary + detector metrics ──
try:
    snap = snap_loader()
except Exception as e:
    st.error(f"Failed to load snapshot: {e}")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Block", f"{snap.block:,}")
col2.metric("Total assets (units)", f"{snap.total_assets:,}")
col3.metric("Markets", len(snap.markets))
col4.metric("HHI", f"{snap.hhi:.3f}")

results = run_all_detectors(
    snap,
    oracle_drift=oracle_drift,
    collateral_shock=collateral_shock,
    top_n_exit=top_n_exit,
    util_band=util_band,
    gas_gwei=gas_gwei,
)

st.subheader("Counterfactual risk")
cols = st.columns(3)
for i, r in enumerate(results):
    with cols[i % 3]:
        st.metric(r.name, f"{r.headline_metric:.1%}", help=r.interpretation)

# ── Sweep charts ──
st.subheader("Sensitivity sweeps")
import pandas as pd  # noqa: E402

c1, c2 = st.columns(2)

with c1:
    st.markdown("**Collateral cascade — % liquidatable vs shock**")
    shocks = [-0.02, -0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40, -0.50]
    cascade_df = pd.DataFrame(
        {
            "shock": [f"{s:+.0%}" for s in shocks],
            "frac": [
                CollateralCascade(shock_pct=s).run(snap).headline_metric
                for s in shocks
            ],
        }
    )
    st.line_chart(cascade_df.set_index("shock"))

with c2:
    st.markdown("**Oracle freeze — % bad debt vs drift**")
    drifts = [-0.02, -0.05, -0.10, -0.15, -0.20, -0.25]
    oracle_df = pd.DataFrame(
        {
            "drift": [f"{d:+.0%}" for d in drifts],
            "frac": [
                OracleFreezeReplay(drift_pct=d).run(snap).headline_metric for d in drifts
            ],
        }
    )
    st.line_chart(oracle_df.set_index("drift"))

# ── Per-detector deep-dive ──
st.subheader("Per-detector findings")
for r in results:
    with st.expander(f"{r.name} — {r.headline_metric:.1%}"):
        st.write(r.interpretation)
        st.json(r.evidence)

# ── Optional diff against another fixture ──
st.divider()
with st.expander("Compare to another snapshot (diff)"):
    other_name = st.selectbox(
        "Compare against fixture",
        ["(none)", "steakhouse_usdc_snapshot_demo", "distressed_single_market_demo"],
        index=0,
    )
    if other_name != "(none)":
        other = load_fixture(other_name)
        if other.vault_address.lower() == snap.vault_address.lower():
            diff = diff_snapshots(other, snap)
            st.code(summarize_diff(diff))
        else:
            st.warning(
                f"Cannot diff: vault addresses differ "
                f"({other.vault_address[:8]}… vs {snap.vault_address[:8]}…)"
            )

st.caption(
    "Built with [morpho-vault-counterfactuals]"
    "(https://github.com/mkzung/morpho-vault-counterfactuals)."
)
