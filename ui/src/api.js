// API client. Base defaults to local FastAPI; override with VITE_API_URL.
// Key lives in React state only (memory) — never localStorage, never logged.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

let lastMs = 0;
export const getLastCallMs = () => lastMs;

export async function call(path, key, opts = {}) {
  const t0 = performance.now();
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { "Content-Type": "application/json", "X-API-Key": key, ...(opts.headers || {}) },
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`);
    return body;
  } finally {
    lastMs = Math.round(performance.now() - t0);
  }
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
