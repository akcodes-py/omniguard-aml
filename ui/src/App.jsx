import { useCallback, useEffect, useMemo, useState } from "react";
import { call } from "./api.js";
import { DEMO_GRAPH, DEMO_ALERTS } from "./demo.js";
import Rail from "./Rail.jsx";
import SearchPalette from "./SearchPalette.jsx";
import GraphCanvas, { kindStyle } from "./GraphCanvas.jsx";
import Inspector from "./Inspector.jsx";
import Review from "./Review.jsx";
import ScenarioLab from "./ScenarioLab.jsx";
import { Grid, Check, X, Key, Refresh, Alert, Play, Menu } from "./icons.jsx";

const ALL_KINDS = ["card", "person", "business", "account", "document"];

function Toggle({ mode, setMode }) {
  return (
    <div className="flex items-center bg-white rounded-lg border border-slate-200 shadow-sm p-[3px]">
      {[
        ["genome", "Genome", Grid],
        ["review", "Review", Check],
      ].map(([id, label, Icon]) => (
        <button
          key={id}
          onClick={() => setMode(id)}
          className={`flex items-center gap-1.5 h-7 px-3 rounded-md text-[12px] font-medium transition-colors ${
            mode === id ? "bg-blue-600 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
          }`}
        >
          <Icon className="w-[13px] h-[13px]" />
          {label}
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [apiKey, setApiKey] = useState("");
  const [keyDraft, setKeyDraft] = useState("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connError, setConnError] = useState(null);

  const [data, setData] = useState(DEMO_GRAPH);
  const [selectedId, setSelectedId] = useState("CC1");
  const [mode, setMode] = useState(() => {
    const h = typeof window !== "undefined" ? window.location.hash.replace("#", "") : "";
    return ["genome", "review", "scenario"].includes(h) ? h : "genome";
  });
  const [panelOpen, setPanelOpen] = useState(true);
  const [loading, setLoading] = useState(false);

  const [searchOpen, setSearchOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alerts, setAlerts] = useState(DEMO_ALERTS);

  const [filters, setFilters] = useState({
    kinds: ALL_KINDS,
    highRiskOnly: false,
    minAmount: 0,
  });

  const [toast, setToast] = useState(null);
  const notify = useCallback((msg, tone = "ok") => setToast({ msg, tone, at: Date.now() }), []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
      if (e.key === "Escape") {
        setSearchOpen(false);
        setFiltersOpen(false);
        setInfoOpen(false);
        setConnectOpen(false);
        setAlertsOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loadGraph = useCallback(
    async (alertId) => {
      if (!connected) {
        setConnectOpen(true);
        notify("Connect the engine to load live alerts", "warn");
        return;
      }
      setLoading(true);
      try {
        const g = await call(`/graph/${encodeURIComponent(alertId)}`, apiKey);
        setData({ ...g, source: "live", fetchedAt: Date.now() });
        setSelectedId(g.focal?.id || g.nodes?.[0]?.id);
        setMode("genome");
        setSearchOpen(false);
        setAlertsOpen(false);
        notify(`Loaded ${g.nodes.length} entities · ${g.edges.length} links`, "ok");
      } catch (e) {
        notify(String(e), "err");
      } finally {
        setLoading(false);
      }
    },
    [apiKey, connected, notify]
  );

  async function connect() {
    if (!keyDraft.trim()) return;
    setConnecting(true);
    setConnError(null);
    try {
      await call("/auth/check", keyDraft.trim());
      setApiKey(keyDraft.trim());
      setConnected(true);
      const a = await call("/alerts", keyDraft.trim());
      if (a?.alerts?.length) {
        setAlerts(a.alerts);
        const g = await call(`/graph/${encodeURIComponent(a.alerts[0].alert_id)}`, keyDraft.trim());
        setData({ ...g, source: "live", fetchedAt: Date.now() });
        setSelectedId(g.focal?.id || g.nodes?.[0]?.id);
      }
      setConnectOpen(false);
      notify("Compliance engine connected", "ok");
    } catch (e) {
      setConnError(String(e));
    } finally {
      setConnecting(false);
    }
  }

  const selected = useMemo(
    () => data.nodes.find((n) => n.id === selectedId) || data.focal || data.nodes[0],
    [data, selectedId]
  );

  const maxEdge = useMemo(
    () => Math.max(1, ...data.edges.map((e) => e.amount || 0)),
    [data.edges]
  );

  const toggleKind = (kind) =>
    setFilters((f) => ({
      ...f,
      kinds: f.kinds.includes(kind) ? f.kinds.filter((k) => k !== kind) : [...f.kinds, kind],
    }));

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[#f4f6f8] text-slate-800">
      <Rail
        mode={mode}
        onMode={(m) => {
          setMode(m);
          setFiltersOpen(false);
          setInfoOpen(false);
        }}
        onSearch={() => setSearchOpen(true)}
        onFilters={() => {
          setFiltersOpen((v) => !v);
          setInfoOpen(false);
        }}
        filtersOpen={filtersOpen}
        onInfo={() => {
          setInfoOpen((v) => !v);
          setFiltersOpen(false);
        }}
        infoOpen={infoOpen}
        onAlerts={() => setAlertsOpen(true)}
      />

      <div className="flex-1 flex min-w-0 relative">
        <div className="flex-1 min-w-0 relative flex flex-col">
          {/* context bar */}
          {mode !== "scenario" && (
          <div className="absolute left-5 top-4 z-20 flex items-center gap-2">
            <span className="text-[11px] text-slate-500">Alert</span>
            <span className="font-mono text-[10.5px] bg-white border border-slate-200 rounded px-2 py-1 shadow-sm text-slate-700">
              {data.alert?.alert_id || "—"}
            </span>
            {data.source === "demo" ? (
              <span className="text-[9.5px] font-bold tracking-wider text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-[3px]">
                DEMO
              </span>
            ) : (
              <span className="text-[9.5px] font-bold tracking-wider text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-[3px]">
                LIVE
              </span>
            )}
            <span className="text-[11px] text-slate-400 hidden md:inline">
              {data.alert?.trigger_reason || ""}
            </span>
          </div>
          )}

          {/* top-right controls */}
          <div className="absolute right-4 top-3.5 z-20 flex items-center gap-3">
            {mode === "scenario" ? (
              <button
                onClick={() => setMode("genome")}
                className="h-8 px-3 rounded-lg bg-white border border-slate-200 shadow-sm text-[12px] font-medium text-slate-600 hover:text-slate-900"
              >
                ← Back to graph
              </button>
            ) : (
              <Toggle mode={mode} setMode={setMode} />
            )}
            <button
              onClick={() => setConnectOpen(true)}
              className="flex items-center gap-2 pl-1 pr-2.5 h-8 rounded-full bg-white border border-slate-200 shadow-sm hover:border-slate-300"
              title={connected ? "Engine connected" : "Connect compliance engine"}
            >
              <span className="relative w-6 h-6 rounded-full bg-[#0b1b2b] text-white text-[9.5px] font-semibold flex items-center justify-center">
                R
                <span
                  className={`absolute -right-0.5 -bottom-0.5 w-2 h-2 rounded-full border-2 border-white ${
                    connected ? "bg-emerald-500" : "bg-amber-400"
                  }`}
                />
              </span>
              <span className="text-[11.5px] font-medium text-slate-600">Ross</span>
            </button>
          </div>

          {/* main canvas */}
          <div className="flex-1 min-h-0 relative">
            {mode === "genome" && (
              <GraphCanvas
                data={data}
                selectedId={selectedId}
                onSelect={setSelectedId}
                filters={filters}
              />
            )}
            {mode === "review" && (
              <Review
                apiKey={apiKey}
                alertId={data.alert?.alert_id}
                connected={connected && data.source !== "demo"}
                demo={data.source === "demo"}
                onToast={notify}
              />
            )}
            {mode === "scenario" && (
              <ScenarioLab apiKey={apiKey} connected={connected} onToast={notify} />
            )}

            {loading && (
              <div className="absolute inset-0 z-30 bg-white/50 backdrop-blur-[1px] flex items-center justify-center">
                <span className="inline-flex items-center gap-2 text-[12px] text-slate-600 bg-white border border-slate-200 rounded-lg px-3.5 py-2 shadow-sm">
                  <Refresh className="w-4 h-4 animate-spin" /> Loading graph…
                </span>
              </div>
            )}
          </div>
        </div>

        {mode !== "scenario" && (
          <Inspector
            data={data}
            selectedId={selectedId}
            onSelect={setSelectedId}
            open={panelOpen}
            onToggle={() => setPanelOpen((v) => !v)}
          />
        )}

        {/* filters popover */}
        {filtersOpen && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setFiltersOpen(false)} />
            <div className="absolute left-0 top-[218px] z-40 w-[248px] bg-white border border-slate-200 rounded-xl shadow-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[12px] font-semibold text-slate-900">Graph filters</h3>
                <button onClick={() => setFiltersOpen(false)} className="text-slate-400 hover:text-slate-700">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-400 mb-2">Entity types</p>
              <div className="space-y-1.5 mb-4">
                {ALL_KINDS.map((k) => {
                  const st = kindStyle(k);
                  const on = filters.kinds.includes(k);
                  return (
                    <button
                      key={k}
                      onClick={() => toggleKind(k)}
                      className="w-full flex items-center gap-2.5 text-left py-0.5"
                    >
                      <span
                        className={`w-3.5 h-3.5 rounded-[3px] border flex items-center justify-center ${
                          on ? "border-transparent" : "border-slate-300 bg-white"
                        }`}
                        style={on ? { background: st.fill } : undefined}
                      >
                        {on && <Check className="w-2.5 h-2.5 text-white" />}
                      </span>
                      <span className="text-[11.5px] text-slate-700 flex-1">{st.label}</span>
                      <span className="text-[10px] text-slate-400 tabular-nums">
                        {data.nodes.filter((n) => n.kind === k).length}
                      </span>
                    </button>
                  );
                })}
              </div>

              <label className="flex items-center justify-between py-1.5 border-t border-slate-100">
                <span className="text-[11.5px] text-slate-700">High-risk only</span>
                <button
                  onClick={() => setFilters((f) => ({ ...f, highRiskOnly: !f.highRiskOnly }))}
                  className={`w-8 h-[18px] rounded-full transition-colors relative ${filters.highRiskOnly ? "bg-blue-600" : "bg-slate-300"}`}
                >
                  <span
                    className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all ${
                      filters.highRiskOnly ? "left-[16px]" : "left-[2px]"
                    }`}
                  />
                </button>
              </label>

              <div className="pt-2.5 mt-1 border-t border-slate-100">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11.5px] text-slate-700">Min. link amount</span>
                  <span className="text-[10.5px] font-mono text-slate-500">
                    ${Math.round(filters.minAmount).toLocaleString()}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.ceil(maxEdge)}
                  value={filters.minAmount}
                  onChange={(e) => setFilters((f) => ({ ...f, minAmount: Number(e.target.value) }))}
                  className="w-full accent-blue-600"
                />
              </div>

              <button
                onClick={() => setFilters({ kinds: ALL_KINDS, highRiskOnly: false, minAmount: 0 })}
                className="mt-3 text-[10.5px] text-slate-500 hover:text-slate-800"
              >
                Reset filters
              </button>
            </div>
          </>
        )}

        {/* info popover */}
        {infoOpen && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setInfoOpen(false)} />
            <div className="absolute left-0 top-[266px] z-40 w-[270px] bg-white border border-slate-200 rounded-xl shadow-xl p-4">
              <div className="flex items-center justify-between mb-2.5">
                <h3 className="text-[12px] font-semibold text-slate-900">OmniGuard AML</h3>
                <button onClick={() => setInfoOpen(false)} className="text-slate-400 hover:text-slate-700">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-500">
                Entity-genome explorer for the dual-pipeline financial-crime engine. Hexagons are entities,
                edge weight is exposure, and the inspector is the evidence pack.
              </p>
              <div className="mt-3 pt-3 border-t border-slate-100 space-y-1.5 text-[10.5px] text-slate-500">
                <div className="flex justify-between"><span>Graph</span><span className="text-slate-700">NetworkX neighbourhood</span></div>
                <div className="flex justify-between"><span>Citations</span><span className="text-slate-700">deterministic verifier</span></div>
                <div className="flex justify-between"><span>Human gate</span><span className="text-slate-700">always on</span></div>
              </div>
            </div>
          </>
        )}

        {/* alerts drawer */}
        {alertsOpen && (
          <>
            <div className="fixed inset-0 z-30 bg-slate-900/10" onClick={() => setAlertsOpen(false)} />
            <div className="absolute left-0 top-0 bottom-0 z-40 w-[320px] bg-white border-r border-slate-200 shadow-2xl flex flex-col">
              <div className="h-[62px] px-4 flex items-center justify-between border-b border-slate-100">
                <div className="flex items-center gap-2">
                  <Menu className="w-4 h-4 text-slate-500" />
                  <h3 className="text-[13px] font-semibold text-slate-900">Alerts</h3>
                </div>
                <button onClick={() => setAlertsOpen(false)} className="text-slate-400 hover:text-slate-700">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto py-1">
                {alerts.map((a) => (
                  <button
                    key={a.alert_id}
                    onClick={() => loadGraph(a.alert_id)}
                    className="w-full px-4 py-3 text-left hover:bg-slate-50 border-b border-slate-50"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[12px] font-medium text-slate-800 truncate">
                        {a.customer_name || a.account_id}
                      </span>
                      <span className="text-[9.5px] font-mono text-slate-400 shrink-0">{a.account_id}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2 mt-0.5">
                      <span className="text-[10.5px] text-slate-500 truncate">{a.trigger_reason || a.trigger}</span>
                      <span className="text-[9.5px] text-slate-400 shrink-0">{a.status || "PENDING"}</span>
                    </div>
                  </button>
                ))}
              </div>
              <div className="p-3 border-t border-slate-100">
                <button
                  onClick={() => { setAlertsOpen(false); setSearchOpen(true); }}
                  className="w-full h-8 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-[11.5px] font-medium"
                >
                  Search all alerts
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <SearchPalette
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        alerts={alerts}
        connected={connected}
        busy={loading}
        onLoad={loadGraph}
        onConnect={() => { setSearchOpen(false); setConnectOpen(true); }}
      />

      {connectOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/25 backdrop-blur-[2px] flex items-center justify-center px-4" onMouseDown={() => setConnectOpen(false)}>
          <div className="w-full max-w-[420px] bg-white rounded-xl shadow-2xl border border-slate-200 p-5" onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-1">
              <div>
                <h3 className="text-[14px] font-semibold text-slate-900">Connect compliance engine</h3>
                <p className="text-[11.5px] text-slate-500 mt-0.5">Paste the API key from your .env (API_KEY).</p>
              </div>
              <button onClick={() => setConnectOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-slate-300 px-3 h-10 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:border-blue-500">
              <Key className="w-4 h-4 text-slate-400" />
              <input
                type="password"
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && connect()}
                placeholder="X-API-Key"
                className="flex-1 text-[12.5px] font-mono text-slate-800 focus:outline-none"
              />
            </div>
            {connError && <p className="text-[11px] text-rose-600 mt-2">{connError}</p>}
            <button
              onClick={connect}
              disabled={connecting || !keyDraft.trim()}
              className="w-full h-9 mt-3 rounded-md bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-[12px] font-medium inline-flex items-center justify-center gap-2"
            >
              {connecting ? <Refresh className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {connecting ? "Connecting…" : "Connect & load latest alert"}
            </button>
            <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100">
              <span className="text-[10.5px] text-slate-400">Key is held in memory only — never persisted.</span>
              <button
                onClick={() => { setConnectOpen(false); setMode("genome"); setData(DEMO_GRAPH); setSelectedId("CC1"); }}
                className="text-[10.5px] text-slate-500 hover:text-slate-800"
              >
                Stay in demo
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[60]">
          <div
            className={`flex items-center gap-2 rounded-lg px-3.5 py-2.5 text-[12px] font-medium shadow-xl border ${
              toast.tone === "err"
                ? "bg-rose-600 border-rose-500 text-white"
                : toast.tone === "warn"
                  ? "bg-amber-500 border-amber-400 text-white"
                  : "bg-slate-900 border-slate-700 text-white"
            }`}
          >
            {toast.tone === "err" ? <Alert className="w-4 h-4" /> : <Check className="w-4 h-4" />}
            {toast.msg}
          </div>
        </div>
      )}
    </div>
  );
}
