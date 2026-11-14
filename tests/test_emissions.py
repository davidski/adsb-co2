from adsb_co2 import emissions as e


def test_emissions():
    # tiers
    assert e.resolve("A21N", None) == ("openap", "a21n")
    assert e.resolve("B764", "A5") == ("mapped", "b763")
    assert e.resolve("c525", None) == ("mapped", "c550")  # overrides OpenAP synonym
    assert e.resolve("SR22", "A1") == ("category", "piston_single")
    assert e.resolve("ZZZZ", "A7") == ("category", "helicopter_light_turbine")
    assert e.resolve(None, "A3") == ("unmodeled", None)
    # every map row points at something we can model
    assert all(v in e.NATIVE or v in e.RATES_KG_H for v in e.TYPE_MAP.values())

    # A320-class cruise: 1-3 kg/s, ordered bounds
    low, mid, high = e.FlowModel(*e.resolve("A320", None)).rate_kg_s(35000, 450, 0)
    assert 0 < low < mid < high and 0.5 < mid < 1.5, (low, mid, high)
    # climb burns more than level
    assert (
        e.FlowModel("openap", "a320").rate_kg_s(10000, 300, 2000)[1]
        > e.FlowModel("openap", "a320").rate_kg_s(10000, 300, 0)[1]
    )
    assert all(
        x == x for t in sorted(e.NATIVE) for x in e.FlowModel("openap", t).rate_kg_s(0, 0, 0)
    )
    # tier 3 is flat kg/h, +/-30%
    low, mid, high = e.FlowModel("category", "piston_single").rate_kg_s(3000, 100, 0)
    assert abs(mid * 3600 - e.RATES_KG_H["piston_single"]) < 1e-9 and abs(high / mid - 1.3) < 1e-9
    assert e.FlowModel("unmodeled", None).rate_kg_s(0, 0, 0) == (0.0, 0.0, 0.0)
    assert e.model_rev().count("+") == 1
