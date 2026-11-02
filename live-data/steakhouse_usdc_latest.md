# Vault risk brief: `0xBEEF...64CB`

- **Block:** n/a (Blue API response is not block-pinned)
- **Total assets:** 63.47M USDC (`63,472,560,095,746` USDC units)
- **Markets:** 11
- **Borrowers analyzed:** 1,000 (largest by debt; API max 1000/query), covering 99.9% of the 522.56M USDC of open debt in the markets this vault lends into.
  Borrower positions are *market-wide*: a MetaMorpho vault supplies into shared Morpho Blue markets, so these are all borrowers of those markets, not only debt funded by this vault. That is why market debt can exceed the vault's own assets.
- **HHI (depositor concentration):** `0.238` (top-1 = 45.8%)

## Headline counterfactual risk

| Detector | Metric | Unit |
|---|---:|---|
| `OracleFreezeReplay` | `0.000` | fraction_bad_debt |
| `CollateralCascade` | `0.132` | fraction_liquidatable_debt |
| `DepositorExitShock` | `0.002` | fraction_rationed |
| `UtilizationInversion` | `0.909` | fraction_markets_above_target |
| `LiquidationLatency` | `0.000` | fraction_unprofitable_to_liquidate |
| `LTVDistributionStress` | `0.001` | fraction_debt_within_5pp_of_lltv |

## Per-detector findings

### OracleFreezeReplay

If the oracle freezes while collateral drifts -10%, 0.0% of outstanding debt (2 positions) crosses the bad-debt frontier - LTV > 0.952 at LIF 5% - meaning seized collateral could not cover debt-plus-incentive even once the oracle updates.

<details><summary>Evidence</summary>

```json
{
  "drift_pct": -0.1,
  "bad_debt_lif": 0.05,
  "bad_debt_frontier_ltv": 0.9523809523809523,
  "bad_debt_assets": 184207774291,
  "total_debt_assets": 522279775826873,
  "bad_debt_positions": 2,
  "per_market": {
    "0xc498f4bfdda99e60ea8eb04c1e145654a70bc59da76ef9c6ed54a1314d78e5b5": {
      "bad_debt_assets": 184207774291,
      "count": 2
    }
  }
}
```

</details>

### CollateralCascade

At a -20% collateral shock, 13.2% of debt becomes liquidatable; liquidity gap (debt minus idle supply) is 44,203,087,217,678 loan-asset units across affected markets.

<details><summary>Evidence</summary>

```json
{
  "shock_pct": -0.2,
  "liquidatable_debt_assets": 69052246753263,
  "total_debt_assets": 522279775826873,
  "liquidity_gap": 44203087217678,
  "per_market": {
    "0x3a85e619751152991742810df6ec69ce473daef99e28a64ab2340d7b7ccfee49": {
      "liquidatable_debt": 25670958332357,
      "available_liquidity": 9066959678117,
      "liquidity_gap": 16603998654240
    },
    "0x64d65c9a2d91c36d56fbc42d69e979335320169b3df63bf92789e2c8883fcc64": {
      "liquidatable_debt": 23808425635594,
      "available_liquidity": 11983155693112,
      "liquidity_gap": 11825269942482
    },
    "0x7e585a933ffe8443c371b4f8cfeb4430f5f6a14c2f32a898c26662c67a1cb8b8": {
      "liquidatable_debt": 5990059633641,
      "available_liquidity": 882524533408,
      "liquidity_gap": 5107535100233
    },
    "0xc498f4bfdda99e60ea8eb04c1e145654a70bc59da76ef9c6ed54a1314d78e5b5": {
      "liquidatable_debt": 10441081417294,
      "available_liquidity": 740317916218,
      "liquidity_gap": 9700763501076
    },
    "0xb323495f7e4148be5643a4ea4a8221eef163e4bccfdedc2a6f4696baacbc86cc": {
      "liquidatable_debt": 1423017947161,
      "available_liquidity": 2986715120808,
      "liquidity_gap": 0
    },
    "0x94b823e6bd8ea533b4e33fbc307faea0b307301bc48763acc4d4aa4def7636cd": {
      "liquidatable_debt": 1436837842958,
      "available_liquidity": 672221863693,
      "liquidity_gap": 764615979265
    },
    "0xbc99de6a88904cd0e69042ad6f266e63182801f030c636507c3caf590ffd84fe": {
      "liquidatable_debt": 276192292726,
      "available_liquidity": 75288252344,
      "liquidity_gap": 200904040382
    },
    "0x09dc9e7eb5d8fc54b2bc41d1135fd4e99057a580f680321faeb90c7a21e631c1": {
      "liquidatable_debt": 5673651532,
      "available_liquidity": 106303834303,
      "liquidity_gap": 0
    }
  }
}
```

