from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict

from .config import annualized_capex
from .process_model import ProcessOutputs


@dataclass
class EconomicOutputs:
    mode: str
    revenue_usd_per_day: float
    costs_usd_per_day: float
    pre_tax_profit_usd_per_day: float
    income_tax_usd_per_day: float
    tax_cut_savings_usd_per_day: float
    profit_usd_per_day: float
    profit_usd_per_wet_ton: float
    methane_sales_usd_per_day: float
    renewable_premium_usd_per_day: float
    carbon_credits_usd_per_day: float
    production_tax_credits_usd_per_day: float
    investment_tax_credits_usd_per_day: float
    char_sales_usd_per_day: float
    avoided_disposal_usd_per_day: float
    transport_usd_per_day: float
    tolling_usd_per_day: float
    transfer_station_usd_per_day: float
    annualized_capex_usd_per_day: float
    financing_usd_per_day: float
    fixed_opex_usd_per_day: float
    variable_opex_usd_per_day: float
    labor_usd_per_day: float
    maintenance_usd_per_day: float
    insurance_usd_per_day: float
    admin_overhead_usd_per_day: float
    catalyst_chemicals_usd_per_day: float
    electricity_usd_per_day: float
    drying_thermal_usd_per_day: float
    water_usd_per_day: float
    ash_disposal_usd_per_day: float
    feedstock_cost_usd_per_day: float

    def to_dict(self) -> Dict[str, float | str]:
        return asdict(self)


def _base_revenue_and_feed_cost(
    process: ProcessOutputs, config: Dict[str, Any], methane_price_usd_per_mmbtu: float
) -> tuple[float, float, float, float, float, float]:
    market = config["market"]
    feed = config["feedstock"]
    app_cfg = config.get("app", {})
    methane_sales = process.methane_mmbtu_per_day * methane_price_usd_per_mmbtu
    renewable_premium = process.methane_mmbtu_per_day * float(market.get("renewable_gas_premium_usd_per_mmbtu", 0.0))
    carbon_credits = (
        (process.methane_mmbtu_per_day
         * float(market.get("co2e_avoided_tco2e_per_mmbtu", 0.0))
         * float(market.get("carbon_credit_usd_per_tco2e", 0.0)))
        if app_cfg.get("enable_carbon_credits", True) else 0.0
    )
    char_sales = process.char_tons_per_day * float(market.get("byproduct_char_sale_usd_per_dry_ton", 0.0))
    avoided_disposal = (
        (process.wet_tons_per_day * float(market.get("tipping_fee_avoided_usd_per_wet_ton", 0.0)))
        if app_cfg.get("enable_tipping_fee", True) else 0.0
    )
    feedstock_cost = process.wet_tons_per_day * float(feed.get("delivered_cost_usd_per_wet_ton", 0.0))
    return methane_sales, renewable_premium, carbon_credits, char_sales, avoided_disposal, feedstock_cost


