"""Read-only public connectivity probe; no credentials or order endpoints."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

if __name__ == '__main__':
    base = 'https://api.india.delta.exchange'
    end = int(time.time())
    paths = {'product': '/v2/products/ETHUSD', 'ticker': '/v2/tickers/ETHUSD',
             'candles': '/v2/history/candles?' + urllib.parse.urlencode(dict(symbol='ETHUSD', resolution='15m', start=end-900*1500, end=end))}
    output = {}
    for name, path in paths.items():
        request = urllib.request.Request(base+path, headers={'User-Agent': 'ETH-Paper-Research/1.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            output[name] = json.load(response)
        result = output[name].get('result')
        print(name, json.dumps(result if name != 'candles' else {'count': len(result), 'latest': max(result, key=lambda b: b['time'])}), flush=True)
    Path(__file__).with_name('delta_probe.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
