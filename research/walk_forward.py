"""Walk-forward evaluation engine running anchored 5-fold cross validation."""
from typing import Any, Dict, List
from paper.broker import PaperBroker
from paper.market_data import validate_candles
from research.chronological_split import create_anchored_folds
from research.cost_model import CostModel
from research.metrics import calculate_metrics


def run_walk_forward_evaluation(
    strategy: Any,
    candles: List[Dict[str, Any]],
    cost_model: CostModel,
    n_folds: int = 5,
    embargo_bars: int = 10,
    initial_cash: float = 10000.0,
) -> Dict[str, Any]:
    """
    Execute anchored walk-forward cross validation over n_folds.
    For each fold:
      1. Train/Dev phase: past candles up to fold.train_end
      2. Test phase: out-of-sample candles from fold.test_start to fold.test_end
      3. Embargo period separating train and test is strictly enforced.
    Aggregates all closed OOS trades across folds.
    """
    candles = validate_candles(candles, min_candles=100)
    folds = create_anchored_folds(
        total_bars=len(candles),
        n_folds=n_folds,
        min_train_bars=100,
        embargo_bars=embargo_bars,
    )

    oos_trades: List[Dict[str, Any]] = []
    fold_reports: List[Dict[str, Any]] = []
    total_test_bars = 0

    for fold in folds:
        # Out-of-sample test evaluation
        test_candles = candles[fold.test_start : fold.test_end + 1]
        total_test_bars += len(test_candles)

        broker = PaperBroker(initial_cash=initial_cash, cost_model=cost_model)

        for i in range(len(test_candles)):
            # Strategy peeks only at historical candles available up to fold.test_start + i
            history_subset = candles[: fold.test_start + i + 1]
            signal = strategy.generate_signal(history_subset)
            broker.step(test_candles[i], signal)

        # Close any open position at end of fold
        if broker.position and test_candles:
            broker.close_position(test_candles[-1], test_candles[-1]["close"], "fold_end")

        fold_metrics = calculate_metrics(
            trades=broker.trades,
            initial_cash=initial_cash,
            total_bars=len(test_candles),
        )

        fold_reports.append({
            "fold_index": fold.fold_index,
            "train_range": (candles[fold.train_start]["date"], candles[fold.train_end]["date"]),
            "test_range": (candles[fold.test_start]["date"], candles[fold.test_end]["date"]),
            "embargo_bars": fold.embargo_bars,
            "metrics": fold_metrics,
        })

        # Tag trades with fold index and collect
        for t in broker.trades:
            t["fold_index"] = fold.fold_index
            oos_trades.append(t)

    # Compute overall aggregated OOS metrics across all folds
    aggregated_metrics = calculate_metrics(
        trades=oos_trades,
        initial_cash=initial_cash,
        total_bars=total_test_bars,
    )

    return {
        "n_folds": n_folds,
        "embargo_bars": embargo_bars,
        "total_oos_bars": total_test_bars,
        "fold_reports": fold_reports,
        "aggregated_oos_metrics": aggregated_metrics,
        "oos_trades": oos_trades,
    }
