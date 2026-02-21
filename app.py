from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.sargassum_model.config import load_config, save_config
from src.sargassum_model.data_sources import pull_miami_data
from src.sargassum_model.modes import run_mode_bundle
from src.sargassum_model.optimizer import optimize_mode, run_sensitivity
from src.sargassum_model.pyrolysis_model import run_pyrolysis
from src.sargassum_model.visualization import mode_profit_bar, process_sankey, profit_waterfall, sensitivity_tornado


CONFIG_PATH = Path("config/model_config.yaml")


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
    st.sidebar.header("Model controls")
    cfg["project"]["run_mode"] = st.sidebar.selectbox(
        "Operating mode",
        options=["auto_compare", "onsite_energy", "existing_facility"],
        index=["auto_compare", "onsite_energy", "existing_facility"].index(cfg["project"]["run_mode"]),
    )
    cfg["miami_data"]["use_live_data"] = st.sidebar.toggle("Use live Miami data pulls", value=cfg["miami_data"]["use_live_data"])

    st.sidebar.subheader("Feedstock")
    cfg["feedstock"]["wet_tons_per_day"] = st.sidebar.slider("Wet tons/day", 1.0, 1000.0, float(cfg["feedstock"]["wet_tons_per_day"]), 0.5)
    cfg["feedstock"]["moisture_fraction"] = st.sidebar.slider("Initial moisture fraction", 0.40, 0.95, float(cfg["feedstock"]["moisture_fraction"]), 0.01)
    cfg["feedstock"]["delivered_cost_usd_per_wet_ton"] = st.sidebar.slider(
        "Feedstock delivered cost (USD/wet ton)",
        0.0,
        120.0,
        float(cfg["feedstock"]["delivered_cost_usd_per_wet_ton"]),
        1.0,
    )

    st.sidebar.subheader("Process")
    cfg["process"]["drying_target_moisture_fraction"] = st.sidebar.slider(
        "Drying target moisture fraction",
        0.10,
        0.60,
        float(cfg["process"]["drying_target_moisture_fraction"]),
        0.01,
    )
    cfg["process"]["gasification_efficiency_fraction"] = st.sidebar.slider(
        "Gasification efficiency",
        0.30,
        0.90,
        float(cfg["process"]["gasification_efficiency_fraction"]),
        0.01,
    )
    cfg["process"]["syngas_to_methane_efficiency_fraction"] = st.sidebar.slider(
        "Syngas->methane efficiency",
        0.20,
        0.90,
        float(cfg["process"]["syngas_to_methane_efficiency_fraction"]),
        0.01,
    )
    cfg["process"]["parasitic_load_fraction"] = st.sidebar.slider(
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
        "Onsite variable OPEX (USD/wet ton)",
        0.0,
        500.0,
        float(cfg["onsite_energy"]["variable_opex_usd_per_wet_ton"]),
        1.0,
    )

    st.sidebar.subheader("Existing facility economics")
    cfg["existing_facility"]["transport_distance_km"] = st.sidebar.slider(
        "Transport distance (km)",
        1.0,
        300.0,
        float(cfg["existing_facility"]["transport_distance_km"]),
        1.0,
    )
    cfg["existing_facility"]["transport_cost_usd_per_ton_km"] = st.sidebar.slider(
        "Transport cost (USD/ton-km)",
        0.05,
        2.0,
        float(cfg["existing_facility"]["transport_cost_usd_per_ton_km"]),
        0.01,
    )
    cfg["existing_facility"]["tolling_fee_usd_per_wet_ton"] = st.sidebar.slider(
        "Facility tolling fee (USD/wet ton)",
        0.0,
        250.0,
        float(cfg["existing_facility"]["tolling_fee_usd_per_wet_ton"]),
        1.0,
    )
    cfg["existing_facility"]["revenue_share_fraction"] = st.sidebar.slider(
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
    cfg["policy"]["investment_tax_credit_fraction_of_capex"] = st.sidebar.slider(
        "Investment tax credit (% of CAPEX)",
        0.0,
        0.80,
        float(cfg["policy"].get("investment_tax_credit_fraction_of_capex", 0.0)),
        0.01,
    )
    cfg["policy"]["corporate_income_tax_rate_fraction"] = st.sidebar.slider(
        "Corporate income tax rate",
        0.0,
        0.45,
        float(cfg["policy"].get("corporate_income_tax_rate_fraction", 0.21)),
        0.01,
    )
    cfg["policy"]["tax_cut_fraction"] = st.sidebar.slider(
        "Tax cut fraction",
        0.0,
        1.0,
        float(cfg["policy"].get("tax_cut_fraction", 0.0)),
        0.01,
    )
    st.sidebar.subheader("Pyrolysis and biochar")
    cfg["pyrolysis"]["biochar_yield_fraction_of_dry_feed"] = st.sidebar.slider(
        "Biochar yield (fraction of dry feed)",
        0.10,
        0.60,
        float(cfg["pyrolysis"]["biochar_yield_fraction_of_dry_feed"]),
        0.01,
    )
    cfg["pyrolysis"]["biooil_yield_fraction_of_dry_feed"] = st.sidebar.slider(
        "Bio-oil yield (fraction of dry feed)",
        0.05,
        0.50,
        float(cfg["pyrolysis"]["biooil_yield_fraction_of_dry_feed"]),
        0.01,
    )
    cfg["market"]["biochar_price_usd_per_ton"] = st.sidebar.number_input(
        "Biochar sale price (USD/ton)",
        0.0,
        2000.0,
        float(cfg["market"]["biochar_price_usd_per_ton"]),
        10.0,
    )
    cfg["market"]["biooil_price_usd_per_ton"] = st.sidebar.number_input(
        "Bio-oil sale price (USD/ton)",
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

    # Basic-mode guardrails requested by user: keep CAPEX and taxes disabled.
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
    st.title("Sargassum to Methane Model (Miami)")
    st.caption("Interactive gasification + methanation model with expanded techno-economic accounting.")

    config = load_config(CONFIG_PATH)
    if config.get("project", {}).get("conversion_path") != "gasification_methanation":
        st.error("This dashboard is for gasification_methanation. Update project.conversion_path in config.")
        st.stop()
    working_config = sidebar_inputs(config)
    st.sidebar.caption("Live mode: changing any input updates both tabs automatically.")

    if st.sidebar.button("Save current controls to config file"):
        save_config(working_config, CONFIG_PATH)
        st.sidebar.success("Saved to config/model_config.yaml")

    with st.spinner("Pulling Miami data and running model..."):
        bundle = pull_miami_data(working_config, raw_data_dir="data/raw")
        methane_price = float(bundle.methane_price_usd_per_mmbtu)
        results = run_mode_bundle(working_config, methane_price)
        pyrolysis_result = run_pyrolysis(working_config)

    st.info(
        f"Methane price source: {bundle.source_notes['price']} | "
        f"Ambient source: {bundle.source_notes['temperature']} | "
        f"Pulled: {bundle.pulled_at_utc}"
    )
    gas_tab, pyro_tab = st.tabs(["Gasification + Methanation", "Pyrolysis + Biochar"])

    with gas_tab:
        best = results[0]
        proc_cost = processing_cost_usd_per_day(best["economics"])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Best mode", best["mode"])
        c2.metric("Profit (USD/day)", f"{best['economics']['profit_usd_per_day']:,.0f}")
        c3.metric("Methane (MMBtu/day)", f"{best['process']['methane_mmbtu_per_day']:,.1f}")
        c4.metric("Processing cost (USD/day)", f"{proc_cost:,.0f}")

        c5, c6, c7 = st.columns(3)
        c5.metric("Carbon credits (USD/day)", f"{best['economics'].get('carbon_credits_usd_per_day', 0.0):,.0f}")
        c6.metric(
            "Tax credits (USD/day)",
            f"{best['economics'].get('production_tax_credits_usd_per_day', 0.0) + best['economics'].get('investment_tax_credits_usd_per_day', 0.0):,.0f}",
        )
        c7.metric("Income tax (USD/day)", f"{best['economics'].get('income_tax_usd_per_day', 0.0):,.0f}")

        st.plotly_chart(mode_profit_bar(results), width="stretch")
        table_rows = [
            {
                "mode": r["mode"],
                "profit_usd_per_day": r["economics"]["profit_usd_per_day"],
                "profit_usd_per_wet_ton": r["economics"]["profit_usd_per_wet_ton"],
                "methane_mmbtu_per_day": r["process"]["methane_mmbtu_per_day"],
            }
            for r in results
        ]
        st.subheader("Mode comparison table")
        st.dataframe(pd.DataFrame(table_rows), width="stretch")

        st.subheader("Profit waterfall")
        selected_mode = st.selectbox("Waterfall mode", [r["mode"] for r in results], index=0)
        selected_result = next(r for r in results if r["mode"] == selected_mode)
        st.plotly_chart(process_sankey(selected_result), width="stretch")
        st.plotly_chart(profit_waterfall(selected_result), width="stretch")

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
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Pyrolysis profit (USD/day)", f"{econ['profit_usd_per_day']:,.0f}")
        p2.metric("Biochar output (tons/day)", f"{process['biochar_tons_per_day']:.2f}")
        p3.metric("Bio-oil output (tons/day)", f"{process['biooil_tons_per_day']:.2f}")
        p4.metric("Syngas energy (MMBtu/day)", f"{process['syngas_mmbtu_per_day']:.2f}")

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

