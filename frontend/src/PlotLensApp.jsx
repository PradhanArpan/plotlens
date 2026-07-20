import React, { useState, useEffect, useRef } from "react";
import {
  MapPin, Mountain, Loader2, Crosshair, AlertTriangle, CheckCircle2,
  ShieldQuestion, ChevronRight, ChevronDown, Droplets, CloudRain, Route,
  Trees, Plug, FileText, ArrowRightLeft, Wind, Database,
} from "lucide-react";
import * as api from "./plotlensApi";
import PlotMap from "./PlotMap";

/* PlotLens v5 — "field record" design system.
   Visual language borrowed from the subject's own world: Survey of India
   toposheets and surveyors' field books. Plate-grey paper, pine ink, contour
   umber, coordinates in mono like a map margin. The verdict is a benchmark
   stamp over a contour engraving — the one deliberate flourish; everything
   else is a quiet ledger.

   Behavior is IDENTICAL to v4: same API contract, same report schema, same
   PlotMap integration, same mock backend. Only presentation changed.
   MOCK_API=true returns a complete report for offline UI work. */
const MOCK_API = false;

/* ---- design tokens (mirrored in CSS custom properties below) ---- */
const T = {
  paper: "#EEF1EC", card: "#F9FAF8", ink: "#17251F", faint: "#6C7A72",
  hair: "#D8DED7", contour: "#8A6A3F",
  pass: "#2E7D4F", warn: "#A8731B", flag: "#A63A26", check: "#2E6E8E",
};

const STATUS = {
  good:    { label: "Looks good",     color: T.pass,  bg: "rgba(46,125,79,0.09)",  icon: CheckCircle2 },
  caution: { label: "Caution",        color: T.warn,  bg: "rgba(168,115,27,0.10)", icon: AlertTriangle },
  flag:    { label: "Flag",           color: T.flag,  bg: "rgba(166,58,38,0.10)",  icon: AlertTriangle },
  check:   { label: "Verify offline", color: T.check, bg: "rgba(46,110,142,0.10)", icon: ShieldQuestion },
};
const SRC = { derived: { t: "Satellite-derived", c: T.pass },
              partial: { t: "Indicative", c: T.warn },
              offline: { t: "Needs site / legal check", c: T.check },
              // Live source not connected yet. Distinct from "offline", which
              // means data satellites fundamentally cannot see (legal title).
              unavailable: { t: "Not connected yet", c: "#8A8E86" } };

// Maps icon names (strings) from the live backend to icon components.
const ICONS = { Mountain, Droplets, CloudRain, Route, Trees, ArrowRightLeft, Plug, FileText, Wind, Database };
function resolveIcon(icon) {
  if (typeof icon === "string") return ICONS[icon] || Mountain;
  return icon || Mountain;   // mock mode passes the component directly
}

const PINS = [
  { key: "filled", label: "Whitefield outskirts, Bengaluru", lat: 12.9698, lng: 77.7499, archetype: "filled_pond" },
  { key: "riverside", label: "Riverbank plot, Mandya", lat: 12.5223, lng: 76.8951, archetype: "riverside" },
  { key: "upland", label: "Upland plot, Tumkur road", lat: 13.1986, lng: 77.4066, archetype: "upland" },
];

function cat(title, icon, source, status, rows, offline_note) {
  return { title, icon, source, status, rows, offline_note };
}

