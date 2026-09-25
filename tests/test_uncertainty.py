"""Tests for uncertainty calculations including Wilson score CI and block-bootstrap CI."""
import unittest
from research.uncertainty import wilson_score_interval, block_bootstrap_ci


class TestUncertainty(unittest.TestCase):

    def test_wilson_score_interval(self):
        # 0 trades
        lower, upper = wilson_score_interval(0, 0)
        self.assertEqual((lower, upper), (0.0, 0.0))

        # 1 win out of 1 trade
        lower, upper = wilson_score_interval(1, 1)
        self.assertGreater(lower, 20.0)
        self.assertEqual(upper, 100.0)

        # 90 wins out of 100 trades
        lower, upper = wilson_score_interval(90, 100)
        self.assertGreaterEqual(lower, 82.0)
        self.assertLessEqual(upper, 95.0)

    def test_block_bootstrap_ci(self):
        pnls = [10.0, -5.0, 15.0, 20.0, -8.0] * 10
        ci = block_bootstrap_ci(pnls, num_resamples=100, block_size=5, seed=42)
        self.assertIn("win_rate_ci_pct", ci)
        self.assertIn("net_pnl_ci", ci)
        self.assertLessEqual(ci["win_rate_ci_pct"][0], ci["win_rate_ci_pct"][1])


if __name__ == "__main__":
    unittest.main()
