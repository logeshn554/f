import copy
import json
import math
import unittest

from delta_paper import BAR, Contract, DataError
from candle_paths import CandleModel, PathBroker, PAPER_CONFIG, VERSION, signal, outcome

T = 1800000000
C = Contract(.01,.01,.00059,3136)


def trend(side,n=900):
    rows = []
    for i in range(n):
        o = 200+side*.2*i
        c = o+side*.2
        rows.append(dict(time=T+i*BAR,open=o,high=max(o,c)+.02,low=min(o,c)-.02,close=c))
    return rows


def quote(t,price):
    return dict(time=t,bid=price,ask=price+.01,bid_size=1000,ask_size=1000)


class CandlePathTests(unittest.TestCase):
    def broker(self):
        b = PathBroker(':memory:',C,config=PAPER_CONFIG,strategy_version=VERSION)
        self.addCleanup(b.db.close)
        return b

    def test_causal_forecast_unchanged_by_unknown_future(self):
        rows = trend(1)
        prefix = CandleModel(rows[:701]).at(700,C)
        rows[701:] = [dict(r,close=r['close']+1000,high=r['high']+1000) for r in rows[701:]]
        full = CandleModel(rows).at(700,C)
        self.assertEqual(prefix,full)
        self.assertLessEqual(full['last_training_outcome'],rows[700]['time'])

    def test_buy_sell_and_wait_are_reachable(self):
        for side in (1,-1):
            s = signal(trend(side),C)
            self.assertEqual(s['side'],side)
            self.assertGreater(s['execution_plan']['utility'],0)
            expensive = Contract(.01,.01,.05,3136)
            self.assertEqual(signal(trend(side),expensive)['side'],0)

    def test_live_window_and_research_window_match(self):
        rows = trend(1,2100)
        self.assertEqual(signal(rows,C),CandleModel(rows).at(len(rows)-1,C))

    def test_fan_order_and_weighted_percentages(self):
        s = signal(trend(1),C)
        self.assertLessEqual(s['matched_paths'],64)
        for p in s['fan']:
            self.assertLessEqual(p['p10'],p['p50'])
            self.assertLessEqual(p['p50'],p['p90'])
        for p in s['plans']:
            self.assertTrue(0<=p['sample_win_pct']<=100.000001)
            self.assertTrue(math.isfinite(p['utility']))

    def test_barrier_ambiguity_gap_and_short_symmetry(self):
        self.assertEqual(outcome([(0,3,-3,1)],1,1,2),(-1,'stop'))
        self.assertEqual(outcome([(0,3,-3,1)],-1,1,2),(-1,'stop'))
        self.assertEqual(outcome([(-4,-3,-5,-4)],1,1,2),(-4,'gap stop'))

    def test_model_exits_replace_atr_multiples(self):
        b = self.broker()
        s = signal(trend(1),C)
        t = s['bar']+BAR
        p = b.step(quote(t,s['reference_price']),s)['position']
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p['target']-p['entry'],s['target_distance'],delta=2*C.tick)
        self.assertNotAlmostEqual(s['target_distance'],4*s['atr'],delta=.01)
        self.assertLessEqual(p['qty']*p['entry'],100)

    def test_replanning_tightens_stop_and_exits_when_edge_lost(self):
        b = self.broker()
        s = signal(trend(1),C)
        t = s['bar']+BAR
        first = b.step(quote(t,s['reference_price']),s)['position']
        next_signal = copy.deepcopy(s)
        next_signal['bar'] += BAR
        later = b.step(quote(t+BAR,s['reference_price']+.1),next_signal)['position']
        self.assertIsNotNone(later)
        self.assertGreaterEqual(later['stop'],first['stop'])
        failed = copy.deepcopy(next_signal)
        failed['bar'] += BAR
        failed['side'] = 0
        for plan in failed['plans']:
            plan['utility'] = -10
        end = b.step(quote(t+2*BAR,s['reference_price']+.1),failed)
        self.assertIsNone(end['position'])
        self.assertEqual(end['trades'],1)
        row = b.db.execute("SELECT body FROM events WHERE kind='EXIT'").fetchone()
        self.assertIn('no longer support',json.loads(row[0])['reason'])

    def test_duplicate_cannot_replan_or_fill_twice(self):
        b = self.broker()
        s = signal(trend(-1),C)
        q = quote(s['bar']+BAR,s['reference_price'])
        first = b.step(q,s)
        events = b.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        self.assertEqual(first,b.step(q,s))
        self.assertEqual(events,b.db.execute('SELECT COUNT(*) FROM events').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
