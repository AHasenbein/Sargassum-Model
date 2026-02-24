"""SI and US customary unit conversions and display helpers."""

# Conversion constants
KG_PER_SHORT_TON = 907.185
KG_PER_TONNE = 1000.0
MJ_PER_MMBTU = 1055.06  # 1 MMBtu = 1055.06 MJ
GJ_PER_MMBTU = 1.05506  # 1 MMBtu = 1.05506 GJ


def use_si(config: dict) -> bool:
    return bool(config.get("app", {}).get("use_si_units", True))


def kg_per_mass_unit(config: dict) -> float:
    return KG_PER_TONNE if use_si(config) else KG_PER_SHORT_TON


def mass_to_display(value_tons_or_tonnes: float, config: dict) -> float:
    """Convert internal mass (always stored as tonnes when SI) to display value."""
    if use_si(config):
        return value_tons_or_tonnes  # already tonnes
    return value_tons_or_tonnes / 0.907185  # tonnes -> short tons for display


def mass_from_input(value: float, config: dict) -> float:
    """Convert user input to internal tonnes."""
    if use_si(config):
        return value  # input is tonnes
    return value * 0.907185  # short tons -> tonnes


def energy_to_display(mmbtu: float, config: dict) -> float:
    """Convert MMBtu to display: GJ if SI, else MMBtu."""
    if use_si(config):
        return mmbtu * GJ_PER_MMBTU
    return mmbtu


def mass_label(config: dict) -> str:
    return "t" if use_si(config) else "ton"


def mass_unit_long(config: dict) -> str:
    return "tonnes" if use_si(config) else "short tons"


def energy_label(config: dict) -> str:
    return "GJ" if use_si(config) else "MMBtu"


def energy_unit_long(config: dict) -> str:
    return "GJ" if use_si(config) else "MMBtu"
