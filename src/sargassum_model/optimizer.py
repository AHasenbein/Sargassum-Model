from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.optimize import differential_evolution

from .modes import run_single_mode


@dataclass
class OptimizationResult:
    mode: str
    best_profit_usd_per_day: float
    best_variables: Dict[str, float]
    success: bool
    message: str


def _objective_factory(
    base_config: Dict[str, Any],
    mode: str,
    methane_price_usd_per_mmbtu: float,
    variable_names: List[str],
) -> Any:
    def objective(x: np.ndarray) -> float:
        overrides = {name: float(val) for name, val in zip(variable_names, x)}
        result = run_single_mode(base_config, mode, methane_price_usd_per_mmbtu, overrides=overrides)
        profit = float(result["economics"]["profit_usd_per_day"])
        return -profit

    return objective


def optimize_mode(
    config: Dict[str, Any],
    mode: str,
    methane_price_usd_per_mmbtu: float,
) -> OptimizationResult:
    opt_cfg = config["optimization"]
    bounds_cfg: Dict[str, List[float]] = opt_cfg["variable_bounds"]
    variable_names = list(bounds_cfg.keys())
    bounds: List[Tuple[float, float]] = [tuple(bounds_cfg[k]) for k in variable_names]

    objective = _objective_factory(config, mode, methane_price_usd_per_mmbtu, variable_names)
    result = differential_evolution(
        objective,
        bounds=bounds,
        maxiter=int(opt_cfg.get("max_iter", 60)),
        polish=bool(opt_cfg.get("polishing", True)),
        seed=42,
    )
    best_vars = {name: float(v) for name, v in zip(variable_names, result.x)}
    best_profit = -float(result.fun)
    return OptimizationResult(
        mode=mode,
        best_profit_usd_per_day=best_profit,
        best_variables=best_vars,
        success=bool(result.success),
        message=str(result.message),
    )


def run_sensitivity(
    config: Dict[str, Any],
    mode: str,
    methane_price_usd_per_mmbtu: float,
    delta_fraction: float = 0.15,
) -> List[Dict[str, float | str]]:
    variables = config["analysis"]["sensitivity_variables"]
    baseline = run_single_mode(config, mode, methane_price_usd_per_mmbtu)
    base_profit = float(baseline["economics"]["profit_usd_per_day"])
    outputs: List[Dict[str, float | str]] = []

    for var in variables:
        low_cfg = deepcopy(config)
        high_cfg = deepcopy(config)

        if var == "methane_price_usd_per_mmbtu":
            low_price = methane_price_usd_per_mmbtu * (1.0 - delta_fraction)
            high_price = methane_price_usd_per_mmbtu * (1.0 + delta_fraction)
            low_profit = float(run_single_mode(low_cfg, mode, low_price)["economics"]["profit_usd_per_day"])
            high_profit = float(run_single_mode(high_cfg, mode, high_price)["economics"]["profit_usd_per_day"])
        else:
            target_groups = ["feedstock", "process", "existing_facility", "market", "policy", "onsite_energy", "economics"]
            key_found = False
            for group in target_groups:
                if var in low_cfg.get(group, {}):
                    base_val = float(low_cfg[group][var])
                    low_cfg[group][var] = base_val * (1.0 - delta_fraction)
                    high_cfg[group][var] = base_val * (1.0 + delta_fraction)
                    key_found = True
                    break
            if not key_found:
                continue
            low_profit = float(run_single_mode(low_cfg, mode, methane_price_usd_per_mmbtu)["economics"]["profit_usd_per_day"])
            high_profit = float(run_single_mode(high_cfg, mode, methane_price_usd_per_mmbtu)["economics"]["profit_usd_per_day"])

        outputs.append(
            {
                "variable": var,
                "baseline_profit_usd_per_day": base_profit,
                "low_profit_usd_per_day": low_profit,
                "high_profit_usd_per_day": high_profit,
                "swing_usd_per_day": high_profit - low_profit,
            }
        )
    outputs.sort(key=lambda x: abs(float(x["swing_usd_per_day"])), reverse=True)
    return outputs