def evaluate_onsite(process: ProcessOutputs, config: Dict[str, Any], methane_price_usd_per_mmbtu: float) -> EconomicOutputs:
    econ = config["economics"]
    onsite = config["onsite_energy"]
    utilities = config.get("utilities", {})
    operations = config.get("operations", {})
    residues = config.get("residues", {})
    policy = config.get("policy", {})
    methane_sales, renewable_premium, carbon_credits, char_sales, avoided_disposal, feedstock_cost = _base_revenue_and_feed_cost(
        process, config, methane_price_usd_per_mmbtu
    )

    annual_capex = annualized_capex(
        capex_usd=float(onsite["capex_usd"]),
        discount_rate=float(econ["discount_rate_fraction"]),
        lifetime_years=int(econ["capex_lifetime_years"]),
    )
    capex_per_day = annual_capex / float(config["time"]["operating_days_per_year"])
    fixed_opex = float(onsite["fixed_opex_usd_per_day"])
    variable_opex = process.wet_tons_per_day * float(onsite["variable_opex_usd_per_wet_ton"])
    financing = (
        float(onsite["capex_usd"])
        * float(econ.get("financing_cost_fraction_of_capex_per_year", 0.0))
        / float(config["time"]["operating_days_per_year"])
    )
    labor = float(operations.get("labor_usd_per_day", 0.0))
    maintenance = (
        float(onsite["capex_usd"])
        * float(operations.get("maintenance_fraction_of_capex_per_year", 0.0))
        / float(config["time"]["operating_days_per_year"])
    )
    insurance = (
        float(onsite["capex_usd"])
        * float(operations.get("insurance_fraction_of_capex_per_year", 0.0))
        / float(config["time"]["operating_days_per_year"])
    )
    admin = float(operations.get("admin_overhead_usd_per_day", 0.0))
    catalyst_chemicals = process.wet_tons_per_day * (
        float(operations.get("catalyst_usd_per_wet_ton", 0.0)) + float(operations.get("chemicals_usd_per_wet_ton", 0.0))
    )
    electricity = process.electrical_kwh_per_day * float(utilities.get("electricity_price_usd_per_kwh", 0.0))
    drying_thermal = process.drying_thermal_mmbtu_per_day * float(utilities.get("thermal_energy_price_usd_per_mmbtu", 0.0))
    water = process.wet_tons_per_day * float(utilities.get("process_water_m3_per_wet_ton", 0.0)) * float(
        utilities.get("water_price_usd_per_m3", 0.0)
    )
    ash_disposal = process.ash_tons_per_day * float(residues.get("ash_disposal_usd_per_dry_ton_ash", 0.0))
    production_tax_credit = process.methane_mmbtu_per_day * float(policy.get("production_tax_credit_usd_per_mmbtu", 0.0))
    investment_tax_credit = (
        float(onsite["capex_usd"])
        * float(policy.get("investment_tax_credit_fraction_of_capex", 0.0))
        / float(config["time"]["operating_days_per_year"])
    )

    revenue = (
        methane_sales
        + renewable_premium
        + carbon_credits
        + production_tax_credit
        + investment_tax_credit
        + char_sales
        + avoided_disposal
    )
    costs = (
        capex_per_day
        + financing
        + fixed_opex
        + variable_opex
        + labor
        + maintenance
        + insurance
        + admin
        + catalyst_chemicals
        + electricity
        + drying_thermal
        + water
        + ash_disposal
        + feedstock_cost
    )
    pre_tax_profit = revenue - costs
    base_tax_rate = float(policy.get("corporate_income_tax_rate_fraction", 0.21))
    tax_cut_fraction = float(policy.get("tax_cut_fraction", 0.0))
    effective_tax_rate = max(0.0, base_tax_rate * (1.0 - tax_cut_fraction))
    taxable_income = max(pre_tax_profit, 0.0)
    income_tax = taxable_income * effective_tax_rate
    tax_cut_savings = taxable_income * (base_tax_rate - effective_tax_rate)
    profit = pre_tax_profit - income_tax

    return EconomicOutputs(
        mode="onsite_energy",
        revenue_usd_per_day=revenue,
        costs_usd_per_day=costs,
        pre_tax_profit_usd_per_day=pre_tax_profit,
        income_tax_usd_per_day=income_tax,
        tax_cut_savings_usd_per_day=tax_cut_savings,
        profit_usd_per_day=profit,
        profit_usd_per_wet_ton=profit / max(process.wet_tons_per_day, 1e-6),
        methane_sales_usd_per_day=methane_sales,
        renewable_premium_usd_per_day=renewable_premium,
        carbon_credits_usd_per_day=carbon_credits,
        production_tax_credits_usd_per_day=production_tax_credit,
        investment_tax_credits_usd_per_day=investment_tax_credit,
        char_sales_usd_per_day=char_sales,
        avoided_disposal_usd_per_day=avoided_disposal,
        transport_usd_per_day=0.0,
        tolling_usd_per_day=0.0,
        transfer_station_usd_per_day=0.0,
        annualized_capex_usd_per_day=capex_per_day,
        financing_usd_per_day=financing,
        fixed_opex_usd_per_day=fixed_opex,
        variable_opex_usd_per_day=variable_opex,
        labor_usd_per_day=labor,
        maintenance_usd_per_day=maintenance,
        insurance_usd_per_day=insurance,
        admin_overhead_usd_per_day=admin,
        catalyst_chemicals_usd_per_day=catalyst_chemicals,
        electricity_usd_per_day=electricity,
        drying_thermal_usd_per_day=drying_thermal,
        water_usd_per_day=water,
        ash_disposal_usd_per_day=ash_disposal,
        feedstock_cost_usd_per_day=feedstock_cost,
    )