// ---- full mock reports (mirror the backend's run_report output shape) ----
const FULL = {
  filled_pond: {
    overall: "flag",
    then: { year: 2017, cover: "Open scrub & a seasonal pond", tint: "#3f6b3a" },
    now: { year: 2025, cover: "Partly built-up, road access added", tint: "#7d7a6b" },
    categories: [
      cat("Topography & Geology", Mountain, "derived", "flag", [["Elevation", "832.5 m"], ["Slope", "0.7 %"], ["Below surroundings", "3.2 m — sits in a dip"], ["Landslide potential", "Low"]]),
      cat("Water & Drainage", Droplets, "derived", "flag", [["Water-collection index", "7.5x area average"], ["Nearest water", "134 m (seasonal pond, filled)"], ["Drainage bearing", "174°"], ["Reading", "Low pocket, water converges here — strong drainage caution."]]),
      cat("Climate & Natural", CloudRain, "derived", "good", [["Annual rainfall", "970 mm"], ["Monsoon peak", "Sep"], ["Prevailing wind", "WSW"], ["Seismic zone", "Zone II (Low)"]]),
      cat("Circulation & Access", Route, "derived", "caution", [["Nearest road", "257 m (Outer Ring Rd)"], ["Transit", "492 m (bus stop)"], ["Emergency", "2.6 km (hospital)"], ["Reading", "Check the access path on the ground."]]),
      cat("Vegetation & Landscaping", Trees, "derived", "caution", [["Vegetation cover", "27% → 15%"], ["Trend", "Tree cover dropped ~30% since 2017"]]),
      cat("Land-cover change", ArrowRightLeft, "derived", "flag", [["Water cover", "12% → 1%"], ["Reading", "A water body appears to have been filled — verify drainage & whether it was a tank bed."]]),
      cat("Utilities & Infrastructure", Plug, "partial", "caution", [["Adjacent land use", "Residential"], ["Mapped utilities", "HT line ~220 m; underground lines not mapped"]]),
      cat("Development Rules & Legal", FileText, "offline", "check", [["Title & ownership", "Cannot be checked from satellite"], ["Zoning / land-use", "Cannot be checked from satellite"], ["Easements & setbacks", "Cannot be checked from satellite"]], "Satellite data can't see legal status. Verify with the sub-registrar, a property lawyer, and the planning authority — this is the costliest place buyers get caught."),
    ],
  },
  riverside: {
    overall: "flag",
    then: { year: 2017, cover: "Floodplain near river channel", tint: "#2f5d6b" },
    now: { year: 2025, cover: "Cleared, levelled, plotted", tint: "#8a8160" },
    categories: [
      cat("Topography & Geology", Mountain, "derived", "flag", [["Elevation", "674.2 m"], ["Slope", "0.2 % — very flat"], ["Below surroundings", "0.9 m"], ["Landslide potential", "Low"]]),
      cat("Water & Drainage", Droplets, "derived", "flag", [["Water-collection index", "9.1x area average"], ["Nearest water", "60 m (Cauvery channel)"], ["Drainage bearing", "177°"], ["Reading", "Former floodplain beside an active channel — high flood exposure."]]),
      cat("Climate & Natural", CloudRain, "derived", "good", [["Annual rainfall", "720 mm"], ["Monsoon peak", "Aug"], ["Prevailing wind", "W"], ["Seismic zone", "Zone II (Low)"]]),
      cat("Circulation & Access", Route, "derived", "caution", [["Nearest road", "120 m (gravel track)"], ["Transit", "1.8 km"], ["Emergency", "9 km"], ["Reading", "Remote; sparse OSM coverage — verify access on the ground."]]),
      cat("Vegetation & Landscaping", Trees, "derived", "caution", [["Vegetation cover", "34% → 3%"], ["Trend", "Riparian cover cleared since 2017"]]),
      cat("Land-cover change", ArrowRightLeft, "derived", "caution", [["Vegetation", "34% → 3%"], ["Reading", "Significant clearing of riverside vegetation — confirm what changed and why."]]),
      cat("Utilities & Infrastructure", Plug, "partial", "caution", [["Adjacent land use", "Agricultural + new plotting"], ["Mapped utilities", "LT line ~400 m; no piped water mapped"]]),
      cat("Development Rules & Legal", FileText, "offline", "check", [["Title & ownership", "Cannot be checked from satellite"], ["River buffer / CRZ rules", "Likely applies — verify with authority"], ["Easements & setbacks", "Cannot be checked from satellite"]], "Riverside plots often carry buffer/flood-zone restrictions. Confirm with the planning authority and a lawyer before buying."),
    ],
  },
  upland: {
    overall: "good",
    then: { year: 2017, cover: "Rocky upland, sparse trees", tint: "#5a5340" },
    now: { year: 2025, cover: "Same upland, access track added", tint: "#6b6147" },
    categories: [
      cat("Topography & Geology", Mountain, "derived", "good", [["Elevation", "911 m"], ["Slope", "6.4 %"], ["Below surroundings", "0 m — sits high"], ["Landslide potential", "Low–moderate"]]),
      cat("Water & Drainage", Droplets, "derived", "good", [["Water-collection index", "0.8x area average"], ["Nearest water", "1.4 km (minor stream)"], ["Drainage bearing", "126°"], ["Reading", "Elevated and well-drained — water flows away from the plot."]]),
      cat("Climate & Natural", CloudRain, "derived", "good", [["Annual rainfall", "810 mm"], ["Monsoon peak", "Sep"], ["Prevailing wind", "WSW"], ["Seismic zone", "Zone II (Low)"]]),
      cat("Circulation & Access", Route, "derived", "good", [["Nearest road", "25 m (Tumkur Rd)"], ["Transit", "900 m"], ["Emergency", "6 km"], ["Reading", "Good road access on a named highway."]]),
      cat("Vegetation & Landscaping", Trees, "derived", "good", [["Vegetation cover", "10% → 8%"], ["Trend", "Stable sparse cover"]]),
      cat("Land-cover change", ArrowRightLeft, "derived", "good", [["Water cover", "0% → 0%"], ["Reading", "Land cover broadly stable since 2017 — no filling or major clearing."]]),
      cat("Utilities & Infrastructure", Plug, "partial", "caution", [["Adjacent land use", "Vacant uplands + farmhouse"], ["Mapped utilities", "HT line ~90 m; underground lines not mapped"]]),
      cat("Development Rules & Legal", FileText, "offline", "check", [["Title & ownership", "Cannot be checked from satellite"], ["Zoning / land-use", "Cannot be checked from satellite"], ["Easements & setbacks", "Cannot be checked from satellite"]], "Even on a clean-looking plot, always verify title, zoning, and encumbrance with the sub-registrar and a lawyer."),
    ],
  },
};

