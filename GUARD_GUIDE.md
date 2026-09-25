# ETH Guard: live $100 paper desk

**Current algorithm: [Candle Paths v4](CANDLE_PATHS.md).** The live service now uses conditional candle scenarios and empirical dynamic TP/SL. The v3 strategy and results below are retained as historical documentation; they are not the current strategy. Start/stop and account controls still apply. The current maximum holding time is two hours, and current research results are in `paths_research/research.json`.

Open **http://127.0.0.1:8765** while the local service is running. It uses Delta Exchange India public ETHUSD prices and a separate **$100 virtual account**. It does not connect to your private Delta account or submit orders. There are no API keys, external libraries, LLM settings, or real-money mode.

## Start and operate

From the workspace root:

```powershell
.\trading\start_guard.ps1
# Or run visibly in a terminal, with Ctrl+C to stop:
.\trading\start_guard.ps1 -Foreground
# Stop the verified background process, retaining its ledger:
.\trading\stop_guard.ps1
```

The hidden service continues while this computer and process stay running; closing the dashboard does not stop it. It does not restart automatically after reboot. The default port is 8765. The account directory is `trading/guard_live`.

- **Pause entries** prevents new entries while existing positions continue receiving exit management.
- **Resume entries** re-enables new entries; a persistent risk halt cannot be bypassed.
- **Close paper position** queues a simulated close at the next valid quote and pauses entries. During a feed outage it waits for valid data rather than inventing a fill.
- A second server cannot own the same paper account. Restart retains equity, positions, funding reserve debits, and control settings.
- For a foreground process, Ctrl+C stops the service but preserves its paper position. Exits do not run while the service is stopped. Restart closes breached barriers at the next observed quote, not retrospectively.

## New algorithm and dynamic exits

ETH Guard v3 is a fixed, unoptimized hypothesis: hourly trend confirmation plus 15-minute pullback recovery. Each signal uses exactly 480 completed 15-minute candles. Only complete four-candle hourly groups are eligible. Hourly close, EMA20, EMA60, and slope must agree. The lower timeframe must touch its contemporaneous EMA20 in the previous four candles, reclaim it, and break the prior candle. RSI, ATR/price, efficiency and estimated friction gates also apply.

No parameter search was performed. These thresholds are design choices to test, not conclusions proven by the cited research.

For each entry:

1. Start with a stop **2 ATR** away and a target **4 ATR** away. ATR is computed from the completed market candles, so dollar distances change with volatility.
2. Planned risk is **0.5% of equity** (initially about **$0.50**), including estimated friction. Round down to integer Delta contracts. If one contract cannot fit the budget, skip. Cap notional at 1× equity.
3. After a favorable move of one initial risk unit, on the next eligible completed-candle observation the stop may tighten toward a 2 ATR trail or a cost-adjusted breakeven level. It never widens. Breakeven is approximate and does not guarantee no loss after funding/gaps.
4. If the hourly trend still agrees, the target can extend, capped at **3 initial risk units** from entry. It does not move farther indefinitely.
5. Exit at stop, target, 8 hours, a risk gate, or an operator paper-close request. Wait 15 minutes after exit before another entry.

Entries must occur within 120 seconds of signal-candle completion. Starting later can show a LONG/SHORT setup while staying flat. This is not a missed-fill error: old signals are not executed retrospectively.

## Costs, protections and limitations

The effective India fee is the product's public taker rate multiplied by 1.18 for GST. All simulated market fills use bid/ask plus 3bp adverse slippage, rounded against the trader. Entry size is capped at displayed top-level size; exits assume sufficient depth. Funding is **a 3bp-per-8-hour continuous reserve debit in either direction**, not actual settled funding. INR conversion and tax on profits are excluded.

The broker uses SQLite WAL and full synchronization, with atomic fill/state transactions. Duplicate/out-of-order quote timestamps cannot repeat fills. A session lock prevents two workers managing the same account. Quotes older than 30 seconds, future timestamps over 5 seconds, gapped or malformed candles, nonoperational products, or changed contract specifications block execution. Risk gates are 2% daily loss and 5% observed drawdown. Polling uses retries and backoff, with rotating logs. The dashboard signals stale or disconnected data instead of displaying old data as live.

The service binds only to 127.0.0.1. Browser controls require a local session token and same-origin requests; unrecognized hosts and arbitrary paths are rejected. No order endpoint exists in the API allowlist. Do not expose this local service to the internet: it has no multi-user authentication or deployment hardening.

This is a hardened **research/paper system, not a certified production execution platform**. Five-second polling misses intrapoll paths; downtime can miss stops. Gaps can exceed the intended risk and drawdown limits. Actual funding, depth-aware fills, exchange reconciliation, real execution, and long-duration operational certification are not implemented. Health and tests are not evidence of profitability.

## Research and measured results

The saved dataset contains **9,120 candles**: 90 days plus five days of warmup, from Delta public prices. A 70/30 chronological split follows warmup. Each period starts independently with $100, and three independent holdout blocks check temporal stability. A cost stress doubles fees, slippage, and the funding reserve. It uses the same signal sequence to isolate execution-cost sensitivity.

Initial measured results (2026-09-25):

| Period | Return | Closed trades | Win rate |
|---|---:|---:|---:|
| Development | -4.75% | 19 | 26.3% |
| Holdout | -4.17% | 40 | 32.5% |
| Double-cost holdout | -4.66% | 38 | 31.6% |

**This algorithm did not establish profitability and did not meet a 90% win-rate target.** The holdout 95% Wilson interval is about 20.1%–48.0%, with the usual independence limitation. The live $100 paper account is separate from these historical losses. Do not mistake replay trades for forward fills.

Historical execution assumes a 2bp spread, adverse intrabar extreme first, estimated funding, and current fee levels for the entire sample. It cannot reconstruct actual historical order-book paths. The report saves the strategy file's SHA-256 for reproducibility. Reusing this observed dataset for later tuning would make it research data, not a fresh unseen test.

```powershell
# Reproduce from saved data, no network:
python trading/eth_guard.py --input trading/guard_research/history.json
# Fetch a new research sample:
python trading/eth_guard.py --days 90
# Unit and execution tests:
python -m unittest discover -s trading -p "test_*.py"
# Running-service read-only integration checks:
python trading/verify_guard.py
```

## Files

- `guard_live/paper.sqlite3`: forward account state, events, and last 30 days of observations.
- `guard_live/health.json`: latest status; check its timestamp.
- `guard_live/controls.json`: persisted pause/close requests.
- `guard_live/service.log`: rotating feed and control log.
- `guard_live/process.json`: running process ID, port, and start time.
- `guard_live/verification.json`: read-only service checks.
- `guard_research/history.json`: public research dataset.
- `guard_research/research.json`: historical results, equity curves, assumptions, and strategy hash.

## Research sources and what they support

- [Delta API documentation](https://docs.delta.exchange/) specifies public candles, ticker, contract details, and rate limits. This implementation uses public REST polling; researching the WebSocket API does not mean a WebSocket transport was implemented.
- [Delta fee schedule](https://www.delta.exchange/fees) lists futures taker/maker fees and 18% GST on trading fees. The implementation reads the product fee and adds GST for India.
- [Liu and Tsyvinski, Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877) reports a cryptocurrency momentum effect in its sample. This motivates a momentum hypothesis; it does **not** validate these ETH intraday rules or a 90% target.
- [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) explains why selecting strategies using backtest results can mislead. This implementation avoids parameter searching and separates chronological tests, but does not implement the paper's CSCV/PBO estimator.
