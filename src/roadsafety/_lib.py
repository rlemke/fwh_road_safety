"""US road-safety risk: NHTSA FARS fatalities normalised by FHWA vehicle-miles.

⚠️ THIS IS A FATAL-CRASH MEASURE, NOT A "DANGEROUS ROADS" MEASURE. FARS records
fatal crashes only. Fatal crashes concentrate on high-speed rural roads; injury
crashes concentrate on urban arterials, so a FARS map and a high-injury network
disagree almost everywhere. Calling this "the most dangerous states" would be the
same error as reading OSM feature counts as real-world prevalence.

⚠️ Exposure normalisation is in v1 on purpose. A raw fatal-crash count map is a
population map with extra steps — it ranks California, Texas and Florida first
because that is where the driving happens. The rate per 100 million VMT is the
measure NHTSA itself reports, and it reorders the map completely.

Three tiers, and only the first two are implemented here:

  count   "many people died here"                      — misleading alone
  rate    "many died per 100M vehicle-miles driven"    — v1, this module
  risk    "the rate is high after accounting for road
           type, and the uncertainty is small enough
           to say so"                                  — needs road-class
                                                         exposure, not v1
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import zipfile
from dataclasses import dataclass, field
from typing import Any

from . import storage as store

log = logging.getLogger(__name__)

FARS_URL = "https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip"
VM2_URL = "https://www.fhwa.dot.gov/policyinformation/statistics/{year}/xls/vm2.xlsx"

#: ⚠️ FARS codes an unknown coordinate as a run of 7s, 8s or 9s rather than
#: leaving it blank (data dictionary: "Not Reported" / "Not Available" /
#: "Reported as Unknown"). Measured in the 2023 file: 85 + 8 + 36 = 129 records,
#: 0.34%. They parse as valid floats, so nothing rejects them — plotted as-is
#: they put fatal crashes at 77.7777°N, in the Arctic Ocean.
_SENTINELS = (77.7777, 88.8888, 99.9999, 777.7777, 888.8888, 999.9999)

#: ⚠️ A sentinel must ALSO be geographically impossible for its field, or the
#: filter eats real data: longitude −77.7777 is a perfectly good place (the
#: Carolina/Virginia coast), and matching on magnitude alone discarded 4 genuine
#: crashes in the 2023 file. US latitudes run ~17–72 N; US longitudes are all
#: negative. So a sentinel is a magnitude match that is ALSO out of range.
_LAT_RANGE = (15.0, 72.0)
_LON_RANGE = (-180.0, -64.0)


def _sentinel_lat(v: float) -> bool:
    return _matches_sentinel(v) and not (_LAT_RANGE[0] <= v <= _LAT_RANGE[1])


def _sentinel_lon(v: float) -> bool:
    return _matches_sentinel(v) and not (_LON_RANGE[0] <= v <= _LON_RANGE[1])


def _matches_sentinel(v: float) -> bool:
    return any(abs(abs(v) - s) < 1e-3 for s in _SENTINELS)

#: 50 states + DC. FARS also carries territory codes in some years; VM-2 does
#: not, and mixing them silently compares a numerator over one key space with a
#: denominator over another.
_NON_STATE_FIPS = {3, 7, 14, 43, 52}


@dataclass
class Crash:
    """The common crash schema every source normalises to."""

    source: str
    year: int
    state_fips: int
    state: str
    case_id: str
    lat: float | None
    lon: float | None
    fatalities: int
    #: FARS FUNC_SYS / RUR_URB — kept because the risk tier needs road class,
    #: and FARS supplies it without touching OSM.
    functional_system: str = ""
    rural_urban: str = ""
    #: FIPS within the state. ⚠️ FARS codes an unknown county as 998/999, which
    #: would otherwise become a real-looking 5-digit FIPS that matches nothing.
    county_fips: int | None = None
    county: str = ""


@dataclass
class StateRate:
    state_fips: int
    state: str
    fatalities: int
    crashes: int
    vmt_millions: float
    #: fatalities per 100 million vehicle-miles travelled
    rate: float
    #: Poisson 95% interval on the rate. ⚠️ Reported because a rate built on a
    #: few hundred deaths is not comparable to one built on thousands, and a
    #: choropleth invites exactly that comparison.
    rate_lo: float
    rate_hi: float


@dataclass
class CoordAudit:
    total: int = 0
    usable: int = 0
    sentinel: int = 0
    unparseable: int = 0
    by_code: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# roadsafety.source.FARS
# ---------------------------------------------------------------------------


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_fars(zip_bytes: bytes, year: int) -> tuple[list[Crash], CoordAudit]:
    """FARS national zip -> the common crash schema, with a coordinate audit.

    The audit is returned, not logged: how many crashes lost their location is a
    property of the result, and a caller that renders a map without knowing it is
    reporting a coverage it never checked.
    """
    audit = CoordAudit()
    out: list[Crash] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next((n for n in z.namelist()
                     if n.lower().endswith("/accident.csv") or n.lower() == "accident.csv"), None)
        if name is None:
            raise ValueError("no accident.csv in the FARS archive")
        raw = z.read(name)
    # ⚠️ utf-8-sig FIRST, to strip a BOM. The 2022 national file starts with
    # EF BB BF; decoded as latin-1 the first column name becomes "\ufeffSTATE"
    # in disguise, every row["STATE"] raises KeyError, and a parser that skipped
    # bad rows silently returned ZERO crashes from a 24 MB file while reporting
    # success. latin-1 remains the fallback because older years carry bytes that
    # are not valid UTF-8.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if text and text[0] == "\ufeff":
        text = text[1:]
    for row in csv.DictReader(io.StringIO(text)):
        audit.total += 1
        lat = lon = None
        raw_lat, raw_lon = row.get("LATITUDE", ""), row.get("LONGITUD", "")
        try:
            flat, flon = float(raw_lat), float(raw_lon)
        except (TypeError, ValueError):
            audit.unparseable += 1
        else:
            bad_lat, bad_lon = _sentinel_lat(flat), _sentinel_lon(flon)
            if bad_lat or bad_lon:
                audit.sentinel += 1
                code = f"{int(abs(flat if bad_lat else flon))}s"
                audit.by_code[code] = audit.by_code.get(code, 0) + 1
            else:
                lat, lon = flat, flon
                audit.usable += 1
        try:
            fips = int(row["STATE"])
        except (KeyError, ValueError):
            continue
        out.append(Crash(
            source="FARS", year=year, state_fips=fips,
            state=(row.get("STATENAME") or "").strip(),
            case_id=str(row.get("ST_CASE", "")),
            lat=lat, lon=lon,
            fatalities=int(row.get("FATALS") or 0),
            functional_system=(row.get("FUNC_SYSNAME") or "").strip(),
            rural_urban=(row.get("RUR_URBNAME") or "").strip(),
            county_fips=_int_or_none(row.get("COUNTY")),
            county=(row.get("COUNTYNAME") or "").strip(),
        ))
    # ⚠️ Fail loudly on an empty parse. Skipping unparseable rows is right; doing
    # it for EVERY row and returning success is not — that is how a BOM turned a
    # 24 MB file into zero crashes with no error anywhere.
    if audit.total and not out:
        raise ValueError(
            f"parsed {audit.total} row(s) from {name} but produced NO crashes — "
            "the column layout probably changed (a BOM on the first header did "
            "exactly this to the 2022 file)")
    if not audit.total:
        raise ValueError(f"{name} contained no rows")
    return out, audit


# ---------------------------------------------------------------------------
# roadsafety.source.VMT  (FHWA Highway Statistics table VM-2)
# ---------------------------------------------------------------------------


def parse_vm2(xlsx_bytes: bytes) -> dict[int, tuple[str, float]]:
    """VM-2 -> {state_fips: (name, annual VMT in millions)}.

    ⚠️ The layout is a Crystal Reports export, not a data file: the header spans
    rows 11-14 and the numbers start at row 15. Column 18 is the rural+urban
    grand total and column 19 is the state FIPS — both to the RIGHT of the
    visible table, in a block the human-readable page never shows.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    ws = wb["A"] if "A" in wb.sheetnames else wb[wb.sheetnames[0]]
    out: dict[int, tuple[str, float]] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or len(row) < 19 or not isinstance(row[0], str):
            continue
        total, fips = row[17], row[18]
        if not isinstance(total, (int, float)) or not isinstance(fips, (int, float)):
            continue
        f = int(fips)
        if not (1 <= f <= 56) or f in _NON_STATE_FIPS:
            continue
        out[f] = (row[0].strip(), float(total))
    if len(out) < 50:
        raise ValueError(f"VM-2 parse produced only {len(out)} states — layout changed?")
    return out


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------


