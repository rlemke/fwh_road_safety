"""Named roads coloured by deaths per mile.

⚠️ **Per mile, never per road.** By raw count the deadliest US roads are simply
the longest busy ones — US-1 in Florida (142 deaths in 2023) is 901 miles long.
Dividing by length reorders it completely: short urban arterials rise, long
interstates fall. That reordering is the result.

⚠️ **Per mile is still not per vehicle-mile.** It removes the "long roads have
more crashes" effect but NOT the "busy roads have more crashes" one. A rural
two-lane at 0.5 deaths/mile is genuinely more dangerous than an interstate at
0.5 deaths/mile carrying twenty times the traffic, and this measure cannot tell
them apart. AADT would; it is not currently obtainable.
"""
from __future__ import annotations

import json
from typing import Any

_PALETTE = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]


def _breaks(vals: list[float], n: int = 5) -> list[float]:
    s = sorted(v for v in vals if v > 0)
    if not s:
        return []
    return [s[min(len(s) - 1, int(round(i * (len(s) - 1) / n)))] for i in range(1, n)]


def render_road_map(data: dict[str, Any]) -> tuple[str, int]:
    yrs = max(1, int(data.get("n_years") or 1))
    roads = data["roads"]
    geom = data.get("geometry") or {}
    feats = []
    for r in roads:
        k = f"{r['state_fips']}:{r['rttyp']}:{r['route'].split('-', 1)[1]}"
        lines = geom.get(k)
        if not lines:
            continue
        feats.append({
            "type": "Feature",
            "properties": {"rt": r["route"], "st": r["state"],
                           "pm": round(r["per_mile_year"], 3),
                           "mi": r["miles"], "d": r["fatalities"], "c": r["crashes"]},
            "geometry": {"type": "MultiLineString", "coordinates": lines},
        })
    brk = _breaks([r["per_mile_year"] for r in roads])
    top = sorted(roads, key=lambda r: -r["per_mile_year"])[:40]
    table = "".join(
        f"<tr><td>{i+1}</td><td>{r['route']}</td><td>{r['state']}</td>"
        f"<td class=v>{r['per_mile_year']:.3f}</td><td class=v>{r['miles']:,.0f}</td>"
        f"<td class=v>{r['fatalities']:,}</td></tr>" for i, r in enumerate(top))
    bycount = sorted(roads, key=lambda r: -r["fatalities"])[:10]
    contrast = "".join(
        f"<tr><td>{r['route']}</td><td>{r['state']}</td><td class=v>{r['fatalities']:,}</td>"
        f"<td class=v>{r['miles']:,.0f}</td><td class=v>{r['per_mile_year']:.3f}</td></tr>"
        for r in bycount)
    d = data["diagnostics"]
    return (_PAGE.replace("__FC__", json.dumps({"type": "FeatureCollection", "features": feats}))
            .replace("__BREAKS__", json.dumps(brk)).replace("__PALETTE__", json.dumps(_PALETTE))
            .replace("__YEARS__", f"{data['years'][0]}–{data['years'][-1]}")
            .replace("__NY__", str(yrs)).replace("__NROADS__", f"{len(roads):,}")
            .replace("__OFF__", f"{d['deaths_no_route_in_tway']:,}")
            .replace("__NOGEO__", f"{d['deaths_route_without_geometry']:,}")
            .replace("__TABLE__", table).replace("__CONTRAST__", contrast), len(feats))