const mockBackend = (() => {
  const jobs = {};
  return {
    create: ({ archetype }) => { const id = Math.random().toString(36).slice(2, 10); jobs[id] = { t: Date.now(), archetype: archetype || "filled_pond" }; return { job_id: id }; },
    get: (id) => { const j = jobs[id]; if (!j) throw new api.ApiError(404, "unknown"); if (Date.now() - j.t < 1400) return { status: "running" };
      return { status: "done", report: FULL[j.archetype] || FULL.filled_pond }; },
  };
})();
const call = {
  create: (a) => MOCK_API ? Promise.resolve(mockBackend.create(a)) : api.createReport(a),
  get: (id) => MOCK_API ? Promise.resolve(mockBackend.get(id)) : api.getReport(id),
};

/* Reverse geocoding: dropped pins arrive labelled with raw coordinates.
   We resolve a human place name via Nominatim (already the app's search
   provider; free, keyless) and fall back to the coordinates silently on any
   failure. Cached per rounded coordinate so repeat views cost nothing. */
const _placeCache = {};
function looksLikeCoords(label) {
  return !label || /^-?\d+\.\d+\s*,\s*-?\d+\.\d+$/.test(label.trim());
}
function compactPlace(addr) {
  if (!addr) return null;
  const local = addr.neighbourhood || addr.suburb || addr.village || addr.hamlet ||
                addr.town || addr.city_district || addr.locality || addr.road;
  const city = addr.city || addr.town || addr.municipality || addr.county ||
               addr.state_district || addr.state;
  if (local && city && local !== city) return `${local}, ${city}`;
  return local || city || null;
}
function usePlaceName(pin) {
  const [name, setName] = useState(null);
  useEffect(() => {
    setName(null);
    if (!pin || !looksLikeCoords(pin.label)) return;
    const key = `${pin.lat.toFixed(4)},${pin.lng.toFixed(4)}`;
    if (_placeCache[key]) { setName(_placeCache[key]); return; }
    let live = true;
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 6000);
    fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=16&lat=${pin.lat}&lon=${pin.lng}`,
          { signal: ctl.signal, headers: { "Accept": "application/json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const p = compactPlace(d && d.address);
        if (p) { _placeCache[key] = p; if (live) setName(p); }
      })
      .catch(() => {})              // silent fallback: coordinates stay as title
      .finally(() => clearTimeout(t));
    return () => { live = false; ctl.abort(); };
  }, [pin]);
  if (!pin) return null;
  return looksLikeCoords(pin.label) ? name : pin.label;
}

/* Coordinates set like a toposheet margin: 12.9698° N · 77.7499° E */
function Coord({ lat, lng }) {
  if (lat == null) return null;
  return (
    <span className="pl-coord">
      {Math.abs(lat).toFixed(4)}° {lat >= 0 ? "N" : "S"}
      <span className="pl-coord-dot">·</span>
      {Math.abs(lng).toFixed(4)}° {lng >= 0 ? "E" : "W"}
    </span>
  );
}

/* The signature: a contour engraving. Irregular nested rings, umber, faint. */
function ContourPlate() {
  return (
    <svg className="pl-contours" viewBox="0 0 420 150" aria-hidden="true" focusable="false">
      <g fill="none" stroke={T.contour} strokeWidth="0.8">
        <path opacity="0.28" d="M330 150 C280 120 300 78 355 66 C412 54 452 92 445 150" />
        <path opacity="0.22" d="M310 150 C255 108 282 52 356 40 C430 28 478 84 470 150" />
        <path opacity="0.16" d="M288 150 C228 96 262 26 358 14 C452 3 505 76 498 150" />
        <path opacity="0.11" d="M264 150 C200 84 240 0 360 -12 C476 -22 532 68 526 150" />
        <path opacity="0.30" d="M-20 150 C-8 112 44 100 78 118 C108 134 112 150 112 150" />
        <path opacity="0.20" d="M-20 128 C0 92 58 76 102 100 C136 118 142 150 142 150" />
        <path opacity="0.13" d="M-20 104 C10 68 74 50 126 82 C162 104 170 150 170 150" />
      </g>
    </svg>
  );
}

export default function PlotLensApp() {
  const [screen, setScreen] = useState("map");
  const [pin, setPin] = useState(null);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState(null);
  const poll = useRef(false);

  const start = async (p) => {
    setPin(p); setErr(null); setReport(null); setScreen("loading");
    try {
      const { job_id } = await call.create({ lat: p.lat, lng: p.lng, archetype: p.archetype });
      poll.current = true;
      const loop = async () => {
        while (poll.current) {
          const s = await call.get(job_id);
          if (s.status === "done") { setReport(s.report); setScreen("report"); return; }
          if (s.status === "error") { setErr(s.error || "Report failed"); setScreen("report"); return; }
          await new Promise((r) => setTimeout(r, 900));
        }
      };
      loop();
    } catch (e) { setErr(e.message); setScreen("report"); }
  };
  useEffect(() => () => { poll.current = false; }, []);

  return (
    <div className="pl-app">
      <style>{CSS}</style>
      <header className="pl-header" onClick={() => { poll.current = false; setScreen("map"); }}>
        <div className="pl-mark"><Crosshair size={17} strokeWidth={2.2} /></div>
        <div className="pl-brand">
          <div className="pl-brand-name">PLOTLENS</div>
          <div className="pl-brand-sub">Read the ground before you buy</div>
        </div>
        {MOCK_API && <span className="pl-mock">MOCK</span>}
      </header>

      {screen === "map" && <MapScreen onPick={start} />}
      {screen === "loading" && <LoadingScreen pin={pin} />}
      {screen === "report" && <Report pin={pin} report={report} err={err} onBack={() => setScreen("map")} />}

      <footer className="pl-footer">
        Indicators are derived from public satellite, elevation and map data and are indicative only — not a guarantee, nor a substitute for a site survey, soil test, or legal title check.
      </footer>
    </div>
  );
}

function MapScreen({ onPick }) {
  return (
    <main className="pl-main">
      <div className="pl-mapframe"><PlotMap onPick={onPick} samples={PINS} /></div>
      <div className="pl-eyebrow">Or pick a sample plot</div>
      {PINS.map((p) => (
        <button key={p.key} onClick={() => onPick(p)} className="pl-sample">
          <div className="pl-sample-text">
            <div className="pl-sample-name">{p.label}</div>
            <Coord lat={p.lat} lng={p.lng} />
          </div>
          <ChevronRight size={17} className="pl-chev" />
        </button>
      ))}
    </main>
  );
}

function LoadingScreen({ pin }) {
  const place = usePlaceName(pin);
  const steps = ["Submitting coordinates", "Fetching elevation & imagery", "Computing terrain & flow", "Scoring site categories"];
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((v) => (v + 1) % steps.length), 450); return () => clearInterval(t); }, []);
  return (
    <main className="pl-main pl-loading">
      <Loader2 size={30} className="spin" color={T.contour} />
      <div className="pl-loading-site">{place || pin?.label}</div>
      <Coord lat={pin?.lat} lng={pin?.lng} />
      <div className="pl-loading-step">{steps[i]}…</div>
    </main>
  );
}

function Report({ pin, report, err, onBack }) {
  const place = usePlaceName(pin);
  if (err) return (
    <main className="pl-main pl-enter">
      <button onClick={onBack} className="pl-back">← Back to map</button>
      <div className="pl-verdict" style={{ borderColor: STATUS.flag.color }}>
        <ContourPlate />
        <div className="pl-verdict-inner">
          <div className="pl-verdict-eyebrow">Survey record</div>
          <div className="pl-verdict-word" style={{ color: STATUS.flag.color }}>Report failed</div>
          <div className="pl-verdict-note">{err}</div>
        </div>
      </div>
    </main>
  );
  if (!report) return null;
  const st = STATUS[report.overall] || STATUS.good;
  const HIcon = st.icon;

  return (
    <main className="pl-main pl-enter">
      <button onClick={onBack} className="pl-back">← Back to map</button>
      <h1 className="pl-title">{place || pin?.label}</h1>
      <div className="pl-title-coord"><MapPin size={12} /> <Coord lat={pin?.lat} lng={pin?.lng} /></div>

      <div className="pl-verdict" style={{ borderColor: st.color }}>
        <ContourPlate />
        <div className="pl-verdict-inner">
          <div className="pl-verdict-eyebrow">Overall read</div>
          <div className="pl-verdict-line">
            <span className="pl-verdict-stamp" style={{ color: st.color, borderColor: st.color }}>
              <HIcon size={15} strokeWidth={2.4} /> {st.label}
            </span>
          </div>
          {report.verdict_note && <div className="pl-verdict-note">{report.verdict_note}</div>}
        </div>
      </div>

      <ThenNow report={report} />

      <div className="pl-eyebrow">Site analysis · {report.categories.length} categories</div>
      <div className="pl-ledger">
        {report.categories.map((c, i) => <Category key={i} cat={c} defaultOpen={i < 2} />)}
      </div>
    </main>
  );
}

function ThenNow({ report }) {
  const [pos, setPos] = useState(50);
  const t = report.then, n = report.now;
  return (
    <section className="pl-tn">
      <div className="pl-tn-head"><ArrowRightLeft size={14} /> What changed here</div>
      <div className="pl-tn-frame">
        <div className="pl-tn-layer" style={{ background: grad(n.tint) }}>
          {n.year && <span className="pl-tn-year">{n.year}</span>}
        </div>
        <div className="pl-tn-layer pl-tn-top" style={{ width: `${pos}%`, background: grad(t.tint) }}>
          {t.year && <span className="pl-tn-year">{t.year}</span>}
        </div>
        <input type="range" min="0" max="100" value={pos} onChange={(e) => setPos(+e.target.value)}
               className="pl-tn-range" aria-label="Compare years" />
      </div>
      <div className="pl-tn-caps">
        <span>{t.year ? <b>{t.year} · </b> : null}{t.cover}</span>
        <span>{n.year ? <b>{n.year} · </b> : null}{n.cover}</span>
      </div>
      <div className="pl-tn-note">Computed artifacts (terrain flow map, access rings, then-vs-now panel) are generated by the backend but not yet displayed in this view.</div>
    </section>
  );
}

function Category({ cat, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const st = STATUS[cat.status] || STATUS.good;
  const src = SRC[cat.source];
  const Ic = resolveIcon(cat.icon);
  return (
    <div className="pl-cat" style={{ borderLeftColor: st.color }}>
      <button className="pl-cat-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <div className="pl-cat-icon" style={{ background: st.bg }}><Ic size={16} color={st.color} /></div>
        <div className="pl-cat-text">
          <div className="pl-cat-title">{cat.title}</div>
          <div className="pl-cat-src" style={{ color: src.c }}>{src.t}</div>
        </div>
        <span className="pl-status" style={{ color: st.color, background: st.bg }}>{st.label}</span>
        {open ? <ChevronDown size={16} className="pl-chev" /> : <ChevronRight size={16} className="pl-chev" />}
      </button>
      {open && (
        <div className="pl-cat-body">
          {cat.rows.map(([k, v], i) => (
            <div key={i} className={"pl-row" + (i === cat.rows.length - 1 && !cat.offline_note ? " pl-row-last" : "")}>
              <span className="pl-row-key">{k}</span><span className="pl-row-val">{v}</span>
            </div>
          ))}
          {cat.offline_note && (
            <div className="pl-offline"><ShieldQuestion size={14} className="pl-offline-ic" /><span>{cat.offline_note}</span></div>
          )}
        </div>
      )}
    </div>
  );
}

const grad = (c) => `linear-gradient(135deg, ${c}, ${shade(c, -18)})`;
function shade(hex, amt) { const n = parseInt(hex.slice(1), 16); let r = Math.max(0, Math.min(255, (n >> 16) + amt)), g = Math.max(0, Math.min(255, ((n >> 8) & 255) + amt)), b = Math.max(0, Math.min(255, (n & 255) + amt)); return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`; }

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --paper: ${T.paper}; --card: ${T.card}; --ink: ${T.ink}; --faint: ${T.faint};
  --hair: ${T.hair}; --contour: ${T.contour};
  --display: 'Big Shoulders Display', 'Arial Narrow', sans-serif;
  --body: 'Public Sans', system-ui, sans-serif;
  --mono: 'IBM Plex Mono', ui-monospace, monospace;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); }

