"""Offline tests for Blue API position enrichment (depositors + borrowers)."""
import httpx
import pytest

from mvcf.fetch import _enrich_positions, fetch_positions
from mvcf.state import MarketState, VaultSnapshot


def _market(mid: str) -> MarketState:
    return MarketState(
        market_id=mid, block=0, timestamp=0,
        collateral_token="0xcoll", loan_token="0xloan",
        total_supply_assets=1000, total_borrow_assets=500,
        total_collateral_assets=2000, oracle_price_36dec=10**36,
        lltv_wad=860_000_000_000_000_000, supply_cap=0,
    )


def _routed_post(self, url, json=None):  # noqa: A002
    q = (json or {}).get("query", "")
    if "vaultPositions" in q:
        body = {"data": {"vaultPositions": {"items": [
            {"user": {"address": "0xaaa"}, "state": {"shares": "100"}},
            {"user": {"address": "0xbbb"}, "state": {"shares": "40"}},
        ]}}}
    else:
        body = {"data": {"marketPositions": {"items": [
            {"user": {"address": "0xccc"}, "market": {"marketId": "0xM1"},
             "state": {"collateral": "2000", "borrowAssets": "500"}},
        ]}}}
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def test_fetch_positions_parses_depositors_and_borrowers(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", _routed_post)
    deps, borrowers = fetch_positions("0xVault", ["0xM1"])
    assert deps == [("0xaaa", 100), ("0xbbb", 40)]  # (address, shares), desc
    assert len(borrowers) == 1
    b = borrowers[0]
    assert b.market_id == "0xM1" and b.collateral == 2000 and b.debt_assets == 500


def test_fetch_positions_skips_none_fields(monkeypatch):
    def post(self, url, json=None):  # noqa: A002
        body = {"data": {"vaultPositions": {"items": [
            {"user": {"address": "0xaaa"}, "state": {"shares": "10"}},
            {"user": {"address": None}, "state": {"shares": "5"}},   # no address -> skipped
            {"user": {"address": "0xccc"}, "state": {"shares": None}},  # no shares -> skipped
        ]}}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.Client, "post", post)
    deps, borrowers = fetch_positions("0xVault", [])  # no markets -> no borrower query
    assert deps == [("0xaaa", 10)]
    assert borrowers == []


def test_enrich_positions_degrades_gracefully_on_error(monkeypatch):
    def boom(self, url, json=None):  # noqa: A002
        raise httpx.ConnectError("upstream down")
    monkeypatch.setattr(httpx.Client, "post", boom)
    snap = VaultSnapshot(
        vault_address="0xVault", block=0, timestamp=0,
        total_assets=1000, total_shares=1000, markets=[_market("0xM1")],
    )
    with pytest.warns(UserWarning):
        out = _enrich_positions(snap)
    assert out.top_depositors == [] and out.borrowers == []
    assert out.markets == snap.markets  # core snapshot preserved
