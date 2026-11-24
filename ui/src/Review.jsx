import { useEffect, useState } from "react";
import { call, sleep } from "./api.js";
import { Check, Alert, Play, Refresh, Shield } from "./icons.jsx";

const J = (v) => {
  if (v == null) return null;
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
};

const dispStyle = (d = "") =>
  d.includes("ESCALATE")
    ? "bg-rose-50 text-rose-700 border-rose-200"
    : d.includes("CLOSE")
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : "bg-amber-50 text-amber-700 border-amber-200";

function Metric({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3.5 py-3">
      <div className="text-[10.5px] text-slate-500 mb-1">{label}</div>
      <div className={`text-[15px] font-semibold tabular-nums ${tone || "text-slate-900"}`}>{value ?? "—"}</div>
    </div>
  );
}

export default function Review({ apiKey, alertId, connected, demo, onToast }) {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [analyst, setAnalyst] = useState("analyst-1");
  const [decision, setDecision] = useState("ESCALATE");
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState(null);

  async function refresh() {
    if (!connected || !alertId) return;
    try {
      const st = await call(`/investigate/${alertId}/status`, apiKey);
      setState(st);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    setState(null); setSaved(null); setError(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, connected]);

  async function run() {
    setBusy(true); setError(null); setSaved(null);
    try {
      await call(`/investigate/${alertId}`, apiKey, { method: "POST" });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/investigate/${alertId}/status`, apiKey);
        if (st.disposition) break;
      }
      if (!st?.disposition) throw new Error("timed out waiting for disposition");
      setState(st);
      onToast?.("Investigation complete — awaiting human review", "ok");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    const pr = state?.partial_results || {};
    try {
      const r = await call(`/investigate/${alertId}/review`, apiKey, {
        method: "POST",
        body: JSON.stringify({ run_id: pr.run_id, analyst_id: analyst, decision, notes }),
      });
      setSaved(r);
      onToast?.(`Decision recorded: ${decision}`, "ok");
    } catch (e) {
      setError(String(e));
    }
  }

  const pr = state?.partial_results || {};
  const ml = J(pr.ml_scores) || {};
  const vr = J(pr.verifier_result) || {};
  const tc = J(pr.token_cost) || {};
  const hasRun = !!state?.disposition;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[880px] mx-auto px-10 pt-[68px] pb-9">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-[19px] font-semibold text-slate-900 tracking-tight">Investigation Review</h1>
              <span className="text-[10.5px] font-mono text-slate-600 bg-slate-100 border border-slate-200 rounded px-2 py-0.5">
                {alertId}
              </span>
            </div>
            <p className="text-[12.5px] text-slate-500 mt-1">
              Dual-chain reasoning, deterministic citation checks, and the mandatory human gate.
            </p>
          </div>
          <button
            onClick={run}
            disabled={busy || !connected}
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-[12px] font-medium px-3.5 py-2 rounded-md shadow-sm transition"
          >
            {busy ? <Refresh className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {busy ? "Investigating…" : hasRun ? "Re-run" : "Run investigation"}
          </button>
        </div>

        {!connected && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[12.5px] text-amber-800 mb-5 flex items-start gap-2">
            <Alert className="w-4 h-4 mt-0.5 shrink-0" />
            {demo
              ? "This is the demo alert. Load a live alert from the search palette to run or review investigations."
              : "Connect the compliance engine with an API key to run or review investigations. The graph and demo data remain available offline."}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[12.5px] text-rose-700 mb-5">
            {error}
          </div>
        )}

        {!hasRun ? (
          <div className="rounded-xl border border-slate-200 bg-white px-6 py-14 text-center">
            <div className="w-11 h-11 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto mb-3 text-slate-400">
              <Shield className="w-5 h-5" />
            </div>
            <h3 className="text-[13.5px] font-semibold text-slate-800">No run for this alert yet</h3>
            <p className="text-[12px] text-slate-500 mt-1 max-w-sm mx-auto leading-relaxed">
              Launch an investigation to reconstruct the graph, score the alert, retrieve policy, and
              produce a citation-verified recommendation.
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            <div className={`rounded-xl border px-5 py-4 flex items-center justify-between ${dispStyle(state.disposition)}`}>
              <div>
                <div className="text-[10.5px] uppercase tracking-wider font-semibold opacity-70">Disposition</div>
                <div className="text-[16px] font-bold mt-0.5">{state.disposition}</div>
              </div>
              <div className="text-right">
                <div className="text-[10.5px] uppercase tracking-wider font-semibold opacity-70">Run</div>
                <div className="text-[11.5px] font-mono mt-1">{pr.run_id}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Metric label="Composite risk" value={ml.composite} />
              <Metric label="Citations valid" value={String(vr.citations_valid ?? "—")}
                tone={String(vr.citations_valid) === "true" ? "text-emerald-600" : "text-amber-600"} />
              <Metric label="Total tokens" value={tc.total} />
              <Metric label="Fallback" value={String(tc.investigator?.fallback ?? false)}
                tone={tc.investigator?.fallback ? "text-amber-600" : "text-slate-900"} />
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[12.5px] font-semibold text-slate-900">Verifier &amp; models</h3>
                <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full border ${
                  String(vr.citations_valid) === "true"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-amber-50 text-amber-700 border-amber-200"
                }`}>
                  {String(vr.citations_valid) === "true" ? "citations verified" : "human triage required"}
                </span>
              </div>
              <div className="grid md:grid-cols-2 gap-x-8 gap-y-2 text-[12px]">
                <div className="flex justify-between gap-4 py-1 border-b border-slate-100">
                  <span className="text-slate-500">Investigator</span>
                  <span className="font-medium text-slate-800 text-right">{tc.investigator?.model_id || "—"}</span>
                </div>
                <div className="flex justify-between gap-4 py-1 border-b border-slate-100">
                  <span className="text-slate-500">Challenger</span>
                  <span className="font-medium text-slate-800 text-right">{tc.challenger?.model_id || "—"}</span>
                </div>
                <div className="flex justify-between gap-4 py-1 border-b border-slate-100">
                  <span className="text-slate-500">Verifier notes</span>
                  <span className="font-medium text-slate-800 text-right">{vr.reason || vr.notes || "—"}</span>
                </div>
                <div className="flex justify-between gap-4 py-1 border-b border-slate-100">
                  <span className="text-slate-500">Injection quarantine</span>
                  <span className="font-medium text-slate-800 text-right">
                    {String(J(pr.injection_scan)?.quarantined ?? "—")}
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-[12.5px] font-semibold text-slate-900 mb-3">Analyst decision</h3>
              {saved ? (
                <div className="flex items-center gap-2 text-[12.5px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2.5">
                  <Check className="w-4 h-4" /> Decision recorded — {saved.status || decision}
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2.5">
                    <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} placeholder="analyst id"
                      className="h-9 px-3 rounded-md border border-slate-300 text-[12.5px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 w-[150px]" />
                    <select value={decision} onChange={(e) => setDecision(e.target.value)}
                      className="h-9 px-2.5 rounded-md border border-slate-300 text-[12.5px] text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500">
                      <option>ESCALATE</option>
                      <option>CLOSE</option>
                      <option>REQUEST_RERUN</option>
                      <option>RETURN_FOR_RERUN</option>
                    </select>
                    <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="rationale / notes"
                      className="h-9 px-3 rounded-md border border-slate-300 text-[12.5px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 flex-1 min-w-[200px]" />
                    <button onClick={submit}
                      className="h-9 px-4 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-medium transition">
                      Submit
                    </button>
                  </div>
                  <p className="text-[10.5px] text-slate-400 mt-2.5">
                    Fraud alerts can never be auto-closed. The human gate always fires.
                  </p>
                </>
              )}
            </div>

            <details className="rounded-xl border border-slate-200 bg-white px-5 py-3.5">
              <summary className="cursor-pointer text-[12px] font-medium text-slate-600">Raw evidence pack</summary>
              <pre className="mt-3 text-[10.5px] font-mono whitespace-pre-wrap text-slate-600 max-h-72 overflow-auto">
                {JSON.stringify(state, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
