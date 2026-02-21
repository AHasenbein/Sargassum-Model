from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _get(container: Dict[str, Any], path: str, default: float) -> float:
    node: Any = container
    for key in path.split("."):
        if not isinstance(node, dict):
            return float(default)
        node = node.get(key)
    try:
        return float(node)
    except (TypeError, ValueError):
        return float(default)


def _set(container: Dict[str, Any], path: str, value: float) -> None:
    keys = path.split(".")
    node: Dict[str, Any] = container
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value


def validate_and_normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(config)
    constraints = [
        ("feedstock.wet_tons_per_day", 0.1, 1000.0, 10.0),
        ("feedstock.moisture_fraction", 0.0, 0.98, 0.8),
        ("feedstock.delivered_cost_usd_per_wet_ton", 0.0, 2000.0, 0.0),
        ("process.gasification_efficiency_fraction", 0.1, 0.95, 0.65),
        ("process.syngas_to_methane_efficiency_fraction", 0.1, 0.95, 0.60),
        ("process.parasitic_load_fraction", 0.0, 0.6, 0.15),
        ("existing_facility.transport_distance_km", 0.0, 2000.0, 30.0),
        ("existing_facility.transport_cost_usd_per_ton_km", 0.0, 10.0, 0.25),
        ("existing_facility.tolling_fee_usd_per_wet_ton", 0.0, 1000.0, 45.0),
        ("market.fallback_natural_gas_price_usd_per_mmbtu", 0.0, 100.0, 6.5),
        ("utilities.electricity_price_usd_per_kwh", 0.0, 5.0, 0.11),
        ("operations.labor_usd_per_day", 0.0, 200000.0, 0.0),
        ("policy.corporate_income_tax_rate_fraction", 0.0, 0.6, 0.0),
        ("policy.tax_cut_fraction", 0.0, 1.0, 0.0),
    ]
    for path, low, high, default in constraints:
        _set(cfg, path, _clamp(_get(cfg, path, default), low, high))

    mode = str(cfg.get("project", {}).get("run_mode", "existing_facility"))
    if mode not in {"auto_compare", "onsite_energy", "existing_facility"}:
        cfg.setdefault("project", {})["run_mode"] = "existing_facility"

    return cfg

