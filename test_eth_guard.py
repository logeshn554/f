import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from delta_paper import BAR, Contract, DataError
from eth_guard import PAPER_CONFIG, VERSION, GuardBroker, effective_contract, hourly, signal, wilson
from guard_server import Application, SessionLock

T = 1800000000
C = Contract(.01,.05,.00059,3136)


def q(t=T,price=2000):
    return dict(time=t,bid=price,ask=price+.05,bid_size=1000,ask_size=1000)


def sig(t=T,side=1,atr=10):
    return dict(bar=t-BAR,side=side,bias=side,atr=atr)


class GuardTests(unittest.TestCase):
    def broker(self,config=PAPER_CONFIG):
        b = GuardBroker(':memory:',C,config=config,strategy_version=VERSION)
        self.addCleanup(b.db.close)
        return b

    def test_100_dollar_account_and_integer_risk(self):
        b = self.broker()
        s = b.step(q(),sig())
        p = s['position']
        self.assertEqual(b.config.initial_cash,100)
        self.assertIsNotNone(p)
        self.assertEqual(int(p['contracts']),p['contracts'])
        self.assertLessEqual(p['qty']*p['entry']*(1+C.fee),100)
        friction = p['entry']*(2*C.fee+2*PAPER_CONFIG.slippage+PAPER_CONFIG.funding_reserve_per_8h)
        self.assertLessEqual(p['qty']*(p['initial_risk']+friction),.5)

    def test_minimum_contract_risk_skips_entry(self):
        b = self.broker()
        self.assertIsNone(b.step(q(),sig(atr=100))['position'])

    def test_trailing_stop_never_widens_long_or_short(self):
        for side in (1,-1):
            b = self.broker()
            first = b.step(q(),sig(side=side))['position']
            moved = b.step(q(T+BAR,2000+side*25),sig(T+BAR,side))['position']
            self.assertIsNotNone(moved)
            self.assertGreater((moved['stop']-first['stop'])*side,0)
            self.assertLessEqual((moved['target']-moved['entry'])*side,3*moved['initial_risk']+C.tick)
            later = b.step(q(T+2*BAR,2000+side*26),sig(T+2*BAR,side,atr=30))['position']
            self.assertGreaterEqual((later['stop']-moved['stop'])*side,0)

    def test_duplicate_does_not_repeat_adjustment(self):
        b = self.broker()
        b.step(q(),sig())
        a = b.step(q(T+BAR,2025),sig(T+BAR))
        count = b.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        self.assertEqual(a,b.step(q(T+BAR,2025),sig(T+BAR)))
        self.assertEqual(count,b.db.execute('SELECT COUNT(*) FROM events').fetchone()[0])

    def test_complete_hour_groups_only(self):
        rows = [dict(time=T+i*BAR,open=100,high=102,low=99,close=101) for i in range(7)]
        self.assertEqual(len(hourly(rows)),1)
        self.assertEqual(hourly(rows)[0]['time'],T)
        self.assertEqual(hourly(rows[:3]),[])

    def test_future_candles_cannot_change_prefix_signal(self):
        rows = [dict(time=T+i*BAR,open=2000+i*.1,high=2002+i*.1,low=1998+i*.1,close=2001+i*.1) for i in range(520)]
        expected = signal(rows[:480],C)
        other = copy.deepcopy(rows)
        for r in other[480:]:
            r['close'] = 999999
        self.assertEqual(expected,signal(other[:480],C))
        self.assertLessEqual(expected['hourly_last_bar']+3600,rows[479]['time']+BAR)

    def test_wilson_does_not_certify_single_win(self):
        self.assertLess(wilson(1,1)[0],90)
        self.assertIsNone(wilson(0,0))

    def test_controls_persist_and_risk_halt_cannot_be_resumed(self):
        d = self.enterContext(tempfile.TemporaryDirectory())
        app = Application(Path(d))
        self.addCleanup(app.close)
        app.control('pause')
        self.assertTrue(json.loads((Path(d)/'controls.json').read_text())['paused'])
        app.view['summary'] = dict(halt='max_drawdown')
        with self.assertRaises(DataError):
            app.control('resume')

    def test_old_quote_marks_dashboard_stale(self):
        d = self.enterContext(tempfile.TemporaryDirectory())
        app = Application(Path(d))
        self.addCleanup(app.close)
        app.view.update(status='LIVE',received_at=1)
        self.assertEqual(app.payload()['status'],'STALE')

    def test_session_lock_prevents_second_owner(self):
        with tempfile.TemporaryDirectory() as d:
            lease = SessionLock(Path(d)/'session.lock')
            try:
                with self.assertRaises(DataError):
                    SessionLock(Path(d)/'session.lock')
            finally:
                lease.close()


if __name__ == '__main__':
    unittest.main()
