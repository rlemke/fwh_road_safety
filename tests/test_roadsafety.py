"""fwh_road_safety — FARS fatalities normalised by FHWA vehicle-miles.

⚠️ The tests that matter here are about MEASUREMENT, not plumbing: the sentinel
filter that must not eat real coordinates, the exposure join that must not
compare different key spaces, and the fact that this is a fatal-crash measure
rather than a dangerous-roads one.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from roadsafety import _lib


def _fars_zip(rows: list[dict]) -> bytes:
    cols = ["STATE", "STATENAME", "ST_CASE", "LATITUDE", "LONGITUD", "FATALS",
            "FUNC_SYSNAME", "RUR_URBNAME"]
    body = ",".join(cols) + "\n"
    for r in rows:
        body += ",".join(str(r.get(c, "")) for c in cols) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FARS2023NationalCSV/accident.csv", body)
    return buf.getvalue()


# --- the sentinel filter ----------------------------------------------------

def test_documented_sentinels_are_removed():
    """FARS codes an unknown coordinate as a run of 7s/8s/9s, which parse as
    valid floats. 77.7777 N is in the Arctic Ocean."""
    z = _fars_zip([
        {"STATE": 1, "ST_CASE": 1, "LATITUDE": 33.5, "LONGITUD": -86.8, "FATALS": 1},
        {"STATE": 1, "ST_CASE": 2, "LATITUDE": 77.7777, "LONGITUD": 777.7777, "FATALS": 1},
        {"STATE": 1, "ST_CASE": 3, "LATITUDE": 88.8888, "LONGITUD": 888.8888, "FATALS": 1},
        {"STATE": 1, "ST_CASE": 4, "LATITUDE": 99.9999, "LONGITUD": 999.9999, "FATALS": 1},
    ])
    crashes, audit = _lib.parse_fars(z, 2023)
    assert audit.total == 4 and audit.usable == 1 and audit.sentinel == 3
    assert [c.lat for c in crashes] == [33.5, None, None, None]


def test_a_real_longitude_of_minus_77_7777_is_kept():
    """⚠️ The regression this exists for. −77.7777 is a genuine place on the
    Carolina/Virginia coast; a filter matching on magnitude alone discarded 4
    real crashes from the 2023 file. A sentinel must ALSO be out of range."""
    z = _fars_zip([{"STATE": 37, "ST_CASE": 9, "LATITUDE": 34.9,
                    "LONGITUD": -77.7777, "FATALS": 1}])
    crashes, audit = _lib.parse_fars(z, 2023)
    assert audit.sentinel == 0 and audit.usable == 1
    assert crashes[0].lon == -77.7777


def test_a_crash_with_no_coordinate_is_still_counted():
    """It lost its location, not its death. Dropping the row would understate
    the numerator while the denominator stayed whole."""
    z = _fars_zip([{"STATE": 1, "ST_CASE": 1, "LATITUDE": 77.7777,
                    "LONGITUD": 777.7777, "FATALS": 2}])
    crashes, _ = _lib.parse_fars(z, 2023)
    assert len(crashes) == 1 and crashes[0].fatalities == 2 and crashes[0].lat is None


# --- the exposure join ------------------------------------------------------

def test_rate_is_per_100_million_vmt():
    crashes = [_lib.Crash("FARS", 2023, 1, "Alabama", "1", 33.0, -86.0, 100)]
    vmt = {1: ("Alabama", 10_000.0)}          # 10,000 million = 100 x 100M
    r = _lib.state_rates(crashes, vmt)[0]
    assert r.rate == pytest.approx(1.0)


def test_states_present_in_only_one_source_are_excluded():
    """⚠️ A state with crashes but no VMT would otherwise vanish from the map,
    and one with VMT but no crashes would render as a genuine zero."""
    crashes = [_lib.Crash("FARS", 2023, 1, "Alabama", "1", 33.0, -86.0, 10),
               _lib.Crash("FARS", 2023, 2, "Alaska", "2", 61.0, -149.0, 5)]
    vmt = {1: ("Alabama", 1000.0), 6: ("California", 5000.0)}
    out = _lib.state_rates(crashes, vmt)
    assert [r.state_fips for r in out] == [1]


def test_territories_are_excluded_from_both_sides():
    """FARS carries territory codes in some years; VM-2 does not. Mixing them
    puts a numerator over one key space and a denominator over another."""
    crashes = [_lib.Crash("FARS", 2023, 43, "Puerto Rico", "1", 18.2, -66.5, 300),
               _lib.Crash("FARS", 2023, 1, "Alabama", "2", 33.0, -86.0, 10)]
    vmt = {1: ("Alabama", 1000.0)}
    out = _lib.state_rates(crashes, vmt)
    assert len(out) == 1 and out[0].fatalities == 10


def test_zero_vmt_never_divides():
    crashes = [_lib.Crash("FARS", 2023, 1, "X", "1", 0.0, 0.0, 5)]
    assert _lib.state_rates(crashes, {1: ("X", 0.0)}) == []


# --- uncertainty ------------------------------------------------------------

def test_confidence_interval_widens_as_counts_shrink():
    """⚠️ Why the interval is on the map. A rate built on a few hundred deaths
    is not comparable to one built on thousands, and a choropleth invites
    exactly that comparison."""
    small = _lib.state_rates([_lib.Crash("FARS", 2023, 1, "S", "1", 0, 0, 25)],
                             {1: ("S", 2000.0)})[0]
    large = _lib.state_rates([_lib.Crash("FARS", 2023, 1, "L", "1", 0, 0, 2500)],
                             {1: ("L", 200_000.0)})[0]
    assert small.rate == pytest.approx(large.rate, rel=1e-6)
    assert (small.rate_hi - small.rate_lo) > 8 * (large.rate_hi - large.rate_lo)


def test_interval_brackets_the_point_estimate():
    r = _lib.state_rates([_lib.Crash("FARS", 2023, 1, "X", "1", 0, 0, 733)],
                         {1: ("X", 40_944.0)})[0]
    assert r.rate_lo < r.rate < r.rate_hi


# --- VM-2 -------------------------------------------------------------------

def test_vm2_layout_change_is_refused_not_guessed():
    """The sheet is a Crystal Reports export; if the columns move, a silent
    partial parse would produce a denominator missing states."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "A"
    ws.append(["Alabama"] + [0] * 20)
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(ValueError, match="only"):
        _lib.parse_vm2(buf.getvalue())


