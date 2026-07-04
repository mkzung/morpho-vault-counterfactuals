"""Domain models for Morpho MetaMorpho vault state.

A MetaMorpho vault is a curator-managed aggregator that allocates deposits
across multiple Morpho Blue markets. Each market is a (collateral asset, loan
asset, oracle, IRM, LLTV) tuple. Curators set parameters such as supply cap
per market, withdraw queue ordering, and timelock; depositors share P&L
according to their share of total deposits.

Risk evaluation needs four pieces of state:

  1. Vault-level state: total assets, total shares, top-N depositor breakdown.
  2. Market-level state: for each underlying market, supply/borrow assets,
     borrow share, current oracle price, LLTV, supply cap.
  3. Borrower-level state: each position's collateral, debt, current LTV.
  4. Time-series of (1)+(2)+(3) at successive block snapshots.

This module models that state explicitly so detectors can reason over it
without re-doing the on-chain plumbing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field


class MarketState(BaseModel):
    """A single Morpho Blue market the vault is exposed to at one block.

    All asset amounts are in the loan-asset's smallest unit (e.g., USDC has 6
    decimals -> 1_000_000 == 1 USDC). Prices are in 36-decimal Morpho oracle
    convention (oracle.price() returns collateral_units * 10^36 / loan_units).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str = Field(..., description="bytes32 market id, hex")
    block: int
    timestamp: int
    collateral_token: str
    loan_token: str
    total_supply_assets: int = Field(ge=0)
    total_borrow_assets: int = Field(ge=0)
    total_collateral_assets: int = Field(ge=0)
    oracle_price_36dec: int = Field(gt=0, description="Morpho oracle price, 1e36 scale")
    lltv_wad: int = Field(gt=0, lt=10**18, description="LLTV in wad, [0,1e18)")
    supply_cap: int = Field(ge=0, description="vault-level supply cap to this market")

    @property
    def utilization(self) -> float:
        """Borrow / supply utilization.

        Normally in [0, 1]. Values > 1 indicate a bad-debt situation
        (interest-accrued borrows exceed deposits); we DO NOT cap, so the
        signal reaches detectors honestly. Supply=0 returns 0.0 if borrow
        is also 0; otherwise returns inf (protocol-invariant violation
        the curator must see).
        """
        if self.total_supply_assets == 0:
            return float("inf") if self.total_borrow_assets > 0 else 0.0
        return self.total_borrow_assets / self.total_supply_assets

    @property
    def lltv(self) -> float:
        """LLTV as a float in [0,1)."""
        return self.lltv_wad / 10**18


class BorrowerPosition(BaseModel):
    """A single borrower position in one market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str
    borrower: str = Field(..., description="address")
    collateral: int = Field(ge=0)
    debt_assets: int = Field(ge=0, description="debt in loan-asset units")

    def ltv(self, oracle_price_36dec: int) -> float:
        """Current LTV given a Morpho oracle price (36-decimal convention).

        Math: `ltv = debt / (collateral * oracle_price / 1e36)`.
        The 36-decimal price encodes the decimal adjustment between collateral
        and loan tokens, so no separate decimal parameter is needed.

        Returns a float in [0, ∞]:
          - 0 ⟺ no debt (healthy)
          - >0 and <LLTV ⟺ healthy
          - ≥LLTV ⟺ liquidatable
          - inf ⟺ debt with zero collateral (bad-debt invariant violation)
        """
        if self.collateral == 0:
            return float("inf") if self.debt_assets > 0 else 0.0
        denom = self.collateral * oracle_price_36dec
        if denom == 0:
            return float("inf") if self.debt_assets > 0 else 0.0
        return self.debt_assets * 10**36 / denom


class VaultSnapshot(BaseModel):
    """A MetaMorpho vault at a single block.

    Aggregates per-market state and a sample of borrower positions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    vault_address: str
    block: int
    timestamp: int
    total_assets: int = Field(ge=0, description="vault assets, loan-asset units")
    total_shares: int = Field(gt=0)
    loan_symbol: str = Field(
        default="", description="vault loan-asset symbol, e.g. USDC (for display)"
    )
    loan_decimals: int = Field(
        default=0, ge=0, description="vault loan-asset decimals; 0 = unknown"
    )
    top_depositors: list[tuple[str, int]] = Field(
        default_factory=list,
        description="(address, shares) sorted desc, top N",
    )
    markets: list[MarketState] = Field(default_factory=list)
    borrowers: list[BorrowerPosition] = Field(default_factory=list)

    @property
    def hhi(self) -> float:
        """Herfindahl-Hirschman Index of depositor concentration, [0,1]."""
        if self.total_shares == 0 or not self.top_depositors:
            return 0.0
        shares = [s for _, s in self.top_depositors]
        # tail (untracked depositors) - assume single residual bucket
        tail = max(0, self.total_shares - sum(shares))
        all_shares = shares + ([tail] if tail > 0 else [])
        return sum((s / self.total_shares) ** 2 for s in all_shares)

    @property
    def top1_share(self) -> float:
        if not self.top_depositors:
            return 0.0
        return self.top_depositors[0][1] / self.total_shares


@dataclass
class VaultHistory:
    """Ordered series of VaultSnapshots for one vault.

    Treated as an immutable replay log - detectors read but don't mutate.
    """

    vault_address: str
    snapshots: list[VaultSnapshot] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.snapshots)

    def by_block(self, block: int) -> VaultSnapshot | None:
        for s in self.snapshots:
            if s.block == block:
                return s
        return None

    def latest(self) -> VaultSnapshot:
        if not self.snapshots:
            raise ValueError("VaultHistory is empty")
        return max(self.snapshots, key=lambda s: s.block)

    def iter_pairs(self) -> Iterable[tuple[VaultSnapshot, VaultSnapshot]]:
        """Yield (prev, next) consecutive snapshots ordered by block."""
        ordered = sorted(self.snapshots, key=lambda s: s.block)
        for i in range(len(ordered) - 1):
            yield ordered[i], ordered[i + 1]
