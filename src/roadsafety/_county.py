"""County fatalities per 100,000 residents.

⚠️ A DIFFERENT MEASURE from the state rate, not a finer-grained one. Per-VMT
answers "how deadly per unit of travel"; per-capita answers "how deadly for the
people who live here". They disagree by design: a rural county on an interstate
carries through-traffic its residents are not driving, so its per-capita rate is
inflated relative to its per-VMT rate. County VMT is not published, which is why
this uses population — the substitution is stated, not hidden.

⚠️ Small numbers dominate at county scale. Most US counties see single-digit
annual road deaths; a county of 800 people with 3 deaths scores 375 per 100k,
which is noise, not a finding. Every county carries a Poisson interval, and
counties below the NCHS reliability threshold of 20 events are FLAGGED rather
than silently ranked beside Los Angeles.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

#: NCHS treats a rate computed on fewer than 20 events as unreliable. Kept as the
#: threshold rather than invented, because the point is to use the convention a
#: reader of vital statistics already knows.
UNRELIABLE_BELOW_EVENTS = 20

#: ⚠️ FARS still codes Connecticut with the EIGHT legacy counties (FIPS 09001–
#: 09015). The Census 2023 vintage uses NINE Planning Regions (09110–09190).
#: The overlap is EMPTY — a naive join drops all 289 Connecticut crashes and
#: renders the state blank with no error. The old counties do not aggregate
#: cleanly into the new regions either: towns were reassigned, so it is not a
#: 1:1 or even a clean many-to-1 mapping. Connecticut is therefore EXCLUDED from
#: the county map and said so, rather than silently vanishing or being
#: apportioned on an assumption.
CT_STATE_FIPS = 9

#: FARS uses this for an unknown county.
_UNKNOWN_COUNTY = {998, 999, 0}


@dataclass
class CountyRate:
    fips: str
    county: str
    state: str
    fatalities: int
    population: int
    rate: float          # per 100,000 residents
    rate_lo: float
    rate_hi: float
    reliable: bool       # >= UNRELIABLE_BELOW_EVENTS deaths


def parse_county_population(csv_bytes: bytes, year: int = 2023) -> dict[str, tuple[str, str, int]]:
    """Census PEP county totals -> {fips: (county, state, population)}."""
    col = f"POPESTIMATE{year}"
    out: dict[str, tuple[str, str, int]] = {}
    for r in csv.DictReader(io.StringIO(csv_bytes.decode("latin-1"))):
        if r.get("COUNTY") in (None, "000"):
            continue                      # a state total row, not a county
        try:
            pop = int(r[col])
        except (KeyError, ValueError):
            continue
        out[f"{r['STATE']}{r['COUNTY']}"] = (r["CTYNAME"], r["STNAME"], pop)
    if len(out) < 3000:
        raise ValueError(f"county population parse produced only {len(out)} rows")
    return out


def _poisson_ci(deaths: int, per: float) -> tuple[float, float]:
    if deaths <= 0 or per <= 0:
        return (0.0, 0.0)
    lo = deaths * (1 - 1 / (9 * deaths) - 1.96 / (3 * math.sqrt(deaths))) ** 3
    hi = (deaths + 1) * (1 - 1 / (9 * (deaths + 1))
                         + 1.96 / (3 * math.sqrt(deaths + 1))) ** 3
    return (lo / per, hi / per)


def county_rates(crashes, population: dict[str, tuple[str, str, int]]):
    """-> (rates, diagnostics). Counties with no deaths are kept at rate 0.

    ⚠️ A county with zero road deaths is a real zero, not missing data, and
    dropping it would make the map look like coverage stops at the county line.
    """
    deaths: dict[str, int] = {}
    unknown_county = 0
    ct_records = 0
    for c in crashes:
        if c.state_fips == CT_STATE_FIPS:
            ct_records += 1
            continue
        cty = getattr(c, "county_fips", None)
        if cty is None or int(cty) in _UNKNOWN_COUNTY:
            unknown_county += 1
            continue
        key = f"{c.state_fips:02d}{int(cty):03d}"
        deaths[key] = deaths.get(key, 0) + c.fatalities

    rates: list[CountyRate] = []
    unmatched = 0
    for fips, n in deaths.items():
        if fips not in population:
            unmatched += 1
    for fips, (cty, st, pop) in population.items():
        if int(fips[:2]) == CT_STATE_FIPS or pop <= 0:
            continue
        n = deaths.get(fips, 0)
        per = pop / 100_000.0
        lo, hi = _poisson_ci(n, per)
        rates.append(CountyRate(fips, cty, st, n, pop, n / per, lo, hi,
                                n >= UNRELIABLE_BELOW_EVENTS))
    rates.sort(key=lambda r: -r.rate)
    diag = {
        "counties": len(rates),
        "unmatched_fars_counties": unmatched,
        "unknown_county_records": unknown_county,
        "connecticut_records_excluded": ct_records,
        "reliable_counties": sum(1 for r in rates if r.reliable),
    }
    return rates, diag
