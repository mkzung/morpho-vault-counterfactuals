"""Synthetic snapshot generator — for performance benchmarking and unit testing.

Real Morpho MetaMorpho vaults can have thousands of borrower positions. The
detectors are O(borrowers × markets), so this module exists to verify the
framework scales acceptably and to power `pytest-benchmark` regressions.

The generator uses a deterministic random seed so test outputs are stable.
"""

from __future__ import annotations

import random

from .state import BorrowerPosition, MarketState, VaultSnapshot


def generate_synthetic_vault(
    n_markets: int = 5,
    n_borrowers: int = 500,
    seed: int = 42,
) -> VaultSnapshot:
    """Generate a deterministic synthetic vault snapshot.

    Args:
        n_markets: number of markets the vault is exposed to.
        n_borrowers: total borrower positions across all markets.
        seed: random seed for reproducibility.

    Returns:
        A self-consistent `VaultSnapshot` with realistic decimal scaling
        (USDC 6dec loan asset, mixed 8/18-decimal collaterals).
    """
    rng = random.Random(seed)

    markets: list[MarketState] = []
    for i in range(n_markets):
        # Half 18-dec ETH-like collateral, half 8-dec BTC-like
        collateral_dec = 18 if i % 2 == 0 else 8
        # Real price between 1000 and 5000 USDC per collateral unit
        real_price = rng.uniform(1000, 5000)
        # Morpho oracle convention
        oracle_price = int(real_price * 10 ** (36 + 6 - collateral_dec))
        # LLTV between 70% and 95%
        lltv = int(rng.uniform(0.70, 0.95) * 10**18)
        supply = rng.randint(10_000_000_000_000, 100_000_000_000_000)
        borrow = int(supply * rng.uniform(0.30, 0.92))
        markets.append(
            MarketState(
                market_id=f"0x{i:064x}",
                block=20_000_000,
                timestamp=1_716_000_000,
                collateral_token=f"0x{'C' * 39}{i}",
                loan_token="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                total_supply_assets=supply,
                total_borrow_assets=borrow,
                total_collateral_assets=rng.randint(1, 10**24),
                oracle_price_36dec=oracle_price,
                lltv_wad=lltv,
                supply_cap=int(supply * 1.2),
            )
        )

    # Map market id → collateral decimals (set when the market was constructed)
    market_decimals = {m.market_id: (18 if i % 2 == 0 else 8) for i, m in enumerate(markets)}

    borrowers: list[BorrowerPosition] = []
    for i in range(n_borrowers):
        mkt = rng.choice(markets)
        # Mix of healthy + near-LLTV borrowers
        target_ltv = rng.uniform(0.20, mkt.lltv * 0.99)
        collateral_units = market_decimals[mkt.market_id]
        collateral = rng.randint(10**collateral_units, 10**collateral_units * 1000)
        debt = int(collateral * mkt.oracle_price_36dec * target_ltv / 10**36)
        if debt > 0:
            borrowers.append(
                BorrowerPosition(
                    market_id=mkt.market_id,
                    # Pad each borrower address distinctly (was: collisions every 256)
                    borrower=f"0x{i:040x}",
                    collateral=collateral,
                    debt_assets=debt,
                )
            )

    total_assets = sum(m.total_supply_assets for m in markets)
    return VaultSnapshot(
        vault_address="0x" + "1" * 38 + "AA",
        block=20_000_000,
        timestamp=1_716_000_000,
        total_assets=total_assets,
        total_shares=total_assets,
        top_depositors=[
            # Unique 42-char hex addresses per i (previously truncated → all 10
            # depositors had the same address, breaking concentration metrics).
            (f"0xDEAD{i:036x}", total_assets // (i + 1) // 10) for i in range(10)
        ],
        markets=markets,
        borrowers=borrowers,
    )
