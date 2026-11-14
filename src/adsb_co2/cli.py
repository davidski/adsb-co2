"""adsb-co2 run | recompute [--since ISO8601]."""

import argparse
import json
import logging
import signal
import time
import urllib.request
from datetime import datetime
from functools import cache

from adsb_co2 import emissions
from adsb_co2.config import Config
from adsb_co2.publish import Mqtt, heartbeat
from adsb_co2.store import Store
from adsb_co2.tracker import Tracker

log = logging.getLogger("adsb_co2")
MAX_FILE_AGE_S = 10  # older aircraft.json means readsb has stalled
HEARTBEAT_EVERY_S = 60


@cache
def _flow_model(tier: str, model_type: str | None) -> emissions.FlowModel:
    return emissions.FlowModel(tier, model_type)


def new_model(type_code: str | None, category: str | None) -> tuple:
    tier, model_type = emissions.resolve(type_code, category)
    return tier, model_type, _flow_model(tier, model_type)


def poll(url: str, wall: float) -> tuple[float, list[dict], bool]:
    """(now, aircraft, ok). On failure or a stale file: wall clock and no aircraft."""
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            data = json.load(r)
        if abs(wall - data["now"]) <= MAX_FILE_AGE_S:
            return data["now"], data["aircraft"], True
        log.warning("aircraft.json is %.0fs old", wall - data["now"])
    except (OSError, ValueError, KeyError) as e:
        log.warning("poll failed: %s", e)
    return wall, [], False


def run(cfg: Config) -> None:
    store, tracker = Store(cfg), Tracker(cfg, new_model)
    mqtt = Mqtt(cfg) if cfg.mqtt_host else None
    stop = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.append(1))
    closed, next_tick = [], time.monotonic()
    next_heartbeat = next_publish = next_tick
    while not stop:
        now, rows, poll_ok = poll(cfg.aircraft_json_url, time.time())
        closed += tracker.update(now, rows)
        db_ok = store.flush([*tracker.active.values(), *closed])
        if db_ok:
            closed.clear()
        mono = time.monotonic()
        if cfg.heartbeat_url and mono >= next_heartbeat:
            next_heartbeat = mono + HEARTBEAT_EVERY_S
            if poll_ok and db_ok:
                heartbeat(cfg.heartbeat_url)
        if mqtt and mono >= next_publish:
            next_publish = mono + cfg.publish_interval_s
            rate = sum(p.rates[1] for p in tracker.active.values())
            values = {
                "adsb_aircraft_in_area": len(tracker.active),
                "adsb_co2_rate_kg_h": rate * emissions.CO2_PER_FUEL * 3600,
            }
            if db_ok:
                try:
                    values["adsb_co2_today_kg"] = store.today_kg()
                except Exception as e:  # noqa: BLE001 - a failed read must not stop the loop
                    log.warning("today total failed: %s", e)
                    store.close()
            mqtt.publish(values)
        next_tick += 1
        time.sleep(max(0.0, next_tick - time.monotonic()))
        if time.monotonic() - next_tick > 5:  # fell behind (long DB stall): don't burst
            next_tick = time.monotonic()
    log.info("stopping")
    store.flush([*tracker.active.values(), *closed])
    if mqtt:
        mqtt.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="adsb-co2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="poll, track passes, store, publish")
    rc = sub.add_parser("recompute", help="re-run stored passes under the current model")
    rc.add_argument("--since", type=datetime.fromisoformat, help="only passes entered since")
    args = ap.parse_args()
    cfg = Config.from_env()
    if args.cmd == "run":
        run(cfg)
    else:
        n = Store(cfg).recompute(args.since)
        log.info("recomputed %d passes", n)
