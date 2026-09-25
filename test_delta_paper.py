import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delta_paper import (BAR, Broker, Config, Contract, DataError, PublicDelta,
                         candles_read, quote_read, signal)

CONTRACT = Contract(.01, .05, .0005, 3136)
T0 = 1800000000


def quote(t=T0, bid=2000, ask=2000.1):
    return dict(time=t, bid=bid, ask=ask, bid_size=10000, ask_size=10000)


def sig(t=T0, side=1, atr=10):
    return dict(bar=t-BAR, side=side, atr=atr)


class PaperTests(unittest.TestCase):
    def broker(self, **kwargs):
        b = Broker(':memory:', CONTRACT, **kwargs)
        self.addCleanup(b.db.close)
        return b

    def test_long_and_short_round_trip(self):
        for side in (1, -1):
            b = self.broker()
            first = b.step(quote(), sig(side=side))
            p = first['position']
            self.assertIsNotNone(p)
            self.assertIsInstance(p['contracts'], int)
            self.assertLessEqual(p['qty']*p['entry'], 10000)
            self.assertLessEqual(p['qty']*(abs(p['entry']-p['stop'])+p['entry']*.0017), 25.01)
            q = quote(T0+15, 2050 if side == 1 else 1950, 2050.1 if side == 1 else 1950.1)
            end = b.step(q, sig(side=side))
            self.assertIsNone(end['position'])
            self.assertEqual(end['trades'], 1)
            self.assertEqual(end['wins'], 1)
            event = json.loads(b.db.execute("SELECT body FROM events WHERE kind='EXIT'").fetchone()[0])
            self.assertAlmostEqual(end['cash']-10000, event['net_pnl'])

    def test_restart_and_duplicate_quote_do_not_duplicate_fill(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'paper.sqlite3'
            b = Broker(path, CONTRACT)
            state = b.step(quote(), sig())
            b.db.close()
            restarted = Broker(path, CONTRACT)
            try:
                self.assertEqual(state, restarted.step(quote(), sig()))
                self.assertEqual(restarted.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            finally:
                restarted.db.close()

    def test_same_bar_cannot_reenter_after_exit(self):
        b = self.broker()
        b.step(quote(), sig())
        b.step(quote(T0+10, 1900, 1900.1), sig())
        s = b.step(quote(T0+BAR+10), sig())
        self.assertIsNone(s['position'])
        self.assertEqual(s['trades'], 1)

    def test_stop_gap_and_funding_cost(self):
        b = self.broker()
        b.step(quote(), sig())
        s = b.step(quote(T0+60, 1800, 1800.1), sig())
        event = json.loads(b.db.execute("SELECT body FROM events WHERE kind='EXIT'").fetchone()[0])
        self.assertLess(event['price'], 1800)
        self.assertGreater(s['funding_debits'], 0)
        self.assertLess(s['cash'], 10000)

    def test_kill_flattens_and_prevents_entry(self):
        b = self.broker()
        b.step(quote(), sig())
        s = b.step(quote(T0+10), sig(), kill=True)
        self.assertIsNone(s['position'])
        self.assertEqual(s['halt'], 'STOP file')
        self.assertIsNone(b.step(quote(T0+BAR), sig(T0+BAR))['position'])

    def test_daily_and_drawdown_breakers(self):
        for cfg, field in [(Config(daily_loss=.00001), 'daily_halt'),
                           (Config(max_drawdown=.00001), 'halt')]:
            b = self.broker(config=cfg)
            b.step(quote(), sig())
            s = b.step(quote(T0+10, 1990, 1990.1), sig())
            self.assertTrue(s[field])
            self.assertIsNone(s['position'])

    def test_spread_and_late_signals_rejected(self):
        b = self.broker()
        self.assertIsNone(b.step(quote(ask=2010), sig())['position'])
        self.assertIsNone(b.step(quote(T0+2*BAR), sig(T0+BAR))['position'])

    def test_freshness_and_bad_quote_rejected(self):
        raw = dict(symbol='ETHUSD', product_trading_status='operational', timestamp=T0*1e6,
                   quotes=dict(best_bid=2000, best_ask=2001, bid_size=100, ask_size=100))
        quote_read(raw, T0)
        for now in (T0+31, T0-6):
            with self.assertRaises(DataError):
                quote_read(raw, now)
        raw['quotes']['best_bid'] = 'nan'
        with self.assertRaises(DataError):
            quote_read(raw, T0)

    def test_atomic_rollback(self):
        b = self.broker()
        before = b.state()
        with patch.object(b, 'event', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                b.step(quote(), sig())
        self.assertEqual(before, b.state())
        self.assertEqual(b.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_future_signal_rejected(self):
        b = self.broker()
        with self.assertRaises(DataError):
            b.step(quote(), sig(T0+BAR))

    def test_no_private_routes(self):
        with self.assertRaises(DataError):
            PublicDelta().get('/v2/orders')

    def test_candles_and_indicator_causality(self):
        rows = [dict(time=T0+i*BAR, open=2000+i, high=2002+i, low=1999+i, close=2001+i) for i in range(120)]
        parsed = candles_read(rows, T0+120*BAR)
        self.assertEqual(signal(parsed[:100]), signal(copy.deepcopy(parsed[:100])))
        changed = copy.deepcopy(rows)
        changed[-1]['close'] = 999999
        self.assertEqual(signal(rows[:100]), signal(changed[:100]))
        with self.assertRaises(DataError):
            candles_read(rows, T0+124*BAR)
        with self.assertRaises(DataError):
            candles_read(rows[:100]+rows[101:], T0+120*BAR)


if __name__ == '__main__':
    unittest.main()
