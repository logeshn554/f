"""Research-only gate ablations. Never modifies the live strategy or account."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from candle_paths import CandleModel, PAPER_CONFIG, PathBroker, effective_contract, WARMUP
from delta_paper import candles_read, save_json, utc
from eth_guard import replay_period


def run():
    root = Path(__file__).parent
    source = root/'guard_research'/'history.json'
    snapshot = json.loads(source.read_text(encoding='utf-8'))
    rows = candles_read(snapshot['candles'], snapshot['fetched_at'], fresh=False)
    model = CandleModel(rows)
    signals = [None]*len(rows)
    failures, observations = Counter(), []
    for i in range(WARMUP-1,len(rows)):
        s = model.at(i,effective_contract(snapshot['product']))
        signals[i] = s
        failures.update(g['name'] for g in s['gates'] if not g['passed'])
        observations.append(s['execution_plan'])
        if (i-WARMUP+2)%1000 == 0:
            print(f'Checked {i-WARMUP+2} causal decisions',flush=True)
    contract = effective_contract(snapshot['product'])
    split = WARMUP+int((len(rows)-WARMUP)*.7)
    variants = {}
    for name in ('baseline','mean_edge_only','sample_win_90'):
        modified = [None]*len(rows)
        for i in range(WARMUP-1,len(rows)):
            s = signals[i]
            plan = s['execution_plan']
            passed = all(g['passed'] for g in s['gates'] if g['name']!='Conservative net edge')
            if name == 'baseline':
                enter = bool(s['side'])
            elif name == 'mean_edge_only':
                enter = passed and plan['mean_net_per_eth']>0
            else:
                enter = passed and plan['utility']>0 and plan['sample_win_pct']>=90
            modified[i] = dict(s,side=plan['side'] if enter else 0)
        blocks = []
        for a,b in ((WARMUP,split),(split,len(rows))):
            report = replay_period(rows,modified,a,b,contract,PAPER_CONFIG,PathBroker,
                                   'research-ablation-'+name)
            blocks.append({k:v for k,v in report.items() if k not in ('events','curve')})
        variants[name] = dict(development=blocks[0],chronological_test=blocks[1])
    result = dict(built_at=utc(time.time()),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  first_decision=utc(rows[WARMUP-1]['time']),last_decision=utc(rows[-1]['time']),
                  decisions=len(observations),failed_gate_counts=dict(failures),
                  positive_mean_plans=sum(p['mean_net_per_eth']>0 for p in observations),
                  positive_utility_plans=sum(p['utility']>0 for p in observations),
                  max_sample_win_pct=max(p['sample_win_pct'] for p in observations),
                  variants=variants,target_achieved=False,
                  limitations=['Previously viewed data; no untouched holdout or prospective evidence.',
                               'Three hypotheses fixed before this diagnostic run; no winning variant auto-deployed.',
                               'Mean-edge ablation removes only entry uncertainty gate; exits keep v4 rules.',
                               'Sample win percentages are fitted conditional summaries, not predicted success probabilities.',
                               'Replays retain sizing, fees, spread, slippage, funding reserve and risk halts.',
                               'Trades and drawdowns are not independent; Wilson intervals are descriptive only.'])
    save_json(root/'target_research'/'diagnostic.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    run()
