"""
Tests verifying the Target Gate enforces the canonical project goal:

  "Research and validate an Ethereum paper-trading algorithm targeting at least
  90% winning trades and positive net returns after realistic costs, using
  chronological out-of-sample evaluation and reporting uncertainty honestly.
  Do not claim the target is achieved without evidence or enable real-money trading."

Specifically tests:
  - TARGET_NOT_ESTABLISHED when OOS trades < 100
  - research_only is always True
  - real_money_execution is always False
  - Both CI types (Wilson + bootstrap) are present in output
  - 2x cost stress result is always reported
  - status can only be "TARGET_SUPPORTED" or "TARGET_NOT_ESTABLISHED" (no other strings)
  - target_supported is False when sample is insufficient
"""
import unittest

from paper.market_data import load_csv_candles
from research.cost_model import CostModel
from research.validation import validate_strategy_manifest
from strategies.candle_paths import CandlePathsStrategy
from strategies.eth_guard import ETHGuardStrategy


class TestTargetGate(unittest.TestCase):

    def setUp(self):
        self.candles = load_csv_candles("data/immutable/eth_daily.csv", min_candles=100)
        self.cost_model = CostModel()

    # ── Core correctness ───────────────────────────────────────────────────────

    def test_target_not_established_when_trades_under_100(self):
        """Fewer than 100 OOS trades must always produce TARGET_NOT_ESTABLISHED."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)

        self.assertEqual(res["status"], "TARGET_NOT_ESTABLISHED")
        self.assertFalse(res["target_supported"])
        self.assertLess(res["oos"]["closed_trades"], 100)

    def test_target_not_established_eth_guard(self):
        strategy = ETHGuardStrategy()
        manifest = {"strategy_name": "eth_guard", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)

        self.assertEqual(res["status"], "TARGET_NOT_ESTABLISHED")
        self.assertFalse(res["target_supported"])

    # ── Paper-only enforcement (goal: "do not enable real-money trading") ──────

    def test_research_only_always_true(self):
        """research_only must always be True — never allow live trading flag."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        self.assertTrue(res["research_only"])

    def test_real_money_execution_always_false(self):
        """real_money_execution must always be False in every report."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        self.assertFalse(res["real_money_execution"])

    # ── Honest uncertainty (goal: "reporting uncertainty honestly") ────────────

    def test_wilson_ci_always_present(self):
        """Wilson CI must appear in every report — uncertainty must be visible."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        # CI is None only when trades == 0; either way the key must exist
        self.assertIn("win_rate_95_ci", res["oos"])

    def test_bootstrap_ci_always_present(self):
        """Block-bootstrap CI must appear — dependency-aware uncertainty required."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        self.assertIn("block_bootstrap_95_ci", res["oos"])

    # ── Chronological OOS (goal: "chronological out-of-sample evaluation") ────

    def test_walk_forward_folds_present(self):
        """Result must include per-fold detail proving OOS evaluation was run."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        folds = res["walk_forward_details"]["folds"]
        self.assertEqual(len(folds), 5)
        for fold in folds:
            self.assertIn("train_range", fold)
            self.assertIn("test_range", fold)

    # ── Cost stress test ──────────────────────────────────────────────────────

    def test_2x_cost_stress_always_reported(self):
        """2x cost stress result must always appear — cost honesty requirement."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        self.assertIn("cost_stress_2x", res)
        self.assertIn("net_return_pct", res["cost_stress_2x"])

    # ── Status string contract ─────────────────────────────────────────────────

    def test_status_is_only_valid_values(self):
        """Status must be exactly one of the two permitted strings — no weasel words."""
        valid_statuses = {"TARGET_SUPPORTED", "TARGET_NOT_ESTABLISHED"}
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        self.assertIn(res["status"], valid_statuses)

    def test_target_supported_matches_status(self):
        """target_supported bool must be consistent with status string."""
        strategy = CandlePathsStrategy()
        manifest = {"strategy_name": "candle_paths", "source_hash": strategy.get_source_hash()}
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)
        if res["status"] == "TARGET_SUPPORTED":
            self.assertTrue(res["target_supported"])
        else:
            self.assertFalse(res["target_supported"])


if __name__ == "__main__":
    unittest.main()
