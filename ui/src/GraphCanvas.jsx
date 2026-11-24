import { useEffect, useMemo, useRef, useState } from "react";
import { hexPath, layoutGraph, edgeTone } from "./layout.js";
import { PersonGlyph, BankGlyph, CardGlyph, DocGlyph, BuildingGlyph, ZoomIn, ZoomOut, Fit } from "./icons.jsx";

const KIND = {
  card: { fill: "#2563eb", ring: "#1d4ed8", Glyph: CardGlyph, label: "Card" },
  person: { fill: "#0f9d8f", ring: "#0b7f74", Glyph: PersonGlyph, label: "Person" },
  business: { fill: "#64748b", ring: "#475569", Glyph: BankGlyph, label: "Business" },
  account: { fill: "#64748b", ring: "#475569", Glyph: BankGlyph, label: "Account" },
  document: { fill: "#7cb342", ring: "#5f8f2f", Glyph: DocGlyph, label: "Document" },
  entity: { fill: "#64748b", ring: "#475569", Glyph: BuildingGlyph, label: "Entity" },
};

export const kindStyle = (k) => KIND[k] || KIND.account;

function useSize(ref) {
  const [size, setSize] = useState({ w: 900, h: 640 });
  useEffect(() => {
    if (!ref.current) return undefined;
    const el = ref.current;
    const measure = () => setSize({ w: el.clientWidth || 900, h: el.clientHeight || 640 });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

export default function GraphCanvas({ data, selectedId, onSelect, filters }) {
  const wrapRef = useRef(null);
  const { w, h } = useSize(wrapRef);
  const [hover, setHover] = useState(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef(null);

  const visible = useMemo(() => {
    const kinds = new Set(filters.kinds);
    let nodes = data.nodes.filter((n) => kinds.has(n.kind));
    if (filters.highRiskOnly) {
      const keep = new Set(nodes.filter((n) => n.high_risk || n.is_focal).map((n) => n.id));
      nodes = nodes.filter((n) => keep.has(n.id));
    }
    const ids = new Set(nodes.map((n) => n.id));
    const edges = data.edges.filter(
      (e) => ids.has(e.source) && ids.has(e.target) && (e.amount || 0) >= (filters.minAmount || 0)
    );
    return { nodes, edges };
  }, [data, filters]);

  const { positions } = useMemo(
    () => layoutGraph(visible.nodes, visible.edges, w, h, data.focal?.id),
    [visible, w, h, data.focal?.id]
  );

  const maxAmount = useMemo(
    () => Math.max(1, ...visible.edges.map((e) => e.amount || 0)),
    [visible.edges]
  );

  useEffect(() => {
    setView({ x: 0, y: 0, k: 1 });
  }, [data.alert?.alert_id]);

  const focus = hover;
  const connected = useMemo(() => {
    const s = new Set();
    visible.edges.forEach((e) => {
      if (e.source === focus || e.target === focus) {
        s.add(e.source);
        s.add(e.target);
      }
    });
    return s;
  }, [visible.edges, focus]);

  function onWheel(e) {
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    setView((v) => {
      const k = Math.max(0.45, Math.min(2.6, v.k * (e.deltaY > 0 ? 0.92 : 1.08)));
      const scale = k / v.k;
      return { k, x: mx - (mx - v.x) * scale, y: my - (my - v.y) * scale };
    });
  }

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [w, h]);

  function onPointerDown(e) {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }
  function onPointerMove(e) {
    if (!drag.current) return;
    setView((v) => ({
      ...v,
      x: drag.current.vx + (e.clientX - drag.current.x),
      y: drag.current.vy + (e.clientY - drag.current.y),
    }));
  }
  function onPointerUp() {
    drag.current = null;
  }

  const zoomBy = (f) =>
    setView((v) => {
      const k = Math.max(0.45, Math.min(2.6, v.k * f));
      const cx = w / 2;
      const cy = h / 2;
      const scale = k / v.k;
      return { k, x: cx - (cx - v.x) * scale, y: cy - (cy - v.y) * scale };
    });

  return (
    <div
      ref={wrapRef}
      className="absolute inset-0 overflow-hidden select-none"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      style={{ cursor: drag.current ? "grabbing" : "default" }}
    >
      <svg width={w} height={h} className="block">
        <defs>
          <filter id="nodeShadow" x="-40%" y="-40%" width="180%" height="180%">
            <feDropShadow dx="0" dy="1.5" stdDeviation="1.6" floodColor="#0f172a" floodOpacity="0.22" />
          </filter>
          <filter id="selShadow" x="-60%" y="-60%" width="220%" height="220%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#0f172a" floodOpacity="0.28" />
          </filter>
        </defs>
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {visible.edges.map((e) => {
            const a = positions[e.source];
            const b = positions[e.target];
            if (!a || !b) return null;
            const tone = edgeTone(e, maxAmount);
            const width = 3 + 9 * Math.sqrt((e.amount || 0) / maxAmount);
            const dim = focus ? !(e.source === focus || e.target === focus) : false;
            return (
              <line
                key={e.id}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={tone.color}
                strokeWidth={width}
                strokeLinecap="round"
                opacity={dim ? 0.16 : 1}
                style={{ transition: "opacity 140ms ease" }}
              />
            );
          })}
          {visible.nodes.map((node) => {
            const p = positions[node.id];
            if (!p) return null;
            const st = kindStyle(node.kind);
            const Glyph = st.Glyph;
            const isSel = node.id === selectedId;
            const isFocus = node.id === focus;
            const dim = focus && !connected.has(node.id) && !isFocus;
            return (
              <g
                key={node.id}
                transform={`translate(${p.x},${p.y})`}
                opacity={dim ? 0.42 : 1}
                style={{ transition: "opacity 140ms ease", cursor: "pointer" }}
                onPointerDown={(ev) => ev.stopPropagation()}
                onClick={(ev) => {
                  ev.stopPropagation();
                  onSelect(node.id);
                }}
                onMouseEnter={() => setHover(node.id)}
                onMouseLeave={() => setHover(null)}
              >
                <title>{`${node.label} · ${st.label}`}</title>
                {isSel && (
                  <circle r={27} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="3 3" />
                )}
                {node.high_risk && (
                  <circle r={23.5} fill="none" stroke="#e11d48" strokeWidth={2.6} opacity={0.9} />
                )}
                <path
                  d={hexPath(0, 0, 19)}
                  fill={st.fill}
                  stroke={isFocus ? "#ffffff" : st.ring}
                  strokeWidth={isFocus ? 2.2 : 1}
                  filter={isSel ? "url(#selShadow)" : "url(#nodeShadow)"}
                />
                <g transform="translate(-8.5,-8.5)">
                  <Glyph className="w-4 h-4" />
                </g>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="absolute right-4 bottom-4 flex flex-col gap-1.5">
        <button onClick={() => zoomBy(1.18)} title="Zoom in"
          className="w-8 h-8 bg-white/95 border border-slate-200 rounded-md shadow-sm text-slate-500 hover:text-slate-900 hover:bg-white flex items-center justify-center">
          <ZoomIn className="w-4 h-4" />
        </button>
        <button onClick={() => zoomBy(0.85)} title="Zoom out"
          className="w-8 h-8 bg-white/95 border border-slate-200 rounded-md shadow-sm text-slate-500 hover:text-slate-900 hover:bg-white flex items-center justify-center">
          <ZoomOut className="w-4 h-4" />
        </button>
        <button onClick={() => setView({ x: 0, y: 0, k: 1 })} title="Reset view"
          className="w-8 h-8 bg-white/95 border border-slate-200 rounded-md shadow-sm text-slate-500 hover:text-slate-900 hover:bg-white flex items-center justify-center">
          <Fit className="w-4 h-4" />
        </button>
      </div>

      <div className="absolute left-4 bottom-4 flex items-center gap-3 text-[10.5px] text-slate-400">
        <span className="flex items-center gap-1.5"><span className="w-4 h-[3px] rounded-full bg-rose-500" /> high exposure</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-[3px] rounded-full bg-rose-300" /> medium</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-[3px] rounded-full bg-slate-300" /> low</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-[3px] rounded-full bg-violet-300" /> cross-border wire</span>
      </div>
    </div>
  );
}
