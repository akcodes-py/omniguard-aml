import { useState } from "react";
import { call, sleep } from "./api.js";

// AlphaCapMatch layout, black theme.
const BG = "#000", PANEL = "#111214", LINE = "#26282d", TXT = "#f5f5f5", MUT = "#a1a1a1";
const page = { background: BG, color: TXT, minHeight: "100vh" };
const wrap = { maxWidth: 980, margin: "0 auto", padding: "20px 16px 60px" };
const header = { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 };
const tabs = { display: "flex", gap: 24, borderBottom: `1px solid ${LINE}`, margin: "12px 0 16px" };
const tab = (on) => ({ padding: "8px 2px", cursor: "pointer", fontSize: 14,
  color: on ? TXT : MUT, borderBottom: on ? `2px solid ${TXT}` : "2px solid transparent", marginBottom: -1 });
const panel = { background: PANEL, border: `1px solid ${LINE}`, borderRadius: 8, padding: 16, marginBottom: 16 };
const title = { fontSize: 13, fontWeight: 700, margin: "0 0 12px" };
const input = { background: "#000", border: `1px solid ${LINE}`, color: TXT, padding: "7px 10px", borderRadius: 6, fontSize: 13 };
const btn = { background: "#f5f5f5", border: 0, color: "#000", padding: "7px 16px", borderRadius: 6, cursor: "pointer", fontSize: 13, fontWeight: 600 };
const btnS = { ...btn, padding: "4px 10px", fontSize: 12 };
const ghost = { ...btn, background: "transparent", color: TXT, border: `1px solid ${LINE}` };
const th = { textAlign: "left", fontSize: 11, color: MUT, fontWeight: 600, padding: "6px 8px", borderBottom: `1px solid ${LINE}` };
const td = { fontSize: 13, padding: "7px 8px", borderBottom: `1px solid #1b1d21` };
const pill = (bg) => ({ display: "inline-block", padding: "1px 8px", borderRadius: 10, background: bg, color: "#000", fontSize: 11, fontWeight: 700 });
const dispPill = (d) => { d = String(d ?? "—"); return d.includes("ESCALATE") ? pill("#f87171") : d.includes("CLOSE") ? pill("#4ade80") : pill("#fbbf24"); };
const verPill = (v) => { v = String(v ?? "—"); return v === "MATCH" ? pill("#4ade80") : v === "MISS" ? pill("#f87171") : pill("#fbbf24"); };
const mono = { fontFamily: "ui-monospace, monospace", fontSize: 11 };
const err = { color: "#f87171", fontSize: 13 };

