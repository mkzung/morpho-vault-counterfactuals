# Contributing

Thanks for the interest. This is primarily a portfolio / research repo, so
the contribution surface is small but well-defined.

## Local development

```bash
git clone https://github.com/mkzung/morpho-vault-counterfactuals.git
cd morpho-vault-counterfactuals
make install                # pip install -e ".[dev]"
make all                    # ruff + mypy + pytest
```

Pre-commit hooks are configured — install once with `pre-commit install` so
`ruff` and `mypy` run on every commit.

## Adding a new detector

Detectors are pure functions on a `VaultSnapshot`. To add one:

1. Add a class to `src/mvcf/detectors.py` with a `run(snapshot) -> DetectorResult`
   method. Validate constructor params (raise `ValueError` on out-of-range
   inputs). Return a single fractional `headline_metric` and a useful
   `evidence` dict the curator can audit.
2. Wire the new detector into `runner.run_all_detectors()` and `__init__.py`.
3. Add tests in `tests/test_detectors.py`:
   - Bounded-output test (metric in [0,1]).
   - Monotonicity test if parameter has a natural direction.
   - Adversarial-input test for constructor validation.
4. Re-render the demo HTML reports under `docs/` (`make demo-html`).

The PR template asks for these four things explicitly.

## Adding a new fixture

Fixtures live under `data/fixtures/*.json` and follow the schema in
`src/mvcf/fetch.py:load_fixture`. Oracle prices must use Morpho's
36-decimal convention:

```
price = real_price × 10^(36 + loan_decimals − collateral_decimals)
```

Test the fixture loads cleanly and that each detector produces a sensible
output on it (see `tests/test_detectors.py` for the pattern).

## Style

- Python 3.10+.
- `ruff` rule set in `pyproject.toml`. Line length 100.
- `mypy` runs on `src/mvcf` and must pass before merging.
- Docstrings follow Google style; one-liners are fine for trivial functions.
- Detectors stay pure. All I/O lives in `fetch.py`.
- Numbers in fixtures are illustrative; document any non-obvious magnitude
  in the `_comment` key of the fixture JSON.

## Code of conduct

Be useful. Disagree about technical decisions in writing, with evidence.
