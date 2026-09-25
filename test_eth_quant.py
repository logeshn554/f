import copy
import datetime as dt
import unittest
from eth_quant import backtest, exit_price, indicators, validate


class QuantTests(unittest.TestCase):
    def test_barrier_ambiguity_and_gap(self):
        self.assertEqual(exit_price(dict(open=100, low=80, high=120), 90, 115), (90, 'stop'))
        self.assertEqual(exit_price(dict(open=70, low=60, high=100), 90, 115), (70, 'gap stop'))

    def test_costs_and_next_open(self):
        rows = [dict(date=str(i), open=100, high=100, low=100, close=100) for i in range(3)]
        ind = [dict(signal=True, atr14=10)] * 3
        result = backtest(rows, ind, 1, 3, fee=.001, slippage=0)
        self.assertEqual(result['trades'], 1)
        self.assertEqual(result['trade_log'][0]['entry_date'], '1')
        self.assertLess(result['net_return_pct'], 0)
        self.assertEqual(result['win_rate_pct'], 0)

    def test_indicators_do_not_see_future(self):
        rows = [dict(open=100+i, high=102+i, low=98+i, close=100+i) for i in range(250)]
        changed = copy.deepcopy(rows)
        changed[-1]['close'] = 100000
        self.assertEqual(indicators(rows)[:-1], indicators(changed)[:-1])

    def test_reject_nan_and_duplicate_dates(self):
        rows = [dict(date=(dt.date(2020, 1, 1)+dt.timedelta(days=i)).isoformat(), open=100, high=110, low=90, close=100) for i in range(240)]
        validate(copy.deepcopy(rows))
        bad = copy.deepcopy(rows)
        bad[0]['close'] = float('nan')
        with self.assertRaises(ValueError):
            validate(bad)
        rows[1]['date'] = rows[0]['date']
        with self.assertRaises(ValueError):
            validate(rows)


if __name__ == '__main__':
    unittest.main()
