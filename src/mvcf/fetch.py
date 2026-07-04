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
    NOT accept a block argument - it always returns the latest indexed
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
    fetch_positions: bool = True,
) -> VaultSnapshot:
    """Fetch the current state of one MetaMorpho vault.

    Args:
        vault_address: 0x-prefixed EOA-style address.
        block: optional block number, stamped into the returned snapshot's
            metadata for audit purposes. NOTE: the Morpho Blue GraphQL
            endpoint does not accept a block argument, so this does not
            pin the query - see module docstring for the honest story.
        timeout: request timeout in seconds.
        fetch_positions: if True (default), also fetch the vault's top
            depositors and borrower positions via the Blue API
            vaultPositions / marketPositions queries. Best-effort: a
            position-fetch failure degrades to a warning, not an error.

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
              marketId
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
    with httpx.Client(timeout=timeout, headers=_auth_headers()) as client:
        data = _post_graphql(client, query, variables, ctx=f"vault {vault_address}")
    snapshot = _parse_response(data, vault_address, block or 0)
    if fetch_positions and snapshot.markets:
        snapshot = _enrich_positions(snapshot, timeout=timeout)
    return snapshot


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
    # A MetaMorpho vault has a single underlying loan asset shared by every
    # market it allocates to; capture its symbol/decimals for human-readable
    # reports (the raw integer amounts are in this asset's smallest unit).
    loan_symbol = ""
    loan_decimals = 0
    for alloc in state.get("allocation", []) or []:
        mkt = alloc.get("market")
        if not mkt:
            continue
        # Idle markets have null collateralAsset (vault holds the loan asset
        # unallocated). Skip - there's nothing to risk-analyze on a position
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
                f"Skipping market {mkt.get('marketId')!r}: "
                f"oracle price is {raw_price!r} (zero/missing). "
                "This usually means the oracle is unset, paused, or the API "
                "is returning a stub. Inspect the oracle contract before "
                "trusting any detector output for this vault.",
                stacklevel=2,
            )
            continue
        if not loan_symbol:
            loan_asset = mkt["loanAsset"]
            loan_symbol = loan_asset.get("symbol") or ""
            loan_decimals = int(loan_asset.get("decimals") or 0)
        markets.append(
            MarketState(
                market_id=mkt["marketId"],
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
        loan_symbol=loan_symbol,
        loan_decimals=loan_decimals,
        top_depositors=[],  # enriched by _enrich_positions (Blue API vaultPositions)
        markets=markets,
        borrowers=[],  # enriched by _enrich_positions (Blue API marketPositions)
    )


# --- Position enrichment: top depositors + per-market borrowers (Blue API) ---
#
# The Morpho Blue GraphQL API DOES expose per-user positions through the
# `vaultPositions` (depositors) and `marketPositions` (borrowers) queries; no
# private subgraph is required. These are fetched separately from the vault
# query and are best-effort: if the position endpoints fail or rate-limit, the
# core vault/market snapshot is still returned so market-level detectors run.

_DEPOSITORS_QUERY = """
query Depositors($vault: String!, $chainId: Int!, $first: Int!) {
  vaultPositions(
    first: $first, orderBy: Shares, orderDirection: Desc,
    where: { vaultAddress_in: [$vault], chainId_in: [$chainId], shares_gte: "1" }
  ) { items { user { address } state { shares } } }
}
"""

_BORROWERS_QUERY = """
query Borrowers($keys: [String!]!, $chainId: Int!, $first: Int!) {
  marketPositions(
    first: $first, orderBy: BorrowShares, orderDirection: Desc,
    where: { marketUniqueKey_in: $keys, chainId_in: [$chainId], borrowShares_gte: "1" }
  ) { items { user { address } market { marketId } state { collateral borrowAssets } } }
}
"""


def _auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("MORPHO_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# The Blue API rejects `first` > 1000 with a BAD_USER_INPUT error, so every
# paged query is clamped to this ceiling. We do not paginate: a single vault's
# markets have not exceeded 1000 open debt positions in practice, and the
# top-1000 by borrowShares captures ~all of the market debt (the residual tail
# is dust). If a future vault crosses 1000, add cursor pagination here.
_API_FIRST_MAX = 1000

# Bounded retry on 429 / 5xx (httpx has no built-in POST retry policy). Shared
# by the vault query and the position queries so both degrade the same way on a
# rate-limited nightly cron rather than one silently returning empty.
_BACKOFFS = (1.0, 2.0, 4.0)


def _post_graphql(
    client: httpx.Client,
    query: str,
    variables: dict,
    *,
    retry: bool = True,
    ctx: str = "",
) -> dict:
    """POST a GraphQL query with bounded 429/5xx retry; surface 200-with-`errors`.

    `ctx` is folded into the error message (e.g. ``"vault 0x.."``) so a caller
    can tell which query failed. Set ``retry=False`` to disable backoff (used in
    tests to keep them fast).
    """
    backoffs = _BACKOFFS if retry else ()
    last_exc: Exception | None = None
    for attempt, sleep_s in enumerate((0.0, *backoffs)):
        if sleep_s > 0:
            time.sleep(sleep_s)
        try:
            resp = client.post(
                MORPHO_API_BASE, json={"query": query, "variables": variables}
            )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                last_exc = httpx.HTTPStatusError(
                    f"Morpho API returned {resp.status_code} "
                    f"(attempt {attempt + 1}/{len(backoffs) + 1})",
                    request=resp.request,
                    response=resp,
                )
                continue
            resp.raise_for_status()
            data = resp.json()
        except httpx.TransportError as e:
            last_exc = e
            continue
        if isinstance(data, dict) and data.get("errors"):
            where = f" for {ctx}" if ctx else ""
            raise ValueError(
                f"Morpho GraphQL returned errors{where}: {data['errors']!r}"
            )
        return data
    assert last_exc is not None
    raise last_exc


def fetch_positions(
    vault_address: str,
    market_ids: list[str],
    *,
    chain_id: int = 1,
    top_n_depositors: int = 25,
    max_borrowers: int = 1000,
    timeout: float = 30.0,
) -> tuple[list[tuple[str, int]], list[BorrowerPosition]]:
    """Fetch a vault's top depositors (by shares) and largest borrower positions.

    Uses the public Morpho Blue API `vaultPositions` / `marketPositions`
    endpoints (no private subgraph). Returns ``(top_depositors, borrowers)``
    where ``top_depositors`` is a ``(address, shares)`` list sorted descending
    and ``borrowers`` are the largest open debt positions across ``market_ids``.
    """
    top_n_depositors = min(top_n_depositors, _API_FIRST_MAX)
    max_borrowers = min(max_borrowers, _API_FIRST_MAX)
    with httpx.Client(timeout=timeout, headers=_auth_headers()) as client:
        dep = _post_graphql(
            client, _DEPOSITORS_QUERY,
            {"vault": vault_address, "chainId": chain_id, "first": top_n_depositors},
            ctx="depositors",
        )
        dep_items = ((dep.get("data") or {}).get("vaultPositions") or {}).get("items") or []
        top_depositors: list[tuple[str, int]] = []
        for it in dep_items:
            addr = (it.get("user") or {}).get("address")
            shares = (it.get("state") or {}).get("shares")
            if addr and shares is not None:
                top_depositors.append((addr, int(shares)))

        borrowers: list[BorrowerPosition] = []
        if market_ids:
            bor = _post_graphql(
                client, _BORROWERS_QUERY,
                {"keys": market_ids, "chainId": chain_id, "first": max_borrowers},
                ctx="borrowers",
            )
            bor_items = ((bor.get("data") or {}).get("marketPositions") or {}).get("items") or []
            for it in bor_items:
                addr = (it.get("user") or {}).get("address")
                mid = (it.get("market") or {}).get("marketId")
                st = it.get("state") or {}
                coll, debt = st.get("collateral"), st.get("borrowAssets")
                if addr and mid and coll is not None and debt is not None:
                    borrowers.append(
                        BorrowerPosition(
                            market_id=mid, borrower=addr,
                            collateral=int(coll), debt_assets=int(debt),
                        )
                    )
    return top_depositors, borrowers


def _enrich_positions(snapshot: VaultSnapshot, *, timeout: float = 30.0) -> VaultSnapshot:
    """Return a copy of `snapshot` with `top_depositors` + `borrowers` populated.

    Best-effort: on any position-fetch failure, emit a warning and return the
    original vault/market snapshot unchanged so market-level detectors still run.
    """
    try:
        top_depositors, borrowers = fetch_positions(
            snapshot.vault_address,
            [m.market_id for m in snapshot.markets],
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - position enrichment is non-critical
        warnings.warn(
            f"Position enrichment failed ({exc!r}); returning the vault/market "
            "snapshot without depositor/borrower detail.",
            stacklevel=2,
        )
        return snapshot
    return snapshot.model_copy(
        update={"top_depositors": top_depositors, "borrowers": borrowers}
    )


# --- Offline fixture loader (used by tests + notebook reproducibility) ---


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
        loan_symbol=raw.get("loan_symbol", ""),
        loan_decimals=raw.get("loan_decimals", 0),
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
            # fixtures root - reconstruct from the relative path.
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
