import React, { useState, useEffect, useRef } from "react";
import {
  MapPin, Mountain, Loader2, Crosshair, AlertTriangle, CheckCircle2,
  ShieldQuestion, ChevronRight, ChevronDown, Droplets, CloudRain, Route,
  Trees, Plug, FileText, ArrowRightLeft, Wind,
} from "lucide-react";
import * as api from "./plotlensApi";
import PlotMap from "./PlotMap";

/* PlotLens v4 — FULL analysis shown (paywall deferred).
   MOCK_API=true returns a complete 8-category report so you can see the whole
   platform. Flip to false later to use the real backend; re-enable gating then. */
const MOCK_API = false;

const STATUS = {
  good:    { label: "Looks good", color: "#3f7d4e", bg: "rgba(63,125,78,0.10)", icon: CheckCircle2 },
  caution: { label: "Caution",    color: "#b5862b", bg: "rgba(181,134,43,0.10)", icon: AlertTriangle },
  flag:    { label: "Flag",       color: "#b5452b", bg: "rgba(181,69,43,0.10)", icon: AlertTriangle },
  check:   { label: "Verify offline", color: "#5a6b8a", bg: "rgba(90,107,138,0.10)", icon: ShieldQuestion },
};
const SRC = { derived: { t: "Satellite-derived", c: "#3f7d4e" },
              partial: { t: "Indicative", c: "#b5862b" },
              offline: { t: "Needs site / legal check", c: "#5a6b8a" } };

// Maps icon names (strings) from the live backend to icon components.
const ICONS = { Mountain, Droplets, CloudRain, Route, Trees, ArrowRightLeft, Plug, FileText, Wind };
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
    <div style={S.app}>
      <style>{CSS}</style>
      <header style={S.header} onClick={() => { poll.current = false; setScreen("map"); }}>
        <div style={S.logoMark}><Crosshair size={18} strokeWidth={2.4} /></div>
        <div><div style={S.logoText}>PlotLens</div><div style={S.logoSub}>Read the ground before you buy</div></div>
        {MOCK_API && <span style={S.mockBadge}>MOCK</span>}
      </header>
      {screen === "map" && <MapScreen onPick={start} />}
      {screen === "loading" && <LoadingScreen pin={pin} />}
      {screen === "report" && <Report pin={pin} report={report} err={err} onBack={() => setScreen("map")} />}
      <footer style={S.footer}>Indicators are derived from public satellite, elevation and map data and are indicative only — not a guarantee, nor a substitute for a site survey, soil test, or legal title check.</footer>
    </div>
  );
}

function MapScreen({ onPick }) {
  return (
    <main style={S.main}>
      <PlotMap onPick={onPick} samples={PINS} />
      <div style={S.eyebrow}>Or pick a sample plot</div>
      {PINS.map((p) => (
        <button key={p.key} onClick={() => onPick(p)} style={S.sampleRow}>
          <div style={{ flex: 1, textAlign: "left" }}>
            <div style={S.sampleTitle}>{p.label}</div>
            <div style={S.sampleMeta}>{p.lat.toFixed(4)}, {p.lng.toFixed(4)}</div>
          </div>
          <ChevronRight size={18} color="#b3ae9f" />
        </button>
      ))}
    </main>
  );
}

function LoadingScreen({ pin }) {
  const steps = ["Submitting coordinates", "Fetching elevation & imagery", "Computing terrain & flow", "Scoring 8 categories"];
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((v) => (v + 1) % steps.length), 450); return () => clearInterval(t); }, []);
  return (
    <main style={{ ...S.main, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "55vh", gap: 16 }}>
      <Loader2 size={32} className="spin" color="#b5452b" />
      <div style={{ fontWeight: 600 }}>{pin?.label}</div>
      <div style={{ color: "#8a8577", fontSize: 14 }}>{steps[i]}…</div>
    </main>
  );
}

