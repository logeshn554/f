"""Tests verifying strict Target Gate decision logic."""
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

    def test_target_not_established_when_trades_under_100(self):
        strategy = CandlePathsStrategy()
        manifest = {
            "strategy_name": "candle_paths",
            "source_hash": strategy.get_source_hash(),
        }
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)

        # Assert status is strictly TARGET_NOT_ESTABLISHED
        self.assertEqual(res["status"], "TARGET_NOT_ESTABLISHED")
        self.assertFalse(res["target_supported"])
        self.assertFalse(res["real_money_execution"])
        self.assertTrue(res["research_only"])

    def test_target_not_established_eth_guard(self):
        strategy = ETHGuardStrategy()
        manifest = {
            "strategy_name": "eth_guard",
            "source_hash": strategy.get_source_hash(),
        }
        res = validate_strategy_manifest(strategy, self.candles, manifest, self.cost_model)

        self.assertEqual(res["status"], "TARGET_NOT_ESTABLISHED")
        self.assertFalse(res["target_supported"])


if __name__ == "__main__":
    unittest.main()
