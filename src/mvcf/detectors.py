"""Counterfactual detectors for Morpho MetaMorpho vault risk.

Each detector takes the current `VaultSnapshot` (and optionally a `VaultHistory`)
and computes what *would have* happened under one specific adverse counterfactual
- oracle freeze, collateral cascade, top-depositor exit, etc.

Design goals (informed by the Inca Challenge #492 forensic framework - same
six-detector + reproducible-replay shape, applied to a new domain):

  - Pure functions on snapshots -> no live RPC inside detectors, all I/O in fetch.py.
  - Each detector returns a `DetectorResult` with a single headline number plus
    an `evidence` dict for the curator to inspect.
  - Risk is reported as fractional bad-debt or fractional-impairment, not
    "good/bad" labels - Re7-style: curators decide thresholds.
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

# --- Common types ---


@dataclass(frozen=True)
class DetectorResult:
    """Output of a single detector on one snapshot."""

    name: str
    headline_metric: float
    headline_unit: str
    interpretation: str
    evidence: dict[str, Any] = field(default_factory=dict)


# --- 1. Oracle freeze replay ---


class OracleFreezeReplay:
    """What fraction of debt becomes **bad debt** if the oracle freezes while
    the true collateral price falls by `drift_pct`?

    Curator interpretation: an oracle stuck at a stale price during a fast
    market move is the most common pre-liquidation failure mode. With the
    oracle stuck, liquidators see no signal - but the *true* solvency of
    the position has degraded. A position becomes **uneconomic to liquidate
    even when the oracle eventually updates** when the true LTV exceeds
    `1 / (1 + LIF)` (typically ~0.952 at 5% LIF), because the seized
    collateral is then worth less than the debt being repaid net of
    liquidator incentive. That is the bad-debt frontier this detector
    measures.

    Args:
      drift_pct: signed collateral price drift while oracle is stale.
        Negative for downside scenarios (the common case); positive
        rejected because positive drift cannot create bad debt.
      bad_debt_lif: Morpho Liquidation Incentive Factor - bonus paid to
        the liquidator on seized collateral. Default 0.05 (the typical
        major-asset LIF on Morpho Blue); set per-market for safer assets.
    """

    def __init__(self, drift_pct: float = -0.10, bad_debt_lif: float = 0.05):
        if not -0.99 < drift_pct <= 0.0:
            raise ValueError(f"drift_pct must be in (-0.99, 0.0], got {drift_pct}")
        if not 0.0 < bad_debt_lif < 1.0:
            raise ValueError(f"bad_debt_lif must be in (0, 1), got {bad_debt_lif}")
        self.drift_pct = drift_pct
        self.bad_debt_lif = bad_debt_lif

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        bad_debt = 0
        total_debt = 0
        bad_debt_positions = 0
        per_market: dict[str, dict[str, int]] = {}

        # Bad-debt frontier: collateral_value < debt × (1 + LIF) means the
        # liquidator gets less collateral than debt-with-incentive.
        # Equivalently, position is bad-debt when LTV > 1 / (1 + LIF).
        bad_debt_ltv = 1.0 / (1.0 + self.bad_debt_lif)

        markets_by_id = {m.market_id: m for m in snapshot.markets}

        for pos in snapshot.borrowers:
            mkt = markets_by_id.get(pos.market_id)
            if mkt is None:
                continue
            # True LTV at the shocked price (oracle still reports old price)
            true_oracle = max(1, int(mkt.oracle_price_36dec * (1 + self.drift_pct)))
            true_ltv = pos.ltv(true_oracle)
            total_debt += pos.debt_assets
            if true_ltv > bad_debt_ltv:
                bad_debt += pos.debt_assets
                bad_debt_positions += 1
                bucket = per_market.setdefault(
                    pos.market_id,
                    {"bad_debt_assets": 0, "count": 0},
                )
                bucket["bad_debt_assets"] += pos.debt_assets
                bucket["count"] += 1

        fraction = (bad_debt / total_debt) if total_debt > 0 else 0.0
        pos_word = "position" if bad_debt_positions == 1 else "positions"
        return DetectorResult(
            name="OracleFreezeReplay",
            headline_metric=fraction,
            headline_unit="fraction_bad_debt",
            interpretation=(
                f"If the oracle freezes while collateral drifts {self.drift_pct:+.0%}, "
                f"{fraction:.1%} of outstanding debt ({bad_debt_positions} {pos_word}) "
                f"crosses the bad-debt frontier - LTV > {bad_debt_ltv:.3f} at "
                f"LIF {self.bad_debt_lif:.0%} - meaning seized collateral could not "
                f"cover debt-plus-incentive even once the oracle updates."
            ),
            evidence={
                "drift_pct": self.drift_pct,
                "bad_debt_lif": self.bad_debt_lif,
                "bad_debt_frontier_ltv": bad_debt_ltv,
                "bad_debt_assets": bad_debt,
                "total_debt_assets": total_debt,
                "bad_debt_positions": bad_debt_positions,
                "per_market": per_market,
            },
        )


# --- 2. Collateral cascade ---


class CollateralCascade:
    """Step-shock the collateral price by `shock_pct` and count liquidations.

    A live curator wants to know: at -10% / -20% / -30% collateral price
    cliffs, how much of the vault's exposure goes underwater, and is there
    enough loan-asset liquidity in the market to absorb the liquidation
    outflow without socializing bad debt to depositors?
    """

    def __init__(self, shock_pct: float = -0.20):
        if not -0.99 < shock_pct < 0.0:
            raise ValueError(
                f"shock_pct must be a negative fraction in (-0.99, 0), got {shock_pct}"
            )
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

        fraction_liquidatable = (liquidatable_debt / total_debt) if total_debt > 0 else 0.0
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


# --- 3. Top depositor exit shock ---


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
                f"vs idle supply {idle_supply:,} -> {fraction_rationed:.1%} would be "
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


# --- 4. Utilization inversion ---


class UtilizationInversion:
    """Highlights markets where utilization is already above the curator's
    target band - a precursor to interest-rate spirals and rationing.
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
                f"{self.target_util_max:.0%} utilization band - IRM curves enter the "
                f"steep regime; depositor withdrawal pressure compounds."
            ),
            evidence={
                "target_util_max": self.target_util_max,
                "breached_markets": [
                    {"market_id": m.market_id, "utilization": m.utilization} for m in breached
                ],
            },
        )


