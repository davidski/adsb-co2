"""Pass tracking: aircraft.json rows in, passes out. No I/O, no emissions import.

Fuel is integrated here; the store turns fuel into CO2.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from adsb_co2.config import Config

R_EARTH_KM = 6371.0088
KM_PER_NM = 1.852
ENTRY_LOOKBACK_S = 60  # last outside fix older than this is not used for entry interpolation
MAX_SEEN_POS_S = 2
DEDUPE_S = 0.25  # position timestamps are 0.1 s resolution; closer than this is a repeat


@dataclass
class Pt:
    t: float
    lat: float
    lon: float
    alt: float
    gs: float
    vs: float
    trk: float | None = None  # true track over ground, degrees


def groundspeed(pt: Pt) -> tuple[float, bool]:
    """Default airspeed source: (speed kt, is_tas)."""
    return pt.gs, False


def haversine_km(a: Pt, b: Pt) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    h = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.lon - a.lon) / 2) ** 2
    )
    return 2 * R_EARTH_KM * math.asin(math.sqrt(h))


def bearing_deg(a: Pt, b: Pt) -> float:
    p1, p2, dl = math.radians(a.lat), math.radians(b.lat), math.radians(b.lon - a.lon)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def lerp(a: Pt, b: Pt, f: float) -> Pt:
    fields = ("t", "lat", "lon", "alt", "gs", "vs")
    # track is an angle: interpolating 359 -> 1 linearly is wrong, so take the later fix's
    return Pt(*(getattr(a, k) + f * (getattr(b, k) - getattr(a, k)) for k in fields), trk=b.trk)


@dataclass
class Pass:
    meta: dict  # hex, callsign, reg, type, operator, category
    tier: str
    model_type: str | None
    model: object  # FlowModel-like: rate_kg_s(alt_ft, speed_kt, vs_fpm, is_tas) -> (low, mid, high)
    store_interval: float
    airspeed: Callable[[Pt], tuple[float, bool]] = groundspeed
    status: str = "open"
    fuel: list = field(default_factory=lambda: [0.0, 0.0, 0.0])  # low, central, high kg
    distance_km: float = 0.0
    n_points: int = 0
    max_gap_s: float = 0.0
    entered: float | None = None
    last: Pt | None = None
    rates: tuple = (0.0, 0.0, 0.0)  # kg/s at `last`
    pending: list = field(default_factory=list)  # (Pt, central fuel kg since previous stored point)
    stored_t: float = -math.inf
    stored_fuel: float = 0.0
    db_id: int | None = None  # set by the store
    synced_status: str | None = None

    def add(self, pt: Pt, fix: bool = True) -> None:
        """Integrate to `pt` (trapezoid = linear flow across gaps); store a point when due."""
        if self.last and pt.t <= self.last.t:
            return
        if pt.trk is None and self.last and haversine_km(self.last, pt) > 0:
            pt.trk = bearing_deg(self.last, pt)
        speed, is_tas = self.airspeed(pt)
        rates = self.model.rate_kg_s(pt.alt, speed, pt.vs, is_tas)
        if self.last:
            dt = pt.t - self.last.t
            self.max_gap_s = max(self.max_gap_s, dt)
            self.distance_km += haversine_km(self.last, pt)
            for i in range(3):
                self.fuel[i] += 0.5 * (self.rates[i] + rates[i]) * dt
        else:
            self.entered = pt.t
        self.last, self.rates = pt, rates
        self.n_points += fix
        if pt.t - self.stored_t >= self.store_interval:
            self._store()

    def _store(self) -> None:
        self.pending.append((self.last, self.fuel[1] - self.stored_fuel))
        self.stored_t, self.stored_fuel = self.last.t, self.fuel[1]

    def close(self, status: str) -> "Pass":
        if self.stored_t < self.last.t:
            self._store()  # remaining fuel rides on the final point
        self.status = status
        return self


class Tracker:
    def __init__(
        self,
        cfg: Config,
        new_model: Callable[[str | None, str | None], tuple],
        airspeed: Callable[[Pt], tuple[float, bool]] = groundspeed,
    ):
        """new_model(type, category) -> (tier, model_type, model); airspeed(pt) -> (kt, is_tas)."""
        self.cfg, self.new_model, self.airspeed = cfg, new_model, airspeed
        self.center = Pt(0, cfg.center_lat, cfg.center_lon, 0, 0, 0)
        self.r_km = cfg.radius_nm * KM_PER_NM
        self.active: dict[str, Pass] = {}
        self.last: dict[str, tuple[Pt, bool]] = {}  # hex -> (last accepted fix, was inside)

    def _parse(self, now: float, ac: dict) -> Pt | None:
        seen, alt, gs = ac.get("seen_pos"), ac.get("alt_baro"), ac.get("gs")
        lat, lon = ac.get("lat"), ac.get("lon")
        if seen is None or seen > MAX_SEEN_POS_S or lat is None or lon is None or gs is None:
            return None
        if not isinstance(alt, int | float):  # "ground" or missing
            return None
        vs = ac.get("baro_rate") or ac.get("geom_rate") or 0
        trk = ac.get("track")
        return Pt(now - seen, lat, lon, alt, gs, vs, trk if isinstance(trk, int | float) else None)

    def inside(self, pt: Pt) -> bool:
        c = self.cfg
        return haversine_km(self.center, pt) <= self.r_km and c.alt_min_ft <= pt.alt <= c.alt_max_ft

    def _xy(self, pt: Pt) -> tuple[float, float]:
        k = math.radians(1) * R_EARTH_KM
        return (
            (pt.lon - self.center.lon) * math.cos(math.radians(self.center.lat)) * k,
            (pt.lat - self.center.lat) * k,
        )

    def _crossing(self, a: Pt, b: Pt, entering: bool) -> float:
        """Fraction along a->b where the path crosses the boundary of the area.

        Radius solved exactly on a local flat projection; altitude limits linearly.
        Exit takes the earliest crossing, entry the latest.
        """
        ts = []
        (ax, ay), (bx, by) = self._xy(a), self._xy(b)
        dx, dy = bx - ax, by - ay
        A, B, C = dx * dx + dy * dy, ax * dx + ay * dy, ax * ax + ay * ay - self.r_km**2
        if (C <= 0) != (C + 2 * B + A <= 0) and A > 0:
            disc = math.sqrt(max(B * B - A * C, 0.0))
            ts += [t for t in ((-B - disc) / A, (-B + disc) / A) if 0 <= t <= 1][:1]
        c = self.cfg
        for sa, sb in (
            (a.alt - c.alt_min_ft, b.alt - c.alt_min_ft),
            (c.alt_max_ft - a.alt, c.alt_max_ft - b.alt),
        ):
            if (sa >= 0) != (sb >= 0):
                ts.append(sa / (sa - sb))
        if not ts:
            return 1.0 if entering else 0.0
        return max(ts) if entering else min(ts)

    def update(self, now: float, aircraft: list[dict]) -> list[Pass]:
        """Feed one poll (`now` = file timestamp); returns the passes that closed."""
        closed = []
        for hex_, p in list(self.active.items()):
            if now - p.last.t > self.cfg.gap_timeout_s:
                closed.append(p.close("incomplete"))
                del self.active[hex_]
        for ac in aircraft:
            hex_ = ac.get("hex")
            pt = self._parse(now, ac)
            if not hex_ or pt is None:
                continue
            prev = self.last.get(hex_)
            if prev and pt.t <= prev[0].t + DEDUPE_S:
                continue
            inside = self.inside(pt)
            self.last[hex_] = (pt, inside)
            p = self.active.get(hex_)
            meta = {
                "hex": hex_,
                "callsign": (ac.get("flight") or "").strip() or None,
                "reg": ac.get("r"),
                "type": ac.get("t"),
                "operator": ac.get("ownOp"),
                "category": ac.get("category"),
            }
            if p and inside:
                p.add(pt)
            elif p:
                p.add(lerp(p.last, pt, self._crossing(p.last, pt, entering=False)), fix=False)
                closed.append(p.close("complete"))
                del self.active[hex_]
            elif inside:
                tier, model_type, model = self.new_model(meta["type"], meta["category"])
                p = Pass(meta, tier, model_type, model, self.cfg.store_interval_s, self.airspeed)
                if prev and not prev[1] and pt.t - prev[0].t <= ENTRY_LOOKBACK_S:
                    p.add(lerp(prev[0], pt, self._crossing(prev[0], pt, entering=True)), fix=False)
                p.add(pt)
                self.active[hex_] = p
            if p:  # callsign etc. often arrive after the first fix
                for k, v in meta.items():
                    if v and not p.meta.get(k):
                        p.meta[k] = v
        for hex_ in [h for h, (pt, _) in self.last.items() if now - pt.t > ENTRY_LOOKBACK_S]:
            if hex_ not in self.active:
                del self.last[hex_]
        return closed
