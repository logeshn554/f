# Research target: 90% net winning trades

The user's target is at least 90% winning closed trades **and positive net account return**. It is a target, not a promised outcome. A trade counts as a win only after its entry/exit fees, modeled GST, spread, slippage and funding reserve. Open losses count in equity and drawdown; they cannot be hidden by reporting only closed winners.

## Evidence required before claiming success

- Freeze the strategy, parameters and source hash before evaluating new validation data. Data already examined is development data, including the saved 95-day candle snapshot.
- Report all tested variants. Do not repeatedly select on the same validation segment and call it untouched.
- Require at least 100 closed validation trades, observed net win rate at least 90%, positive net equity return, and positive return under doubled fee/slippage/funding assumptions. This is a minimum screening sample, not proof of a stable future success rate.
- Report win-rate uncertainty and dependence between trades. A Wilson interval assumes independent outcomes and cannot by itself establish 90% reliability for clustered crypto trades. Confirm across separate chronological periods and subsequent live paper observations.
- Preserve 0.5% planned risk per trade, the 1x notional cap, daily loss stop and total drawdown stop. No martingale, loss averaging, forced fills, or oversized stops to manufacture a high win percentage.
- No claim of production profitability from unit tests, synthetic trends, fitted neighbor win percentages, zero trades, or forecast-band containment.

## First diagnostic experiment

`diagnose_target.py` compares three predeclared entry rules over the existing historical snapshot:

1. Current Candle Paths v4 gates.
2. Positive sample mean after costs, omitting the uncertainty/tail entry penalty; other entry gates and dynamic exits remain unchanged.
3. Current gates plus a minimum 90% weighted historical sample win fraction.

Each uses the same chronological 70/30 split and execution simulator. This is an ablation to explain inactivity, not independent validation of profitability. Output: `target_research/diagnostic.json`. It cannot change the live ledger or deployed model.

## Next research decision

The first diagnostic evaluated 8,521 completed-candle decisions (June 28–September 25, 2026). The baseline made five development trades, winning two and returning -0.44%; it made no later-segment trades. Removing the entry uncertainty penalty produced 31 later-segment trades, four wins (12.90%), and -4.90% return before the drawdown halt stopped entries. The 90% sample-win filter produced no trades. None of these variants achieved the target. These are results on reused data, not prospective evidence.

If the mean-edge variant also fails, simply weakening the penalty is not supported. Investigate whether the input features predict the next path at all, using prospective forecasts and explicit calibration tests, before attempting more complex entry rules. Any new hypothesis must be frozen and separately tested. A failed hypothesis should be reported rather than tuned until the historical result reaches 90%.

Reference: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf). Repeated historical selection can give misleading performance; this project does not implement the paper's PBO estimator.

## Second experiment: hourly candle states

`research_states.py` fixes eight candle states (six-hour direction, body direction and wick imbalance), four direction/range-barrier combinations, and three probability entry thresholds before downloading a disjoint year of history. Local outcome estimates shrink toward the historical global rate. Only fully matured, separated eight-hour labels enter training. The source hash and timestamp are stored in `state_research/preregistration.json`.

The dataset contains 8,760 hourly candles from June 20, 2025 through June 19, 2026. The final chronological quarter (March 20–June 19, 2026) is the first-pass historical test. Online updates within that quarter use only outcomes that have already matured. This is a separate historical cohort, not a prospective forward test.

Results in `state_research/report.json`:

- 6,199 supported forecasts; none had a positive uncertainty-penalized net edge.
- Maximum fitted win estimate 58.06%; this is a model output, not an observed trade win rate.
- On 272 separated test forecasts, Brier score was 0.24437 versus 0.24040 for a past-only global-rate reference. Lower is better; this model did not improve that probability forecast metric.
- All three entry variants and their doubled-cost replays made zero trades. Neither profitability nor the 90% target was established.
- Four new causality/cost/sparse-support tests pass; the full suite has 38 passing tests. Tests verify implementation behavior, not profitability.

Decision: reject this hourly state hypothesis for deployment. Do not tune its bins or thresholds on this test quarter and continue calling it untouched. The original live paper model and account were not modified by this experiment. Candle-only features tested so far have not demonstrated the required predictive edge; further progress requires a new justified hypothesis and fresh validation evidence.

Hourly history is obtained from the public [Delta historical candle API](https://docs.delta.exchange/), with complete coverage and OHLC checks. Current product fees are applied to historical execution; actual historical funding, depth and exchange outages remain unmodeled.

## Prospective evidence collection

The running service now stores each timely Candle Paths forecast in SQLite before its two-hour outcome exists. A record must arrive within 120 seconds after the origin candle closes, with a fresh quote. Late startup does not backfill forecasts. A composite source hash identifies the exact model/accounting code; the first record for each hash and candle cannot be overwritten through the recorder. This is a local audit journal, not tamper-proof external attestation.

`forward_forecasts` preserves the full signal and quote. `forward_outcomes` records the eventual closed candle and whether it falls inside the saved forecast band, only after the outcome candle closes. These are forecast checks, **not profitable trades**. Overlapping two-hour forecasts are dependent; any later evaluation must account for that. Trade profitability still comes exclusively from the paper trade ledger.

The service was restarted flat with $100 retained. All 42 tests and 19 live integration checks passed. At the initial verification (September 25, 2026, 15:32 UTC), the recording window for the current candle had already passed.

The first prospective record was captured on September 25, 2026 at 15:45:04 UTC under model hash `8e42ddfcd99a572de684bc86ec8913353868f3340e41885ea0f670513fc5cd43`. It used the completed 15:30 UTC candle as its origin, saved a WAIT signal with eight forecast fan points, and targets a horizon close of 17:45 UTC. No outcome existed at recording time, and no outcome row was present when checked immediately afterward. This collection period cannot be accelerated by replaying historical data. The goal remains unachieved pending genuine new evidence and a demonstrably successful hypothesis.
