#!/usr/bin/env python3
"""
make_map.py - Turn drive logs (CSV) into a single-file street map with colored dots.

You normally do NOT run this yourself: the "Make map" button in the RF Noise Map
window calls it. Command line use (optional):
    python3 make_map.py "Drives/drive_2026....csv" -o my_map.html

HOW THE PROGRAM FLOWS
  read the CSV rows -> group them by frequency -> pack them into one HTML file as data
  -> the page's JavaScript draws the dots with Leaflet (a free map library).
  The finished map is ONE self-contained file: you can view it, print it, save it,
  or email it (the street background needs internet when you open it).
"""

import argparse
import base64
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STOPS = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#ffffbf", "#fdae61", "#f46d43", "#d73027", "#a50026"]


def read_vendor(name, mode="r"):
    with open(os.path.join(HERE, "vendor", name), mode) as f:
        return f.read()


def b64(name):
    return base64.b64encode(read_vendor(name, "rb")).decode()


def load_rows(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({
                        "t": r["time_utc"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                        "mph": float(r["speed_mph"] or 0), "f": float(r["freq_mhz"]),
                        "bw": float(r["bw_khz"]), "v": float(r["level_cal"]),
                    })
                except (KeyError, ValueError):
                    continue
    return rows


def group_rows(rows):
    groups = {}
    for r in rows:
        groups.setdefault(f"{r['f']:g}", []).append(
            {"lat": round(r["lat"], 7), "lon": round(r["lon"], 7), "v": round(r["v"], 2),
             "t": r["t"], "mph": r["mph"], "bw": r["bw"]})
    return groups


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__LEAFLET_CSS__
html,body{height:100%;margin:0;font-family:-apple-system,Helvetica,Arial,sans-serif}
#map{position:absolute;inset:0}
.panel{position:absolute;z-index:1000;background:rgba(255,255,255,.95);border-radius:8px;
 box-shadow:0 1px 6px rgba(0,0,0,.4);padding:8px 10px;font-size:13px}
#ctl{top:10px;left:50px;max-width:270px}
#ctl select,#ctl input{font-size:14px}
#ctl input[type=number]{width:62px}
#bar,#pbar{height:14px;border-radius:3px;margin:6px 0 2px}
#barlab,#pbarlab{display:flex;justify-content:space-between;font-size:12px}
#hot{bottom:24px;left:10px;max-height:34%;overflow:auto;width:250px}
#hot div{padding:2px 0;cursor:pointer;border-bottom:1px solid #eee}
#hot div:hover{background:#eef}
.sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;border:1px solid #333}
h4{margin:0 0 4px 0;font-size:13px}
button{font-size:13px;padding:3px 8px}
#printhdr{display:none}
@page{size:landscape;margin:8mm}
@media print{
  html,body{height:auto}
  .panel,.leaflet-control-container{display:none!important}
  #printhdr{display:block;margin:0 0 4mm 0;font-size:12px}
  #printhdr h2{margin:0 0 2px 0;font-size:18px}
  #pbar{width:60%}
  #pbarlab{width:60%}
  #map{position:relative;inset:auto;height:150mm;width:100%;border:1px solid #888}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
</style></head><body>
<div id="printhdr">
 <h2>__TITLE__</h2>
 <div id="pline"></div>
 <div id="pbar"></div><div id="pbarlab"><span id="plo"></span><span>weak &rarr; strong (dB, relative unless calibrated)</span><span id="phi"></span></div>
 <div id="phot"></div>
</div>
<div id="map"></div>
<div id="ctl" class="panel">
 <h4>__TITLE__</h4>
 Frequency: <select id="freq"></select><br>
 Min <input id="mn" type="number" step="1"> Max <input id="mx" type="number" step="1"> dB
 <button id="auto">Auto</button><br>
 Dot size <input id="sz" type="range" min="2" max="12" value="5" style="width:110px">
 <div id="bar"></div>
 <div id="barlab"><span id="lo"></span><span>weak &rarr; strong</span><span id="hi"></span></div>
 <div id="info" style="margin-top:4px;color:#555"></div>
 <div style="margin-top:6px"><button id="print">Print / Save as PDF</button></div>
</div>
<div id="hot" class="panel"><h4>Hottest spots</h4><div id="hotlist"></div></div>
<script>
__LEAFLET_JS__
</script>
<script>
const DATA = __DATA__;   // { "3.7": [ {lat,lon,v,t,mph,bw}, ... ], ... }
const STOPS = __STOPS__;
function hex2rgb(h){return [1,3,5].map(i=>parseInt(h.substr(i,2),16));}
const RGB = STOPS.map(hex2rgb);
function colorAt(f){            // f = 0..1
  f=Math.max(0,Math.min(1,f)); const x=f*(RGB.length-1), i=Math.min(Math.floor(x),RGB.length-2), u=x-i;
  const c=RGB[i].map((a,k)=>Math.round(a+(RGB[i+1][k]-a)*u)); return "rgb("+c.join(",")+")";
}
const GRAD="linear-gradient(to right,"+STOPS.join(",")+")";
document.getElementById("bar").style.background=GRAD;
document.getElementById("pbar").style.background=GRAD;

const map = L.map("map",{preferCanvas:true});
const street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom:19, attribution:"&copy; OpenStreetMap contributors", crossOrigin:true});
const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  {maxZoom:19, attribution:"Tiles &copy; Esri", crossOrigin:true});
street.addTo(map);
L.control.layers({"Street":street,"Satellite":sat}).addTo(map);
L.control.scale({imperial:true,metric:false}).addTo(map);

