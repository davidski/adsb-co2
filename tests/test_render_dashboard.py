import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("rd", ROOT / "scripts" / "render_dashboard.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def test_render_fills_placeholders_and_keeps_grafana_vars():
    env = {"CENTER_LAT": "1.5", "CENTER_LON": "-2.25", "TZ": "Europe/Paris"}
    out = rd.render(rd.TEMPLATE.read_text(), env)
    d = json.loads(out)
    geo = next(p for p in d["panels"] if p["type"] == "geomap")
    assert (geo["options"]["view"]["lat"], geo["options"]["view"]["lon"]) == (1.5, -2.25)
    assert "'Europe/Paris'" in out
    assert "${CENTER_" not in out and "${TZ}" not in out
    assert "${__url_time_range}" in out and "${pass_id:raw}" in out


def test_render_rejects_bad_input():
    t = rd.TEMPLATE.read_text()
    with pytest.raises(KeyError):
        rd.render(t, {"CENTER_LON": "0"})
    with pytest.raises(ValueError):
        rd.render(t, {"CENTER_LAT": "0", "CENTER_LON": "0", "TZ": "x'; DROP TABLE passes; --"})
