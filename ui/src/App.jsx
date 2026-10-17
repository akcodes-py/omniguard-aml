import { useState } from "react";
import { call, sleep, getLastCallMs } from "./api.js";

// --- tokens & tiny UI helpers -------------------------------------------
const card = "bg-[#111827] border border-slate-800 rounded-xl p-6 shadow-xl";
const inputCls =
  "w-full bg-[#0B0F17] border border-slate-700/80 rounded-lg px-3.5 py-2.5 text-sm font-mono text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition";
const inputSans =
  "w-full bg-[#0B0F17] border border-slate-700/80 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition";
const inputSmall =
  "bg-[#0B0F17] border border-slate-700/80 rounded-lg px-3 py-1.5 text-xs font-mono text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 transition";
const btnPrimary =
  "w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs py-2.5 px-4 rounded-lg shadow-sm transition flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed";
const btnGhostSm =
  "bg-slate-800 hover:bg-slate-700 text-white text-[11px] font-medium px-2.5 py-1 rounded-md border border-slate-700 transition disabled:opacity-40 disabled:cursor-not-allowed";
const thCls = "text-left text-[11px] text-slate-400 font-semibold px-2 py-1.5 border-b border-slate-800";
const tdCls = "text-[13px] px-2 py-2 border-b border-slate-800/60 align-top";
const mono = "font-mono text-[11px]";

// Real alert IDs from core.alerts (eval3 set + demo seeds) — no invented chips.
const PRESETS = ["eval3-tp-00", "eval3-inj-00", "eval3-lik-00", "alert-demo-rapid"];

// Audit fields arrive parsed (Postgres jsonb) or stringified (SQLite) — accept both.
const J = (v) => {
  if (v == null) return null;
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
};

function Chip({ className, children }) {
  return <span className={`text-[11px] font-mono px-2 py-0.5 rounded border ${className}`}>{children}</span>;
}

