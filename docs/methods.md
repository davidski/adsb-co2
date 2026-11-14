# Methods

Local in-flight CO₂ from aircraft inside a fixed radius of the receiver. Reported quantity is CO₂ mass (kg, t), never CO₂-equivalent. Local and full-flight numbers are never summed.

## Method

Per 1 Hz step inside the study area: `fuel_kg += ff × dt`, `co2_kg = 3.16 × fuel_kg` (`CO2_PER_FUEL`, kg CO₂ per kg fuel).

### Type resolution (stored per pass as `tier`, `model_type`)

| Tier | Source | Fuel flow |
|---|---|---|
| 1 `openap` | ICAO type is one of OpenAP 2.6.2's 37 aircraft | `FuelFlow.enroute(mass, tas=gs, alt=alt_baro, vs=baro_rate)` |
| 2 `mapped` | `type_map.csv` maps the type to an OpenAP type (nearest by MTOW, or same family) | as tier 1, on the mapped type |
| 3 `category` | `type_map.csv` maps the type to a class, else ADS-B `category` (`cat:A1` rows) selects one | flat kg/h from `fuel_rates.csv` |
| `unmodeled` | no type and no usable category | zero CO₂, counted in quality stats |

Tier 1 types take precedence over `type_map.csv`. The map exists to override OpenAP's built-in synonyms, which are crude (C525 and C550 both map to one 6.8 t model; AT72 to a jet; A310 to the A318). The collector never passes `use_synonym` for a type outside `available_aircraft()`.

Phase (climb, level, descent) enters only through `baro_rate`. Groundspeed stands in for TAS (ADS-B on this receiver carries no TAS/IAS/Mach). Inputs are floored at 30 kt (OpenAP returns NaN near 0 kt) and 0 ft.

### Bounds

| Bound | Mass | Airspeed factor on fuel flow |
|---|---|---|
| low | 75% MTOW | ×0.85 |
| central | 90% MTOW | ×1.00 |
| high | 100% MTOW | ×1.15 |

MTOW is `openap.prop.aircraft(type)["mtow"]`. The factor covers groundspeed-versus-airspeed (wind), applied to fuel flow rather than to the speed input. Tier 3 uses a flat ±30% around the class rate. Headline figures are central; bands are shown alongside.

### Tier 3 class rates (`fuel_rates.csv`)

kg/h per class with a source citation per row. Mostly manufacturer or POH figures reached through secondary sources; where only forum or aggregator figures exist the row says so. Two classes (`turboprop_regional`, `helicopter_light_turbine`) go beyond the first six because one rate for an ATR 72 / Q400 and a Cessna Caravan, or for an R44 and an AS350, is out by more than the ±30% band. ADS-B category fallback: A1 → `piston_single`, A2 → `turboprop_twin`, A7 → `helicopter_light_turbine`; A3–A6 with no type are `unmodeled`.

### OpenAP coverage

OpenAP 2.6.2 lists 37 aircraft. Only 26 have their own drag polar; 11 (A19N, A21N, A318, B37M, B39M, B3XM, B763, B773, CRJ9, E145, E170) construct only with `use_synonym=True`, which borrows a sibling's drag polar (A20N, A20N, A319, B38M, B38M, B38M, B752, B77W, E75L, E75L, E75L) while keeping the type's own MTOW and engine. These count as tier 1 but are weaker than the other 26.

### Provenance and recompute

Per pass: `openap_version`, `tier`, `model_type`, `model_rev` (`<package version>+<first 8 hex of sha256 over type_map.csv + fuel_rates.csv>`). Editing either CSV changes `model_rev`. `adsb-co2 recompute [--since …]` re-runs stored passes from their track points. OpenAP is never automerged; an upgrade is reviewed and recompute is a deliberate step.

## Configuration

Env only (see `.env.example`): `AIRCRAFT_JSON_URL`, `CENTER_LAT`, `CENTER_LON`, `RADIUS_NM`, `ALT_MIN_FT`, `ALT_MAX_FT`, `GAP_TIMEOUT_S`, `STORE_INTERVAL_S`, `PUBLISH_INTERVAL_S`, `DB_*`, `MQTT_*`, `HEARTBEAT_URL`, `TZ`. Emissions-relevant data lives in `src/adsb_co2/data/`.

## Known limitations

- Groundspeed used as airspeed; the ±15% band is a judgement, not a measured wind error.
- Mass unknown; reference mass 90% MTOW with 75–100% bounds.
- Tier 2/3 are approximations; the dashboard shows their CO₂ share. Bizjets map to airliner-derived OpenAP models (mostly C550, E145, E170), whose fuel flow differs from the real aircraft.
- Tier 3 rates are flat kg/h: no climb/cruise distinction. Q400 (~1,000+ kg/h) is undercounted by the `turboprop_regional` rate; larger medium helicopters (S-76, AW139, S-92) and Cessna Caravan-class singles are off by similar margins.
- 11 tier 1 types use a borrowed drag polar (above).
- Reception gaps under 5 min are bridged by interpolation; passes that time out inside the area undercount.
- Aircraft without ADS-B/MLAT positions are invisible.
- Ground operations excluded.
- Unknown type with ADS-B category A3–A6 is `unmodeled` (zero CO₂), not guessed.

## Acceptance

TODO: hand-computed passes, one-day plausibility band, 24 h uptime check (design § Acceptance).
