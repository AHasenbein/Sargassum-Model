from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict

from .config import annualized_capex as compute_annualized_capex
from .units import kg_per_mass_unit


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class PyrolysisOutputs:
    wet_tons_per_day: float
    dry_tons_per_day: float
    biochar_tons_per_day: float
    biooil_tons_per_day: float
    syngas_mmbtu_per_day: float
    electrical_kwh_per_day: float
    drying_thermal_mmbtu_per_day: float
    water_removed_tons_per_day: float
    utilization_fraction: float


@dataclass
class PyrolysisEconomics:
    revenue_usd_per_day: float
    costs_usd_per_day: float
    pre_tax_profit_usd_per_day: float
    income_tax_usd_per_day: float
    profit_usd_per_day: float
    biochar_sales_usd_per_day: float
    biooil_sales_usd_per_day: float
    syngas_value_usd_per_day: float
    carbon_credits_usd_per_day: float
    tipping_fee_usd_per_day: float
    production_tax_credits_usd_per_day: float
    investment_tax_credits_usd_per_day: float
    feedstock_cost_usd_per_day: float
    fixed_opex_usd_per_day: float
    variable_opex_usd_per_day: float
    labor_usd_per_day: float
    maintenance_usd_per_day: float
    insurance_usd_per_day: float
    admin_usd_per_day: float
    electricity_usd_per_day: float
    drying_thermal_usd_per_day: float
    water_usd_per_day: float
    packaging_usd_per_day: float
    biochar_transport_usd_per_day: float
    annualized_capex_usd_per_day: float
    financing_usd_per_day: float