def _poisson_ci(deaths: int, exposure_100m: float) -> tuple[float, float]:
    """Byar's approximation to the Poisson 95% interval on a rate.

    ⚠️ Present because the smallest states have a few hundred deaths and the
    largest have thousands; a choropleth invites a comparison the point
    estimates alone do not support.
    """
    if deaths <= 0 or exposure_100m <= 0:
        return (0.0, 0.0)
    lo = deaths * (1 - 1 / (9 * deaths) - 1.96 / (3 * math.sqrt(deaths))) ** 3
    hi = (deaths + 1) * (1 - 1 / (9 * (deaths + 1))
                         + 1.96 / (3 * math.sqrt(deaths + 1))) ** 3
    return (lo / exposure_100m, hi / exposure_100m)


def state_rates(crashes: list[Crash], vmt: dict[int, tuple[str, float]]) -> list[StateRate]:
    """Join fatalities to exposure. Only states present in BOTH are returned.

    ⚠️ The intersection is deliberate and is reported by the caller. A state with
    crashes but no VMT would otherwise silently vanish from the map, and one with
    VMT but no crashes would render as a genuine zero rather than as missing.
    """
    deaths: dict[int, int] = {}
    counts: dict[int, int] = {}
    names: dict[int, str] = {}
    for c in crashes:
        if c.state_fips in _NON_STATE_FIPS:
            continue
        deaths[c.state_fips] = deaths.get(c.state_fips, 0) + c.fatalities
        counts[c.state_fips] = counts.get(c.state_fips, 0) + 1
        names.setdefault(c.state_fips, c.state)
    out: list[StateRate] = []
    for fips, (vname, miles) in sorted(vmt.items()):
        if fips not in deaths or miles <= 0:
            continue
        exposure = miles / 100.0          # VM-2 is millions; rate is per 100M
        rate = deaths[fips] / exposure
        lo, hi = _poisson_ci(deaths[fips], exposure)
        out.append(StateRate(
            state_fips=fips, state=names.get(fips) or vname,
            fatalities=deaths[fips], crashes=counts[fips],
            vmt_millions=miles, rate=rate, rate_lo=lo, rate_hi=hi,
        ))
    return sorted(out, key=lambda r: -r.rate)


def national_rate(rates: list[StateRate]) -> tuple[int, float, float]:
    """(fatalities, VMT millions, rate per 100M) across the returned states."""
    d = sum(r.fatalities for r in rates)
    v = sum(r.vmt_millions for r in rates)
    return d, v, (d / (v / 100.0) if v else 0.0)
