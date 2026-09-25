"""Fixed ETH Guard v3 rules and a reproducible chronological research harness."""
from dataclasses import asdict, replace
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from delta_paper import BAR, Broker, Config, Contract, DataError, PublicDelta, candles_read, ema, save_json, utc

VERSION = 'eth-guard-v3.0'
WARMUP = 480
PAPER_CONFIG = Config(initial_cash=100, risk=.005, max_notional=1,
                      slippage=.0003, max_holding_seconds=8*3600)


def effective_contract(product, region='india'):
    raw = Contract.read(product)
    return replace(raw, fee=raw.fee*(1.18 if region == 'india' else 1))


def hourly(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r['time']//3600*3600, []).append(r)
    return [dict(time=t, open=g[0]['open'], high=max(r['high'] for r in g),
                 low=min(r['low'] for r in g), close=g[-1]['close'])
            for t,g in sorted(groups.items())
            if len(g) == 4 and [r['time'] for r in g] == [t+j*BAR for j in range(4)]]


def indicators(rows):
    close = [r['close'] for r in rows]
    atr = statistics.mean(max(rows[i]['high']-rows[i]['low'], abs(rows[i]['high']-close[i-1]),
                              abs(rows[i]['low']-close[i-1])) for i in range(len(rows)-14, len(rows)))
    changes = [close[i]-close[i-1] for i in range(len(rows)-14, len(rows))]
    gain, loss = sum(max(x,0) for x in changes), sum(max(-x,0) for x in changes)
    travel = sum(abs(close[i]-close[i-1]) for i in range(len(rows)-20, len(rows)))
    return dict(ema20=ema(close,20), ema60=ema(close,60), atr=atr,
                rsi=100*gain/(gain+loss) if gain+loss else 50,
                efficiency=abs(close[-1]-close[-21])/travel if travel else 0)


def signal(rows, contract, config=PAPER_CONFIG):
    if len(rows) < WARMUP:
        raise DataError(f'ETH Guard requires {WARMUP} completed candles')
    rows = rows[-WARMUP:]
    hours = hourly(rows)[-100:]
    if len(hours) < 80:
        raise DataError('Insufficient completed hourly context')
    lower = indicators(rows[-160:])
    higher = indicators(hours)
    hclose = [r['close'] for r in hours]
    rising = higher['ema60'] > ema(hclose[:-1], 60)
    falling = higher['ema60'] < ema(hclose[:-1], 60)
    bias = 1 if hclose[-1] > higher['ema20'] > higher['ema60'] and rising else (
        -1 if hclose[-1] < higher['ema20'] < higher['ema60'] and falling else 0)
    close = rows[-1]['close']
    atr = lower['atr']
    # A previous bar touched the contemporaneous EMA, not an EMA calculated with future bars.
    long_touch = short_touch = False
    for back in (1,2,3,4):
        prefix = rows[:-back][-160:]
        level = ema([r['close'] for r in prefix],20)
        long_touch |= prefix[-1]['low'] <= level
        short_touch |= prefix[-1]['high'] >= level
    long_trigger = long_touch and close > lower['ema20'] and close > rows[-2]['high'] and 45 <= lower['rsi'] <= 72
    short_trigger = short_touch and close < lower['ema20'] and close < rows[-2]['low'] and 28 <= lower['rsi'] <= 55
    volatility_ok = .0008 <= atr/close <= .02
    efficiency_ok = lower['efficiency'] >= .18
    # Gross 4-ATR target must be at least three times the estimated friction.
    friction = close*(2*contract.fee+2*config.slippage+config.funding_reserve_per_8h+.0002)
    cost_ok = 4*atr >= 3*friction
    pullback_ok = long_trigger if bias == 1 else short_trigger if bias == -1 else False
    gates = [dict(name='Hourly trend', passed=bool(bias), detail={1:'Uptrend',-1:'Downtrend',0:'Mixed'}[bias]),
             dict(name='15m pullback recovery', passed=bool(pullback_ok), detail='Reclaim + prior candle break'),
             dict(name='Directional efficiency', passed=efficiency_ok, detail=f'{lower["efficiency"]:.2f} / 0.18 minimum'),
             dict(name='Volatility window', passed=volatility_ok, detail=f'{100*atr/close:.2f}% ATR'),
             dict(name='Move exceeds costs', passed=cost_ok, detail=f'{4*atr/max(friction,1e-9):.1f}x friction / 3x minimum')]
    side = bias if all(g['passed'] for g in gates) else 0
    return dict(bar=rows[-1]['time'], side=side, label={1:'LONG',-1:'SHORT',0:'WAIT'}[side],
                atr=atr, ema20=lower['ema20'], ema60=lower['ema60'], rsi14=lower['rsi'],
                efficiency=lower['efficiency'], hourly_ema20=higher['ema20'], hourly_ema60=higher['ema60'],
                hourly_last_bar=hours[-1]['time'], bias=bias, gates=gates,
                stop_distance=2*atr, target_distance=4*atr, friction_per_eth=friction)


def quote(price, ts):
    return dict(time=ts, bid=price*.9999, ask=price*1.0001, bid_size=1e9, ask_size=1e9)


class GuardBroker(Broker):
    """Tighten stops only; bounded target extension after +1 initial risk unit."""
    def step(self, q, sig, kill=False):
        from delta_paper import rounded
        result = super().step(q,sig,kill)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            s = self.state()
            p = s['position']
            if not p or sig['bar'] <= p.get('adjusted_bar',0) or q['time'] < s['last_quote']:
                self.db.rollback()
                return result
            p.setdefault('initial_risk',abs(p['entry']-p['stop']))
            p.setdefault('initial_target',p['target'])
            p['adjusted_bar'] = sig['bar']
            side = p['side']
            mark = q['bid'] if side == 1 else q['ask']
            favorable = (mark-p['entry'])*side
            before = dict(stop=p['stop'],target=p['target'])
            if favorable >= p['initial_risk']:
                # Include two-sided trading costs in the breakeven reference; gaps still lose money.
                breakeven = p['entry']+side*(2*p['entry']*(self.contract.fee+self.config.slippage))
                candidate = max(breakeven,mark-2*sig['atr']) if side == 1 else min(breakeven,mark+2*sig['atr'])
                candidate = min(candidate,mark-self.contract.tick) if side == 1 else max(candidate,mark+self.contract.tick)
                candidate = rounded(candidate,self.contract.tick,side == -1)
                p['stop'] = max(p['stop'],candidate) if side == 1 else min(p['stop'],candidate)
                if sig.get('bias') == side:
                    cap = p['entry']+side*3*p['initial_risk']
                    target = min(cap,mark+2*sig['atr']) if side == 1 else max(cap,mark-2*sig['atr'])
                    target = rounded(target,self.contract.tick,side == -1)
                    p['target'] = max(p['target'],target) if side == 1 else min(p['target'],target)
            after = dict(stop=p['stop'],target=p['target'])
            if before != after:
                self.event('ADJUST',dict(time=q['time'],before=before,after=after,side=side,
                                         reason='Volatility trail after +1R; target capped at 3R'))
            self.db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s),))
            self.db.commit()
            return s
        except Exception:
            self.db.rollback()
            raise


