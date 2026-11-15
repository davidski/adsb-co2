# adsb-co2

Estimates CO₂ from aircraft flying within a fixed radius of an ADS-B receiver. It polls a readsb/tar1090 `aircraft.json` at 1 Hz, tracks each aircraft's **pass** through the study area, integrates fuel burned while inside (OpenAP, with fallbacks for types it doesn't cover), and stores per-pass records and 5 s track points in Postgres. It also publishes Home Assistant sensors over MQTT (CO₂ today, CO₂ rate, and the configured radius as a diagnostic) and pings an optional heartbeat URL (any monitor that accepts a GET).

Local in-flight CO₂ only, reported as CO₂ mass (kg), never CO₂-equivalent. Estimates carry low/central/high bounds (mass and airspeed assumptions); the central value is the headline.

## Configuration

Environment variables only; see [`.env.example`](.env.example). `CENTER_LAT`, `CENTER_LON` and `DB_PASSWORD` are required. No receiver coordinates or secrets belong in the repo.

| Variable | Default | |
|---|---|---|
| `AIRCRAFT_JSON_URL` | `http://ultrafeeder-collector/data/aircraft.json` | source feed |
| `RADIUS_NM`, `ALT_MIN_FT`, `ALT_MAX_FT` | `25`, `0`, `60000` | study area (cylinder) |
| `GAP_TIMEOUT_S` | `300` | no fix for this long closes the pass as `incomplete` |
| `STORE_INTERVAL_S` | `5` | track point spacing |
| `PUBLISH_INTERVAL_S` | `30` | MQTT publish spacing |
| `DB_HOST/PORT/NAME/USER/PASSWORD` | `adsb-co2-db`, `5432`, `adsb_co2`, `adsb_co2`, – | Postgres |
| `MQTT_HOST/PORT/USER/PASSWORD` | – | MQTT disabled while `MQTT_HOST` is empty |
| `HA_DISCOVERY` | `false` | publish retained HA discovery configs |
| `HEARTBEAT_URL` | – | push URL, hit every minute while polling and DB writes both work |
| `TZ` | `UTC` | session time zone for "today" and the time-bucket views |
| `WIND` | `true` | fetch winds aloft from [Open-Meteo](https://open-meteo.com) (CC-BY 4.0) hourly to turn groundspeed into airspeed; sends the receiver location rounded to 0.5°. `false` = groundspeed |

## Run

```sh
uv sync
cp .env.example .env   # fill in, then export the variables
uv run adsb-co2 run
uv run adsb-co2 recompute --since 2026-11-01   # re-run stored passes under the current model
docker exec <collector> adsb-co2 recompute     # same, inside the running container
```

The schema (`src/adsb_co2/schema.sql`) is applied idempotently on connect. Passes left `open` by a previous run are closed as `incomplete` on startup. The `co2_hourly`, `co2_daily`, `co2_weekly` and `co2_monthly` views bucket in the session time zone; for Grafana set it on its role: `ALTER ROLE grafana_ro SET timezone = '<TZ>'`. A `grafana_ro` role, if it exists, gets `SELECT` on every connect.

A Grafana dashboard template and the script that renders it for your instance are described in [`docs/grafana.md`](docs/grafana.md).

Image: `ghcr.io/davidski/adsb-co2` (built from `Dockerfile` on push to `main`).

## Development

```sh
uv run ruff check && uv run ruff format --check && uv run pytest
```

`tests/test_tracker.py` is the self-check: a fixed fake track through the pass tracker with a constant flow model gives a known fuel total, with entry/exit interpolation, gap bridging and timeout checks.

OpenAP is pinned and never automerged: a new version changes the numbers, so review the PR and then run `adsb-co2 recompute` deliberately.

## License

MIT
