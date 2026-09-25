"""Key-free ETH research: standard library only; never places orders."""
import argparse
import csv
import datetime as dt
import json
import math
import statistics
import urllib.request
from pathlib import Path


def validate(rows):
    previous = ''
    for row in rows:
        date = row['date']
        dt.date.fromisoformat(date)
        if date <= previous:
            raise ValueError('Dates must be unique and strictly increasing')
        if previous and (dt.date.fromisoformat(date) - dt.date.fromisoformat(previous)).days != 1:
            raise ValueError('Daily candles must be consecutive; missing dates invalidate daily indicators')
        previous = date
        o, h, l, c = (float(row[k]) for k in ('open', 'high', 'low', 'close'))
        if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)):
            raise ValueError('Prices must be positive finite numbers')
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Invalid OHLC candle')
        row.update(open=o, high=h, low=l, close=c)
    if len(rows) < 240:
        raise ValueError('At least 240 daily candles required')
    return rows


def fetch():
    end = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=299)
    url = ('https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=86400'
           f'&start={start.isoformat()}&end={end.isoformat()}')
    request = urllib.request.Request(url, headers={'User-Agent': 'ETHQuantResearch/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        candles = json.load(response)
    rows = [{'date': dt.datetime.fromtimestamp(x[0], dt.timezone.utc).date().isoformat(),
             'open': x[3], 'high': x[2], 'low': x[1], 'close': x[4]}
            for x in sorted(candles) if x[0] < end.timestamp()]
    return validate(rows), url


def indicators(rows):
    result = []
    closes = [r['close'] for r in rows]
    ranges = []
    for i, row in enumerate(rows):
        prev = closes[max(0, i - 1)]
        ranges.append(max(row['high'] - row['low'], abs(row['high'] - prev), abs(row['low'] - prev)))
        if i < 100:
            result.append(None)
            continue
        sma20 = statistics.mean(closes[i-19:i+1])
        sma100 = statistics.mean(closes[i-99:i+1])
        old100 = statistics.mean(closes[i-100:i])
        changes = [closes[j] - closes[j-1] for j in range(i-13, i+1)]
        gain = sum(max(v, 0) for v in changes)
        loss = sum(max(-v, 0) for v in changes)
        rsi = 100 * gain / (gain + loss) if gain + loss else 50
        atr = statistics.mean(ranges[i-13:i+1])
        signal = closes[i] > sma100 and sma100 > old100 and closes[i] < sma20 and 30 <= rsi <= 48 and atr / closes[i] < .08
        result.append(dict(sma20=sma20, sma100=sma100, rsi14=rsi, atr14=atr,
                           signal=signal, regime='uptrend' if closes[i] > sma100 and sma100 > old100 else 'defensive'))
    return result


def exit_price(row, stop, target):
    # Adverse gaps fill at open; when both barriers occur, assume stop first.
    if row['open'] <= stop:
        return row['open'], 'gap stop'
    if row['open'] >= target:
        return target, 'target'
    if row['low'] <= stop:
        return stop, 'stop'
    if row['high'] >= target:
        return target, 'target'
    return None


def backtest(rows, ind, start, end, fee=.001, slippage=.0005):
    cash = peak = 10000.0
    drawdown = 0.0
    position = None
    trades = []
    for i in range(start, end):
        row, previous = rows[i], ind[i-1]
        if position is None and previous and previous['signal']:
            entry = row['open'] * (1 + slippage)
            distance = 2 * previous['atr14']
            qty = min(cash * .005 / (distance + entry * (2 * fee + 2 * slippage)), cash / (entry * (1 + fee)))
            if qty > 0:
                cost = qty * entry * (1 + fee)
                cash -= cost
                position = dict(entry=entry, qty=qty, cost=cost, stop=entry-distance,
                                target=entry+1.5*distance, index=i, date=row['date'])
        if position:
            p = position
            outcome = exit_price(row, p['stop'], p['target'])
            if outcome is None and (i-p['index'] >= 10 or i == end-1):
                outcome = row['close'], 'time/end'
            if outcome:
                price, reason = outcome
                proceeds = p['qty'] * price * (1-slippage) * (1-fee)
                cash += proceeds
                trades.append(dict(entry_date=p['date'], exit_date=row['date'],
                                   pnl=round(proceeds-p['cost'], 4), reason=reason))
                position = None
        equity = cash + (position['qty'] * row['close'] * (1-slippage) * (1-fee) if position else 0)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)
    wins = sum(t['pnl'] > 0 for t in trades)
    n = len(trades)
    p = wins/n if n else 0
    z = 1.96
    half = z * math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n) if n else 0
    center = (p+z*z/(2*n))/(1+z*z/n) if n else 0
    profits = sum(max(t['pnl'], 0) for t in trades)
    losses = -sum(min(t['pnl'], 0) for t in trades)
    benchmark = 100 * (rows[end-1]['close']*(1-slippage)*(1-fee)/(rows[start]['open']*(1+slippage)*(1+fee))-1)
    return dict(start=rows[start]['date'], end=rows[end-1]['date'], trades=n,
                win_rate_pct=100*p if n else None,
                win_rate_95pct_interval=[100*(center-half), 100*(center+half)] if n else None,
                net_return_pct=100*(cash/10000-1), max_close_drawdown_pct=100*drawdown,
                profit_factor=profits/losses if losses else None,
                mean_trade_pnl=(profits-losses)/n if n else None,
                buy_hold_return_pct=benchmark, trade_log=trades)


