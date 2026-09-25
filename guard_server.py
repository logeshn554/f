"""Local live ETH paper dashboard. Binds only to 127.0.0.1; no live-order capability."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import signal as os_signal
import sqlite3
import threading
import time

from delta_paper import BAR, DataError, PublicDelta, candles_read, quote_read, save_json, utc
from candle_paths import PAPER_CONFIG, VERSION, PathBroker as GuardBroker, effective_contract, signal, wilson, HISTORY, CONTEXT
from forward_evidence import ForwardEvidence, fingerprint

WEB = Path(__file__).with_name('guard_web')
SOURCES = [dict(title='Delta public API',url='https://docs.delta.exchange/'),
           dict(title='Delta fees and GST',url='https://www.delta.exchange/fees'),
           dict(title='Predictive uncertainty',url='https://www.itl.nist.gov/div898/handbook/pmd/section5/pmd512.htm'),
           dict(title='Backtest overfitting research',url='https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf')]


class SessionLock:
    def __init__(self,path):
        self.file = path.open('a+b')
        self.file.seek(0,2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise DataError('Another ETH Guard process owns this paper account')

    def close(self):
        self.file.close()


class Application:
    def __init__(self,directory,region='india',interval=5):
        self.directory = directory
        directory.mkdir(parents=True,exist_ok=True)
        self.region, self.interval = region, interval
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.view = dict(status='STARTING',checked_at=None,error=None,summary=None,candles=[],events=[],equity=[])
        self.controls = dict(paused=False,flatten=False)
        if (directory/'controls.json').exists():
            saved = json.loads((directory/'controls.json').read_text(encoding='utf-8'))
            if set(saved) != set(self.controls) or any(type(v) is not bool for v in saved.values()):
                raise DataError('Invalid saved controls')
            self.controls = saved
        self.research_path = Path(__file__).with_name('paths_research')/'research.json'
        self.research_cache = None
        self.research_mtime = None
        self.logger = logging.getLogger('eth_guard.'+str(directory.resolve()))
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(directory/'service.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger.addHandler(handler)
        self.handler = handler

    def close(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()

    def control(self,action):
        with self.lock:
            if action == 'pause':
                self.controls['paused'] = True
            elif action == 'resume':
                if (self.view.get('summary') or {}).get('halt'):
                    raise DataError('Risk halt is persistent. A new paper account is required; resume cannot bypass it.')
                if self.controls['flatten']:
                    raise DataError('Wait for the pending paper close before resuming')
                self.controls['paused'] = False
            elif action == 'flatten':
                self.controls.update(paused=True,flatten=True)
            else:
                raise DataError('Unknown control')
            save_json(self.directory/'controls.json',self.controls)
            self.logger.info('Operator control %s',action)
            return dict(self.controls)

    def payload(self):
        with self.lock:
            try:
                mtime = self.research_path.stat().st_mtime
                if mtime != self.research_mtime:
                    self.research_cache = json.loads(self.research_path.read_text(encoding='utf-8'))
                    self.research_mtime = mtime
            except FileNotFoundError:
                pass
            data = dict(self.view,controls=dict(self.controls),token=self.token,server_time=time.time(),
                        region=self.region,config=asdict(PAPER_CONFIG),version=VERSION,sources=SOURCES,
                        research=self.research_cache)
            # An old OK response must never appear live after the feed stops.
            if data.get('received_at') and time.time()-data['received_at'] > 30:
                data['status'] = 'STALE'
            return data

    def publish(self,data):
        with self.lock:
            self.view = data
            save_json(self.directory/'health.json',{k:v for k,v in data.items() if k not in ('candles','events','equity')})

    def worker(self):
        broker = None
        evidence = None
        model_hash = fingerprint()
        api = PublicDelta(self.region)
        rows = []
        cached_signal = None
        contract = None
        product = None
        product_checked = 0
        failures = 0
        last_valid = 0
        try:
            while not self.stop.is_set():
                tick_start = time.monotonic()
                try:
                    now = time.time()
                    if contract is None or now-product_checked > 300:
                        product = api.get('/v2/products/ETHUSD')
                        latest_contract = effective_contract(product,self.region)
                        if contract is not None and latest_contract != contract:
                            raise DataError('Contract specification or fee changed; restart with a new paper account after review')
                        contract = latest_contract
                        product_checked = now
                    if broker is None:
                        broker = GuardBroker(self.directory/'paper.sqlite3',contract,self.region,PAPER_CONFIG,VERSION)
                        broker.db.execute('CREATE TABLE IF NOT EXISTS observations(time REAL PRIMARY KEY, equity REAL, bid REAL, ask REAL)')
                        evidence = ForwardEvidence(broker.db,model_hash)
                    expected_bar = int(now)//BAR*BAR-BAR
                    if not rows or rows[-1]['time'] != expected_bar:
                        raw = api.get('/v2/history/candles',symbol='ETHUSD',resolution='15m',
                                      start=int(now)-(HISTORY+CONTEXT+3)*BAR,end=int(now))
                        rows = candles_read(raw,time.time())
                    ticker = api.get('/v2/tickers/ETHUSD')
                    now = time.time()
                    q = quote_read(ticker,now)
                    if int(ticker['product_id']) != contract.product_id:
                        raise DataError('Ticker product does not match the contract')
                    if now-(rows[-1]['time']+BAR) > BAR+30:
                        raise DataError('Candle cache is stale')
                    if cached_signal is None or cached_signal['bar'] != rows[-1]['time']:
                        cached_signal = signal(rows,contract)
                    sig = cached_signal
                    evidence.record(sig,q,time.time())
                    evidence.settle(rows,time.time())
                    with self.lock:
                        controls = dict(self.controls)
                    effective_signal = dict(sig)
                    if controls['paused'] or controls['flatten']:
                        effective_signal['side'] = 0
                    # Missed observations are explicitly surfaced. Never invent retrospective fills.
                    previous_quote = broker.state()['last_quote']
                    gap = q['time']-previous_quote if previous_quote else 0
                    state = broker.step(q,effective_signal)
                    if controls['flatten']:
                        broker.db.execute('BEGIN IMMEDIATE')
                        try:
                            state = broker.state()
                            if state['position']:
                                broker.close_position(state,q,'operator paper close')
                            state['equity'] = state['cash']
                            state['max_drawdown'] = max(state['max_drawdown'],1-state['equity']/state['peak'])
                            broker.db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(state),))
                            broker.db.commit()
                        except Exception:
                            broker.db.rollback()
                            raise
                        with self.lock:
                            self.controls['flatten'] = False
                            save_json(self.directory/'controls.json',self.controls)
                    summary = broker.summary()
                    summary['confidence_interval'] = wilson(summary['wins'],summary['closed_trades'])
                    broker.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)',(q['time'],state['equity'],q['bid'],q['ask']))
                    # Bound disk growth: retain 30 days of high-frequency observations, all trades.
                    broker.db.execute('DELETE FROM observations WHERE time < ?',(now-30*86400,))
                    observations = broker.db.execute('SELECT time,equity FROM observations ORDER BY time DESC LIMIT 3000').fetchall()[::-1]
                    events = [dict(id=i,kind=k,**json.loads(b)) for i,k,b in broker.db.execute('SELECT id,kind,body FROM events ORDER BY id DESC LIMIT 100')]
                    halted = summary['halt'] or summary['daily_halt']
                    status = 'HALTED' if halted else 'PAUSED' if controls['paused'] else 'LIVE'
                    last_valid = now
                    failures = 0
                    data = dict(status=status,checked_at=utc(now),received_at=now,quote=q,signal=sig,
                                forward_evidence=evidence.summary(),
                                summary=summary,candles=rows[-160:],events=events,
                                equity=[dict(time=t,equity=e) for t,e in observations],
                                contract=asdict(contract),base_fee=float(product['taker_commission_rate']),
                                gst_rate=.18 if self.region == 'india' else 0,source=api.base,error=None,
                                gap_warning=f'{gap:.0f}s between observations; intragap stops cannot be reconstructed' if gap>30 else None,
                                entry_window_open=0<=q['time']-(sig['bar']+BAR)<=120,
                                cycle_ms=round(1000*(time.monotonic()-tick_start)))
                    self.publish(data)
                    self.logger.info('status=%s quote=%.2f signal=%s equity=%.6f closed=%d',status,q['bid'],sig['label'],summary['equity'],summary['closed_trades'])
                except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                    failures += 1
                    with self.lock:
                        data = dict(self.view)
                    data.update(status='BLOCKED',checked_at=utc(time.time()),error=str(exc),consecutive_failures=failures,
                                received_at=last_valid or None)
                    self.publish(data)
                    self.logger.warning('Failed cycle %s: %s; inspect persisted ledger for committed fills',failures,exc)
                delay = min(60,self.interval*2**min(failures,3)) if failures else self.interval
                self.stop.wait(max(.1,delay-(time.monotonic()-tick_start)))
        except Exception:
            self.logger.exception('Fatal worker failure')
            with self.lock:
                data = dict(self.view)
            data.update(status='STOPPED',error='Worker stopped unexpectedly; inspect service.log',checked_at=utc(time.time()))
            self.publish(data)
        finally:
            if broker:
                broker.db.close()


def handler_for(app,port):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ETHGuard'

        def log_message(self,*args):
            pass

        def host_ok(self):
            return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')

        def send(self,status,body,kind='application/json; charset=utf-8'):
            body = body if isinstance(body,bytes) else body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.host_ok():
                return self.send(403,'{"error":"Host rejected"}')
            if self.path == '/api/state':
                return self.send(200,json.dumps(app.payload(),allow_nan=False))
            if self.path == '/api/health':
                data = app.payload()
                return self.send(200 if data['status'] in ('LIVE','PAUSED','HALTED') else 503,
                                 json.dumps({k:data.get(k) for k in ('status','checked_at','error')}))
            static = {'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),
                      '/style.css':('style.css','text/css; charset=utf-8')}
            if self.path in static:
                name,kind = static[self.path]
                return self.send(200,(WEB/name).read_bytes(),kind)
            return self.send(404,'{"error":"Not found"}')

        def do_POST(self):
            if not self.host_ok():
                return self.send(403,'{"error":"Host rejected"}')
            origin = self.headers.get('Origin')
            if origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                return self.send(403,'{"error":"Origin rejected"}')
            token = self.headers.get('X-Paper-Token','')
            if not secrets.compare_digest(token,app.token):
                return self.send(403,'{"error":"Token rejected"}')
            if self.path != '/api/control':
                return self.send(404,'{"error":"Not found"}')
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 1024:
                    raise DataError('Invalid body length')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict) or set(data) != {'action'}:
                    raise DataError('Expected action only')
                result = app.control(data['action'])
                self.send(200,json.dumps(result))
            except (ValueError,KeyError,TypeError) as exc:
                self.send(400,json.dumps(dict(error=str(exc))))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--region',choices=['india','global'],default='india')
    parser.add_argument('--directory',type=Path,default=Path(__file__).with_name('guard_live'))
    parser.add_argument('--interval',type=int,default=5)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not 5 <= args.interval <= 60:
        parser.error('port must be 1024..65535 and interval 5..60')
    args.directory.mkdir(parents=True,exist_ok=True)
    lease = SessionLock(args.directory/'session.lock')
    app = Application(args.directory,args.region,args.interval)
    server = ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(app,args.port))
    server.daemon_threads = True
    worker = threading.Thread(target=app.worker,name='public-feed',daemon=True)
    worker.start()
    save_json(args.directory/'process.json',dict(pid=os.getpid(),port=args.port,started_at=utc(time.time()),mode='LOCAL PAPER'))
    print(f'ETH Guard: http://127.0.0.1:{args.port} | $100 LOCAL PAPER ONLY',flush=True)
    def stop(*_):
        app.stop.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    os_signal.signal(os_signal.SIGTERM,stop)
    os_signal.signal(os_signal.SIGINT,stop)
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        app.stop.set()
        worker.join(timeout=45)
        server.server_close()
        app.close()
        lease.close()


if __name__ == '__main__':
    main()
