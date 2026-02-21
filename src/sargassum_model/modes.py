from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List

from .economics import evaluate_existing_facility, evaluate_onsite
from .process_model import run_process_model


def run_single_mode(
    config: Dict[str, Any],
    mode: str,
    methane_price_usd_per_mmbtu: float,
    overrides: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    process = run_process_model(config, overrides=overrides)
    if mode == "onsite_energy":
        economics = evaluate_onsite(process, config, methane_price_usd_per_mmbtu)
    elif mode == "existing_facility":
        economics = evaluate_existing_facility(process, config, methane_price_usd_per_mmbtu)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    return {
        "mode": mode,
        "process": asdict(process),
        "economics": economics.to_dict(),
    }


def run_mode_bundle(
    config: Dict[str, Any],
    methane_price_usd_per_mmbtu: float,
    overrides: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    mode = config["project"]["run_mode"]
    if mode == "auto_compare":
        modes = ["onsite_energy", "existing_facility"]
    else:
        modes = [mode]

    results = [run_single_mode(config, m, methane_price_usd_per_mmbtu, overrides=overrides) for m in modes]
    results.sort(key=lambda x: float(x["economics"]["profit_usd_per_day"]), reverse=True)
    return results

