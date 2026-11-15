"""Fixed fake track through the tracker with a constant-flow model -> known fuel."""

import math

from adsb_co2.config import Config
from adsb_co2.tracker import KM_PER_NM, R_EARTH_KM, Tracker

CFG = Config(center_lat=0.0, center_lon=0.0, radius_nm=25)
R_KM = 25 * KM_PER_NM
SPEED = 0.2  # km/s due east along the equator through the center, 1 Hz fixes
LON_PER_KM = math.degrees(1 / R_EARTH_KM)


class Const:
    def rate_kg_s(self, alt, speed, vs, is_tas=False):
        return 0.5, 1.0, 2.0


def new_model(type_code, category):
    return "openap", "fake", Const()


def row(x_km, hex_="abc123"):
    return {
        "hex": hex_,
        "t": "B738",
        "flight": "TST1 ",
        "lat": 0.0,
        "lon": x_km * LON_PER_KM,
        "alt_baro": 30000,
        "gs": 450,
        "baro_rate": 0,
        "seen_pos": 0.0,
    }


def fly(tracker, t0, x0, x1, skip=range(0)):
    """Fixes from x0 to x1 km, one per second from time t0; returns the closed passes."""
    closed = []
    for s in range(int((x1 - x0) / SPEED) + 1):
        if s not in skip:
            closed += tracker.update(t0 + s, [row(x0 + s * SPEED)])
    return closed


def test_complete_pass_fuel_and_interpolation():
    tr = Tracker(CFG, new_model)
    x0 = -60.0
    (p,) = fly(tr, 1000.0, x0, 60.0)
    t_in = 1000 + (-R_KM - x0) / SPEED
    t_out = 1000 + (R_KM - x0) / SPEED
    assert p.status == "complete" and p.tier == "openap"
    assert abs(p.entered - t_in) < 0.01 and abs(p.last.t - t_out) < 0.01
    assert abs(p.last.lon / LON_PER_KM - R_KM) < 0.01  # exit lies on the circle
    want = t_out - t_in  # 1 kg/s central
    assert abs(p.fuel[1] - want) < 0.01
    assert abs(p.fuel[0] - want / 2) < 0.01 and abs(p.fuel[2] - want * 2) < 0.01
    assert abs(p.distance_km - 2 * R_KM) < 0.01
    assert abs(sum(f for _, f in p.pending) - p.fuel[1]) < 1e-6  # stored increments are exact
    assert p.meta["callsign"] == "TST1"


def test_gap_is_bridged_and_repeat_fixes_ignored():
    tr = Tracker(CFG, new_model)
    (p,) = fly(tr, 0.0, -60.0, 60.0, skip=range(100, 340))  # 240 s gap < 300 s timeout
    assert p.status == "complete" and p.max_gap_s > 240
    assert abs(p.fuel[1] - 2 * R_KM / SPEED) < 0.01  # constant flow: bridging loses nothing
    tr = Tracker(CFG, new_model)
    for i in range(2):  # same position re-served with growing seen_pos
        tr.update(100.0 + i, [{**row(0.0), "seen_pos": float(i)}])
    assert tr.active["abc123"].n_points == 1


def test_gap_timeout_closes_incomplete_and_hex_can_return():
    tr = Tracker(CFG, new_model)
    fly(tr, 0.0, -60.0, 0.0)  # last fix at t=300, at the center
    (p,) = tr.update(601, [])
    assert p.status == "incomplete" and not tr.active
    assert p.last.t == 300 and abs(p.last.lon) < 1e-9  # counted to the last fix only
    assert tr.update(1000, [row(0.0)]) == [] and "abc123" in tr.active  # new pass
