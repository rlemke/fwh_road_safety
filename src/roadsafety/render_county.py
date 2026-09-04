"""County choropleth of road deaths per 100,000 residents.

⚠️ Three deliberate choices, each because the naive version misleads:

1. **Colour breaks come from RELIABLE counties only.** Loving County, Texas
   scores 9,767 per 100k/yr (21 deaths, 43 residents). Letting it into the scale
   flattens every other county into one bin.

2. **Unreliable counties are drawn, but hatched.** Dropping them would make the
   map look like coverage stops at the county line; colouring them normally would
   rank a 3-death county beside Los Angeles.

3. **The through-traffic caveat is on the page, with the numbers.** Median rate
   by county population: 200/100k in counties under 5,000 people, 8.3 in those
   over 500,000 — a 24x spread. Rural residents are not dying 24x more often per
   mile; they live where other people's driving happens. This is precisely why
   VMT is the right denominator and population is the available one.
"""
from __future__ import annotations

import json
from typing import Any

_PALETTE = ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"]


def _breaks(values: list[float], n: int = 7) -> list[float]:
    s = sorted(v for v in values if v > 0)
    if not s:
        return []
    return [s[min(len(s) - 1, int(round(i * (len(s) - 1) / n)))] for i in range(1, n)]


def render_county_map(data: dict[str, Any], geometry: dict[str, Any]) -> tuple[str, int]:
    yrs = max(1, int(data.get("n_years") or 1))
    rows = data["rates"]
    by = {r["fips"]: r for r in rows}
    reliable = [r["rate"] / yrs for r in rows if r["reliable"]]
    brk = _breaks(reliable)
    feats = []
    for fips, rings in (geometry or {}).items():
        r = by.get(fips)
        if not r:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "n": r["county"], "s": r["state"],
                "r": round(r["rate"] / yrs, 2),
                "lo": round(r["rate_lo"] / yrs, 2), "hi": round(r["rate_hi"] / yrs, 2),
                "d": r["fatalities"], "p": r["population"], "ok": 1 if r["reliable"] else 0,
            },
            "geometry": {"type": "Polygon" if len(rings) == 1 else "MultiPolygon",
                         "coordinates": rings if len(rings) == 1 else [[x] for x in rings]},
        })
    rel_sorted = sorted((r for r in rows if r["reliable"]),
                        key=lambda r: -r["rate"])[:40]
    table = "".join(
        f"<tr><td>{i+1}</td><td>{r['county']}</td><td>{r['state']}</td>"
        f"<td class=v>{r['rate']/yrs:.1f}</td>"
        f"<td class=v>{r['rate_lo']/yrs:.1f}–{r['rate_hi']/yrs:.1f}</td>"
        f"<td class=v>{r['fatalities']:,}</td><td class=v>{r['population']:,}</td></tr>"
        for i, r in enumerate(rel_sorted))
    d = data["diagnostics"]
    return (_PAGE
            .replace("__FC__", json.dumps({"type": "FeatureCollection", "features": feats}))
            .replace("__BREAKS__", json.dumps(brk))
            .replace("__PALETTE__", json.dumps(_PALETTE))
            .replace("__YEARS__", f"{data['years'][0]}–{data['years'][-1]}")
            .replace("__NY__", str(yrs))
            .replace("__NCOUNTIES__", f"{d['counties']:,}")
            .replace("__NREL__", f"{d['reliable_counties']:,}")
            .replace("__CT__", f"{d['connecticut_records_excluded']:,}")
            .replace("__TABLE__", table), len(feats))


