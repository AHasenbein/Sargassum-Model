from __future__ import annotations

from copy import deepcopy
import hmac
import json
import os
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.sargassum_model.config import load_config, save_config
from src.sargassum_model.data_sources import pull_miami_data
from src.sargassum_model.units import (
    energy_to_display,
    mass_label,
    mass_unit_long,
    energy_label,
)
from src.sargassum_model.modes import run_mode_bundle
from src.sargassum_model.optimizer import optimize_mode, run_sensitivity
from src.sargassum_model.pyrolysis_model import run_pyrolysis
from src.sargassum_model.validation import validate_and_normalize_config
from src.sargassum_model.visualization import mode_profit_bar, process_sankey, profit_waterfall, sensitivity_tornado


CONFIG_PATH = Path("config/model_config.yaml")
USER_SETTINGS_DIR = Path("data/user_settings")


def apply_basic_cost_mode(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(cfg)
    cfg.setdefault("policy", {})
    cfg.setdefault("economics", {})
    cfg.setdefault("operations", {})
    cfg.setdefault("onsite_energy", {})
    cfg.setdefault("pyrolysis", {})
    cfg["onsite_energy"]["capex_usd"] = 0.0
    cfg["pyrolysis"]["capex_usd"] = 0.0
    cfg["economics"]["financing_cost_fraction_of_capex_per_year"] = 0.0
    cfg["operations"]["maintenance_fraction_of_capex_per_year"] = 0.0
    cfg["operations"]["insurance_fraction_of_capex_per_year"] = 0.0
    cfg["policy"]["investment_tax_credit_fraction_of_capex"] = 0.0
    cfg["policy"]["corporate_income_tax_rate_fraction"] = 0.0
    cfg["policy"]["tax_cut_fraction"] = 0.0
    cfg["policy"]["production_tax_credit_usd_per_mmbtu"] = 0.0
    return cfg


@st.cache_data(ttl=300, show_spinner=False)
def run_cached_models(config_for_run: Dict[str, Any]) -> Dict[str, Any]:
    bundle = pull_miami_data(config_for_run, raw_data_dir="data/raw")
    methane_price = float(bundle.methane_price_usd_per_mmbtu)
    results = run_mode_bundle(config_for_run, methane_price)
    pyrolysis_result = run_pyrolysis(config_for_run)
    return {
        "bundle": bundle,
        "methane_price": methane_price,
        "gasification_results": results,
        "pyrolysis_result": pyrolysis_result,
    }


def check_auth(config: Dict[str, Any]) -> None:
    auth_cfg = config.get("app", {}).get("auth", {})
    if not bool(auth_cfg.get("enabled", False)):
        return

    allowed_users = {str(u).strip().lower() for u in auth_cfg.get("users", []) if str(u).strip()}
    password_env_var = str(auth_cfg.get("password_env_var", "APP_PASSWORD"))
    default_password = str(auth_cfg.get("default_password", "nori"))
    expected_password = os.getenv(password_env_var, default_password)

    if st.session_state.get("authenticated", False):
        st.sidebar.success(f"Logged in as {st.session_state.get('auth_user', 'user')}")
        if st.sidebar.button("Logout"):
            st.session_state["authenticated"] = False
            st.session_state["auth_user"] = ""
            st.rerun()
        return

    st.title("Sargassum Model Login")
    st.caption("Authorized users only.")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user_ok = username.strip().lower() in allowed_users
        pass_ok = hmac.compare_digest(password, expected_password)
        if user_ok and pass_ok:
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = username.strip()
            st.rerun()
        st.error("Invalid username or password.")
    st.stop()


def _safe_user_id(username: str) -> str:
    cleaned = "".join(ch for ch in username.lower() if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "user"


def _user_settings_path(username: str) -> Path:
    USER_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    return USER_SETTINGS_DIR / f"{_safe_user_id(username)}.yaml"


def _extract_user_preferences(config: Dict[str, Any]) -> Dict[str, Any]:
    allowed_sections = [
        "project",
        "feedstock",
        "process",
        "onsite_energy",
        "existing_facility",
        "market",
        "utilities",
        "operations",
        "residues",
        "miami_data",
        "optimization",
        "analysis",
        "policy",
        "pyrolysis",
        "app",
    ]
    out: Dict[str, Any] = {}
    for key in allowed_sections:
        if key in config:
            out[key] = deepcopy(config[key])
    # Never allow auth config to be user-overridden.
    if "app" in out and isinstance(out["app"], dict):
        out["app"].pop("auth", None)
    return out


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_update(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_user_preferences(base_config: Dict[str, Any], username: str) -> Dict[str, Any]:
    path = _user_settings_path(username)
    if not path.exists():
        return base_config
    try:
        user_cfg = load_config(path)
        return _deep_update(base_config, user_cfg)
    except Exception:
        return base_config


def persist_user_preferences(current_config: Dict[str, Any], username: str) -> None:
    prefs = _extract_user_preferences(current_config)
    fingerprint = json.dumps(prefs, sort_keys=True, default=str)
    if st.session_state.get("prefs_fingerprint") == fingerprint:
        return
    path = _user_settings_path(username)
    save_config(prefs, path)
    st.session_state["prefs_fingerprint"] = fingerprint


def processing_cost_usd_per_day(econ: Dict[str, float]) -> float:
    return float(
        econ.get("fixed_opex_usd_per_day", 0.0)
        + econ.get("variable_opex_usd_per_day", 0.0)
        + econ.get("labor_usd_per_day", 0.0)
        + econ.get("maintenance_usd_per_day", 0.0)
        + econ.get("insurance_usd_per_day", 0.0)
        + econ.get("admin_overhead_usd_per_day", 0.0)
        + econ.get("catalyst_chemicals_usd_per_day", 0.0)
        + econ.get("electricity_usd_per_day", 0.0)
        + econ.get("drying_thermal_usd_per_day", 0.0)
        + econ.get("water_usd_per_day", 0.0)
        + econ.get("ash_disposal_usd_per_day", 0.0)
        + econ.get("tolling_usd_per_day", 0.0)
        + econ.get("transfer_station_usd_per_day", 0.0)
        + econ.get("transport_usd_per_day", 0.0)
        + econ.get("annualized_capex_usd_per_day", 0.0)
        + econ.get("financing_usd_per_day", 0.0)
    )


def sidebar_inputs(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(config)
    cfg.setdefault("app", {})
    cfg["app"].setdefault("basic_cost_mode", True)
    cfg["app"].setdefault("use_si_units", True)
    cfg["app"].setdefault("enable_tipping_fee", True)
    cfg["app"].setdefault("enable_carbon_credits", True)
    st.sidebar.header("Model controls")
    cfg["project"]["run_mode"] = st.sidebar.selectbox(
        "Operating mode",
        options=["auto_compare", "onsite_energy", "existing_facility"],
        index=["auto_compare", "onsite_energy", "existing_facility"].index(cfg["project"]["run_mode"]),
    )
    cfg["miami_data"]["use_live_data"] = st.sidebar.toggle("Use live Miami data pulls", value=cfg["miami_data"]["use_live_data"])
    cfg["app"]["basic_cost_mode"] = st.sidebar.toggle("Basic cost-only mode (no CAPEX/taxes)", value=bool(cfg["app"]["basic_cost_mode"]))
    cfg["app"]["use_si_units"] = st.sidebar.toggle("SI units (tonnes, GJ)", value=bool(cfg["app"].get("use_si_units", True)))
    cfg["app"]["enable_tipping_fee"] = st.sidebar.toggle("Include tipping fee revenue", value=bool(cfg["app"].get("enable_tipping_fee", True)))
    cfg["app"]["enable_carbon_credits"] = st.sidebar.toggle("Include carbon credits", value=bool(cfg["app"].get("enable_carbon_credits", True)))

    mass_lbl = mass_unit_long(cfg)
    st.sidebar.subheader("Feedstock")
    cfg["feedstock"]["wet_tons_per_day"] = st.sidebar.number_input(f"Wet {mass_lbl}/day", 1.0, 1000.0, float(cfg["feedstock"]["wet_tons_per_day"]), 0.5)
    cfg["feedstock"]["moisture_fraction"] = st.sidebar.number_input("Initial moisture fraction", 0.40, 0.95, float(cfg["feedstock"]["moisture_fraction"]), 0.01)
    cfg["feedstock"]["delivered_cost_usd_per_wet_ton"] = st.sidebar.number_input(
        f"Feedstock delivered cost (USD/wet {mass_label(cfg)})",
        0.0,
        120.0,
        float(cfg["feedstock"]["delivered_cost_usd_per_wet_ton"]),
        1.0,
    )

    st.sidebar.subheader("Process")
    cfg["process"]["drying_target_moisture_fraction"] = st.sidebar.number_input(
        "Drying target moisture fraction",
        0.10,
        0.60,
        float(cfg["process"]["drying_target_moisture_fraction"]),
        0.01,
    )
    cfg["process"]["gasification_efficiency_fraction"] = st.sidebar.number_input(
        "Gasification efficiency",
        0.30,
        0.90,
        float(cfg["process"]["gasification_efficiency_fraction"]),
        0.01,
    )
    cfg["process"]["syngas_to_methane_efficiency_fraction"] = st.sidebar.number_input(
        "Syngas->methane efficiency",
        0.20,
        0.90,
        float(cfg["process"]["syngas_to_methane_efficiency_fraction"]),
        0.01,
    )
    cfg["process"]["parasitic_load_fraction"] = st.sidebar.number_input(
        "Parasitic load fraction",
        0.00,
        0.40,
        float(cfg["process"]["parasitic_load_fraction"]),
        0.01,
    )

    st.sidebar.subheader("Onsite economics")
    cfg["onsite_energy"]["capex_usd"] = st.sidebar.number_input("Onsite CAPEX (USD)", 0.0, 100000000.0, float(cfg["onsite_energy"]["capex_usd"]), 50000.0)
    cfg["onsite_energy"]["fixed_opex_usd_per_day"] = st.sidebar.number_input(
        "Onsite fixed OPEX (USD/day)",
        0.0,
        200000.0,
        float(cfg["onsite_energy"]["fixed_opex_usd_per_day"]),
        50.0,
    )
    cfg["onsite_energy"]["variable_opex_usd_per_wet_ton"] = st.sidebar.number_input(
        f"Onsite variable OPEX (USD/wet {mass_label(cfg)})",
        0.0,
        500.0,
        float(cfg["onsite_energy"]["variable_opex_usd_per_wet_ton"]),
        1.0,
    )

    st.sidebar.subheader("Existing facility economics")
    cfg["existing_facility"]["transport_distance_km"] = st.sidebar.number_input(
        "Transport distance (km)",
        1.0,
        300.0,
        float(cfg["existing_facility"]["transport_distance_km"]),
        1.0,
    )
    cfg["existing_facility"]["transport_cost_usd_per_ton_km"] = st.sidebar.number_input(
        f"Transport cost (USD/{mass_label(cfg)}·km)",
        0.05,
        2.0,
        float(cfg["existing_facility"]["transport_cost_usd_per_ton_km"]),
        0.01,
    )
    cfg["existing_facility"]["tolling_fee_usd_per_wet_ton"] = st.sidebar.number_input(
        f"Facility tolling fee (USD/wet {mass_label(cfg)})",
        0.0,
        250.0,
        float(cfg["existing_facility"]["tolling_fee_usd_per_wet_ton"]),
        1.0,
    )
    cfg["existing_facility"]["revenue_share_fraction"] = st.sidebar.number_input(
        "Revenue share fraction",
        0.10,
        1.00,
        float(cfg["existing_facility"]["revenue_share_fraction"]),
        0.01,
    )

    st.sidebar.subheader("Policy and credits")
    cfg["market"]["carbon_credit_usd_per_tco2e"] = st.sidebar.number_input(
        "Carbon credit (USD/tCO2e)",
        0.0,
        500.0,
        float(cfg["market"].get("carbon_credit_usd_per_tco2e", 0.0)),
        1.0,
    )
    cfg["policy"]["production_tax_credit_usd_per_mmbtu"] = st.sidebar.number_input(
        "Production tax credit (USD/MMBtu)",
        0.0,
        50.0,
        float(cfg["policy"].get("production_tax_credit_usd_per_mmbtu", 0.0)),
        0.25,
    )
    cfg["policy"]["investment_tax_credit_fraction_of_capex"] = st.sidebar.number_input(
        "Investment tax credit (% of CAPEX)",
        0.0,
        0.80,
        float(cfg["policy"].get("investment_tax_credit_fraction_of_capex", 0.0)),
        0.01,
    )
    cfg["policy"]["corporate_income_tax_rate_fraction"] = st.sidebar.number_input(
        "Corporate income tax rate",
        0.0,
        0.45,
        float(cfg["policy"].get("corporate_income_tax_rate_fraction", 0.21)),
        0.01,
    )
    cfg["policy"]["tax_cut_fraction"] = st.sidebar.number_input(
        "Tax cut fraction",
        0.0,
        1.0,
        float(cfg["policy"].get("tax_cut_fraction", 0.0)),
        0.01,
    )
    st.sidebar.subheader("Pyrolysis and biochar")
    cfg["pyrolysis"]["biochar_yield_fraction_of_dry_feed"] = st.sidebar.number_input(
        "Biochar yield (fraction of dry feed)",
        0.10,
        0.60,
        float(cfg["pyrolysis"]["biochar_yield_fraction_of_dry_feed"]),
        0.01,
    )
    cfg["pyrolysis"]["biooil_yield_fraction_of_dry_feed"] = st.sidebar.number_input(
        "Bio-oil yield (fraction of dry feed)",
        0.05,
        0.50,
        float(cfg["pyrolysis"]["biooil_yield_fraction_of_dry_feed"]),
        0.01,
    )
    cfg["market"]["biochar_price_usd_per_ton"] = st.sidebar.number_input(
        f"Biochar sale price (USD/{mass_label(cfg)})",
        0.0,
        2000.0,
        float(cfg["market"]["biochar_price_usd_per_ton"]),
        10.0,
    )
    cfg["market"]["biooil_price_usd_per_ton"] = st.sidebar.number_input(
        f"Bio-oil sale price (USD/{mass_label(cfg)})",
        0.0,
        2000.0,
        float(cfg["market"]["biooil_price_usd_per_ton"]),
        10.0,
    )
    cfg["pyrolysis"]["capex_usd"] = st.sidebar.number_input(
        "Pyrolysis CAPEX (USD)",
        0.0,
        100000000.0,
        float(cfg["pyrolysis"]["capex_usd"]),
        50000.0,
    )

    with st.sidebar.expander("Advanced parameters"):
        cfg.setdefault("time", {"operating_days_per_year": 290})
        cfg.setdefault("economics", {})
        cfg.setdefault("utilities", {})
        cfg.setdefault("operations", {})
        cfg.setdefault("residues", {})
        adv_mass = mass_label(cfg)
        cfg["time"]["operating_days_per_year"] = int(st.number_input("Operating days/year", 1, 365, int(cfg["time"].get("operating_days_per_year", 290)), 1))
        cfg["feedstock"]["ash_fraction_dry"] = st.number_input("Ash fraction (dry)", 0.05, 0.70, float(cfg["feedstock"]["ash_fraction_dry"]), 0.01)
        cfg["feedstock"]["carbon_fraction_dry"] = st.number_input("Carbon fraction (dry)", 0.15, 0.50, float(cfg["feedstock"]["carbon_fraction_dry"]), 0.01)
        cfg["feedstock"]["hhv_mj_per_kg_dry"] = st.number_input("HHV (MJ/kg dry)", 5.0, 25.0, float(cfg["feedstock"]["hhv_mj_per_kg_dry"]), 0.5)
        cfg["process"]["latent_heat_mj_per_kg_water_removed"] = st.number_input("Latent heat water (MJ/kg)", 2.0, 3.0, float(cfg["process"].get("latent_heat_mj_per_kg_water_removed", 2.45)), 0.05)
        cfg["process"]["dryer_efficiency_fraction"] = st.number_input("Dryer efficiency", 0.30, 0.95, float(cfg["process"].get("dryer_efficiency_fraction", 0.70)), 0.01)
        cfg["process"]["gasification_power_kwh_per_dry_ton"] = st.number_input(f"Gasification power (kWh/dry {adv_mass})", 50.0, 300.0, float(cfg["process"].get("gasification_power_kwh_per_dry_ton", 150)), 5.0)
        cfg["process"]["methanation_power_kwh_per_mmbtu_methane"] = st.number_input("Methanation power (kWh/MMBtu)", 5.0, 50.0, float(cfg["process"].get("methanation_power_kwh_per_mmbtu_methane", 18)), 1.0)
        cfg["process"]["char_yield_fraction_of_dry_feed"] = st.number_input("Char yield (fraction)", 0.05, 0.25, float(cfg["process"].get("char_yield_fraction_of_dry_feed", 0.12)), 0.01)
        cfg["market"]["methane_price_usd_per_mmbtu"] = st.number_input("Methane price (USD/MMBtu)", 0.0, 50.0, float(cfg["market"].get("methane_price_usd_per_mmbtu", 6.5)), 0.25)
        cfg["market"]["fallback_natural_gas_price_usd_per_mmbtu"] = st.number_input("Fallback gas price (USD/MMBtu)", 0.0, 50.0, float(cfg["market"].get("fallback_natural_gas_price_usd_per_mmbtu", 6.5)), 0.25)
        cfg["market"]["tipping_fee_avoided_usd_per_wet_ton"] = st.number_input(f"Tipping fee avoided (USD/wet {adv_mass})", 0.0, 200.0, float(cfg["market"].get("tipping_fee_avoided_usd_per_wet_ton", 5.0)), 1.0)
        cfg["market"]["renewable_gas_premium_usd_per_mmbtu"] = st.number_input("Renewable gas premium (USD/MMBtu)", 0.0, 20.0, float(cfg["market"].get("renewable_gas_premium_usd_per_mmbtu", 2.5)), 0.25)
        cfg["market"]["co2e_avoided_tco2e_per_mmbtu"] = st.number_input("CO2e avoided (tCO2e/MMBtu)", 0.0, 0.15, float(cfg["market"].get("co2e_avoided_tco2e_per_mmbtu", 0.065)), 0.005)
        cfg["market"]["byproduct_char_sale_usd_per_dry_ton"] = st.number_input(f"Char sale price (USD/dry {adv_mass})", 0.0, 500.0, float(cfg["market"].get("byproduct_char_sale_usd_per_dry_ton", 20)), 5.0)
        cfg["market"]["syngas_value_usd_per_mmbtu"] = st.number_input("Syngas value (USD/MMBtu)", 0.0, 20.0, float(cfg["market"].get("syngas_value_usd_per_mmbtu", 6.0)), 0.5)
        cfg["pyrolysis"]["target_moisture_fraction"] = st.number_input("Pyrolysis target moisture", 0.05, 0.40, float(cfg["pyrolysis"].get("target_moisture_fraction", 0.20)), 0.01)
        cfg["pyrolysis"]["utilization_fraction"] = st.number_input("Pyrolysis utilization", 0.50, 1.0, float(cfg["pyrolysis"].get("utilization_fraction", 1.0)), 0.01)
        cfg["pyrolysis"]["syngas_energy_mmbtu_per_dry_ton"] = st.number_input(f"Pyrolysis syngas (MMBtu/dry {adv_mass})", 1.0, 10.0, float(cfg["pyrolysis"].get("syngas_energy_mmbtu_per_dry_ton", 4.0)), 0.5)
        cfg["pyrolysis"]["process_power_kwh_per_dry_ton"] = st.number_input(f"Pyrolysis power (kWh/dry {adv_mass})", 50.0, 300.0, float(cfg["pyrolysis"].get("process_power_kwh_per_dry_ton", 140)), 5.0)
        cfg["pyrolysis"]["fixed_opex_usd_per_day"] = st.number_input("Pyrolysis fixed OPEX (USD/day)", 0.0, 50000.0, float(cfg["pyrolysis"].get("fixed_opex_usd_per_day", 0)), 100.0)
        cfg["pyrolysis"]["variable_opex_usd_per_wet_ton"] = st.number_input(f"Pyrolysis variable OPEX (USD/wet {adv_mass})", 0.0, 100.0, float(cfg["pyrolysis"].get("variable_opex_usd_per_wet_ton", 18)), 1.0)
        cfg["pyrolysis"]["packaging_usd_per_ton_biochar"] = st.number_input(f"Biochar packaging (USD/{adv_mass})", 0.0, 100.0, float(cfg["pyrolysis"].get("packaging_usd_per_ton_biochar", 22)), 1.0)
        cfg["pyrolysis"]["biochar_transport_usd_per_ton"] = st.number_input(f"Biochar transport (USD/{adv_mass})", 0.0, 100.0, float(cfg["pyrolysis"].get("biochar_transport_usd_per_ton", 30)), 1.0)
        cfg["pyrolysis"]["biochar_co2e_stored_t_per_ton"] = st.number_input("Biochar CO2e stored (tCO2e/t)", 0.0, 5.0, float(cfg["pyrolysis"].get("biochar_co2e_stored_t_per_ton", 2.2)), 0.1)
        cfg["economics"]["discount_rate_fraction"] = st.number_input("Discount rate", 0.0, 0.25, float(cfg["economics"].get("discount_rate_fraction", 0.10)), 0.01)
        cfg["economics"]["capex_lifetime_years"] = int(st.number_input("CAPEX lifetime (years)", 5, 30, int(cfg["economics"].get("capex_lifetime_years", 15)), 1))
        cfg["economics"]["financing_cost_fraction_of_capex_per_year"] = st.number_input("Financing cost (fraction)", 0.0, 0.15, float(cfg["economics"].get("financing_cost_fraction_of_capex_per_year", 0)), 0.01)
        cfg["existing_facility"]["transfer_station_fee_usd_per_wet_ton"] = st.number_input(f"Transfer station fee (USD/wet {adv_mass})", 0.0, 50.0, float(cfg["existing_facility"].get("transfer_station_fee_usd_per_wet_ton", 5)), 0.5)
        cfg["utilities"]["electricity_price_usd_per_kwh"] = st.number_input("Electricity price (USD/kWh)", 0.0, 0.50, float(cfg["utilities"].get("electricity_price_usd_per_kwh", 0.11)), 0.01)
        cfg["utilities"]["thermal_energy_price_usd_per_mmbtu"] = st.number_input("Thermal energy (USD/MMBtu)", 0.0, 20.0, float(cfg["utilities"].get("thermal_energy_price_usd_per_mmbtu", 7)), 0.5)
        cfg["utilities"]["water_price_usd_per_m3"] = st.number_input("Water price (USD/m³)", 0.0, 10.0, float(cfg["utilities"].get("water_price_usd_per_m3", 2)), 0.25)
        cfg["utilities"]["process_water_m3_per_wet_ton"] = st.number_input(f"Process water (m³/wet {adv_mass})", 0.0, 2.0, float(cfg["utilities"].get("process_water_m3_per_wet_ton", 0.5)), 0.05)
        cfg["operations"]["labor_usd_per_day"] = st.number_input("Labor (USD/day)", 0.0, 10000.0, float(cfg["operations"].get("labor_usd_per_day", 0)), 50.0)
        cfg["operations"]["maintenance_fraction_of_capex_per_year"] = st.number_input("Maintenance (% CAPEX/yr)", 0.0, 0.15, float(cfg["operations"].get("maintenance_fraction_of_capex_per_year", 0)), 0.01)
        cfg["operations"]["insurance_fraction_of_capex_per_year"] = st.number_input("Insurance (% CAPEX/yr)", 0.0, 0.05, float(cfg["operations"].get("insurance_fraction_of_capex_per_year", 0)), 0.005)
        cfg["operations"]["admin_overhead_usd_per_day"] = st.number_input("Admin overhead (USD/day)", 0.0, 2000.0, float(cfg["operations"].get("admin_overhead_usd_per_day", 0)), 50.0)
        cfg["operations"]["catalyst_usd_per_wet_ton"] = st.number_input(f"Catalyst (USD/wet {adv_mass})", 0.0, 20.0, float(cfg["operations"].get("catalyst_usd_per_wet_ton", 5)), 0.5)
        cfg["operations"]["chemicals_usd_per_wet_ton"] = st.number_input(f"Chemicals (USD/wet {adv_mass})", 0.0, 20.0, float(cfg["operations"].get("chemicals_usd_per_wet_ton", 4)), 0.5)
        cfg["residues"]["ash_disposal_usd_per_dry_ton_ash"] = st.number_input(f"Ash disposal (USD/dry {adv_mass})", 0.0, 500.0, float(cfg["residues"].get("ash_disposal_usd_per_dry_ton_ash", 180)), 10.0)

    return cfg


def pyrolysis_waterfall(pyro: Dict[str, Any]) -> go.Figure:
    econ = pyro["economics"]
    entries = [
        ("Biochar sales", econ["biochar_sales_usd_per_day"]),
        ("Bio-oil sales", econ["biooil_sales_usd_per_day"]),
        ("Syngas value", econ["syngas_value_usd_per_day"]),
        ("Carbon credits", econ["carbon_credits_usd_per_day"]),
        ("Tipping fee", econ["tipping_fee_usd_per_day"]),
        ("Production tax credits", econ["production_tax_credits_usd_per_day"]),
        ("Investment tax credits", econ["investment_tax_credits_usd_per_day"]),
        ("Feedstock", -econ["feedstock_cost_usd_per_day"]),
        ("Fixed OPEX", -econ["fixed_opex_usd_per_day"]),
        ("Variable OPEX", -econ["variable_opex_usd_per_day"]),
        ("Labor", -econ["labor_usd_per_day"]),
        ("Maintenance", -econ["maintenance_usd_per_day"]),
        ("Insurance", -econ["insurance_usd_per_day"]),
        ("Admin", -econ["admin_usd_per_day"]),
        ("Electricity", -econ["electricity_usd_per_day"]),
        ("Drying thermal", -econ["drying_thermal_usd_per_day"]),
        ("Water", -econ["water_usd_per_day"]),
        ("Packaging", -econ["packaging_usd_per_day"]),
        ("Biochar transport", -econ["biochar_transport_usd_per_day"]),
        ("CAPEX charge", -econ["annualized_capex_usd_per_day"]),
        ("Financing", -econ["financing_usd_per_day"]),
        ("Income tax", -econ["income_tax_usd_per_day"]),
    ]
    labels = [x[0] for x in entries] + ["Net profit"]
    values = [float(x[1]) for x in entries] + [float(econ["profit_usd_per_day"])]
    measures = ["relative"] * len(entries) + ["total"]
    fig = go.Figure(go.Waterfall(x=labels, y=values, measure=measures))
    fig.update_layout(title="Pyrolysis Profit Waterfall", yaxis_title="USD/day")
    return fig


def run_dashboard() -> None:
    st.set_page_config(page_title="Sargassum to Methane Model", layout="wide")
    config = validate_and_normalize_config(load_config(CONFIG_PATH))
    check_auth(config)
    auth_user = str(st.session_state.get("auth_user", "anonymous"))
    config = validate_and_normalize_config(load_user_preferences(config, auth_user))
    st.title("Sargassum to Methane Model (Miami)")
    st.caption("Interactive gasification + methanation model with expanded techno-economic accounting.")
    if config.get("project", {}).get("conversion_path") != "gasification_methanation":
        st.error("This dashboard is for gasification_methanation. Update project.conversion_path in config.")
        st.stop()
    working_config = validate_and_normalize_config(sidebar_inputs(config))
    if bool(working_config.get("app", {}).get("basic_cost_mode", True)):
        working_config = apply_basic_cost_mode(working_config)
    persist_user_preferences(working_config, auth_user)
    st.sidebar.caption("Live mode: changing any input updates both tabs automatically.")
    st.sidebar.caption(f"User settings auto-saved for: {auth_user}")

    if st.sidebar.button("Save current controls to config file"):
        save_config(working_config, CONFIG_PATH)
        st.sidebar.success("Saved to config/model_config.yaml")

    with st.spinner("Pulling Miami data and running model..."):
        computed = run_cached_models(working_config)
        bundle = computed["bundle"]
        methane_price = float(computed["methane_price"])
        results = computed["gasification_results"]
        pyrolysis_result = computed["pyrolysis_result"]

    st.info(
        f"Methane price source: {bundle.source_notes['price']} | "
        f"Ambient source: {bundle.source_notes['temperature']} | "
        f"Pulled: {bundle.pulled_at_utc}"
    )
    gas_tab, pyro_tab = st.tabs(["Gasification + Methanation", "Pyrolysis + Biochar"])

    with gas_tab:
        best = results[0]
        proc_cost = processing_cost_usd_per_day(best["economics"])
        methane_val = energy_to_display(best["process"]["methane_mmbtu_per_day"], working_config)
        energy_lbl = energy_label(working_config)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Best mode", best["mode"])
        c2.metric("Profit (USD/day)", f"{best['economics']['profit_usd_per_day']:,.0f}")
        c3.metric(f"Methane ({energy_lbl}/day)", f"{methane_val:,.1f}")
        c4.metric("Processing cost (USD/day)", f"{proc_cost:,.0f}")

        c5, c6, c7 = st.columns(3)
        c5.metric("Carbon credits (USD/day)", f"{best['economics'].get('carbon_credits_usd_per_day', 0.0):,.0f}")
        c6.metric(
            "Tax credits (USD/day)",
            f"{best['economics'].get('production_tax_credits_usd_per_day', 0.0) + best['economics'].get('investment_tax_credits_usd_per_day', 0.0):,.0f}",
        )
        c7.metric("Income tax (USD/day)", f"{best['economics'].get('income_tax_usd_per_day', 0.0):,.0f}")

        st.plotly_chart(mode_profit_bar(results, working_config), width="stretch")
        table_rows = [
            {
                "mode": r["mode"],
                "profit_usd_per_day": r["economics"]["profit_usd_per_day"],
                "profit_usd_per_wet_ton": r["economics"]["profit_usd_per_wet_ton"],
                "methane_energy_per_day": energy_to_display(r["process"]["methane_mmbtu_per_day"], working_config),
            }
            for r in results
        ]
        df_table = pd.DataFrame(table_rows).rename(columns={
            "methane_energy_per_day": f"Methane ({energy_label(working_config)}/day)",
            "profit_usd_per_wet_ton": f"Profit (USD/wet {mass_label(working_config)})",
        })
        st.subheader("Mode comparison table")
        st.dataframe(df_table, width="stretch")

        st.subheader("Profit waterfall")
        selected_mode = st.selectbox("Waterfall mode", [r["mode"] for r in results], index=0)
        selected_result = next(r for r in results if r["mode"] == selected_mode)
        st.plotly_chart(process_sankey(selected_result, working_config), width="stretch")
        st.plotly_chart(profit_waterfall(selected_result, working_config), width="stretch")

        st.subheader("Optimization")
        if working_config["optimization"]["enable"]:
            modes_to_optimize = [r["mode"] for r in results]
            opt_rows = []
            for mode in modes_to_optimize:
                opt = optimize_mode(working_config, mode, methane_price)
                opt_rows.append(
                    {
                        "mode": mode,
                        "best_profit_usd_per_day": opt.best_profit_usd_per_day,
                        "success": opt.success,
                        "message": opt.message,
                        "best_variables": opt.best_variables,
                    }
                )
            st.dataframe(pd.DataFrame(opt_rows), width="stretch")
        else:
            st.write("Optimization disabled in config.")

        st.subheader("Sensitivity")
        if working_config["analysis"]["enable_sensitivity"]:
            sens_mode = st.selectbox("Sensitivity mode", [r["mode"] for r in results], index=0)
            sens_rows = run_sensitivity(working_config, sens_mode, methane_price)
            st.plotly_chart(sensitivity_tornado(sens_rows), width="stretch")
            st.dataframe(pd.DataFrame(sens_rows), width="stretch")
        else:
            st.write("Sensitivity disabled in config.")

    with pyro_tab:
        process = pyrolysis_result["process"]
        econ = pyrolysis_result["economics"]
        mass_u = mass_unit_long(working_config)
        energy_u = energy_label(working_config)
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Pyrolysis profit (USD/day)", f"{econ['profit_usd_per_day']:,.0f}")
        p2.metric(f"Biochar output ({mass_u}/day)", f"{process['biochar_tons_per_day']:.2f}")
        p3.metric(f"Bio-oil output ({mass_u}/day)", f"{process['biooil_tons_per_day']:.2f}")
        p4.metric(f"Syngas energy ({energy_u}/day)", f"{energy_to_display(process['syngas_mmbtu_per_day'], working_config):.2f}")

        p5, p6, p7 = st.columns(3)
        p5.metric("Biochar sales (USD/day)", f"{econ['biochar_sales_usd_per_day']:,.0f}")
        p6.metric("Carbon credits (USD/day)", f"{econ['carbon_credits_usd_per_day']:,.0f}")
        p7.metric("Tax credits (USD/day)", f"{econ['production_tax_credits_usd_per_day'] + econ['investment_tax_credits_usd_per_day']:,.0f}")

        st.plotly_chart(pyrolysis_waterfall(pyrolysis_result), width="stretch")
        st.subheader("Pyrolysis economics detail")
        st.dataframe(pd.DataFrame([econ]).T.rename(columns={0: "usd_per_day"}), width="stretch")


if __name__ == "__main__":
    if not st.runtime.exists():
        print("Run this app with: streamlit run app.py")
        raise SystemExit(0)
    run_dashboard()