function Report({ pin, report, err, onBack }) {
  if (err) return (
    <main style={S.main}>
      <button onClick={onBack} style={S.backBtn}>← Back to map</button>
      <div style={{ ...S.verdict, background: STATUS.flag.bg, borderColor: STATUS.flag.color + "55" }}>
        <div style={{ ...S.verdictIcon, background: STATUS.flag.color }}><AlertTriangle size={20} color="#fff" /></div>
        <div><div style={{ fontWeight: 800, color: STATUS.flag.color }}>Something went wrong</div>
        <div style={{ fontSize: 13, color: "#4a4639", marginTop: 4 }}>{err}</div></div>
      </div>
    </main>
  );
  if (!report) return null;
  const st = STATUS[report.overall] || STATUS.good;
  const HIcon = st.icon;

  return (
    <main style={S.main}>
      <button onClick={onBack} style={S.backBtn}>← Back to map</button>
      <h1 style={S.reportTitle}>{pin?.label}</h1>
      <div style={S.coords}><MapPin size={13} /> {pin?.lat.toFixed(4)}, {pin?.lng.toFixed(4)}</div>

      <div style={{ ...S.verdict, background: st.bg, borderColor: st.color + "55" }}>
        <div style={{ ...S.verdictIcon, background: st.color }}><HIcon size={20} color="#fff" /></div>
        <div>
          <div style={{ fontSize: 13, color: "#6b6657" }}>Overall read</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: st.color }}>{st.label}</div>
        </div>
      </div>

      <ThenNow report={report} />

      <div style={S.eyebrow}>Site analysis · {report.categories.length} categories</div>
      {report.categories.map((c, i) => <Category key={i} cat={c} defaultOpen={i < 2} />)}
    </main>
  );
}

function ThenNow({ report }) {
  const [pos, setPos] = useState(50);
  const t = report.then, n = report.now;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={S.tnHead}><ArrowRightLeft size={15} /> What changed here</div>
      <div style={S.tnFrame}>
        <div style={{ ...S.tnLayer, background: grad(n.tint) }}><span style={S.tnYear}>{n.year}</span></div>
        <div style={{ ...S.tnLayer, width: `${pos}%`, borderRight: "2px solid #faf7ef", background: grad(t.tint) }}><span style={S.tnYear}>{t.year}</span></div>
        <input type="range" min="0" max="100" value={pos} onChange={(e) => setPos(+e.target.value)} style={S.tnRange} aria-label="Compare years" />
      </div>
      <div style={S.tnCaps}><span><b>{t.year}:</b> {t.cover}</span><span><b>{n.year}:</b> {n.cover}</span></div>
      <div style={S.artNote}>Computed artifacts (terrain flow map, then-vs-now imagery, access rings) appear here once the backend is connected.</div>
    </div>
  );
}

