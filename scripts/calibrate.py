"""Per-type cruise fuel calibration of OpenAP against the ICAO fuel consumption table.

usage: uv run python scripts/calibrate.py icao.txt > src/adsb_co2/data/calibration.csv

The text is `pdftotext -layout` of the ICAO Carbon Emissions Calculator Methodology
(v13.1, Aug 2024), Appendix C. For each OpenAP type, ICAO's marginal fuel per nm over a
cruise-dominated stage range is turned into kg/h at the type's cruise Mach and height,
then divided by OpenAP's flow at the same condition and our central mass. See
docs/calibration.md.
"""

import csv
import re
import sys
import warnings
from pathlib import Path

import openap
from openap import aero
from openap.prop import aircraft, available_aircraft

from adsb_co2.emissions import BOUNDS, _fuel_flow

DIST_NM = [125, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]

# OpenAP type -> ICAO equivalent aircraft code; None = no ICAO row, left uncalibrated
ICAO_CODE = {
    "a19n": "31N", "a20n": "32N", "a21n": "32Q", "a318": "318", "a319": "319",
    "a320": "320", "a321": "321", "a332": "332", "a333": "333", "a343": "343",
    "a359": "359", "a388": "388", "b37m": "7M8", "b38m": "7M8", "b39m": "7M9",
    "b3xm": "7M9", "b734": "734", "b737": "73G", "b738": "738", "b739": "739",
    "b744": "744", "b748": "74H", "b752": "752", "b763": "763", "b772": "772",
    "b773": "773", "b77w": "77W", "b788": "788", "b789": "789", "c550": "CNJ",
    "crj9": "CR9", "e145": "ER4", "e170": "E70", "e190": "E90", "e195": "E95",
    "e75l": "E75", "glf6": None,
}  # fmt: skip

# ICAO's generic Citation row is a doubtful match for a Citation II; other bizjets map to c550
UNTRUSTED = {"c550"}


def fitted_types() -> set[str]:
    """Types with their own OpenAP fuel curve; the rest use the scaled default curve."""
    path = Path(openap.__file__).parent / "data" / "fuel" / "fuel_models.csv"
    with open(path, newline="") as f:
        return {r["typecode"].lower() for r in csv.DictReader(f)}


def icao_rows(path: str) -> dict[str, dict[int, int]]:
    rows: dict[str, dict[int, int]] = {}
    for line in open(path):
        m = re.match(r"\s*([0-9A-Z]{3})\s+((?:\d+\s+){3,}\d+)\s*$", line)
        if m and m[1] not in rows:
            # rows stop at the type's range; columns past 5000 nm are unused
            rows[m[1]] = dict(zip(DIST_NM, map(int, m[2].split()), strict=False))
    return rows


def stage(fuel: dict[int, int], mtow: float) -> tuple[int, int]:
    """Cruise-dominated stage range: long for widebodies, else the longest pair available."""
    pairs = [(2000, 4000)] if mtow > 150_000 else []
    pairs += [(1000, 2000), (750, 1500), (500, 1000)]
    return next((a, b) for a, b in pairs if a in fuel and b in fuel)


def main() -> None:
    rows = icao_rows(sys.argv[1])
    fitted = fitted_types()
    central_mass = BOUNDS[1][0]
    out = csv.writer(sys.stdout, lineterminator="\n")
    header = ["type", "curve", "icao", "stage_nm", "icao_kg_h", "openap_kg_h", "ratio", "factor"]
    out.writerow(header)
    for t in sorted(available_aircraft()):
        code, curve = ICAO_CODE[t], "fitted" if t in fitted else "generic"
        if code is None or code not in rows:
            out.writerow([t, curve, code or "", "", "", "", "", "1.000"])
            continue
        a = aircraft(t)
        h_m, mach = a["cruise"]["height"], a["cruise"]["mach"]
        tas_kt = aero.mach2tas(mach, h_m) / aero.kts
        a_nm, b_nm = stage(rows[code], a["mtow"])
        icao = (rows[code][b_nm] - rows[code][a_nm]) / (b_nm - a_nm) * tas_kt
        ff, mtow = _fuel_flow(t)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            oap = float(ff.enroute(mtow * central_mass, tas_kt, h_m / aero.ft, 0)) * 3600
        ratio = icao / oap
        # only generic curves are corrected; fitted ones already agree within ~10%
        factor = ratio if curve == "generic" and t not in UNTRUSTED else 1.0
        stage_nm = f"{a_nm}-{b_nm}"
        out.writerow(
            [t, curve, code, stage_nm, round(icao), round(oap), f"{ratio:.3f}", f"{factor:.3f}"]
        )


if __name__ == "__main__":
    main()
