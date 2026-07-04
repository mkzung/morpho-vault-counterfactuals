# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-05-25

Second audit-driven release. The v0.4.0 audit shipped fixes; this round closes the audit's follow-up - the things v0.4.0 left half-done or got wrong.

### BREAKING
- **`extra="forbid"` on every Pydantic model** (`MarketState`, `BorrowerPosition`, `VaultSnapshot`). Fixtures or upstream API payloads with typo'd keys now raise `ValidationError` instead of silently dropping the field. If you maintain a private fixture with extra metadata, move that metadata into a sibling `_meta` block before upgrading.
- **`fetch.fetch_vault_snapshot` no longer substitutes `1` for a missing oracle price.** Markets reporting `price=0` are now skipped with a `UserWarning` rather than producing garbage LTV math. Detector output on affected vaults will change.
- **GraphQL `errors` arrays raise `ValueError`.** Previously these were silently swallowed and produced empty snapshots - the exact failure mode that masked the live-data zeros bug for nine days.

### Fixed
- **Live-data zeros were a presentation bug, not a fetch bug.** The Markdown report header rendered `Block: 0` and `Borrowers analyzed: 0` literally, when the truth is the public Morpho Blue API does not expose either field. The header now says `Block: n/a (Blue API response is not block-pinned)` and `Borrowers analyzed: 0 - the public Blue API does not return per-borrower positions...`. `total_assets` (~$114M on Steakhouse USDC) was always real.
- **README quickstart was broken** - `pip install -e ".[dev]"` did not install jupyter (in `[notebook]`), so the very next line `jupyter notebook notebooks/01_demo.ipynb` failed. Quickstart now installs `.[dev,notebook]`.
- **`docs/index.html` numerical claims were wrong** - the distressed fixture has top-1 depositor at exactly 60% (not `>60%`) and trips 4 of 6 detectors CRITICAL (not 5 of 6). Both fixed against actual fixture output.
- **Synthetic depositor address collisions** - `f"0x{'D'*38}{i:04x}"[:42]` truncated the per-i suffix so all 10 "top depositors" had the same address. Fixed by using `f"0xDEAD{i:036x}"` (proper 42-char distinct addresses). The borrower-address fix from v0.4.0 had the same root cause and was not generalised; this closes the gap.
- **Block-pinning claim in `fetch.py` was false.** The module docstring promised reproducibility via a `block` argument; the GraphQL query never had a `block` field. Docstring now states honestly: the public `vaultByAddress` endpoint does not accept block-pinning; the `block` parameter is metadata-only; for true block-pinning use fixtures or a private archival indexer.
- **`load_history` was dead code.** It expected a `snapshot_names` key that no fixture provided. Now supports two layouts - an index-file layout with `snapshot_names`, or a directory of `*.json` snapshots - plus a clear `FileNotFoundError` when neither exists. Removed from "broken" status; added to the test suite.
- **TVL contradiction across docs.** CHANGELOG said >$120M, README said >$100M, live data says $114M. All three now say "~$114M (as of 2026-05)" sourced from the live snapshot.
- **Streamlit lambdas replaced with named functions** (`streamlit_app.py`) so the snapshot loader is mypy-checkable and traceback-readable.

### Added
- **HTTP retry on Morpho Blue API** - 1s/2s/4s exponential backoff on 429 / 5xx, with the last error surfaced (not silently swallowed) when retries exhaust. Curator crons fail loudly instead of hanging.
- **GitHub Issue on `live-snapshot` workflow failure** - when the nightly cron breaks, the workflow opens a labeled bug issue so stale data does not silently accumulate.
- **`pip-audit` CI job** - runtime + dev deps audited against PyPI's advisory DB on every push and PR.
- **11 new tests** covering `extra="forbid"`, zero-oracle skip, GraphQL error surfacing, retry/backoff (200 after 503s, exhaust on persistent 429), `load_history` directory layout, and synthetic depositor uniqueness. Test count: 54 -> 65.

## [0.4.0] - 2026-05-16

Audit-driven release. ~40 findings fixed across math correctness, CLI ergonomics, and documentation consistency.

