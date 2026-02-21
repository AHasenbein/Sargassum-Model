from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from .config import load_config
from .data_sources import pull_miami_data
from .modes import run_mode_bundle
from .optimizer import optimize_mode, run_sensitivity
from .validation import validate_and_normalize_config


def run_pipeline(config_path: str, output_dir: str) -> Dict[str, Any]:
    config = validate_and_normalize_config(load_config(config_path))
    conversion_path = str(config.get("project", {}).get("conversion_path", "gasification_methanation"))
    if conversion_path != "gasification_methanation":
        raise ValueError(
            "This model is configured for gasification_methanation only. "
            "Set project.conversion_path to gasification_methanation."
        )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = pull_miami_data(config, raw_data_dir="data/raw")
    methane_price = float(bundle.methane_price_usd_per_mmbtu)

    baseline_results = run_mode_bundle(config, methane_price_usd_per_mmbtu=methane_price)

    optimization_rows = []
    if bool(config["optimization"]["enable"]):
        modes = [r["mode"] for r in baseline_results]
        for mode in modes:
            optimization_rows.append(asdict(optimize_mode(config, mode, methane_price)))

    sensitivity_rows = []
    if bool(config["analysis"]["enable_sensitivity"]):
        best_mode = baseline_results[0]["mode"]
        sensitivity_rows = run_sensitivity(config, mode=best_mode, methane_price_usd_per_mmbtu=methane_price)

    payload = {
        "miami_data": bundle.__dict__,
        "baseline_results": baseline_results,
        "optimization_results": optimization_rows,
        "sensitivity_results": sensitivity_rows,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sargassum-to-methane model")
    parser.add_argument("--config", default="config/model_config.yaml", help="Path to model config YAML")
    parser.add_argument("--out", default="outputs", help="Output directory")
    args = parser.parse_args()

    payload = run_pipeline(args.config, args.out)
    best = payload["baseline_results"][0]
    print(f"Best baseline mode: {best['mode']}")
    print(f"Profit (USD/day): {best['economics']['profit_usd_per_day']:.2f}")
    print(f"Methane (MMBtu/day): {best['process']['methane_mmbtu_per_day']:.2f}")
    print("Saved JSON results to outputs/results.json")


if __name__ == "__main__":
    main()

