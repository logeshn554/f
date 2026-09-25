"""
Canonical Research & Validation Engine CLI.
Single entry authority for strategy evaluation and target gating.
"""
import argparse
import json
from pathlib import Path
import sys

from paper.market_data import load_csv_candles
from research.cost_model import CostModel
from research.validation import validate_strategy_manifest
from strategies.baselines import BuyAndHoldStrategy, MovingAverageCrossoverStrategy
from strategies.candle_paths import CandlePathsStrategy
from strategies.eth_guard import ETHGuardStrategy


STRATEGY_REGISTRY = {
    "candle_paths": CandlePathsStrategy,
    "eth_guard": ETHGuardStrategy,
    "ma_crossover": MovingAverageCrossoverStrategy,
    "buy_and_hold": BuyAndHoldStrategy,
}


def load_manifest(manifest_path: Path) -> dict:
    """Load experiment manifest from JSON."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def run_experiment(manifest_path: Path, dataset_override: Path = None) -> dict:
    """Run validation for a single experiment manifest."""
    manifest = load_manifest(manifest_path)
    strategy_name = manifest["strategy_name"]

    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{strategy_name}' in manifest")

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    params = manifest.get("parameters", {})
    strategy = strategy_cls(**params)

    data_path = dataset_override or Path(manifest.get("dataset", "data/immutable/eth_daily.csv"))
    candles = load_csv_candles(data_path, min_candles=100)

    cost_cfg = manifest.get("cost_model", {})
    cost_model = CostModel(
        taker_fee_rate=cost_cfg.get("taker_fee_rate", 0.0005),
        gst_rate=cost_cfg.get("gst_rate", 0.18),
        slippage_rate=cost_cfg.get("slippage_rate", 0.0002),
        spread_rate=cost_cfg.get("spread_rate", 0.0002),
        funding_reserve_per_8h=cost_cfg.get("funding_reserve_per_8h", 0.0003),
        tick_size=cost_cfg.get("tick_size", 0.01),
    )

    report = validate_strategy_manifest(
        strategy=strategy,
        candles=candles,
        manifest=manifest,
        cost_model=cost_model,
    )
    report["experiment_id"] = manifest.get("experiment_id", manifest_path.stem)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Ethereum Paper-Trading Research & Validation Engine"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/manifests/exp_001_candle_paths.json"),
        help="Path to experiment manifest JSON",
    )
    parser.add_argument(
        "--all-manifests",
        action="store_true",
        help="Run all manifests in experiments/manifests/",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Override dataset path (CSV)",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/validation_report.json"),
        help="Path to output machine-readable validation report",
    )
    args = parser.parse_args()

    results = []

    if args.all_manifests:
        manifest_files = list(Path("experiments/manifests").glob("*.json"))
        if not manifest_files:
            print("No manifests found in experiments/manifests/")
            sys.exit(1)
        for mf in sorted(manifest_files):
            print(f"Running experiment: {mf.name}...")
            rep = run_experiment(mf, dataset_override=args.dataset)
            results.append(rep)
            # Save individual result in experiments/results/
            res_path = Path("experiments/results") / f"{mf.stem}_result.json"
            res_path.parent.mkdir(parents=True, exist_ok=True)
            res_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    else:
        print(f"Running experiment: {args.manifest.name}...")
        rep = run_experiment(args.manifest, dataset_override=args.dataset)
        results.append(rep)
        res_path = Path("experiments/results") / f"{args.manifest.stem}_result.json"
        res_path.parent.mkdir(parents=True, exist_ok=True)
        res_path.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    # Select primary report for reports/validation_report.json
    primary_report = results[0]
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(primary_report, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("VALIDATION ENGINE SUMMARY RESULT")
    print("=" * 60)
    print(f"Status:               {primary_report['status']}")
    print(f"Target Supported:     {primary_report['target_supported']}")
    print(f"OOS Closed Trades:    {primary_report['oos']['closed_trades']} (Required: >= 100)")
    print(f"OOS Win Rate:         {primary_report['oos']['win_rate_pct']}%")
    print(f"OOS Win Rate 95% CI:  {primary_report['oos']['win_rate_95_ci']}")
    print(f"OOS Net Return:       {primary_report['oos']['net_return_pct']}%")
    print(f"2x Cost Stress Net:   {primary_report['cost_stress_2x']['net_return_pct']}%")
    print(f"Report saved to:      {args.report_output.resolve()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