.pl-app { max-width: 440px; margin: 0 auto; min-height: 100vh; background: var(--paper);
  color: var(--ink); font-family: var(--body); display: flex; flex-direction: column; }

/* ---- header: map-margin ---- */
.pl-header { display: flex; align-items: center; gap: 11px; padding: 14px 18px;
  border-bottom: 1.5px solid var(--ink); cursor: pointer; position: sticky; top: 0;
  background: color-mix(in srgb, var(--paper) 92%, transparent); backdrop-filter: blur(8px); z-index: 600; }
.pl-mark { width: 34px; height: 34px; background: var(--ink); color: var(--paper);
  display: grid; place-items: center; border-radius: 4px; }
.pl-brand-name { font-family: var(--display); font-weight: 700; font-size: 21px;
  letter-spacing: 0.10em; line-height: 1; }
.pl-brand-sub { font-family: var(--mono); font-size: 10px; color: var(--faint);
  letter-spacing: 0.04em; margin-top: 3px; }
.pl-mock { margin-left: auto; font-family: var(--mono); font-size: 10px; font-weight: 500;
  color: ${T.warn}; border: 1px solid ${T.warn}; padding: 2px 7px; border-radius: 3px; }

.pl-main { flex: 1; padding: 18px 18px 8px; }
.pl-footer { font-size: 11px; line-height: 1.55; color: var(--faint);
  padding: 16px 20px 26px; border-top: 1px solid var(--hair); margin-top: 12px; }