# --- the framing ------------------------------------------------------------

def test_the_map_says_it_is_a_fatal_crash_measure():
    """⚠️ Fatal crashes concentrate on high-speed rural roads; injury crashes on
    urban arterials. Calling this 'dangerous roads' is the same error as reading
    OSM feature counts as real-world prevalence."""
    from roadsafety.render import render_rate_map
    html, drawn = render_rate_map(
        {"year": 2023, "national_rate_per_100m_vmt": 1.26, "fatalities": 41025,
         "vmt_millions": 3_246_817.0,
         "rates": [{"state_fips": 28, "state": "Mississippi", "fatalities": 733,
                    "crashes": 700, "vmt_millions": 40944.0, "rate": 1.79,
                    "rate_lo": 1.66, "rate_hi": 1.92}]}, {})
    assert "fatal-crash measure, not" in html
    assert "high-injury network" in html
    assert drawn == 0          # no geometry supplied -> table only, not a crash


def test_render_degrades_to_a_table_without_geometry():
    """The RATES are the result; the map is a presentation of them."""
    from roadsafety.render import render_rate_map
    html, drawn = render_rate_map(
        {"year": 2023, "national_rate_per_100m_vmt": 1.26, "fatalities": 1,
         "vmt_millions": 100.0,
         "rates": [{"state_fips": 1, "state": "Alabama", "fatalities": 1, "crashes": 1,
                    "vmt_millions": 100.0, "rate": 1.0, "rate_lo": 0.1, "rate_hi": 5.0}]}, {})
    assert drawn == 0 and "Alabama" in html


