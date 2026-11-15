# Cruise fuel calibration against ICAO

OpenAP fits a fuel curve to each type only where its Acropole-derived data covers it. Every other type gets a default curve scaled by the engine's ICAO take-off fuel flow. Those generic-curve types are where our cruise fuel disagreed with published figures, in both directions. Our calls into OpenAP were checked against its source: units are kg, kt, ft and ft/min.

## Reference

ICAO Carbon Emissions Calculator Methodology v13.1 (Aug 2024), Appendix C: trip fuel (kg) by stage length (nm) per equivalent aircraft code. https://icec.icao.int/Documents/Methodology%20ICAO%20Carbon%20Emissions%20Calculator_v13_Final.pdf

## Method (`scripts/calibrate.py`)

For each OpenAP type:

1. Marginal ICAO fuel per nm over a cruise-dominated stage range, which excludes take-off, climb and descent: 2000–4000 nm for MTOW above 150 t, else 1000–2000 nm (750–1500 where the table stops short).
2. Converted to kg/h at the type's OpenAP cruise Mach and height (true airspeed, ISA).
3. OpenAP `enroute` at the same speed and height, level, at the central mass (80% MTOW).
4. `factor = ICAO / OpenAP`.

```sh
pdftotext -layout methodology.pdf icao.txt
uv run python scripts/calibrate.py icao.txt
```

## Applied

`src/adsb_co2/data/calibration.csv` holds `ratio` (ICAO / OpenAP) and the applied `factor`, which multiplies the low, central and high fuel flow alike. `factor` is the ratio for generic-curve types and 1.0 for:

- fitted-curve types, which already agree with ICAO within about ±10%, within the method's own error;
- `c550`, whose ICAO match is doubtful and which other bizjets map to (see caveats);
- `glf6`, which has no ICAO row.

Regenerate with the command above after an OpenAP upgrade, then run `adsb-co2 recompute`.

## Result

Fitted types agree with ICAO to within about ±10% (median 1.02), which supports the method. Generic types range from 0.63 to 1.58.

| Type | ICAO | ICAO kg/h | OpenAP kg/h | Ratio | OpenAP curve |
|---|---|---|---|---|---|
| a19n | 31N | 2250 | 1428 | 1.576 | generic |
| a20n | 32N | 2354 | 1489 | 1.581 | generic |
| a21n | 32Q | 2507 | 1858 | 1.349 | generic |
| a318 | 318 | 2171 | 1963 | 1.106 | fitted |
| a319 | 319 | 2415 | 2372 | 1.018 | fitted |
| a320 | 320 | 2629 | 2575 | 1.021 | fitted |
| a321 | 321 | 3064 | 3045 | 1.006 | fitted |
| a332 | 332 | 5514 | 5663 | 0.974 | fitted |
| a333 | 333 | 5764 | 5651 | 1.020 | fitted |
| a343 | 343 | 6346 | 7945 | 0.799 | generic |
| a359 | 359 | 6640 | 7781 | 0.853 | generic |
| a388 | 388 | 14162 | 13592 | 1.042 | generic |
| b37m | 7M8 | 2304 | 2051 | 1.123 | generic |
| b38m | 7M8 | 2334 | 2102 | 1.110 | generic |
| b39m | 7M9 | 2425 | 2217 | 1.094 | generic |
| b3xm | 7M9 | 2425 | 2257 | 1.075 | generic |
| b734 | 734 | 2800 | 2355 | 1.189 | generic |
| b737 | 73G | 2196 | 2389 | 0.919 | fitted |
| b738 | 738 | 2584 | 2533 | 1.020 | fitted |
| b739 | 739 | 2755 | 2603 | 1.058 | fitted |
| b744 | 744 | 11420 | 13428 | 0.851 | generic |
| b748 | 74H | 10587 | 12631 | 0.838 | generic |
| b752 | 752 | 3513 | 4330 | 0.811 | generic |
| b763 | 763 | 4939 | 5486 | 0.900 | generic |
| b772 | 772 | 6957 | 11095 | 0.627 | generic |
| b773 | 773 | 7905 | 10727 | 0.737 | generic |
| b77w | 77W | 7992 | 11347 | 0.704 | generic |
| b788 | 788 | 5075 | 5089 | 0.997 | generic |
| b789 | 789 | 5770 | 6971 | 0.828 | generic |
| c550 | CNJ | 454 | 706 | 0.643 | generic |
| crj9 | CR9 | 1557 | 1365 | 1.141 | fitted |
| e145 | ER4 | 1031 | 796 | 1.295 | generic |
| e170 | E70 | 1471 | 1617 | 0.910 | fitted |
| e190 | E90 | 1850 | 1921 | 0.963 | fitted |
| e195 | E95 | 2085 | 1911 | 1.091 | fitted |
| e75l | E75 | 1590 | 1626 | 0.978 | fitted |
| glf6 | – | – | – | – | generic |

