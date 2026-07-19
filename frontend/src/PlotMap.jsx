import React, { useEffect, useRef, useState } from "react";
import { MapPin, Crosshair, Navigation } from "lucide-react";

/* PlotMap — a real pannable/zoomable map with tap-to-drop-pin.
   Uses Leaflet via CDN (loaded dynamically) so it needs no build-time import
   fiddling and no API key. Tiles from OpenStreetMap.

   Props:
     onPick({lat, lng})  -> called when user confirms a plot
     samples             -> [{key,label,lat,lng}] quick-jump buttons
*/

const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";

function loadLeaflet() {
  return new Promise((resolve, reject) => {
    if (window.L) return resolve(window.L);
    if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
    if (document.querySelector(`script[src="${LEAFLET_JS}"]`)) {
      const wait = setInterval(() => { if (window.L) { clearInterval(wait); resolve(window.L); } }, 50);
      return;
    }
    const s = document.createElement("script");
    s.src = LEAFLET_JS;
    s.onload = () => resolve(window.L);
    s.onerror = () => reject(new Error("Could not load the map library. Check your connection."));
    document.body.appendChild(s);
  });
}

export default function PlotMap({ onPick, samples = [] }) {
  const mapEl = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [picked, setPicked] = useState(null);   // {lat,lng}
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    loadLeaflet().then((L) => {
      if (cancelled || mapRef.current || !mapEl.current) return;
      const map = L.map(mapEl.current, { zoomControl: true, attributionControl: true })
        .setView([12.97, 77.59], 11);   // Bengaluru default
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(map);

      const redIcon = L.divIcon({
        className: "plotlens-pin",
        html: '<div style="transform:translate(-50%,-100%)"><svg width="30" height="30" viewBox="0 0 24 24" fill="#b5452b" stroke="#fff" stroke-width="1.5"><path d="M12 21s7-6.5 7-12a7 7 0 1 0-14 0c0 5.5 7 12 7 12z"/><circle cx="12" cy="9" r="2.5" fill="#fff" stroke="none"/></svg></div>',
        iconSize: [30, 30], iconAnchor: [0, 0],
      });

      const drop = (lat, lng) => {
        setPicked({ lat, lng });
        if (markerRef.current) markerRef.current.setLatLng([lat, lng]);
        else markerRef.current = L.marker([lat, lng], { icon: redIcon }).addTo(map);
      };

      map.on("click", (e) => drop(e.latlng.lat, e.latlng.lng));
      mapRef.current = map;
      mapRef.current._drop = drop;
      setReady(true);
    }).catch((e) => setError(e.message));

    return () => {
      cancelled = true;
      if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }
    };
  }, []);

  const flyTo = (s) => {
    if (!mapRef.current) return;
    mapRef.current.flyTo([s.lat, s.lng], 14, { duration: 0.8 });
    mapRef.current._drop(s.lat, s.lng);
  };

  if (error) {
    return (
      <div style={S.errorBox}>
        <Navigation size={22} color="#b5452b" />
        <div style={{ fontWeight: 600 }}>Map couldn't load</div>
        <div style={{ fontSize: 13, color: "#6b6657", textAlign: "center" }}>{error}</div>
        <div style={{ fontSize: 12, color: "#a39e8f" }}>You can still use the sample plots below.</div>
        <div style={S.sampleRow}>
          {samples.map((s) => (
            <button key={s.key} style={S.sampleChip} onClick={() => onPick({ lat: s.lat, lng: s.lng, label: s.label, archetype: s.archetype })}>
              {s.label.split(",")[0]}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={S.mapWrap}>
        <div ref={mapEl} style={S.map} />
        {!ready && <div style={S.loadingOverlay}>Loading map…</div>}
        <div style={S.hint}><MapPin size={13} /> Tap anywhere on the map to drop a pin</div>
      </div>

      {/* quick jump to samples */}
      <div style={S.jumpRow}>
        <span style={S.jumpLabel}>Jump to:</span>
        {samples.map((s) => (
          <button key={s.key} style={S.jumpChip} onClick={() => flyTo(s)}>
            {s.label.split(",")[0]}
          </button>
        ))}
      </div>

      {/* confirm bar */}
      {picked && (
        <div style={S.confirmBar}>
          <div>
            <div style={{ fontSize: 12, color: "#8a8577" }}>Selected location</div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>
              {picked.lat.toFixed(4)}, {picked.lng.toFixed(4)}
            </div>
          </div>
          <button style={S.analyseBtn}
                  onClick={() => onPick({ lat: picked.lat, lng: picked.lng, label: `${picked.lat.toFixed(4)}, ${picked.lng.toFixed(4)}`, archetype: "filled_pond" })}>
            <Crosshair size={16} /> Analyse this plot
          </button>
        </div>
      )}
    </div>
  );
}

const edge = "#e7e1d2", ink = "#1f1d18";
const S = {
  mapWrap: { position: "relative", height: 320, borderRadius: 16, overflow: "hidden", border: `1px solid ${edge}` },
  map: { position: "absolute", inset: 0, width: "100%", height: "100%" },
  loadingOverlay: { position: "absolute", inset: 0, display: "grid", placeItems: "center", background: "#eef0e8", color: "#6b6657", fontSize: 14, zIndex: 500 },
  hint: { position: "absolute", bottom: 12, left: 12, fontSize: 12, color: "#2c2a23", background: "#faf7efe6", padding: "6px 10px", borderRadius: 8, display: "flex", alignItems: "center", gap: 6, zIndex: 500, pointerEvents: "none" },
  jumpRow: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "12px 0" },
  jumpLabel: { fontSize: 12, color: "#8a8577" },
  jumpChip: { fontSize: 12.5, padding: "6px 12px", borderRadius: 20, border: `1px solid ${edge}`, background: "#fff", color: ink, cursor: "pointer" },
  confirmBar: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, background: "#fff", border: `1px solid ${edge}`, borderRadius: 12, padding: "12px 14px", marginBottom: 8 },
  analyseBtn: { display: "flex", alignItems: "center", gap: 7, background: "#b5452b", color: "#fff", border: "none", borderRadius: 10, padding: "11px 16px", fontSize: 14, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" },
  errorBox: { display: "flex", flexDirection: "column", alignItems: "center", gap: 8, padding: 24, background: "#fff", border: `1px solid ${edge}`, borderRadius: 16 },
  sampleRow: { display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center", marginTop: 8 },
  sampleChip: { fontSize: 12.5, padding: "8px 14px", borderRadius: 20, border: `1px solid ${edge}`, background: "#faf7ef", color: ink, cursor: "pointer" },
};
