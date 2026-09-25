"""
Canonical Validation Authority.
The ONLY authority allowed to issue TARGET_SUPPORTED or TARGET_NOT_ESTABLISHED.
"""
from typing import Any, Dict, List
from research.cost_model import CostModel
from research.walk_forward import run_walk_forward_evaluation


def validate_strategy_manifest(
    strategy: Any,
    candles: List[Dict[str, Any]],
    manifest: Dict[str, Any],
    cost_model: CostModel,
) -> Dict[str, Any]:
    """
    Validate a frozen strategy manifest against anchored walk-forward cross validation
    and a 2x cost stress test. Evaluates strict Target Gate criteria.
    """
    # Verify strategy freeze / source hash
    expected_hash = manifest.get("source_hash")
    actual_hash = strategy.get_source_hash()
    hash_matched = (expected_hash == actual_hash) if expected_hash else True

    # 1. Base Walk-Forward Evaluation
    base_results = run_walk_forward_evaluation(
        strategy=strategy,
        candles=candles,
        cost_model=cost_model,
        n_folds=5,
        embargo_bars=10,
    )
    base_metrics = base_results["aggregated_oos_metrics"]

    # 2. 2x Cost Stress Test
    stress_cost_model = cost_model.create_2x_stress_model()
    stress_results = run_walk_forward_evaluation(
        strategy=strategy,
        candles=candles,
        cost_model=stress_cost_model,
        n_folds=5,
        embargo_bars=10,
    )
    stress_metrics = stress_results["aggregated_oos_metrics"]

    # Target Gate Metrics Extraction
    closed_trades = base_metrics["closed_trades"]
    wins = base_metrics["wins"]
    win_rate_pct = base_metrics["win_rate_pct"]
    win_rate_95_ci = base_metrics["win_rate_95_ci"]
    net_return_pct = base_metrics["net_return_pct"]
    profit_factor = base_metrics["profit_factor"]
    max_drawdown_pct = base_metrics["max_drawdown_pct"]

    ci_lower = win_rate_95_ci[0] if win_rate_95_ci else 0.0
    stressed_net_return_pct = stress_metrics["net_return_pct"]

    # Target Gate Decision Logic
    target_supported = (
        closed_trades >= 100
        and (win_rate_pct is not None and win_rate_pct >= 90.0)
        and (ci_lower >= 90.0)
        and (net_return_pct > 0.0)
        and (stressed_net_return_pct > 0.0)
        and hash_matched
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
            "source_hash": actual_hash,
            "manifest_hash_matched": hash_matched,
        },
        "oos": {
            "closed_trades": closed_trades,
            "wins": wins,
            "win_rate_pct": win_rate_pct,
            "win_rate_95_ci": win_rate_95_ci,
            "net_return_pct": net_return_pct,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
        },
        "cost_stress_2x": {
            "net_return_pct": stressed_net_return_pct,
        },
        "requirements": {
            "minimum_oos_trades": 100,
            "minimum_win_rate_pct": 90,
            "positive_net_return": True,
            "positive_2x_cost_return": True,
        },
        "target_supported": target_supported,
        "walk_forward_details": {
            "folds": base_results["fold_reports"],
            "block_bootstrap_95_ci": base_metrics.get("block_bootstrap_95_ci"),
        },
    }
