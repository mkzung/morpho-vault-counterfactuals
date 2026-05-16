# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-05-16

Audit-driven release. ~40 findings fixed across math correctness, CLI ergonomics, and documentation consistency.

### Fixed (math + correctness)
- **OracleFreezeReplay math** — renamed `liquidation_incentive` → `bad_debt_lif`; threshold now `1/(1+LIF)` (the actual bad-debt frontier), not `LLTV × (1+LIF)` (which was neither liquidation boundary nor bad-debt boundary). Headline metric definition and `evidence` keys updated.
- **LiquidationLatency** — parametrized loan-asset decimals + USD price + LIF (previously hardcoded USDC-6dec at 5% LIF; broke silently for WETH/DAI vaults).
- **MarketState.utilization** — removed `min(1.0, ...)` cap so bad-debt situations (borrow > supply) reach detectors honestly; `supply=0 + borrow>0` now returns `inf` instead of silently 0.
- **BorrowerPosition.ltv** — `collateral=0 + debt>0` returns `inf` instead of silently 0; the parameter `collateral_decimals` was unused and is removed.
- **Synthetic generator** — `collateral_units` decimal-selection bug: previously always 18, now correctly alternates per market index. Borrower address collisions fixed (was: ~256 distinct addresses across N borrowers).
- **fetch.py hardening** — already in v0.3.0; explicit price>0 / lltv>0 filters.

### Fixed (UX + docs)
- **Version sync** — `pyproject.toml`, `__init__.__version__`, `CITATION.cff` all → `0.4.0`.
- **mypy "strict" badge** was a lie — mypy was `strict = false`. Either drop "strict" claim (done) or actually enable. New config keeps gradual typing on but adds `warn_*` flags.
- **README sample output** — regenerated from actual fixture run; was stale numbers from an older fixture.
- **README architecture tree** — added `diff.py`, `synthetic.py`, `html_report.py`, `report.py`.
- **TVL claim** — unified language; live JSON is now the source of truth.
- **live-data/README** — corrected claim that all detectors are populated (only `UtilizationInversion` runs on live data).
- **CLI friendly errors** — invalid fixture / bad params / bad output path now print one-line errors with available fixtures listed, instead of raw tracebacks.
- **CLI `--version`** action added.
- **CLI flags** — every `analyze` parameter now has a `help=` string (units, sign, default).
- **Pluralization** — "1 small positions" → "1 small position" across detector interpretations.
- **LTVDistributionStress** — returned two different `headline_unit` strings depending on branch; now consistent.
- **Test count** unified to 54 across CHANGELOG, docs, badges.
- **pyproject deps** — removed unused `numpy` + `rich` from runtime; added `[streamlit]` + `[notebook]` optional-dep groups; `pandas`/`matplotlib` moved to optional.
- **CITATION.cff** — removed empty-string `orcid` (CFF 1.2 schema invalid); removed redundant `(Researcher)` from affiliation.
- **Issue template** — `mvcf --version` now actually exists.
- **Fixture comments** — fixed stale notebook reference and TVL inconsistency.

### Added
- **Nightly live-snapshot workflow** (carried from v0.3.0) — daily GitHub Actions cron fetches Steakhouse USDC (>$120M TVL mainnet vault) and commits fresh HTML/JSON/Markdown reports + a timestamped JSON archive under `live-data/history/`.
- **PyPI publish workflow** — fires on `v*.*.*` tag push; uses Trusted Publishing (no API tokens).
- **CITATION.cff** — academic-style citation file (CFF 1.2 standard).
- **`fetch.py` hardening** — gracefully skips idle markets (null collateralAsset) and degenerate LLTV values when parsing live Morpho Blue API responses. Verified end-to-end against the live Steakhouse USDC vault.
- `mvcf diff old.json new.json` — week-over-week snapshot delta with biggest-mover ranking.
- `src/mvcf/synthetic.py` — deterministic synthetic-vault generator for performance and scaling tests.
- `streamlit_app.py` — interactive Streamlit dashboard with live parameter sweeping.
- `docs/index.html` — landing page for GitHub Pages auto-deploy.
- `.github/workflows/pages.yml` — auto-deploys `docs/` to GitHub Pages on every push to main.
- `.github/ISSUE_TEMPLATE/` (bug + feature) and `PULL_REQUEST_TEMPLATE.md`.
- Performance smoke test: 1000-borrower × 10-market synthetic vault must complete all six detectors in &lt; 1 second.

## [0.1.0] — 2026-05-16

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

[Unreleased]: https://github.com/mkzung/morpho-vault-counterfactuals/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mkzung/morpho-vault-counterfactuals/releases/tag/v0.1.0