function Category({ cat, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const st = STATUS[cat.status] || STATUS.good;
  const src = SRC[cat.source];
  const Ic = resolveIcon(cat.icon);
  return (
    <div style={S.cat}>
      <button style={S.catHead} onClick={() => setOpen((o) => !o)}>
        <div style={{ ...S.catIcon, background: st.bg }}><Ic size={17} color={st.color} /></div>
        <div style={{ flex: 1, textAlign: "left" }}>
          <div style={S.catTitle}>{cat.title}</div>
          <div style={{ ...S.srcTag, color: src.c }}>{src.t}</div>
        </div>
        <span style={{ ...S.statusPill, color: st.color, background: st.bg }}>{st.label}</span>
        {open ? <ChevronDown size={17} color="#b3ae9f" /> : <ChevronRight size={17} color="#b3ae9f" />}
      </button>
      {open && (
        <div style={S.catBody}>
          {cat.rows.map(([k, v], i) => (
            <div key={i} style={{ ...S.row, borderBottom: i === cat.rows.length - 1 && !cat.offline_note ? "none" : "1px solid #f1ece0" }}>
              <span style={S.rowKey}>{k}</span><span style={S.rowVal}>{v}</span>
            </div>
          ))}
          {cat.offline_note && (
            <div style={S.offlineNote}><ShieldQuestion size={14} style={{ flexShrink: 0, marginTop: 1 }} /><span>{cat.offline_note}</span></div>
          )}
        </div>
      )}
    </div>
  );
}

const grad = (c) => `linear-gradient(135deg, ${c}, ${shade(c, -18)})`;
function shade(hex, amt) { const n = parseInt(hex.slice(1), 16); let r = Math.max(0, Math.min(255, (n >> 16) + amt)), g = Math.max(0, Math.min(255, ((n >> 8) & 255) + amt)), b = Math.max(0, Math.min(255, (n & 255) + amt)); return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`; }

const edge = "#e7e1d2", ink = "#1f1d18";
const S = {
  app: { maxWidth: 440, margin: "0 auto", minHeight: "100vh", background: "#faf7ef", color: ink, fontFamily: "'Inter', system-ui, sans-serif", display: "flex", flexDirection: "column" },
  header: { display: "flex", alignItems: "center", gap: 11, padding: "16px 18px", borderBottom: `1px solid ${edge}`, cursor: "pointer", position: "sticky", top: 0, background: "#faf7efee", backdropFilter: "blur(8px)", zIndex: 600 },
  logoMark: { width: 34, height: 34, borderRadius: 9, background: ink, color: "#faf7ef", display: "grid", placeItems: "center" },
  logoText: { fontWeight: 800, fontSize: 17, letterSpacing: "-0.02em" }, logoSub: { fontSize: 11, color: "#8a8577", marginTop: -1 },
  mockBadge: { marginLeft: "auto", fontSize: 10, fontWeight: 700, color: "#b5862b", background: "rgba(181,134,43,0.12)", padding: "3px 7px", borderRadius: 6 },
  main: { flex: 1, padding: "18px 18px 8px" },
  eyebrow: { fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#a39e8f", margin: "16px 0 8px" },
  sampleRow: { display: "flex", alignItems: "center", gap: 10, background: "#fff", border: `1px solid ${edge}`, borderRadius: 12, padding: "13px 14px", cursor: "pointer", width: "100%", marginBottom: 8 },
  sampleTitle: { fontWeight: 600, fontSize: 14 }, sampleMeta: { fontSize: 12, color: "#8a8577", marginTop: 2 },
  backBtn: { background: "none", border: "none", color: "#8a8577", fontSize: 13, cursor: "pointer", padding: 0, marginBottom: 8 },
  reportTitle: { fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em", margin: "2px 0 4px" },
  coords: { display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#8a8577", marginBottom: 16 },
  verdict: { display: "flex", gap: 12, alignItems: "flex-start", border: "1px solid", borderRadius: 14, padding: 15, marginBottom: 16 },
  verdictIcon: { width: 40, height: 40, borderRadius: 11, display: "grid", placeItems: "center", flexShrink: 0 },
  tnHead: { display: "flex", alignItems: "center", gap: 7, fontSize: 13, fontWeight: 600, color: "#6b6657", marginBottom: 8 },
  tnFrame: { position: "relative", height: 170, borderRadius: 14, overflow: "hidden", border: `1px solid ${edge}` },
  tnLayer: { position: "absolute", inset: 0, overflow: "hidden", display: "flex", alignItems: "flex-end" },
  tnYear: { position: "relative", margin: 10, fontSize: 12, fontWeight: 700, color: "#fff", background: "rgba(0,0,0,0.35)", padding: "3px 8px", borderRadius: 6 },
  tnRange: { position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0, cursor: "ew-resize", margin: 0 },
  tnCaps: { display: "flex", flexDirection: "column", gap: 3, fontSize: 12, color: "#6b6657", marginTop: 9 },
  artNote: { fontSize: 11, color: "#a39e8f", fontStyle: "italic", marginTop: 8, lineHeight: 1.4 },
  cat: { background: "#fff", border: `1px solid ${edge}`, borderRadius: 12, marginBottom: 8, overflow: "hidden" },
  catHead: { display: "flex", alignItems: "center", gap: 11, width: "100%", background: "none", border: "none", padding: "13px 14px", cursor: "pointer" },
  catIcon: { width: 34, height: 34, borderRadius: 9, display: "grid", placeItems: "center", flexShrink: 0 },
  catTitle: { fontWeight: 600, fontSize: 14 }, srcTag: { fontSize: 11, marginTop: 1, fontWeight: 600 },
  statusPill: { fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 20, whiteSpace: "nowrap" },
  catBody: { padding: "2px 14px 12px", borderTop: `1px solid ${edge}` },
  row: { display: "flex", justifyContent: "space-between", gap: 14, padding: "8px 0", fontSize: 13 },
  rowKey: { color: "#8a8577", flexShrink: 0 }, rowVal: { color: "#2c2a23", textAlign: "right", fontWeight: 500 },
  offlineNote: { display: "flex", gap: 8, fontSize: 12.5, lineHeight: 1.5, color: "#5a6b8a", marginTop: 10, background: "rgba(90,107,138,0.08)", padding: "11px 12px", borderRadius: 9 },
  footer: { fontSize: 11, lineHeight: 1.5, color: "#a39e8f", padding: "16px 20px 26px", borderTop: `1px solid ${edge}`, marginTop: 12 },
};
const CSS = `* { box-sizing: border-box; } body { margin: 0; }
.spin { animation: spin .9s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
.leaflet-container { font-family: inherit; }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }`;
