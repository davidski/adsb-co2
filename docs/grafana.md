# Grafana dashboard

`grafana/adsb-co2.json.tmpl` is the dashboard with your instance's details replaced by placeholders. Render it locally, then import or provision the result yourself. Nothing here deploys it.

## Render

```sh
uv run python scripts/render_dashboard.py > grafana/adsb-co2.json
```

The script fills in three placeholders from the environment, falling back to `./.env`:

| Placeholder | Variable | Used for |
|---|---|---|
| `${CENTER_LAT}`, `${CENTER_LON}` | `CENTER_LAT`, `CENTER_LON` | centre of the pass drilldown map |
| `${TZ}` | `TZ` (default `UTC`) | date labels in the pass picker |

It checks the coordinates are in range, that `TZ` is a real time zone, and that the output is valid JSON. Grafana's own `${...}` variables are left as they are. `grafana/adsb-co2.json` is git-ignored because it contains your receiver's location; keep it out of the repo.

## Requirements

- A PostgreSQL data source with UID `adsb-co2` pointing at the collector's database. Every panel refers to it by that UID.
- A read-only role for it, such as `grafana_ro`, with its session time zone set to match `TZ` so the hourly and daily views bucket correctly (see the README).
- The dashboard keeps UID `adsb-co2`. The passes table's click-through links to `/d/adsb-co2`; Grafana adds any server subpath itself.

## Changing the dashboard

Edit the template, not a rendered copy. If you edit in the Grafana UI, export the JSON and put the placeholders back before committing: the map centre's `lat`/`lon`, and the time zone in the `pass_id` variable query. Then check nothing instance-specific slipped in, for example with `rg -n 'CENTER_|TZ' grafana/adsb-co2.json.tmpl`.
