"""Entry point: `python -m mvcf` and `mvcf` console script.

Usage examples (see `mvcf --help` for the full surface):

    # Replay all six detectors against a checked-in fixture
    mvcf analyze --fixture steakhouse_usdc_snapshot_demo

    # Sensitivity sweep on collateral shock magnitude
    mvcf sweep collateral --fixture steakhouse_usdc_snapshot_demo \
            --shocks -0.05,-0.10,-0.20,-0.30,-0.50

    # Live fetch + report
    mvcf analyze --vault 0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB \
            --format markdown --output report.md

    # JSON-emit results (for piping into downstream tooling)
    mvcf analyze --fixture steakhouse_usdc_snapshot_demo --format json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .detectors import CollateralCascade, OracleFreezeReplay
from .fetch import fetch_vault_snapshot, load_fixture
from .report import as_json, as_markdown
from .runner import run_all_detectors, summarize


def _cmd_analyze(args: argparse.Namespace) -> int:
    if args.vault and args.fixture:
        print("error: --vault and --fixture are mutually exclusive", file=sys.stderr)
        return 2
    if not args.vault and not args.fixture:
        print("error: pass either --vault <addr> or --fixture <name>", file=sys.stderr)
        return 2

    snap = (
        fetch_vault_snapshot(args.vault, block=args.block)
        if args.vault
        else load_fixture(args.fixture)
    )

    results = run_all_detectors(
        snap,
        oracle_drift=args.oracle_drift,
        collateral_shock=args.collateral_shock,
        top_n_exit=args.top_n_exit,
        util_band=args.util_band,
        gas_gwei=args.gas_gwei,
    )

    if args.format == "text":
        out = summarize(results)
    elif args.format == "json":
        out = as_json(snap, results)
    elif args.format == "markdown":
        out = as_markdown(snap, results)
    else:
        print(f"error: unknown format {args.format!r}", file=sys.stderr)
        return 2

    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
        print(f"  ✓ wrote {args.output}", file=sys.stderr)
    else:
        print(out)
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    if not args.fixture and not args.vault:
        print("error: pass either --vault <addr> or --fixture <name>", file=sys.stderr)
        return 2
    snap = (
        fetch_vault_snapshot(args.vault, block=args.block)
        if args.vault
        else load_fixture(args.fixture)
    )

    if args.kind == "collateral":
        values = [float(s.strip()) for s in args.shocks.split(",")]
        print(f"Collateral cascade sweep on {snap.vault_address[:10]}…  (block {snap.block})\n")
        print(f"  {'shock':>8}  {'liquidatable_debt':>20}  {'liquidity_gap':>15}")
        for shock in values:
            res = CollateralCascade(shock_pct=shock).run(snap)
            print(
                f"  {shock:>+8.0%}  "
                f"{res.headline_metric:>20.1%}  "
                f"{res.evidence['liquidity_gap']:>15,}"
            )
    elif args.kind == "oracle":
        values = [float(s.strip()) for s in args.shocks.split(",")]
        print(f"Oracle freeze sweep on {snap.vault_address[:10]}…  (block {snap.block})\n")
        print(f"  {'drift':>8}  {'bad_debt_frac':>15}  {'unliquidatable_positions':>25}")
        for drift in values:
            res = OracleFreezeReplay(drift_pct=drift).run(snap)
            print(
                f"  {drift:>+8.0%}  "
                f"{res.headline_metric:>15.1%}  "
                f"{res.evidence['unliquidatable_positions']:>25}"
            )
    else:
        print(f"error: unknown sweep kind {args.kind!r}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mvcf",
        description="Counterfactual risk monitor for Morpho MetaMorpho vaults.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # analyze
    a = sub.add_parser("analyze", help="Run all six detectors on a vault")
    a.add_argument("--vault", help="Live MetaMorpho vault address (0x...)")
    a.add_argument("--fixture", help="Name of a checked-in fixture (data/fixtures/<name>.json)")
    a.add_argument("--block", type=int, default=None, help="Block to pin a live query (default: latest)")
    a.add_argument("--oracle-drift", type=float, default=-0.10)
    a.add_argument("--collateral-shock", type=float, default=-0.20)
    a.add_argument("--top-n-exit", type=int, default=1)
    a.add_argument("--util-band", type=float, default=0.92)
    a.add_argument("--gas-gwei", type=float, default=30.0)
    a.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    a.add_argument("--output", help="Write to file instead of stdout")
    a.set_defaults(func=_cmd_analyze)

    # sweep
    s = sub.add_parser("sweep", help="Sensitivity sweep on one detector parameter")
    s.add_argument("kind", choices=["collateral", "oracle"], help="Which detector to sweep")
    s.add_argument("--vault", help="Live MetaMorpho vault address (0x...)")
    s.add_argument("--fixture", help="Name of a checked-in fixture")
    s.add_argument("--block", type=int, default=None)
    s.add_argument(
        "--shocks",
        default="-0.02,-0.05,-0.10,-0.15,-0.20,-0.30,-0.50",
        help="Comma-separated list of shock fractions (negative)",
    )
    s.set_defaults(func=_cmd_sweep)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
