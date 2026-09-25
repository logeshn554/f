"""
Walk-forward evaluation engine running anchored 5-fold cross validation.

CAUSALITY RULE (critical):
  Signal is generated from candles[:absolute_index] — that is, all candles
  whose close is *known* before the current bar's open.  The broker then
  executes on candles[absolute_index], entering at that bar's OPEN.
  The current bar's HIGH, LOW, and CLOSE are never visible to the strategy.
"""
import datetime
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
      1. Train/Dev phase  : candles[0 : fold.train_end+1]  (closed, fully known)
      2. Embargo          : fold.train_end+1 … fold.test_start-1  (never touched)
      3. Test/OOS phase   : candles[fold.test_start : fold.test_end+1]

    Causality inside the OOS phase (for bar at absolute_index):
      - history visible to strategy = candles[:absolute_index]
        (the bar whose close triggered the signal is the LAST bar in history;
         the next bar opens after that close — no same-bar peek)
      - broker.step receives candles[absolute_index] and enters at its OPEN.

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
        test_candles = candles[fold.test_start : fold.test_end + 1]
        total_test_bars += len(test_candles)

        broker = PaperBroker(initial_cash=initial_cash, cost_model=cost_model)

        for i in range(len(test_candles)):
            absolute_index = fold.test_start + i

            # ── CAUSALITY BOUNDARY ──────────────────────────────────────────────
            # Strategy may only see candles BEFORE the current bar opens.
            # candles[:absolute_index] gives [0 … absolute_index-1], the last of
            # which closed at the end of bar (absolute_index-1).  The current bar
            # at absolute_index has not yet opened from the strategy's perspective.
            history_subset = candles[:absolute_index]
            signal = strategy.generate_signal(history_subset)

            # Broker receives the full current candle and enters at its OPEN.
            broker.step(test_candles[i], signal)

        # Close any position still open at fold boundary (at last available close)
        if broker.position and test_candles:
            broker.close_position(
                test_candles[-1],
                test_candles[-1]["close"],
                "fold_end",
            )

        fold_metrics = calculate_metrics(
            trades=broker.trades,
            initial_cash=initial_cash,
            total_bars=len(test_candles),
        )

        fold_reports.append({
            "fold_index": fold.fold_index,
            "train_range": (
                candles[fold.train_start]["date"],
                candles[fold.train_end]["date"],
            ),
            "test_range": (
                candles[fold.test_start]["date"],
                candles[fold.test_end]["date"],
            ),
            "embargo_bars": fold.embargo_bars,
            "metrics": fold_metrics,
        })

        for t in broker.trades:
            t["fold_index"] = fold.fold_index
            oos_trades.append(t)

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