/* ---- shared small pieces ---- */
.pl-eyebrow { font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--faint); margin: 18px 0 9px;
  display: flex; align-items: center; gap: 10px; }
.pl-eyebrow::after { content: ""; flex: 1; height: 1px; background: var(--hair); }
.pl-coord { font-family: var(--mono); font-size: 11.5px; color: var(--faint); letter-spacing: 0.01em; }
.pl-coord-dot { margin: 0 6px; color: var(--contour); }
.pl-chev { color: #9AA59D; flex-shrink: 0; }

/* ---- map screen ---- */
.pl-mapframe { border: 1px solid var(--hair); border-radius: 6px; overflow: hidden; }
.pl-sample { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  background: var(--card); border: 1px solid var(--hair); border-left: 3px solid var(--contour);
  border-radius: 4px; padding: 12px 13px; cursor: pointer; margin-bottom: 8px;
  font-family: var(--body); color: var(--ink); transition: border-color .15s; }
.pl-sample:hover { border-color: var(--contour); }
.pl-sample-text { flex: 1; }
.pl-sample-name { font-weight: 600; font-size: 14px; margin-bottom: 3px; }

/* ---- loading ---- */
.pl-loading { display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-height: 55vh; gap: 12px; }
.pl-loading-site { font-weight: 600; }
.pl-loading-step { font-family: var(--mono); color: var(--faint); font-size: 13px; }

/* ---- report ---- */
.pl-back { background: none; border: none; color: var(--faint); font-size: 13px;
  cursor: pointer; padding: 0; margin-bottom: 10px; font-family: var(--body); }
.pl-title { font-family: var(--display); font-weight: 700; font-size: 27px;
  letter-spacing: 0.03em; margin: 0 0 5px; line-height: 1.05; text-transform: uppercase; }
.pl-title-coord { display: flex; align-items: center; gap: 5px; color: var(--faint); margin-bottom: 16px; }

/* verdict: benchmark stamp over contour engraving — the signature */
.pl-verdict { position: relative; overflow: hidden; background: var(--card);
  border: 1.5px solid; border-radius: 6px; padding: 16px 16px 15px; margin-bottom: 18px; }
.pl-contours { position: absolute; right: -30px; bottom: 0; width: 115%; height: 100%;
  pointer-events: none; }
.pl-verdict-inner { position: relative; }
.pl-verdict-eyebrow { font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--faint); margin-bottom: 7px; }
.pl-verdict-line { margin: 2px 0 0; }
.pl-verdict-stamp { display: inline-flex; align-items: center; gap: 7px;
  font-family: var(--display); font-weight: 700; font-size: 22px; letter-spacing: 0.06em;
  text-transform: uppercase; border: 2px solid; border-radius: 4px; padding: 4px 12px 5px;
  transform: rotate(-1.2deg); background: color-mix(in srgb, var(--card) 65%, transparent); }
