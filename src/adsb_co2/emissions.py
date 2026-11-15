"""Per-aircraft fuel flow and CO2: OpenAP where covered, mapped types, flat class rates."""

import csv
import hashlib
import warnings
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from openap.fuel import FuelFlow
from openap.prop import aircraft, available_aircraft

DATA = Path(__file__).parent / "data"
OPENAP_VERSION = version("openap")
CO2_PER_FUEL = 3.16  # kg CO2 per kg jet fuel / avgas

MASS_FRACTIONS = (0.75, 0.80, 1.00)  # of MTOW: low, central, high
# +/- factor on fuel flow for speed error: groundspeed alone carries the full wind;
# model-wind airspeed leaves only the wind model's error
SPEED_BAND_GS = 0.15
SPEED_BAND_TAS = 0.05
CLASS_BAND = 0.30  # tier 3 flat +/-30%


def _read(name: str) -> list[dict]:
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


NATIVE = frozenset(available_aircraft())
TYPE_MAP = {r["type"]: r["maps_to"] for r in _read("type_map.csv")}
RATES_KG_H = {r["class"]: float(r["kg_per_h"]) for r in _read("fuel_rates.csv")}
# ICAO-derived cruise correction for OpenAP types on the generic fuel curve; docs/calibration.md
CALIBRATION = {r["type"]: float(r["factor"]) for r in _read("calibration.csv")}


def model_rev() -> str:
    try:
        pkg = version("adsb-co2")
    except PackageNotFoundError:
        pkg = "dev"
    h = hashlib.sha256()
    for name in ("type_map.csv", "fuel_rates.csv", "calibration.csv"):
        h.update((DATA / name).read_bytes())
    return f"{pkg}+{h.hexdigest()[:8]}"


def resolve(type_code: str | None, category: str | None) -> tuple[str, str | None]:
    """(tier, model_type); tier is openap | mapped | category | unmodeled."""
    t = (type_code or "").strip().upper()
    if t.lower() in NATIVE:
        return "openap", t.lower()
    target = TYPE_MAP.get(t)
    if target in NATIVE:
        return "mapped", target
    # unknown type falls through to the ADS-B category, same as a class-mapped type
    target = target or TYPE_MAP.get(f"cat:{(category or '').strip().upper()}")
    if target in RATES_KG_H:
        return "category", target
    return "unmodeled", None


@lru_cache
def _fuel_flow(model_type: str) -> tuple[FuelFlow, float]:
    # 11 of the 37 native types lack a drag polar; use_synonym borrows a sibling's polar
    # (own mass and engine are kept). See docs/methods.md.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return FuelFlow(model_type, use_synonym=True), aircraft(model_type)["mtow"]


class FlowModel:
    def __init__(self, tier: str, model_type: str | None):
        self.tier, self.model_type = tier, model_type

    def rate_kg_s(
        self, alt_ft: float, speed_kt: float, vs_fpm: float, is_tas: bool = False
    ) -> tuple[float, float, float]:
        """Fuel kg/s as (low, central, high); speed is TAS when is_tas, else groundspeed."""
        if self.tier == "category":
            c = RATES_KG_H[self.model_type] / 3600
            return c * (1 - CLASS_BAND), c, c * (1 + CLASS_BAND)
        if self.tier == "unmodeled":
            return 0.0, 0.0, 0.0
        ff, mtow = _fuel_flow(self.model_type)
        tas = max(speed_kt, 30.0)  # OpenAP overflows to NaN near 0 kt
        alt = max(alt_ft, 0.0)
        k_cal = CALIBRATION.get(self.model_type, 1.0)
        band = SPEED_BAND_TAS if is_tas else SPEED_BAND_GS
        low, mid, high = (
            float(ff.enroute(mtow * m, tas, alt, vs_fpm)) * k * k_cal
            for m, k in zip(MASS_FRACTIONS, (1 - band, 1.0, 1 + band), strict=True)
        )
        return low, mid, high