# --- county: per-capita, and why that is a different measure -----------------

from roadsafety import _county


def _pop(**kw):
    return {f: (n, s, p) for f, (n, s, p) in kw.items()}


def test_connecticut_is_excluded_not_silently_dropped():
    """⚠️ The regression this exists for. FARS still codes CT with the 8 legacy
    counties (09001–09015); the Census 2023 vintage uses 9 planning regions
    (09110–09190). The overlap is EMPTY, so a naive join blanks the whole state
    out with no error. It is excluded explicitly and COUNTED."""
    crashes = [_lib.Crash("FARS", 2023, 9, "Connecticut", "1", 41.3, -72.9, 2,
                          county_fips=9),
               _lib.Crash("FARS", 2023, 1, "Alabama", "2", 33.0, -86.0, 3,
                          county_fips=1)]
    pop = _pop(**{"01001": ("Autauga", "Alabama", 60000),
                  "09110": ("Capitol Planning Region", "Connecticut", 900000)})
    rates, diag = _county.county_rates(crashes, pop)
    assert diag["connecticut_records_excluded"] == 1
    assert all(not r.fips.startswith("09") for r in rates)


def test_unknown_county_codes_do_not_become_real_fips():
    """FARS codes an unknown county 998/999; concatenated they would form a
    plausible 5-digit FIPS that matches nothing and vanishes without a trace."""
    crashes = [_lib.Crash("FARS", 2023, 1, "Alabama", "1", 33.0, -86.0, 4,
                          county_fips=998)]
    _, diag = _county.county_rates(crashes, _pop(**{"01001": ("A", "Alabama", 1000)}))
    assert diag["unknown_county_records"] == 1


def test_a_county_with_no_deaths_is_a_real_zero():
    """⚠️ Dropping it would make the map look like coverage stops at the county
    line. Zero road deaths is a fact, not missing data."""
    rates, _ = _county.county_rates(
        [], _pop(**{"01001": ("Autauga", "Alabama", 60000)}))
    assert len(rates) == 1 and rates[0].fatalities == 0 and rates[0].rate == 0.0


def test_small_counties_are_flagged_unreliable():
    """⚠️ Loving County, Texas: 21 deaths among 43 residents = 9,767 per 100k.
    The NCHS convention is that a rate on fewer than 20 events is unreliable —
    and note it does NOT rescue Loving, which is why the page also carries the
    through-traffic caveat."""
    crashes = [_lib.Crash("FARS", 2023, 1, "X", str(i), 0, 0, 1, county_fips=1)
               for i in range(5)]
    rates, diag = _county.county_rates(crashes, _pop(**{"01001": ("Small", "X", 800)}))
    assert rates[0].fatalities == 5 and rates[0].reliable is False
    assert diag["reliable_counties"] == 0


def test_reliability_threshold_is_the_nchs_one():
    assert _county.UNRELIABLE_BELOW_EVENTS == 20


def test_population_parse_refuses_a_truncated_file():
    bad = b"SUMLEV,STATE,COUNTY,STNAME,CTYNAME,POPESTIMATE2023\n040,01,000,Alabama,Alabama,5000000\n"
    with pytest.raises(ValueError, match="only"):
        _county.parse_county_population(bad, 2023)


# --- the BOM ----------------------------------------------------------------

def test_a_utf8_bom_does_not_silently_zero_the_file():
    """⚠️ The 2022 national file starts with EF BB BF. Decoded as latin-1 the
    first column became 'STATE' in disguise, every row[\"STATE\"] raised KeyError,
    and the parser returned ZERO crashes from a 24 MB file while reporting
    success — 39,422 crashes and 42,721 deaths lost in silence."""
    cols = "STATE,STATENAME,ST_CASE,LATITUDE,LONGITUD,FATALS,COUNTY\n"
    body = (cols + "1,Alabama,1,33.5,-86.8,1,13\n").encode("utf-8")
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("FARS2022NationalCSV/accident.csv", b"\xef\xbb\xbf" + body)
    crashes, audit = _lib.parse_fars(z.getvalue(), 2022)
    assert len(crashes) == 1 and crashes[0].state_fips == 1


