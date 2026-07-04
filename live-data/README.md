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
| `history/YYYY-MM-DD.json` | Timestamped daily archives - the time-series itself |

## Why this exists

To prove this framework runs against the real Morpho Blue API on real
mainnet data, not just offline fixtures. Anyone can fork this repo,
re-point the workflow at any other MetaMorpho vault address, and have a
free daily risk dashboard inside 5 minutes.

## Caveats

- Both market-level state and per-user positions come from the public Morpho
  Blue API: `vaultByAddress` (markets), `vaultPositions` (depositor shares),
  and `marketPositions` (borrower positions). All six detectors run against
  live data; no private subgraph is required.
- The Blue API returns at most 1000 positions per query, so the borrower-level
  detectors analyze the largest-by-debt positions. For the tracked vault this
  covers ~100% of open market debt; the `borrower_debt_coverage` field in each
  JSON snapshot records the exact fraction captured on that run.
- Offline fixtures are kept for deterministic, block-pinned test replay.
- The Morpho Blue API occasionally rate-limits unauthenticated calls.
  If you fork this and want to run it frequently, add `MORPHO_API_KEY`
  as a repository secret.
