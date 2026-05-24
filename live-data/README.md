# Live data

Auto-committed by the [Live snapshot workflow](../.github/workflows/live-snapshot.yml).
Runs once per day (~06:17 UTC) and captures the current state of
[Steakhouse USDC](https://etherscan.io/address/0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB),
the flagship MetaMorpho vault on Ethereum mainnet (~$114M TVL as of 2026-05).

## Files

| File | What |
|---|---|
| `steakhouse_usdc_latest.html` | Latest HTML dashboard (Chart.js, browser-ready) |
| `steakhouse_usdc_latest.json` | Latest JSON payload (for downstream pipes) |
| `steakhouse_usdc_latest.md` | Latest markdown brief (paste-ready) |
| `history/YYYY-MM-DD.json` | Timestamped daily archives — the time-series itself |

## Why this exists

To prove this framework runs against the real Morpho Blue API on real
mainnet data, not just offline fixtures. Anyone can fork this repo,
re-point the workflow at any other MetaMorpho vault address, and have a
free daily risk dashboard inside 5 minutes.

## Caveats

- The public Morpho Blue API returns market-level state but not individual
  borrower positions or per-depositor shares. Of the six detectors, only
  `UtilizationInversion` runs against fully-populated live data; the
  others (`OracleFreezeReplay`, `CollateralCascade`, `DepositorExitShock`,
  `LiquidationLatency`, `LTVDistributionStress`) require borrower /
  depositor data that needs an additional subgraph fetch — not yet wired in.
  They will read `0.0` on live snapshots until that's added.
- This is honest disclosure: the offline fixtures exist precisely because
  the framework needs full vault state to demonstrate all six detectors.
- The Morpho Blue API occasionally rate-limits unauthenticated calls.
  If you fork this and want to run it frequently, add `MORPHO_API_KEY`
  as a repository secret.
