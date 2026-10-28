# Vault risk brief: `0xBEEF...64CB`

- **Block:** n/a (Blue API response is not block-pinned)
- **Total assets:** 64.18M USDC (`64,180,207,275,985` USDC units)
- **Markets:** 11
- **Borrowers analyzed:** 1,000 (largest by debt; API max 1000/query), covering 100.0% of the 541.45M USDC of open debt in the markets this vault lends into.
  Borrower positions are *market-wide*: a MetaMorpho vault supplies into shared Morpho Blue markets, so these are all borrowers of those markets, not only debt funded by this vault. That is why market debt can exceed the vault's own assets.
- **HHI (depositor concentration):** `0.241` (top-1 = 46.3%)

## Headline counterfactual risk

| Detector | Metric | Unit |
|---|---:|---|
| `OracleFreezeReplay` | `0.001` | fraction_bad_debt |
| `CollateralCascade` | `0.100` | fraction_liquidatable_debt |
| `DepositorExitShock` | `0.000` | fraction_rationed |
| `UtilizationInversion` | `0.000` | fraction_markets_above_target |
| `LiquidationLatency` | `0.000` | fraction_unprofitable_to_liquidate |
| `LTVDistributionStress` | `0.001` | fraction_debt_within_5pp_of_lltv |

## Per-detector findings

### OracleFreezeReplay

If the oracle freezes while collateral drifts -10%, 0.1% of outstanding debt (3 positions) crosses the bad-debt frontier - LTV > 0.952 at LIF 5% - meaning seized collateral could not cover debt-plus-incentive even once the oracle updates.

<details><summary>Evidence</summary>

```json
{
  "drift_pct": -0.1,
  "bad_debt_lif": 0.05,
  "bad_debt_frontier_ltv": 0.9523809523809523,
  "bad_debt_assets": 342850077605,
  "total_debt_assets": 541257423275572,
  "bad_debt_positions": 3,
  "per_market": {
    "0xc498f4bfdda99e60ea8eb04c1e145654a70bc59da76ef9c6ed54a1314d78e5b5": {
      "bad_debt_assets": 342850077605,
      "count": 3
    }
  }
}
```

</details>

### CollateralCascade

At a -20% collateral shock, 10.0% of debt becomes liquidatable; liquidity gap (debt minus idle supply) is 23,531,223,903,039 loan-asset units across affected markets.

<details><summary>Evidence</summary>

```json
{
  "shock_pct": -0.2,
  "liquidatable_debt_assets": 53929372033091,
  "total_debt_assets": 541257423275572,
  "liquidity_gap": 23531223903039,
  "per_market": {
    "0x3a85e619751152991742810df6ec69ce473daef99e28a64ab2340d7b7ccfee49": {
      "liquidatable_debt": 21424108763858,
      "available_liquidity": 12737572296572,
      "liquidity_gap": 8686536467286
    },
    "0x7e585a933ffe8443c371b4f8cfeb4430f5f6a14c2f32a898c26662c67a1cb8b8": {
      "liquidatable_debt": 5788658692768,
      "available_liquidity": 1254924731291,
      "liquidity_gap": 4533733961477
    },
    "0xc498f4bfdda99e60ea8eb04c1e145654a70bc59da76ef9c6ed54a1314d78e5b5": {
      "liquidatable_debt": 10836289893117,
      "available_liquidity": 1189633824945,
      "liquidity_gap": 9646656068172
    },
    "0x64d65c9a2d91c36d56fbc42d69e979335320169b3df63bf92789e2c8883fcc64": {
      "liquidatable_debt": 12612927330905,
      "available_liquidity": 34164581309549,
      "liquidity_gap": 0
    },
    "0xb323495f7e4148be5643a4ea4a8221eef163e4bccfdedc2a6f4696baacbc86cc": {
      "liquidatable_debt": 1585919498851,
      "available_liquidity": 3972476980124,
      "liquidity_gap": 0
    },
    "0x94b823e6bd8ea533b4e33fbc307faea0b307301bc48763acc4d4aa4def7636cd": {
      "liquidatable_debt": 1495741080891,
      "available_liquidity": 900997430680,
      "liquidity_gap": 594743650211
    },
    "0xbc99de6a88904cd0e69042ad6f266e63182801f030c636507c3caf590ffd84fe": {
      "liquidatable_debt": 179787095565,
      "available_liquidity": 110233339672,
      "liquidity_gap": 69553755893
    },
    "0x09dc9e7eb5d8fc54b2bc41d1135fd4e99057a580f680321faeb90c7a21e631c1": {
      "liquidatable_debt": 5939677136,
      "available_liquidity": 152178708393,
      "liquidity_gap": 0
    }
  }
}
```

</details>

### DepositorExitShock

If top-1 depositor(s) exit, demand is 29,683,490,659,313 vs idle supply 59,839,525,459,048 -> 0.0% would be queue-rationed until borrowers repay.

<details><summary>Evidence</summary>

```json
{
  "top_n": 1,
  "exit_demand_loan_assets": 29683490659313,
  "idle_supply_loan_assets": 59839525459048,
  "rationing_gap": 0,
  "hhi": 0.24143377323797074
}
```

</details>

### UtilizationInversion

0 / 11 markets are above the 92% utilization band - IRM curves enter the steep regime; depositor withdrawal pressure compounds.

<details><summary>Evidence</summary>

```json
{
  "target_util_max": 0.92,
  "breached_markets": []
}
```

</details>

### LiquidationLatency

At 30 gwei and ETH $3500, liquidation cost is ~$36.75; 0.0% of debt sits in 0 positions where liquidator profit (debt × 5%) is below cost - these accrue bad-debt risk during oracle-shock windows.

<details><summary>Evidence</summary>

```json
{
  "gas_price_gwei": 30.0,
  "eth_price_usd": 3500.0,
  "lif": 0.05,
  "loan_decimals": 6,
  "loan_price_usd": 1.0,
  "cost_per_liquidation_usd": 36.75,
  "unprofitable_positions": 0,
  "unprofitable_debt_assets": 0,
  "total_debt_assets": 541257423275572
}
```

</details>

### LTVDistributionStress

0.1% of outstanding debt sits within 5 percentage points of LLTV. Top-5% LTV avg: 76.52%. A small adverse oracle move would push this debt into liquidation.

<details><summary>Evidence</summary>

```json
{
  "top_5pct_ltv_avg": 0.7652429398765753,
  "median_ltv": 0.46621675514704597,
  "n_positions": 1000,
  "near_lltv_debt": 270682832986,
  "total_debt_assets": 541257423275572
}
```

</details>

## Suggested curator actions

- If `OracleFreezeReplay` headline > 5% - review oracle update cadence + consider Chainlink fallback or oracle-router timeout.
- If `CollateralCascade` headline > 30% at -20% shock - lower LLTV on the concentrated market(s) by 1-3 percentage points.
- If `DepositorExitShock` headline > 20% rationing - reduce vault-level supply cap to that market to free idle supply.
- If `UtilizationInversion` flags ≥ 50% of markets - raise IRM upper rate or reallocate via the MetaMorpho `reallocate()` flow.
- If `LiquidationLatency` headline > 5% - raise the minimum-position-size threshold (cap supply on markets where dust positions accumulate).
- If `LTVDistributionStress` shows >40% of debt within 5pp of LLTV - lower LLTV proactively before the next adverse oracle move.

---

*Generated by [morpho-vault-counterfactuals](https://github.com/mkzung/morpho-vault-counterfactuals).*