"""Winds aloft from Open-Meteo (GFS pressure levels) and true airspeed from groundspeed.

A profile is one hour's wind over the area: [(height_ft, u_kt, v_kt), ...] sorted by height,
where (u, v) is the velocity the air moves with, east and north. One point serves the whole
area; the request location is rounded to 0.5 degrees.
"""

import json
import math
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import UTC, date, datetime

from adsb_co2.tracker import Pt

LEVELS_HPA = (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150)
FT_PER_M = 3.28084
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"  # past model runs
MAX_HOUR_GAP_S = 3600  # beyond this from the nearest stored hour, fall back to groundspeed

Profile = list[tuple[float, float, float]]


def _query(lat: float, lon: float) -> dict:
    hourly = ",".join(
        f"{v}_{p}hPa"
        for p in LEVELS_HPA
        for v in ("wind_speed", "wind_direction", "geopotential_height")
    )
    return {
        "latitude": round(lat * 2) / 2,
        "longitude": round(lon * 2) / 2,
        "hourly": hourly,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }


def parse(data: dict) -> dict[int, Profile]:
    """Open-Meteo hourly JSON -> {hour epoch s: profile}; hours with missing levels are dropped."""
    h = data["hourly"]
    out = {}
    for i, t in enumerate(h["time"]):
        prof = []
        for p in LEVELS_HPA:
            z, spd, frm = (
                h[f"{v}_{p}hPa"][i] for v in ("geopotential_height", "wind_speed", "wind_direction")
            )
            if z is None or spd is None or frm is None:
                break
            r = math.radians(frm)  # direction the wind blows from
            prof.append((z * FT_PER_M, -spd * math.sin(r), -spd * math.cos(r)))
        else:
            hour = int(datetime.fromisoformat(t).replace(tzinfo=UTC).timestamp())
            out[hour] = sorted(prof)
    return out


def fetch(
    lat: float,
    lon: float,
    start: date | None = None,
    end: date | None = None,
    timeout: float = 60,
) -> dict[int, Profile]:
    """Yesterday and today from the forecast API, or a past date range from the archive."""
    q = _query(lat, lon)
    if start is None:
        url, q = FORECAST_URL, q | {"past_days": 1, "forecast_days": 1}
    else:
        url, q = (
            ARCHIVE_URL,
            q | {"start_date": start.isoformat(), "end_date": (end or start).isoformat()},
        )
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(q)}", headers={"User-Agent": "adsb-co2"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse(json.load(r))


def wind_at(prof: Profile, alt_ft: float) -> tuple[float, float]:
    """(u, v) kt at an altitude, linear in height, clamped to the top and bottom levels."""
    zs = [z for z, _, _ in prof]
    i = bisect_left(zs, alt_ft)
    if i == 0:
        return prof[0][1:]
    if i == len(prof):
        return prof[-1][1:]
    (z0, u0, v0), (z1, u1, v1) = prof[i - 1], prof[i]
    f = (alt_ft - z0) / (z1 - z0)
    return u0 + f * (u1 - u0), v0 + f * (v1 - v0)


def tas_kt(gs_kt: float, trk_deg: float, u_kt: float, v_kt: float) -> float:
    """Airspeed = |ground velocity - wind velocity|."""
    t = math.radians(trk_deg)
    return math.hypot(gs_kt * math.sin(t) - u_kt, gs_kt * math.cos(t) - v_kt)


class Winds:
    def __init__(self, profiles: dict[int, Profile] | None = None):
        self.profiles: dict[int, Profile] = dict(profiles or {})
        self._hours: list[int] = sorted(self.profiles)

    def update(self, profiles: dict[int, Profile]) -> None:
        self.profiles.update(profiles)
        self._hours = sorted(self.profiles)

    def airspeed(self, pt: Pt) -> tuple[float, bool]:
        """(speed kt, is_tas): model-wind TAS, or groundspeed when track or wind is unknown."""
        if pt.trk is None or not self._hours:
            return pt.gs, False
        i = bisect_left(self._hours, pt.t)
        near = min(self._hours[max(i - 1, 0) : i + 1], key=lambda hr: abs(hr - pt.t))
        if abs(near - pt.t) > MAX_HOUR_GAP_S:
            return pt.gs, False
        return tas_kt(pt.gs, pt.trk, *wind_at(self.profiles[near], pt.alt)), True
