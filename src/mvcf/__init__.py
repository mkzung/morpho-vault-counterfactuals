"""morpho-vault-counterfactuals — historical replay + adverse-scenario stress testing for Morpho MetaMorpho vaults."""

from .detectors import (
    CollateralCascade,
    DepositorExitShock,
    LiquidationLatency,
    LTVDistributionStress,
    OracleFreezeReplay,
    UtilizationInversion,
)
from .diff import VaultDiff, diff_snapshots, summarize_diff
from .fetch import fetch_vault_snapshot, load_fixture, load_history
from .html_report import as_html
from .report import as_json, as_markdown
from .runner import run_all_detectors, summarize
from .state import BorrowerPosition, MarketState, VaultHistory, VaultSnapshot

__version__ = "0.1.0"

__all__ = [
    "BorrowerPosition",
    "CollateralCascade",
    "DepositorExitShock",
    "LTVDistributionStress",
    "LiquidationLatency",
    "MarketState",
    "OracleFreezeReplay",
    "UtilizationInversion",
    "VaultHistory",
    "VaultSnapshot",
    "VaultDiff",
    "as_html",
    "as_json",
    "as_markdown",
    "diff_snapshots",
    "summarize_diff",
    "fetch_vault_snapshot",
    "load_fixture",
    "load_history",
    "run_all_detectors",
    "summarize",
]
