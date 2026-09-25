"""Candle Paths v4: conditional empirical paths and cost-aware BUY/SELL/WAIT decisions.

Custom trading design using standard statistical building blocks. No claim of universal
novelty, exhaustive futures, calibrated probabilities, or guaranteed returns.
"""
from dataclasses import replace
import heapq
import math
import statistics
import json

from delta_paper import BAR, Broker, DataError, rounded
from eth_guard import PAPER_CONFIG as BASE_CONFIG, effective_contract, wilson

VERSION = 'candle-paths-v4.0'
PAPER_CONFIG = replace(BASE_CONFIG,max_holding_seconds=8*BAR)
CONTEXT = 24
HORIZON = 8
HISTORY = 1800
WARMUP = 600
NEIGHBORS = 64


def quantile(values,weights,p):
    ordered = sorted(zip(values,weights))
    threshold = p*sum(weights)
    total = 0
    for value,weight in ordered:
        total += weight
        if total >= threshold:
            return value
    return ordered[-1][0]


def feature(rows,i):
    block = rows[i-CONTEXT+1:i+1]
    close = block[-1]['close']
    tr = [max(r['high']-r['low'],abs(r['high']-rows[i-CONTEXT+j]['close']),
              abs(r['low']-rows[i-CONTEXT+j]['close'])) for j,r in enumerate(block)]
    scale = max(statistics.median(tr),close*.0001)
    r = block[-1]
    width = max(r['high']-r['low'],close*1e-9)
    body = (r['close']-r['open'])/width
    upper = (r['high']-max(r['open'],r['close']))/width
    lower = (min(r['open'],r['close'])-r['low'])/width
    changes = [block[j]['close']-block[j-1]['close'] for j in range(1,len(block))]
    travel = sum(abs(x) for x in changes)
    pressure = sum((b['close']-b['open'])/max(b['high']-b['low'],close*1e-9) for b in block[-4:])/4
    hi,lo = max(b['high'] for b in block),min(b['low'] for b in block)
    f = [body,upper,lower,(close-block[-4]['close'])/(scale*math.sqrt(3)),
         (close-block[-9]['close'])/(scale*math.sqrt(8)),(close-block[0]['close'])/(scale*math.sqrt(23)),
         math.log(max(tr[-1]/scale,.01)),(close-lo)/max(hi-lo,close*1e-9),
         pressure,(close-block[0]['close'])/travel if travel else 0,
         (r['open']-block[-2]['close'])/scale,
         math.log(max(statistics.mean(tr[-4:])/scale,.01))]
    return tuple(max(-6,min(6,x)) for x in f),scale


def outcome(path,side,stop,target):
    """Relative-price units; adverse gap at open, stop first for ambiguous OHLC."""
    for bar in path:
        o,h,l,c = bar
        directional_open = side*o
        if directional_open <= -stop:
            return directional_open,'gap stop'
        if directional_open >= target:
            return target,'target'
        adverse = l if side == 1 else -h
        favorable = h if side == 1 else -l
        if adverse <= -stop:
            return -stop,'stop'
        if favorable >= target:
            return target,'target'
    return side*path[-1][3],'horizon'


def plan_for(paths,weights,side,scale,price,contract,config):
    total = sum(weights)
    w = [x/total for x in weights]
    effective_n = 1/sum(x*x for x in w)
    friction = price*(2*contract.fee+2*config.slippage+.0002+config.funding_reserve_per_8h*HORIZON*BAR/28800)
    adverse = [max(0,max(-b[2] if side == 1 else b[1] for b in path)) for path in paths]
    favorable = [max(0,max(b[1] if side == 1 else -b[2] for b in path)) for path in paths]
    stops = sorted({max(.5,min(6,quantile(adverse,w,p))) for p in (.35,.6,.8)})
    targets = sorted({max(.5,min(8,quantile(favorable,w,p))) for p in (.35,.6,.8)})
    plans = []
    for stop in stops:
        for target in targets:
            results = [outcome(path,side,stop,target) for path in paths]
            net = [gross*scale-friction for gross,_ in results]
            mean = sum(p*v for p,v in zip(w,net))
            variance = sum(p*(v-mean)**2 for p,v in zip(w,net))
            # Heuristic uncertainty penalty, not a statistically valid confidence bound.
            conservative = mean-2.5*math.sqrt(variance/max(effective_n,1))
            tail_cut = quantile(net,w,.2)
            tail = [(p,v) for p,v in zip(w,net) if v <= tail_cut]
            tail_loss = -min(0,sum(p*v for p,v in tail)/sum(p for p,_ in tail))
            utility = conservative-.15*tail_loss
            plans.append(dict(side=side,label='BUY' if side == 1 else 'SELL',stop_distance=stop*scale,
                              target_distance=target*scale,mean_net_per_eth=mean,conservative_net_per_eth=conservative,
                              tail_loss_per_eth=tail_loss,utility=utility,
                              sample_win_pct=100*sum(p for p,v in zip(w,net) if v>0),
                              sample_tp_pct=100*sum(p for p,(_,reason) in zip(w,results) if reason=='target'),
                              friction_per_eth=friction,effective_n=effective_n))
    return max(plans,key=lambda p:p['utility'])


