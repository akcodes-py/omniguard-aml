// Deterministic graph layout: BFS rings around the focal node, then a light
// repulsion/spring relaxation so the result looks organic but never overlaps.

export function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hexPath(cx, cy, r) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 180) * (60 * i - 90);
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return `M${pts.map((p) => p.map((v) => v.toFixed(2)).join(",")).join("L")}Z`;
}

export function edgeTone(edge, maxAmount) {
  if (edge.laundering) return { color: "#e11d48", rank: 3 };
  if ((edge.channels || []).includes("wire")) return { color: "#b9a4e6", rank: 1 };
  const ratio = maxAmount > 0 ? edge.amount / maxAmount : 0;
  if (ratio >= 0.55) return { color: "#ef4444", rank: 2 };
  if (ratio >= 0.22) return { color: "#f19bb0", rank: 1 };
  return { color: "#cbd2da", rank: 0 };
}

export function layoutGraph(nodes, edges, width, height, focalId) {
  const n = nodes.length;
  if (!n) return { positions: {}, bounds: null };
  const pad = 56;
  const cx = width / 2;
  const cy = height / 2;
  const maxR = Math.max(90, Math.min(width, height) / 2 - pad);
  const rand = mulberry32(1337);

  const adj = new Map(nodes.map((x) => [x.id, new Set()]));
  edges.forEach((e) => {
    if (adj.has(e.source) && adj.has(e.target)) {
      adj.get(e.source).add(e.target);
      adj.get(e.target).add(e.source);
    }
  });

  const focal = focalId && adj.has(focalId) ? focalId : nodes[0].id;
  const depth = new Map([[focal, 0]]);
  const queue = [focal];
  while (queue.length) {
    const cur = queue.shift();
    for (const nb of adj.get(cur) || []) {
      if (!depth.has(nb)) {
        depth.set(nb, depth.get(cur) + 1);
        queue.push(nb);
      }
    }
  }
  let orphanDepth = 1;
  nodes.forEach((x) => {
    if (!depth.has(x.id)) depth.set(x.id, orphanDepth++);
  });

  const byDepth = new Map();
  nodes.forEach((x) => {
    const d = Math.min(depth.get(x.id) ?? 1, 3);
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d).push(x.id);
  });

  const positions = {};
  positions[focal] = { x: cx, y: cy };

  const depths = [...byDepth.keys()].filter((d) => d > 0).sort((a, b) => a - b);
  depths.forEach((d, di) => {
    const ring = byDepth.get(d);
    const radius = Math.min(maxR, 148 + di * 138 + (d > 2 ? 22 : 0));
    const offset = rand() * Math.PI * 2;
    ring.forEach((id, i) => {
      const jitter = (rand() - 0.5) * 0.18;
      const a = offset + (i / ring.length) * Math.PI * 2 + jitter;
      const rr = radius * (0.92 + rand() * 0.14);
      positions[id] = { x: cx + Math.cos(a) * rr, y: cy + Math.sin(a) * rr };
    });
  });

  // Relax: pairwise repulsion + weak edge springs + center gravity.
  const P = nodes.map((x) => ({ id: x.id, ...positions[x.id] }));
  const idx = new Map(P.map((p, i) => [p.id, i]));
  const springs = edges
    .map((e) => [idx.get(e.source), idx.get(e.target), e.amount || 0])
    .filter(([a, b]) => a != null && b != null);
  const maxAmount = Math.max(1, ...edges.map((e) => e.amount || 0));
  const minDist = 74;

  for (let iter = 0; iter < 220; iter++) {
    const alpha = 1 - iter / 220;
    for (let i = 0; i < P.length; i++) {
      for (let j = i + 1; j < P.length; j++) {
        const a = P[i];
        const b = P[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-4) {
          dx = (rand() - 0.5) * 2;
          dy = (rand() - 0.5) * 2;
          d2 = dx * dx + dy * dy;
        }
        const d = Math.sqrt(d2);
        const push = ((minDist * minDist) / d2) * 0.8 * alpha;
        const ux = dx / d;
        const uy = dy / d;
        a.x -= ux * push;
        a.y -= uy * push;
        b.x += ux * push;
        b.y += uy * push;
        if (d < minDist) {
          const overlap = (minDist - d) * 0.45;
          a.x -= ux * overlap;
          a.y -= uy * overlap;
          b.x += ux * overlap;
          b.y += uy * overlap;
        }
      }
    }
    springs.forEach(([i, j, amount]) => {
      const a = P[i];
      const b = P[j];
      const target = 110 + 54 * (1 - amount / maxAmount);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = ((d - target) / d) * 0.014 * alpha;
      a.x += dx * f;
      a.y += dy * f;
      b.x -= dx * f;
      b.y -= dy * f;
    });
    P.forEach((p) => {
      p.x += (cx - p.x) * 0.0005 * alpha;
      p.y += (cy - p.y) * 0.0005 * alpha;
    });
  }

  // Fill the canvas: scale the settled cluster up about the centre.
  let spanX = 0;
  let spanY = 0;
  P.forEach((p) => {
    spanX = Math.max(spanX, Math.abs(p.x - cx));
    spanY = Math.max(spanY, Math.abs(p.y - cy));
  });
  const fit = Math.min(
    2.15,
    Math.max(0.6, Math.min((width / 2 - pad) / Math.max(1, spanX), (height / 2 - pad) / Math.max(1, spanY)))
  );
  if (fit > 1.001) {
    P.forEach((p) => {
      p.x = cx + (p.x - cx) * fit;
      p.y = cy + (p.y - cy) * fit;
    });
  }

  const minX = pad;
  const maxX = width - pad;
  const minY = pad;
  const maxY = height - pad;
  P.forEach((p) => {
    p.x = Math.max(minX, Math.min(maxX, p.x));
    p.y = Math.max(minY, Math.min(maxY, p.y));
    positions[p.id] = { x: p.x, y: p.y };
  });

  let bounds = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  Object.values(positions).forEach((p) => {
    bounds.minX = Math.min(bounds.minX, p.x);
    bounds.minY = Math.min(bounds.minY, p.y);
    bounds.maxX = Math.max(bounds.maxX, p.x);
    bounds.maxY = Math.max(bounds.maxY, p.y);
  });
  return { positions, bounds };
}

export function money(v, { cents = false } = {}) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  });
}

export function shortTs(ts) {
  if (!ts) return "—";
  const s = String(ts).replace("T", " ").replace(/\+.*$/, "").replace(/Z$/, "");
  return s.slice(0, 19);
}

export function timeAgo(ts) {
  if (!ts) return "just now";
  const secs = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)} min ago`;
  return `${Math.round(secs / 3600)}h ago`;
}
