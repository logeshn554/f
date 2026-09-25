# Ethereum Paper-Trading Research & Validation Engine

**Ethereum Paper-Trading Research & Validation Engine** — Research and validate Ethereum paper-trading algorithms targeting at least 90% winning closed trades and positive net returns after realistic trading costs. All evaluation must be chronological and out-of-sample, uncertainty must be reported explicitly, failed hypotheses must remain visible, and no real-money order execution is permitted.

> [!IMPORTANT]
> **Current Status: TARGET NOT ESTABLISHED**
> Evaluated strategies currently yield fewer than 100 out-of-sample closed trades or fail the 90% lower confidence interval bound. The validation gate strictly outputs `TARGET_NOT_ESTABLISHED`.

---

## Core Features & Design Principles

1. **Canonical Entry Point**: `research_validation.py` acts as the single authority allowed to output `TARGET_SUPPORTED` or `TARGET_NOT_ESTABLISHED`.
2. **Anchored Walk-Forward Cross Validation**: 5 chronological out-of-sample folds with strict embargo periods preventing boundary data leakage.
3. **Realistic Exchange Cost Model & 2× Stress Testing**: Models Delta Exchange public fees, 18% GST tax, spread, adverse slippage, continuous funding debits, and integer contracts. Mandatory 2× friction stress test.
4. **Uncertainty Quantification**: Calculates both Wilson Score 95% Confidence Intervals and Block-Bootstrap 95% Confidence Intervals.
5. **Strict Safety Boundary**: Prohibits API keys, live credentials, or order POST endpoints. Standard library Python only.

---

## Project Structure

```text
f/
├── data/
│   └── immutable/               # Immutable historical candle datasets
├── experiments/
│   ├── manifests/               # Frozen experiment configuration manifests
│   └── results/                 # Machine-readable experiment outputs & failure logs
├── strategies/
│   ├── candle_paths.py          # Candle Geometry Path strategy
│   ├── eth_guard.py             # Trend + RSI + Volatility strategy
│   └── baselines.py             # Baseline benchmarks (MA crossover, Buy & Hold)
├── research/
│   ├── chronological_split.py   # Chronological fold generator with embargo
│   ├── walk_forward.py          # Anchored walk-forward CV engine
│   ├── cost_model.py            # Fee/GST/slippage/funding & 2x stress model
│   ├── uncertainty.py           # Wilson & Block-Bootstrap CIs
│   ├── metrics.py               # Comprehensive trade performance metrics
│   └── validation.py            # Canonical Target Gate decision authority
├── paper/
│   ├── broker.py                # Local key-free paper simulation broker
│   ├── market_data.py           # Candle validation and loaders
│   └── forward_evidence.py      # Prospective forward paper tracking
├── tests/                       # Unit test suite verifying leakage, costs, and safety
├── reports/
│   └── validation_report.json   # Machine-readable output report
├── RESEARCH_PROTOCOL.md         # Detailed research protocol documentation
└── README.md
```

---

## Quick Start

Run the validation engine across all experiment manifests:

```powershell
python research_validation.py --all-manifests
```

Run the unit test suite:

```powershell
python -m unittest discover -s tests
```

---

## Machine-Readable Validation Schema

Validation outputs follow this standard JSON format:

```json
{
  "status": "TARGET_NOT_ESTABLISHED",
  "target_win_rate_pct": 90,
  "research_only": true,
  "real_money_execution": false,
  "oos": {
    "closed_trades": 7,
    "wins": 6,
    "win_rate_pct": 85.7143,
    "win_rate_95_ci": [48.6873, 97.432],
    "net_return_pct": 2.5892,
    "profit_factor": 25.3272,
    "max_drawdown_pct": 0.1064
  },
  "cost_stress_2x": {
    "net_return_pct": 2.2784
  },
  "requirements": {
    "minimum_oos_trades": 100,
    "minimum_win_rate_pct": 90,
    "positive_net_return": true,
    "positive_2x_cost_return": true
  },
  "target_supported": false
}
```