def run_pyrolysis(config: Dict[str, Any], overrides: Dict[str, float] | None = None) -> Dict[str, Any]:
    overrides = overrides or {}
    feed = config["feedstock"]
    pyro = config["pyrolysis"]
    market = config["market"]
    utilities = config["utilities"]
    operations = config["operations"]
    policy = config["policy"]
    economics = config["economics"]
    operating_days = float(config["time"]["operating_days_per_year"])

    wet_tpd = float(overrides.get("wet_tons_per_day", feed["wet_tons_per_day"]))
    moisture = _clamp(float(overrides.get("moisture_fraction", feed["moisture_fraction"])), 0.0, 0.98)
    utilization = _clamp(float(overrides.get("utilization_fraction", pyro.get("utilization_fraction", 1.0))), 0.1, 1.0)
    dry_tpd = wet_tpd * (1.0 - moisture) * utilization

    target_moisture = _clamp(float(pyro.get("target_moisture_fraction", 0.20)), 0.05, 0.6)
    dried_mass_tpd = dry_tpd / max(1.0 - target_moisture, 1e-6)
    initial_water_tpd = wet_tpd * moisture * utilization
    final_water_tpd = max(dried_mass_tpd - dry_tpd, 0.0)
    water_removed_tpd = max(initial_water_tpd - final_water_tpd, 0.0)

    kg_per_mass = kg_per_mass_unit(config)
    latent_heat = float(config["process"].get("latent_heat_mj_per_kg_water_removed", 2.45))
    dryer_eff = _clamp(float(config["process"].get("dryer_efficiency_fraction", 0.70)), 0.1, 1.0)
    drying_mj_day = water_removed_tpd * kg_per_mass * latent_heat / dryer_eff
    drying_mmbtu_day = drying_mj_day / 1055.06

    biochar_yield = _clamp(float(pyro["biochar_yield_fraction_of_dry_feed"]), 0.0, 0.9)
    biooil_yield = _clamp(float(pyro["biooil_yield_fraction_of_dry_feed"]), 0.0, 0.9)
    biochar_tpd = dry_tpd * biochar_yield
    biooil_tpd = dry_tpd * biooil_yield
    syngas_mmbtu_day = dry_tpd * float(pyro["syngas_energy_mmbtu_per_dry_ton"])
    electrical_kwh_day = dry_tpd * float(pyro["process_power_kwh_per_dry_ton"])

    process_outputs = PyrolysisOutputs(
        wet_tons_per_day=wet_tpd,
        dry_tons_per_day=dry_tpd,
        biochar_tons_per_day=biochar_tpd,
        biooil_tons_per_day=biooil_tpd,
        syngas_mmbtu_per_day=syngas_mmbtu_day,
        electrical_kwh_per_day=electrical_kwh_day,
        drying_thermal_mmbtu_per_day=drying_mmbtu_day,
        water_removed_tons_per_day=water_removed_tpd,
        utilization_fraction=utilization,
    )

    app_cfg = config.get("app", {})
    biochar_sales = biochar_tpd * float(market.get("biochar_price_usd_per_ton", 0.0))
    biooil_sales = biooil_tpd * float(market.get("biooil_price_usd_per_ton", 0.0))
    syngas_value = syngas_mmbtu_day * float(market.get("syngas_value_usd_per_mmbtu", 0.0))
    carbon_credits = (
        (biochar_tpd
         * float(pyro.get("biochar_co2e_stored_t_per_ton", 0.0))
         * float(market.get("carbon_credit_usd_per_tco2e", 0.0)))
        if app_cfg.get("enable_carbon_credits", True) else 0.0
    )
    tipping_fee = (
        (wet_tpd * float(market.get("tipping_fee_avoided_usd_per_wet_ton", 0.0)))
        if app_cfg.get("enable_tipping_fee", True) else 0.0
    )
    production_tax_credits = syngas_mmbtu_day * float(policy.get("production_tax_credit_usd_per_mmbtu", 0.0))
    investment_tax_credits = (
        float(pyro.get("capex_usd", 0.0))
        * float(policy.get("investment_tax_credit_fraction_of_capex", 0.0))
        / operating_days
    )
    revenue = biochar_sales + biooil_sales + syngas_value + carbon_credits + tipping_fee + production_tax_credits + investment_tax_credits

    annualized_capex_per_day = compute_annualized_capex(
        capex_usd=float(pyro["capex_usd"]),
        discount_rate=float(economics["discount_rate_fraction"]),
        lifetime_years=int(economics["capex_lifetime_years"]),
    ) / operating_days
    financing = float(pyro["capex_usd"]) * float(economics.get("financing_cost_fraction_of_capex_per_year", 0.0)) / operating_days
    maintenance = float(pyro["capex_usd"]) * float(operations.get("maintenance_fraction_of_capex_per_year", 0.0)) / operating_days
    insurance = float(pyro["capex_usd"]) * float(operations.get("insurance_fraction_of_capex_per_year", 0.0)) / operating_days

    feedstock_cost = wet_tpd * float(feed.get("delivered_cost_usd_per_wet_ton", 0.0))
    fixed_opex = float(pyro.get("fixed_opex_usd_per_day", 0.0))
    variable_opex = wet_tpd * float(pyro.get("variable_opex_usd_per_wet_ton", 0.0))
    labor = float(operations.get("labor_usd_per_day", 0.0))
    admin = float(operations.get("admin_overhead_usd_per_day", 0.0))
    electricity_cost = electrical_kwh_day * float(utilities.get("electricity_price_usd_per_kwh", 0.0))
    drying_thermal_cost = drying_mmbtu_day * float(utilities.get("thermal_energy_price_usd_per_mmbtu", 0.0))
    water_cost = wet_tpd * float(utilities.get("process_water_m3_per_wet_ton", 0.0)) * float(utilities.get("water_price_usd_per_m3", 0.0))
    packaging = biochar_tpd * float(pyro.get("packaging_usd_per_ton_biochar", 0.0))
    biochar_transport = biochar_tpd * float(pyro.get("biochar_transport_usd_per_ton", 0.0))

    costs = (
        annualized_capex_per_day
        + financing
        + feedstock_cost
        + fixed_opex
        + variable_opex
        + labor
        + maintenance
        + insurance
        + admin
        + electricity_cost
        + drying_thermal_cost
        + water_cost
        + packaging
        + biochar_transport
    )

    pre_tax = revenue - costs
    base_tax_rate = float(policy.get("corporate_income_tax_rate_fraction", 0.21))
    tax_cut_fraction = float(policy.get("tax_cut_fraction", 0.0))
    effective_tax = max(0.0, base_tax_rate * (1.0 - tax_cut_fraction))
    income_tax = max(pre_tax, 0.0) * effective_tax
    profit = pre_tax - income_tax

    econ_outputs = PyrolysisEconomics(
        revenue_usd_per_day=revenue,
        costs_usd_per_day=costs,
        pre_tax_profit_usd_per_day=pre_tax,
        income_tax_usd_per_day=income_tax,
        profit_usd_per_day=profit,
        biochar_sales_usd_per_day=biochar_sales,
        biooil_sales_usd_per_day=biooil_sales,
        syngas_value_usd_per_day=syngas_value,
        carbon_credits_usd_per_day=carbon_credits,
        tipping_fee_usd_per_day=tipping_fee,
        production_tax_credits_usd_per_day=production_tax_credits,
        investment_tax_credits_usd_per_day=investment_tax_credits,
        feedstock_cost_usd_per_day=feedstock_cost,
        fixed_opex_usd_per_day=fixed_opex,
        variable_opex_usd_per_day=variable_opex,
        labor_usd_per_day=labor,
        maintenance_usd_per_day=maintenance,
        insurance_usd_per_day=insurance,
        admin_usd_per_day=admin,
        electricity_usd_per_day=electricity_cost,
        drying_thermal_usd_per_day=drying_thermal_cost,
        water_usd_per_day=water_cost,
        packaging_usd_per_day=packaging,
        biochar_transport_usd_per_day=biochar_transport,
        annualized_capex_usd_per_day=annualized_capex_per_day,
        financing_usd_per_day=financing,
    )
    return {"process": asdict(process_outputs), "economics": asdict(econ_outputs)}
