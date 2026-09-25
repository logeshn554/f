"""Tests for walk-forward execution engine."""
import unittest
from paper.market_data import load_csv_candles
from research.cost_model import CostModel
from research.walk_forward import run_walk_forward_evaluation
from strategies.candle_paths import CandlePathsStrategy


class TestWalkForward(unittest.TestCase):

    def setUp(self):
        self.candles = load_csv_candles("data/immutable/eth_daily.csv", min_candles=100)
        self.strategy = CandlePathsStrategy()
        self.cost_model = CostModel()

    def test_run_walk_forward_evaluation(self):
        results = run_walk_forward_evaluation(
            strategy=self.strategy,
            candles=self.candles,
            cost_model=self.cost_model,
            n_folds=5,
            embargo_bars=10,
        )
        self.assertEqual(results["n_folds"], 5)
        self.assertEqual(len(results["fold_reports"]), 5)
        self.assertIn("aggregated_oos_metrics", results)
        metrics = results["aggregated_oos_metrics"]
        self.assertIn("closed_trades", metrics)
        self.assertIn("win_rate_pct", metrics)


if __name__ == "__main__":
    unittest.main()