.pl-verdict-word { font-family: var(--display); font-weight: 700; font-size: 22px;
  letter-spacing: 0.05em; text-transform: uppercase; }
.pl-verdict-note { font-size: 12.5px; color: var(--faint); margin-top: 10px;
  line-height: 1.5; max-width: 46ch; }

/* then / now */
.pl-tn { margin-bottom: 4px; }
.pl-tn-head { display: flex; align-items: center; gap: 7px; font-size: 13px;
  font-weight: 600; color: var(--ink); margin-bottom: 8px; }
.pl-tn-frame { position: relative; height: 170px; border-radius: 6px; overflow: hidden;
  border: 1px solid var(--hair); }
.pl-tn-layer { position: absolute; inset: 0; overflow: hidden; display: flex; align-items: flex-end; }
.pl-tn-top { border-right: 2px solid var(--paper); }
.pl-tn-year { position: relative; margin: 10px; font-family: var(--mono); font-size: 12px;
  font-weight: 500; color: #fff; background: rgba(0,0,0,0.38); padding: 2px 8px; border-radius: 3px; }
.pl-tn-range { position: absolute; inset: 0; width: 100%; height: 100%;
  opacity: 0; cursor: ew-resize; margin: 0; }
.pl-tn-caps { display: flex; flex-direction: column; gap: 3px; font-size: 12px;
  color: var(--faint); margin-top: 9px; }
.pl-tn-caps b { font-family: var(--mono); font-weight: 500; color: var(--ink); }
.pl-tn-note { font-size: 11px; color: #9AA59D; font-style: italic; margin-top: 8px; line-height: 1.4; }

/* category ledger: left rail encodes status */
.pl-ledger { border-top: 1px solid var(--hair); }
.pl-cat { background: var(--card); border: 1px solid var(--hair); border-left: 3px solid;
  border-radius: 4px; margin: 8px 0; overflow: hidden; }
.pl-cat-head { display: flex; align-items: center; gap: 11px; width: 100%;
  background: none; border: none; padding: 12px 13px; cursor: pointer;
  font-family: var(--body); color: var(--ink); text-align: left; }
.pl-cat-icon { width: 32px; height: 32px; border-radius: 4px; display: grid;
  place-items: center; flex-shrink: 0; }
.pl-cat-text { flex: 1; min-width: 0; }
.pl-cat-title { font-weight: 600; font-size: 14px; }
.pl-cat-src { font-family: var(--mono); font-size: 10.5px; margin-top: 2px; letter-spacing: 0.02em; }
.pl-status { font-family: var(--mono); font-size: 10.5px; font-weight: 500;
  padding: 3px 8px; border-radius: 3px; white-space: nowrap; letter-spacing: 0.02em; }
.pl-cat-body { padding: 2px 14px 12px; border-top: 1px solid var(--hair); }
.pl-row { display: flex; justify-content: space-between; gap: 14px; padding: 8px 0;
  font-size: 13px; border-bottom: 1px dotted var(--hair); }
.pl-row-last { border-bottom: none; }
.pl-row-key { color: var(--faint); flex-shrink: 0; }
.pl-row-val { color: var(--ink); text-align: right; font-weight: 500;
  font-variant-numeric: tabular-nums; }
.pl-offline { display: flex; gap: 8px; font-size: 12.5px; line-height: 1.55;
  color: ${T.check}; margin-top: 10px; background: rgba(46,110,142,0.07);
  padding: 11px 12px; border-radius: 4px; }
.pl-offline-ic { flex-shrink: 0; margin-top: 2px; }

/* motion */
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.pl-enter { animation: rise .28s ease-out; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
button:focus-visible { outline: 2px solid var(--contour); outline-offset: 2px; }
.leaflet-container { font-family: inherit; }
@media (prefers-reduced-motion: reduce) { .spin, .pl-enter { animation: none; } }
`;
