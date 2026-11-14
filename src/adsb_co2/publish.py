"""Outbound notifications: MQTT (Home Assistant sensors) and the heartbeat."""

import json
import logging
import urllib.request

import paho.mqtt.client as mqtt

from adsb_co2.config import Config

log = logging.getLogger(__name__)
STATUS_TOPIC = "adsb_co2/status"  # LWT availability
SENSORS = {
    "adsb_co2_today_kg": {
        "name": "ADS-B CO2 today",
        "unit_of_measurement": "kg",
        "state_class": "total_increasing",
        "icon": "mdi:molecule-co2",
    },
    "adsb_aircraft_in_area": {
        "name": "ADS-B aircraft in area",
        "state_class": "measurement",
        "icon": "mdi:airplane",
    },
    "adsb_co2_rate_kg_h": {
        "name": "ADS-B CO2 rate",
        "unit_of_measurement": "kg/h",
        "state_class": "measurement",
        "icon": "mdi:molecule-co2",
    },
}


class Mqtt:
    def __init__(self, cfg: Config):
        self.discovery = cfg.ha_discovery
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="adsb-co2")
        if cfg.mqtt_user:
            self.client.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect_async(cfg.mqtt_host, cfg.mqtt_port)
        self.client.loop_start()  # reconnects on its own; a dead broker never blocks the poller

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("mqtt connect refused: %s", reason_code)
            return
        client.publish(STATUS_TOPIC, "online", retain=True)
        if self.discovery:
            client.subscribe("homeassistant/status")
            self._discover()

    def _on_message(self, client, userdata, msg):
        if msg.payload == b"online":  # Home Assistant restarted
            self._discover()

    def _discover(self):
        for key, sensor in SENSORS.items():
            config = {
                **sensor,
                "unique_id": key,
                "default_entity_id": f"sensor.{key}",
                "state_topic": f"adsb_co2/{key}/state",
                "availability_topic": STATUS_TOPIC,
                "device": {"identifiers": ["adsb_co2"], "name": "ADS-B CO2"},
            }
            topic = f"homeassistant/sensor/{key}/config"
            self.client.publish(topic, json.dumps(config), retain=True)

    def publish(self, values: dict[str, float]) -> None:
        for key, value in values.items():
            self.client.publish(f"adsb_co2/{key}/state", f"{value:.2f}")

    def stop(self) -> None:
        self.client.publish(STATUS_TOPIC, "offline", retain=True).wait_for_publish(2)
        self.client.loop_stop()


def heartbeat(url: str) -> None:
    try:
        urllib.request.urlopen(url, timeout=3).close()
    except OSError as e:
        log.warning("heartbeat failed: %s", e)