</details>

### DepositorExitShock

If top-1 depositor(s) exit, demand is 29,075,753,343,270 vs idle supply 29,004,549,445,553 -> 0.2% would be queue-rationed until borrowers repay.

<details><summary>Evidence</summary>

```json
{
  "top_n": 1,
  "exit_demand_loan_assets": 29075753343270,
  "idle_supply_loan_assets": 29004549445553,
  "rationing_gap": 71203897717,
  "hhi": 0.2376214324819053
}
```

</details>

### UtilizationInversion

10 / 11 markets are above the 92% utilization band - IRM curves enter the steep regime; depositor withdrawal pressure compounds.

<details><summary>Evidence</summary>

```json
{
  "target_util_max": 0.92,
  "breached_markets": [
    {
      "market_id": "0x85252bb8485c99bba46fe149c7dd2aad83672640f53c630890673cf1848ba16e",
      "utilization": 0.9338384526605322
    },
    {
      "market_id": "0xfb8d92086861bae6fb778917afd1de5dbbc4ec70edfb636fed48238e225e7e3d",
      "utilization": 0.9400827906956836
    },
    {
      "market_id": "0x3a85e619751152991742810df6ec69ce473daef99e28a64ab2340d7b7ccfee49",
      "utilization": 0.9310482427383386
    },
    {
      "market_id": "0x7e585a933ffe8443c371b4f8cfeb4430f5f6a14c2f32a898c26662c67a1cb8b8",
      "utilization": 0.9312880225746523
    },
    {
      "market_id": "0xc498f4bfdda99e60ea8eb04c1e145654a70bc59da76ef9c6ed54a1314d78e5b5",
      "utilization": 0.9361070783298987
    },
    {
      "market_id": "0x94b823e6bd8ea533b4e33fbc307faea0b307301bc48763acc4d4aa4def7636cd",
      "utilization": 0.9306669791408216
    },
    {
      "market_id": "0x09dc9e7eb5d8fc54b2bc41d1135fd4e99057a580f680321faeb90c7a21e631c1",
      "utilization": 0.9312999958518965
    },
    {
      "market_id": "0xbc99de6a88904cd0e69042ad6f266e63182801f030c636507c3caf590ffd84fe",
      "utilization": 0.9344144378246242
    },
    {
      "market_id": "0x64d65c9a2d91c36d56fbc42d69e979335320169b3df63bf92789e2c8883fcc64",
      "utilization": 0.9616091245503925
    },
    {
      "market_id": "0x34377fc4f617c51818e92c79df31ff270c6a91bc94ad32e367fdf59b9f4ac5dd",
      "utilization": 0.9960262482481486
    }
  ]
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
  "total_debt_assets": 522279775826873
}
```

</details>

### LTVDistributionStress

0.1% of outstanding debt sits within 5 percentage points of LLTV. Top-5% LTV avg: 77.53%. A small adverse oracle move would push this debt into liquidation.

<details><summary>Evidence</summary>

```json
{
  "top_5pct_ltv_avg": 0.7753131053596931,
  "median_ltv": 0.48022638062811274,
  "n_positions": 1000,
  "near_lltv_debt": 401625232715,
  "total_debt_assets": 522279775826873
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