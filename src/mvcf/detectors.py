"""Counterfactual detectors for Morpho MetaMorpho vault risk.

Each detector takes the current `VaultSnapshot` (and optionally a `VaultHistory`)
and computes what *would have* happened under one specific adverse counterfactual
— oracle freeze, collateral cascade, top-depositor exit, etc.

Design goals (informed by the Inca Challenge #492 forensic framework — same
six-detector + reproducible-replay shape, applied to a new domain):

  - Pure functions on snapshots → no live RPC inside detectors, all I/O in fetch.py.
  - Each detector returns a `DetectorResult` with a single headline number plus
    an `evidence` dict for the curator to inspect.
  - Risk is reported as fractional bad-debt or fractional-impairment, not
    "good/bad" labels — Re7-style: curators decide thresholds.
  - All detectors are deterministic given (snapshot, params).

References:
  - Morpho Blue whitepaper (LLTV, liquidation incentive multiplier)
  - MetaMorpho v1.1 documentation (supply cap, reallocation queue)
  - @morpho-org/vault-risk-sdk (concentration HHI definition)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state import VaultSnapshot

# ──────────────────────────────────────────────────────────────────────
# Common types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DetectorResult:
    """Output of a single detector on one snapshot."""

    name: str
    headline_metric: float
    headline_unit: str
    interpretation: str
    evidence: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# 1. Oracle freeze replay
# ──────────────────────────────────────────────────────────────────────


class OracleFreezeReplay:
    """What fraction of debt becomes bad debt if oracle freezes for N blocks
    while collateral drifts by `drift_pct`?

    Curator interpretation: an oracle stuck at a stale price during a fast
    market move is the most common pre-liquidation failure mode. We measure
    the gap between the on-paper LTV (using stale oracle) and the "true" LTV
    (using shocked price) for every borrower. Borrowers whose true LTV
    exceeds LLTV+liquidation-incentive cushion are *unliquidatable* in the
    window and represent unrealized bad debt.
    """

    def __init__(self, drift_pct: float = -0.10, liquidation_incentive: float = 0.05):
        # drift_pct: how much true collateral price moves while oracle is stale
        # liquidation_incentive: Morpho default ~5% for major assets
        if not -0.99 < drift_pct < 0.99:
            raise ValueError(f"drift_pct must be in (-0.99, 0.99), got {drift_pct}")
        self.drift_pct = drift_pct
        self.liquidation_incentive = liquidation_incentive

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        unhealthy_debt = 0
        total_debt = 0
        unliquidatable_count = 0
        per_market: dict[str, dict[str, int]] = {}

        markets_by_id = {m.market_id: m for m in snapshot.markets}

        for pos in snapshot.borrowers:
            mkt = markets_by_id.get(pos.market_id)
            if mkt is None:
                continue
            # True LTV after price drift (oracle still reports old price)
            true_oracle = int(mkt.oracle_price_36dec * (1 + self.drift_pct))
            if true_oracle <= 0:
                true_oracle = 1
            true_ltv = pos.ltv(true_oracle)
            # Liquidation threshold (LLTV + incentive cushion)
            liq_threshold = mkt.lltv * (1 + self.liquidation_incentive)
            total_debt += pos.debt_assets
            if true_ltv > liq_threshold:
                unhealthy_debt += pos.debt_assets
                unliquidatable_count += 1
                bucket = per_market.setdefault(
                    pos.market_id,
                    {"unhealthy_debt": 0, "count": 0},
                )
                bucket["unhealthy_debt"] += pos.debt_assets
                bucket["count"] += 1

        fraction = (unhealthy_debt / total_debt) if total_debt > 0 else 0.0
        return DetectorResult(
            name="OracleFreezeReplay",
            headline_metric=fraction,
            headline_unit="fraction_bad_debt",
            interpretation=(
                f"If oracle freezes while collateral drifts {self.drift_pct:+.0%}, "
                f"{fraction:.1%} of outstanding debt ({unliquidatable_count} positions) "
                f"would breach liquidation threshold but remain unliquidatable until "
                f"oracle updates."
            ),
            evidence={
                "drift_pct": self.drift_pct,
                "liquidation_incentive": self.liquidation_incentive,
                "unhealthy_debt_assets": unhealthy_debt,
                "total_debt_assets": total_debt,
                "unliquidatable_positions": unliquidatable_count,
                "per_market": per_market,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 2. Collateral cascade
# ──────────────────────────────────────────────────────────────────────


class CollateralCascade:
    """Step-shock the collateral price by `shock_pct` and count liquidations.

    A live curator wants to know: at -10% / -20% / -30% collateral price
    cliffs, how much of the vault's exposure goes underwater, and is there
    enough loan-asset liquidity in the market to absorb the liquidation
    outflow without socializing bad debt to depositors?
    """

    def __init__(self, shock_pct: float = -0.20):
        if not -0.99 < shock_pct < 0.0:
            raise ValueError(f"shock_pct must be a negative fraction in (-0.99, 0), got {shock_pct}")
        self.shock_pct = shock_pct

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        liquidatable_debt = 0
        total_debt = 0
        liquidity_gap = 0
        per_market: dict[str, dict[str, int]] = {}

        markets_by_id = {m.market_id: m for m in snapshot.markets}

        for pos in snapshot.borrowers:
            mkt = markets_by_id.get(pos.market_id)
            if mkt is None:
                continue
            shocked_oracle = max(1, int(mkt.oracle_price_36dec * (1 + self.shock_pct)))
            ltv_after = pos.ltv(shocked_oracle)
            total_debt += pos.debt_assets
            if ltv_after > mkt.lltv:
                liquidatable_debt += pos.debt_assets
                bucket = per_market.setdefault(
                    pos.market_id,
                    {"liquidatable_debt": 0, "available_liquidity": 0},
                )
                bucket["liquidatable_debt"] += pos.debt_assets

        # Liquidity gap: do the markets have enough idle supply to absorb the wave?
        for mkt_id, bucket in per_market.items():
            mkt = markets_by_id[mkt_id]
            idle = max(0, mkt.total_supply_assets - mkt.total_borrow_assets)
            bucket["available_liquidity"] = idle
            gap = max(0, bucket["liquidatable_debt"] - idle)
            liquidity_gap += gap
            bucket["liquidity_gap"] = gap

        fraction_liquidatable = (
            (liquidatable_debt / total_debt) if total_debt > 0 else 0.0
        )
        return DetectorResult(
            name="CollateralCascade",
            headline_metric=fraction_liquidatable,
            headline_unit="fraction_liquidatable_debt",
            interpretation=(
                f"At a {self.shock_pct:+.0%} collateral shock, {fraction_liquidatable:.1%} "
                f"of debt becomes liquidatable; liquidity gap (debt minus idle supply) is "
                f"{liquidity_gap:,} loan-asset units across affected markets."
            ),
            evidence={
                "shock_pct": self.shock_pct,
                "liquidatable_debt_assets": liquidatable_debt,
                "total_debt_assets": total_debt,
                "liquidity_gap": liquidity_gap,
                "per_market": per_market,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 3. Top depositor exit shock
# ──────────────────────────────────────────────────────────────────────


class DepositorExitShock:
    """If the top-N depositors withdraw simultaneously, does the vault
    have liquid (i.e., non-borrowed) supply in its markets to honor the
    redemption? If not, the vault enters withdraw-queue rationing.
    """

    def __init__(self, top_n: int = 1):
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        self.top_n = top_n

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        # Approximate exit demand in loan-asset units
        if snapshot.total_shares == 0:
            return DetectorResult(
                name="DepositorExitShock",
                headline_metric=0.0,
                headline_unit="fraction_rationed",
                interpretation="No shares outstanding.",
                evidence={"top_n": self.top_n},
            )
        top_shares = sum(s for _, s in snapshot.top_depositors[: self.top_n])
        exit_demand = int(snapshot.total_assets * top_shares / snapshot.total_shares)

        idle_supply = sum(
            max(0, m.total_supply_assets - m.total_borrow_assets) for m in snapshot.markets
        )

        rationing_gap = max(0, exit_demand - idle_supply)
        fraction_rationed = (rationing_gap / exit_demand) if exit_demand > 0 else 0.0

        return DetectorResult(
            name="DepositorExitShock",
            headline_metric=fraction_rationed,
            headline_unit="fraction_rationed",
            interpretation=(
                f"If top-{self.top_n} depositor(s) exit, demand is {exit_demand:,} "
                f"vs idle supply {idle_supply:,} → {fraction_rationed:.1%} would be "
                f"queue-rationed until borrowers repay."
            ),
            evidence={
                "top_n": self.top_n,
                "exit_demand_loan_assets": exit_demand,
                "idle_supply_loan_assets": idle_supply,
                "rationing_gap": rationing_gap,
                "hhi": snapshot.hhi,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 4. Utilization inversion
# ──────────────────────────────────────────────────────────────────────


class UtilizationInversion:
    """Highlights markets where utilization is already above the curator's
    target band — a precursor to interest-rate spirals and rationing.
    """

    def __init__(self, target_util_max: float = 0.92):
        if not 0.0 < target_util_max < 1.0:
            raise ValueError("target_util_max must be in (0,1)")
        self.target_util_max = target_util_max

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        breached = [m for m in snapshot.markets if m.utilization > self.target_util_max]
        return DetectorResult(
            name="UtilizationInversion",
            headline_metric=len(breached) / max(1, len(snapshot.markets)),
            headline_unit="fraction_markets_above_target",
            interpretation=(
                f"{len(breached)} / {len(snapshot.markets)} markets are above the "
                f"{self.target_util_max:.0%} utilization band — IRM curves enter the "
                f"steep regime; depositor withdrawal pressure compounds."
            ),
            evidence={
                "target_util_max": self.target_util_max,
                "breached_markets": [
                    {"market_id": m.market_id, "utilization": m.utilization}
                    for m in breached
                ],
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 5. Liquidation latency
# ──────────────────────────────────────────────────────────────────────


class LiquidationLatency:
    """Estimate the latency window between an oracle update that pushes a
    position underwater and the first profitable liquidation, given gas
    economics and minimum-profit thresholds.

    Returns: estimated fraction of debt where post-gas profit is *negative*
    for a liquidator at the assumed gas price — meaning the position sits
    underwater longer than ideal and accrues bad debt risk.
    """

    def __init__(
        self,
        gas_price_gwei: float = 30.0,
        liquidation_gas: int = 350_000,
        eth_price_usd: float = 3500.0,
    ):
        self.gas_price_gwei = gas_price_gwei
        self.liquidation_gas = liquidation_gas
        self.eth_price_usd = eth_price_usd

    def _liquidation_cost_usd(self) -> float:
        return (
            self.gas_price_gwei * 1e-9 * self.liquidation_gas * self.eth_price_usd
        )

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        cost_usd = self._liquidation_cost_usd()
        # For each borrower, profitable liquidation = debt * liquidation_incentive (5%)
        # We approximate debt in USD by treating loan-asset units 1:1 USD
        # (true for USDC/DAI-loan vaults; documented assumption for the demo).
        unprofitable_count = 0
        unprofitable_debt = 0
        total_debt = 0
        for pos in snapshot.borrowers:
            total_debt += pos.debt_assets
            # Convert assuming USDC 6-decimal as the demo case
            debt_usd = pos.debt_assets / 1e6
            profit_usd = debt_usd * 0.05
            if profit_usd < cost_usd:
                unprofitable_count += 1
                unprofitable_debt += pos.debt_assets

        fraction = (unprofitable_debt / total_debt) if total_debt > 0 else 0.0
        return DetectorResult(
            name="LiquidationLatency",
            headline_metric=fraction,
            headline_unit="fraction_unprofitable_to_liquidate",
            interpretation=(
                f"At {self.gas_price_gwei:.0f} gwei and ETH ${self.eth_price_usd:.0f}, "
                f"liquidation cost is ~${cost_usd:.2f}; "
                f"{fraction:.1%} of debt sits in positions where liquidation profit < cost "
                f"({unprofitable_count} small positions) — these accrue bad-debt risk "
                f"during oracle-shock windows."
            ),
            evidence={
                "gas_price_gwei": self.gas_price_gwei,
                "eth_price_usd": self.eth_price_usd,
                "cost_per_liquidation_usd": cost_usd,
                "unprofitable_positions": unprofitable_count,
                "unprofitable_debt_assets": unprofitable_debt,
                "total_debt_assets": total_debt,
            },
        )


# ──────────────────────────────────────────────────────────────────────
# 6. LTV distribution stress
# ──────────────────────────────────────────────────────────────────────


class LTVDistributionStress:
    """Reports the LTV distribution percentiles vs each market's LLTV.

    A vault is healthier when most borrowers sit far below LLTV (long buffer
    before a price drop puts them underwater). The 99th-percentile distance
    to LLTV is the metric most curators monitor weekly.
    """

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        markets_by_id = {m.market_id: m for m in snapshot.markets}

        ltvs: list[float] = []
        buffers: list[float] = []
        for pos in snapshot.borrowers:
            mkt = markets_by_id.get(pos.market_id)
            if mkt is None:
                continue
            ltv = pos.ltv(mkt.oracle_price_36dec)
            if ltv > 0:
                ltvs.append(ltv)
                buffers.append(max(0.0, mkt.lltv - ltv))

        if not ltvs:
            return DetectorResult(
                name="LTVDistributionStress",
                headline_metric=0.0,
                headline_unit="fraction_near_lltv",
                interpretation="No borrower positions to analyze.",
                evidence={},
            )

        ltvs_sorted = sorted(ltvs, reverse=True)
        top_5pct_idx = max(1, len(ltvs_sorted) * 5 // 100)
        top_5pct_avg = sum(ltvs_sorted[:top_5pct_idx]) / top_5pct_idx

        # Headline: fraction of debt held by borrowers within 5pp of LLTV
        # (a small adverse move would liquidate them).
        near_lltv_debt = 0
        total_debt = 0
        for pos in snapshot.borrowers:
            mkt = markets_by_id.get(pos.market_id)
            if mkt is None:
                continue
            total_debt += pos.debt_assets
            if mkt.lltv - pos.ltv(mkt.oracle_price_36dec) < 0.05:
                near_lltv_debt += pos.debt_assets

        fraction = (near_lltv_debt / total_debt) if total_debt > 0 else 0.0

        return DetectorResult(
            name="LTVDistributionStress",
            headline_metric=fraction,
            headline_unit="fraction_debt_within_5pp_of_lltv",
            interpretation=(
                f"{fraction:.1%} of outstanding debt sits within 5 percentage points "
                f"of LLTV. Top-5% LTV avg: {top_5pct_avg:.2%}. "
                f"A small adverse oracle move would push this debt into liquidation."
            ),
            evidence={
                "top_5pct_ltv_avg": top_5pct_avg,
                "median_ltv": ltvs_sorted[len(ltvs_sorted) // 2],
                "n_positions": len(ltvs_sorted),
                "near_lltv_debt": near_lltv_debt,
                "total_debt_assets": total_debt,
            },
        )


# Helper type alias for the runner
Detector = (
    OracleFreezeReplay
    | CollateralCascade
    | DepositorExitShock
    | UtilizationInversion
    | LiquidationLatency
    | LTVDistributionStress
)
