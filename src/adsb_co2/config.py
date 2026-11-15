"""Configuration from environment variables only."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    center_lat: float
    center_lon: float
    radius_nm: float = 25.0
    alt_min_ft: float = 0.0
    alt_max_ft: float = 60000.0
    aircraft_json_url: str = "http://ultrafeeder-collector/data/aircraft.json"
    gap_timeout_s: float = 300.0
    store_interval_s: float = 5.0
    publish_interval_s: float = 30.0
    tz: str = "UTC"
    db_host: str = "adsb-co2-db"
    db_port: int = 5432
    db_name: str = "adsb_co2"
    db_user: str = "adsb_co2"
    db_password: str = ""
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    ha_discovery: bool = False
    heartbeat_url: str = ""
    wind: bool = True  # Open-Meteo winds aloft for airspeed; False = groundspeed

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ

        def get(name, default, cast=str):
            return cast(e.get(name) or default)

        for name in ("CENTER_LAT", "CENTER_LON", "DB_PASSWORD"):
            if not e.get(name):
                raise SystemExit(f"missing required env var {name}")
        return cls(
            center_lat=float(e["CENTER_LAT"]),
            center_lon=float(e["CENTER_LON"]),
            radius_nm=get("RADIUS_NM", 25, float),
            alt_min_ft=get("ALT_MIN_FT", 0, float),
            alt_max_ft=get("ALT_MAX_FT", 60000, float),
            aircraft_json_url=get("AIRCRAFT_JSON_URL", cls.aircraft_json_url),
            gap_timeout_s=get("GAP_TIMEOUT_S", 300, float),
            store_interval_s=get("STORE_INTERVAL_S", 5, float),
            publish_interval_s=get("PUBLISH_INTERVAL_S", 30, float),
            tz=get("TZ", "UTC"),
            db_host=get("DB_HOST", cls.db_host),
            db_port=get("DB_PORT", 5432, int),
            db_name=get("DB_NAME", cls.db_name),
            db_user=get("DB_USER", cls.db_user),
            db_password=e["DB_PASSWORD"],
            mqtt_host=get("MQTT_HOST", ""),
            mqtt_port=get("MQTT_PORT", 1883, int),
            mqtt_user=get("MQTT_USER", ""),
            mqtt_password=get("MQTT_PASSWORD", ""),
            ha_discovery=e.get("HA_DISCOVERY", "false").lower() in ("1", "true", "yes"),
            heartbeat_url=get("HEARTBEAT_URL", ""),
            wind=e.get("WIND", "true").lower() in ("1", "true", "yes"),
        )
