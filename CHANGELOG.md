# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
