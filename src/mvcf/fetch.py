"""Live fetch utilities for Morpho MetaMorpho vault state.

This module wraps the Morpho subgraph + Blue API into our `VaultSnapshot`
domain model. It is kept SEPARATE from `detectors.py` so the test suite can
run fully offline against checked-in fixtures.

USAGE NOTE (read before running against mainnet):
  - The Morpho Blue API endpoint occasionally rate-limits unauthenticated
    callers. For production use, set MORPHO_API_KEY in the environment.
  - The Subgraph URL is the upstream-blessed Morpho Blue endpoint; mirror
    it to a private indexer (Goldsky, Subsquid) for >100 req/min loads.
  - Block-pinning: the Morpho Blue `vaultByAddress` GraphQL endpoint does
    NOT accept a block argument — it always returns the latest indexed
    state. The `block` parameter on `fetch_vault_snapshot` is metadata
    only (stamped into the returned `VaultSnapshot.block` for audit
    purposes) and does not pin the query. For true block-pinning, query
    a private archival indexer (Goldsky / Subsquid / your own subgraph).
    Fixture-based replay (`load_fixture`) IS block-pinned bit-for-bit.

Author note: This file is the I/O frontier. All on-chain plumbing lives
here so the detectors stay pure functions on `VaultSnapshot`.
"""

from __future__ import annotations

import json
import os
import time
import warnings
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
        block: optional block number, stamped into the returned snapshot's
            metadata for audit purposes. NOTE: the Morpho Blue GraphQL
            endpoint does not accept a block argument, so this does not
            pin the query — see module docstring for the honest story.
        timeout: request timeout in seconds.

    Returns:
        Validated `VaultSnapshot`.

    Raises:
        httpx.HTTPError on network failures (after retries exhausted).
        ValueError if the GraphQL response contains an `errors` array or
            the vault is missing.
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

    # Retry on 429 / 5xx with exponential backoff (1s, 2s, 4s). httpx has no
    # built-in retry policy on POST, so we hand-roll it; keep it bounded so a
    # curator's nightly cron fails loudly rather than hanging for minutes.
    backoffs = [1.0, 2.0, 4.0]
    last_exc: Exception | None = None
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for attempt, sleep_s in enumerate([0.0] + backoffs):
            if sleep_s > 0:
                time.sleep(sleep_s)
            try:
                resp = client.post(
                    MORPHO_API_BASE,
                    json={"query": query, "variables": variables},
                )
                if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                    last_exc = httpx.HTTPStatusError(
                        f"Morpho API returned {resp.status_code} "
                        f"(attempt {attempt + 1}/{len(backoffs) + 1})",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.TransportError as e:
                last_exc = e
                continue
        else:
            assert last_exc is not None
            raise last_exc

    # Surface GraphQL-level errors. The Morpho API returns 200 with an `errors`
    # array on schema/query errors; without this check those failures silently
    # produced empty snapshots — exactly the live-data zeros bug we shipped.
    if isinstance(data, dict) and data.get("errors"):
        raise ValueError(
            f"Morpho GraphQL returned errors for vault {vault_address}: "
            f"{data['errors']!r}"
        )
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
        # Idle markets have null collateralAsset (vault holds the loan asset
        # unallocated). Skip — there's nothing to risk-analyze on a position
        # that has no collateral to liquidate.
        if not mkt.get("collateralAsset") or not mkt.get("loanAsset"):
            continue
        mkt_state = mkt.get("state") or {}
        # LLTV must be strictly < 1e18; skip markets with degenerate metadata.
        lltv = int(mkt.get("lltv", 0) or 0)
        if not (0 < lltv < 10**18):
            continue
        # Skip markets with zero/missing oracle price. Previously this code
        # substituted 1 for a missing price, which silently produced garbage
        # LTV math (debt × 10^36 / 1 ≈ infinity on every position). Better to
        # drop the market with a warning so the curator sees the gap.
        raw_price = mkt_state.get("price", 0) or 0
        oracle_price = int(raw_price)
        if oracle_price <= 0:
            warnings.warn(
                f"Skipping market {mkt.get('uniqueKey')!r}: "
                f"oracle price is {raw_price!r} (zero/missing). "
                "This usually means the oracle is unset, paused, or the API "
                "is returning a stub. Inspect the oracle contract before "
                "trusting any detector output for this vault.",
                stacklevel=2,
            )
            continue
        markets.append(
            MarketState(
                market_id=mkt["uniqueKey"],
                block=block,
                timestamp=0,  # the Blue API doesn't always return ts; pin later
                collateral_token=mkt["collateralAsset"]["address"],
                loan_token=mkt["loanAsset"]["address"],
                total_supply_assets=int(mkt_state.get("supplyAssets", 0) or 0),
                total_borrow_assets=int(mkt_state.get("borrowAssets", 0) or 0),
                total_collateral_assets=int(mkt_state.get("collateralAssets", 0) or 0),
                oracle_price_36dec=oracle_price,
                lltv_wad=lltv,
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
    """Load a multi-snapshot replay fixture.

    Supports two on-disk layouts:

      1. A single index fixture `data/fixtures/<name>.json` containing keys
         `{"vault_address": "0x...", "snapshot_names": ["snap1", "snap2"]}`,
         where each `snap_i` is itself a fixture file in the same directory.
      2. A directory `data/fixtures/<name>/` with `*.json` files, each a
         full `VaultSnapshot` payload sharing the same `vault_address`.

    Raises:
        FileNotFoundError if neither layout exists.
        ValueError if the snapshots in a directory layout disagree on
            `vault_address`.
    """
    fixtures_dir = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"
    index_path = fixtures_dir / f"{name}.json"
    dir_path = fixtures_dir / name

    if index_path.exists():
        raw = json.loads(index_path.read_text())
        snapshots = [load_fixture(s) for s in raw["snapshot_names"]]
        return VaultHistory(vault_address=raw["vault_address"], snapshots=snapshots)

    if dir_path.is_dir():
        snapshots = []
        for child in sorted(dir_path.glob("*.json")):
            # `load_fixture` expects a name (no .json suffix) relative to the
            # fixtures root — reconstruct from the relative path.
            rel = child.relative_to(fixtures_dir).with_suffix("")
            snapshots.append(load_fixture(str(rel)))
        if not snapshots:
            raise FileNotFoundError(f"No *.json snapshots found in {dir_path}")
        addrs = {s.vault_address for s in snapshots}
        if len(addrs) != 1:
            raise ValueError(
                f"Snapshots in {dir_path} disagree on vault_address: {addrs}"
            )
        return VaultHistory(vault_address=snapshots[0].vault_address, snapshots=snapshots)

    raise FileNotFoundError(
        f"No history fixture named '{name}' (looked for "
        f"{index_path} and {dir_path}/)"
    )
