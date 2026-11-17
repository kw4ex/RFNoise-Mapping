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
import bisect
import calendar
import csv
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

STOPS = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#ffffbf", "#fdae61", "#f46d43", "#d73027", "#a50026"]


def read_vendor(name, mode="r"):
    with open(os.path.join(HERE, "vendor", name), mode) as f:
        return f.read()


def b64(name):
    return base64.b64encode(read_vendor(name, "rb")).decode()


def _meta_for(csv_path):
    try:
        with open(csv_path[:-4] + ".meta.json") as f:
            return json.load(f)
    except Exception:
        return {}


def infer_slots(csv_path):
    """Older drive files have no slot / radio columns. The drive's info file lists the frequencies in slot order,
    so the slot and radio can be worked out from the frequency: {freq_mhz: (slot, radio)}."""
    out = {}
    for i, c in enumerate(_meta_for(csv_path).get("channels", []) or []):
        try:
            out.setdefault(round(float(c["mhz"]), 6), (int(c.get("slot") or (i + 1)), str(c.get("radio") or "")))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def load_rows(paths):
    rows = []
    for p in paths:
        guess = None
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    fq = float(r["freq_mhz"])
                    slot, radio = (r.get("slot") or "").strip(), (r.get("radio") or "").strip()
                    if not slot:
                        if guess is None:
                            guess = infer_slots(p)
                        g = guess.get(round(fq, 6))
                        slot, radio = (str(g[0]), g[1]) if g else ("", radio)
                    rows.append({
                        "t": r["time_utc"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                        "mph": float(r["speed_mph"] or 0), "f": fq,
                        "bw": float(r["bw_khz"]), "v": float(r["level_cal"]),
                        "pt": (r.get("pos_time_utc") or r["time_utc"]),
                        "slot": int(slot) if slot.isdigit() else 0, "radio": radio,
                    })
                except (KeyError, ValueError, TypeError):
                    continue
    return rows


def clean_filters(flt):
    """Make the 'only use these readings' choices safe: lists of numbers / names, plain numbers for ranges."""
    flt = dict(flt or {})
    out = {}
    def nums(k, conv):
        v = flt.get(k)
        if isinstance(v, (list, tuple)) and v:
            try:
                out[k] = [conv(x) for x in v]
            except (TypeError, ValueError):
                pass
    nums("slots", int)
    nums("freqs", float)
    v = flt.get("radios")
    if isinstance(v, (list, tuple)) and v:
        out["radios"] = [str(x) for x in v]
    for k in ("mph_min", "mph_max", "db_min", "db_max"):
        try:
            if flt.get(k) not in (None, ""):
                out[k] = float(flt[k])
        except (TypeError, ValueError):
            pass
    return out


def filter_rows(rows, flt, stage="pre"):
    """pre  = choices that do not depend on the dot spacing (slot, radio, frequency)
       post = choices on the finished dots (speed, level)"""
    if not flt:
        return rows
    if stage == "pre":
        sl, rd, fr = flt.get("slots"), flt.get("radios"), flt.get("freqs")
        return [r for r in rows
                if (not sl or r["slot"] in sl) and (not rd or r["radio"] in rd)
                and (not fr or any(abs(r["f"] - x) < 1e-6 for x in fr))]
    a, b, c, d = flt.get("mph_min"), flt.get("mph_max"), flt.get("db_min"), flt.get("db_max")
    return [r for r in rows
            if (a is None or r["mph"] >= a) and (b is None or r["mph"] <= b)
            and (c is None or r["v"] >= c) and (d is None or r["v"] <= d)]


def filter_tag(flt):
    """A short piece of the map's file name, so a limited map does not overwrite the full one."""
    t = ""
    if flt.get("slots"):
        t += "_slot" + "".join(str(x) for x in sorted(flt["slots"]))
    if flt.get("radios"):
        t += "_" + "-".join(flt["radios"])
    if flt.get("freqs"):
        t += "_f" + "-".join("%g" % x for x in flt["freqs"])
    if "mph_min" in flt or "mph_max" in flt:
        t += "_spd"
    if "db_min" in flt or "db_max" in flt:
        t += "_lvl"
    return t[:60]


def describe_filters(flt):
    """A short sentence for the map title: what the map was limited to."""
    bits = []
    if flt.get("slots"):
        bits.append("slot " + ",".join(str(x) for x in sorted(flt["slots"])))
    if flt.get("radios"):
        bits.append("radio " + ",".join(flt["radios"]))
    if flt.get("freqs"):
        bits.append(",".join("%g" % x for x in flt["freqs"]) + " MHz")
    if "mph_min" in flt or "mph_max" in flt:
        bits.append("speed %s-%s mph" % (("%g" % flt["mph_min"]) if "mph_min" in flt else "0",
                                         ("%g" % flt["mph_max"]) if "mph_max" in flt else "any"))
    if "db_min" in flt or "db_max" in flt:
        bits.append("level %s to %s dB" % (("%g" % flt["db_min"]) if "db_min" in flt else "any",
                                           ("%g" % flt["db_max"]) if "db_max" in flt else "any"))
    return ", ".join(bits)


def group_rows(rows):
    """One group per frequency. If the same frequency is used in two slots, each slot gets its own group,
    labelled '7.2 [slot 2]'."""
    slots_of = {}
    for r in rows:
        slots_of.setdefault(f"{r['f']:g}", set()).add(r["slot"])
    groups = {}
    for r in rows:
        k = f"{r['f']:g}"
        if len(slots_of[k]) > 1:
            k += " [slot %d]" % r["slot"]
        groups.setdefault(k, []).append(
            {"lat": round(r["lat"], 7), "lon": round(r["lon"], 7), "v": round(r["v"], 2),
             "t": r["t"], "mph": r["mph"], "bw": r["bw"]})
    return groups


def key_mhz(k):
    """'7.2 [slot 2]' -> 7.2"""
    return float(str(k).split()[0])


MIN_SPAN_DB = 10.0      # a colour scale narrower than this makes a quiet channel look like it has hot spots
FLAT_DB = 6.0           # a channel that moved less than this in total is called flat


def colour_range(vals):
    """Low / high of the colour scale for one frequency: the 2nd to 99.5th percentile, but never narrower than
    MIN_SPAN_DB. Returns (lo, hi, flat)."""
    v = sorted(vals)
    lo = v[int(0.02 * (len(v) - 1))]
    hi = v[int(0.995 * (len(v) - 1))]
    lo = math.floor(lo)
    hi = math.ceil(hi)
    if hi - lo < MIN_SPAN_DB:
        hi = lo + MIN_SPAN_DB
    return lo, hi, (v[-1] - v[0]) < FLAT_DB


# ----------------------------------------------------------------------------
# Hot spots: places where several frequencies rise together
# ----------------------------------------------------------------------------
HOT_RADIUS_FT = 150.0       # readings this close together count as the same place
PASS_GAP_S = 60.0           # elevated readings more than this far apart in time are different passes


def find_hotspots(groups, max_spots=12):
    """A noise source (a bad insulator, a faulty LED lamp) usually raises several frequencies at once.
    For each frequency, 'raised' means well above that frequency's usual level (the median): at least
    6 dB, or 2.5 times its normal wobble if that is more. Flat channels are skipped. Raised readings
    from different frequencies that sit within 150 ft of each other are one place. Places with two or
    more frequencies are returned, best first."""
    pts = []                                              # (rise, freqkey, lat, lon, t_epoch, level)
    for k, rows in groups.items():
        if len(rows) < 8:
            continue
        vals = sorted(r["v"] for r in rows)
        if vals[-1] - vals[0] < FLAT_DB:
            continue
        med = vals[len(vals) // 2]
        dev = sorted(abs(x - med) for x in vals)
        sigma = 1.4826 * dev[len(dev) // 2]
        thr = max(6.0, 2.5 * sigma)
        for r in rows:
            if r["v"] - med >= thr:
                try:
                    te = _epoch(r["t"])
                except Exception:
                    te = 0.0
                pts.append((r["v"] - med, k, r["lat"], r["lon"], te, r["v"]))
    pts.sort(reverse=True)
    used = [False] * len(pts)
    spots = []
    for i, p in enumerate(pts):
        if used[i]:
            continue
        members = []
        for j, q in enumerate(pts):
            if not used[j] and _dist_ft(p[2], p[3], q[2], q[3]) <= HOT_RADIUS_FT:
                members.append(q)
                used[j] = True
        per = {}
        for q in members:
            if q[1] not in per or q[0] > per[q[1]][0]:
                per[q[1]] = q
        if len(per) < 2:
            continue
        ts = sorted(q[4] for q in members)
        passes = 1 + sum(1 for a, b in zip(ts, ts[1:]) if b - a > PASS_GAP_S)
        spots.append({"lat": round(sum(q[2] for q in members) / len(members), 6),
                      "lon": round(sum(q[3] for q in members) / len(members), 6),
                      "n": len(per), "passes": passes,
                      "total": round(sum(q[0] for q in per.values()), 1),
                      "t": _iso(ts[0]) if ts[0] else "",
                      "items": [[k, round(q[0], 1), round(q[5], 1)] for k, q in
                                sorted(per.items(), key=lambda kv: -kv[1][0])]})
    spots.sort(key=lambda sp: (-sp["n"], -sp["passes"], -sp["total"]))
    return spots[:max_spots]


# ----------------------------------------------------------------------------
# Re-spacing the dots by distance (done when the map is made, not while driving)
# ----------------------------------------------------------------------------
FT_PER_M = 3.28084


def _epoch(iso):
    """'2026-11-14T03:21:07.482Z' -> seconds since 1970 (UTC), millisecond precision."""
    s = iso.strip().rstrip("Z")
    try:
        d = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        d = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(d.timetuple()) + d.microsecond / 1e6


def _iso(t):
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dist_ft(lat1, lon1, lat2, lon2):
    mlat = math.radians((lat1 + lat2) / 2.0)
    dy = (lat2 - lat1) * 111_320.0
    dx = (lon2 - lon1) * 111_320.0 * math.cos(mlat)
    return math.hypot(dx, dy) * FT_PER_M


def _build_track(rows):
    """One position per moment in time, with how far along the route (feet) the vehicle was then.
    Small wobbles while standing still (GPS drift) are ignored: the distance only grows after the
    vehicle has moved at least 3 ft from the last counted spot."""
    pts = {}
    for r in rows:
        pts.setdefault(_epoch(r["pt"]), (r["lat"], r["lon"]))
    times = sorted(pts)
    lats, lons, cum = [], [], []
    total, anchor = 0.0, None
    for t in times:
        la, lo = pts[t]
        if anchor is None:
            anchor = (la, lo)
        else:
            step = _dist_ft(anchor[0], anchor[1], la, lo)
            if step >= 3.0:
                total += step
                anchor = (la, lo)
        lats.append(la)
        lons.append(lo)
        cum.append(total)
    return times, lats, lons, cum


def _interp(times, vals, t):
    i = bisect.bisect_right(times, t)
    if i <= 0:
        return vals[0]
    if i >= len(times):
        return vals[-1]
    t0, t1 = times[i - 1], times[i]
    if t1 <= t0:
        return vals[i]
    u = (t - t0) / (t1 - t0)
    return vals[i - 1] + (vals[i] - vals[i - 1]) * u


def thin_rows(rows, spacing_ft, pick="peak"):
    """Keep one dot per `spacing_ft` of route, per frequency.
    pick = "peak"    -> the strongest reading in each stretch (best for hunting noise)
           "average" -> the power average of the readings in each stretch
    Distance comes from the clock: each reading's time is placed on the GPS track, so the spacing
    follows how far the vehicle really travelled, whatever the sample rate was."""
    if not spacing_ft or spacing_ft <= 0 or not rows:
        return rows
    times, lats, lons, cum = _build_track(rows)
    buckets = {}
    for r in rows:
        t = _epoch(r["t"])
        d = _interp(times, cum, t)
        la = _interp(times, lats, t)
        lo = _interp(times, lons, t)
        key = (f"{r['f']:g}", int(d // spacing_ft))
        buckets.setdefault(key, []).append((t, la, lo, r))
    out = []
    for (_, _b), items in buckets.items():
        if pick == "average":
            pw = [10 ** (it[3]["v"] / 10.0) for it in items]
            v = 10.0 * math.log10(sum(pw) / len(pw))
            t = sorted(it[0] for it in items)[len(items) // 2]
            la = sum(it[1] for it in items) / len(items)
            lo = sum(it[2] for it in items) / len(items)
            base = dict(items[0][3])
            base.update(lat=la, lon=lo, v=v, t=_iso(t),
                        mph=sum(it[3]["mph"] for it in items) / len(items))
        else:
            t, la, lo, r0 = max(items, key=lambda it: it[3]["v"])
            base = dict(r0)
            base.update(lat=la, lon=lo)
        out.append(base)
    out.sort(key=lambda r: r["t"])
    return out


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
#ctl{top:10px;left:50px;width:292px;max-height:calc(100vh - 24px);overflow:auto}
#ctl details{margin-top:5px;border-top:1px solid #ddd;padding-top:4px}
#ctl summary{cursor:pointer;font-weight:600;font-size:13px}
#ctl label{white-space:nowrap}
#ctl .sm{font-size:12px;color:#555}
#ctl .tg{display:block;margin:2px 0}
#ctl select,#ctl input{font-size:14px}
#ctl input[type=number]{width:62px}
#bar,#pbar{height:14px;border-radius:3px;margin:6px 0 2px}
#barlab,#pbarlab{display:flex;justify-content:space-between;font-size:12px}
#hot{bottom:24px;left:10px;max-height:34%;overflow:auto;width:250px}
#multi{top:10px;right:56px;max-height:46%;overflow:auto;width:290px}
#multi div.sp{padding:3px 0;cursor:pointer;border-bottom:1px solid #eee}
#multi div.sp:hover{background:#eef}
#multi small{color:#555}
#flat{display:none;margin-top:4px;padding:3px 6px;background:#fff3cd;border:1px solid #e0c36a;border-radius:4px;font-size:12px}
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
 <div id="pmulti"></div>
</div>
<div id="map"></div>
<div id="ctl" class="panel">
 <h4>__TITLE__</h4>
 Frequency: <select id="freq"></select><br>
 Min <input id="mn" type="number" step="1"> Max <input id="mx" type="number" step="1"> dB
 <button id="auto">Auto</button><br>
 Dot size <input id="sz" type="range" min="2" max="12" value="5" style="width:80px"> see-through <input id="op" type="range" min="15" max="100" value="92" style="width:62px" title="Left = more see-through">
 <div id="bar"></div>
 <div id="barlab"><span id="lo"></span><span>weak &rarr; strong</span><span id="hi"></span></div>
 <div id="info" style="margin-top:4px;color:#555"></div>
 <div id="flat"></div>
 <details open><summary>Background and what to show</summary>
  Background <select id="basesel" style="max-width:200px"></select>
  <div class="sm">Terrain, topo and USGS are free public map layers; &ldquo;No background&rdquo; works without internet.</div>
  <label class="tg"><input type="checkbox" id="tgDots" checked> Dots</label>
  <label class="tg"><input type="checkbox" id="tgHeat"> Heat glow (smooth areas of noise)</label>
  <label class="tg"><input type="checkbox" id="tgMarks" checked> &#128681; Marked spots</label>
  <label class="tg"><input type="checkbox" id="tgPower"> Power lines &amp; poles (OpenStreetMap)</label>
  <div class="sm" id="powerMsg"></div>
  Also show <select id="freq2"><option value="">(nothing)</option></select> as rings
  <div class="sm" id="f2info"></div>
 </details>
 <details><summary>Replay the drive</summary>
  <button id="pPlay" title="Play / pause">&#9654;</button>
  <input id="pSl" type="range" min="0" max="1000" value="1000" style="width:110px">
  <select id="pSpd"><option value="10">10&times;</option><option value="30" selected>30&times;</option><option value="100">100&times;</option><option value="300">300&times;</option></select>
  <div class="sm" id="pNow">Drag the slider or press play to watch the dots appear in the order they were recorded. Slide fully right for the normal view.</div>
 </details>
 <div style="margin-top:6px"><button id="print">Print / Save as PDF</button></div>
</div>
<div id="hot" class="panel"><h4>Hottest spots</h4><div id="hotlist"></div></div>
<div id="multi" class="panel"><h4>Same place, several frequencies</h4><label style="font-size:12px"><input type="checkbox" id="hotmark" checked> mark them on the map</label><div id="multilist"></div></div>
<script>
__LEAFLET_JS__
</script>
<script>
const DATA = __DATA__;   // { "3.7": [ {lat,lon,v,t,mph,bw}, ... ], ... }
const MARKS = __MARKS__;  // spots flagged with 'Mark this spot' while driving: [lat, lon, number, note, time, drive]
const HOT = __HOT__;     // places where 2 or more frequencies rose together
const MINSPAN = __MINSPAN__, FLATDB = __FLATDB__;
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

const map = L.map("map",{preferCanvas:true,maxZoom:19});
const OSMA="&copy; OpenStreetMap contributors", ESRI="Tiles &copy; Esri", ES="https://server.arcgisonline.com/ArcGIS/rest/services/";
const TL=(u,o)=>L.tileLayer(u,Object.assign({maxZoom:19,crossOrigin:true},o||{}));
const BASES={
 "Street (OpenStreetMap)":TL("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:OSMA}),
 "Satellite":TL(ES+"World_Imagery/MapServer/tile/{z}/{y}/{x}",{attribution:ESRI}),
 "Satellite + street names":L.layerGroup([TL(ES+"World_Imagery/MapServer/tile/{z}/{y}/{x}",{attribution:ESRI}),
    TL(ES+"Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}"),TL(ES+"Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}")]),
 "Terrain (OpenTopoMap)":TL("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",{maxNativeZoom:17,attribution:OSMA+", SRTM | &copy; OpenTopoMap (CC-BY-SA)"}),
 "Topo (Esri)":TL(ES+"World_Topo_Map/MapServer/tile/{z}/{y}/{x}",{attribution:ESRI}),
 "USGS imagery (US only)":TL("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",{maxNativeZoom:16,attribution:"USGS The National Map"}),
 "USGS topo (US only)":TL("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",{maxNativeZoom:16,attribution:"USGS The National Map"}),
 "Light grey (dots stand out)":TL("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",{subdomains:"abcd",attribution:OSMA+" &copy; CARTO"}),
 "Dark":TL("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",{subdomains:"abcd",attribution:OSMA+" &copy; CARTO"}),
 "No background (works offline)":L.layerGroup([])
};
let baseName="Street (OpenStreetMap)", baseLayer=null;
try{ const b=localStorage.getItem("rfmapBase"); if(b&&BASES[b]) baseName=b; }catch(e){}
function setBase(n){ if(!BASES[n]) return; if(baseLayer) map.removeLayer(baseLayer); baseLayer=BASES[n]; baseLayer.addTo(map); if(baseLayer.bringToBack) baseLayer.bringToBack(); baseName=n; try{localStorage.setItem("rfmapBase",n);}catch(e){} }
const bsel=document.getElementById("basesel");
Object.keys(BASES).forEach(n=>{const o=document.createElement("option");o.value=o.textContent=n;bsel.appendChild(o);});
bsel.value=baseName; setBase(baseName); bsel.onchange=()=>setBase(bsel.value);
function geoLinks(la,lo){ const q=la.toFixed(6)+","+lo.toFixed(6), a=(u,t)=>'<a target="_blank" rel="noopener" href="'+u+'">'+t+'</a>';
  return '<div style="margin-top:4px">'+a("https://www.google.com/maps/@?api=1&map_action=pano&viewpoint="+q,"Street View")+' &middot; '+
    a("https://www.google.com/maps/dir/?api=1&destination="+q,"Navigate")+' &middot; '+a("https://maps.apple.com/?daddr="+q,"Apple Maps")+'</div>'; }
L.control.scale({imperial:true,metric:false}).addTo(map);

const sel=document.getElementById("freq"), mn=document.getElementById("mn"), mx=document.getElementById("mx");
const freqs=Object.keys(DATA).sort((a,b)=>parseFloat(a)-parseFloat(b));
freqs.forEach(f=>{const o=document.createElement("option");o.value=f;o.textContent=f+" MHz  ("+DATA[f].length+" dots)";sel.appendChild(o);});

const heatLayer=L.layerGroup().addTo(map), group2=L.layerGroup().addTo(map);
let group=L.layerGroup().addTo(map), fitted=false, lastPicked=[];

function pct(arr,p){const s=[...arr].sort((a,b)=>a-b);return s[Math.min(s.length-1,Math.max(0,Math.floor(p*(s.length-1))))];}
function rangeOf(vals){ let lo=Math.floor(pct(vals,0.02)), hi=Math.ceil(pct(vals,0.995)); if(hi-lo<MINSPAN) hi=lo+MINSPAN; return [lo,hi]; }
function autoRange(){
  const r=rangeOf(DATA[sel.value].map(r=>r.v)); mn.value=r[0]; mx.value=r[1];   // a quiet channel must not be stretched into a rainbow
}
function dotOp(){ return (+document.getElementById("op").value)/100; }
function dotMarker(r,lo,hi,rad,op){
  return L.circleMarker([r.lat,r.lon],{radius:rad,color:"#222",weight:0.6,opacity:Math.min(1,op+0.1),fillColor:colorAt((r.v-lo)/(hi-lo||1)),fillOpacity:op})
   .bindPopup("<b>"+r.v.toFixed(1)+" dB</b><br>"+sel.value+" MHz, "+r.bw+" kHz wide<br>"+
              r.t.replace("T"," ").replace("Z"," UTC")+"<br>"+r.mph.toFixed(0)+" mph<br>"+
              r.lat.toFixed(6)+", "+r.lon.toFixed(6)+geoLinks(r.lat,r.lon));
}
function draw(){
  pbStop();
  group.clearLayers();
  const rows=DATA[sel.value], lo=+mn.value, hi=+mx.value, rad=+document.getElementById("sz").value, op=dotOp();
  document.getElementById("lo").textContent=lo; document.getElementById("hi").textContent=hi;
  document.getElementById("plo").textContent=lo; document.getElementById("phi").textContent=hi;
  // draw weak first, strong last, so the strong dots sit on top
  [...rows].sort((a,b)=>a.v-b.v).forEach(r=>dotMarker(r,lo,hi,rad,op).addTo(group));
  if(!fitted && rows.length){map.fitBounds(L.latLngBounds(rows.map(r=>[r.lat,r.lon])).pad(0.05));fitted=true;}
  const spread=(Math.max(...rows.map(r=>r.v))-Math.min(...rows.map(r=>r.v))).toFixed(0);
  document.getElementById("info").textContent=rows.length+" dots, spread "+spread+" dB";
  const fl=document.getElementById("flat"), flat=(+spread)<FLATDB;
  fl.style.display=flat?"block":"none";
  fl.textContent=flat?"FLAT: this frequency moved only "+spread+" dB along the whole route, so nothing stands out. The colours are spread over a "+MINSPAN+" dB scale so small wobbles do not look like hot spots.":"";
  document.querySelector("#hot h4").textContent=flat?"Highest readings (flat channel)":"Hottest spots";
  const t0=rows.map(r=>r.t).sort()[0]||"", t1=rows.map(r=>r.t).sort().slice(-1)[0]||"";
  document.getElementById("pline").textContent=sel.value+" MHz   |   "+rows.length+" dots   |   "+
     t0.replace("T"," ").slice(0,16)+" to "+t1.replace("T"," ").slice(0,16)+" UTC   |   spread "+spread+" dB";
  hotspots(rows,lo,hi);
  drawHeat(); draw2();
}
// ---- heat glow: big soft translucent discs that add up where readings are strong
function drawHeat(){
  heatLayer.clearLayers();
  if(!document.getElementById("tgHeat").checked) return;
  const rows=DATA[sel.value], lo=+mn.value, hi=+mx.value;
  [...rows].sort((a,b)=>a.v-b.v).forEach(r=>L.circleMarker([r.lat,r.lon],{radius:20,stroke:false,fillColor:colorAt((r.v-lo)/(hi-lo||1)),fillOpacity:0.13,interactive:false}).addTo(heatLayer));
}
// ---- a second frequency drawn as rings around the dots
const f2=document.getElementById("freq2");
freqs.forEach(f=>{const o=document.createElement("option");o.value=f;o.textContent=f+" MHz";f2.appendChild(o);});
function draw2(){
  group2.clearLayers(); const k=f2.value, inf=document.getElementById("f2info"); inf.textContent="";
  if(!k||!DATA[k]) return;
  const rows=DATA[k], r2=rangeOf(rows.map(r=>r.v)), rad=+document.getElementById("sz").value+4, op=Math.min(1,dotOp()+0.05);
  inf.textContent="Rings: "+k+" MHz, coloured "+r2[0]+" to "+r2[1]+" dB (same colour scale as the dots)";
  [...rows].sort((a,b)=>a.v-b.v).forEach(r=>L.circleMarker([r.lat,r.lon],{radius:rad,color:colorAt((r.v-r2[0])/(r2[1]-r2[0]||1)),weight:3,fill:false,opacity:op})
    .bindPopup("<b>"+k+" MHz: "+r.v.toFixed(1)+" dB</b><br>"+r.t.replace("T"," ").replace("Z"," UTC")+"<br>"+r.lat.toFixed(6)+", "+r.lon.toFixed(6)+geoLinks(r.lat,r.lon)).addTo(group2));
}
// ---- replay: the dots appear in the order they were recorded
const PB={timer:null,rows:[],ts:[],i:0,t0:0};
function pbPrep(){ PB.rows=[...DATA[sel.value]].sort((a,b)=>a.t<b.t?-1:a.t>b.t?1:0); PB.ts=PB.rows.map(r=>Date.parse(r.t)); }
function pbShow(i){                                   // dots 0..i on the map
  group.clearLayers(); const lo=+mn.value, hi=+mx.value, rad=+document.getElementById("sz").value, op=dotOp();
  for(let k=0;k<=i&&k<PB.rows.length;k++) dotMarker(PB.rows[k],lo,hi,rad,op).addTo(group);
  const r=PB.rows[Math.min(i,PB.rows.length-1)]; if(r) document.getElementById("pNow").textContent=r.t.slice(11,19)+" UTC  |  "+r.v.toFixed(1)+" dB  |  "+r.mph.toFixed(0)+" mph  |  dot "+(i+1)+" of "+PB.rows.length;
}
function pbStop(){ if(PB.timer){ clearInterval(PB.timer); PB.timer=null; } document.getElementById("pPlay").innerHTML="&#9654;"; }
const pSl=document.getElementById("pSl");
pSl.oninput=()=>{ pbStop(); if(+pSl.value>=1000){ draw(); document.getElementById("pNow").textContent="Normal view: all dots."; return; }
  pbPrep(); PB.i=Math.round(+pSl.value/1000*(PB.rows.length-1)); pbShow(PB.i); };
document.getElementById("pPlay").onclick=()=>{
  if(PB.timer){ pbStop(); return; }
  pbPrep(); if(!PB.rows.length) return;
  if(+pSl.value>=1000||PB.i>=PB.rows.length-1){ PB.i=0; group.clearLayers(); }
  let wall=Date.now(); const base=PB.ts[PB.i];
  document.getElementById("pPlay").innerHTML="&#9208;";
  PB.timer=setInterval(()=>{
    const driveT=base+(Date.now()-wall)*(+document.getElementById("pSpd").value);
    let j=PB.i; const lo=+mn.value, hi=+mx.value, rad=+document.getElementById("sz").value, op=dotOp();
    while(j+1<PB.rows.length&&PB.ts[j+1]<=driveT){ j++; dotMarker(PB.rows[j],lo,hi,rad,op).addTo(group); }
    if(j!==PB.i){ PB.i=j; pSl.value=Math.round(j/(PB.rows.length-1)*1000); const r=PB.rows[j]; document.getElementById("pNow").textContent=r.t.slice(11,19)+" UTC  |  "+r.v.toFixed(1)+" dB  |  "+r.mph.toFixed(0)+" mph  |  dot "+(j+1)+" of "+PB.rows.length; }
    if(PB.i>=PB.rows.length-1){ pbStop(); pSl.value=1000; }
  },120);
};
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
    d.onclick=()=>{map.setView([r.lat,r.lon],19);L.popup().setLatLng([r.lat,r.lon]).setContent("<b>"+r.v.toFixed(1)+" dB</b><br>"+r.t.replace("T"," ")+geoLinks(r.lat,r.lon)).openOn(map);};
    box.appendChild(d);
  });
  document.getElementById("phot").innerHTML="<b>Strongest spots:</b> "+picked.slice(0,5).map((r,i)=>
     (i+1)+") "+r.v.toFixed(1)+" dB at "+r.lat.toFixed(5)+", "+r.lon.toFixed(5)).join(" &nbsp; ");
}
// ---- places where several frequencies rose together
const hotLayer=L.layerGroup().addTo(map);
function drawHot(){
  hotLayer.clearLayers();
  const on=document.getElementById("hotmark").checked;
  const box=document.getElementById("multilist"); box.innerHTML="";
  if(!HOT.length){box.innerHTML="<small>None found. This list needs two or more frequencies that rise at the same place.</small>";}
  HOT.forEach((h,i)=>{
    const txt=h.items.map(x=>x[0]+" MHz +"+x[1]+" dB").join("<br>");
    if(on){ L.circle([h.lat,h.lon],{radius:30,color:"#000",weight:2,dashArray:"4 3",fill:false}).bindPopup("<b>Place "+(i+1)+": "+h.n+" frequencies</b><br>"+txt+"<br>seen on "+h.passes+" pass"+(h.passes>1?"es":"")+geoLinks(h.lat,h.lon)).addTo(hotLayer); }
    const d=document.createElement("div"); d.className="sp";
    d.innerHTML="<b>"+(i+1)+". "+h.n+" frequencies"+(h.passes>1?", "+h.passes+" passes":"")+"</b><br><small>"+h.items.map(x=>x[0]+" (+"+x[1]+")").join(", ")+"<br>"+h.lat.toFixed(5)+", "+h.lon.toFixed(5)+"</small>";
    d.onclick=()=>{map.setView([h.lat,h.lon],18);};
    box.appendChild(d);
  });
  document.getElementById("pmulti").innerHTML=HOT.length?"<b>Same place, several frequencies:</b> "+HOT.slice(0,5).map((h,i)=>(i+1)+") "+h.n+" freq at "+h.lat.toFixed(5)+", "+h.lon.toFixed(5)+" ("+h.items.map(x=>x[0]).join(", ")+" MHz)").join(" &nbsp; "):"";
}
document.getElementById("hotmark").onchange=drawHot;
// ---- flags dropped with "Mark this spot" while driving
const markLayer=L.layerGroup().addTo(map);
MARKS.forEach(m=>{
  const ic=L.divIcon({className:"",html:'<div style="font-size:22px;line-height:22px;text-shadow:0 0 3px #fff,0 0 3px #fff">&#128681;</div>',iconSize:[22,22],iconAnchor:[4,20]});
  L.marker([m[0],m[1]],{icon:ic}).bindPopup("<b>Mark "+m[2]+"</b>"+(m[3]?"<br>"+m[3].replace(/</g,"&lt;"):"")+"<br>"+(m[4]||"").replace("T"," ").replace("Z"," UTC")+(m[5]?"<br>"+m[5]:"")+geoLinks(m[0],m[1])).addTo(markLayer);
});
if(MARKS.length){ const mb=document.createElement("div"); mb.style.marginTop="4px"; mb.innerHTML="&#128681; "+MARKS.length+" spot"+(MARKS.length>1?"s":"")+" marked while driving"; document.getElementById("info").after(mb);
  document.getElementById("phot").insertAdjacentHTML("afterend","<div id='pmarks'><b>Marked spots:</b> "+MARKS.slice(0,8).map(m=>m[2]+") "+(m[3]||"(no note)").replace(/</g,"&lt;")+" at "+m[0].toFixed(5)+", "+m[1].toFixed(5)).join(" &nbsp; ")+"</div>"); }
sel.onchange=()=>{autoRange();draw();};
mn.onchange=mx.onchange=document.getElementById("sz").oninput=document.getElementById("op").oninput=draw;
f2.onchange=draw2;
document.getElementById("tgHeat").onchange=drawHeat;
document.getElementById("tgDots").onchange=function(){ if(this.checked) map.addLayer(group); else map.removeLayer(group); };
document.getElementById("tgMarks").onchange=function(){ if(this.checked) map.addLayer(markLayer); else map.removeLayer(markLayer); };
document.getElementById("auto").onclick=()=>{autoRange();draw();};
if(freqs.length){sel.value=freqs[0];autoRange();draw();}
drawHot();

// ---- power lines and poles from OpenStreetMap (needs internet; not every pole is mapped)
const powerLayer=L.layerGroup(), pwMsg=document.getElementById("powerMsg"); let powerDone=false, powerBusy=false;
function dataBounds(){ const pts=[]; freqs.forEach(f=>DATA[f].forEach(r=>pts.push([r.lat,r.lon]))); return L.latLngBounds(pts); }
async function loadPower(){
  if(powerDone||powerBusy) return; powerBusy=true; pwMsg.textContent="Loading power lines from OpenStreetMap...";
  let b=dataBounds().pad(0.05); if(b.getNorth()-b.getSouth()>0.25||b.getEast()-b.getWest()>0.25) b=map.getBounds();
  const bb=[b.getSouth(),b.getWest(),b.getNorth(),b.getEast()].map(x=>x.toFixed(5)).join(",");
  const q='[out:json][timeout:25];(way["power"~"^(line|minor_line)$"]('+bb+');node["power"~"^(pole|tower)$"]('+bb+'););out geom;';
  let j=null;
  for(const ep of ["https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter"]){
    try{ const r=await fetch(ep,{method:"POST",body:"data="+encodeURIComponent(q),headers:{"Content-Type":"application/x-www-form-urlencoded"}}); if(!r.ok) continue; j=await r.json(); break; }catch(e){}
  }
  powerBusy=false;
  if(!j){ pwMsg.textContent="Could not load power lines (needs internet). Untick and tick again to retry."; return; }
  let nl=0,np=0;
  (j.elements||[]).forEach(e=>{
    const t=e.tags||{}, info=(t.power||"")+(t.voltage?", "+t.voltage+" V":"")+(t.operator?"<br>"+String(t.operator).replace(/</g,"&lt;"):"");
    if(e.type==="way"&&e.geometry){ nl++; L.polyline(e.geometry.map(g=>[g.lat,g.lon]),{color:t.power==="line"?"#e67e00":"#b35900",weight:t.power==="line"?3.5:2.5,dashArray:t.power==="line"?null:"6 4",opacity:0.9}).bindPopup("<b>Power "+info+"</b>").addTo(powerLayer); }
    else if(e.type==="node"&&e.lat!=null){ np++; L.circleMarker([e.lat,e.lon],{radius:t.power==="tower"?5:3.5,color:"#000",weight:1,fillColor:"#ffd400",fillOpacity:1}).bindPopup("<b>"+(t.power==="tower"?"Tower":"Pole")+"</b>"+(t.voltage?"<br>"+t.voltage+" V":"")+geoLinks(e.lat,e.lon)).addTo(powerLayer); }
  });
  powerDone=true; pwMsg.textContent=nl+" line"+(nl==1?"":"s")+" and "+np+" pole/tower"+(np==1?"":"s")+" found (OpenStreetMap data: coverage varies, not every pole is mapped).";
}
document.getElementById("tgPower").onchange=function(){ if(this.checked){ powerLayer.addTo(map); loadPower(); } else map.removeLayer(powerLayer); };

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


def build_map(paths, out, title=None, spacing_ft=None, pick="peak", filters=None):
    """Create the HTML map. Returns (out_path, {freq: dot_count}, info) where info holds the
    multi-frequency hot spots, the flat channels and what the map was limited to.
    filters (all optional): slots [1,3,4], radios ["hl2"], freqs [7.2], mph_min, mph_max, db_min, db_max."""
    rows = load_rows(paths)
    if not rows:
        raise ValueError("No usable rows found in the CSV (is it empty?).")
    flt = clean_filters(filters)
    rows = filter_rows(rows, flt, "pre")
    if not rows:
        raise ValueError("No readings match those choices (slot / radio / frequency). Loosen them and try again.")
    if spacing_ft:
        rows = thin_rows(rows, float(spacing_ft), pick)
    rows = filter_rows(rows, flt, "post")
    if not rows:
        raise ValueError("No readings match those choices (speed / level). Loosen them and try again.")
    groups = group_rows(rows)

    title = title or "RF noise map - " + os.path.basename(paths[0])
    if spacing_ft:
        title += "  (one dot per %g ft, %s)" % (float(spacing_ft), "strongest" if pick != "average" else "average")
    if flt:
        title += "  [only: %s]" % describe_filters(flt)
    marks = []
    for pth in paths:
        nm = (_meta_for(pth).get("name") or "") if len(paths) > 1 else ""
        for mk in _meta_for(pth).get("marks") or []:
            try:
                marks.append([float(mk["lat"]), float(mk["lon"]), len(marks) + 1, str(mk.get("note", "")), str(mk.get("t_utc", "")), nm])
            except (KeyError, ValueError, TypeError):
                continue
    hot = find_hotspots(groups)
    flat = sorted((k for k, v in groups.items() if max(r["v"] for r in v) - min(r["v"] for r in v) < FLAT_DB), key=key_mhz)
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
                .replace("__MARKS__", json.dumps(marks, separators=(",", ":")).replace("</", "<\\/"))
                .replace("__HOT__", json.dumps(hot, separators=(",", ":")).replace("</", "<\\/"))
                .replace("__MINSPAN__", repr(MIN_SPAN_DB)).replace("__FLATDB__", repr(FLAT_DB))
                .replace("__DATA__", json.dumps(groups, separators=(",", ":")).replace("</", "<\\/")))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out, {k: len(v) for k, v in groups.items()}, {"hot": hot, "flat": flat, "filters": describe_filters(flt), "marks": len(marks)}


# ----------------------------------------------------------------------------
# Google Earth export
# ----------------------------------------------------------------------------
def _kml_color(hexrgb, alpha="ff"):
    r, g, b = hexrgb[1:3], hexrgb[3:5], hexrgb[5:7]
    return alpha + b + g + r                      # KML wants aabbggrr


def export_kml(paths, out, freq=None, title="RF noise map", spacing_ft=None, pick="peak", filters=None):
    """Colored dots for Google Earth. One folder per frequency (or just `freq`)."""
    flt = clean_filters(filters)
    rows = filter_rows(load_rows(paths), flt, "pre")
    if spacing_ft:
        rows = thin_rows(rows, float(spacing_ft), pick)
    rows = filter_rows(rows, flt, "post")
    groups = group_rows(rows)
    if freq is not None:
        groups = {k: v for k, v in groups.items() if key_mhz(k) == float(freq)}
    if not groups:
        raise ValueError("No data for that frequency.")
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>', f"<name>{esc(title)}</name>"]
    for i, c in enumerate(STOPS):
        parts.append(f'<Style id="s{i}"><IconStyle><color>{_kml_color(c)}</color><scale>0.45</scale>'
                     '<Icon><href>http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href></Icon>'
                     '</IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>')
    for k in sorted(groups, key=key_mhz):
        rows = groups[k]
        lo, hi, _flat = colour_range([r["v"] for r in rows])
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
    ap.add_argument("--spacing-ft", type=float, default=None,
                    help="show one dot every this many feet of route (worked out from the readings' times)")
    ap.add_argument("--pick", choices=["peak", "average"], default="peak",
                    help="with --spacing-ft: keep the strongest reading, or the average, in each stretch")
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
            export_kml(paths, out, title=args.title or "RF noise map", spacing_ft=args.spacing_ft, pick=args.pick)
            print(f"KML written: {out}")
        else:
            out = args.out or os.path.splitext(paths[0])[0] + "_map.html"
            out, counts, info = build_map(paths, out, args.title, args.spacing_ft, args.pick)
            print(f"Map written: {out}\n  dots per frequency -> " +
                  ", ".join(f"{k} MHz: {v}" for k, v in sorted(counts.items(), key=lambda kv: key_mhz(kv[0]))))
            if info["hot"]:
                print("  places where several frequencies rose together: %d" % len(info["hot"]))
            if info["flat"]:
                print("  flat channels (moved under %g dB): %s" % (FLAT_DB, ", ".join(info["flat"])))
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
