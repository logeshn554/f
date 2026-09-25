import unittest
from delta_paper import Contract
from research_states import forecasts, label, context, posterior, HOUR


def rows(n):
    return [dict(time=i*HOUR,open=200+i*.2,high=200+i*.2+.3,
                 low=200+i*.2-.1,close=200+i*.2+.2) for i in range(n)]


class StateResearchTests(unittest.TestCase):
    def test_unknown_future_cannot_change_earlier_forecasts(self):
        data = rows(700)
        cost = Contract(.01,.01,.00059,1)
        before,_ = forecasts(data,cost)
        changed = data[:601]+[dict(r,open=r['open']*2,high=r['high']*2,
                                      low=r['low']*2,close=r['close']*2) for r in data[601:]]
        after,_ = forecasts(changed,cost)
        self.assertTrue(before)
        self.assertEqual({i:p for i,p in before.items() if i<=600},
                         {i:p for i,p in after.items() if i<=600})

    def test_flat_prices_lose_after_costs(self):
        data = [dict(time=i*HOUR,open=200,high=200,low=200,close=200) for i in range(50)]
        cost = Contract(.01,.01,.00059,1)
        for side in (-1,1):
            self.assertLess(label(data,30,side,1.5,1,cost),0)

    def test_sparse_cell_cannot_trade(self):
        self.assertIsNone(posterior([1]*39,[1]*100))
        self.assertLess(posterior([1]*40,[-1]*100)['p'],1)

    def test_features_ignore_later_rows(self):
        data = rows(100)
        self.assertEqual(context(data,50),context(data[:51],50))


if __name__=='__main__':
    unittest.main()