def test_an_all_rows_skipped_parse_raises_instead_of_returning_empty():
    """Skipping a bad row is right; skipping every row and reporting success is
    how the BOM stayed invisible."""
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("FARS2022NationalCSV/accident.csv",
                    "WRONG,COLUMNS\n1,2\n")
    with pytest.raises(ValueError, match="NO crashes"):
        _lib.parse_fars(z.getvalue(), 2022)


# --- roads: deaths per mile -------------------------------------------------

from roadsafety import _roads


def test_fars_and_tiger_name_the_same_road_differently():
    """⚠️ The join is (type, number) because the sources disagree on spelling:
    FARS 'US-1' vs TIGER 'US Hwy 1'+RTTYP=U, and TIGER writes interstates with a
    space ('I- 95')."""
    assert _roads.fars_route_key("US-1") == ("U", "1")
    assert _roads.tiger_route_key("US Hwy 1", "U") == ("U", "1")
    assert _roads.fars_route_key("I-95") == ("I", "95")
    assert _roads.tiger_route_key("I- 95", "I") == ("I", "95")
    assert _roads.fars_route_key("SR-99") == ("S", "99")
    assert _roads.tiger_route_key("State Hwy 99", "S") == ("S", "99")


def test_only_the_first_route_in_tway_id_is_the_crash_road():
    """'US-31 SR-3' is a junction: the crash is on US-31, SR-3 is the cross
    street. Counting both would double-attribute the death."""
    assert _roads.fars_route_key("US-31 SR-3") == ("U", "31")


def test_unnumbered_roads_are_skipped_not_guessed():
    for v in ("CR-BOE RD", "MAIN ST", "", "FARM RD 12 1/2"):
        k = _roads.fars_route_key(v)
        assert k is None or k[0] in ("I", "U", "S", "C")


def test_leading_zeros_do_not_split_a_route():
    """FARS 'US-001' and TIGER 'US Hwy 1' are the same road."""
    assert _roads.fars_route_key("US-001") == _roads.tiger_route_key("US Hwy 1", "U")


def test_short_stubs_are_excluded_from_the_ranking():
    """⚠️ Same reason the county map has a reliability floor: a 0.4-mile stub
    with one death scores 2.5 deaths/mile and would top the list on a rounding
    artifact."""
    c = [_lib.Crash("FARS", 2023, 1, "X", "1", 0, 0, 1, trafficway="US-9")]
    lines = [(("U", "9"), 0.4, [[0, 0], [0.01, 0]])]
    out, _ = _roads.road_risk(c, {1: lines}, {1: "X"}, n_years=1, min_miles=5.0)
    assert out == []


def test_per_mile_reorders_against_raw_count():
    """The whole point: by count the deadliest roads are the longest busy ones."""
    c = ([_lib.Crash("FARS", 2023, 1, "X", str(i), 0, 0, 1, trafficway="I-5")
          for i in range(100)]
         + [_lib.Crash("FARS", 2023, 1, "X", "s" + str(i), 0, 0, 1, trafficway="SR-9")
            for i in range(10)])
    lines = [(("I", "5"), 1000.0, [[0, 0], [1, 0]]),
             (("S", "9"), 10.0, [[0, 0], [0.1, 0]])]
    out, _ = _roads.road_risk(c, {1: lines}, {1: "X"}, n_years=1)
    assert out[0].route == "SR-9"          # per mile
    assert max(out, key=lambda r: r.fatalities).route == "I-5"   # by count


def test_length_is_measured_not_assumed():
    lines = [(("I", "5"), 0, [[-100.0, 40.0], [-100.0, 41.0]])]
    miles = _roads._haversine_miles((-100.0, 40.0), (-100.0, 41.0))
    assert 68 < miles < 70          # one degree of latitude ~69 miles
