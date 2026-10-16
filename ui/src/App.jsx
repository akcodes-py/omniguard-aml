import { useState } from "react";
import { call, sleep } from "./api.js";

const input = { background: "#0f1420", border: "1px solid #2a3350", color: "#e8ecf4", padding: "8px 10px", borderRadius: 6, width: "100%", boxSizing: "border-box" };
const btn = { background: "#3b82f6", border: 0, color: "#fff", padding: "8px 14px", borderRadius: 6, cursor: "pointer" };
const card = { background: "#161c2e", border: "1px solid #26304d", borderRadius: 10, padding: 16, marginTop: 16 };
const mono = { fontFamily: "ui-monospace, monospace", fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" };

function useKey() {
  const [key, setKey] = useState("");
  const bar = (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input type="password" placeholder="X-API-Key (memory only)" value={key}
        onChange={(e) => setKey(e.target.value)} style={{ ...input, maxWidth: 320 }} />
      <span style={{ fontSize: 12, color: key ? "#4ade80" : "#f87171" }}>{key ? "key set" : "key required"}</span>
    </div>
  );
  return [key, bar];
}

function Health({ k }) {
  const [s, setS] = useState(null);
  const [e, setE] = useState(null);
  return (
    <section style={card}>
      <h3>Health</h3>
      <button style={btn} onClick={async () => { setE(null); try { setS(await call("/health", k)); } catch (err) { setE(String(err)); } }}>
        Check
      </button>
      {s && <pre style={mono}>{JSON.stringify(s, null, 2)}</pre>}
      {e && <p style={{ color: "#f87171" }}>{e}</p>}
    </section>
  );
}

function Investigate({ k }) {
  const [alertId, setAlertId] = useState("alert-demo-rapid");
  const [out, setOut] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [analyst, setAnalyst] = useState("analyst-1");
  const [decision, setDecision] = useState("ESCALATE");
  const [notes, setNotes] = useState("");

  async function run() {
    setErr(null); setOut(null); setBusy(true);
    try {
      await call(`/investigate/${alertId}`, k, { method: "POST" });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/investigate/${alertId}/status`, k);
        if (st.disposition) break;
      }
      setOut(st);
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  async function review() {
    setErr(null); setBusy(true);
    try {
      const runId = out?.partial_results?.run_id;
      const r = await call(`/investigate/${alertId}/review`, k,
        { method: "POST", body: JSON.stringify({ run_id: runId, analyst_id: analyst, decision, notes }) });
      setOut({ ...out, review: r });
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  return (
    <section style={card}>
      <h3>Investigate alert</h3>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={alertId} onChange={(e) => setAlertId(e.target.value)} style={input} />
        <button style={btn} disabled={busy || !k} onClick={run}>{busy ? "…" : "Investigate"}</button>
      </div>
      {out && <pre style={mono}>{JSON.stringify(out, null, 2)}</pre>}
      {out?.disposition && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} style={{ ...input, maxWidth: 160 }} />
          <select value={decision} onChange={(e) => setDecision(e.target.value)} style={{ ...input, maxWidth: 200 }}>
            <option>ESCALATE</option><option>CLOSE</option>
            <option>REQUEST_RERUN</option><option>RETURN_FOR_RERUN</option>
          </select>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="notes" style={{ ...input, maxWidth: 220 }} />
          <button style={btn} disabled={busy} onClick={review}>Submit review</button>
        </div>
      )}
      {err && <p style={{ color: "#f87171" }}>{err}</p>}
    </section>
  );
}

function Scenario({ k }) {
  const [concern, setConcern] = useState("smurfing via micro-deposits under reporting threshold");
  const [by, setBy] = useState("risk-owner-1");
  const [out, setOut] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setErr(null); setOut(null); setBusy(true);
    try {
      const { concern_id } = await call("/scenario/", k,
        { method: "POST", body: JSON.stringify({ concern_text: concern, submitted_by: by }) });
      let st = null;
      for (let i = 0; i < 20; i++) {
        await sleep(1500);
        st = await call(`/scenario/${concern_id}/status`, k);
        if (st.scenarios_generated) break;
      }
      setOut({ concern_id, ...st });
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  async function approve() {
    setErr(null); setBusy(true);
    try {
      const exec = await call(`/scenario/${out.set_id}/approve`, k, { method: "POST", body: "{}" });
      const res = await call(`/scenario/${out.set_id}/results`, k);
      setOut({ ...out, exec, res });
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  return (
    <section style={card}>
      <h3>ScenarioLab</h3>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={concern} onChange={(e) => setConcern(e.target.value)} style={{ ...input, flex: 2 }} />
        <input value={by} onChange={(e) => setBy(e.target.value)} style={{ ...input, maxWidth: 160 }} />
        <button style={btn} disabled={busy || !k} onClick={run}>{busy ? "…" : "Generate"}</button>
      </div>
      {out && <pre style={mono}>{JSON.stringify(out, null, 2)}</pre>}
      {out?.scenarios_generated && !out.exec && (
        <button style={{ ...btn, marginTop: 8 }} disabled={busy} onClick={approve}>Approve &amp; execute control</button>
      )}
      {err && <p style={{ color: "#f87171" }}>{err}</p>}
    </section>
  );
}

export default function App() {
  const [key, bar] = useKey();
  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: 20, background: "#0b0f1a", color: "#e8ecf4", minHeight: "100vh" }}>
      <h2>OmniGuard AML</h2>
      {bar}
      <Health k={key} />
      <Investigate k={key} />
      <Scenario k={key} />
    </div>
  );
}
