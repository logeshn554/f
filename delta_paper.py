"""Delta ETHUSD public-data connector and LOCAL paper broker. Never sends orders."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
import math
from pathlib import Path
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = 'eth-trend-breakout-v2'
BAR = 900
HOSTS = {'india': 'https://api.india.delta.exchange', 'global': 'https://api.delta.exchange'}


class DataError(ValueError):
    pass


def number(value, positive=True):
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise DataError('Nonfinite or invalid market number')
    return value


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


class PublicDelta:
    def __init__(self, region='india'):
        self.base = HOSTS[region]

    def get(self, path, **params):
        if path not in ('/v2/products/ETHUSD', '/v2/tickers/ETHUSD', '/v2/history/candles'):
            raise DataError('Only public ETH market-data routes are allowed')
        url = self.base + path + ('?' + urllib.parse.urlencode(params) if params else '')
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, method='GET', headers={
                    'Accept': 'application/json', 'User-Agent': 'ETH-Local-Paper/2.0', 'Cache-Control': 'no-cache'})
                with urllib.request.urlopen(req, timeout=12) as response:
                    data = json.load(response)
                if data.get('success') is not True or 'result' not in data:
                    raise DataError('Delta returned an unsuccessful response')
                return data['result']
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                delay = min(5, max(1, float(exc.headers.get('X-RATE-LIMIT-RESET', 1000))/1000))
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)

    def snapshot(self):
        now = time.time()
        product = self.get('/v2/products/ETHUSD')
        candles = self.get('/v2/history/candles', symbol='ETHUSD', resolution='15m',
                           start=int(now)-BAR*1500, end=int(now))
        ticker = self.get('/v2/tickers/ETHUSD')
        return dict(product=product, candles=candles, ticker=ticker, fetched_at=time.time(), source=self.base)


@dataclass(frozen=True)
class Contract:
    unit: float
    tick: float
    fee: float
    product_id: int

    @classmethod
    def read(cls, p):
        if (p['symbol'] != 'ETHUSD' or p['contract_type'] != 'perpetual_futures'
                or p['notional_type'] != 'vanilla' or p['is_quanto'] is not False
                or p['contract_unit_currency'] != 'ETH'):
            raise DataError('Unsupported contract; requires linear ETHUSD perpetual')
        if p['state'] != 'live' or p['trading_status'] != 'operational':
            raise DataError('Contract is not operational')
        fee = number(p['taker_commission_rate'], False)
        if not 0 <= fee <= .01:
            raise DataError('Unexpected commission rate')
        return cls(number(p['contract_value']), number(p['tick_size']), fee, int(p['id']))


@dataclass(frozen=True)
class Config:
    initial_cash: float = 10000
    risk: float = .0025
    max_notional: float = 1.0
    slippage: float = .0002
    max_spread: float = .001
    daily_loss: float = .02
    max_drawdown: float = .05
    max_holding_seconds: int = BAR * 16
    # Conservative continuous debit for either direction, not actual exchange settlement.
    funding_reserve_per_8h: float = .0003


def candles_read(raw, now, fresh=True):
    rows = []
    seen = set()
    for item in sorted(raw, key=lambda b: b['time']):
        ts = int(item['time'])
        if ts % BAR:
            raise DataError('Misaligned candle timestamp')
        if ts + BAR > now:
            continue
        if ts in seen:
            raise DataError('Duplicate candle')
        seen.add(ts)
        o, h, l, c = (number(item[k]) for k in ('open', 'high', 'low', 'close'))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise DataError('Invalid OHLC candle')
        if rows and ts - rows[-1]['time'] != BAR:
            raise DataError('Missing 15-minute candles')
        rows.append(dict(time=ts, open=o, high=h, low=l, close=c))
    if len(rows) < 100:
        raise DataError('Need at least 100 completed 15-minute candles')
    if fresh and now - (rows[-1]['time'] + BAR) > BAR + 30:
        raise DataError(f'Stale candles: last completed at {utc(rows[-1]["time"]+BAR)}')
    return rows


def quote_read(raw, now):
    if raw['symbol'] != 'ETHUSD' or raw['product_trading_status'] != 'operational':
        raise DataError('Ticker unavailable or market suspended')
    timestamp = number(raw['timestamp']) / 1_000_000
    if not -5 <= now-timestamp <= 30:
        raise DataError(f'Stale ticker: {utc(timestamp)}; age {now-timestamp:.1f}s')
    bid, ask = (number(raw['quotes'][key]) for key in ('best_bid', 'best_ask'))
    if bid > ask:
        raise DataError('Crossed order book')
    return dict(time=timestamp, bid=bid, ask=ask,
                bid_size=number(raw['quotes']['bid_size']), ask_size=number(raw['quotes']['ask_size']))


def ema(values, n):
    result = values[0]
    for v in values[1:]:
        result += 2/(n+1)*(v-result)
    return result


def signal(rows):
    # A fixed trailing window makes a restart produce the same indicators.
    rows = rows[-100:]
    if len(rows) < 100:
        raise DataError('Insufficient signal warmup')
    c = [b['close'] for b in rows]
    fast, slow = ema(c, 20), ema(c, 60)
    previous_slow = ema(c[:-1], 60)
    changes = [c[i]-c[i-1] for i in range(len(c)-14, len(c))]
    gain, loss = sum(max(x, 0) for x in changes), sum(max(-x, 0) for x in changes)
    rsi = 100*gain/(gain+loss) if gain+loss else 50
    atr = statistics.mean(max(rows[i]['high']-rows[i]['low'], abs(rows[i]['high']-c[i-1]),
                              abs(rows[i]['low']-c[i-1])) for i in range(len(c)-14, len(c)))
    travel = sum(abs(c[i]-c[i-1]) for i in range(len(c)-20, len(c)))
    efficiency = abs(c[-1]-c[-21])/travel if travel else 0
    side = 0
    if .001 <= atr/c[-1] <= .03 and efficiency >= .25:
        if c[-1] > max(b['high'] for b in rows[-13:-1]) and fast > slow > previous_slow and 52 <= rsi <= 78:
            side = 1
        elif c[-1] < min(b['low'] for b in rows[-13:-1]) and fast < slow < previous_slow and 22 <= rsi <= 48:
            side = -1
    return dict(bar=rows[-1]['time'], side=side, atr=atr, ema20=fast, ema60=slow,
                rsi14=rsi, efficiency=efficiency, label={1:'LONG', -1:'SHORT', 0:'WAIT'}[side])


def rounded(price, tick, up):
    units = (Decimal(str(price))/Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return float(units * Decimal(str(tick)))


class Broker:
    """SQLite serializes state and fill journals atomically, including between processes."""
    def __init__(self, path, contract, region='india', config=Config(), strategy_version=VERSION):
        self.contract, self.config = contract, config
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, kind TEXT, body TEXT NOT NULL)')
        self.identity = dict(version=strategy_version, region=region, contract=asdict(contract), config=asdict(config))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
            if row:
                if json.loads(row[0])['identity'] != self.identity:
                    raise DataError('State configuration differs; use a separate database')
            else:
                initial = dict(identity=self.identity, cash=config.initial_cash, peak=config.initial_cash,
                               position=None, last_quote=0, last_bar=0, last_exit=0, day='',
                               day_start=config.initial_cash, halt=None, daily_halt=False, equity=config.initial_cash,
                               max_drawdown=0, trades=0, wins=0, gross_profit=0, gross_loss=0, funding_debits=0)
                self.db.execute('INSERT INTO state VALUES (1, ?)', (json.dumps(initial),))
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    def state(self):
        return json.loads(self.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])

    def event(self, kind, data):
        self.db.execute('INSERT INTO events(kind,body) VALUES (?,?)', (kind, json.dumps(data, allow_nan=False)))

    def equity(self, s, q):
        p = s['position']
        if not p:
            return s['cash']
        mark = q['bid'] if p['side'] == 1 else q['ask']
        return s['cash'] + p['qty']*(mark-p['entry'])*p['side'] - p['qty']*mark*self.contract.fee

    def close_position(self, s, q, reason):
        p, cfg, contract = s['position'], self.config, self.contract
        sell = p['side'] == 1
        price = rounded((q['bid'] if sell else q['ask'])*(1-cfg.slippage if sell else 1+cfg.slippage), contract.tick, not sell)
        gross = p['qty']*(price-p['entry'])*p['side']
        exit_fee = p['qty']*price*contract.fee
        net = gross-exit_fee-p['entry_fee']-p['funding']
        s['cash'] += gross-exit_fee
        s['trades'] += 1
        s['wins'] += int(net > 0)
        s['gross_profit'] += max(net, 0)
        s['gross_loss'] += max(-net, 0)
        s['last_exit'] = q['time']
        s['position'] = None
        self.event('EXIT', dict(time=q['time'], price=price, net_pnl=net, reason=reason, **p))

    def step(self, q, sig, kill=False):
        for k in ('time', 'bid', 'ask', 'bid_size', 'ask_size'):
            number(q[k])
        if q['bid'] > q['ask'] or sig['side'] not in (-1, 0, 1):
            raise DataError('Invalid observation')
        if sig['bar']+BAR > q['time']:
            raise DataError('Cannot use an unfinished/future signal candle')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            s = self.state()
            if q['time'] <= s['last_quote']:
                self.db.rollback()
                return s
            cfg, c = self.config, self.contract
            p = s['position']
            if p:
                elapsed = max(0, q['time']-p['funded_to'])
                debit = p['qty'] * ((q['bid']+q['ask'])/2) * cfg.funding_reserve_per_8h * elapsed/28800
                s['cash'] -= debit
                s['funding_debits'] += debit
                p['funding'] += debit
                p['funded_to'] = q['time']
            eq = self.equity(s, q)
            day = utc(q['time'])[:10]
            if day != s['day']:
                s.update(day=day, day_start=eq, daily_halt=False)
            s['peak'] = max(s['peak'], eq)
            if eq <= s['day_start']*(1-cfg.daily_loss):
                s['daily_halt'] = True
            if eq <= s['peak']*(1-cfg.max_drawdown):
                s['halt'] = 'max_drawdown'
            if kill:
                s['halt'] = 'STOP file'
            if p:
                mark = q['bid'] if p['side'] == 1 else q['ask']
                reason = None
                if s['halt'] or s['daily_halt']:
                    reason = s['halt'] or 'daily loss'
                elif (mark-p['stop'])*p['side'] <= 0:
                    reason = 'stop'
                elif (mark-p['target'])*p['side'] >= 0:
                    reason = 'target'
                elif q['time']-p['opened'] >= cfg.max_holding_seconds:
                    reason = 'time exit'
                if reason:
                    self.close_position(s, q, reason)
            new_bar = sig['bar'] > s['last_bar']
            if (new_bar and sig['side'] and not s['position'] and not s['halt'] and not s['daily_halt']
                    and q['time']-s['last_exit'] >= BAR and q['time']-(sig['bar']+BAR) <= 120):
                spread = (q['ask']-q['bid'])/((q['ask']+q['bid'])/2)
                if spread <= cfg.max_spread:
                    side = sig['side']
                    entry = rounded((q['ask'] if side == 1 else q['bid'])*(1+side*cfg.slippage), c.tick, side == 1)
                    plan = sig.get('execution_plan')
                    distance = max(number(plan['stop_distance']) if plan else 2*number(sig['atr']), 4*c.tick)
                    stop = rounded(entry-side*distance, c.tick, side == -1)
                    distance = abs(entry-stop)
                    friction = entry*(2*c.fee + 2*cfg.slippage + cfg.funding_reserve_per_8h)
                    available = min(s['cash'], self.equity(s, q))
                    contracts = math.floor(min(available*cfg.risk/((distance+friction)*c.unit),
                                              available*cfg.max_notional/(entry*c.unit*(1+c.fee)),
                                              q['ask_size'] if side == 1 else q['bid_size']))
                    reward = number(plan['target_distance']) if plan else 2*distance
                    target = rounded(entry+side*reward, c.tick, side == 1)
                    if contracts >= 1 and stop > 0 and target > 0:
                        qty = contracts*c.unit
                        fee = qty*entry*c.fee
                        s['cash'] -= fee
                        s['position'] = dict(side=side, contracts=contracts, qty=qty, entry=entry,
                                             stop=stop, target=target,
                                             opened=q['time'], entry_fee=fee, funding=0, funded_to=q['time'])
                        self.event('ENTRY', dict(signal=sig, **s['position']))
            s['last_bar'] = max(s['last_bar'], sig['bar'])
            s['last_quote'] = q['time']
            s['equity'] = self.equity(s, q)
            s['peak'] = max(s['peak'], s['equity'])
            s['max_drawdown'] = max(s['max_drawdown'], 1-s['equity']/s['peak'])
            if s['equity'] <= s['peak']*(1-cfg.max_drawdown):
                s['halt'] = 'max_drawdown'
            self.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(s, allow_nan=False),))
            self.db.commit()
            return s
        except Exception:
            self.db.rollback()
            raise

    def summary(self):
        s = self.state()
        return dict(strategy=self.identity['version'], mode='LOCAL PAPER ONLY', equity=s['equity'], cash=s['cash'],
                    return_pct=100*(s['equity']/self.config.initial_cash-1), closed_trades=s['trades'],
                    wins=s['wins'], win_rate_pct=100*s['wins']/s['trades'] if s['trades'] else None,
                    profit_factor=s['gross_profit']/s['gross_loss'] if s['gross_loss'] else None,
                    max_observed_drawdown_pct=100*s['max_drawdown'], funding_reserve_debits=s['funding_debits'],
                    position=s['position'], halt=s['halt'], daily_halt=s['daily_halt'], last_quote=s['last_quote'])


def replay(snapshot):
    contract = Contract.read(snapshot['product'])
    rows = candles_read(snapshot['candles'], snapshot['fetched_at'], fresh=False)
    split = 100 + int((len(rows)-100)*.6)
    reports = {}
    for name, start, end in [('development',100,split), ('holdout',split,len(rows))]:
        broker = Broker(':memory:', contract)
        for i in range(start, end):
            row = rows[i]
            sig = signal(rows[:i])
            def quote(price, stamp):
                # Historical top-of-book is unavailable: assume a 2bp spread.
                return dict(time=stamp, bid=price*.9999, ask=price*1.0001, bid_size=1e9, ask_size=1e9)
            broker.step(quote(row['open'], row['time']), sig)
            p = broker.state()['position']
            extremes = (row['low'], row['high']) if not p or p['side'] == 1 else (row['high'], row['low'])
            # Adverse extreme first. Barrier/gap price controls avoid filling targets at the bar's high/low.
            for offset, price in [(1, extremes[0]), (2, extremes[1])]:
                p = broker.state()['position']
                if p:
                    mark = price*(.9999 if p['side'] == 1 else 1.0001)
                    if (mark-p['stop'])*p['side'] <= 0:
                        price = p['stop']/(.9999 if p['side'] == 1 else 1.0001)
                    elif (mark-p['target'])*p['side'] >= 0:
                        price = p['target']/(.9999 if p['side'] == 1 else 1.0001)
                broker.step(quote(price, row['time']+offset), sig)
            broker.step(quote(row['close'], row['time']+BAR-1), sig)
        s = broker.state()
        if s['position']:
            broker.db.execute('BEGIN IMMEDIATE')
            broker.close_position(s, quote(rows[end-1]['close'], rows[end-1]['time']+BAR), 'replay end')
            s['equity'] = s['cash']
            broker.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(s),))
            broker.db.commit()
        reports[name] = dict(start=utc(rows[start]['time']), end=utc(rows[end-1]['time']+BAR),
                             **broker.summary(), events=[dict(kind=k, **json.loads(b)) for k,b in broker.db.execute('SELECT kind,body FROM events')])
        broker.db.close()
    return dict(source=snapshot.get('source'), fetched_at=utc(snapshot['fetched_at']), bars=len(rows),
                latest_signal=signal(rows), periods=reports,
                assumptions=['Chronological 60/40 split after warmup; fixed rules, no tuning.',
                             'Historical replay, not forward paper results. 2bp spread, 2bp adverse slippage per side.',
                             'Current product taker fee used throughout; integer contracts and tick rounding.',
                             'Adverse intrabar extreme first; OHLC cannot establish real fill sequence.',
                             'Funding is a conservative 3bp/8h continuous debit in either direction, not actual funding.',
                             'USD research ledger; no INR conversion, tax, queue, latency or liquidation model.',
                             'No win-rate guarantee; historical profitability does not establish future performance.'])


def run(args):
    folder = args.directory
    folder.mkdir(parents=True, exist_ok=True)
    if args.command == 'status':
        path = folder/'health.json'
        print(path.read_text(encoding='utf-8') if path.exists() else 'No paper session has run.')
        return 0
    if args.command == 'replay':
        snapshot = json.loads(args.input.read_text(encoding='utf-8')) if args.input else PublicDelta(args.region).snapshot()
        save_json(folder/'snapshot.json', snapshot)
        report = replay(snapshot)
        save_json(folder/'replay.json', report)
        print(json.dumps({k:{a:b for a,b in v.items() if a != 'events'} for k,v in report['periods'].items()}, indent=2))
        return 0
    failures = 0
    last_code = 0
    for iteration in range(args.cycles):
        broker = None
        try:
            snapshot = PublicDelta(args.region).snapshot()
            save_json(folder/'snapshot.json', snapshot)
            contract = Contract.read(snapshot['product'])
            broker = Broker(folder/'paper.sqlite3', contract, args.region)
            now = time.time()
            q = quote_read(snapshot['ticker'], now)
            rows = candles_read(snapshot['candles'], now)
            sig = signal(rows)
            state = broker.step(q, sig, kill=(folder/'STOP').exists())
            health = dict(status='HALTED' if state['halt'] or state['daily_halt'] else 'OK',
                          checked_at=utc(now), source=snapshot['source'], signal=sig, **broker.summary())
            failures = 0
            last_code = 0
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            failures += 1
            last_code = 2
            health = dict(status='BLOCKED', checked_at=utc(time.time()), error=str(exc), consecutive_failures=failures,
                          mode='LOCAL PAPER ONLY', note='No simulated fills made from this failed snapshot.')
            if broker:
                health['paper_state'] = broker.summary()
        finally:
            if broker:
                broker.db.close()
        save_json(folder/'health.json', health)
        with (folder/'run.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(health, allow_nan=False)+'\n')
        print(json.dumps(health, allow_nan=False), flush=True)
        if failures >= 3 or (folder/'STOP').exists():
            break
        if iteration+1 < args.cycles:
            time.sleep(args.interval)
    return last_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['paper', 'replay', 'status'])
    parser.add_argument('--region', choices=HOSTS, default='india')
    parser.add_argument('--directory', type=Path, default=Path(__file__).with_name('delta_run'))
    parser.add_argument('--input', type=Path, help='Saved public snapshot, replay only')
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100000 or not 5 <= args.interval <= 60:
        parser.error('cycles must be 1..100000; interval must be 5..60 seconds')
    try:
        raise SystemExit(run(args))
    except KeyboardInterrupt:
        print('Stopped. Local paper state retained for restart; no exchange orders exist.')
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(2, f'Blocked: {exc}\n')


if __name__ == '__main__':
    main()
