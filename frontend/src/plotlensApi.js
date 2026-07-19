// plotlensApi.js — client for the PlotLens backend.
// Drop-in module the React app imports. Handles submit -> poll -> unlock -> pdf.
//
// Configure the base URL via Vite env: VITE_PLOTLENS_API=https://api.yourdomain.com
// Falls back to localhost for dev.

const BASE =
  (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_PLOTLENS_API) ||
  "http://localhost:8000";

async function jsonOrThrow(res) {
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    throw new ApiError(res.status, detail || res.statusText);
  }
  return res.json();
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

// Kick off a report. Returns { job_id, status }.
export async function createReport({ lat, lng, archetype = "filled_pond" }) {
  const res = await fetch(`${BASE}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lat, lng, archetype }),
  });
  return jsonOrThrow(res);
}

// Get current state of a job. Returns either:
//   { status: 'running' }
//   { status: 'done', tier: 'free', overall, topography, locked, unlock_price_inr }
//   { status: 'done', tier: 'full', result }
//   { status: 'error', error }
export async function getReport(jobId) {
  const res = await fetch(`${BASE}/report/${jobId}`);
  return jsonOrThrow(res);
}

// Poll until done or error, with backoff. onTick(status) fires each poll.
export async function pollReport(jobId, { onTick, intervalMs = 1200, timeoutMs = 60000 } = {}) {
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await getReport(jobId);
    if (onTick) onTick(state);
    if (state.status === "done" || state.status === "error") return state;
    if (Date.now() - start > timeoutMs) throw new ApiError(408, "Report timed out");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// Confirm payment + unlock the full report. payment_token comes from Razorpay.
export async function unlockReport(jobId, paymentToken) {
  const res = await fetch(
    `${BASE}/report/${jobId}/unlock?payment_token=${encodeURIComponent(paymentToken)}`,
    { method: "POST" }
  );
  return jsonOrThrow(res);
}

// URL for the gated PDF (only works after unlock; backend returns 402 otherwise).
export function pdfUrl(jobId) {
  return `${BASE}/report/${jobId}/pdf`;
}

export async function health() {
  return jsonOrThrow(await fetch(`${BASE}/health`));
}
