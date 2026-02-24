from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go

from .units import energy_to_display, energy_label, mass_label


def mode_profit_bar(results: List[Dict[str, Any]], config: Optional[Dict[str, Any]] = None) -> go.Figure:
    config = config or {}
    df = pd.DataFrame(
        [
            {
                "mode": r["mode"],
                "profit_usd_per_day": r["economics"]["profit_usd_per_day"],
                "methane": energy_to_display(r["process"]["methane_mmbtu_per_day"], config),
            }
            for r in results
        ]
    )
    fig = go.Figure()
    fig.add_bar(x=df["mode"], y=df["profit_usd_per_day"], name="Profit (USD/day)")
    fig.update_layout(title="Mode Comparison: Daily Profit", yaxis_title="USD/day")
    return fig


def profit_waterfall(result: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> go.Figure:
    config = config or {}
    econ = result["economics"]
    revenue_items = [
        ("Methane sales", "methane_sales_usd_per_day"),
        ("Renewable premium", "renewable_premium_usd_per_day"),
        ("Carbon credits", "carbon_credits_usd_per_day"),
        ("Production tax credits", "production_tax_credits_usd_per_day"),
        ("Investment tax credits", "investment_tax_credits_usd_per_day"),
        ("Tax cut savings", "tax_cut_savings_usd_per_day"),
        ("Char sales", "char_sales_usd_per_day"),
        ("Avoided disposal", "avoided_disposal_usd_per_day"),
    ]
    cost_items = [
        ("Feedstock", "feedstock_cost_usd_per_day"),
        ("Transport", "transport_usd_per_day"),
        ("Tolling", "tolling_usd_per_day"),
        ("Transfer station", "transfer_station_usd_per_day"),
        ("Fixed OPEX", "fixed_opex_usd_per_day"),
        ("Variable OPEX", "variable_opex_usd_per_day"),
        ("Labor", "labor_usd_per_day"),
        ("Maintenance", "maintenance_usd_per_day"),
        ("Insurance", "insurance_usd_per_day"),
        ("Admin", "admin_overhead_usd_per_day"),
        ("Catalyst+chemicals", "catalyst_chemicals_usd_per_day"),
        ("Electricity", "electricity_usd_per_day"),
        ("Drying thermal", "drying_thermal_usd_per_day"),
        ("Water", "water_usd_per_day"),
        ("Ash disposal", "ash_disposal_usd_per_day"),
        ("CAPEX charge", "annualized_capex_usd_per_day"),
        ("Financing", "financing_usd_per_day"),
        ("Income tax", "income_tax_usd_per_day"),
    ]

    labels: list[str] = []
    measures: list[str] = []
    values: list[float] = []

    for label, key in revenue_items:
        value = float(econ.get(key, 0.0))
        if abs(value) > 1e-9:
            labels.append(label)
            measures.append("relative")
            values.append(value)
    for label, key in cost_items:
        value = float(econ.get(key, 0.0))
        if abs(value) > 1e-9:
            labels.append(label)
            measures.append("relative")
            values.append(-value)
    labels.append("Net profit")
    measures.append("total")
    values.append(float(econ["profit_usd_per_day"]))

    fig = go.Figure(
        go.Waterfall(
            x=labels,
            measure=measures,
            y=values,
            connector={"line": {"color": "rgb(110,110,110)"}},
        )
    )
    fig.update_layout(title=f"Profit Waterfall ({result['mode']})", yaxis_title="USD/day")
    return fig


def sensitivity_tornado(sensitivity_rows: List[Dict[str, float | str]]) -> go.Figure:
    if not sensitivity_rows:
        return go.Figure()
    df = pd.DataFrame(sensitivity_rows)
    df = df.sort_values("swing_usd_per_day", key=lambda s: s.abs())
    fig = go.Figure()
    fig.add_bar(
        x=df["swing_usd_per_day"],
        y=df["variable"],
        orientation="h",
        name="Profit swing",
    )
    fig.update_layout(title="Sensitivity (High-Low Profit Swing)", xaxis_title="USD/day", yaxis_title="")
    return fig


def process_sankey(result: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> go.Figure:
    config = config or {}
    process = result["process"]
    wet_in = process["wet_tons_per_day"]
    dry = process["dry_tons_per_day"]
    methane_raw = max(process["methane_mmbtu_per_day"], 0.0)
    methane = energy_to_display(methane_raw, config)
    losses_raw = max(process["gross_energy_mmbtu_per_day"] - process["methane_mmbtu_per_day"], 0.0)
    losses = energy_to_display(losses_raw, config) if losses_raw > 0 else 0.001
    mass_u = mass_label(config)
    energy_u = energy_label(config)
    fig = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=15,
                    thickness=18,
                    label=[
                        f"Wet sargassum input ({mass_u}/day)",
                        f"Dry solids ({mass_u}/day)",
                        f"Converted methane energy ({energy_u}/day)",
                        f"Parasitic and conversion losses ({energy_u}/day)",
                    ],
                ),
                link=dict(
                    source=[0, 1, 1],
                    target=[1, 2, 3],
                    value=[wet_in, methane, losses if losses > 0.001 else 0.001],
                ),
            )
        ]
    )
    fig.update_layout(title=f"Process Flow Visual ({result['mode']})")
    return fig