Applied to 2026-11-14's passes as estimated before wiring, the generic-only factors lower the day's total by about 7% (486.8 t to about 453 t): the 777s fall by 26–37%, but the A320neo family and ERJ-145 rise.

## Caveats

- ICAO's table is itself modelled, with average loads and real-world routing built in. It's a published, consistent reference, not measured fuel.
- 737 MAX 7 and MAX 10 borrow the MAX 8 and MAX 9 rows. `c550` maps to ICAO's generic Citation (`CNJ`), so its factor is the weakest. `glf6` has no ICAO row and stays at 1.0.
- One factor per type, taken at cruise. Climb and descent inherit it.
- Separate from the wind bias: groundspeed stands in for true airspeed, and on 2026-11-14 eastbound cruise ran 9–35% above westbound for the same types.

## Decision: keep fixed MTOW fractions (route-based mass not adopted)

Prototyped on 2026-11-15 against 2026-11-14's passes. Routes came from adsb.im's routeset (adsb.lol's returned empty responses with or without a key). Mass at the aircraft's position was estimated as OEW + payload (typical seats × load factor × 100 kg, plus a cargo uplift) + ICAO trip fuel for the leg + reserves (5% of trip + 45 min cruise), capped at MTOW, minus ICAO fuel for the distance already flown.

- Coverage: 278 of 537 airliner passes (66% of their fuel) had a plausible route. adsb.im found plausible routes for 90% of OpenAP-tier callsigns; adsbdb's position-checked rate was 54%.
- Estimated mass at position: median 81% of MTOW (p10 72%, p90 90%), essentially the current central assumption.
- Effect: central fuel +0.6% across all airliner passes (+0.9% on those with routes). Per type −8% to +6%. The low–high band narrowed from 49% to 36% of central.

Not adopted: daily totals barely move, while it adds a runtime dependency (batched, cached lookups under adsb.im's terms), multi-leg leg selection, and payload assumptions that fail for freighters (767-300s came out at 96% of MTOW) and for mapped types, which borrow their stand-in's seats and OEW. OpenAP fuel flow moves about 8% per 10% of MTOW, so speed (via wind) is the larger error. Revisit if per-flight figures or narrower bands matter.

## Wind: adopted

Prototyped the same day: Open-Meteo's archived GFS winds for 2026-11-14 (about 38–40 kt from the west at cruise) turned each point's groundspeed into airspeed. Cruise burn, east / west, kg/h at central mass:

| Type | Groundspeed | Gap | Airspeed | Gap |
|---|---|---|---|---|
| b77w | 8952 / 7877 | +14% | 8481 / 8140 | +4% |
| b772 | 7774 / 6558 | +19% | 7326 / 6762 | +8% |
| a359 | 8200 / 6061 | +35% | 7764 / 6306 | +23% |
| a333 | 6656 / 5303 | +26% | 6168 / 5517 | +12% |
| a21n | 2730 / 2497 | +9% | 2635 / 2517 | +5% |
| e75l | 1896 / 1563 | +21% | 1786 / 1601 | +12% |

Airliner fuel fell 2.0% (160.4 t to 157.3 t): headwinds and tailwinds mostly cancel, and the remainder is drag's square-law asymmetry. Adopted because it removes a known directional bias and lets the speed band narrow from ±15% to ±5%, at the cost of one hourly request. Some of the remaining gap is plausibly real (eastbound long-haul is heavier at this point). Implementation: [methods.md](methods.md#wind-windpy).
