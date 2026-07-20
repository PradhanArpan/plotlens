import React, { useState, useEffect, useRef } from "react";
import {
  MapPin, Mountain, Loader2, Crosshair, AlertTriangle, CheckCircle2,
  ShieldQuestion, ChevronRight, ChevronDown, Droplets, CloudRain, Route,
  Trees, Plug, FileText, ArrowRightLeft, Wind, Database,
} from "lucide-react";
import * as api from "./plotlensApi";
import PlotMap from "./PlotMap";

/* PlotLens v6 — the report as a DOCUMENT.

   Designed for one reader doing one thing: a buyer reading a single site
   report end to end before spending a large sum of money. Not a dashboard.

   Consequences of that decision, which drive every layout choice below:
   - Desktop gets two columns: a sticky summary rail (verdict, headline facts,
     jump links) beside a single readable column of evidence at ~68ch measure.
     v5 was a 440px phone column marooned in a 1900px window; that alone made
     it read as unfinished.
   - Findings are ordered by CONSEQUENCE, not by data source. Anything flagged
     or cautioned is grouped first under "What could hurt you", because a buyer
     scanning for risk should not have to read past "Utilities: Indicative".
   - Legal sits last and is styled as the closing warning, where it lands
     hardest.
   - Monospace marks DATA (coordinates, source tags, figures) and nothing else.
     v5 used it decoratively for the tagline and labels, which cheapened it.
   - The header collapses to a slim bar once you scroll past it.

   Behaviour is unchanged from v4/v5: same API contract, same report schema,
   same PlotMap integration, same mock backend, same null-year and
   verdict_note handling. Only presentation changed.
   MOCK_API=true returns a complete report for offline UI work. */
const MOCK_API = false;

/* ---- design tokens ---- */
const T = {
  paper: "#EDF0EA", card: "#FBFCFA", ink: "#16231D", body: "#3A4842",
  faint: "#6E7C74", hair: "#DCE2DA", rule: "#C6CFC3", contour: "#8A6A3F",
  pass: "#2C7A4B", warn: "#9E6B15", flag: "#A33720", check: "#2A6785",
};

const STATUS = {
  good:    { label: "Looks good",     short: "Clear",   color: T.pass,  bg: "rgba(44,122,75,0.09)",  icon: CheckCircle2, rank: 0 },
  caution: { label: "Caution",        short: "Caution", color: T.warn,  bg: "rgba(158,107,21,0.10)", icon: AlertTriangle, rank: 2 },
  flag:    { label: "Flag",           short: "Flag",    color: T.flag,  bg: "rgba(163,55,32,0.10)",  icon: AlertTriangle, rank: 3 },
  check:   { label: "Verify offline", short: "Verify",  color: T.check, bg: "rgba(42,103,133,0.10)", icon: ShieldQuestion, rank: 1 },
};
const SRC = { derived: { t: "Satellite-derived", c: T.pass },
              partial: { t: "Indicative", c: T.warn },
              offline: { t: "Needs site / legal check", c: T.check },
              // Live source not connected yet. Distinct from "offline", which
              // means data satellites fundamentally cannot see (legal title).
              unavailable: { t: "Not connected yet", c: "#8A8E86" } };

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

/* ---------- small shared pieces ---------- */
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
/* Dropped pins arrive labelled with raw coordinates. Resolve a human place
   name via Nominatim (already the app's search provider; free, keyless) and
   fall back to the coordinates silently on any failure. */
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
      .then((d) => { const p = compactPlace(d && d.address);
                     if (p) { _placeCache[key] = p; if (live) setName(p); } })
      .catch(() => {})
      .finally(() => clearTimeout(t));
    return () => { live = false; ctl.abort(); };
  }, [pin]);
  if (!pin) return null;
  return looksLikeCoords(pin.label) ? name : pin.label;
}

function Coord({ lat, lng }) {
  if (lat == null) return null;
  return (
    <span className="pl-coord">
      {Math.abs(lat).toFixed(4)}°{lat >= 0 ? "N" : "S"}
      <span className="pl-coord-sep">/</span>
      {Math.abs(lng).toFixed(4)}°{lng >= 0 ? "E" : "W"}
    </span>
  );
}