// Audit fields arrive parsed (Postgres jsonb) or stringified (SQLite) — accept both.
const J = (v) => {
  if (v == null) return null;
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
};

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
    <div>
      <div style={panel}>
        <p style={title}>Investigate alert</p>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={alertId} onChange={(e) => setAlertId(e.target.value)} style={{ ...input, flex: 1 }} />
          <button style={btn} disabled={busy || !k} onClick={run}>{busy ? "Running…" : "Investigate"}</button>
        </div>
      </div>
      <div style={panel}>
        <p style={title}>Investigations ({rows.length})</p>
        {rows.length === 0 && <p style={{ color: MUT, fontSize: 13 }}>No investigations yet. Run one above.</p>}
        {rows.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Alert</th><th style={th}>Composite</th><th style={th}>Disposition</th>
              <th style={th}>Citations</th><th style={th}>Tokens</th><th style={th}>Review</th>
            </tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.run || r.alert} onClick={() => setSel(r.run || r.alert)}
                  style={{ cursor: "pointer", background: (r.run || r.alert) === sel ? "#1a1d22" : "transparent" }}>
                <td style={{ ...td, ...mono }}>{r.alert}</td>
                <td style={td}>{r.ml.composite ?? "—"}</td>
                <td style={td}><span style={dispPill(r.disp)}>{r.disp.replace("RECOMMEND_", "")}</span></td>
                <td style={td}>{String(r.vr.citations_valid ?? "—")}</td>
                <td style={td}>{r.tc.total ?? "—"}</td>
                <td style={td}>{r.review ? r.review.status : <span style={{ color: MUT }}>pending</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {cur && (
        <div style={panel}>
          <p style={title}>Analyst review — <span style={mono}>{cur.alert}</span></p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} style={{ ...input, maxWidth: 150 }} />
            <select value={decision} onChange={(e) => setDecision(e.target.value)} style={{ ...input, maxWidth: 180 }}>
              <option>ESCALATE</option><option>CLOSE</option>
              <option>REQUEST_RERUN</option><option>RETURN_FOR_RERUN</option>
            </select>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="notes" style={{ ...input, flex: 1, minWidth: 160 }} />
            <button style={ghost} onClick={() => review(cur)}>Submit</button>
          </div>
          <div style={{ display: "flex", gap: 24, marginTop: 10, fontSize: 12, color: MUT }}>
            <span>investigator <b style={{ color: TXT }}>{cur.tc.investigator?.model_id || "—"}</b></span>
            <span>challenger <b style={{ color: TXT }}>{cur.tc.challenger?.model_id || "—"}</b></span>
            <span>fallback <b style={{ color: TXT }}>{String(cur.tc.investigator?.fallback || cur.tc.challenger?.fallback || false)}</b></span>
            {cur.tc.investigator?.attempts ? <span>attempts <b style={{ color: TXT }}>{cur.tc.investigator.attempts}</b></span> : null}
          </div>
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", fontSize: 12, color: MUT }}>raw evidence</summary>
            <pre style={{ ...mono, whiteSpace: "pre-wrap" }}>{JSON.stringify(cur, null, 2)}</pre>
          </details>
        </div>
      )}
      {e && <p style={err}>{e}</p>}
    </div>
  );
}

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
  const summary = cur?.exec?.summary || {};
  const gaps = J(cur?.exec?.coverage_gaps) || [];

  return (
    <div>
      <div style={panel}>
        <p style={title}>New scenario run</p>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={concern} onChange={(e) => setConcern(e.target.value)} style={{ ...input, flex: 2 }} />
          <input value={by} onChange={(e) => setBy(e.target.value)} style={{ ...input, maxWidth: 150 }} />
          <button style={btn} disabled={busy || !k} onClick={run}>{busy ? "Running…" : "Generate"}</button>
        </div>
      </div>
      <div style={panel}>
        <p style={title}>Scenario runs ({rows.length})</p>
        {rows.length === 0 && <p style={{ color: MUT, fontSize: 13 }}>No runs yet. Generate one above.</p>}
        {rows.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={th}>Concern</th><th style={th}>State</th><th style={th}>Match</th>
              <th style={th}>Miss</th><th style={th}>Over-alert</th><th style={th}></th>
            </tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.set} onClick={() => setSel(r.set)}
                  style={{ cursor: "pointer", background: r.set === sel ? "#1a1d22" : "transparent" }}>
                <td style={{ ...td, maxWidth: 320 }}>{r.concern}</td>
                <td style={td}>{r.exec ? "EXECUTED" : r.state}</td>
                <td style={td}>{r.exec?.summary.matches ?? "—"}</td>
                <td style={td}>{r.exec?.summary.misses ?? "—"}</td>
                <td style={td}>{r.exec?.summary.over_alerts ?? "—"}</td>
                <td style={td}>{!r.exec && <button style={btnS} onClick={(ev) => { ev.stopPropagation(); approve(r); }}>Approve</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {cur?.exec && (
        <div style={panel}>
          <p style={title}>Control results</p>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr><th style={th}>Scenario</th><th style={th}>Expected</th><th style={th}>Actual</th><th style={th}>Verdict</th></tr></thead>
            <tbody>{Object.entries(results).map(([idx, r]) => (
              <tr key={idx}>
                <td style={td}>#{idx}</td><td style={td}>{r.expected}</td><td style={td}>{r.actual}</td>
                <td style={td}><span style={verPill(r.verdict)}>{r.verdict}</span></td>
              </tr>
            ))}</tbody>
          </table>
          <p style={{ ...title, marginTop: 14 }}>What was NOT tested</p>
          <ul style={{ fontSize: 13, color: MUT, margin: "0 0 8px", paddingLeft: 18 }}>
            {gaps.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
          <div style={{ fontSize: 12, color: MUT }}>evidence pack <span style={mono}>{String(cur.exec.evidence_pack_hash).slice(0, 20)}…</span></div>
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", fontSize: 12, color: MUT }}>raw evidence</summary>
            <pre style={{ ...mono, whiteSpace: "pre-wrap" }}>{JSON.stringify(cur, null, 2)}</pre>
          </details>
        </div>
      )}
      {e && <p style={err}>{e}</p>}
    </div>
  );
}

export default function App() {
  const [key, setKey] = useState("");
  const [tab, setTab] = useState("inv");
  const [health, setHealth] = useState(null);
  const [invRows, setInvRows] = useState([]);
  const [scnRows, setScnRows] = useState([]);

  return (
    <div style={page}>
      <div style={wrap}>
        <div style={header}>
          <h2 style={{ margin: 0, fontSize: 18 }}>OmniGuard AML — Financial crime compliance</h2>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: MUT }}>API key</span>
            <input type="password" placeholder="required" value={key}
              onChange={(e) => setKey(e.target.value)} style={{ ...input, width: 180 }} />
            <button style={ghost} onClick={async () => {
              try { setHealth(await call("/health", key)); }
              catch (e) { setHealth({ error: String(e) }); }
            }}>Check</button>
          </div>
        </div>
        {health && (
          <div style={{ fontSize: 12, color: MUT, marginBottom: 4 }}>
            api {health.status || "?"} · queue {health.services?.queue || "?"} · llm {health.services?.llm || health.error || "?"}
          </div>
        )}
        <div style={tabs}>
          <span style={tab(tab === "inv")} onClick={() => setTab("inv")}>Investigations ({invRows.length})</span>
          <span style={tab(tab === "scn")} onClick={() => setTab("scn")}>Scenario runs ({scnRows.length})</span>
        </div>
        {tab === "inv"
          ? <Investigate k={key} rows={invRows} setRows={setInvRows} />
          : <Scenario k={key} rows={scnRows} setRows={setScnRows} />}
      </div>
    </div>
  );
}