### Fixed (math + correctness)
- **OracleFreezeReplay math** - renamed `liquidation_incentive` -> `bad_debt_lif`; threshold now `1/(1+LIF)` (the actual bad-debt frontier), not `LLTV × (1+LIF)` (which was neither liquidation boundary nor bad-debt boundary). Headline metric definition and `evidence` keys updated.
- **LiquidationLatency** - parametrized loan-asset decimals + USD price + LIF (previously hardcoded USDC-6dec at 5% LIF; broke silently for WETH/DAI vaults).
- **MarketState.utilization** - removed `min(1.0, ...)` cap so bad-debt situations (borrow > supply) reach detectors honestly; `supply=0 + borrow>0` now returns `inf` instead of silently 0.
- **BorrowerPosition.ltv** - `collateral=0 + debt>0` returns `inf` instead of silently 0; the parameter `collateral_decimals` was unused and is removed.
- **Synthetic generator** - `collateral_units` decimal-selection bug: previously always 18, now correctly alternates per market index. Borrower address collisions fixed (was: ~256 distinct addresses across N borrowers).
- **fetch.py hardening** - already in v0.3.0; explicit price>0 / lltv>0 filters.

### Fixed (UX + docs)
- **Version sync** - `pyproject.toml`, `__init__.__version__`, `CITATION.cff` all -> `0.4.0`.
- **mypy "strict" badge** was a lie - mypy was `strict = false`. Either drop "strict" claim (done) or actually enable. New config keeps gradual typing on but adds `warn_*` flags.
- **README sample output** - regenerated from actual fixture run; was stale numbers from an older fixture.
- **README architecture tree** - added `diff.py`, `synthetic.py`, `html_report.py`, `report.py`.
- **TVL claim** - unified language; live JSON is now the source of truth.
- **live-data/README** - corrected claim that all detectors are populated (only `UtilizationInversion` runs on live data).
- **CLI friendly errors** - invalid fixture / bad params / bad output path now print one-line errors with available fixtures listed, instead of raw tracebacks.
- **CLI `--version`** action added.
- **CLI flags** - every `analyze` parameter now has a `help=` string (units, sign, default).
- **Pluralization** - "1 small positions" -> "1 small position" across detector interpretations.
- **LTVDistributionStress** - returned two different `headline_unit` strings depending on branch; now consistent.
- **Test count** unified to 54 across CHANGELOG, docs, badges.
- **pyproject deps** - removed unused `numpy` + `rich` from runtime; added `[streamlit]` + `[notebook]` optional-dep groups; `pandas`/`matplotlib` moved to optional.
- **CITATION.cff** - removed empty-string `orcid` (CFF 1.2 schema invalid); removed redundant `(Researcher)` from affiliation.
- **Issue template** - `mvcf --version` now actually exists.
- **Fixture comments** - fixed stale notebook reference and TVL inconsistency.

### Added
- **Nightly live-snapshot workflow** (carried from v0.3.0) - daily GitHub Actions cron fetches Steakhouse USDC (~$114M TVL as of 2026-05) and commits fresh HTML/JSON/Markdown reports + a timestamped JSON archive under `live-data/history/`.
- **PyPI publish workflow** - fires on `v*.*.*` tag push; uses Trusted Publishing (no API tokens).
- **CITATION.cff** - academic-style citation file (CFF 1.2 standard).
- **`fetch.py` hardening** - gracefully skips idle markets (null collateralAsset) and degenerate LLTV values when parsing live Morpho Blue API responses. Verified end-to-end against the live Steakhouse USDC vault.
- `mvcf diff old.json new.json` - week-over-week snapshot delta with biggest-mover ranking.
- `src/mvcf/synthetic.py` - deterministic synthetic-vault generator for performance and scaling tests.
- `streamlit_app.py` - interactive Streamlit dashboard with live parameter sweeping.
- `docs/index.html` - landing page for GitHub Pages auto-deploy.
- `.github/workflows/pages.yml` - auto-deploys `docs/` to GitHub Pages on every push to main.
- `.github/ISSUE_TEMPLATE/` (bug + feature) and `PULL_REQUEST_TEMPLATE.md`.
- Performance smoke test: 1000-borrower × 10-market synthetic vault must complete all six detectors in &lt; 1 second.