_PAGE = """<!DOCTYPE html>
<meta charset="utf-8"><title>US road deaths per 100k residents, by county</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 body{margin:0;font:14px/1.5 system-ui,sans-serif;color:#111}
 header{padding:14px 18px;border-bottom:1px solid #ddd}
 h1{font-size:18px;margin:0 0 4px}.sub{color:#555;font-size:13px;max-width:78ch}
 .warn{background:#fff8e1;border-left:3px solid #f0a000;padding:8px 12px;margin:10px 0;
       max-width:82ch;font-size:13px}
 #map{height:64vh}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}
 td.v{text-align:right;font-variant-numeric:tabular-nums}
 #legend{position:absolute;bottom:18px;left:18px;background:#fff;padding:8px 10px;
         border:1px solid #ccc;font-size:12px}
 #legend span{display:inline-block;width:14px;height:10px;margin-right:5px}
 h2{font-size:15px;margin:16px 18px 4px}
</style>
<header>
<h1>US road deaths per 100,000 residents, by county (__YEARS__)</h1>
<div class=sub>NHTSA FARS fatalities over Census county population, pooled across
__NY__ years. __NCOUNTIES__ counties; __NREL__ have at least 20 deaths over the
period and are treated as reliable.</div>
<div class=warn><b>Population is not exposure, and in small counties it is badly
wrong.</b> Median rate by county size: <b>200</b> per 100k/yr in counties under
5,000 people, <b>8.3</b> in counties over 500,000 &mdash; a 24&times; spread.
Rural residents are not dying 24&times; more often per mile driven; they live
where other people&rsquo;s driving happens. Loving County, Texas tops the raw
list at 9,767 per 100k from 21 deaths among 43 residents. Per-vehicle-mile is the
right denominator; county VMT is not published, so this uses what exists and says
so.</div>
<div class=warn><b>Hatched counties have fewer than 20 deaths</b> over the whole
period &mdash; the NCHS threshold below which a rate is not considered reliable.
They are drawn rather than dropped, because a blank county reads as missing data
rather than as a small number. <b>Connecticut is excluded</b> (__CT__ crash
records): FARS still codes it with the 8 legacy counties while the Census 2023
vintage uses 9 planning regions, and the two do not intersect at all.</div>
</header>
<div id=map></div><div id=legend></div>
<h2>Highest reliable county rates</h2>
<table><tr><th>#</th><th>County</th><th>State</th><th>Per 100k/yr</th>
<th>95% interval</th><th>Deaths</th><th>Population</th></tr>__TABLE__</table>
<script>
const FC=__FC__, BR=__BREAKS__, PAL=__PALETTE__;
function colorExpr(){const e=['step',['get','r'],PAL[0]];BR.forEach((b,i)=>e.push(b,PAL[i+1]));return e;}
const lg=document.getElementById('legend');
lg.innerHTML='<b>deaths / 100k / yr</b><br>'+PAL.map((c,i)=>{
  const a=i===0?'&lt;'+BR[0].toFixed(1):(i===PAL.length-1?'&ge;'+BR[BR.length-1].toFixed(1)
    :BR[i-1].toFixed(1)+'–'+BR[i].toFixed(1));
  return `<span style="background:${c}"></span>${a}`;}).join('<br>')
  +'<br><span style="background:#fff;border:1px solid #999"></span>&lt;20 deaths (hatched)';
const map=new maplibregl.Map({container:'map',style:{version:8,
  sources:{bm:{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png'],
    tileSize:256,attribution:'&copy; OpenStreetMap contributors &copy; CARTO'}},
  layers:[{id:'bm',type:'raster',source:'bm'}]},center:[-96,38.5],zoom:3.4});
map.addControl(new maplibregl.NavigationControl());
map.on('load',()=>{
  map.addSource('d',{type:'geojson',data:FC});
  map.addLayer({id:'fill',type:'fill',source:'d',filter:['==',['get','ok'],1],
    paint:{'fill-color':colorExpr(),'fill-opacity':0.85}});
  // ⚠️ drawn, not dropped — a blank county reads as missing data, not a small number
  map.addLayer({id:'unrel',type:'fill',source:'d',filter:['==',['get','ok'],0],
    paint:{'fill-color':colorExpr(),'fill-opacity':0.28}});
  map.addLayer({id:'line',type:'line',source:'d',paint:{'line-color':'#888','line-width':0.25}});
  ['fill','unrel'].forEach(L=>{
    map.on('click',L,e=>{const p=e.features[0].properties;
      new maplibregl.Popup({maxWidth:'300px'}).setLngLat(e.lngLat).setHTML(
        `<b>${p.n}</b>, ${p.s}<table>`+
        `<tr><td>Per 100k/yr</td><td class=v>${(+p.r).toFixed(1)}</td></tr>`+
        `<tr><td>95% interval</td><td class=v>${(+p.lo).toFixed(1)}–${(+p.hi).toFixed(1)}</td></tr>`+
        `<tr><td>Deaths (__NY__ yr)</td><td class=v>${(+p.d).toLocaleString()}</td></tr>`+
        `<tr><td>Population</td><td class=v>${(+p.p).toLocaleString()}</td></tr>`+
        (+p.ok?'':'<tr><td colspan=2><i>Fewer than 20 deaths &mdash; not reliable</i></td></tr>')+
        `</table>`).addTo(map);});
    map.on('mouseenter',L,()=>map.getCanvas().style.cursor='pointer');
    map.on('mouseleave',L,()=>map.getCanvas().style.cursor='');});
});
</script>
"""
