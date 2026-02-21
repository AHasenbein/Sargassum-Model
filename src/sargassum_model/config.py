from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml


def deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_update(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: Dict[str, Any], config_path: str | Path) -> None:
    path = Path(config_path)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def annualized_capex(capex_usd: float, discount_rate: float, lifetime_years: int) -> float:
    if lifetime_years <= 0:
        raise ValueError("lifetime_years must be > 0")
    if discount_rate <= 0:
        return capex_usd / lifetime_years
    r = discount_rate
    n = lifetime_years
    crf = r * (1 + r) ** n / ((1 + r) ** n - 1)
    return capex_usd * crf