/* Contour engraving — the one flourish, behind the verdict. */
function ContourPlate() {
  return (
    <svg className="pl-contours" viewBox="0 0 460 190" preserveAspectRatio="xMaxYMid slice" aria-hidden="true" focusable="false">
      <g fill="none" stroke={T.contour} strokeWidth="0.9">
        <path opacity="0.26" d="M352 190 C300 156 322 104 384 90 C448 76 492 120 484 190" />
        <path opacity="0.20" d="M330 190 C268 140 300 74 382 60 C464 46 518 108 510 190" />
        <path opacity="0.14" d="M306 190 C238 124 276 40 380 26 C484 12 542 96 534 190" />
        <path opacity="0.09" d="M280 190 C204 108 248 4 378 -10 C506 -24 568 84 562 190" />
      </g>
    </svg>
  );
}

/* Findings are grouped by consequence, not by data source. */
function groupCategories(cats) {
  const risk = [], verify = [], clear = [], legal = [];
  cats.forEach((c) => {
    const isLegal = /legal|development rules/i.test(c.title);
    if (isLegal) { legal.push(c); return; }
    const r = (STATUS[c.status] || STATUS.good).rank;
    if (r >= 2) risk.push(c);
    else if (r === 1) verify.push(c);
    else clear.push(c);
  });
  return { risk, verify, clear, legal };
}

export default function PlotLensApp() {
  const [screen, setScreen] = useState("map");
  const [pin, setPin] = useState(null);
  const [report, setReport] = useState(null);
  const [err, setErr] = useState(null);
  const [scrolled, setScrolled] = useState(false);
  const poll = useRef(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const start = async (p) => {
    setPin(p); setErr(null); setReport(null); setScreen("loading");
    window.scrollTo({ top: 0 });
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

  const home = () => { poll.current = false; setScreen("map"); window.scrollTo({ top: 0 }); };

  return (
    <div className="pl-app">
      <style>{CSS}</style>
      <header className={"pl-header" + (scrolled ? " pl-header-slim" : "")}>
        <button className="pl-brandbtn" onClick={home} aria-label="Back to map">
          <span className="pl-mark"><Crosshair size={16} strokeWidth={2.3} /></span>
          <span className="pl-brand">
            <span className="pl-brand-name">PlotLens</span>
            <span className="pl-brand-sub">Read the ground before you buy</span>
          </span>
        </button>
        {MOCK_API && <span className="pl-mock">MOCK DATA</span>}
      </header>

      {screen === "map" && <MapScreen onPick={start} />}
      {screen === "loading" && <LoadingScreen pin={pin} />}
      {screen === "report" && <Report pin={pin} report={report} err={err} onBack={home} />}

      <footer className="pl-footer">
        <div className="pl-footer-inner">
          Indicators are derived from public satellite, elevation and map data and are
          indicative only — not a guarantee, nor a substitute for a site survey, soil
          test, or legal title check.
        </div>
      </footer>
    </div>
  );
}

function MapScreen({ onPick }) {
  return (
    <main className="pl-main pl-main-map">
      <div className="pl-lede">
        <h1 className="pl-lede-h">Check the ground<br />before you buy it.</h1>
        <p className="pl-lede-p">
          Drop a pin on any plot in India. PlotLens reads public satellite,
          elevation and map data and tells you what the land itself says —
          drainage, access, what changed since 2017, and what no satellite can
          see.
        </p>
      </div>
      <div className="pl-mapframe"><PlotMap onPick={onPick} samples={PINS} /></div>
      <div className="pl-rule"><span>Or open a sample report</span></div>
      <div className="pl-samples">
        {PINS.map((p) => (
          <button key={p.key} onClick={() => onPick(p)} className="pl-sample">
            <span className="pl-sample-text">
              <span className="pl-sample-name">{p.label}</span>
              <Coord lat={p.lat} lng={p.lng} />
            </span>
            <ChevronRight size={16} className="pl-chev" />
          </button>
        ))}
      </div>
    </main>
  );
}

function LoadingScreen({ pin }) {
  const place = usePlaceName(pin);
  const steps = ["Submitting coordinates", "Fetching elevation & imagery",
                 "Computing terrain & flow", "Scoring site categories"];
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((v) => (v + 1) % steps.length), 900);
    return () => clearInterval(t);
  }, []);
  return (
    <main className="pl-main pl-loading">
      <Loader2 size={26} className="spin" color={T.contour} />
      <div className="pl-loading-site">{place || pin?.label}</div>
      <Coord lat={pin?.lat} lng={pin?.lng} />
      <ol className="pl-steps">
        {steps.map((s, k) => (
          <li key={s} className={k < i ? "done" : k === i ? "now" : ""}>{s}</li>
        ))}
      </ol>
    </main>
  );
}

