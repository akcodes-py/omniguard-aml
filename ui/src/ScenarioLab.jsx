import { useState } from "react";
import { call, sleep } from "./api.js";
import { Flask, Play, Check, Alert } from "./icons.jsx";

const J = (v) => {
  if (v == null) return null;
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
};

const verdictTone = (v) =>
  v === "MATCH" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : v === "MISS" ? "bg-rose-50 text-rose-700 border-rose-200"
      : "bg-amber-50 text-amber-700 border-amber-200";

export default function ScenarioLab({ apiKey, connected, onToast }) {
  const [concern, setConcern] = useState("smurfing via micro-deposits under reporting threshold");
  const [by, setBy] = useState("risk-owner-1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState(null);

  async function run() {
    setError(null); setBusy(true);
    try {
      const { concern_id } = await call("/scenario/", apiKey, {
        method: "POST",
        body: JSON.stringify({ concern_text: concern, submitted_by: by }),
      });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/scenario/${concern_id}/status`, apiKey);
        if (st.scenarios_generated) break;
      }
      if (!st?.set_id) throw new Error("timed out waiting for scenarios");
      const row = { concern, set: st.set_id, state: st.state, findings: J(st.challenger_findings) || [], exec: null };
      setRows((r) => [row, ...r]);
      setSel(row.set);
      onToast?.("Scenario set drafted and sealed", "ok");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function approve(row) {
    setError(null);
    try {
      const exec = await call(`/scenario/${row.set}/approve`, apiKey, { method: "POST", body: "{}" });
      setRows((rs) => rs.map((x) => (x.set === row.set ? { ...x, exec } : x)));
      onToast?.("Control executed — coverage report ready", "ok");
    } catch (e) {
      setError(String(e));
    }
  }

  const cur = rows.find((x) => x.set === sel) || rows[0];
  const results = cur?.exec?.results || {};
  const gaps = J(cur?.exec?.coverage_gaps) || [];
  const fRaw = J(cur?.findings);
  const findings = Array.isArray(fRaw) ? fRaw : Array.isArray(fRaw?.findings) ? fRaw.findings : fRaw ? [fRaw] : [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[980px] mx-auto px-10 pt-[68px] pb-9">
        <div className="mb-6">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[19px] font-semibold text-slate-900 tracking-tight">Scenario Lab</h1>
            <span className="text-[10.5px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
              Simulation
            </span>
          </div>
          <p className="text-[12.5px] text-slate-500 mt-1">
            Turn a compliance concern into synthetic transactions, seal expected outcomes with SHA-256, then
            execute the control.
          </p>
        </div>

        {!connected && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-[12.5px] text-amber-800 mb-5 flex items-start gap-2">
            <Alert className="w-4 h-4 mt-0.5 shrink-0" /> Connect the engine to generate and execute scenarios.
          </div>
        )}

        <div className="rounded-xl border border-slate-200 bg-white p-5 mb-5">
          <label className="block text-[11.5px] font-medium text-slate-600 mb-1.5">Scenario description / typology</label>
          <textarea
            rows={2}
            value={concern}
            onChange={(e) => setConcern(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-[12.5px] text-slate-800 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
          />
          <div className="flex items-end gap-3 mt-3">
            <div className="flex-1 max-w-[260px]">
              <label className="block text-[11.5px] font-medium text-slate-600 mb-1.5">Risk owner / jurisdiction</label>
              <input
                value={by}
                onChange={(e) => setBy(e.target.value)}
                className="w-full h-9 rounded-lg border border-slate-300 px-3 text-[12.5px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
            </div>
            <button
              onClick={run}
              disabled={busy || !connected}
              className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-[12px] font-medium px-4 h-9 rounded-md shadow-sm transition"
            >
              {busy ? <Flask className="w-3.5 h-3.5 animate-pulse" /> : <Play className="w-3.5 h-3.5" />}
              {busy ? "Generating…" : "Generate scenarios"}
            </button>
          </div>
          <p className="text-[10.5px] text-slate-400 mt-2.5">
            Generation locks expectations; execution only runs after you approve the set below.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[12.5px] text-rose-700 mb-5">{error}</div>
        )}

        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-[12.5px] font-semibold text-slate-900">Scenario sets</h3>
            <span className="text-[10.5px] text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">{rows.length}</span>
          </div>
          {rows.length === 0 ? (
            <div className="px-5 py-12 text-center text-[12px] text-slate-400">
              No scenario runs yet. Describe a typology above to draft a sealed test set.
            </div>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-[10.5px] text-slate-500 bg-slate-50/70">
                  <th className="text-left font-medium px-5 py-2">Concern</th>
                  <th className="text-left font-medium px-3 py-2">State</th>
                  <th className="text-right font-medium px-3 py-2">Match</th>
                  <th className="text-right font-medium px-3 py-2">Miss</th>
                  <th className="text-right font-medium px-3 py-2">Over-alert</th>
                  <th className="px-5 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.set}
                    onClick={() => setSel(r.set)}
                    className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${r.set === sel ? "bg-slate-50" : ""}`}
                  >
                    <td className="px-5 py-2.5 text-[12px] text-slate-700 max-w-[320px]">{r.concern}</td>
                    <td className="px-3 py-2.5 text-[11.5px] text-slate-500">{r.exec ? "EXECUTED" : r.state}</td>
                    <td className="px-3 py-2.5 text-right text-[11.5px] tabular-nums text-slate-700">{r.exec?.summary?.matches ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right text-[11.5px] tabular-nums text-slate-700">{r.exec?.summary?.misses ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right text-[11.5px] tabular-nums text-slate-700">{r.exec?.summary?.over_alerts ?? "—"}</td>
                    <td className="px-5 py-2.5 text-right">
                      {!r.exec && (
                        <button
                          onClick={(ev) => { ev.stopPropagation(); approve(r); }}
                          className="inline-flex items-center gap-1.5 text-[11px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded px-2 py-1 transition"
                        >
                          <Check className="w-3 h-3" /> Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {cur && (findings.length > 0 || cur.exec) && (
          <div className="grid md:grid-cols-2 gap-4 mt-5">
            {findings.length > 0 && (
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <h3 className="text-[12.5px] font-semibold text-slate-900 mb-2">Challenger findings</h3>
                <ul className="space-y-1.5 text-[11.5px] text-slate-600 list-disc pl-4">
                  {findings.map((f, i) => (
                    <li key={i}>
                      {typeof f === "string" ? f : (
                        <>
                          <span className="font-mono text-slate-500">#{f.scenario_idx ?? i}</span>{" "}
                          <span className="font-mono text-[10px] text-slate-400">[{f.verdict || "?"}]</span>{" "}
                          {f.label_flip_arg || ""}
                          {f.leakage ? ` · leakage: ${f.leakage}` : ""}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {cur.exec && (
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <h3 className="text-[12.5px] font-semibold text-slate-900 mb-2">Control results</h3>
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="text-[10.5px] text-slate-500">
                      <th className="text-left font-medium pb-1.5">Scenario</th>
                      <th className="text-left font-medium pb-1.5">Expected</th>
                      <th className="text-left font-medium pb-1.5">Actual</th>
                      <th className="text-left font-medium pb-1.5">Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results).map(([idx, r]) => (
                      <tr key={idx} className="border-t border-slate-100 text-[11.5px]">
                        <td className="py-1.5 text-slate-500">#{idx}</td>
                        <td className="py-1.5 text-slate-700">{r.expected}</td>
                        <td className="py-1.5 text-slate-700">{r.actual}</td>
                        <td className="py-1.5">
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${verdictTone(r.verdict)}`}>
                            {r.verdict}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[10.5px] text-slate-400 mt-3 font-mono truncate">
                  evidence {String(cur.exec.evidence_pack_hash).slice(0, 24)}…
                </p>
              </div>
            )}
          </div>
        )}

        {cur?.exec && gaps.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-5 mt-4">
            <h3 className="text-[12.5px] font-semibold text-slate-900 mb-2">What was not tested</h3>
            <ul className="space-y-1 text-[11.5px] text-slate-600 list-disc pl-4">
              {gaps.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
