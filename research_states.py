"""Frozen, research-only hourly candle-state hypothesis; public GET data only."""
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from candle_paths import PAPER_CONFIG, outcome
from delta_paper import BAR, Broker, DataError, PublicDelta, number, save_json, utc
from eth_guard import effective_contract, finish, quote, wilson

ROOT = Path(__file__).parent/'state_research'
HOUR, HORIZON, CONTEXT = 3600, 8, 24
END = int(datetime(2026,6,20,tzinfo=timezone.utc).timestamp())
START = END-365*24*HOUR
CONFIG = replace(PAPER_CONFIG,max_holding_seconds=HORIZON*HOUR)
# Equal initial reward/risk; no tiny TP and unbounded SL to inflate wins.
ACTIONS = ((1,1.5),(-1,1.5),(1,2.5),(-1,2.5))


def validate(raw):
    rows = []
    for item in sorted(raw,key=lambda b:b['time']):
        ts = int(item['time'])
        vals = {k:number(item[k]) for k in ('open','high','low','close')}
        if ts%HOUR or (rows and ts-rows[-1]['time']!=HOUR):
            raise DataError('Hourly candle gap, duplicate or misalignment')
        if not vals['low']<=min(vals['open'],vals['close'])<=max(vals['open'],vals['close'])<=vals['high']:
            raise DataError('Invalid hourly OHLC')
        rows.append(dict(time=ts,**vals))
    if not rows or rows[0]['time']!=START or rows[-1]['time']!=END-HOUR:
        raise DataError('Incomplete requested historical coverage')
    return rows


def download():
    api, merged = PublicDelta(), {}
    for a in range(START,END,1800*HOUR):
        page = api.get('/v2/history/candles',symbol='ETHUSD',resolution='1h',
                       start=a,end=min(END,a+1800*HOUR))
        for row in page:
            t = int(row['time'])
            if START<=t<END:
                if t in merged and merged[t]!=row:
                    raise DataError('Conflicting page boundary')
                merged[t]=row
        print(f'Downloaded {len(merged)} hourly candles',flush=True)
    rows = validate(list(merged.values()))
    snapshot = dict(candles=rows,product=api.get('/v2/products/ETHUSD'),
                    source=api.base,fetched_at=time.time())
    save_json(ROOT/'history.json',snapshot)
    return snapshot


def context(rows,i):
    block = rows[i-CONTEXT+1:i+1]
    scale = statistics.median(max(r['high']-r['low'],abs(r['high']-rows[i-CONTEXT+j]['close']),
                                  abs(r['low']-rows[i-CONTEXT+j]['close'])) for j,r in enumerate(block))
    r = rows[i]
    upper = r['high']-max(r['open'],r['close'])
    lower = min(r['open'],r['close'])-r['low']
    # Eight fixed cells, no fitting bins on future data.
    cell = (int(r['close']>rows[i-6]['close']),int(r['close']>r['open']),int(lower>upper))
    return cell,max(scale,r['close']*.0001)


def label(rows,i,side,multiple,scale,cost):
    """Per-scale net outcome using next open; conservative full-horizon funding."""
    entry = rows[i+1]['open']*(1+side*(.0001+CONFIG.slippage))
    path = [tuple((r[k]-entry)/scale for k in ('open','high','low','close'))
            for r in rows[i+1:i+HORIZON+1]]
    gross,_ = outcome(path,side,multiple,multiple)
    exit_mid = entry+side*gross*scale
    exit_fill = exit_mid*(1-side*(.0001+CONFIG.slippage))
    net = side*(exit_fill-entry)-cost.fee*(entry+exit_fill)-entry*CONFIG.funding_reserve_per_8h
    return net/scale


def posterior(local,global_values):
    if len(local)<40 or not global_values:
        return None
    prior_n = 24
    gp = sum(x>0 for x in global_values)/len(global_values)
    gm = statistics.mean(global_values)
    n = len(local)
    probability = (sum(x>0 for x in local)+prior_n*gp)/(n+prior_n)
    mean = (sum(local)+prior_n*gm)/(n+prior_n)
    # Uncertainty penalty is a heuristic, not a calibrated interval.
    lower = mean-1.96*statistics.stdev(local)/math.sqrt(n)
    return dict(p=probability,mean=mean,lower=lower,samples=n)


def forecasts(rows,cost):
    local,global_values = defaultdict(list),defaultdict(list)
    known = {i:context(rows,i) for i in range(CONTEXT,len(rows))}
    signals,calibration = {},[]
    for i in range(CONTEXT,len(rows)-HORIZON):
        j = i-HORIZON
        # Disjoint eight-hour outcome windows. Admit only fully completed labels.
        if j>=CONTEXT and j%HORIZON==0:
            cell,scale = known[j]
            for action in ACTIONS:
                value = label(rows,j,*action,scale,cost)
                local[(cell,action)].append(value)
                global_values[action].append(value)
        cell,scale = known[i]
        plans = []
        for action in ACTIONS:
            stats = posterior(local[(cell,action)],global_values[action])
            if stats:
                plans.append(dict(**stats,side=action[0],multiple=action[1]))
        if plans:
            chosen = max(plans,key=lambda x:x['lower'])
            signals[i] = dict(chosen,scale=scale,cell=cell,last_admissible_label=i)
            if i%HORIZON==0:
                actual = label(rows,i,chosen['side'],chosen['multiple'],scale,cost)>0
                base = global_values[(chosen['side'],chosen['multiple'])]
                calibration.append(dict(index=i,p=chosen['p'],actual=int(actual),
                                        baseline=sum(x>0 for x in base)/len(base)))
    return signals,calibration


