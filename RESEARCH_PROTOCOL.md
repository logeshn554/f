# Research Protocol

## Canonical project goal

> Research and validate an Ethereum paper-trading algorithm targeting at least 90% winning trades and positive net returns after realistic costs, using chronological out-of-sample evaluation and reporting uncertainty honestly. Do not claim the target is achieved without evidence or enable real-money trading.

This sentence is the binding contract for every decision in this codebase. Any feature, result, or claim that conflicts with it must be removed or corrected.

---

## What the protocol requires

### 1. Chronological out-of-sample evaluation only

- All performance measurement uses **anchored walk-forward cross-validation** (5 folds, 10-bar embargo).
- Training observations are strictly prior to the first test bar.
- The signal for bar `i` is generated from `candles[:i]` — the current bar's open/high/low/close are **never visible** to the strategy at signal time.
- In-sample or fitted win rates (e.g. optimised on development data) are **never reported as evidence** for the target.

### 2. Honest uncertainty reporting

- Every result must include a **Wilson 95% confidence interval** and a **block-bootstrap 95% CI**.
- The bootstrap CI is required because crypto trades can be temporally dependent; the Wilson CI alone is insufficient.
- Results with fewer than 100 OOS closed trades **cannot establish the target** regardless of observed win rate.
- A wide confidence interval (e.g. [9.7%, 70.0%]) must be reported prominently, not hidden.

### 3. Realistic costs

- Delta Exchange taker fee: 0.05% (5 bps).
- 18% GST applied to exchange fees.
- Half bid-ask spread: 2 bps per side.
- Adverse slippage: 2 bps per side.
- Continuous funding reserve debit: 3 bps / 8 h (applied to both long and short).
- Tick-size quantisation: 0.01 USD.
- Integer lot sizing: 1 lot = 0.01 ETH (Delta ETHUSD standard).
- **2× cost stress test** required: double all variable costs; result must still be positive.

### 4. Paper-only operation

- No API keys, secret keys, or private keys are permitted anywhere in the codebase.
- `POST /v2/orders` and equivalent authenticated endpoints are rejected at the transport layer.
- `PaperBroker.execute_live_order()` raises `OrderExecutionProhibitedError` unconditionally.
- The `mode` field in every output is `"LOCAL PAPER ONLY"`.
- Converting paper results to live trading is explicitly prohibited by this protocol.

### 5. Frozen experiments

- Every experiment is defined by an immutable manifest JSON in `experiments/manifests/`.
- The manifest stores `source_hash` (SHA-256 of strategy `.py` bytes + parameters) and `dataset_sha256`.
- Changing strategy logic or parameters without updating the manifest causes a hash mismatch → `TARGET_NOT_ESTABLISHED`.
- Result files are stored as `<experiment_id>_<manifest_hash>.json`; prior runs are never overwritten.

### 6. Visible failed hypotheses

- Failed experiments remain in `experiments/results/` permanently.
- The research process cannot silently discard bad results.
- `TARGET_NOT_ESTABLISHED` is the default and correct output until all gate criteria are met.

---

## Target gate (exact logic)

```python
target_supported = (
    closed_trades >= 100               # minimum sample
    and win_rate_pct >= 90.0           # observed rate
    and wilson_ci_lower >= 90.0        # standard CI lower bound
    and bootstrap_ci_lower >= 90.0     # dependency-aware CI lower bound
    and net_return > 0.0               # must be profitable
    and stressed_net_return > 0.0      # profitable at 2x costs
    and source_hash_matched            # code frozen before OOS
    and dataset_sha256_matched         # data immutable
)
```

If any condition fails the output is:

```
TARGET NOT ESTABLISHED
```

Not "close to target," not "high-confidence strategy," not "promising result."

---

## Prohibited outputs

The following phrases and claims are prohibited in any report, commit message, or comment:

- "90% win rate achieved"
- "target established" (without `target_supported = true` in the JSON)
- "profitable strategy" (based on fewer than 100 OOS trades)
- "high win rate" (based on in-sample or fitted data)
- "live trading ready"
- Any claim that paper results predict live performance
