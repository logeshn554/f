# Candle Paths v4 — custom ETH scenario model

The live dashboard at **http://127.0.0.1:8765** now uses this algorithm. It keeps the original **$100 paper account**, its journal, and risk limits. The previous EMA/RSI strategy is no longer the active decision model. Existing public data, broker accounting, and dashboard infrastructure are reused.

This is a custom trading design built from familiar statistical techniques, not a claim that no one has ever used similar mathematics. No finite calculation can enumerate all market futures. Candle histories omit order flow, news, liquidity changes and other causes of price moves.

## How it decides BUY, SELL, or WAIT

1. Read the last 24 completed 15-minute candles. Measure 12 features: body fraction, upper/lower wick fractions, movements over 3/8/23 bars, range expansion, position within the recent range, four-bar body pressure, path efficiency, opening gap, and recent range change. Normalize moves by the median true range. No EMA, RSI, or fixed indicator-cross entry rule is used.
2. Compare this feature vector with **every eligible endpoint in the last 1,800 bars**. Only contexts whose next eight candles are already observed can enter the training set. This is about 18.75 days of historical context; it is not the entire crypto market.
3. Select up to **64 similar contexts**, separating their endpoints by at least eight candles so their future outcome windows do not overlap. Weight by feature similarity and recency. Context windows themselves can still overlap, so these are not independent observations.
4. Rescale each known eight-candle continuation by the current volatility scale. The resulting empirical paths provide possible two-hour continuations—not an exhaustive scenario universe or a calibrated probability distribution.
5. For both BUY and SELL, derive stop and target distances from the weighted 35th/60th/80th percentiles of adverse and favorable excursions. Compare up to 18 direction/stop/target combinations. Each historical path is simulated with gap fills and adverse-first handling when both barriers occur in a candle.
6. Subtract estimated fees, GST, spread, slippage and the two-hour funding reserve from each path return. Score each plan as:

   `score = weighted mean net return − 2.5 × weighted SD / sqrt(effective sample count) − 0.15 × downside tail loss`

   These are dollar-per-ETH scores. The uncertainty penalty is a heuristic, **not a validated statistical confidence bound**. Choosing a best local candidate can itself overfit.
7. Enter only if the best score is positive, support is at least 24 effective paths, similarity and volatility checks pass, and target distance covers at least twice estimated friction. Otherwise WAIT. Model sample win percentages are not forecasts with proven calibration.

## Dynamic take-profit, stop-loss, and early selling/buying back

- Initial TP and SL come from the selected empirical path plan, rather than fixed dollar values or fixed ATR multiples.
- Size down to integer Delta contracts, with approximately **0.5% of equity planned risk** (initially $0.50), and no more than 1× notional. If the minimum contract exceeds the risk budget, do not enter.
- After each new completed candle, evaluate fresh paths for the held direction. Tighten the stop when the revised stop is closer; never widen it.
- Revise the target from the new plan, bounded by an estimated cost-covering level and four initial risk units from entry. The target may move closer or farther. At entry, the original selected barrier is preserved.
- Close if the updated score for the held direction is no longer positive, or if a stop/target, two-hour timeout, risk gate, or operator close occurs. Selling closes a long; buying back closes a short. A new opposite entry still obeys cooldown and fresh-signal requirements.
- Entries are only eligible within 120 seconds of a signal candle's completion. Starting later does not invent an earlier fill.

## What is live and what is simulated

Delta India public ETHUSD quotes and candles are live. Cash, contracts, entries, exits, TP and SL are local simulations. No private Delta account is connected, no API key is requested, and there is no order-submission route. Five-second polling can miss price excursions. Gaps and outages can cause losses beyond planned risk.

Current product taker commission is multiplied by 1.18 for India GST. Fills include bid/ask, adverse slippage and adverse tick rounding. Funding uses a **3bp per 8-hour continuous reserve debit**, not actual funding settlements. Income taxes, INR conversion, depth-aware exit fills and liquidation are not modeled. See the older [operations guide](GUARD_GUIDE.md) for service controls, files and safeguards; its v3 algorithm/results section is historical.

The dashboard shows both direction scores, candidate exit distances and a 10th/50th/90th-percentile scenario fan. The fan is an empirical summary, not a guaranteed 80% predictive interval. A BUY candidate with a negative score is still WAIT, even if its sample win percentage exceeds SELL's.

## Measured evidence

The 30-day chronological replay evaluated **2,880 decision candles** using the previously saved dataset, with earlier candles supplying context. The data had already been viewed during v3 research; this is **not an untouched validation set**.

Both replay segments and the double-cost stress produced **zero trades** because no plan passed all gates. Equity remained $100. This establishes neither profitability nor a win rate. The 90% target remains unsupported. Do not interpret no losses when no trades occurred as trading success.

On 108 nonoverlapping two-hour forecast checks, 82.4% of observed closes fell inside the empirical 10–90% band. This is an observed containment fraction on the reused dataset, not proven calibration and not a trade win rate.

The tests use explicitly synthetic trending candles to confirm that BUY and SELL can both execute, and that dynamic exits work. Those test trades are not market performance evidence and are not inserted into the real paper journal.

## Run, stop and reproduce

```powershell
.\trading\start_guard.ps1
.\trading\stop_guard.ps1
python trading/research_paths.py
python -m unittest discover -s trading -p "test_*.py"
python trading/verify_guard.py
```

The running account is in `trading/guard_live`; the v4 replay is `trading/paths_research/research.json`. The one-time migration backed up the prior SQLite ledger and retained its balance, history and risk halts. Pause/resume is available in the dashboard. Closing the browser does not stop the local server; shutting down the computer does. Production readiness and long-duration forward profitability are unproven.

## Sources and limits of attribution

- [Delta API documentation](https://docs.delta.exchange/) supplies the public data interface, not the decision rules.
- [Delta fee schedule](https://www.delta.exchange/fees) supplies the fee/GST context.
- [NIST on predictive uncertainty](https://www.itl.nist.gov/div898/handbook/pmd/section5/pmd512.htm) explains why future-outcome uncertainty exceeds uncertainty about an average. Its regression interval formula is not implemented here, and this model's empirical bands are not presented as equivalent.
- [Bailey et al., backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) motivates caution about selecting attractive backtest results. This model does not calculate that paper's PBO statistic.
