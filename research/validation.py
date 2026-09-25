"""
Canonical Validation Authority.
The ONLY module allowed to issue TARGET_SUPPORTED or TARGET_NOT_ESTABLISHED.

Project goal (binding contract):
  Research and validate an Ethereum paper-trading algorithm targeting at least
  90% winning trades and positive net returns after realistic costs, using
  chronological out-of-sample evaluation and reporting uncertainty honestly.
  Do not claim the target is achieved without evidence or enable real-money trading.

Gate criteria — ALL eight must be satisfied for TARGET_SUPPORTED:
  1. closed_trades >= 100               (minimum sample size)
  2. observed win rate >= 90%
  3. Wilson 95% CI lower bound >= 90%   (standard CI)
  4. Block-bootstrap 95% CI lower >= 90% (dependency-aware CI)
  5. OOS net return > 0
  6. 2x cost-stress OOS net return > 0  (all variable costs doubled)
  7. Strategy source_hash matches manifest (code frozen before OOS)
  8. Dataset SHA-256 matches manifest    (data immutable)

Any single failure produces TARGET_NOT_ESTABLISHED.
"""
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from research.cost_model import CostModel
from research.walk_forward import run_walk_forward_evaluation


# ── Dataset integrity helper ──────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    """Return hex SHA-256 of a file on disk (chunk-reads for large files)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Canonical validation entry point ─────────────────────────────────────────

def validate_strategy_manifest(
    strategy: Any,
    candles: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    cost_model: CostModel,
    dataset_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate a frozen strategy against anchored walk-forward OOS evaluation.

    Parameters
    ----------
    strategy      : Strategy object exposing generate_signal() and get_source_hash().
    candles       : Validated list of candle dicts (already loaded by caller).
    manifest      : Frozen experiment manifest dict (from experiments/manifests/).
    cost_model    : Base cost model (2× stress is derived internally).
    dataset_path  : Path to the dataset file; used for SHA-256 integrity check.
                    If None, the SHA-256 check is skipped but flagged.

    Returns
    -------
    Full validation report dict.  status is one of:
      "TARGET_SUPPORTED"        — all gate criteria satisfied
      "TARGET_NOT_ESTABLISHED"  — one or more criteria failed
    """

    # ── 1. Strategy source hash check ─────────────────────────────────────────
    expected_hash = manifest.get("source_hash")
    actual_hash = strategy.get_source_hash()
    hash_matched = (expected_hash == actual_hash) if expected_hash else False
    hash_note = "" if expected_hash else "source_hash absent from manifest"

    # ── 2. Dataset integrity check ────────────────────────────────────────────
    expected_dataset_sha = manifest.get("dataset_sha256")
    if dataset_path and expected_dataset_sha:
        actual_dataset_sha = sha256_file(dataset_path)
        dataset_sha_matched = (actual_dataset_sha == expected_dataset_sha)
        dataset_sha_note = "" if dataset_sha_matched else "Dataset SHA-256 mismatch — data may have changed"
    elif dataset_path and not expected_dataset_sha:
        actual_dataset_sha = sha256_file(dataset_path)
        dataset_sha_matched = False
        dataset_sha_note = "dataset_sha256 absent from manifest — add it to freeze the data"
    else:
        actual_dataset_sha = None
        dataset_sha_matched = False
        dataset_sha_note = "No dataset_path provided; SHA-256 check skipped"

    # ── 3. Base walk-forward evaluation ───────────────────────────────────────
    base_results = run_walk_forward_evaluation(
        strategy=strategy,
        candles=candles,
        cost_model=cost_model,
        n_folds=5,
        embargo_bars=10,
    )
    base_metrics = base_results["aggregated_oos_metrics"]

    # ── 4. 2× cost-stress evaluation ──────────────────────────────────────────
    stress_cost_model = cost_model.create_2x_stress_model()
    stress_results = run_walk_forward_evaluation(
        strategy=strategy,
        candles=candles,
        cost_model=stress_cost_model,
        n_folds=5,
        embargo_bars=10,
    )
    stress_metrics = stress_results["aggregated_oos_metrics"]

    # ── 5. Extract gate variables ──────────────────────────────────────────────
    closed_trades     = base_metrics["closed_trades"]
    wins              = base_metrics["wins"]
    win_rate_pct      = base_metrics["win_rate_pct"]
    win_rate_95_ci    = base_metrics["win_rate_95_ci"]
    net_return_pct    = base_metrics["net_return_pct"]
    profit_factor     = base_metrics["profit_factor"]
    max_drawdown_pct  = base_metrics["max_drawdown_pct"]

    wilson_ci_lower = win_rate_95_ci[0] if win_rate_95_ci else 0.0
    stressed_net    = stress_metrics["net_return_pct"]

    # Block-bootstrap lower bound (dependency-aware)
    boot_ci = base_metrics.get("block_bootstrap_95_ci") or {}
    boot_wr_ci = boot_ci.get("win_rate_pct") if boot_ci else None
    boot_lower = boot_wr_ci[0] if boot_wr_ci else 0.0

    # ── 6. Target Gate ────────────────────────────────────────────────────────
    target_supported = (
        closed_trades >= 100
        and win_rate_pct is not None
        and win_rate_pct >= 90.0
        and wilson_ci_lower >= 90.0        # Wilson CI (standard)
        and boot_lower >= 90.0             # Block-bootstrap CI (dependency-aware)
        and net_return_pct > 0.0
        and stressed_net > 0.0
        and hash_matched                   # Strategy code was frozen before OOS
        and dataset_sha_matched            # Dataset was immutable
    )

    status = "TARGET_SUPPORTED" if target_supported else "TARGET_NOT_ESTABLISHED"

    return {
        "status": status,
        "target_win_rate_pct": 90,
        "research_only": True,
        "real_money_execution": False,

        "strategy": {
            "name": getattr(strategy, "name", "unknown"),
            "version": getattr(strategy, "version", "1.0"),
            "source_hash_actual": actual_hash,
            "source_hash_manifest": expected_hash,
            "source_hash_matched": hash_matched,
            "note": hash_note,
        },

        "dataset_integrity": {
            "sha256_actual": actual_dataset_sha,
            "sha256_manifest": expected_dataset_sha,
            "matched": dataset_sha_matched,
            "note": dataset_sha_note,
        },

        "oos": {
            "closed_trades": closed_trades,
            "wins": wins,
            "win_rate_pct": win_rate_pct,
            "win_rate_95_ci": win_rate_95_ci,
            "block_bootstrap_95_ci": boot_wr_ci,
            "net_return_pct": net_return_pct,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
        },

        "cost_stress_2x": {
            "net_return_pct": stressed_net,
        },

        "requirements": {
            "minimum_oos_trades": 100,
            "minimum_win_rate_pct": 90,
            "wilson_ci_lower_pct": 90,
            "bootstrap_ci_lower_pct": 90,
            "positive_net_return": True,
            "positive_2x_cost_return": True,
            "strategy_hash_frozen": True,
            "dataset_sha256_frozen": True,
        },

        "target_supported": target_supported,

        "walk_forward_details": {
            "folds": base_results["fold_reports"],
            "aggregated_block_bootstrap_ci": boot_ci,
        },
    }
