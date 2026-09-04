"""Choropleth of the fatal-crash rate, with the uncertainty shown.

⚠️ The map renders the RATE, never the count. A count choropleth of fatal
crashes is a population map: California, Texas and Florida lead it because that
is where the driving happens. The rate reorders it completely — Mississippi and
Arizona lead, Massachusetts and Minnesota trail — and that reordering IS the
result.

⚠️ The Poisson interval is in the popup because a rate built on 342 deaths
(Massachusetts) is not comparable to one built on 3,800 (Texas), and a
choropleth invites exactly that comparison. Colour encodes the point estimate;
the popup says how much to trust it.
"""
from __future__ import annotations

import json
from typing import Any

# Sequential, colour-blind-safe (ColorBrewer YlOrRd), light -> dark = safer -> worse.
_PALETTE = ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"]


def _breaks(values: list[float], n: int = 6) -> list[float]:
    """Quantile breaks. ⚠️ Quantile, not equal-interval: state rates cluster
    between 0.5 and 1.8, and equal intervals would put 40 states in one bin."""
    s = sorted(v for v in values if v > 0)
    if not s:
        return []
    return [s[min(len(s) - 1, int(round(i * (len(s) - 1) / n)))] for i in range(1, n)]


def render_rate_map(data: dict[str, Any], geometry: dict[str, Any]) -> tuple[str, int]:
    rates = data["rates"]
    by_fips = {f"{r['state_fips']:02d}": r for r in rates}
    feats = []
    for fips, rings in (geometry or {}).items():
        r = by_fips.get(fips)
        if not r:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "name": r["state"], "rate": round(r["rate"], 3),
                "lo": round(r["rate_lo"], 3), "hi": round(r["rate_hi"], 3),
                "deaths": r["fatalities"], "crashes": r["crashes"],
                "vmt": round(r["vmt_millions"]),
            },
            "geometry": {"type": "Polygon" if len(rings) == 1 else "MultiPolygon",
                         "coordinates": rings if len(rings) == 1 else [[x] for x in rings]},
        })
    fc = {"type": "FeatureCollection", "features": feats}
    brk = _breaks([r["rate"] for r in rates])
    table = "".join(
        f"<tr><td>{i+1}</td><td>{r['state']}</td><td class=v>{r['rate']:.2f}</td>"
        f"<td class=v>{r['rate_lo']:.2f}–{r['rate_hi']:.2f}</td>"
        f"<td class=v>{r['fatalities']:,}</td><td class=v>{r['vmt_millions']:,.0f}</td></tr>"
        for i, r in enumerate(rates))
    html = _PAGE.replace("__FC__", json.dumps(fc)) \
                .replace("__BREAKS__", json.dumps(brk)) \
                .replace("__PALETTE__", json.dumps(_PALETTE)) \
                .replace("__YEAR__", str(data["year"])) \
                .replace("__NAT__", f"{data['national_rate_per_100m_vmt']:.2f}") \
                .replace("__DEATHS__", f"{data['fatalities']:,}") \
                .replace("__VMT__", f"{data['vmt_millions']/1e6:.2f}") \
                .replace("__NSTATES__", str(len(rates))) \
                .replace("__TABLE__", table)
    return html, len(feats)


_PAGE = """<!DOCTYPE html>
<meta charset="utf-8"><title>US fatal-crash rate, __YEAR__</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
 body{margin:0;font:14px/1.5 system-ui,sans-serif;color:#111}
 header{padding:14px 18px;border-bottom:1px solid #ddd}
 h1{font-size:18px;margin:0 0 4px}
 .sub{color:#555;font-size:13px;max-width:70ch}
 .warn{background:#fff8e1;border-left:3px solid #f0a000;padding:8px 12px;margin:10px 0;
       max-width:80ch;font-size:13px}
 #map{height:62vh}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}
 td.v{text-align:right;font-variant-numeric:tabular-nums}
 #legend{position:absolute;bottom:18px;left:18px;background:#fff;padding:8px 10px;
         border:1px solid #ccc;font-size:12px}
 #legend span{display:inline-block;width:14px;height:10px;margin-right:5px}
</style>
<header>
<h1>Fatal-crash rate by state, __YEAR__</h1>
<div class=sub>Deaths per 100 million vehicle-miles travelled.
NHTSA FARS fatalities over FHWA Highway Statistics VM-2 exposure.
National: <b>__NAT__</b> per 100M VMT (__DEATHS__ deaths over __VMT__ trillion miles,
__NSTATES__ states).</div>
<div class=warn><b>This is a fatal-crash measure, not a &ldquo;dangerous roads&rdquo;
measure.</b> FARS records fatal crashes only. Fatal crashes concentrate on
high-speed rural roads; injury crashes concentrate on urban arterials, so this
map and a high-injury network disagree almost everywhere. The interval in each
popup is a Poisson 95% interval &mdash; a rate built on a few hundred deaths is
not comparable to one built on thousands.</div>
</header>
<div id=map></div><div id=legend></div>
<table><tr><th>#</th><th>State</th><th>Rate</th><th>95% interval</th>
<th>Deaths</th><th>VMT (M)</th></tr>__TABLE__</table>
<script>
const FC=__FC__, BR=__BREAKS__, PAL=__PALETTE__;
function colorExpr(){const e=['step',['get','rate'],PAL[0]];
  BR.forEach((b,i)=>{e.push(b,PAL[i+1]);});return e;}
const lg=document.getElementById('legend');
lg.innerHTML='<b>per 100M VMT</b><br>'+PAL.map((c,i)=>{
  const a=i===0?'&lt;'+BR[0].toFixed(2):(i===PAL.length-1?'&ge;'+BR[BR.length-1].toFixed(2)
      :BR[i-1].toFixed(2)+'–'+BR[i].toFixed(2));
  return `<span style="background:${c}"></span>${a}`;}).join('<br>');
const map=new maplibregl.Map({container:'map',style:{version:8,
  sources:{bm:{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png'],
    tileSize:256,attribution:'&copy; OpenStreetMap contributors &copy; CARTO'}},
  layers:[{id:'bm',type:'raster',source:'bm'}]},center:[-96,38.5],zoom:3.2});
map.addControl(new maplibregl.NavigationControl());
map.on('load',()=>{
  map.addSource('d',{type:'geojson',data:FC});
  map.addLayer({id:'fill',type:'fill',source:'d',
    paint:{'fill-color':colorExpr(),'fill-opacity':0.8}});
  map.addLayer({id:'line',type:'line',source:'d',paint:{'line-color':'#666','line-width':0.5}});
  map.on('click','fill',e=>{const p=e.features[0].properties;
    new maplibregl.Popup({maxWidth:'290px'}).setLngLat(e.lngLat).setHTML(
      `<b>${p.name}</b><table>`+
      `<tr><td>Rate</td><td class=v>${(+p.rate).toFixed(2)}</td></tr>`+
      `<tr><td>95% interval</td><td class=v>${(+p.lo).toFixed(2)}–${(+p.hi).toFixed(2)}</td></tr>`+
      `<tr><td>Deaths</td><td class=v>${(+p.deaths).toLocaleString()}</td></tr>`+
      `<tr><td>Fatal crashes</td><td class=v>${(+p.crashes).toLocaleString()}</td></tr>`+
      `<tr><td>VMT (millions)</td><td class=v>${(+p.vmt).toLocaleString()}</td></tr>`+
      `</table>`).addTo(map);});
  map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
});
</script>
"""
