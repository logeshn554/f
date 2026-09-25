"""Read-only integration checks against the running local paper service."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def request(path,headers=None,body=None):
    req = urllib.request.Request('http://127.0.0.1:8765'+path,headers=headers or {},data=body)
    try:
        with urllib.request.urlopen(req,timeout=10) as response:
            return response.status,dict(response.headers),response.read()
    except urllib.error.HTTPError as exc:
        return exc.code,dict(exc.headers),exc.read()


if __name__ == '__main__':
    checks = {}
    code,headers,body = request('/api/state')
    state = json.loads(body)
    checks['state_api'] = code == 200
    checks['paper_balance_config'] = state['config']['initial_cash'] == 100
    checks['fresh_quote'] = -5 <= time.time()-state['quote']['time'] <= 30
    checks['active_worker'] = state['status'] == 'LIVE'
    checks['research_loaded'] = bool(state['research']) and state['research']['assessment']['production_ready'] is False
    checks['candle_paths_active'] = state['version'] == 'candle-paths-v4.0' == state['summary']['strategy']
    checks['automatic_entries_enabled'] = state['controls']['paused'] is False
    checks['both_directions_evaluated'] = {p['side'] for p in state['signal']['plans']} == {-1,1}
    checks['scenario_fan_present'] = len(state['signal']['fan']) == 8
    checks['training_outcomes_are_past'] = state['signal']['last_training_outcome'] <= state['signal']['bar']
    evidence = state.get('forward_evidence',{})
    checks['prospective_recorder_active'] = len(evidence.get('model_hash','')) == 64
    checks['prospective_counts_consistent'] = evidence.get('forecasts',-1) == evidence.get('matured',-2)+evidence.get('pending',-3)
    checks['security_headers'] = "frame-ancestors 'none'" in headers.get('Content-Security-Policy','')
    checks['reject_wrong_host'] = request('/api/state',{'Host':'untrusted.invalid'})[0] == 403
    checks['reject_wrong_origin'] = request('/api/control',{'Origin':'https://untrusted.invalid','X-Paper-Token':state['token']},b'{"action":"pause"}')[0] == 403
    checks['reject_missing_token'] = request('/api/control',{'Origin':'http://127.0.0.1:8765'},b'{"action":"pause"}')[0] == 403
    checks['reject_path_traversal'] = request('/../guard_server.py')[0] == 404
    checks['live_orders_route_absent'] = request('/v2/orders')[0] == 404
    time.sleep(7)
    second = json.loads(request('/api/state')[2])
    checks['feed_advances'] = second['quote']['time'] > state['quote']['time']
    report = dict(passed=all(checks.values()),checks=checks,checked_at=second['checked_at'],
                  summary=second['summary'],note='Read-only checks; invalid control requests were rejected.')
    Path(__file__).with_name('guard_live').joinpath('verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
