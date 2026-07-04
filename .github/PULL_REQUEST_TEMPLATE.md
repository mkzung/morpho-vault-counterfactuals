## What this PR changes

A clear description of the change.

## Checklist

- [ ] `make all` passes locally (ruff + mypy + pytest)
- [ ] If a new detector or fixture was added, tests cover both happy and adversarial inputs
- [ ] If decimal handling was touched, manually verified against Morpho oracle convention (`price = real_price × 10^(36 + loan_dec - collateral_dec)`)
- [ ] If a CLI surface changed, README usage examples are updated
- [ ] CHANGELOG.md updated under `[Unreleased]`

## Curator-impact summary
(One sentence: what does this change about the metrics a curator would see?)