def analyze(rows, source, fee=.001, slippage=.0005):
    ind = indicators(rows)
    split = 100 + int((len(rows)-100)*.6)
    last = ind[-1]
    return dict(instrument='ETH-USD', timeframe='daily', source=source,
                last_completed_candle=rows[-1]['date'], close=rows[-1]['close'],
                latest=last, next_open_signal='LONG candidate' if last['signal'] else 'WAIT',
                assumptions=dict(fee_per_side=fee, slippage_per_side=slippage, risk_fraction=.005,
                                 starting_cash_per_period=10000, leverage=1),
                development=backtest(rows, ind, 101, split, fee, slippage),
                holdout=backtest(rows, ind, split, len(rows), fee, slippage),
                limitations=['Fixed unoptimized rules; no 90% win-rate or profit guarantee.',
                             'Small single-asset sample; holdout is a historical simulation, not live validation.',
                             'Daily OHLC cannot reconstruct intraday paths; stop-first assumption; gaps can exceed risk budget.',
                             'Fees and slippage are estimates. Taxes, liquidity impact and outages excluded.',
                             'Drawdown uses daily closes; profit factor null means undefined, not zero.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, help='Daily ETH OHLC CSV; otherwise fetch public Coinbase candles')
    parser.add_argument('--output', type=Path, default=Path('eth_report.json'))
    parser.add_argument('--fee-bps', type=float, default=10)
    parser.add_argument('--slippage-bps', type=float, default=5)
    args = parser.parse_args()
    for value in (args.fee_bps, args.slippage_bps):
        if not math.isfinite(value) or not 0 <= value <= 1000:
            parser.error('Costs must be finite and between 0 and 1000 basis points')
    try:
        if args.csv:
            with args.csv.open(newline='', encoding='utf-8-sig') as f:
                rows = validate(list(csv.DictReader(f)))
            source = str(args.csv)
        else:
            rows, source = fetch()
        report = analyze(rows, source, args.fee_bps/10000, args.slippage_bps/10000)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        with args.output.with_suffix('.candles.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['date', 'open', 'high', 'low', 'close'])
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({k:v for k,v in report.items() if k not in ('development', 'holdout')}, indent=2))
        print('HOLDOUT:', json.dumps({k:v for k,v in report['holdout'].items() if k != 'trade_log'}, indent=2))
        print('Saved:', args.output.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Analysis failed: {exc}\n')


if __name__ == '__main__':
    main()
