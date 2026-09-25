"""Tests verifying cost calculations, GST tax, adverse slippage, and 2x stress test."""
import unittest
from research.cost_model import CostModel, round_tick


class TestRealisticCosts(unittest.TestCase):

    def setUp(self):
        self.model = CostModel(
            taker_fee_rate=0.0005,
            gst_rate=0.18,
            slippage_rate=0.0002,
            spread_rate=0.0002,
            funding_reserve_per_8h=0.0003,
            tick_size=0.01,
        )

    def test_fee_with_gst(self):
        # Base fee rate = 0.0005. GST = 18%. Total fee rate = 0.0005 * 1.18 = 0.00059
        notional = 10000.0
        fee = self.model.calculate_fee(notional)
        self.assertAlmostEqual(fee, 5.9, places=4)

    def test_entry_and_exit_slippage_and_spread(self):
        raw_price = 3000.0
        # Entry LONG: price pushed up by half-spread + slippage
        long_entry = self.model.calculate_entry_price(raw_price, side=1)
        self.assertGreater(long_entry, raw_price)

        # Exit LONG: selling price pushed down by half-spread + slippage
        long_exit = self.model.calculate_exit_price(raw_price, side=1)
        self.assertLess(long_exit, raw_price)

    def test_2x_cost_stress_model(self):
        stress_model = self.model.create_2x_stress_model()
        self.assertEqual(stress_model.taker_fee_rate, 0.0010)
        self.assertEqual(stress_model.slippage_rate, 0.0004)
        self.assertEqual(stress_model.spread_rate, 0.0004)
        self.assertEqual(stress_model.funding_reserve_per_8h, 0.0006)

    def test_tick_rounding(self):
        price = 3000.004
        rounded_up = round_tick(price, 0.01, up=True)
        rounded_down = round_tick(price, 0.01, up=False)
        self.assertEqual(rounded_up, 3000.01)
        self.assertEqual(rounded_down, 3000.00)


if __name__ == "__main__":
    unittest.main()
