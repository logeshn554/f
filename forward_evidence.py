"""Persist forecasts before outcomes exist. Fan checks are not trading wins."""
import hashlib
import json
from pathlib import Path

from delta_paper import BAR, DataError


def fingerprint():
    root = Path(__file__).parent
    h = hashlib.sha256()
    for name in ('candle_paths.py','delta_paper.py','eth_guard.py','forward_evidence.py'):
        h.update(name.encode())
        h.update((root/name).read_bytes())
    return h.hexdigest()


class ForwardEvidence:
    def __init__(self,db,model_hash):
        self.db,self.model_hash = db,model_hash
        db.execute('CREATE TABLE IF NOT EXISTS forward_forecasts(model_hash TEXT, bar INTEGER, recorded_at REAL, horizon_close INTEGER, body TEXT, PRIMARY KEY(model_hash,bar))')
        db.execute('CREATE TABLE IF NOT EXISTS forward_outcomes(model_hash TEXT, bar INTEGER, evaluated_at REAL, actual_close REAL, contained INTEGER, PRIMARY KEY(model_hash,bar))')

    def record(self,sig,quote,now):
        close_time = sig['bar']+BAR
        # Late startup is not a prospective forecast at the claimed origin.
        if not 0<=now-close_time<=120 or not 0<=quote['time']-close_time<=120:
            return False
        if not -5<=now-quote['time']<=30:
            return False
        if sig['last_training_outcome']>sig['bar']:
            raise DataError('Forecast training contains future outcomes')
        if not sig['fan'] or sig['fan'][-1]['time']!=close_time+sig['horizon_bars']*BAR:
            raise DataError('Forecast horizon mismatch')
        body = json.dumps(dict(signal=sig,quote=quote),sort_keys=True,allow_nan=False)
        result = self.db.execute('INSERT OR IGNORE INTO forward_forecasts VALUES(?,?,?,?,?)',
                               (self.model_hash,sig['bar'],now,sig['fan'][-1]['time'],body))
        return result.rowcount==1

    def settle(self,rows,now):
        closes = {r['time']+BAR:r['close'] for r in rows if r['time']+BAR<=now}
        pending = self.db.execute('SELECT f.model_hash,f.bar,f.horizon_close,f.body FROM forward_forecasts f LEFT JOIN forward_outcomes o ON o.model_hash=f.model_hash AND o.bar=f.bar WHERE o.bar IS NULL').fetchall()
        for model_hash,bar,end,body in pending:
            if end not in closes:
                continue
            band = json.loads(body)['signal']['fan'][-1]
            actual = closes[end]
            self.db.execute('INSERT OR IGNORE INTO forward_outcomes VALUES(?,?,?,?,?)',
                            (model_hash,bar,now,actual,int(band['p10']<=actual<=band['p90'])))

    def summary(self):
        n,first,last = self.db.execute('SELECT COUNT(*),MIN(recorded_at),MAX(recorded_at) FROM forward_forecasts WHERE model_hash=?',(self.model_hash,)).fetchone()
        matured,hits = self.db.execute('SELECT COUNT(*),SUM(contained) FROM forward_outcomes WHERE model_hash=?',(self.model_hash,)).fetchone()
        return dict(model_hash=self.model_hash,forecasts=n,matured=matured,pending=n-matured,
                    first_recorded=first,last_recorded=last,
                    containment_pct=100*hits/matured if matured else None,
                    note='Prospective forecast-band checks, not trade win rate. Overlapping horizons are dependent.')
