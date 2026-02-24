from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .units import kg_per_mass_unit, MJ_PER_MMBTU


@dataclass
class ProcessOutputs:
    wet_tons_per_day: float  # tonnes when SI, short tons when US
    dry_tons_per_day: float
    dried_mass_tons_per_day: float
    ash_tons_per_day: float
    char_tons_per_day: float
    water_removed_tons_per_day: float
    drying_thermal_mmbtu_per_day: float
    electrical_kwh_per_day: float
    methane_nm3_per_day: float
    methane_mmbtu_per_day: float
    gross_energy_mmbtu_per_day: float
    net_energy_mmbtu_per_day: float
    utilization_fraction: float


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def run_process_model(config: Dict[str, Any], overrides: Dict[str, float] | None = None) -> ProcessOutputs:
    overrides = overrides or {}
    feed = config["feedstock"]
    process = config["process"]

    wet_tpd = float(overrides.get("wet_tons_per_day", feed["wet_tons_per_day"]))
    moisture = _clamp(float(overrides.get("moisture_fraction", feed["moisture_fraction"])), 0.0, 0.98)
    drying_target = _clamp(
        float(overrides.get("drying_target_moisture_fraction", process["drying_target_moisture_fraction"])),
        0.05,
        0.70,
    )
    gas_eff = _clamp(float(overrides.get("gasification_efficiency_fraction", process["gasification_efficiency_fraction"])), 0.1, 0.95)
    meth_eff = _clamp(
        float(overrides.get("syngas_to_methane_efficiency_fraction", process["syngas_to_methane_efficiency_fraction"])),
        0.1,
        0.95,
    )
    parasitic = _clamp(float(overrides.get("parasitic_load_fraction", process["parasitic_load_fraction"])), 0.0, 0.5)
    utilization = _clamp(float(overrides.get("utilization_fraction", 1.0)), 0.1, 1.0)

    dry_tpd = wet_tpd * (1.0 - moisture) * utilization
    dried_mass_tpd = dry_tpd / (1.0 - drying_target)
    kg_per_mass = kg_per_mass_unit(config)
    dry_kg_per_day = dry_tpd * kg_per_mass
    ash_tpd = dry_tpd * float(feed.get("ash_fraction_dry", 0.25))

    hhv_mj_per_kg = float(feed["hhv_mj_per_kg_dry"])
    methane_lhv_mj_per_nm3 = float(process["methane_lhv_mj_per_nm3"])
    char_yield = _clamp(float(process.get("char_yield_fraction_of_dry_feed", 0.10)), 0.0, 0.40)
    char_tpd = dry_tpd * char_yield

    initial_water_tpd = wet_tpd * moisture * utilization
    final_water_tpd = dried_mass_tpd - dry_tpd
    water_removed_tpd = max(initial_water_tpd - final_water_tpd, 0.0)
    latent_heat = float(process.get("latent_heat_mj_per_kg_water_removed", 2.6))
    dryer_eff = _clamp(float(process.get("dryer_efficiency_fraction", 0.70)), 0.1, 1.0)
    drying_mj_per_day = water_removed_tpd * kg_per_mass * latent_heat / dryer_eff
    drying_mmbtu_per_day = drying_mj_per_day / MJ_PER_MMBTU

    gross_mj_per_day = dry_kg_per_day * hhv_mj_per_kg * gas_eff * meth_eff
    methane_nm3_per_day = gross_mj_per_day / methane_lhv_mj_per_nm3
    gross_mmbtu_per_day = gross_mj_per_day / MJ_PER_MMBTU
    net_mmbtu_per_day = gross_mmbtu_per_day * (1.0 - parasitic)
    gasification_kwh = dry_tpd * float(process.get("gasification_power_kwh_per_dry_ton", 120.0))
    methanation_kwh = net_mmbtu_per_day * float(process.get("methanation_power_kwh_per_mmbtu_methane", 18.0))
    electrical_kwh_per_day = gasification_kwh + methanation_kwh

    return ProcessOutputs(
        wet_tons_per_day=wet_tpd,
        dry_tons_per_day=dry_tpd,
        dried_mass_tons_per_day=dried_mass_tpd,
        ash_tons_per_day=ash_tpd,
        char_tons_per_day=char_tpd,
        water_removed_tons_per_day=water_removed_tpd,
        drying_thermal_mmbtu_per_day=drying_mmbtu_per_day,
        electrical_kwh_per_day=electrical_kwh_per_day,
        methane_nm3_per_day=methane_nm3_per_day,
        methane_mmbtu_per_day=net_mmbtu_per_day,
        gross_energy_mmbtu_per_day=gross_mmbtu_per_day,
        net_energy_mmbtu_per_day=net_mmbtu_per_day,
        utilization_fraction=utilization,
    )

