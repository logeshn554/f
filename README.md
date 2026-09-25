# Ethereum Paper-Trading Research & Validation Engine

**Goal:** Research and validate an Ethereum paper-trading algorithm targeting at least 90% winning trades and positive net returns after realistic costs, using chronological out-of-sample evaluation and reporting uncertainty honestly. Do not claim the target is achieved without evidence or enable real-money trading.

---

> [!IMPORTANT]
> **Current status: TARGET NOT ESTABLISHED**
> The latest measured result (Candle Paths, corrected for look-ahead):
> OOS trades: 6 | Win rate: 33.33% | Net return: +0.72% | 2× cost: +0.47%
> The 90% win-rate target is not supported by the current evidence.

---

## Design principles

| Principle | Implementation |
|---|---|
| Chronological OOS | Anchored 5-fold walk-forward, 10-bar embargo |
| Uncertainty honest | Wilson 95% CI **and** block-bootstrap 95% CI both required |
| Costs realistic | Delta taker fee + 18% GST + spread + slippage + funding debit |
| 2× stress test | All variable costs doubled; must still be profitable |
| No look-ahead | Signal uses `candles[:absolute_index]`; execution at next open |
| Code frozen | Real SHA-256 of `.py` bytes + params in every manifest |
| Data frozen | Dataset SHA-256 checked before every run |
| Results preserved | Content-addressed filenames; prior runs never overwritten |
| Paper-only | No API keys, no POST order routes, `execute_live_order()` raises |
| 100-trade minimum | Fewer than 100 OOS closed trades → `TARGET_NOT_ESTABLISHED` |

---

## Repository layout

```text
f/
├── data/immutable/              # Frozen candle datasets
├── experiments/
│   ├── manifests/               # One JSON per frozen experiment
│   └── results/                 # Content-addressed, append-only
├── strategies/
│   ├── candle_paths.py
│   ├── eth_guard.py
│   └── baselines.py
├── research/
│   ├── chronological_split.py   # Anchored folds + embargo
│   ├── walk_forward.py          # Causality-correct OOS engine
│   ├── cost_model.py            # Fee/GST/slippage/funding + 2× stress
│   ├── uncertainty.py           # Wilson + block-bootstrap CI
│   ├── metrics.py               # Full performance metrics
│   └── validation.py            # Canonical TARGET gate (single authority)
├── paper/
│   ├── broker.py                # Integer-lot paper broker, key-free
│   ├── market_data.py
│   └── forward_evidence.py
├── tests/                       # 16 tests, all passing
├── reports/validation_report.json
├── RESEARCH_PROTOCOL.md
└── README.md
```

---

## Quick start

```powershell
# Freeze source + data hashes into manifests before the first run
python research_validation.py --all-manifests --stamp-manifest

# Run all experiments
python research_validation.py --all-manifests

# Run tests
python -m unittest discover -s tests
```

---

## Output schema

Every run writes `reports/validation_report.json`:

```json
{
  "status": "TARGET_NOT_ESTABLISHED",
  "target_win_rate_pct": 90,
  "research_only": true,
  "real_money_execution": false,
  "oos": {
    "closed_trades": 6,
    "win_rate_pct": 33.3333,
    "win_rate_95_ci": [9.6772, 70.0006],
    "block_bootstrap_95_ci": [33.3333, 33.3333],
    "net_return_pct": 0.7169
  },
  "cost_stress_2x": { "net_return_pct": 0.47 },
  "target_supported": false
}
```

`"target_supported": true` is only possible when **all** of the following hold simultaneously:

```python
target_supported = (
    closed_trades >= 100
    and win_rate_pct >= 90.0
    and wilson_ci_lower >= 90.0        # standard CI
    and bootstrap_ci_lower >= 90.0     # dependency-aware CI
    and net_return > 0.0
    and stressed_net_return > 0.0      # 2× costs
    and source_hash_matched            # code was frozen
    and dataset_sha256_matched         # data was immutable
)
```
