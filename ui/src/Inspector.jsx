import { useMemo, useState } from "react";
import { kindStyle } from "./GraphCanvas.jsx";
import { money, shortTs, timeAgo } from "./layout.js";
import { ChevronLeft, ChevronRight, External, More, Sort, Link } from "./icons.jsx";

const TITLE = {
  card: "Card Summary",
  person: "Person Summary",
  business: "Business Summary",
  account: "Account Summary",
  document: "Document Summary",
};

function Field({ label, value, mono }) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="text-[11.5px] text-slate-500 mb-0.5">{label}</div>
      <div className={`text-[13.5px] font-semibold text-slate-900 leading-snug ${mono ? "font-mono" : ""}`}>
        {value || "—"}
      </div>
    </div>
  );
}

function Stat({ label, value, cap, currency }) {
  const pct = cap > 0 ? Math.min(100, Math.round((value / cap) * 100)) : 0;
  const fmt = (v) => (currency ? money(v) : v);
  return (
    <div className="rounded-lg bg-[#f4f5f7] px-3 py-2.5 flex-1 min-w-0 text-center">
      <div className="text-[10.5px] font-medium text-slate-600 mb-1">{label}</div>
      <div className="flex items-baseline justify-center gap-1.5">
        <span className="text-[19px] font-bold text-[#e11d48] leading-none tabular-nums">{fmt(value)}</span>
        <span className="text-[13px] font-medium text-slate-500 leading-none">/ {fmt(cap)}</span>
      </div>
      <div className="mt-2 h-[3px] rounded-full bg-slate-200 overflow-hidden">
        <div className="h-full rounded-full bg-[#e11d48]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function thirdField(node) {
  if (node.kind === "card") return { label: "Brand", value: node.brand || "Card" };
  if (node.kind === "person") return { label: "Purpose", value: node.account_purpose || "Individual" };
  if (node.kind === "document") return { label: "Type", value: node.account_purpose || "KYC artifact" };
  return { label: "Purpose", value: node.account_purpose || "Business" };
}

export default function Inspector({ data, selectedId, onSelect, open, onToggle }) {
  const [tab, setTab] = useState("tx");
  const [sort, setSort] = useState({ key: "ts", dir: "desc" });

  const node = useMemo(
    () => data.nodes.find((n) => n.id === selectedId) || data.focal || data.nodes[0],
    [data, selectedId]
  );
  const st = kindStyle(node?.kind);
  const Glyph = st.Glyph;
  const third = thirdField(node || {});

  const isFocal = !!node?.is_focal;
  const txCount = node?.tx_count ?? data.summary.tx_count;
  const txCap = isFocal ? data.summary.tx_capacity : node?.tx_count ?? 0;
  const amount = node?.amount_total ?? data.summary.amount_total;
  const amountCap = isFocal ? data.summary.amount_capacity : node?.amount_total ?? 0;

  const rows = useMemo(() => {
    let list = data.transactions || [];
    if (!isFocal) list = list.filter((t) => t.counterparty === node.id);
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      if (sort.key === "amount") return (a.amount - b.amount) * dir;
      return String(a.ts).localeCompare(String(b.ts)) * dir;
    });
  }, [data.transactions, isFocal, node?.id, sort]);

  const connections = useMemo(() => {
    if (!node) return [];
    return data.edges
      .filter((e) => e.source === node.id || e.target === node.id)
      .map((e) => {
        const other = e.source === node.id ? e.target : e.source;
        const n = data.nodes.find((x) => x.id === other) || { id: other, label: other, kind: "account" };
        return { ...e, node: n };
      })
      .sort((a, b) => b.amount - a.amount);
  }, [data.edges, data.nodes, node]);

  if (!open) {
    return (
      <button
        onClick={onToggle}
        title="Open inspector"
        className="absolute right-0 top-1/2 -translate-y-1/2 z-20 w-6 h-12 bg-white border border-slate-200 border-r-0 rounded-l-md shadow-sm flex items-center justify-center text-slate-400 hover:text-slate-700"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
    );
  }

  return (
    <aside className="relative w-[340px] shrink-0 bg-white border-l border-slate-200 flex flex-col h-full">
      <button
        onClick={onToggle}
        title="Collapse inspector"
        className="absolute -left-3 top-1/2 -translate-y-1/2 z-20 w-6 h-12 bg-white border border-slate-200 rounded-md shadow-sm flex items-center justify-center text-slate-400 hover:text-slate-700"
      >
        <ChevronRight className="w-4 h-4" />
      </button>

      <div className="h-[62px] px-5 flex items-center gap-3 border-b border-slate-100">
        <span className="w-7 h-7 rounded-md border border-slate-200 flex items-center justify-center text-slate-700">
          <Glyph className="w-[17px] h-[17px]" stroke="#0f172a" />
        </span>
        <h2 className="text-[14.5px] font-semibold text-slate-900">
          {TITLE[node?.kind] || "Entity Summary"}
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-5 pt-5 pb-4">
          <Field label="Label" value={node?.label} />
          <Field label="Id" value={node?.id} mono />
          <Field label={third.label} value={third.value} />
          <div className="flex gap-2.5 mt-4">
            <Stat label="Transactions" value={txCount} cap={txCap} />
            <Stat label="Amount" value={amount} cap={amountCap} currency />
          </div>
        </div>

        <div className="px-5">
          <div className="flex items-center gap-6 border-b border-slate-200">
            {[
              ["tx", "Transactions"],
              ["conn", "Connections"],
            ].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`pb-2.5 -mb-px text-[12.5px] font-medium border-b-2 transition-colors ${
                  tab === id
                    ? "text-blue-600 border-blue-600"
                    : "text-slate-500 border-transparent hover:text-slate-800"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {tab === "tx" ? (
          <div className="px-5 pt-4 pb-2">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-[12.5px] font-semibold text-slate-900">Top Transactions</span>
                <span className="text-[10.5px] font-medium text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                  {rows.length}
                </span>
              </div>
              <div className="flex items-center gap-2.5 text-slate-400">
                <button className="hover:text-slate-700" title="Open full ledger"><External className="w-3.5 h-3.5" /></button>
                <button className="hover:text-slate-700" title="More"><More className="w-3.5 h-3.5" /></button>
              </div>
            </div>

            <table className="w-full border-collapse">
              <thead>
                <tr className="text-slate-500">
                  <th className="text-left font-medium text-[11px] pb-2">
                    <button
                      className="inline-flex items-center gap-1 hover:text-slate-800"
                      onClick={() => setSort((s) => ({ key: "ts", dir: s.key === "ts" && s.dir === "desc" ? "asc" : "desc" }))}
                    >
                      Timestamp <Sort className="w-2.5 h-2.5" />
                    </button>
                  </th>
                  <th className="text-right font-medium text-[11px] pb-2">
                    <button
                      className="inline-flex items-center gap-1 hover:text-slate-800"
                      onClick={() => setSort((s) => ({ key: "amount", dir: s.key === "amount" && s.dir === "desc" ? "asc" : "desc" }))}
                    >
                      Amount <Sort className="w-2.5 h-2.5" />
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr
                    key={t.tx_id}
                    className="group cursor-pointer hover:bg-slate-50"
                    onClick={() => t.counterparty && onSelect(t.counterparty)}
                    title={t.counterparty_name || t.counterparty}
                  >
                    <td className="py-[7px] pr-2">
                      <div className="flex items-center gap-2">
                        <span className={`w-[5px] h-[5px] rounded-full shrink-0 ${t.direction === "OUT" ? "bg-[#e11d48]" : "bg-slate-300"}`} />
                        <span className="text-[11.5px] text-slate-600 tabular-nums">{shortTs(t.ts)}</span>
                      </div>
                    </td>
                    <td className="py-[7px] text-right text-[11.5px] font-semibold text-slate-800 tabular-nums">
                      {money(t.amount)}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={2} className="py-6 text-center text-[11.5px] text-slate-400">
                      No transactions touch this entity.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 pt-4 pb-2">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-[12.5px] font-semibold text-slate-900">Counterparties</span>
                <span className="text-[10.5px] font-medium text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                  {connections.length}
                </span>
              </div>
            </div>
            <div className="space-y-0.5">
              {connections.map((c) => {
                const cs = kindStyle(c.node.kind);
                const CG = cs.Glyph;
                return (
                  <button
                    key={c.id}
                    onClick={() => onSelect(c.node.id)}
                    className="w-full flex items-center gap-2.5 py-[7px] px-1 -mx-1 rounded hover:bg-slate-50 text-left"
                  >
                    <span className="w-5 h-5 rounded flex items-center justify-center text-white shrink-0" style={{ background: cs.fill }}>
                      <CG className="w-3 h-3" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11.5px] text-slate-800 truncate">{c.node.label}</span>
                      <span className="block text-[10px] text-slate-400 truncate">
                        {c.count} tx · {(c.channels || []).join(", ") || "—"}
                      </span>
                    </span>
                    <span className="text-[11.5px] font-semibold text-slate-700 tabular-nums">{money(c.amount)}</span>
                  </button>
                );
              })}
              {connections.length === 0 && (
                <p className="py-6 text-center text-[11.5px] text-slate-400">No connections in this window.</p>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="px-5 py-3 border-t border-slate-100 flex items-center justify-between text-[10.5px] text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <Link className="w-3 h-3" /> {data.source === "demo" ? "demo dataset" : "live ledger"}
        </span>
        <span>Last update: {timeAgo(data.fetchedAt)}</span>
      </div>
    </aside>
  );
}