const sel=document.getElementById("freq"), mn=document.getElementById("mn"), mx=document.getElementById("mx");
const freqs=Object.keys(DATA).sort((a,b)=>+a-+b);
freqs.forEach(f=>{const o=document.createElement("option");o.value=f;o.textContent=(+f)+" MHz  ("+DATA[f].length+" dots)";sel.appendChild(o);});

let group=L.layerGroup().addTo(map), fitted=false, lastPicked=[];

function pct(arr,p){const s=[...arr].sort((a,b)=>a-b);return s[Math.min(s.length-1,Math.max(0,Math.floor(p*(s.length-1))))];}
function autoRange(){
  const vals=DATA[sel.value].map(r=>r.v);
  mn.value=Math.floor(pct(vals,0.02)); mx.value=Math.ceil(pct(vals,0.995));
}
function draw(){
  group.clearLayers();
  const rows=DATA[sel.value], lo=+mn.value, hi=+mx.value, rad=+document.getElementById("sz").value;
  document.getElementById("lo").textContent=lo; document.getElementById("hi").textContent=hi;
  document.getElementById("plo").textContent=lo; document.getElementById("phi").textContent=hi;
  // draw weak first, strong last, so the strong dots sit on top
  const order=[...rows].sort((a,b)=>a.v-b.v);
  order.forEach(r=>{
    const c=colorAt((r.v-lo)/(hi-lo||1));
    L.circleMarker([r.lat,r.lon],{radius:rad,color:"#222",weight:0.6,fillColor:c,fillOpacity:0.92})
     .bindPopup("<b>"+r.v.toFixed(1)+" dB</b><br>"+(+sel.value)+" MHz, "+r.bw+" kHz wide<br>"+
                r.t.replace("T"," ").replace("Z"," UTC")+"<br>"+r.mph.toFixed(0)+" mph<br>"+
                r.lat.toFixed(6)+", "+r.lon.toFixed(6)).addTo(group);
  });
  if(!fitted && rows.length){map.fitBounds(L.latLngBounds(rows.map(r=>[r.lat,r.lon])).pad(0.05));fitted=true;}
  const spread=(Math.max(...rows.map(r=>r.v))-Math.min(...rows.map(r=>r.v))).toFixed(0);
  document.getElementById("info").textContent=rows.length+" dots, spread "+spread+" dB";
  const t0=rows.map(r=>r.t).sort()[0]||"", t1=rows.map(r=>r.t).sort().slice(-1)[0]||"";
  document.getElementById("pline").textContent=(+sel.value)+" MHz   |   "+rows.length+" dots   |   "+
     t0.replace("T"," ").slice(0,16)+" to "+t1.replace("T"," ").slice(0,16)+" UTC   |   spread "+spread+" dB";
  hotspots(rows,lo,hi);
}
function hotspots(rows,lo,hi){
  // strongest readings, skipping any within ~250 ft of one already listed
  const picked=[];
  for(const r of [...rows].sort((a,b)=>b.v-a.v)){
    if(picked.every(p=>Math.hypot((p.lat-r.lat)*364000,(p.lon-r.lon)*364000*Math.cos(r.lat*Math.PI/180))>250)){
      picked.push(r); if(picked.length>=10)break;}
  }
  lastPicked=picked;
  const box=document.getElementById("hotlist"); box.innerHTML="";
  picked.forEach((r,i)=>{
    const d=document.createElement("div");
    d.innerHTML='<span class="sw" style="background:'+colorAt((r.v-lo)/(hi-lo||1))+'"></span>'+(i+1)+". "+r.v.toFixed(1)+" dB";
    d.onclick=()=>{map.setView([r.lat,r.lon],19);L.popup().setLatLng([r.lat,r.lon]).setContent("<b>"+r.v.toFixed(1)+" dB</b><br>"+r.t.replace("T"," ")).openOn(map);};
    box.appendChild(d);
  });
  document.getElementById("phot").innerHTML="<b>Strongest spots:</b> "+picked.slice(0,5).map((r,i)=>
     (i+1)+") "+r.v.toFixed(1)+" dB at "+r.lat.toFixed(5)+", "+r.lon.toFixed(5)).join(" &nbsp; ");
}
sel.onchange=()=>{autoRange();draw();};
mn.onchange=mx.onchange=document.getElementById("sz").oninput=draw;
document.getElementById("auto").onclick=()=>{autoRange();draw();};
if(freqs.length){sel.value=freqs[0];autoRange();draw();}