function Report({ pin, report, err, onBack }) {
  const place = usePlaceName(pin);

  if (err) return (
    <main className="pl-main">
      <button onClick={onBack} className="pl-back">← Back to map</button>
      <div className="pl-doc">
        <div className="pl-verdict pl-verdict-err">
          <div className="pl-verdict-inner">
            <div className="pl-kicker">Survey record</div>
            <div className="pl-verdict-word" style={{ color: STATUS.flag.color }}>Report failed</div>
            <p className="pl-verdict-note">{err}</p>
          </div>
        </div>
      </div>
    </main>
  );
  if (!report) return null;

  const st = STATUS[report.overall] || STATUS.good;
  const HIcon = st.icon;
  const { risk, verify, clear, legal } = groupCategories(report.categories);
  const headline = pickHeadlineFacts(report);

  return (
    <main className="pl-main pl-report">
      <button onClick={onBack} className="pl-back">← Back to map</button>

      <div className="pl-layout">
        {/* -------- sticky summary rail -------- */}
        <aside className="pl-rail">
          <div className="pl-rail-inner">
            <div className="pl-kicker">Site</div>
            <h1 className="pl-title">{place || pin?.label}</h1>
            <div className="pl-title-coord">
              <MapPin size={11} /> <Coord lat={pin?.lat} lng={pin?.lng} />
            </div>

            <div className="pl-railverdict" style={{ borderColor: st.color, background: st.bg }}>
              <HIcon size={15} strokeWidth={2.4} color={st.color} />
              <span style={{ color: st.color }}>{st.label}</span>
            </div>

            {headline.length > 0 && (
              <dl className="pl-facts">
                {headline.map(([k, v]) => (
                  <div key={k} className="pl-fact">
                    <dt>{k}</dt><dd>{v}</dd>
                  </div>
                ))}
              </dl>
            )}

            <nav className="pl-jump" aria-label="Sections">
              {risk.length > 0 && <a href="#s-risk">What could hurt you <span>{risk.length}</span></a>}
              {verify.length > 0 && <a href="#s-verify">To verify <span>{verify.length}</span></a>}
              {clear.length > 0 && <a href="#s-clear">Nothing adverse found <span>{clear.length}</span></a>}
              {legal.length > 0 && <a href="#s-legal">Before you pay</a>}
            </nav>
          </div>
        </aside>

        {/* -------- document column -------- */}
        <div className="pl-doc">
          <section className="pl-verdict" style={{ borderColor: st.color }}>
            <ContourPlate />
            <div className="pl-verdict-inner">
              <div className="pl-kicker">Overall read</div>
              <div className="pl-stamp" style={{ color: st.color, borderColor: st.color }}>
                <HIcon size={17} strokeWidth={2.4} /> {st.label}
              </div>
              {report.verdict_note && <p className="pl-verdict-note">{report.verdict_note}</p>}
            </div>
          </section>

          <ThenNow report={report} />

          {risk.length > 0 && (
            <Section id="s-risk" title="What could hurt you" tone={T.flag}
                     blurb="Findings that a buyer should resolve before committing money.">
              {risk.map((c, i) => <Category key={i} cat={c} defaultOpen />)}
            </Section>
          )}

          {verify.length > 0 && (
            <Section id="s-verify" title="To verify on the ground" tone={T.check}
                     blurb="Indicative or unconnected data. Absence of a warning here is not an all-clear.">
              {verify.map((c, i) => <Category key={i} cat={c} />)}
            </Section>
          )}

          {clear.length > 0 && (
            <Section id="s-clear" title="Nothing adverse found" tone={T.pass}
                     blurb="Measured, and within normal ranges for this area.">
              {clear.map((c, i) => <Category key={i} cat={c} />)}
            </Section>
          )}

          {legal.length > 0 && (
            <Section id="s-legal" title="Before you pay" tone={T.check}
                     blurb="No satellite can see any of this. It is also where buyers lose the most money.">
              {legal.map((c, i) => <Category key={i} cat={c} defaultOpen />)}
            </Section>
          )}
        </div>
      </div>
    </main>
  );
}

/* Pull a few headline numbers for the rail. Reads whatever the backend sent —
   no assumptions about which categories exist. */
