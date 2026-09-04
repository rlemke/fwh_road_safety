"""Deaths per mile of named road, from FARS + TIGER road geometry.

⚠️ This is the closest thing to "which roads are dangerous" that the public data
supports WITHOUT AADT. Deaths per mile is a partial exposure control: it removes
the "long roads have more crashes" effect but NOT the "busy roads have more
crashes" one. A rural two-lane with 5 deaths per mile is genuinely worse than an
interstate with 5 deaths per mile carrying 20x the traffic — and this measure
cannot see that. Per vehicle-mile would; AADT is not currently obtainable.

The join key is (state, route type, route number), because the two sources write
the same road differently:

    FARS TWAY_ID   TIGER FULLNAME + RTTYP
    US-1           "US Hwy 1"      U
    I-95           "I- 95"         I     (note the space TIGER inserts)
    SR-99          "State Hwy 99"  S
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass

#: FARS trafficway prefixes -> TIGER RTTYP. Anything else is not a numbered
#: route and is skipped rather than guessed at.
_PREFIX_TO_RTTYP = {
    "I": "I", "IH": "I", "INTERSTATE": "I",
    "US": "U", "USHWY": "U", "USH": "U",
    "SR": "S", "SH": "S", "STATE": "S", "ST": "S", "STHWY": "S",
    "CR": "C", "CH": "C", "COUNTY": "C",
}
_FARS_ROUTE = re.compile(r"^([A-Z]{1,10})[-\s]+0*(\d{1,4})\b")
_TIGER_NUM = re.compile(r"(\d{1,4})")


@dataclass
class RoadRisk:
    state_fips: int
    state: str
    route: str            # canonical, e.g. "I-95"
    rttyp: str
    miles: float
    fatalities: int
    crashes: int
    per_mile: float       # deaths per mile over the whole period
    per_mile_year: float  # ... per year


def fars_route_key(tway_id: str) -> tuple[str, str] | None:
    """'US-31 SR-3' -> ('U','31'). The FIRST route named is the crash's road;
    a second is the cross-street at a junction."""
    if not tway_id:
        return None
    m = _FARS_ROUTE.match(tway_id.strip().upper())
    if not m:
        return None
    rt = _PREFIX_TO_RTTYP.get(m.group(1))
    return (rt, m.group(2)) if rt else None


def tiger_route_key(fullname: str, rttyp: str) -> tuple[str, str] | None:
    """'US Hwy 1' + 'U' -> ('U','1'). RTTYP carries the type, so only the number
    has to be recovered from the name."""
    if rttyp not in ("I", "U", "S", "C"):
        return None
    m = _TIGER_NUM.search(fullname or "")
    return (rttyp, m.group(1).lstrip("0") or "0") if m else None


def canonical(key: tuple[str, str]) -> str:
    return {"I": "I-", "U": "US-", "S": "SR-", "C": "CR-"}[key[0]] + key[1]


def _haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 3958.7613
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def read_tiger_lines(shp: bytes, dbf: bytes):
    """-> [(key, miles, [[lon,lat],...])] for numbered routes only."""
    nrec, hlen, rlen = struct.unpack("<I H H", dbf[4:12])
    fields, off = [], 32
    while dbf[off] != 0x0D:
        fields.append((dbf[off:off + 11].split(b"\x00")[0].decode("latin-1"), dbf[off + 16]))
        off += 32
    attrs = []
    for i in range(nrec):
        rec = dbf[hlen + i * rlen: hlen + (i + 1) * rlen]
        pos, v = 1, {}
        for name, fl in fields:
            v[name] = rec[pos:pos + fl].decode("latin-1").strip()
            pos += fl
        attrs.append(v)

    out = []
    pos, idx = 100, 0
    while pos < len(shp):
        _num, clen = struct.unpack(">I I", shp[pos:pos + 8])
        body = shp[pos + 8: pos + 8 + clen * 2]
        pos += 8 + clen * 2
        if len(body) < 4 or struct.unpack("<I", body[:4])[0] != 3:   # polyline
            idx += 1
            continue
        nparts, npoints = struct.unpack("<I I", body[36:44])
        parts = list(struct.unpack(f"<{nparts}I", body[44:44 + 4 * nparts]))
        px = 44 + 4 * nparts
        pts = struct.unpack(f"<{2 * npoints}d", body[px:px + 16 * npoints])
        a = attrs[idx] if idx < len(attrs) else {}
        key = tiger_route_key(a.get("FULLNAME", ""), a.get("RTTYP", ""))
        idx += 1
        if key is None:
            continue
        for k, s in enumerate(parts):
            e = parts[k + 1] if k + 1 < nparts else npoints
            line = [[round(pts[2 * j], 5), round(pts[2 * j + 1], 5)] for j in range(s, e)]
            if len(line) < 2:
                continue
            miles = sum(_haversine_miles(line[i], line[i + 1]) for i in range(len(line) - 1))
            out.append((key, miles, line))
    return out


def road_risk(crashes, tiger_by_state: dict[int, list], state_names: dict[int, str],
              n_years: int = 1, min_miles: float = 5.0):
    """Join FARS deaths to TIGER route length.

    ⚠️ `min_miles` exists for the same reason the county map has a reliability
    threshold: a 0.4-mile stub of a route with one fatal crash scores 2.5 deaths
    per mile and would top the ranking on a rounding artifact.
    """
    deaths: dict[tuple[int, str, str], int] = {}
    counts: dict[tuple[int, str, str], int] = {}
    unmatched_deaths = 0
    for c in crashes:
        k = fars_route_key(c.__dict__.get("trafficway", "") or "")
        if k is None:
            unmatched_deaths += c.fatalities
            continue
        kk = (c.state_fips, k[0], k[1])
        deaths[kk] = deaths.get(kk, 0) + c.fatalities
        counts[kk] = counts.get(kk, 0) + 1

    out: list[RoadRisk] = []
    no_geometry = 0
    for fips, lines in tiger_by_state.items():
        agg: dict[tuple[str, str], float] = {}
        for key, miles, _line in lines:
            agg[key] = agg.get(key, 0.0) + miles
        for key, miles in agg.items():
            kk = (fips, key[0], key[1])
            d = deaths.get(kk, 0)
            if d == 0 or miles < min_miles:
                continue
            out.append(RoadRisk(fips, state_names.get(fips, ""), canonical(key), key[0],
                                round(miles, 1), d, counts.get(kk, 0),
                                d / miles, d / miles / max(1, n_years)))
    matched = {(f, t, n) for f, t, n in (
        (r.state_fips, r.rttyp, r.route.split("-")[1]) for r in out)}
    for kk, d in deaths.items():
        if kk not in matched:
            no_geometry += d
    out.sort(key=lambda r: -r.per_mile)
    return out, {"routes": len(out), "deaths_no_route_in_tway": unmatched_deaths,
                 "deaths_route_without_geometry": no_geometry}
