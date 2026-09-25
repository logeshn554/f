import json
import sqlite3
import unittest
from forward_evidence import ForwardEvidence
from delta_paper import BAR, DataError


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.addCleanup(self.db.close)
        self.store=ForwardEvidence(self.db,'frozen-model')
        self.sig=dict(bar=10*BAR,last_training_outcome=10*BAR,horizon_bars=8,
                      fan=[dict(time=19*BAR,p10=90,p50=100,p90=110)])
        self.q=dict(time=11*BAR+5,bid=100,ask=101)

    def test_first_forecast_is_immutable_on_duplicate(self):
        self.assertTrue(self.store.record(self.sig,self.q,11*BAR+6))
        changed=dict(self.sig,fan=[dict(time=19*BAR,p10=1,p50=2,p90=3)])
        self.assertFalse(self.store.record(changed,self.q,11*BAR+7))
        body=self.db.execute('SELECT body FROM forward_forecasts').fetchone()[0]
        self.assertEqual(json.loads(body)['signal']['fan'][0]['p10'],90)

    def test_late_or_stale_forecast_is_not_backfilled(self):
        self.assertFalse(self.store.record(self.sig,self.q,11*BAR+121))
        self.assertFalse(self.store.record(self.sig,self.q,11*BAR+50))
        self.assertEqual(self.store.summary()['forecasts'],0)

    def test_no_outcome_before_candle_closes(self):
        self.store.record(self.sig,self.q,11*BAR+6)
        rows=[dict(time=18*BAR,close=105)]
        self.store.settle(rows,19*BAR-1)
        self.assertEqual(self.store.summary()['matured'],0)
        self.store.settle(rows,19*BAR)
        self.assertEqual(self.store.summary()['containment_pct'],100)
        self.store.settle([dict(time=18*BAR,close=200)],20*BAR)
        self.assertEqual(self.store.summary()['containment_pct'],100)

    def test_reject_training_leakage(self):
        with self.assertRaises(DataError):
            self.store.record(dict(self.sig,last_training_outcome=11*BAR),self.q,11*BAR+6)


if __name__=='__main__':
    unittest.main()