function pickHeadlineFacts(report) {
  const out = [];
  const find = (title, key) => {
    const c = report.categories.find((x) => new RegExp(title, "i").test(x.title));
    if (!c) return null;
    const row = c.rows.find((r) => new RegExp(key, "i").test(r[0]));
    return row ? row[1] : null;
  };
  const elev = find("topography", "^elevation");
  const slope = find("topography", "^slope");
  const road = find("circulation|access", "nearest road");
  const aqi = find("air quality", "^aqi");
  if (elev) out.push(["Elevation", elev]);
  if (slope) out.push(["Slope", slope]);
  if (road) out.push(["Nearest road", road]);
  if (aqi) out.push(["Air quality", aqi]);
  return out.slice(0, 4);
}

function Section({ id, title, tone, blurb, children }) {
  return (
    <section className="pl-section" id={id}>
      <h2 className="pl-h2" style={{ borderColor: tone }}>{title}</h2>
      {blurb && <p className="pl-blurb">{blurb}</p>}
      {children}
    </section>
  );
}

function ThenNow({ report }) {
  const [pos, setPos] = useState(50);
  const t = report.then, n = report.now;
  return (
    <section className="pl-tn">
      <h2 className="pl-h2 pl-h2-plain"><ArrowRightLeft size={15} /> What changed here</h2>
      <div className="pl-tn-frame">
        <div className="pl-tn-layer" style={{ background: grad(n.tint) }}>
          {n.year && <span className="pl-tn-year">{n.year}</span>}
        </div>
        <div className="pl-tn-layer pl-tn-top" style={{ width: `${pos}%`, background: grad(t.tint) }}>
          {t.year && <span className="pl-tn-year">{t.year}</span>}
        </div>
        <div className="pl-tn-handle" style={{ left: `${pos}%` }} aria-hidden="true" />
        <input type="range" min="0" max="100" value={pos} onChange={(e) => setPos(+e.target.value)}
               className="pl-tn-range" aria-label="Compare years" />
      </div>
      <div className="pl-tn-caps">
        <span>{t.year ? <b>{t.year}</b> : null}{t.year ? " · " : ""}{t.cover}</span>
        <span>{n.year ? <b>{n.year}</b> : null}{n.year ? " · " : ""}{n.cover}</span>
      </div>
      <p className="pl-tn-note">
        Computed artifacts (terrain flow map, access rings, then-vs-now panel) are
        generated by the backend but not yet displayed in this view.
      </p>
    </section>
  );
}

