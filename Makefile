.PHONY: install test lint typecheck format cov clean demo demo-html demo-compare all

# Default: full quality gate.
all: lint typecheck test

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

cov:
	pytest tests/ --cov=src/mvcf --cov-report=term-missing --cov-report=html

lint:
	ruff check src tests

format:
	ruff check src tests --fix
	ruff format src tests

typecheck:
	mypy src/mvcf

# Demo targets — rebuild the committed sample reports under docs/.
demo:
	mvcf analyze --fixture steakhouse_usdc_snapshot_demo

demo-html:
	mvcf analyze --fixture steakhouse_usdc_snapshot_demo --format html --output docs/demo_report.html
	mvcf analyze --fixture distressed_single_market_demo --format html --output docs/demo_report_distressed.html

demo-compare:
	mvcf compare --fixtures steakhouse_usdc_snapshot_demo,distressed_single_market_demo

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
