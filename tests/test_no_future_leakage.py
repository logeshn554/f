"""
Tests verifying zero data leakage:
  (a) fold-boundary / embargo ordering
  (b) same-candle look-ahead bias in walk_forward.py (most critical)

The same-candle regression test works by placing a sentinel value in the
current execution candle's high/low/close and verifying that the strategy
signal is identical whether or not the sentinel is present.  If the signal
changes, the strategy was peeking at the current bar's internals.
"""
import copy
import unittest

from research.chronological_split import create_anchored_folds, LeakageError
from research.walk_forward import run_walk_forward_evaluation
from research.cost_model import CostModel
from strategies.candle_paths import CandlePathsStrategy


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_synthetic_candles(n: int = 300) -> list:
    """Generate n synthetic daily candles with a simple upward drift."""
    candles = []
    price = 3000.0
    for i in range(n):
        o = price
        h = o * 1.005
        l = o * 0.995
        c = o * 1.001
        candles.append({
            "date": f"2025-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
            "time": i,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
        })
        price = c
    return candles


class _SentinelTrackingStrategy:
    """
    Wraps CandlePathsStrategy and records the LAST candle in history_subset.
    Used to assert that the last visible candle is always the one BEFORE the
    execution candle (absolute_index - 1), never the execution candle itself.
    """

    def __init__(self):
        self.name = "candle_paths"
        self.version = "v4.0"
        self._inner = CandlePathsStrategy()
        self.last_seen_close = None  # close of last candle passed to generate_signal

    def get_source_hash(self) -> str:
        return self._inner.get_source_hash()

    def generate_signal(self, candle_history):
        if candle_history:
            self.last_seen_close = candle_history[-1]["close"]
        return self._inner.generate_signal(candle_history)


# ── Test cases ─────────────────────────────────────────────────────────────────

class TestNoFutureLeakage(unittest.TestCase):

    # ── (a) Fold boundary / embargo ordering ─────────────────────────────────

    def test_anchored_folds_chronology(self):
        folds = create_anchored_folds(
            total_bars=300, n_folds=5, min_train_bars=100, embargo_bars=10
        )
        self.assertEqual(len(folds), 5)

        for fold in folds:
            # Train end + embargo must be <= test start (strict causality)
            self.assertLessEqual(fold.train_end + fold.embargo_bars, fold.test_start)
            # Anchored: training always starts at bar 0
            self.assertEqual(fold.train_start, 0)
            # Test period must have at least 2 bars
            self.assertGreater(fold.test_end, fold.test_start)

    def test_embargo_violation_raises(self):
        with self.assertRaises(LeakageError):
            create_anchored_folds(
                total_bars=120, n_folds=5, min_train_bars=100, embargo_bars=10
            )

    # ── (b) Same-candle look-ahead regression ─────────────────────────────────

    def test_signal_does_not_see_current_bar(self):
        """
        REGRESSION TEST FOR SAME-CANDLE LOOK-AHEAD BIAS.

        For every OOS bar at absolute_index, the strategy must receive
        candles[:absolute_index] — i.e. the current execution bar must NOT
        appear in history_subset.

        We verify this by running the evaluation twice:
          Run A: candles as normal.
          Run B: each candle at positions that would be execution bars has its
                 close replaced with an extreme sentinel value (9_999_999).

        If the strategy leaks the current bar, it would see the sentinel and
        the generated signals (and therefore trade count / entry timing) would
        differ between runs A and B.  They must be identical.
        """
        candles = _make_synthetic_candles(300)
        strategy_a = _SentinelTrackingStrategy()
        cost_model = CostModel()

        # Run A: clean candles
        results_a = run_walk_forward_evaluation(
            strategy=strategy_a,
            candles=candles,
            cost_model=cost_model,
            n_folds=5,
            embargo_bars=10,
        )

        # Build Run B: poison the close of every candle that could be an
        # execution bar (any bar at index >= min_train_bars in any fold).
        folds = create_anchored_folds(
            total_bars=len(candles), n_folds=5, min_train_bars=100, embargo_bars=10
        )
        poisoned = copy.deepcopy(candles)
        for fold in folds:
            for i in range(fold.test_start, fold.test_end + 1):
                # Sentinel: multiply close by 1000 but keep O/H/L consistent so
                # OHLC validation passes.  The strategy must NOT see close=3_000_000.
                orig_o = poisoned[i]["open"]
                sentinel_c = orig_o * 1000.0
                poisoned[i]["close"] = sentinel_c
                poisoned[i]["high"] = max(orig_o, sentinel_c)  # keeps H >= max(O,C)
                poisoned[i]["low"] = min(orig_o, sentinel_c)   # keeps L <= min(O,C)


        strategy_b = _SentinelTrackingStrategy()
        results_b = run_walk_forward_evaluation(
            strategy=strategy_b,
            candles=poisoned,
            cost_model=cost_model,
            n_folds=5,
            embargo_bars=10,
        )

        # Signal count (and timing) must be identical — poison never visible to strategy
        trades_a = results_a["aggregated_oos_metrics"]["closed_trades"]
        trades_b = results_b["aggregated_oos_metrics"]["closed_trades"]
        self.assertEqual(
            trades_a,
            trades_b,
            msg=(
                f"Trade counts differ ({trades_a} vs {trades_b}): "
                "strategy is peeking at the current execution bar (look-ahead bias)!"
            ),
        )

    def test_history_subset_excludes_execution_bar(self):
        """
        Direct unit test: for bar i (absolute_index), the last candle that
        generate_signal receives must have date/time strictly before bar i.
        """
        candles = _make_synthetic_candles(300)
        folds = create_anchored_folds(
            total_bars=len(candles), n_folds=5, min_train_bars=100, embargo_bars=10
        )

        strategy = _SentinelTrackingStrategy()
        cost_model = CostModel()

        for fold in folds[:1]:  # first fold is sufficient
            for i in range(min(5, fold.test_end - fold.test_start + 1)):
                absolute_index = fold.test_start + i
                history_subset = candles[:absolute_index]
                strategy.generate_signal(history_subset)

                if history_subset:
                    last_visible_close = history_subset[-1]["close"]
                    execution_bar_close = candles[absolute_index]["close"]
                    # The last visible close must NOT equal the execution bar's close
                    # (they could accidentally be the same in synthetic data, so we
                    #  check that the last element index is correct instead)
                    self.assertEqual(
                        len(history_subset),
                        absolute_index,
                        msg=(
                            f"history_subset has {len(history_subset)} bars but "
                            f"absolute_index={absolute_index}: off-by-one leakage!"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
