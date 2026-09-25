"""
Canonical Research & Validation Engine CLI.
Single entry authority for strategy evaluation and target gating.

Result files are stored by experiment_id + manifest_sha256[:8] so previous
runs are never overwritten (protocol requirement: failed hypotheses must remain
visible).
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from paper.market_data import load_csv_candles
from research.cost_model import CostModel
from research.validation import validate_strategy_manifest, sha256_file
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


def manifest_content_hash(manifest: dict) -> str:
    """Return first 8 hex chars of SHA-256 over the canonical JSON of the manifest."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def run_experiment(manifest_path: Path, dataset_override: Path = None) -> dict:
    """
    Run validation for a single experiment manifest.

    Result is written to experiments/results/<experiment_id>_<manifest_hash>.json
    so earlier runs are preserved even if the manifest changes.
    """
    manifest = load_manifest(manifest_path)
    strategy_name = manifest["strategy_name"]

    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{strategy_name}' in manifest")

    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    params = manifest.get("parameters", {})
    strategy = strategy_cls(**params)

    # Dataset path (CLI override disables the SHA-256 frozen-dataset check with a warning)
    data_path = dataset_override or Path(manifest.get("dataset", "data/immutable/eth_daily.csv"))
    if dataset_override and dataset_override != Path(manifest.get("dataset", "")):
        print(
            f"[WARNING] --dataset override active: SHA-256 dataset integrity check will "
            f"likely fail.  This run should not be treated as a frozen experiment."
        )

    candles = load_csv_candles(data_path, min_candles=100)

    cost_cfg = manifest.get("cost_model", {})
    cost_model = CostModel(
        taker_fee_rate=cost_cfg.get("taker_fee_rate", 0.0005),
        gst_rate=cost_cfg.get("gst_rate", 0.18),
        slippage_rate=cost_cfg.get("slippage_rate", 0.0002),
        spread_rate=cost_cfg.get("spread_rate", 0.0002),
        funding_reserve_per_8h=cost_cfg.get("funding_reserve_per_8h", 0.0003),
        tick_size=cost_cfg.get("tick_size", 0.01),
        contract_unit=cost_cfg.get("contract_unit", 0.01),
        max_notional=cost_cfg.get("max_notional", 1.0),
    )

    report = validate_strategy_manifest(
        strategy=strategy,
        candles=candles,
        manifest=manifest,
        cost_model=cost_model,
        dataset_path=str(data_path),
    )
    exp_id = manifest.get("experiment_id", manifest_path.stem)
    report["experiment_id"] = exp_id
    report["manifest_path"] = str(manifest_path)

    # ── Immutable result storage (content-addressed by manifest hash) ─────────
    mhash = manifest_content_hash(manifest)
    res_dir = Path("experiments/results")
    res_dir.mkdir(parents=True, exist_ok=True)
    res_path = res_dir / f"{exp_id}_{mhash}.json"
    res_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  -> Saved result: {res_path}")

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
        help="Override dataset path (disables SHA-256 frozen-data check — use only for dev)",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/validation_report.json"),
        help="Path for the primary machine-readable report",
    )
    parser.add_argument(
        "--stamp-manifest",
        action="store_true",
        help=(
            "Compute and print source_hash + dataset_sha256 for each manifest, "
            "then write them back. Use once before freezing an experiment."
        ),
    )
    args = parser.parse_args()

    # ── Stamp mode: compute and write hashes into manifests ──────────────────
    if args.stamp_manifest:
        manifest_files = (
            sorted(Path("experiments/manifests").glob("*.json"))
            if args.all_manifests
            else [args.manifest]
        )
        for mf in manifest_files:
            manifest = load_manifest(mf)
            strategy_name = manifest.get("strategy_name", "")
            if strategy_name not in STRATEGY_REGISTRY:
                print(f"[SKIP] Unknown strategy in {mf.name}: {strategy_name}")
                continue
            params = manifest.get("parameters", {})
            strategy = STRATEGY_REGISTRY[strategy_name](**params)
            src_hash = strategy.get_source_hash()

            data_path = args.dataset or Path(manifest.get("dataset", "data/immutable/eth_daily.csv"))
            ds_sha = sha256_file(str(data_path)) if data_path.exists() else None

            manifest["source_hash"] = src_hash
            if ds_sha:
                manifest["dataset_sha256"] = ds_sha
            mf.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"[STAMPED] {mf.name}: source_hash={src_hash}, dataset_sha256={ds_sha}")
        return

    # ── Normal run mode ───────────────────────────────────────────────────────
    results = []
    if args.all_manifests:
        manifest_files = sorted(Path("experiments/manifests").glob("*.json"))
        if not manifest_files:
            print("No manifests found in experiments/manifests/")
            sys.exit(1)
        for mf in manifest_files:
            print(f"\nRunning experiment: {mf.name}...")
            rep = run_experiment(mf, dataset_override=args.dataset)
            results.append(rep)
    else:
        print(f"\nRunning experiment: {args.manifest.name}...")
        rep = run_experiment(args.manifest, dataset_override=args.dataset)
        results.append(rep)

    primary_report = results[0]
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(primary_report, indent=2), encoding="utf-8")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("VALIDATION ENGINE SUMMARY RESULT")
    print("=" * 65)
    for rep in results:
        oos = rep["oos"]
        print(f"\nExperiment:           {rep['experiment_id']}")
        print(f"Status:               {rep['status']}")
        print(f"Target Supported:     {rep['target_supported']}")
        print(f"OOS Closed Trades:    {oos['closed_trades']}  (Required: >= 100)")
        print(f"OOS Win Rate:         {oos['win_rate_pct']}%")
        print(f"OOS Wilson 95% CI:    {oos['win_rate_95_ci']}")
        print(f"OOS Bootstrap 95% CI: {oos['block_bootstrap_95_ci']}")
        print(f"OOS Net Return:       {oos['net_return_pct']}%")
        print(f"2x Cost Stress:       {rep['cost_stress_2x']['net_return_pct']}%")
        di = rep.get("dataset_integrity", {})
        print(f"Dataset SHA matched:  {di.get('matched')}  {di.get('note','')}")
        st = rep.get("strategy", {})
        print(f"Source hash matched:  {st.get('source_hash_matched')}  {st.get('note','')}")
    print(f"\nPrimary report:       {args.report_output.resolve()}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