_PAGE = """<!DOCTYPE html>
<meta charset="utf-8"><title>US road deaths per mile, by named route</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 body{margin:0;font:14px/1.5 system-ui,sans-serif;color:#111}
 header{padding:14px 18px;border-bottom:1px solid #ddd}
 h1{font-size:18px;margin:0 0 4px}.sub{color:#555;font-size:13px;max-width:80ch}
 .warn{background:#fff8e1;border-left:3px solid #f0a000;padding:8px 12px;margin:10px 0;
       max-width:84ch;font-size:13px}
 #map{height:62vh}
 table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:18px}
 th,td{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}
 td.v{text-align:right;font-variant-numeric:tabular-nums}
 h2{font-size:15px;margin:16px 18px 4px}
 #legend{position:absolute;bottom:18px;left:18px;background:#fff;padding:8px 10px;
         border:1px solid #ccc;font-size:12px}
 #legend span{display:inline-block;width:16px;height:4px;margin-right:6px;vertical-align:middle}
</style>
<header>
<h1>US road deaths per mile, by named route (__YEARS__)</h1>
<div class=sub>NHTSA FARS deaths on each numbered route, divided by that
route&rsquo;s length in the state from Census TIGER. __NROADS__ routes, pooled
over __NY__ years.</div>
<div class=warn><b>Per mile, not per road.</b> By raw count the deadliest US
roads are simply the longest busy ones. Dividing by length reorders the list
completely &mdash; short urban arterials rise, long interstates fall. Both
orderings are shown below so the difference is visible.</div>
<div class=warn><b>Per mile is still not per vehicle-mile.</b> It removes the
&ldquo;long roads have more crashes&rdquo; effect but not the &ldquo;busy roads
have more crashes&rdquo; one: a rural two-lane at 0.5 deaths/mile is genuinely
worse than an interstate at 0.5 carrying twenty times the traffic, and this
measure cannot separate them. AADT would; it is not currently obtainable.
<br><br><b>Coverage:</b> __OFF__ deaths were not on a parseable numbered route
(local streets, unnamed roads) and __NOGEO__ were on a route with no TIGER
geometry. Neither appears on this map, so it under-counts rather than
mis-attributes.</div>
</header>
<div id=map></div><div id=legend></div>
<h2>Deadliest routes per mile</h2>
<table><tr><th>#</th><th>Route</th><th>State</th><th>Deaths/mile/yr</th>
<th>Miles</th><th>Deaths</th></tr>__TABLE__</table>
<h2>&hellip;and by raw count, for contrast</h2>
<table><tr><th>Route</th><th>State</th><th>Deaths</th><th>Miles</th>
<th>Deaths/mile/yr</th></tr>__CONTRAST__</table>
<script>
const FC=__FC__, BR=__BREAKS__, PAL=__PALETTE__;
function colorExpr(){const e=['step',['get','pm'],PAL[0]];BR.forEach((b,i)=>e.push(b,PAL[i+1]));return e;}
document.getElementById('legend').innerHTML='<b>deaths / mile / yr</b><br>'+PAL.map((c,i)=>{
  const a=i===0?'&lt;'+BR[0].toFixed(2):(i===PAL.length-1?'&ge;'+BR[BR.length-1].toFixed(2)
    :BR[i-1].toFixed(2)+'–'+BR[i].toFixed(2));
  return `<span style="background:${c}"></span>${a}`;}).join('<br>');
const map=new maplibregl.Map({container:'map',style:{version:8,
  sources:{bm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    tileSize:256,attribution:'&copy; OpenStreetMap contributors'}},
  layers:[{id:'bg',type:'background',paint:{'background-color':'#eef1f4'}},
          {id:'bm',type:'raster',source:'bm'}]},center:[-96,38.5],zoom:3.6});
map.addControl(new maplibregl.NavigationControl());
// The basemap is decoration; the roads are the data. Drop it rather than fail.
map.on('error',e=>{const m=String((e&&e.error&&e.error.message)||'');
  if(/tile|429|403|key|Failed to fetch/i.test(m)&&map.getLayer&&map.getLayer('bm')){
    try{map.removeLayer('bm');}catch(_){}}});
map.on('load',()=>{
  map.addSource('r',{type:'geojson',data:FC});
  map.addLayer({id:'road',type:'line',source:'r',
    paint:{'line-color':colorExpr(),'line-width':['interpolate',['linear'],['zoom'],3,1.2,10,4]}});
  map.on('click','road',e=>{const p=e.features[0].properties;
    new maplibregl.Popup({maxWidth:'280px'}).setLngLat(e.lngLat).setHTML(
      `<b>${p.rt}</b>, ${p.st}<table>`+
      `<tr><td>Deaths/mile/yr</td><td class=v>${(+p.pm).toFixed(3)}</td></tr>`+
      `<tr><td>Length in state</td><td class=v>${(+p.mi).toLocaleString()} mi</td></tr>`+
      `<tr><td>Deaths (__NY__ yr)</td><td class=v>${(+p.d).toLocaleString()}</td></tr>`+
      `<tr><td>Fatal crashes</td><td class=v>${(+p.c).toLocaleString()}</td></tr>`+
      `</table>`).addTo(map);});
  map.on('mouseenter','road',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','road',()=>map.getCanvas().style.cursor='');
});
</script>
"""
