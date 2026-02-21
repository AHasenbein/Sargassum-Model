from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import requests


@dataclass
class MiamiDataBundle:
    methane_price_usd_per_mmbtu: float
    avg_temp_c: float
    source_notes: Dict[str, str]
    pulled_at_utc: str


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def fetch_eia_florida_ng_price(fallback_price: float) -> tuple[float, str]:
    """
    Scrapes EIA historical table CSV endpoint for series N3035FL3M.
    If unavailable, returns fallback.
    """
    url = "https://www.eia.gov/dnav/ng/hist_xls/N3035FL3M.xls"
    try:
        # Keep this lightweight and robust without requiring xlrd/openpyxl.
        # We use a simple API fallback endpoint from EIA where possible.
        alt_url = "https://api.eia.gov/v2/natural-gas/pri/sum/data/?frequency=monthly&data[0]=value&facets[stateid][]=FL&facets[process][]=PIN&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=1"
        resp = requests.get(alt_url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("response", {}).get("data", [])
        if not data:
            return fallback_price, "EIA unavailable; using fallback methane price"
        latest = _safe_float(data[0].get("value"), fallback_price)
        return latest, "EIA Florida industrial natural gas price (latest monthly)"
    except requests.RequestException:
        return fallback_price, "EIA unavailable; using fallback methane price"


def fetch_noaa_miami_temp_c(station_id: str, fallback_temp_c: float = 27.0) -> tuple[float, str]:
    """
    NOAA APIs often require tokens depending on endpoint.
    Use open endpoint attempt; fallback if unavailable.
    """
    url = (
        "https://www.ncei.noaa.gov/access/services/data/v1"
        f"?dataset=daily-summaries&stations={station_id}"
        "&startDate=2025-01-01&endDate=2025-12-31"
        "&dataTypes=TAVG&format=json&units=metric"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        vals = []
        for row in rows:
            v = row.get("TAVG")
            if v not in (None, ""):
                vals.append(float(v))
        if not vals:
            return fallback_temp_c, "NOAA returned no TAVG; using fallback ambient temperature"
        avg = sum(vals) / len(vals)
        return avg, "NOAA Miami station daily average temperature"
    except (requests.RequestException, ValueError, TypeError):
        return fallback_temp_c, "NOAA unavailable; using fallback ambient temperature"


def pull_miami_data(config: Dict[str, Any], raw_data_dir: str | Path) -> MiamiDataBundle:
    market = config.get("market", {})
    miami_data = config.get("miami_data", {})
    use_live = bool(miami_data.get("use_live_data", True))

    fallback_price = _safe_float(market.get("fallback_natural_gas_price_usd_per_mmbtu"), 8.0)
    fallback_temp = 27.0

    if use_live:
        methane_price, price_note = fetch_eia_florida_ng_price(fallback_price)
        avg_temp_c, temp_note = fetch_noaa_miami_temp_c(miami_data.get("noaa_station_id", "USW00012839"), fallback_temp)
    else:
        methane_price = fallback_price
        avg_temp_c = fallback_temp
        price_note = "Live EIA pull disabled; using fallback methane price"
        temp_note = "Live NOAA pull disabled; using fallback ambient temperature"

    pulled_at = datetime.now(timezone.utc).isoformat()
    bundle = MiamiDataBundle(
        methane_price_usd_per_mmbtu=methane_price,
        avg_temp_c=avg_temp_c,
        source_notes={"price": price_note, "temperature": temp_note},
        pulled_at_utc=pulled_at,
    )

    raw_path = Path(raw_data_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    output = raw_path / "miami_data_cache.json"
    output.write_text(json.dumps(bundle.__dict__, indent=2), encoding="utf-8")
    return bundle