def replay(rows,predictions,a,b,cost,threshold,stress=False):
    cfg = replace(CONFIG,slippage=CONFIG.slippage*2,funding_reserve_per_8h=CONFIG.funding_reserve_per_8h*2) if stress else CONFIG
    cost = replace(cost,fee=cost.fee*2) if stress else cost
    broker = Broker(':memory:',cost,config=cfg,strategy_version='hourly-state-research-v1')
    try:
        for i in range(a,b):
            r,plan = rows[i],predictions.get(i-1)
            active = plan and plan['lower']>0 and plan['p']>=threshold
            # Broker expects a 15m timestamp; this represents the same hourly close.
            sig = dict(bar=rows[i-1]['time']+HOUR-BAR,side=plan['side'] if active else 0,
                       atr=plan['scale'] if plan else 1)
            if plan:
                sig['execution_plan'] = dict(stop_distance=plan['scale']*plan['multiple'],
                                             target_distance=plan['scale']*plan['multiple'])
            broker.step(quote(r['open'],r['time']),sig)
            p = broker.state()['position']
            extremes = (r['low'],r['high']) if not p or p['side']==1 else (r['high'],r['low'])
            for offset,price in enumerate(extremes,1):
                p = broker.state()['position']
                if p:
                    factor = .9999 if p['side']==1 else 1.0001
                    mark = price*factor
                    if (mark-p['stop'])*p['side']<=0:
                        price = p['stop']/factor
                    elif (mark-p['target'])*p['side']>=0:
                        price = p['target']/factor
                broker.step(quote(price,r['time']+offset),sig)
            broker.step(quote(r['close'],r['time']+HOUR-1),sig)
        finish(broker,quote(rows[b-1]['close'],rows[b-1]['time']+HOUR))
        summary = broker.summary()
        return dict(**summary,confidence_interval=wilson(summary['wins'],summary['closed_trades']))
    finally:
        broker.db.close()


def run():
    ROOT.mkdir(exist_ok=True)
    manifest_path = ROOT/'preregistration.json'
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not manifest_path.exists():
        save_json(manifest_path,dict(created_at=utc(time.time()),code_sha256=digest,start=utc(START),end=utc(END),
                  actions=ACTIONS,win_thresholds=[0,.6,.9],test_start_fraction=.75,
                  note='Rules saved before requesting this disjoint historical cohort. No live deployment.'))
    manifest = json.loads(manifest_path.read_text())
    if manifest['code_sha256']!=digest:
        raise ValueError('Frozen code changed; explicitly register a new experiment instead of overwriting')
    snapshot = json.loads((ROOT/'history.json').read_text()) if (ROOT/'history.json').exists() else download()
    rows,cost = validate(snapshot['candles']),effective_contract(snapshot['product'])
    predictions,calibration = forecasts(rows,cost)
    split,end = int(len(rows)*.75),len(rows)-HORIZON
    test = [x for x in calibration if split<=x['index']<end]
    variants = {}
    for threshold in (0,.6,.9):
        variants[str(threshold)] = dict(test=replay(rows,predictions,split,end,cost,threshold),
                                       cost_stress=replay(rows,predictions,split,end,cost,threshold,True))
    report = dict(built_at=utc(time.time()),code_sha256=digest,
                  data_sha256=hashlib.sha256((ROOT/'history.json').read_bytes()).hexdigest(),
                  bars=len(rows),test_start=utc(rows[split]['time']),test_end=utc(rows[end]['time']),
                  supported_forecasts=len(predictions),positive_lower_edge=sum(p['lower']>0 for p in predictions.values()),
                  max_estimated_win_pct=100*max((p['p'] for p in predictions.values()),default=0),
                  calibration_samples=len(test),
                  brier_score=statistics.mean((x['p']-x['actual'])**2 for x in test) if test else None,
                  baseline_brier=statistics.mean((x['baseline']-x['actual'])**2 for x in test) if test else None,
                  variants=variants,target_achieved=False,
                  limitations=['Historical cohort earlier than the previously viewed snapshot; not prospective evidence.',
                               'Online cell statistics use only matured, nonoverlapping eight-hour labels.',
                               'Cell contexts overlap; samples are dependent. No calibrated 90% guarantee.',
                               'Current fee/GST schedule applied historically; funding reserve is not settlement funding.',
                               'Labels approximate costs; portfolio replay adds integer sizing, adverse rounding and account stops.',
                               'Hourly OHLC cannot reproduce queue depth or intrabar path; adverse barrier first.',
                               'Frozen initial barriers scale with current candle ranges; no live dynamic-exit replacement.'])
    save_json(ROOT/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    run()
