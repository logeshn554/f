# Ethereum Paper-Trading Research & Validation Protocol

## Project Framing
**Ethereum Paper-Trading Research & Validation Engine** — Research and validate Ethereum paper-trading algorithms targeting at least 90% winning closed trades and positive net returns after realistic trading costs. All evaluation must be chronological and out-of-sample, uncertainty must be reported explicitly, failed hypotheses must remain visible, and no real-money order execution is permitted.

## Strict Research Rules & Boundary Constraints
1. **Key-Free / No Live Order Execution**: No API keys, secret keys, or order execution methods are permitted. Live order execution endpoints (e.g. `POST /v2/orders`) are permanently rejected by the safety architecture.
2. **Chronological Causality & Embargo**:
   - All evaluation uses anchored walk-forward out-of-sample (OOS) cross-validation (5 folds).
   - Training/development observations strictly precede out-of-sample testing observations.
   - An embargo buffer of at least 10 bars (or max trade horizon) separates training and testing periods to eliminate boundary leakage.
3. **Frozen Experiment Manifests**:
   - Every experiment is defined by an immutable JSON manifest specifying strategy parameters, data paths, cost models, and source code hashes.
   - Modifying any parameter or code creates a new experiment manifest; earlier experiment logs are preserved in `experiments/results/`.
4. **Realistic Exchange Cost Model & 2× Stress Testing**:
   - Taker commissions (e.g. 5–10 bps) + 18% GST tax treatment.
   - Half-spread and adverse slippage per side (e.g. 2 bps).
   - Continuous funding reserve debits (e.g. 3 bps / 8h).
   - Tick size quantization and integer contract constraints.
   - Mandatory **2× cost stress test** (doubled fees, spread, slippage, and funding).
5. **Uncertainty Quantification**:
   - Dual confidence interval calculation: **Wilson 95% Score Interval** and **Block-Bootstrap 95% Confidence Interval** (to account for trade auto-correlation).
6. **Target Gate Criteria**:
   To establish `TARGET_SUPPORTED`, a strategy MUST satisfy ALL of the following:
   - `closed_trades >= 100` (Minimum 100 out-of-sample closed trades)
   - `observed_win_rate >= 90.0%`
   - `confidence_interval_lower >= 90.0%` (95% Wilson CI lower bound ≥ 90%)
   - `net_return > 0.0%`
   - `stressed_net_return > 0.0%` (2× cost stress test)
   - `no_data_leakage` & `strategy_was_frozen_before_oos`

   If ANY requirement fails, the engine strictly outputs:
   ```json
   "status": "TARGET_NOT_ESTABLISHED"
   ```

## Repository Architecture

```text
f/
├── data/
│   └── immutable/
├── experiments/
│   ├── manifests/
│   └── results/
├── strategies/
│   ├── candle_paths.py
│   ├── eth_guard.py
│   └── baselines.py
├── research/
│   ├── chronological_split.py
│   ├── walk_forward.py
│   ├── cost_model.py
│   ├── uncertainty.py
│   ├── metrics.py
│   └── validation.py
├── paper/
│   ├── broker.py
│   ├── market_data.py
│   └── forward_evidence.py
├── tests/
│   ├── test_no_future_leakage.py
│   ├── test_realistic_costs.py
│   ├── test_no_live_orders.py
│   ├── test_walk_forward.py
│   ├── test_uncertainty.py
│   └── test_target_gate.py
├── reports/
│   └── validation_report.json
├── RESEARCH_PROTOCOL.md
└── README.md
```
