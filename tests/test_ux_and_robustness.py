"""Tests for the human-readable reporting + position-fetch robustness.

Covers: humanize_amount formatting, loan symbol/decimals capture in
_parse_response, the shared _post_graphql retry, the Blue API first-page
clamp, and the market-wide/coverage wording in the markdown brief.
"""
import httpx
import pytest

from mvcf.fetch import _API_FIRST_MAX, _parse_response, _post_graphql, fetch_positions
from mvcf.report import as_markdown, humanize_amount
from mvcf.state import BorrowerPosition, MarketState, VaultSnapshot


def _market(mid: str = "0xM1") -> MarketState:
    return MarketState(
        market_id=mid, block=0, timestamp=0,
        collateral_token="0xcoll", loan_token="0xloan",
        total_supply_assets=1_000_000, total_borrow_assets=500_000,
        total_collateral_assets=2_000_000, oracle_price_36dec=10**36,
        lltv_wad=860_000_000_000_000_000, supply_cap=0,
    )


# --- humanize_amount ---

@pytest.mark.parametrize(
    "units,decimals,symbol,expected",
    [
        (95_340_290_886_683, 6, "USDC", "95.34M USDC"),
        (5_000_000_000_000_000, 6, "USDC", "5.00B USDC"),
        (1_500_000, 6, "USDC", "1.50 USDC"),
        (123_456, 6, "USDC", "0.12 USDC"),
        (2_000_000_000_000_000_000, 18, "WETH", "2.00 WETH"),  # 18-dec asset
        (1234, 0, "X", "1,234 units"),                          # unknown decimals
        (0, 6, "USDC", "0.00 USDC"),
    ],
)
def test_humanize_amount(units, decimals, symbol, expected):
    assert humanize_amount(units, decimals, symbol) == expected


# --- _parse_response captures the loan asset symbol/decimals ---

def test_parse_response_captures_loan_symbol_decimals():
    payload = {"data": {"vaultByAddress": {"address": "0xV", "state": {
        "totalAssets": "1000000", "totalSupply": "1000",
        "allocation": [{"market": {
            "marketId": "0xM1",
            "collateralAsset": {"address": "0xc", "symbol": "WBTC", "decimals": 8},
            "loanAsset": {"address": "0xL", "symbol": "USDC", "decimals": 6},
            "state": {"supplyAssets": "1000000", "borrowAssets": "500000",
                      "collateralAssets": "2000000", "price": str(10**36),
                      "utilization": "0.5"},
            "lltv": "860000000000000000",
        }, "supplyAssets": "1000000", "supplyCap": "0"}],
    }}}}
    snap = _parse_response(payload, "0xV", 0)
    assert snap.loan_symbol == "USDC"
    assert snap.loan_decimals == 6


# --- _post_graphql retry parity ---

def test_post_graphql_retries_5xx_then_succeeds(monkeypatch):
    calls: list[int] = []

    def post(self, url, json=None):  # noqa: A002
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, json={}, request=httpx.Request("POST", url))
        return httpx.Response(
            200, json={"data": {"ok": True}}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr("mvcf.fetch.time.sleep", lambda _s: None)
    with httpx.Client() as client:
        data = _post_graphql(client, "query", {})
    assert data == {"data": {"ok": True}}
    assert len(calls) == 3  # two 500s retried, third 200 returned


def test_post_graphql_surfaces_graphql_errors_with_ctx(monkeypatch):
    def post(self, url, json=None):  # noqa: A002
        return httpx.Response(
            200, json={"errors": [{"message": "bad"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    with httpx.Client() as client, pytest.raises(ValueError, match="for depositors"):
        _post_graphql(client, "query", {}, ctx="depositors")


# --- fetch_positions clamps `first` to the Blue API ceiling ---

def test_fetch_positions_clamps_first_to_api_max(monkeypatch):
    seen_first: list[int] = []

    def post(self, url, json=None):  # noqa: A002
        seen_first.append(json["variables"]["first"])
        q = json["query"]
        key = "vaultPositions" if "vaultPositions" in q else "marketPositions"
        return httpx.Response(
            200, json={"data": {key: {"items": []}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    fetch_positions("0xV", ["0xM1"], top_n_depositors=9999, max_borrowers=9999)
    assert seen_first  # both queries fired
    assert all(f <= _API_FIRST_MAX for f in seen_first)


# --- markdown brief: humanized total + market-wide/coverage wording ---

def test_markdown_humanizes_and_flags_market_wide():
    snap = VaultSnapshot(
        vault_address="0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
        block=0, timestamp=0,
        total_assets=95_340_290_886_683, total_shares=100,
        loan_symbol="USDC", loan_decimals=6,
        top_depositors=[("0xa", 40)],
        markets=[_market()],
        borrowers=[BorrowerPosition(
            market_id="0xM1", borrower="0xc", collateral=2_000_000, debt_assets=500_000
        )],
    )
    md = as_markdown(snap, [])
    assert "95.34M USDC" in md          # humanized headline
    assert "market-wide" in md          # borrower-scope clarifier
    assert "100.0% of" in md            # debt coverage (500k of 500k)
