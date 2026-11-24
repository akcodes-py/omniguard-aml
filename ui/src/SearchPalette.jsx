import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, Play, Key, Refresh, ChevronRight } from "./icons.jsx";

export default function SearchPalette({ open, onClose, alerts, connected, busy, onLoad, onConnect }) {
  const [q, setQ] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQ("");
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return alerts.slice(0, 12);
    return alerts.filter((a) =>
      [a.alert_id, a.account_id, a.customer_name, a.trigger_reason, a.trigger]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(s))
    );
  }, [alerts, q]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/25 backdrop-blur-[2px] flex items-start justify-center pt-[12vh] px-4" onMouseDown={onClose}>
      <div
        className="w-full max-w-[560px] bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 h-[52px] border-b border-slate-100">
          <Search className="w-[18px] h-[18px] text-slate-400" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "Enter" && q.trim()) onLoad(q.trim());
            }}
            placeholder="Search alert ID, account, or typology…"
            className="flex-1 text-[13px] text-slate-800 placeholder:text-slate-400 focus:outline-none"
          />
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="max-h-[330px] overflow-y-auto py-1.5">
          {list.map((a) => (
            <button
              key={a.alert_id}
              onClick={() => onLoad(a.alert_id)}
              className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 text-left"
            >
              <span className="w-7 h-7 rounded-md bg-slate-100 border border-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-500 shrink-0">
                {(a.customer_name || a.account_id || "?").slice(0, 2).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2">
                  <span className="text-[12.5px] font-medium text-slate-800 truncate">
                    {a.customer_name || a.account_id}
                  </span>
                  <span className="text-[10px] font-mono text-slate-400">{a.alert_id}</span>
                </span>
                <span className="block text-[10.5px] text-slate-500 truncate">
                  {a.trigger_reason || a.trigger} · {a.status || "PENDING"}
                </span>
              </span>
              <ChevronRight className="w-3.5 h-3.5 text-slate-300" />
            </button>
          ))}
          {list.length === 0 && (
            <div className="px-4 py-8 text-center">
              <p className="text-[12px] text-slate-500 mb-3">No alert matches “{q}”.</p>
              <button
                onClick={() => onLoad(q.trim())}
                disabled={!connected}
                className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-40 border border-blue-200 rounded px-2.5 py-1.5"
              >
                <Play className="w-3 h-3" /> Load /graph/{q.trim()}
              </button>
            </div>
          )}
        </div>

        <div className="border-t border-slate-100 px-4 py-2.5 flex items-center justify-between">
          <span className="text-[10.5px] text-slate-400">
            {connected ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Engine connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> Demo mode — connect to load live alerts
              </span>
            )}
          </span>
          <button
            onClick={onConnect}
            className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-600 hover:text-slate-900"
          >
            <Key className="w-3.5 h-3.5" /> API key
          </button>
        </div>
        {busy && (
          <div className="px-4 py-2 border-t border-slate-100 text-[11px] text-slate-500 inline-flex items-center gap-2">
            <Refresh className="w-3.5 h-3.5 animate-spin" /> Loading graph…
          </div>
        )}
      </div>
    </div>
  );
}