def evaluate_existing_facility(process: ProcessOutputs, config: Dict[str, Any], methane_price_usd_per_mmbtu: float) -> EconomicOutputs:
    facility = config["existing_facility"]
    operations = config.get("operations", {})
    policy = config.get("policy", {})
    methane_sales, renewable_premium, carbon_credits, char_sales, avoided_disposal, feedstock_cost = _base_revenue_and_feed_cost(
        process, config, methane_price_usd_per_mmbtu
    )

    revenue_share = float(facility["revenue_share_fraction"])
    methane_sales_shared = methane_sales * revenue_share
    premium_shared = renewable_premium * revenue_share
    carbon_shared = carbon_credits * revenue_share
    production_tax_credit_shared = process.methane_mmbtu_per_day * float(policy.get("production_tax_credit_usd_per_mmbtu", 0.0)) * revenue_share
    char_shared = char_sales * revenue_share

    transport = process.wet_tons_per_day * float(facility["transport_distance_km"]) * float(facility["transport_cost_usd_per_ton_km"])
    tolling = process.wet_tons_per_day * float(facility["tolling_fee_usd_per_wet_ton"])
    transfer_station = process.wet_tons_per_day * float(facility.get("transfer_station_fee_usd_per_wet_ton", 0.0))
    admin = float(operations.get("admin_overhead_usd_per_day", 0.0)) * 0.35

    revenue = methane_sales_shared + premium_shared + carbon_shared + production_tax_credit_shared + char_shared + avoided_disposal
    costs = transport + tolling + transfer_station + admin + feedstock_cost
    pre_tax_profit = revenue - costs
    base_tax_rate = float(policy.get("corporate_income_tax_rate_fraction", 0.21))
    tax_cut_fraction = float(policy.get("tax_cut_fraction", 0.0))
    effective_tax_rate = max(0.0, base_tax_rate * (1.0 - tax_cut_fraction))
    taxable_income = max(pre_tax_profit, 0.0)
    income_tax = taxable_income * effective_tax_rate
    tax_cut_savings = taxable_income * (base_tax_rate - effective_tax_rate)
    profit = pre_tax_profit - income_tax

    return EconomicOutputs(
        mode="existing_facility",
        revenue_usd_per_day=revenue,
        costs_usd_per_day=costs,
        pre_tax_profit_usd_per_day=pre_tax_profit,
        income_tax_usd_per_day=income_tax,
        tax_cut_savings_usd_per_day=tax_cut_savings,
        profit_usd_per_day=profit,
        profit_usd_per_wet_ton=profit / max(process.wet_tons_per_day, 1e-6),
        methane_sales_usd_per_day=methane_sales_shared,
        renewable_premium_usd_per_day=premium_shared,
        carbon_credits_usd_per_day=carbon_shared,
        production_tax_credits_usd_per_day=production_tax_credit_shared,
        investment_tax_credits_usd_per_day=0.0,
        char_sales_usd_per_day=char_shared,
        avoided_disposal_usd_per_day=avoided_disposal,
        transport_usd_per_day=transport,
        tolling_usd_per_day=tolling,
        transfer_station_usd_per_day=transfer_station,
        annualized_capex_usd_per_day=0.0,
        financing_usd_per_day=0.0,
        fixed_opex_usd_per_day=0.0,
        variable_opex_usd_per_day=0.0,
        labor_usd_per_day=0.0,
        maintenance_usd_per_day=0.0,
        insurance_usd_per_day=0.0,
        admin_overhead_usd_per_day=admin,
        catalyst_chemicals_usd_per_day=0.0,
        electricity_usd_per_day=0.0,
        drying_thermal_usd_per_day=0.0,
        water_usd_per_day=0.0,
        ash_disposal_usd_per_day=0.0,
        feedstock_cost_usd_per_day=feedstock_cost,
    )