class CandleModel:
    def __init__(self,rows):
        self.rows = rows
        self.features = {i:feature(rows,i) for i in range(CONTEXT,len(rows))}

    def at(self,i,contract,config=PAPER_CONFIG):
        if i+1 < WARMUP:
            raise DataError(f'Candle Paths needs {WARMUP} completed candles')
        rows = self.rows
        current,scale = self.features[i]
        start = max(CONTEXT,i-HISTORY)
        candidates = []
        for j in range(start,i-HORIZON+1):
            f,_ = self.features[j]
            distance = sum((a-b)**2 for a,b in zip(current,f))/len(f)
            candidates.append((distance,j))
        selected = []
        # Compare every eligible endpoint; separate selected futures to reduce overlap.
        for distance,j in heapq.nsmallest(min(512,len(candidates)),candidates):
            if all(abs(j-other[1])>=HORIZON for other in selected):
                selected.append((distance,j))
                if len(selected) == NEIGHBORS:
                    break
        if len(selected) < 12:
            raise DataError('Too few separated historical paths')
        paths,weights = [],[]
        for distance,j in selected:
            _,past_scale = self.features[j]
            base = rows[j]['close']
            paths.append([tuple((rows[k][name]-base)/past_scale for name in ('open','high','low','close'))
                          for k in range(j+1,j+HORIZON+1)])
            weights.append(math.exp(-distance)*.5**((i-j)/960))
        price = rows[i]['close']
        long = plan_for(paths,weights,1,scale,price,contract,config)
        short = plan_for(paths,weights,-1,scale,price,contract,config)
        chosen = max((long,short),key=lambda p:p['utility'])
        similarity = statistics.mean(d for d,_ in selected)
        gates = [dict(name='Historical support',passed=chosen['effective_n']>=24,detail=f'{chosen["effective_n"]:.1f} effective paths / 24 minimum'),
                 dict(name='Context similarity',passed=similarity<=1.5,detail=f'{similarity:.3f} distance / 1.5 maximum'),
                 dict(name='Conservative net edge',passed=chosen['utility']>0,detail=f'${chosen["utility"]:.2f} per ETH after uncertainty and tail penalties'),
                 dict(name='Reward covers friction',passed=chosen['target_distance']>=2*chosen['friction_per_eth'],detail=f'{chosen["target_distance"]/chosen["friction_per_eth"]:.2f}x costs / 2x minimum'),
                 dict(name='Observed volatility',passed=.0003<=scale/price<=.02,detail=f'{100*scale/price:.3f}% median true range')]
        side = chosen['side'] if all(g['passed'] for g in gates) else 0
        fan = []
        for step in range(HORIZON):
            values = [price+path[step][3]*scale for path in paths]
            fan.append(dict(time=rows[i]['time']+(step+2)*BAR,p10=quantile(values,weights,.1),
                            p50=quantile(values,weights,.5),p90=quantile(values,weights,.9)))
        return dict(bar=rows[i]['time'],side=side,label={1:'BUY',-1:'SELL',0:'WAIT'}[side],
                    atr=scale,scale=scale,bias=chosen['side'],gates=gates,execution_plan=chosen,
                    stop_distance=chosen['stop_distance'],target_distance=chosen['target_distance'],
                    friction_per_eth=chosen['friction_per_eth'],plans=[long,short],fan=fan,
                    feature_values=list(current),feature_names=['Body','Upper wick','Lower wick','3-bar movement','8-bar movement',
                    '23-bar movement','Range expansion','Range location','4-bar pressure','Path efficiency','Opening gap','Recent range'],
                    candidates=len(candidates),matched_paths=len(paths),effective_paths=chosen['effective_n'],
                    last_training_outcome=rows[max(j for _,j in selected)+HORIZON]['time'],
                    context_start=rows[start]['time'],model_note='Weighted historical scenarios, not all possible futures. Model percentages are uncalibrated.',
                    reference_price=price,horizon_bars=HORIZON)


def signal(rows,contract,config=PAPER_CONFIG):
    # Enough history to make the last endpoint independent of the caller's larger dataset.
    rows = rows[-(HISTORY+CONTEXT+1):]
    return CandleModel(rows).at(len(rows)-1,contract,config)


class PathBroker(Broker):
    def step(self,q,sig,kill=False):
        initial = super().step(q,sig,kill)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            s = self.state()
            p = s['position']
            if not p or sig['bar'] <= p.get('planned_bar',0) or q['time']<s['last_quote']:
                self.db.rollback()
                return initial
            p.setdefault('initial_risk',abs(p['entry']-p['stop']))
            p.setdefault('initial_target',p['target'])
            p['planned_bar'] = sig['bar']
            plan = next(x for x in sig['plans'] if x['side']==p['side'])
            mark = q['bid'] if p['side']==1 else q['ask']
            # Do not instantaneously discard the entry due to the same forecast that created it.
            if q['time']>p['opened'] and plan['utility']<=0:
                self.close_position(s,q,'updated candle paths no longer support holding')
                s['equity'] = s['cash']
            elif q['time']>p['opened']:
                side = p['side']
                old = dict(stop=p['stop'],target=p['target'])
                stop = mark-side*plan['stop_distance']
                stop = rounded(stop,self.contract.tick,side==-1)
                p['stop'] = max(p['stop'],stop) if side==1 else min(p['stop'],stop)
                min_target = p['entry']+side*plan['friction_per_eth']
                max_target = p['entry']+side*4*p['initial_risk']
                target = mark+side*plan['target_distance']
                if side==1:
                    target = min(max_target,max(min_target,target))
                else:
                    target = max(max_target,min(min_target,target))
                target = rounded(target,self.contract.tick,side==1)
                # Replan only when the barrier remains ahead; already-crossed barriers exit next quote.
                p['target'] = target
                after = dict(stop=p['stop'],target=p['target'])
                if old != after:
                    self.event('ADJUST',dict(time=q['time'],side=side,before=old,after=after,
                                             reason='Updated conditional candle paths; stop never widens'))
            s['max_drawdown'] = max(s['max_drawdown'],1-s['equity']/s['peak'])
            self.db.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(s,allow_nan=False),))
            self.db.commit()
            return s
        except Exception:
            self.db.rollback()
            raise