## [0.3.0] - 2026-05-16

### Added
- **Nightly live-snapshot workflow** (`.github/workflows/live-snapshot.yml`) - daily cron pulls the real Steakhouse USDC vault state from the public Morpho Blue API and commits fresh HTML/JSON/Markdown reports under `live-data/`, plus a timestamped archive under `live-data/history/`. The repo becomes a public time-series of curator metrics for one of the largest MetaMorpho vaults.
- **PyPI publish workflow** (`.github/workflows/publish.yml`) - Trusted-Publishing flow, fires on `v*.*.*` tag push.
- **`CITATION.cff`** - academic citation file (CFF 1.2 standard).
- **`FUNDING.yml`** - GitHub Sponsors metadata.

### Fixed
- **`fetch.py` hardening** - gracefully skips idle markets (`collateralAsset == null`) and degenerate-LLTV values when parsing live Morpho Blue API responses. Verified end-to-end against the live Steakhouse USDC vault.

## [0.2.0] - 2026-05-16

### Added
- **`mvcf diff`** - week-over-week snapshot delta CLI subcommand with biggest-mover ranking, exposed as `mvcf.diff_snapshots` / `mvcf.summarize_diff`.
- **`src/mvcf/synthetic.py`** - deterministic synthetic-vault generator for performance benchmarking and 1000-borrower scaling tests.
- **`streamlit_app.py`** - interactive dashboard with sidebar parameter sweeping; same content as the HTML report but live-tunable.
- **`docs/index.html`** + **`.github/workflows/pages.yml`** - landing page auto-deployed to GitHub Pages on every push to `main`.
- **Issue templates** (`bug.md`, `feature.md`) and **`PULL_REQUEST_TEMPLATE.md`** under `.github/`.
- **Performance smoke test** - 1000-borrower × 10-market synthetic vault must finish all six detectors in under 1 second.
- **README live demo link** - pointed at the GitHub Pages site; advertised the Streamlit dashboard.

### Stats
- 52 tests, 90% coverage.

## [0.1.0] - 2026-05-16

### Added
- Six counterfactual detectors: `OracleFreezeReplay`, `CollateralCascade`,
  `DepositorExitShock`, `UtilizationInversion`, `LiquidationLatency`,
  `LTVDistributionStress`.
- `VaultSnapshot` / `MarketState` / `BorrowerPosition` / `VaultHistory`
  domain models with Pydantic v2 validation. Decimal-correct LTV math per
  Morpho's oracle convention.
- `fetch.py` Morpho Blue API client + offline fixture loader.
- CLI: `mvcf analyze`, `mvcf sweep`, `mvcf compare` with `text` / `json` /
  `markdown` / `html` output formats.
- HTML report generator with embedded Chart.js (single-file dashboard,
  no external assets except Chart.js CDN).
- Markdown report generator (paste-ready curator brief).
- Two fixtures: Steakhouse-USDC-style multi-market vault and a single-market
  distressed-vault edge case.
- 44 tests (pytest), ruff lint, mypy strict on `src/mvcf`.
- GitHub Actions matrix CI: Python 3.10/3.11/3.12 + mypy + cli-smoke jobs.
- Makefile, pre-commit hooks, Dockerfile, MIT LICENSE.

### Background
This repo was built as a curator-side counterfactual complement to the official
[`@morpho-org/vault-risk-sdk`](https://github.com/morpho-org/vault-risk-sdk)
(TypeScript, measures current risk). The six-detector + reproducible-replay
shape is borrowed from the author's earlier [Inca Challenge #492](https://github.com/mkzung/ethbtc-suspicious-patterns)
forensic framework on ETH/BTC microstructure, and re-applied to the Morpho
MetaMorpho protocol domain.

[Unreleased]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mkzung/morpho-vault-counterfactuals/releases/tag/v0.1.0
