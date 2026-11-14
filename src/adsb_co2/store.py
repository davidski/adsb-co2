"""Postgres storage: schema, pass/track-point writes, today's total, recompute."""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from adsb_co2 import emissions
from adsb_co2.config import Config
from adsb_co2.tracker import Pass, Pt

log = logging.getLogger(__name__)
SCHEMA = (Path(__file__).parent / "schema.sql").read_text()
RETRY_S = 10
K = emissions.CO2_PER_FUEL

UPDATE_PASS = """UPDATE passes SET callsign=%s, reg=%s, type=%s, operator=%s, category=%s,
    exited_at=%s, status=%s, distance_km=%s, duration_s=%s, n_points=%s, max_gap_s=%s,
    tier=%s, model_type=%s, openap_version=%s, model_rev=%s,
    fuel_kg=%s, co2_kg=%s, co2_low_kg=%s, co2_high_kg=%s WHERE id=%s"""


def ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


class Store:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.conn: psycopg.Connection | None = None
        self.started = False  # stale open passes are closed once, on the first connect
        self.retry_at = 0.0
        self.model_rev = emissions.model_rev()

    def connect(self, close_stale: bool = False) -> None:
        c = self.cfg
        self.conn = psycopg.connect(
            host=c.db_host,
            port=c.db_port,
            dbname=c.db_name,
            user=c.db_user,
            password=c.db_password,
            connect_timeout=3,
            application_name="adsb-co2",
        )
        self.conn.execute("SELECT set_config('timezone', %s, false)", (c.tz,))
        self.conn.execute(SCHEMA)
        if close_stale:
            n = self.conn.execute(
                "UPDATE passes SET status='incomplete' WHERE status='open'"
            ).rowcount
            log.info("closed %d stale open passes", n)
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
        self.conn = None

    def flush(self, passes: list[Pass]) -> bool:
        """Write pending points and pass rows; False (and retry later) on any DB error."""
        try:
            if self.conn is None:
                if time.monotonic() < self.retry_at:
                    return False
                self.retry_at = time.monotonic() + RETRY_S
                self.connect(close_stale=not self.started)
                self.started = True
            self._write(passes)
            return True
        except psycopg.Error as e:
            log.warning("db unavailable: %s", e)
            self.close()
            return False

    def _write(self, passes: list[Pass]) -> None:
        written = []
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.execute("SELECT 1")  # liveness even when nothing is pending
            for p in passes:
                if not p.pending and p.status == p.synced_status:
                    continue
                pid = p.db_id
                if pid is None:
                    pid = cur.execute(
                        "INSERT INTO passes (hex, entered_at, status) VALUES (%s, %s, %s)"
                        " RETURNING id",
                        (p.meta["hex"], ts(p.entered), p.status),
                    ).fetchone()[0]
                written.append((p, pid))
                m = p.meta
                low, mid, high = (f * K for f in p.fuel)
                last = p.pending[-1][0].t if p.pending else p.stored_t
                cur.execute(
                    UPDATE_PASS,
                    (
                        m["callsign"],
                        m["reg"],
                        m["type"],
                        m["operator"],
                        m["category"],
                        ts(last),
                        p.status,
                        p.distance_km,
                        round(last - p.entered),
                        p.n_points,
                        round(p.max_gap_s),
                        p.tier,
                        p.model_type,
                        emissions.OPENAP_VERSION,
                        self.model_rev,
                        p.fuel[1],
                        mid,
                        low,
                        high,
                        pid,
                    ),
                )
                cur.executemany(
                    "INSERT INTO track_points VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (pid, ts(pt.t), pt.lat, pt.lon, round(pt.alt), pt.gs, round(pt.vs), f * K)
                        for pt, f in p.pending
                    ],
                )
        for p, pid in written:
            p.db_id, p.synced_status = pid, p.status
            p.pending.clear()

    def today_kg(self) -> float:
        return self.conn.execute(
            "SELECT coalesce(sum(co2_kg), 0) FROM track_points WHERE ts >= date_trunc('day', now())"
        ).fetchone()[0]

    def recompute(self, since: datetime | None) -> int:
        """Re-run stored passes from their track points under the current model."""
        self.connect()
        passes = self.conn.execute(
            "SELECT id, type, category FROM passes WHERE status <> 'open' AND entered_at >= %s"
            " ORDER BY id",
            (since or datetime.min.replace(tzinfo=UTC),),
        ).fetchall()
        for pid, type_code, category in passes:
            tier, model_type = emissions.resolve(type_code, category)
            p = Pass({}, tier, model_type, emissions.FlowModel(tier, model_type), 0)
            rows = self.conn.execute(
                "SELECT ts, lat, lon, alt_ft, gs_kt, vs_fpm FROM track_points"
                " WHERE pass_id=%s ORDER BY ts",
                (pid,),
            ).fetchall()
            for t, lat, lon, alt, gs, vs in rows:
                p.add(Pt(t.timestamp(), lat, lon, alt, gs, vs))
            if len(p.pending) != len(rows):
                raise RuntimeError(f"pass {pid}: {len(rows)} points, {len(p.pending)} stored")
            with self.conn.transaction(), self.conn.cursor() as cur:
                cur.executemany(
                    "UPDATE track_points SET co2_kg=%s WHERE pass_id=%s AND ts=%s",
                    [(f * K, pid, r[0]) for (_, f), r in zip(p.pending, rows, strict=True)],
                )
                cur.execute(
                    "UPDATE passes SET tier=%s, model_type=%s, openap_version=%s, model_rev=%s,"
                    " fuel_kg=%s, co2_kg=%s, co2_low_kg=%s, co2_high_kg=%s WHERE id=%s",
                    (
                        tier,
                        model_type,
                        emissions.OPENAP_VERSION,
                        self.model_rev,
                        p.fuel[1],
                        p.fuel[1] * K,
                        p.fuel[0] * K,
                        p.fuel[2] * K,
                        pid,
                    ),
                )
        return len(passes)