// ---- printing: resize the map for the page, print, then restore
function doPrint(){ window.print(); }
window.addEventListener("beforeprint",()=>{ map.invalidateSize(); if(group.getLayers().length) map.fitBounds(group.getBounds().pad(0.05)); });
window.addEventListener("afterprint",()=>{ map.invalidateSize(); });
if(window.matchMedia){ const mq=window.matchMedia("print"); const f=e=>{ if(e.matches){ map.invalidateSize(); if(group.getLayers().length) map.fitBounds(group.getBounds().pad(0.05)); } };
  if(mq.addEventListener) mq.addEventListener("change",f); else if(mq.addListener) mq.addListener(f); }
document.getElementById("print").onclick=doPrint;
if(location.search.indexOf("print=1")>=0){ setTimeout(doPrint,3500); }   // lets the street tiles load first
</script></body></html>
"""


def build_map(paths, out, title=None):
    """Create the HTML map. Returns (out_path, {freq: dot_count})."""
    rows = load_rows(paths)
    if not rows:
        raise ValueError("No usable rows found in the CSV (is it empty?).")
    groups = group_rows(rows)

    title = title or "RF noise map - " + os.path.basename(paths[0])
    css = read_vendor("leaflet.css")
    # The layer-switch icon is an image file; embed it so the map is one single file.
    css = css.replace("url(images/layers-2x.png)", f"url(data:image/png;base64,{b64('layers-2x.png')})")
    css = css.replace("url(images/layers.png)", f"url(data:image/png;base64,{b64('layers.png')})")
    js = read_vendor("leaflet.js")
    safe_title = (title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    html = (HTML.replace("__TITLE__", safe_title)
                .replace("__LEAFLET_CSS__", css)
                .replace("__LEAFLET_JS__", js.replace("</script>", "<\\/script>"))
                .replace("__STOPS__", json.dumps(STOPS))
                .replace("__DATA__", json.dumps(groups, separators=(",", ":")).replace("</", "<\\/")))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out, {k: len(v) for k, v in groups.items()}


# ----------------------------------------------------------------------------
# Google Earth export
# ----------------------------------------------------------------------------
def _kml_color(hexrgb, alpha="ff"):
    r, g, b = hexrgb[1:3], hexrgb[3:5], hexrgb[5:7]
    return alpha + b + g + r                      # KML wants aabbggrr


def export_kml(paths, out, freq=None, title="RF noise map"):
    """Colored dots for Google Earth. One folder per frequency (or just `freq`)."""
    groups = group_rows(load_rows(paths))
    if freq is not None:
        groups = {k: v for k, v in groups.items() if float(k) == float(freq)}
    if not groups:
        raise ValueError("No data for that frequency.")
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{esc(title)}</name>"]
    for i, c in enumerate(STOPS):
        parts.append(f'<Style id="s{i}"><IconStyle><color>{_kml_color(c)}</color><scale>0.45</scale>'
                     '<Icon><href>http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href></Icon>'
                     '</IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>')
    for k in sorted(groups, key=float):
        rows = groups[k]
        vals = sorted(r["v"] for r in rows)
        lo = vals[int(0.02 * (len(vals) - 1))]
        hi = vals[int(0.995 * (len(vals) - 1))]
        parts.append(f"<Folder><name>{k} MHz</name>")
        for r in rows:
            f = (r["v"] - lo) / ((hi - lo) or 1)
            idx = max(0, min(len(STOPS) - 1, int(round(f * (len(STOPS) - 1)))))
            parts.append(f'<Placemark><name>{r["v"]:.1f} dB</name><styleUrl>#s{idx}</styleUrl>'
                         f'<description>{k} MHz, {r["v"]:.1f} dB, {r["t"]}</description>'
                         f'<Point><coordinates>{r["lon"]},{r["lat"]},0</coordinates></Point></Placemark>')
        parts.append("</Folder>")
    parts.append("</Document></kml>")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    return out


def main():
    ap = argparse.ArgumentParser(description="Build a colored-dot street map from drive CSV file(s)")
    ap.add_argument("csv", nargs="+", help="one or more CSV files (wildcards ok)")
    ap.add_argument("-o", "--out", help="output HTML file (default: next to the first CSV)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--kml", action="store_true", help="write a Google Earth .kml instead")
    args = ap.parse_args()

    paths = []
    for p in args.csv:
        paths.extend(sorted(glob.glob(p)) or [p])
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        sys.exit(f"File not found: {missing[0]}")
    try:
        if args.kml:
            out = args.out or os.path.splitext(paths[0])[0] + ".kml"
            export_kml(paths, out, title=args.title or "RF noise map")
            print(f"KML written: {out}")
        else:
            out = args.out or os.path.splitext(paths[0])[0] + "_map.html"
            out, counts = build_map(paths, out, args.title)
            print(f"Map written: {out}\n  dots per frequency -> " +
                  ", ".join(f"{k} MHz: {v}" for k, v in sorted(counts.items(), key=lambda kv: float(kv[0]))))
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