function Category({ cat, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const st = STATUS[cat.status] || STATUS.good;
  const src = SRC[cat.source];
  const Ic = resolveIcon(cat.icon);
  const reading = cat.rows.find((r) => /^reading$/i.test(r[0]));
  const rows = cat.rows.filter((r) => r !== reading);
  return (
    <article className={"pl-cat" + (open ? " open" : "")} style={{ "--rail": st.color }}>
      <button className="pl-cat-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="pl-cat-icon" style={{ background: st.bg }}><Ic size={15} color={st.color} /></span>
        <span className="pl-cat-text">
          <span className="pl-cat-title">{cat.title}</span>
          <span className="pl-cat-src" style={{ color: src.c }}>{src.t}</span>
        </span>
        <span className="pl-status" style={{ color: st.color, background: st.bg }}>{st.short}</span>
        {open ? <ChevronDown size={15} className="pl-chev" /> : <ChevronRight size={15} className="pl-chev" />}
      </button>
      {open && (
        <div className="pl-cat-body">
          {reading && <p className="pl-reading">{reading[1]}</p>}
          {rows.length > 0 && (
            <dl className="pl-rows">
              {rows.map(([k, v], i) => (
                <div key={i} className="pl-row"><dt>{k}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          )}
          {cat.offline_note && (
            <div className="pl-offline">
              <ShieldQuestion size={14} className="pl-offline-ic" /><span>{cat.offline_note}</span>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

const grad = (c) => `linear-gradient(140deg, ${c}, ${shade(c, -20)})`;
function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.max(0, Math.min(255, (n >> 16) + amt));
  const g = Math.max(0, Math.min(255, ((n >> 8) & 255) + amt));
  const b = Math.max(0, Math.min(255, (n & 255) + amt));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --paper: ${T.paper}; --card: ${T.card}; --ink: ${T.ink}; --body: ${T.body};
  --faint: ${T.faint}; --hair: ${T.hair}; --rule: ${T.rule}; --contour: ${T.contour};
  --serif: 'Fraunces', Georgia, serif;
  --sans: 'Public Sans', system-ui, -apple-system, sans-serif;
  --mono: 'IBM Plex Mono', ui-monospace, monospace;
  --measure: 68ch;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 90px; }
body { margin: 0; background: var(--paper); }

.pl-app { min-height: 100vh; background: var(--paper); color: var(--body);
  font-family: var(--sans); font-size: 15px; line-height: 1.6;
  display: flex; flex-direction: column; }

/* ---------- header: full, then slim on scroll ---------- */
.pl-header { position: sticky; top: 0; z-index: 800;
  display: flex; align-items: center; gap: 12px;
  padding: 18px 32px; border-bottom: 1px solid var(--hair);
  background: color-mix(in srgb, var(--paper) 88%, transparent);
  backdrop-filter: blur(10px); transition: padding .18s ease; }
.pl-header-slim { padding: 9px 32px; }
.pl-brandbtn { display: flex; align-items: center; gap: 11px; background: none;
  border: none; padding: 0; cursor: pointer; color: inherit; font: inherit; }
.pl-mark { width: 30px; height: 30px; background: var(--ink); color: var(--paper);
  display: grid; place-items: center; border-radius: 5px; flex-shrink: 0;
  transition: transform .18s ease; }
.pl-header-slim .pl-mark { transform: scale(.86); }
.pl-brand { display: flex; flex-direction: column; align-items: flex-start; }
.pl-brand-name { font-family: var(--serif); font-weight: 700; font-size: 19px;
  letter-spacing: -0.01em; color: var(--ink); line-height: 1.1; }
.pl-brand-sub { font-size: 12px; color: var(--faint); margin-top: 1px;
  max-height: 20px; opacity: 1; transition: max-height .18s ease, opacity .14s ease; }
.pl-header-slim .pl-brand-sub { max-height: 0; opacity: 0; overflow: hidden; }
.pl-mock { margin-left: auto; font-family: var(--mono); font-size: 10px;
  color: ${T.warn}; border: 1px solid ${T.warn}; padding: 2px 7px; border-radius: 3px; }

.pl-main { flex: 1; width: 100%; max-width: 1180px; margin: 0 auto;
  padding: 34px 32px 10px; }
.pl-footer { border-top: 1px solid var(--hair); margin-top: 40px; }
.pl-footer-inner { max-width: 1180px; margin: 0 auto; padding: 20px 32px 34px;
  font-size: 12.5px; color: var(--faint); max-width: 78ch; }

/* ---------- landing ---------- */
.pl-main-map { max-width: 860px; }
.pl-lede { margin-bottom: 26px; }
.pl-lede-h { font-family: var(--serif); font-weight: 700; font-size: 40px;
  line-height: 1.08; letter-spacing: -0.022em; color: var(--ink); margin: 0 0 12px; }
.pl-lede-p { max-width: 56ch; font-size: 15.5px; color: var(--body); margin: 0; }
.pl-mapframe { border: 1px solid var(--rule); border-radius: 8px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(22,35,29,.05), 0 8px 24px -18px rgba(22,35,29,.35); }
.pl-rule { display: flex; align-items: center; gap: 14px; margin: 26px 0 12px;
  font-family: var(--mono); font-size: 10.5px; letter-spacing: .09em;
  text-transform: uppercase; color: var(--faint); }
.pl-rule::before, .pl-rule::after { content: ""; flex: 1; height: 1px; background: var(--hair); }
.pl-samples { display: grid; gap: 8px; }
.pl-sample { display: flex; align-items: center; gap: 12px; width: 100%;
  text-align: left; background: var(--card); border: 1px solid var(--hair);
  border-radius: 6px; padding: 13px 15px; cursor: pointer; font: inherit;
  color: var(--ink); transition: border-color .14s, transform .14s; }
.pl-sample:hover { border-color: var(--contour); transform: translateX(2px); }
.pl-sample-text { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.pl-sample-name { font-weight: 600; font-size: 14.5px; }

/* ---------- loading ---------- */
.pl-loading { display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-height: 58vh; gap: 10px; text-align: center; }
.pl-loading-site { font-family: var(--serif); font-weight: 600; font-size: 22px;
  color: var(--ink); }
.pl-steps { list-style: none; padding: 0; margin: 18px 0 0; font-family: var(--mono);
  font-size: 12.5px; color: var(--faint); text-align: left; }
.pl-steps li { padding: 3px 0 3px 20px; position: relative; opacity: .45; }
.pl-steps li.done, .pl-steps li.now { opacity: 1; }
.pl-steps li.done::before { content: "✓"; position: absolute; left: 0; color: ${T.pass}; }
.pl-steps li.now::before { content: "▸"; position: absolute; left: 0; color: var(--contour); }

/* ---------- report: two columns ---------- */
.pl-report { padding-bottom: 30px; }
.pl-back { background: none; border: none; color: var(--faint); font: inherit;
  font-size: 13.5px; cursor: pointer; padding: 0; margin-bottom: 16px; }
.pl-back:hover { color: var(--ink); }
.pl-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 46px;
  align-items: start; }
.pl-rail-inner { position: sticky; top: 96px; }
.pl-doc { max-width: var(--measure); }

.pl-kicker { font-family: var(--mono); font-size: 10px; letter-spacing: .11em;
  text-transform: uppercase; color: var(--faint); margin-bottom: 6px; }
.pl-title { font-family: var(--serif); font-weight: 700; font-size: 25px;
  line-height: 1.14; letter-spacing: -0.018em; color: var(--ink); margin: 0 0 5px; }
.pl-title-coord { display: flex; align-items: center; gap: 5px; color: var(--faint);
  margin-bottom: 16px; }
.pl-coord { font-family: var(--mono); font-size: 11.5px; color: var(--faint); }
.pl-coord-sep { margin: 0 5px; color: var(--rule); }

.pl-railverdict { display: inline-flex; align-items: center; gap: 7px;
  border: 1px solid; border-radius: 5px; padding: 6px 11px; font-weight: 600;
  font-size: 13.5px; margin-bottom: 18px; }

.pl-facts { margin: 0 0 18px; padding: 14px 0 4px; border-top: 1px solid var(--hair); }
.pl-fact { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; }
.pl-fact dt { font-size: 12.5px; color: var(--faint); margin: 0; }
.pl-fact dd { margin: 0; font-family: var(--mono); font-size: 12.5px; color: var(--ink);
  text-align: right; font-variant-numeric: tabular-nums; }

.pl-jump { display: flex; flex-direction: column; border-top: 1px solid var(--hair);
  padding-top: 10px; }
.pl-jump a { display: flex; justify-content: space-between; align-items: center;
  gap: 10px; padding: 7px 0; font-size: 13.5px; color: var(--body);
  text-decoration: none; border-bottom: 1px solid transparent; }
.pl-jump a:hover { color: var(--ink); border-bottom-color: var(--hair); }
.pl-jump span { font-family: var(--mono); font-size: 11px; color: var(--faint); }

/* verdict block */
.pl-verdict { position: relative; overflow: hidden; background: var(--card);
  border: 1px solid; border-left-width: 3px; border-radius: 7px;
  padding: 20px 22px; margin-bottom: 30px; }
.pl-verdict-err { border-color: ${T.flag}; }
.pl-contours { position: absolute; right: 0; top: 0; height: 100%; width: 55%;
  pointer-events: none; }
.pl-verdict-inner { position: relative; }
.pl-stamp { display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--serif); font-weight: 700; font-size: 21px; letter-spacing: -0.01em;
  border: 2px solid; border-radius: 5px; padding: 5px 14px 6px;
  transform: rotate(-0.8deg); background: color-mix(in srgb, var(--card) 70%, transparent); }
.pl-verdict-word { font-family: var(--serif); font-weight: 700; font-size: 21px; }
.pl-verdict-note { font-size: 13.5px; color: var(--faint); margin: 13px 0 0;
  max-width: 52ch; }

/* section headings */
.pl-section { margin-bottom: 34px; }
.pl-h2 { font-family: var(--serif); font-weight: 600; font-size: 20px;
  letter-spacing: -0.012em; color: var(--ink); margin: 0 0 6px;
  padding-left: 12px; border-left: 3px solid; line-height: 1.25; }
.pl-h2-plain { border: none; padding: 0; display: flex; align-items: center; gap: 8px;
  font-size: 17px; margin-bottom: 12px; }
.pl-blurb { font-size: 13.5px; color: var(--faint); margin: 0 0 14px;
  padding-left: 15px; max-width: 56ch; }

/* then / now */
.pl-tn { margin-bottom: 34px; }
.pl-tn-frame { position: relative; height: 210px; border-radius: 7px; overflow: hidden;
  border: 1px solid var(--rule); }
.pl-tn-layer { position: absolute; inset: 0; display: flex; align-items: flex-end; }
.pl-tn-top { overflow: hidden; }
.pl-tn-handle { position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--paper); transform: translateX(-1px);
  box-shadow: 0 0 0 1px rgba(0,0,0,.18); }
.pl-tn-year { position: relative; margin: 12px; font-family: var(--mono);
  font-size: 11.5px; color: #fff; background: rgba(0,0,0,.42);
  padding: 3px 9px; border-radius: 3px; }
.pl-tn-range { position: absolute; inset: 0; width: 100%; height: 100%;
  opacity: 0; cursor: ew-resize; margin: 0; }
.pl-tn-caps { display: flex; flex-direction: column; gap: 3px; font-size: 13px;
  color: var(--faint); margin-top: 10px; }
.pl-tn-caps b { font-family: var(--mono); font-weight: 500; color: var(--ink); }
.pl-tn-note { font-size: 12px; color: #9AA59D; margin: 8px 0 0; max-width: 54ch; }

/* category cards */
.pl-cat { background: var(--card); border: 1px solid var(--hair);
  border-left: 3px solid var(--rail); border-radius: 6px; margin-bottom: 9px;
  overflow: hidden; transition: box-shadow .14s; }
.pl-cat.open { box-shadow: 0 1px 2px rgba(22,35,29,.05), 0 10px 26px -20px rgba(22,35,29,.4); }
.pl-cat-head { display: flex; align-items: center; gap: 12px; width: 100%;
  background: none; border: none; padding: 13px 15px; cursor: pointer;
  font: inherit; color: var(--ink); text-align: left; }
.pl-cat-icon { width: 30px; height: 30px; border-radius: 5px; display: grid;
  place-items: center; flex-shrink: 0; }
.pl-cat-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pl-cat-title { font-weight: 600; font-size: 14.5px; letter-spacing: -0.005em; }
.pl-cat-src { font-family: var(--mono); font-size: 10.5px; margin-top: 1px; }
.pl-status { font-family: var(--mono); font-size: 10.5px; padding: 3px 8px;
  border-radius: 3px; white-space: nowrap; }
.pl-cat-body { padding: 0 15px 14px 57px; }
.pl-reading { font-size: 14px; color: var(--body); margin: 0 0 12px;
  padding-bottom: 12px; border-bottom: 1px solid var(--hair); max-width: 52ch; }
.pl-rows { margin: 0; }
.pl-row { display: flex; justify-content: space-between; gap: 16px; padding: 6px 0;
  border-bottom: 1px dotted var(--hair); }
.pl-row:last-child { border-bottom: none; }
.pl-row dt { font-size: 13px; color: var(--faint); margin: 0; }
.pl-row dd { margin: 0; font-size: 13px; color: var(--ink); text-align: right;
  font-weight: 500; font-variant-numeric: tabular-nums; }
.pl-offline { display: flex; gap: 9px; font-size: 13px; color: ${T.check};
  margin-top: 12px; background: rgba(42,103,133,.07); padding: 12px 13px;
  border-radius: 5px; max-width: 54ch; }
.pl-offline-ic { flex-shrink: 0; margin-top: 2px; }
.pl-chev { color: #9AA59D; flex-shrink: 0; }

/* motion + focus */
.spin { animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
button:focus-visible, a:focus-visible { outline: 2px solid var(--contour); outline-offset: 2px; }
.leaflet-container { font-family: inherit; }

/* ---------- responsive: collapse to one column ---------- */
@media (max-width: 900px) {
  .pl-layout { grid-template-columns: 1fr; gap: 22px; }
  .pl-rail-inner { position: static; }
  .pl-jump { display: none; }
  .pl-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
  .pl-doc { max-width: none; }
  .pl-lede-h { font-size: 31px; }
}
@media (max-width: 620px) {
  .pl-header, .pl-header-slim { padding: 12px 18px; }
  .pl-main { padding: 22px 18px 8px; }
  .pl-footer-inner { padding: 18px 18px 28px; }
  .pl-lede-h { font-size: 27px; }
  .pl-cat-body { padding-left: 15px; }
  .pl-facts { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .spin { animation: none; }
  .pl-sample:hover { transform: none; }
}
`;
