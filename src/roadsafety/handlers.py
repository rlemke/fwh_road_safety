"""Handlers for the roadsafety facets."""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.request
import zipfile
from dataclasses import asdict
from typing import Any

from . import _lib
from . import storage as store

log = logging.getLogger(__name__)


def _log(params: dict[str, Any]):
    cb = params.get("_step_log")
    return cb if callable(cb) else (lambda *a, **k: None)


def _fetch(url: str, timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "facetwork-roadsafety/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def handle_fars(params: dict[str, Any]) -> dict[str, Any]:
    say = _log(params)
    year = int(params.get("year") or 2023)
    dest = str(params["dest"])
    url = _lib.FARS_URL.format(year=year)
    say(f"FARS {year}: {url}")
    crashes, audit = _lib.parse_fars(_fetch(url), year)
    if audit.sentinel:
        # ⚠️ Not a debug line. These crashes exist but have no usable location;
        # a map drawn from this file covers fewer crashes than it reports.
        say(f"{audit.sentinel} crash(es) carry a FARS 7s/8s/9s coordinate code "
            f"and are NOT mappable ({audit.by_code})", level="warning")
    out = dest + "/crashes.json"
    store.write_text(out, json.dumps({
        "source": "FARS", "year": year, "source_url": url,
        "audit": asdict(audit),
        "crashes": [asdict(c) for c in crashes],
    }))
    return {
        "crashes_path": out,
        "crashes": len(crashes),
        "fatalities": sum(c.fatalities for c in crashes),
        "usable_coords": audit.usable,
        "sentinel_coords": audit.sentinel,
        "source_url": url,
    }


def handle_vmt(params: dict[str, Any]) -> dict[str, Any]:
    say = _log(params)
    year = int(params.get("year") or 2023)
    dest = str(params["dest"])
    url = _lib.VM2_URL.format(year=year)
    say(f"FHWA VM-2 {year}: {url}")
    vmt = _lib.parse_vm2(_fetch(url))
    out = dest + "/vmt.json"
    store.write_text(out, json.dumps({
        "source": "FHWA VM-2", "year": year, "source_url": url,
        "states": {str(k): {"name": v[0], "vmt_millions": v[1]} for k, v in vmt.items()},
    }))
    return {
        "vmt_path": out, "states": len(vmt),
        "total_vmt_millions": sum(v for _, v in vmt.values()),
        "source_url": url,
    }


def handle_state_rates(params: dict[str, Any]) -> dict[str, Any]:
    say = _log(params)
    cr = json.loads(store.read_text(str(params["crashes_path"])))
    vm = json.loads(store.read_text(str(params["vmt_path"])))
    crashes = [_lib.Crash(**c) for c in cr["crashes"]]
    vmt = {int(k): (v["name"], float(v["vmt_millions"])) for k, v in vm["states"].items()}
    rates = _lib.state_rates(crashes, vmt)
    deaths, miles, nat = _lib.national_rate(rates)
    # ⚠️ Report what the join DROPPED. A state that appears in one source and not
    # the other would otherwise disappear from the map without a trace.
    crash_states = {c.state_fips for c in crashes} - _lib._NON_STATE_FIPS
    dropped = len((crash_states | set(vmt)) - {r.state_fips for r in rates})
    if dropped:
        say(f"{dropped} state(s) present in only one source and excluded", level="warning")
    dest = str(params["dest"])
    store.write_text(dest, json.dumps({
        "year": cr["year"], "national_rate_per_100m_vmt": nat,
        "fatalities": deaths, "vmt_millions": miles, "dropped_states": dropped,
        "rates": [asdict(r) for r in rates],
    }, indent=1))
    say(f"national rate {nat:.2f} per 100M VMT across {len(rates)} states")
    return {"rates_path": dest, "states": len(rates), "dropped": dropped,
            "national_rate": round(nat, 4), "fatalities": deaths}


def handle_rate_map(params: dict[str, Any]) -> dict[str, Any]:
    from .render import render_rate_map

    say = _log(params)
    data = json.loads(store.read_text(str(params["rates_path"])))
    geom = _state_geometry(str(params["geometry_url"]), say)
    html, drawn = render_rate_map(data, geom)
    dest = str(params["dest"])
    store.write_text(dest, html)
    return {"map_path": dest, "states_drawn": drawn,
            "title": f"US fatal-crash rate per 100M vehicle-miles, {data['year']}"}


def _state_geometry(url: str, say) -> dict[str, Any]:
    """Census cartographic state boundaries -> {fips: [[lon,lat], ...] rings}.

    ⚠️ Read straight from the shapefile with the stdlib rather than pulling in
    geopandas/pyshp: this is one 186 KB file with one geometry type, and a heavy
    geospatial stack is a large dependency for a domain that otherwise needs
    none. Degrades to an empty map rather than failing the run, because the
    RATES are the result and the map is a presentation of them.
    """
    try:
        raw = _fetch(url, timeout=180)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            shp = next(n for n in z.namelist() if n.endswith(".shp"))
            dbf = next(n for n in z.namelist() if n.endswith(".dbf"))
            return _read_shapefile(z.read(shp), z.read(dbf))
    except Exception as exc:  # noqa: BLE001 - the rates stand without a map
        say(f"state geometry unavailable ({type(exc).__name__}); "
            f"rendering the table without the map", level="warning")
        return {}


def _read_shapefile(shp: bytes, dbf: bytes, key: str = "STATEFP") -> dict[str, Any]:
    import struct

    # --- dbf: find the STATEFP column ---
    nrec, hlen, rlen = struct.unpack("<I H H", dbf[4:12])
    fields, off = [], 32
    while dbf[off] != 0x0D:
        name = dbf[off:off + 11].split(b"\x00")[0].decode("latin-1")
        flen = dbf[off + 16]
        fields.append((name, flen))
        off += 32
    start = hlen
    fips_by_index: list[str] = []
    for i in range(nrec):
        rec = dbf[start + i * rlen: start + (i + 1) * rlen]
        pos = 1
        vals = {}
        for name, flen in fields:
            vals[name] = rec[pos:pos + flen].decode("latin-1").strip()
            pos += flen
        fips_by_index.append(vals.get(key, ""))

    # --- shp: polygons only (type 5) ---
    out: dict[str, list] = {}
    pos, idx = 100, 0
    while pos < len(shp):
        _num, clen = struct.unpack(">I I", shp[pos:pos + 8])
        body = shp[pos + 8: pos + 8 + clen * 2]
        pos += 8 + clen * 2
        if len(body) < 4 or struct.unpack("<I", body[:4])[0] != 5:
            idx += 1
            continue
        nparts, npoints = struct.unpack("<I I", body[36:44])
        parts = list(struct.unpack(f"<{nparts}I", body[44:44 + 4 * nparts]))
        pxy = 44 + 4 * nparts
        pts = struct.unpack(f"<{2 * npoints}d", body[pxy:pxy + 16 * npoints])
        rings = []
        for k, s in enumerate(parts):
            e = parts[k + 1] if k + 1 < nparts else npoints
            rings.append([[round(pts[2 * j], 4), round(pts[2 * j + 1], 4)] for j in range(s, e)])
        fips = fips_by_index[idx] if idx < len(fips_by_index) else ""
        if fips:
            out.setdefault(fips, []).extend(rings)
        idx += 1
    return out


# ---------------------------------------------------------------------------
# county: fatalities per 100,000 residents
# ---------------------------------------------------------------------------

COUNTY_POP_URL = ("https://www2.census.gov/programs-surveys/popest/datasets/"
                  "2020-2023/counties/totals/co-est2023-alldata.csv")


def handle_county_population(params: dict[str, Any]) -> dict[str, Any]:
    from . import _county

    say = _log(params)
    year = int(params.get("year") or 2023)
    dest = str(params["dest"])
    say(f"Census county population {year}: {COUNTY_POP_URL}")
    pop = _county.parse_county_population(_fetch(COUNTY_POP_URL), year)
    out = dest + "/county_population.json"
    store.write_text(out, json.dumps({
        "source": "Census PEP", "year": year, "source_url": COUNTY_POP_URL,
        "counties": {k: {"county": v[0], "state": v[1], "population": v[2]}
                     for k, v in pop.items()},
    }))
    return {"population_path": out, "counties": len(pop),
            "total_population": sum(v[2] for v in pop.values()),
            "source_url": COUNTY_POP_URL}


def handle_county_rates(params: dict[str, Any]) -> dict[str, Any]:
    from dataclasses import asdict as _asdict

    from . import _county

    say = _log(params)
    years = [int(y) for y in (params.get("years") or [2023])]
    dest = str(params["dest"])
    crashes = []
    for path in params["crash_paths"]:
        d = json.loads(store.read_text(str(path)))
        crashes.extend(_lib.Crash(**c) for c in d["crashes"])
    pop_doc = json.loads(store.read_text(str(params["population_path"])))
    pop = {k: (v["county"], v["state"], v["population"])
           for k, v in pop_doc["counties"].items()}
    rates, diag = _county.county_rates(crashes, pop)
    if diag["connecticut_records_excluded"]:
        # ⚠️ Not a footnote. FARS still codes CT with the 8 legacy counties while
        # Census 2023 uses 9 Planning Regions; the overlap is EMPTY, so a silent
        # join would blank the state out.
        say(f"Connecticut EXCLUDED: {diag['connecticut_records_excluded']} crash records — "
            f"FARS uses the legacy 8 counties, Census 2023 uses 9 planning regions, "
            f"and they do not intersect", level="warning")
    if diag["unmatched_fars_counties"]:
        say(f"{diag['unmatched_fars_counties']} FARS county code(s) matched no "
            f"Census county", level="warning")
    store.write_text(dest, json.dumps({
        "years": years, "n_years": len(years), "measure": "fatalities per 100k residents",
        "diagnostics": diag,
        "rates": [_asdict(r) for r in rates],
    }, indent=1))
    say(f"{diag['counties']:,} counties, {diag['reliable_counties']:,} with >=20 deaths")
    return {"rates_path": dest, "counties": diag["counties"],
            "reliable": diag["reliable_counties"],
            "excluded_records": diag["connecticut_records_excluded"]}


def handle_county_map(params: dict[str, Any]) -> dict[str, Any]:
    from .render_county import render_county_map

    say = _log(params)
    data = json.loads(store.read_text(str(params["rates_path"])))
    geom = _county_geometry(str(params["geometry_url"]), say)
    html, drawn = render_county_map(data, geom)
    dest = str(params["dest"])
    store.write_text(dest, html)
    return {"map_path": dest, "counties_drawn": drawn}


def _county_geometry(url: str, say) -> dict[str, Any]:
    try:
        raw = _fetch(url, timeout=240)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            shp = next(n for n in z.namelist() if n.endswith(".shp"))
            dbf = next(n for n in z.namelist() if n.endswith(".dbf"))
            return _read_shapefile(z.read(shp), z.read(dbf), key="GEOID")
    except Exception as exc:  # noqa: BLE001
        say(f"county geometry unavailable ({type(exc).__name__}); table only",
            level="warning")
        return {}


_DISPATCH = {
    "roadsafety.source.FARS": handle_fars,
    "roadsafety.source.VMT": handle_vmt,
    "roadsafety.StateRates": handle_state_rates,
    "roadsafety.RateMap": handle_rate_map,
    "roadsafety.source.CountyPopulation": handle_county_population,
    "roadsafety.CountyRates": handle_county_rates,
    "roadsafety.CountyMap": handle_county_map,
}


def handle(payload: dict) -> dict:
    facet = payload["_facet_name"]
    fn = _DISPATCH.get(facet)
    if fn is None:
        raise KeyError(f"no roadsafety handler for {facet!r}")
    return fn(payload)


def facet_names() -> list[str]:
    return sorted(_DISPATCH)


def register_handlers(runner) -> None:
    """RegistryRunner registration — one entrypoint per facet."""
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_poller(poller) -> None:
    for facet_name, fn in _DISPATCH.items():
        poller.register(facet_name, fn)


def register_all_registry_handlers(runner) -> None:
    register_handlers(runner)