function Pill({ tone, children }) {
  const bg = tone === "crimson" ? "bg-red-400" : tone === "emerald" ? "bg-emerald-400" : "bg-amber-400";
  return <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-bold text-black ${bg}`}>{children}</span>;
}

const dispTone = (d) => {
  d = String(d ?? "—");
  return d.includes("ESCALATE") ? "crimson" : d.includes("CLOSE") ? "emerald" : "amber";
};
const verTone = (v) => {
  v = String(v ?? "—");
  return v === "MATCH" ? "emerald" : v === "MISS" ? "crimson" : "amber";
};

function RecordBadge({ n }) {
  return (
    <span className="text-xs font-mono text-slate-400 bg-[#0B0F17] px-2.5 py-1 rounded border border-slate-800">
      {n} record{n === 1 ? "" : "s"}
    </span>
  );
}

function EmptyState({ title, children }) {
  return (
    <div className="my-auto py-12 text-center max-w-sm mx-auto">
      <div className="w-12 h-12 rounded-full bg-slate-800/50 border border-slate-700/50 flex items-center justify-center mx-auto mb-3 text-slate-400">
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <h3 className="text-sm font-medium text-slate-200 mb-1">{title}</h3>
      <p className="text-xs text-slate-400 leading-relaxed">{children}</p>
    </div>
  );
}

function Canvas({ title, sub, n, children }) {
  const ms = getLastCallMs();
  return (
    <section className="lg:col-span-7">
      <div className="bg-[#111827] border border-slate-800 rounded-xl min-h-[420px] flex flex-col p-6">
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
          <div>
            <h2 className="text-sm font-semibold text-white">{title}</h2>
            <p className="text-xs text-slate-400">{sub}</p>
          </div>
          <RecordBadge n={n} />
        </div>
        <div className="flex-1 flex flex-col">{children}</div>
        <div className="mt-6 border-t border-slate-800/80 pt-3 flex items-center justify-between text-[11px] text-slate-500 font-mono">
          <span>APPEND-ONLY AUDIT TRAIL: ENABLED</span>
          <span>LAST API CALL: {ms ? `${ms} ms` : "—"}</span>
        </div>
      </div>
    </section>
  );
}

function TabBtn({ active, onClick, label, n }) {
  return (
    <button onClick={onClick}
      className={`px-3.5 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
        active ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-slate-200"}`}>
      {label}
      <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${active ? "bg-indigo-700 text-indigo-100" : "bg-slate-800 text-slate-400"}`}>
        {n}
      </span>
    </button>
  );
}

const ArrowIcon = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
  </svg>
);
const BoltIcon = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
  </svg>
);

// --- Investigations ------------------------------------------------------
function Investigate({ k, rows, setRows }) {
  const [alertId, setAlertId] = useState("eval3-tp-00");
  const [busy, setBusy] = useState(false);
  const [e, setE] = useState(null);
  const [sel, setSel] = useState(null);
  const [analyst, setAnalyst] = useState("analyst-1");
  const [decision, setDecision] = useState("ESCALATE");
  const [notes, setNotes] = useState("");

  async function run() {
    setE(null); setBusy(true);
    try {
      await call(`/investigate/${alertId}`, k, { method: "POST" });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/investigate/${alertId}/status`, k);
        if (st.disposition) break;
      }
      if (!st?.disposition) throw new Error("timed out waiting for disposition (is the API + DB up?)");
      const pr = st.partial_results || {};
      const row = { alert: alertId, run: pr.run_id, disp: st.disposition,
        ml: J(pr.ml_scores) || {}, vr: J(pr.verifier_result) || {},
        tc: J(pr.token_cost) || {}, review: null };
      setRows((r) => [row, ...r.filter((x) => x.alert !== alertId)]);
      setSel(row.run || alertId);
    } catch (ex) { setE(String(ex)); } finally { setBusy(false); }
  }

  async function review(row) {
    setE(null);
    try {
      const r = await call(`/investigate/${row.alert}/review`, k,
        { method: "POST", body: JSON.stringify({ run_id: row.run, analyst_id: analyst, decision, notes }) });
      setRows((rs) => rs.map((x) => x.run === row.run ? { ...x, review: r } : x));
    } catch (ex) { setE(String(ex)); }
  }

  const cur = rows.find((x) => (x.run || x.alert) === sel) || rows[0];

  return (
    <>
      <section className="lg:col-span-5 space-y-6">
        <div className={card}>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-base font-semibold text-white">Investigate Alert</h2>
            <Chip className="text-indigo-400 bg-indigo-950/60 border-indigo-800/50">Alert Triage</Chip>
          </div>
          <p className="text-xs text-slate-400 mb-5">
            Ingest an alert ID to reconstruct transaction graphs and evaluate AML typology alignment.
          </p>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">Alert Identifier</label>
          <input value={alertId} onChange={(e) => setAlertId(e.target.value)} className={inputCls} placeholder="e.g. eval3-tp-00" />
          <button className={`${btnPrimary} mt-4`} disabled={busy || !k} onClick={run}>
            {busy ? "Running…" : "Launch Investigation"} <ArrowIcon />
          </button>
        </div>
        <div className="bg-[#111827]/60 border border-slate-800/70 rounded-xl p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">Investigation presets</h3>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button key={p} onClick={() => setAlertId(p)}
                className="text-xs font-mono px-2.5 py-1 rounded bg-[#0B0F17] hover:bg-slate-800 text-slate-300 border border-slate-800 transition">
                {p}
              </button>
            ))}
          </div>
        </div>
      </section>

      <Canvas title="Active Investigation Ledger" sub="Typology scoring, citations, and the human-review gate" n={rows.length}>
        {rows.length === 0 ? (
          <EmptyState title="Ready for telemetry">
            Submit an alert ID like <code className="text-indigo-400 font-mono">eval3-tp-00</code> on the
            left to populate the ledger — scored, investigated, and citation-verified.
          </EmptyState>
        ) : (
          <table className="w-full border-collapse mt-2">
            <thead><tr>
              <th className={thCls}>Alert</th><th className={thCls}>Composite</th><th className={thCls}>Disposition</th>
              <th className={thCls}>Citations</th><th className={thCls}>Tokens</th><th className={thCls}>Review</th>
            </tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.run || r.alert} onClick={() => setSel(r.run || r.alert)}
                className={`cursor-pointer hover:bg-slate-800/30 ${(r.run || r.alert) === sel ? "bg-slate-800/40" : ""}`}>
                <td className={`${tdCls} ${mono}`}>{r.alert}</td>
                <td className={tdCls}>{r.ml.composite ?? "—"}</td>
                <td className={tdCls}><Pill tone={dispTone(r.disp)}>{r.disp.replace("RECOMMEND_", "")}</Pill></td>
                <td className={tdCls}>{String(r.vr.citations_valid ?? "—")}</td>
                <td className={tdCls}>{r.tc.total ?? "—"}</td>
                <td className={tdCls}>{r.review ? r.review.status : <span className="text-slate-500">pending</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {cur && (
          <div className="border border-slate-800/80 rounded-lg p-4 mt-4">
            <p className="text-xs font-semibold text-slate-200 mb-3">
              Analyst review — <span className="font-mono text-indigo-300">{cur.alert}</span>
            </p>
            <div className="flex gap-2 flex-wrap">
              <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} className={`${inputSmall} max-w-[150px]`} />
              <select value={decision} onChange={(e) => setDecision(e.target.value)} className={`${inputSmall} max-w-[180px]`}>
                <option>ESCALATE</option><option>CLOSE</option>
                <option>REQUEST_RERUN</option><option>RETURN_FOR_RERUN</option>
              </select>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="notes" className={`${inputSmall} flex-1 min-w-[160px]`} />
              <button className={btnGhostSm} onClick={() => review(cur)}>Submit</button>
            </div>
            <div className="flex gap-6 mt-3 text-[12px] text-slate-400 flex-wrap">
              <span>investigator <b className="text-slate-200">{cur.tc.investigator?.model_id || "—"}</b></span>
              <span>challenger <b className="text-slate-200">{cur.tc.challenger?.model_id || "—"}</b></span>
              <span>fallback <b className="text-slate-200">{String(cur.tc.investigator?.fallback || cur.tc.challenger?.fallback || false)}</b></span>
              {cur.tc.investigator?.attempts ? <span>attempts <b className="text-slate-200">{cur.tc.investigator.attempts}</b></span> : null}
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-[12px] text-slate-400">raw evidence</summary>
              <pre className="font-mono text-[11px] whitespace-pre-wrap text-slate-300 mt-2">{JSON.stringify(cur, null, 2)}</pre>
            </details>
          </div>
        )}
        {e && <p className="text-red-400 text-[13px] mt-3">{e}</p>}
      </Canvas>
    </>
  );
}