def finish(broker, q):
    s = broker.state()
    if s['position']:
        broker.db.execute('BEGIN IMMEDIATE')
        try:
            broker.close_position(s,q,'research period end')
            s['equity'] = s['cash']
            s['max_drawdown'] = max(s['max_drawdown'], 1-s['equity']/s['peak'])
            broker.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(s),))
            broker.db.commit()
        except Exception:
            broker.db.rollback()
            raise


def wilson(wins, n):
    if not n:
        return None
    p, z = wins/n, 1.96
    center = (p+z*z/(2*n))/(1+z*z/n)
    width = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0,100*(center-width)), min(100,100*(center+width))]


def replay_period(rows, signals, start, end, contract, config=PAPER_CONFIG, broker_class=GuardBroker, strategy_version=VERSION):
    broker = broker_class(':memory:', contract, config=config, strategy_version=strategy_version)
    curve = []
    try:
        for i in range(start,end):
            r, sig = rows[i], signals[i-1]
            broker.step(quote(r['open'],r['time']),sig)
            p = broker.state()['position']
            extremes = [r['low'],r['high']] if not p or p['side'] == 1 else [r['high'],r['low']]
            for j, price in enumerate(extremes,1):
                p = broker.state()['position']
                if p:
                    factor = .9999 if p['side'] == 1 else 1.0001
                    mark = price*factor
                    if (mark-p['stop'])*p['side'] <= 0:
                        price = p['stop']/factor
                    elif (mark-p['target'])*p['side'] >= 0:
                        price = p['target']/factor
                broker.step(quote(price,r['time']+j),sig)
            s = broker.step(quote(r['close'],r['time']+BAR-1),sig)
            curve.append(dict(time=r['time']+BAR-1, equity=s['equity']))
        finish(broker,quote(rows[end-1]['close'],rows[end-1]['time']+BAR))
        summary = broker.summary()
        curve[-1]['equity'] = summary['equity']
        events = [dict(kind=k,**json.loads(b)) for k,b in broker.db.execute('SELECT kind,body FROM events ORDER BY id')]
        wins, trades = summary['wins'], summary['closed_trades']
        fee = contract.fee
        benchmark = 100*((rows[end-1]['close']*(1-config.slippage)*(1-fee))/(rows[start]['open']*(1+config.slippage)*(1+fee))-1)
        return dict(**summary, start=utc(rows[start]['time']), end=utc(rows[end-1]['time']+BAR),
                    confidence_interval=wilson(wins,trades), curve=curve[::max(1,len(curve)//300)]+[curve[-1]],
                    events=events, buy_hold_return_pct=benchmark)
    finally:
        broker.db.close()


def research(snapshot, region='india'):
    rows = candles_read(snapshot['candles'], snapshot['fetched_at'], fresh=False)
    if len(rows) < WARMUP+400:
        raise DataError('Need at least 880 candles for chronological research')
    contract = effective_contract(snapshot['product'],region)
    signals = [None]*(WARMUP-1) + [signal(rows[:i+1],contract) for i in range(WARMUP-1,len(rows))]
    split = WARMUP+int((len(rows)-WARMUP)*.7)
    development = replay_period(rows,signals,WARMUP,split,contract)
    holdout = replay_period(rows,signals,split,len(rows),contract)
    stressed = replay_period(rows,signals,split,len(rows),replace(contract,fee=contract.fee*2),
                             replace(PAPER_CONFIG,slippage=PAPER_CONFIG.slippage*2, funding_reserve_per_8h=.0006))
    blocks = []
    for j in range(3):
        a = split+(len(rows)-split)*j//3
        b = split+(len(rows)-split)*(j+1)//3
        block = replay_period(rows,signals,a,b,contract)
        blocks.append({k:v for k,v in block.items() if k not in ('curve','events')})
    enough = holdout['closed_trades'] >= 100
    positive = holdout['return_pct'] > 0 and stressed['return_pct'] > 0
    lower = holdout['confidence_interval'][0] if holdout['confidence_interval'] else 0
    return dict(strategy=VERSION, built_at=utc(time.time()), bars=len(rows), source=snapshot['source'],
                source_fetched_at=utc(snapshot['fetched_at']), config=asdict(PAPER_CONFIG),
                strategy_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                development=development, holdout=holdout, cost_stress=stressed, chronological_blocks=blocks,
                assessment=dict(status='RESEARCH ONLY', target_win_rate=90, target_supported=bool(enough and lower>=90),
                                sufficient_sample=enough, positive_holdout_and_stress=positive,
                                production_ready=False, note='No production certification. Fixed hypothesis; no parameter search. Historical results are not live paper results.'),
                assumptions=['$100 starting cash per independent period, 1x notional cap, integer ETH contracts.',
                             'Delta current taker fee plus 18% GST for India; 2bp synthetic spread and 3bp adverse slippage/side.',
                             'Funding reserve debit 3bp per 8h, not actual settlement; tax on profits and INR conversion excluded.',
                             '70/30 chronological split; 3 independent holdout blocks; 2x fees/slippage/funding stress.',
                             'Signals use only completed 15m and complete hourly groups; entries use the next bar open.',
                             'Adverse extreme first in each bar. Historical quotes, actual depth, latency and outages are not modeled.',
                             'Buy-and-hold is a fractional, fully invested price benchmark with fees/slippage, not a matched perpetual strategy.',
                             'Wilson interval assumes independent trades; clustered outcomes can make it overconfident.'])


def download(days, region):
    api = PublicDelta(region)
    end = int(time.time())//BAR*BAR
    start = end-(days*96+WARMUP)*BAR
    candles = {}
    for cursor in range(start,end,1800*BAR):
        stop = min(end,cursor+1800*BAR)
        page = api.get('/v2/history/candles',symbol='ETHUSD',resolution='15m',start=cursor,end=stop)
        for r in page:
            if start <= int(r['time']) < end:
                if r['time'] in candles and candles[r['time']] != r:
                    raise DataError('Conflicting historical candle at a page boundary')
                candles[r['time']] = r
        print(f'Downloaded {len(candles)} completed candles',flush=True)
    rows = sorted(candles.values(),key=lambda r:r['time'])
    if len(rows) != (end-start)//BAR:
        raise DataError('Historical response did not cover the requested range')
    return dict(product=api.get('/v2/products/ETHUSD'), candles=rows, fetched_at=time.time(), source=api.base)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--days',type=int,default=90)
    p.add_argument('--region',choices=['india','global'],default='india')
    p.add_argument('--input',type=Path)
    p.add_argument('--directory',type=Path,default=Path(__file__).with_name('guard_research'))
    args = p.parse_args()
    if not 14 <= args.days <= 365:
        p.error('days must be 14..365')
    try:
        snapshot = json.loads(args.input.read_text(encoding='utf-8')) if args.input else download(args.days,args.region)
        save_json(args.directory/'history.json',snapshot)
        report = research(snapshot,args.region)
        save_json(args.directory/'research.json',report)
        print(json.dumps({k:{a:b for a,b in report[k].items() if a not in ('curve','events')} for k in ('development','holdout','cost_stress')},indent=2))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        p.exit(2,f'Research failed: {exc}\n')


if __name__ == '__main__':
    main()
