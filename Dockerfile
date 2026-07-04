# Slim, single-stage Dockerfile - for reproducible CLI invocations.
#
# Usage:
#   docker build -t mvcf .
#   docker run --rm mvcf analyze --fixture steakhouse_usdc_snapshot_demo
#   docker run --rm -v "$PWD/out:/out" mvcf analyze \
#     --fixture steakhouse_usdc_snapshot_demo --format html --output /out/report.html

FROM python:3.12-slim

WORKDIR /app

# Install package + runtime deps only (no dev tools).
COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
RUN pip install --no-cache-dir .

ENTRYPOINT ["mvcf"]
CMD ["--help"]
