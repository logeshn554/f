"""Prequential replay of Candle Paths with no future outcome in a decision's context."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from delta_paper import candles_read, save_json, utc
from eth_guard import replay_period
from candle_paths import CandleModel, PathBroker, VERSION, PAPER_CONFIG, effective_contract, WARMUP


def research(snapshot,days=30):
    rows = candles_read(snapshot['candles'],snapshot['fetched_at'],fresh=False)
    start = max(WARMUP,len(rows)-days*96)
    if len(rows)-start < 400:
        raise ValueError('Need at least 400 evaluation candles after warmup')
    c = effective_contract(snapshot['product'])
    model = CandleModel(rows)
    signals = [None]*len(rows)
    for i in range(start-1,len(rows)):
        signals[i] = model.at(i,c)
        if (i-start+1)%400 == 0:
            print(f'Calculated {i-start+1}/{len(rows)-start} causal candle forecasts',flush=True)
    split = start+int((len(rows)-start)*.7)
    def period(a,b,contract=c,config=PAPER_CONFIG):
        return replay_period(rows,signals,a,b,contract,config,PathBroker,VERSION)
    development = period(start,split)
    holdout = period(split,len(rows))
    stressed = period(split,len(rows),replace(c,fee=2*c.fee),
                      replace(PAPER_CONFIG,slippage=2*PAPER_CONFIG.slippage,funding_reserve_per_8h=.0006))
    blocks = []
    for j in range(3):
        report = period(split+(len(rows)-split)*j//3,split+(len(rows)-split)*(j+1)//3)
        blocks.append({k:v for k,v in report.items() if k not in ('curve','events')})
    latest = signals[-1]
    # Assess fan containment on nonoverlapping 8-bar horizons; not fitted/calibrated here.
    forecasts = [(signals[i],rows[i+8]['close']) for i in range(split-1,len(rows)-8,8)]
    coverage = sum(s['fan'][-1]['p10']<=value<=s['fan'][-1]['p90'] for s,value in forecasts)
    enough = holdout['closed_trades']>=100
    interval = holdout['confidence_interval']
    return dict(strategy=VERSION,built_at=utc(time.time()),bars=len(rows),evaluation_bars=len(rows)-start,
                source=snapshot['source'],config=asdict(PAPER_CONFIG),
                strategy_sha256=hashlib.sha256(Path(__file__).with_name('candle_paths.py').read_bytes()).hexdigest(),
                development=development,holdout=holdout,cost_stress=stressed,chronological_blocks=blocks,latest_signal=latest,
                forecast_check=dict(samples=len(forecasts),empirical_10_90_coverage_pct=100*coverage/len(forecasts) if forecasts else None,
                                    note='Observed containment, not a calibrated 80% predictive guarantee.'),
                assessment=dict(status='RESEARCH ONLY',target_win_rate=90,target_supported=bool(enough and interval and interval[0]>=90),
                                sufficient_sample=enough,positive_holdout_and_stress=holdout['return_pct']>0 and stressed['return_pct']>0,
                                production_ready=False,note='Previously viewed dataset. Chronological replay is not a pristine unseen validation set.'),
                assumptions=['Custom conditional candle-path decision logic; standard statistical building blocks, no claim of universal novelty.',
                             'Every eligible past endpoint is compared, but only 64 separated paths at most are retained; unknown future scenarios remain.',
                             'Context features and future labels in each selected historical path end at or before the decision candle.',
                             '$100 per independent replay period; max 0.5% planned risk and 1x notional; integer contracts.',
                             'Current taker fee plus 18% GST, 2bp assumed historical spread, 3bp slippage per side, funding reserve 3bp/8h.',
                             'Data was viewed during earlier strategy research; the last 30% is a chronological replay segment, not untouched holdout evidence.',
                             'BUY/SELL barrier selection searches up to 18 local candidates; this selection can overfit despite penalties.',
                             'Model win percentages and 10–90% scenario fan are uncalibrated conditional sample summaries.',
                             'Adverse extreme first; quote depth, actual funding, tax on profits, INR conversion and outages are not simulated.',
                             'Cost stress uses frozen decisions/plans to isolate execution frictions; profit factor and Wilson interval use net closed trades.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path(__file__).with_name('guard_research')/'history.json')
    p.add_argument('--directory',type=Path,default=Path(__file__).with_name('paths_research'))
    p.add_argument('--days',type=int,default=30)
    args = p.parse_args()
    if not 7<=args.days<=90:
        p.error('days must be 7..90')
    result = research(json.loads(args.input.read_text(encoding='utf-8')),args.days)
    save_json(args.directory/'research.json',result)
    print(json.dumps({k:{a:b for a,b in result[k].items() if a not in ('events','curve')} for k in ('development','holdout','cost_stress')},indent=2))
