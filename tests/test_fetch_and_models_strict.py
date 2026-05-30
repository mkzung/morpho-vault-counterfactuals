"""Tests for v0.5.0 hardening:

  - Pydantic models reject extra fields (`extra="forbid"`).
  - `fetch._parse_response` skips markets with zero oracle price (no silent
    substitution).
  - `fetch.fetch_vault_snapshot` raises on GraphQL `errors` arrays.
  - `fetch.fetch_vault_snapshot` retries 429 / 5xx and surfaces the last
    error after retries exhaust.
  - `fetch.load_history` works against a directory of snapshot files.
  - `synthetic.generate_synthetic_vault` produces unique depositor addresses.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from mvcf.fetch import _parse_response, fetch_vault_snapshot, load_history
from mvcf.state import BorrowerPosition, MarketState, VaultSnapshot
from mvcf.synthetic import generate_synthetic_vault

# ──────────────────────────────────────────────────────────────────
# extra="forbid" — typo'd fixture keys must fail loudly
# ──────────────────────────────────────────────────────────────────


def test_market_state_rejects_unknown_field():
    with pytest.raises(ValidationError):
        MarketState(
            market_id="0xabc",
            block=1,
            timestamp=1000,
            collateral_token="0xC",
            loan_token="0xL",
            total_supply_assets=1_000_000_000,
            total_borrow_assets=500_000_000,
            total_collateral_assets=10**21,
            oracle_price_36dec=10**36,
            lltv_wad=860 * 10**15,
            supply_cap=2_000_000_000,
            total_assests=999,  # typo
        )


def test_borrower_position_rejects_unknown_field():
    with pytest.raises(ValidationError):
        BorrowerPosition(
            market_id="0xabc",
            borrower="0xb1",
            collateral=10**18,
            debt_assets=1000,
            colateral=999,  # typo
        )


def test_vault_snapshot_rejects_unknown_field():
    with pytest.raises(ValidationError):
        VaultSnapshot(
            vault_address="0xv1",
            block=1,
            timestamp=1,
            total_assets=1,
            total_shares=1,
            markets=[],
            borrowers=[],
            total_assests=999,  # typo from the audit
        )


# ──────────────────────────────────────────────────────────────────
# Oracle price zero → market skipped with warning (no silent 1)
# ──────────────────────────────────────────────────────────────────


def _vault_payload(*, oracle_price: int) -> dict:
    return {
        "data": {
            "vaultByAddress": {
                "address": "0xVault",
                "state": {
                    "totalAssets": "1000000000",
                    "totalSupply": "1000000000",
                    "lastTotalAssets": "1000000000",
                    "allocation": [
                        {
                            "market": {
                                "marketId": "0xMkt",
                                "collateralAsset": {
                                    "address": "0xC",
                                    "symbol": "C",
                                    "decimals": 18,
                                },
                                "loanAsset": {
                                    "address": "0xL",
                                    "symbol": "L",
                                    "decimals": 6,
                                },
                                "state": {
                                    "supplyAssets": "1000000000",
                                    "borrowAssets": "500000000",
                                    "collateralAssets": "10",
                                    "price": str(oracle_price),
                                    "utilization": 0.5,
                                },
                                "lltv": str(860 * 10**15),
                            },
                            "supplyAssets": "1000000000",
                            "supplyCap": "2000000000",
                        }
                    ],
                },
            }
        }
    }


def test_parse_response_skips_zero_oracle_price_with_warning():
    payload = _vault_payload(oracle_price=0)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        snap = _parse_response(payload, "0xVault", 0)
    assert snap.markets == []
    assert any("oracle price" in str(w.message) for w in caught)


def test_parse_response_keeps_nonzero_oracle_price():
    payload = _vault_payload(oracle_price=10**36)
    snap = _parse_response(payload, "0xVault", 0)
    assert len(snap.markets) == 1
    assert snap.markets[0].oracle_price_36dec == 10**36


# ──────────────────────────────────────────────────────────────────
# GraphQL `errors` array surfaces with diagnostic context
# ──────────────────────────────────────────────────────────────────


def test_fetch_raises_on_graphql_errors(monkeypatch):
    def fake_post(self, url, json=None):  # noqa: A002
        req = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"errors": [{"message": "Field 'foo' not found"}]},
            request=req,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(ValueError, match="GraphQL returned errors"):
        fetch_vault_snapshot("0xVault")


# ──────────────────────────────────────────────────────────────────
# Retry on 429 / 5xx with bounded backoff
# ──────────────────────────────────────────────────────────────────


def test_fetch_retries_on_500_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(self, url, json=None):  # noqa: A002
        req = httpx.Request("POST", url)
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="upstream", request=req)
        return httpx.Response(200, json=_vault_payload(oracle_price=10**36), request=req)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    # Speed up the test — patch time.sleep to a no-op.
    monkeypatch.setattr("mvcf.fetch.time.sleep", lambda *_: None)

    snap = fetch_vault_snapshot("0xVault")
    assert calls["n"] == 3
    assert snap.total_assets == 1_000_000_000


def test_fetch_retries_exhaust_and_raises(monkeypatch):
    calls = {"n": 0}

    def fake_post(self, url, json=None):  # noqa: A002
        req = httpx.Request("POST", url)
        calls["n"] += 1
        return httpx.Response(429, text="rate-limited", request=req)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr("mvcf.fetch.time.sleep", lambda *_: None)

    with pytest.raises(httpx.HTTPStatusError, match="429"):
        fetch_vault_snapshot("0xVault")
    # 1 initial + 3 retries
    assert calls["n"] == 4


# ──────────────────────────────────────────────────────────────────
# load_history directory layout
# ──────────────────────────────────────────────────────────────────


def test_load_history_directory_layout(tmp_path, monkeypatch):
    fixtures_root = Path(__file__).resolve().parent.parent / "data" / "fixtures"
    # Build a temporary directory layout under a known name
    dir_name = "_tmp_history_test"
    dir_path = fixtures_root / dir_name
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        for block in (100, 200):
            payload = {
                "vault_address": "0xHistVault",
                "block": block,
                "timestamp": 1_000_000 + block,
                "total_assets": 1_000_000,
                "total_shares": 1_000_000,
                "top_depositors": [],
                "markets": [],
                "borrowers": [],
            }
            (dir_path / f"snap_{block}.json").write_text(json.dumps(payload))
        hist = load_history(dir_name)
        assert hist.vault_address == "0xHistVault"
        assert len(hist) == 2
        assert {s.block for s in hist.snapshots} == {100, 200}
    finally:
        # Clean up so subsequent test runs are deterministic
        for f in dir_path.glob("*.json"):
            f.unlink()
        dir_path.rmdir()


def test_load_history_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_history("definitely_does_not_exist_v05")


# ──────────────────────────────────────────────────────────────────
# Synthetic depositor address uniqueness
# ──────────────────────────────────────────────────────────────────


def test_synthetic_depositors_are_unique():
    snap = generate_synthetic_vault(n_markets=3, n_borrowers=50, seed=7)
    addrs = [a for a, _ in snap.top_depositors]
    assert len(addrs) == len(set(addrs)), (
        f"Synthetic vault produced duplicate depositor addresses: {addrs}"
    )
    # Each address must be a valid-length 0x address (42 chars).
    for a in addrs:
        assert len(a) == 42, f"Address {a!r} is {len(a)} chars, expected 42"
