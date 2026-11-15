"""Winds aloft -> airspeed, and its use by the tracker and flow model."""

import math
from datetime import UTC, datetime

from test_tracker import CFG, fly

from adsb_co2 import emissions as e
from adsb_co2 import wind
from adsb_co2.tracker import Pt, Tracker

H0 = int(datetime(2026, 11, 14, tzinfo=UTC).timestamp())


def om(hours, speed=40.0, frm=270.0):
    """Open-Meteo-shaped hourly JSON: uniform wind, 1000 ft per level."""
    h = {"time": hours}
    for i, p in enumerate(wind.LEVELS_HPA):
        h[f"wind_speed_{p}hPa"] = [speed] * len(hours)
        h[f"wind_direction_{p}hPa"] = [frm] * len(hours)
        h[f"geopotential_height_{p}hPa"] = [i * 1000 / wind.FT_PER_M] * len(hours)
    return {"hourly": h}


def test_parse_profiles():
    data = om(["2026-11-14T00:00", "2026-11-14T01:00"])
    data["hourly"]["wind_speed_250hPa"][1] = None  # incomplete hour is dropped
    prof = wind.parse(data)
    assert list(prof) == [H0]
    z, u, v = prof[H0][0]
    assert abs(u - 40) < 1e-9 and abs(v) < 1e-9  # from the west = air moving east
    assert [p[0] for p in prof[H0]] == sorted(p[0] for p in prof[H0])


def test_wind_at_and_tas():
    prof = [(0.0, 0.0, 0.0), (10000.0, 20.0, -10.0)]
    assert wind.wind_at(prof, 5000) == (10.0, -5.0)
    assert wind.wind_at(prof, -100) == (0.0, 0.0) and wind.wind_at(prof, 40000) == (20.0, -10.0)
    assert abs(wind.tas_kt(490, 90, 40, 0) - 450) < 1e-9  # tailwind
    assert abs(wind.tas_kt(410, 270, 40, 0) - 450) < 1e-9  # headwind
    assert abs(wind.tas_kt(450, 0, 40, 0) - math.hypot(450, 40)) < 1e-9  # crosswind


def test_winds_airspeed_falls_back_to_groundspeed():
    w = wind.Winds(wind.parse(om(["2026-11-14T00:00"])))
    pt = Pt(H0 + 600, 0, 0, 5000, 490, 0, 90.0)
    assert w.airspeed(pt) == (wind.tas_kt(490, 90, 40, 0), True)
    assert w.airspeed(Pt(H0, 0, 0, 5000, 490, 0)) == (490, False)  # no track
    assert w.airspeed(Pt(H0 + 7200, 0, 0, 5000, 490, 0, 90.0)) == (490, False)  # no hour near
    assert wind.Winds().airspeed(pt) == (490, False)


def test_tracker_feeds_airspeed_to_model():
    seen = []

    class Rec:
        def rate_kg_s(self, alt, speed, vs, is_tas=False):
            seen.append((round(speed, 6), is_tas))
            return 0.5, 1.0, 2.0

    w = wind.Winds({h: wind.parse(om(["2026-11-14T00:00"]))[H0] for h in (0, 3600)})
    tr = Tracker(CFG, lambda t, c: ("openap", "fake", Rec()), w.airspeed)
    (p,) = fly(tr, 0.0, -60.0, 60.0)  # due east at 450 kt, no track field: derived
    assert seen[0] == (450, False)  # entry point: no previous fix, no track
    assert set(seen[1:]) == {(410, True)}  # 40 kt tailwind removed
    assert p.last.trk is not None and abs(p.last.trk - 90) < 1e-6


def test_flow_model_band_narrows_with_airspeed():
    m = e.FlowModel("openap", "a320")
    gs_low, gs_mid, gs_high = m.rate_kg_s(35000, 450, 0)
    tas_low, tas_mid, tas_high = m.rate_kg_s(35000, 450, 0, is_tas=True)
    assert tas_mid == gs_mid
    assert abs((gs_high / gs_mid) / (tas_high / tas_mid) - 1.15 / 1.05) < 1e-9
    assert tas_low > gs_low and tas_high < gs_high
