"""morpho-vault-counterfactuals — historical replay + adverse-scenario stress testing for Morpho MetaMorpho vaults."""

from .detectors import (
    CollateralCascade,
    DepositorExitShock,
    LiquidationLatency,
    LTVDistributionStress,
    OracleFreezeReplay,
    UtilizationInversion,
)
from .fetch import load_fixture, load_history
from .runner import run_all_detectors
from .state import MarketState, VaultHistory, VaultSnapshot

__version__ = "0.1.0"

__all__ = [
    "VaultSnapshot",
    "MarketState",
    "VaultHistory",
    "load_fixture",
    "load_history",
    "OracleFreezeReplay",
    "CollateralCascade",
    "DepositorExitShock",
    "UtilizationInversion",
    "LiquidationLatency",
    "LTVDistributionStress",
    "run_all_detectors",
]
