"""Render grafana/adsb-co2.json.tmpl to stdout with CENTER_LAT, CENTER_LON and TZ.

Values come from the environment, falling back to ./.env. Only these three
placeholders are replaced; Grafana's own ${...} variables are left alone.
"""

import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "grafana" / "adsb-co2.json.tmpl"


def dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {k.strip(): v.strip().strip("\"'") for k, v in pairs if not k.lstrip().startswith("#")}


def render(template: str, env: dict[str, str]) -> str:
    lat, lon = float(env["CENTER_LAT"]), float(env["CENTER_LON"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("CENTER_LAT/CENTER_LON out of range")
    tz = env.get("TZ") or "UTC"
    try:
        ZoneInfo(tz)  # rejects unknown zones and anything that could break the SQL literal
    except (KeyError, ValueError) as e:
        raise ValueError(f"unknown TZ {tz!r}") from e
    out = (
        template.replace("${CENTER_LAT}", repr(lat))
        .replace("${CENTER_LON}", repr(lon))
        .replace("${TZ}", tz)
    )
    json.loads(out)
    return out


def main() -> None:
    env = {**dotenv(Path.cwd() / ".env"), **{k: v for k, v in os.environ.items() if v}}
    try:
        sys.stdout.write(render(TEMPLATE.read_text(), env))
    except KeyError as e:
        sys.exit(f"render_dashboard: {e.args[0]} is not set (environment or .env)")
    except ValueError as e:
        sys.exit(f"render_dashboard: {e}")


if __name__ == "__main__":
    main()