// --- ScenarioLab ----------------------------------------------------------
function Scenario({ k, rows, setRows }) {
  const [concern, setConcern] = useState("smurfing via micro-deposits under reporting threshold");
  const [by, setBy] = useState("risk-owner-1");
  const [busy, setBusy] = useState(false);
  const [e, setE] = useState(null);
  const [sel, setSel] = useState(null);

  async function run() {
    setE(null); setBusy(true);
    try {
      const { concern_id } = await call("/scenario/", k,
        { method: "POST", body: JSON.stringify({ concern_text: concern, submitted_by: by }) });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/scenario/${concern_id}/status`, k);
        if (st.scenarios_generated) break;
      }
      if (!st?.set_id) throw new Error("timed out waiting for scenarios (is the API + DB up?)");
      const row = { concern, set: st.set_id, state: st.state, findings: J(st.challenger_findings) || [], exec: null };
      setRows((r) => [row, ...r]);
      setSel(row.set);
    } catch (ex) { setE(String(ex)); } finally { setBusy(false); }
  }

  async function approve(row) {
    setE(null);
    try {
      const exec = await call(`/scenario/${row.set}/approve`, k, { method: "POST", body: "{}" });
      setRows((rs) => rs.map((x) => x.set === row.set ? { ...x, exec } : x));
    } catch (ex) { setE(String(ex)); }
  }

  const cur = rows.find((x) => x.set === sel) || rows[0];
  const results = cur?.exec?.results || {};
  const gaps = J(cur?.exec?.coverage_gaps) || [];
  const fRaw = J(cur?.findings);
  const fl = Array.isArray(fRaw) ? fRaw : Array.isArray(fRaw?.findings) ? fRaw.findings : fRaw ? [fRaw] : [];

  return (
    <>
      <section className="lg:col-span-5 space-y-6">
        <div className={card}>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-base font-semibold text-white">Run a New Scenario</h2>
            <Chip className="text-amber-400 bg-amber-950/60 border-amber-800/50">Simulation</Chip>
          </div>
          <p className="text-xs text-slate-400 mb-5">
            LLM-drafted suspicious scenarios + benign lookalikes; expected outcomes are
            SHA-256-locked before the control runs.
          </p>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">Scenario Description / Typology</label>
          <textarea rows={3} value={concern} onChange={(e) => setConcern(e.target.value)} className={`${inputSans} resize-none`} />
          <label className="block text-xs font-medium text-slate-300 mb-1.5 mt-4">Risk Owner / Jurisdiction</label>
          <input value={by} onChange={(e) => setBy(e.target.value)} className={inputCls} />
          <button className={`${btnPrimary} mt-4`} disabled={busy || !k} onClick={run}>
            {busy ? "Running…" : "Generate Scenarios"} <BoltIcon />
          </button>
          <p className="text-[11px] text-slate-500 mt-2">
            Generation drafts and locks the scenario set; execution runs only after you approve it in the ledger.
          </p>
        </div>
      </section>

      <Canvas title="Scenario Execution Output" sub="Control results, coverage gaps, and the approval gate" n={rows.length}>
        {rows.length === 0 ? (
          <EmptyState title="No scenario runs yet">
            Describe a typology on the left and generate a scenario set — execution runs only
            after you approve the locked expectations.
          </EmptyState>
        ) : (
          <table className="w-full border-collapse mt-2">
            <thead><tr>
              <th className={thCls}>Concern</th><th className={thCls}>State</th><th className={thCls}>Match</th>
              <th className={thCls}>Miss</th><th className={thCls}>Over-alert</th><th className={thCls}></th>
            </tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.set} onClick={() => setSel(r.set)}
                className={`cursor-pointer hover:bg-slate-800/30 ${r.set === sel ? "bg-slate-800/40" : ""}`}>
                <td className={`${tdCls} max-w-[320px]`}>{r.concern}</td>
                <td className={tdCls}>{r.exec ? "EXECUTED" : r.state}</td>
                <td className={tdCls}>{r.exec?.summary.matches ?? "—"}</td>
                <td className={tdCls}>{r.exec?.summary.misses ?? "—"}</td>
                <td className={tdCls}>{r.exec?.summary.over_alerts ?? "—"}</td>
                <td className={tdCls}>{!r.exec && (
                  <button className={btnGhostSm} onClick={(ev) => { ev.stopPropagation(); approve(r); }}>Approve</button>
                )}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {cur && fl.length > 0 && (
          <div className="border border-slate-800/80 rounded-lg p-4 mt-4">
            <p className="text-xs font-semibold text-slate-200 mb-2">
              Challenger findings <span className="font-normal text-slate-500">— adversarial review of the sealed set</span>
            </p>
            <ul className="text-[13px] text-slate-400 list-disc pl-5 space-y-1">
              {fl.map((f, i) => (
                <li key={i}>
                  {typeof f === "string" ? f : f?.label_flip_arg != null || f?.leakage != null ? (
                    <>
                      <span className="font-mono text-slate-300">#{f.scenario_idx ?? i}</span>{" "}
                      <span className="font-mono text-[11px] text-slate-400">[{f.verdict || "?"}]</span>{" "}
                      {f.label_flip_arg || ""}
                      {f.leakage ? ` · leakage: ${f.leakage}` : ""}
                      {f.consistency ? ` · ${f.consistency}` : ""}
                    </>
                  ) : (
                    JSON.stringify(f)
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {cur?.exec && (
          <div className="border border-slate-800/80 rounded-lg p-4 mt-4">
            <p className="text-xs font-semibold text-slate-200 mb-3">Control results</p>
            <table className="w-full border-collapse">
              <thead><tr>
                <th className={thCls}>Scenario</th><th className={thCls}>Expected</th><th className={thCls}>Actual</th><th className={thCls}>Verdict</th>
              </tr></thead>
              <tbody>{Object.entries(results).map(([idx, r]) => (
                <tr key={idx}>
                  <td className={tdCls}>#{idx}</td><td className={tdCls}>{r.expected}</td><td className={tdCls}>{r.actual}</td>
                  <td className={tdCls}><Pill tone={verTone(r.verdict)}>{r.verdict}</Pill></td>
                </tr>
              ))}</tbody>
            </table>
            <p className="text-xs font-semibold text-slate-200 mt-4 mb-2">What was NOT tested</p>
            <ul className="text-[13px] text-slate-400 list-disc pl-5 space-y-1">
              {gaps.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
            <div className="text-[12px] text-slate-400 mt-3">
              evidence pack <span className={`${mono} text-slate-300`}>{String(cur.exec.evidence_pack_hash).slice(0, 20)}…</span>
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-[12px] text-slate-400">raw evidence</summary>
              <pre className="font-mono text-[11px] whitespace-pre-wrap text-slate-300 mt-2">{JSON.stringify(cur, null, 2)}</pre>
            </details>
          </div>
        )}
        {e && <p className="text-red-400 text-[13px] mt-3">{e}</p>}
      </Canvas>
    </>
  );
}

// --- Shell ----------------------------------------------------------------
export default function App() {
  const [key, setKey] = useState("");
  const [tab, setTab] = useState("inv");
  const [auth, setAuth] = useState(null); // null | {ok:true} | {ok:false, msg}
  const [health, setHealth] = useState(null);
  const [showKey, setShowKey] = useState(false);
  const [invRows, setInvRows] = useState([]);
  const [scnRows, setScnRows] = useState([]);

  async function verifyKey() {
    setHealth(null);
    try {
      await call("/auth/check", key);
    } catch (ex) {
      setAuth({ ok: false, msg: String(ex) });
      return;
    }
    setAuth({ ok: true });
    try { setHealth(await call("/health", key)); } catch (ex) { setHealth({ error: String(ex) }); }
    setShowKey(false);
  }

  const badge = auth?.ok
    ? { cls: "bg-emerald-950/40 border-emerald-800/60 text-emerald-300 hover:bg-emerald-950/60", dot: "bg-emerald-400", label: "Engine Connected" }
    : auth && !auth.ok
      ? { cls: "bg-red-950/40 border-red-800/60 text-red-300 hover:bg-red-950/60", dot: "bg-red-400", label: "Key Not Verified" }
      : { cls: "bg-amber-950/40 border-amber-800/60 text-amber-300 hover:bg-amber-950/60", dot: "bg-amber-400 animate-pulse", label: "API Key Required" };

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-200 font-sans antialiased selection:bg-indigo-500/30">
      <header className="border-b border-slate-800/80 bg-[#0F1623]/90 backdrop-blur-md sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-9 h-9 rounded-lg bg-indigo-600/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-inner">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-semibold tracking-tight text-white">OmniGuard AML</h1>
                <Chip className="text-slate-400 bg-slate-800 border-slate-700">V1</Chip>
              </div>
              <p className="text-xs text-slate-400">Financial Crime &amp; Compliance Intelligence</p>
            </div>
          </div>

          <nav className="flex items-center gap-1 bg-[#0B0F17] p-1 rounded-lg border border-slate-800">
            <TabBtn active={tab === "inv"} onClick={() => setTab("inv")} label="Investigations" n={invRows.length} />
            <TabBtn active={tab === "scn"} onClick={() => setTab("scn")} label="Scenario Runs" n={scnRows.length} />
          </nav>

          <button onClick={() => setShowKey(!showKey)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${badge.cls}`}>
            <span className={`w-2 h-2 rounded-full ${badge.dot}`} />
            {badge.label}
          </button>
        </div>

        {showKey && (
          <div className="bg-[#0B0F17] border-t border-slate-800/80 px-6 py-3">
            <div className="max-w-7xl mx-auto flex items-center justify-end gap-3 flex-wrap">
              <label className="text-xs text-slate-400 font-medium">Compliance Engine API Key:</label>
              <input type="password" value={key}
                onChange={(e) => { setKey(e.target.value); setAuth(null); }}
                placeholder="paste from .env (API_KEY)"
                className="bg-[#111827] border border-slate-700 rounded-md px-3 py-1 text-xs font-mono text-white focus:outline-none focus:border-indigo-500 w-64" />
              <button onClick={verifyKey} disabled={!key} className={btnGhostSm}>Verify</button>
              {auth && !auth.ok && <span className="text-[11px] text-red-400">{auth.msg}</span>}
              {auth?.ok && health && !health.error && (
                <span className="text-[11px] text-slate-400 font-mono">
                  api {health.status} · queue {health.services?.queue || "?"} · llm {health.services?.llm || "?"}
                </span>
              )}
              {health?.error && <span className="text-[11px] text-red-400">{health.error}</span>}
            </div>
            <div className="max-w-7xl mx-auto text-right mt-1">
              <span className="text-[10px] text-slate-500">key held in memory only — never persisted or logged</span>
            </div>
          </div>
        )}
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {tab === "inv"
          ? <Investigate k={key} rows={invRows} setRows={setInvRows} />
          : <Scenario k={key} rows={scnRows} setRows={setScnRows} />}
      </main>
    </div>
  );
}
