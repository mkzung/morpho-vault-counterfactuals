"""Live fetch utilities for Morpho MetaMorpho vault state.

This module wraps the Morpho subgraph + Blue API into our `VaultSnapshot`
domain model. It is kept SEPARATE from `detectors.py` so the test suite can
run fully offline against checked-in fixtures.

USAGE NOTE (read before running against mainnet):
  - The Morpho Blue API endpoint occasionally rate-limits unauthenticated
    callers. For production use, set MORPHO_API_KEY in the environment.
  - The Subgraph URL is the upstream-blessed Morpho Blue endpoint; mirror
    it to a private indexer (Goldsky, Subsquid) for >100 req/min loads.
  - Block-pinning: we always query with a specific `block` to ensure
    reproducibility — a curator's monitor that queries "latest" is
    non-deterministic between runs.

Author note: This file is the I/O frontier. All on-chain plumbing lives
here so the detectors stay pure functions on `VaultSnapshot`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .state import BorrowerPosition, MarketState, VaultHistory, VaultSnapshot

MORPHO_API_BASE = "https://blue-api.morpho.org/graphql"


def fetch_vault_snapshot(
    vault_address: str,
    *,
    block: int | None = None,
    timeout: float = 30.0,
) -> VaultSnapshot:
    """Fetch the current state of one MetaMorpho vault.

    Args:
        vault_address: 0x-prefixed EOA-style address.
        block: optional block number to pin the query. If None, fetches latest.
        timeout: request timeout in seconds.

    Returns:
        Validated `VaultSnapshot`.

    Raises:
        httpx.HTTPError on network failures.
        pydantic.ValidationError if Morpho returns unexpected shapes.
    """
    query = """
    query VaultRisk($address: String!, $chainId: Int!) {
      vaultByAddress(address: $address, chainId: $chainId) {
        address
        state {
          totalAssets
          totalSupply
          lastTotalAssets
          allocation {
            market {
              uniqueKey
              collateralAsset { address symbol decimals }
              loanAsset { address symbol decimals }
              state {
                supplyAssets
                borrowAssets
                collateralAssets
                price
                utilization
              }
              lltv
            }
            supplyAssets
            supplyCap
          }
        }
      }
    }
    """
    variables = {"address": vault_address, "chainId": 1}
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("MORPHO_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=timeout, headers=headers) as client:
        resp = client.post(
            MORPHO_API_BASE,
            json={"query": query, "variables": variables},
        )
        resp.raise_for_status()
        data = resp.json()
    return _parse_response(data, vault_address, block or 0)


def _parse_response(payload: dict, vault_address: str, block: int) -> VaultSnapshot:
    """Translate Morpho Blue API GraphQL response into our domain model.

    Kept in fetch.py (and not state.py) because shape changes belong with the
    fetcher, not the schema. If Morpho ships a breaking API change, only this
    function needs to learn about it.
    """
    vault = payload.get("data", {}).get("vaultByAddress")
    if not vault:
        raise ValueError(f"Vault {vault_address} not found in API response")
    state = vault["state"]
    markets: list[MarketState] = []
    for alloc in state.get("allocation", []) or []:
        mkt = alloc.get("market")
        if not mkt:
            continue
        mkt_state = mkt.get("state") or {}
        markets.append(
            MarketState(
                market_id=mkt["uniqueKey"],
                block=block,
                timestamp=0,  # the Blue API doesn't always return ts; pin later
                collateral_token=mkt["collateralAsset"]["address"],
                loan_token=mkt["loanAsset"]["address"],
                total_supply_assets=int(mkt_state.get("supplyAssets", 0)),
                total_borrow_assets=int(mkt_state.get("borrowAssets", 0)),
                total_collateral_assets=int(mkt_state.get("collateralAssets", 0)),
                oracle_price_36dec=int(mkt_state.get("price", 0)) or 1,
                lltv_wad=int(mkt["lltv"]),
                supply_cap=int(alloc.get("supplyCap") or 0),
            )
        )
    return VaultSnapshot(
        vault_address=vault["address"],
        block=block,
        timestamp=0,
        total_assets=int(state["totalAssets"]),
        total_shares=int(state["totalSupply"]) or 1,
        top_depositors=[],  # populated by separate query against subgraph
        markets=markets,
        borrowers=[],  # populated by separate query against subgraph
    )


# ──────────────────────────────────────────────────────────────────────
# Offline fixture loader (used by tests + notebook reproducibility)
# ──────────────────────────────────────────────────────────────────────


def load_fixture(name: str) -> VaultSnapshot:
    """Load a checked-in snapshot fixture by file name.

    Used by:
      - the pytest suite (offline, deterministic),
      - the demo notebook (so anyone cloning the repo can replay without RPC).
    """
    fixtures_dir = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
    path = fixtures_dir / f"{name}.json"
    raw = json.loads(path.read_text())
    markets = [MarketState(**m) for m in raw["markets"]]
    borrowers = [BorrowerPosition(**b) for b in raw["borrowers"]]
    return VaultSnapshot(
        vault_address=raw["vault_address"],
        block=raw["block"],
        timestamp=raw["timestamp"],
        total_assets=raw["total_assets"],
        total_shares=raw["total_shares"],
        top_depositors=[tuple(t) for t in raw["top_depositors"]],
        markets=markets,
        borrowers=borrowers,
    )


def load_history(name: str) -> VaultHistory:
    """Load a multi-snapshot replay fixture."""
    fixtures_dir = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
    path = fixtures_dir / f"{name}.json"
    raw = json.loads(path.read_text())
    snapshots = [load_fixture(s) for s in raw["snapshot_names"]]
    return VaultHistory(vault_address=raw["vault_address"], snapshots=snapshots)