# --- 5. Liquidation latency ---


class LiquidationLatency:
    """Estimate the fraction of debt sitting in positions too small to be
    profitably liquidated at the current gas price.

    A liquidator's profit per call is `debt × LIF × loan_price_usd` and
    cost is `gas_price × gas_used × eth_price_usd`. Below the breakeven,
    positions linger underwater and accrue bad-debt risk during oracle
    update lags.

    Args:
      gas_price_gwei: assumed gas price in gwei.
      liquidation_gas: gas units per liquidation call (Morpho Blue ~350k).
      eth_price_usd: ETH price for the gas-cost USD conversion.
      lif: Liquidation Incentive Factor - bonus paid to liquidator.
      loan_decimals: decimals of the vault's loan asset. Default 6 (USDC).
      loan_price_usd: USD price of the loan asset. Default 1.0 (stablecoin
        vaults). Override for WETH-/DAI-denominated vaults.
    """

    def __init__(
        self,
        gas_price_gwei: float = 30.0,
        liquidation_gas: int = 350_000,
        eth_price_usd: float = 3500.0,
        lif: float = 0.05,
        loan_decimals: int = 6,
        loan_price_usd: float = 1.0,
    ):
        if gas_price_gwei <= 0:
            raise ValueError(f"gas_price_gwei must be > 0, got {gas_price_gwei}")
        if not 0.0 < lif < 1.0:
            raise ValueError(f"lif must be in (0,1), got {lif}")
        if loan_decimals < 0:
            raise ValueError(f"loan_decimals must be >= 0, got {loan_decimals}")
        self.gas_price_gwei = gas_price_gwei
        self.liquidation_gas = liquidation_gas
        self.eth_price_usd = eth_price_usd
        self.lif = lif
        self.loan_decimals = loan_decimals
        self.loan_price_usd = loan_price_usd

    def _liquidation_cost_usd(self) -> float:
        return self.gas_price_gwei * 1e-9 * self.liquidation_gas * self.eth_price_usd

    def run(self, snapshot: VaultSnapshot) -> DetectorResult:
        cost_usd = self._liquidation_cost_usd()
        loan_unit = 10**self.loan_decimals

        unprofitable_count = 0
        unprofitable_debt = 0
        total_debt = 0
        for pos in snapshot.borrowers:
            total_debt += pos.debt_assets
            debt_usd = pos.debt_assets / loan_unit * self.loan_price_usd
            profit_usd = debt_usd * self.lif
            if profit_usd < cost_usd:
                unprofitable_count += 1
                unprofitable_debt += pos.debt_assets

        fraction = (unprofitable_debt / total_debt) if total_debt > 0 else 0.0
        pos_word = "position" if unprofitable_count == 1 else "positions"
        return DetectorResult(
            name="LiquidationLatency",
            headline_metric=fraction,
            headline_unit="fraction_unprofitable_to_liquidate",
            interpretation=(
                f"At {self.gas_price_gwei:.0f} gwei and ETH ${self.eth_price_usd:.0f}, "
                f"liquidation cost is ~${cost_usd:.2f}; "
                f"{fraction:.1%} of debt sits in {unprofitable_count} {pos_word} where "
                f"liquidator profit (debt × {self.lif:.0%}) is below cost - these accrue "
                f"bad-debt risk during oracle-shock windows."
            ),
            evidence={
                "gas_price_gwei": self.gas_price_gwei,
                "eth_price_usd": self.eth_price_usd,
                "lif": self.lif,
                "loan_decimals": self.loan_decimals,
                "loan_price_usd": self.loan_price_usd,
                "cost_per_liquidation_usd": cost_usd,
                "unprofitable_positions": unprofitable_count,
                "unprofitable_debt_assets": unprofitable_debt,
                "total_debt_assets": total_debt,
            },
        )


# --- 6. LTV distribution stress ---


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
                headline_unit="fraction_debt_within_5pp_of_lltv",
                interpretation=(
                    "No borrower positions in the snapshot - LTV distribution "
                    "is undefined, so this detector reads zero."
                ),
                evidence={"n_positions": 0},
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
