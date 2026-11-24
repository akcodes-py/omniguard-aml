// Curated demo graph so the workspace renders without a backend/API key.
// Mirrors the live /graph/{alert_id} contract exactly.

const N = (id, label, kind, extra = {}) => ({
  id, label, kind, high_risk: false, is_focal: false,
  tx_count: 1, amount_total: 0, account_purpose: null, jurisdiction: null, ...extra,
});

const E = (source, target, amount, opts = {}) => ({
  id: `${source}->${target}`, source, target, amount, count: 1,
  channels: opts.channels || ["ach"], laundering: !!opts.laundering,
});

const TX = [
  ["2020-05-19 13:36:40", 58, "P-1", "A. Okafor"],
  ["2020-05-18 09:50:00", 16, "C-2", "CC2"],
  ["2020-05-17 06:03:20", 9, "B-7", "Meridian Bank"],
  ["2020-05-16 02:16:40", 24, "P-3", "M. Chen"],
  ["2020-05-14 22:30:00", 7, "B-3", "Northgate Bank"],
  ["2020-05-13 18:43:20", 6, "C-3", "CC3"],
  ["2020-05-12 14:56:40", 8, "B-11", "Crescent Bank"],
  ["2020-05-11 11:10:00", 9, "B-5", "Atlas Bank"],
  ["2020-05-10 07:23:20", 4, "B-2", "First Union"],
  ["2020-05-09 03:36:40", 5, "P-2", "J. Silva"],
  ["2020-05-07 23:50:00", 6, "B-9", "Summit Bank"],
  ["2020-05-06 20:03:20", 5, "B-12", "Harbor Bank"],
];

const banks = [
  ["B-1", "First National", 14, 1840],
  ["B-2", "First Union", 6, 612],
  ["B-3", "Northgate Bank", 8, 934],
  ["B-4", "Ridgeway Bank", 4, 288],
  ["B-5", "Atlas Bank", 9, 1102],
  ["B-6", "Beacon Bank", 3, 214],
  ["B-7", "Meridian Bank", 11, 1487],
  ["B-8", "Cobalt Bank", 5, 470],
  ["B-9", "Summit Bank", 7, 736],
  ["B-10", "Vantage Bank", 4, 352],
  ["B-11", "Crescent Bank", 8, 845],
  ["B-12", "Harbor Bank", 5, 401],
  ["B-13", "Union Trust", 3, 260],
  ["B-14", "Sterling Bank", 2, 170],
];

const nodes = [
  N("CC1", "CC1", "card", { is_focal: true, brand: "Mastercard", tx_count: 8, amount_total: 157 }),
  N("C-2", "CC2", "card", { brand: "Visa", tx_count: 6, amount_total: 421 }),
  N("C-3", "CC3", "card", { brand: "Amex", tx_count: 3, amount_total: 96 }),
  N("P-1", "A. Okafor", "person", { tx_count: 9, amount_total: 1284 }),
  N("P-2", "J. Silva", "person", { tx_count: 5, amount_total: 512 }),
  N("P-3", "M. Chen", "person", { tx_count: 4, amount_total: 233 }),
  N("D-1", "KYC-8841", "document", { tx_count: 1, amount_total: 0 }),
  N("D-2", "INV-2201", "document", { tx_count: 1, amount_total: 0 }),
  N("D-3", "CTR-0912", "document", { tx_count: 1, amount_total: 0 }),
  ...banks.map(([id, label, c, a], i) =>
    N(id, label, "business", { tx_count: c, amount_total: a, high_risk: [2, 6, 10].includes(i) })
  ),
];

const edges = [
  E("CC1", "P-1", 58, { laundering: true, channels: ["card"] }),
  E("CC1", "C-2", 48, { laundering: true, channels: ["card"] }),
  E("CC1", "P-3", 24, { laundering: true, channels: ["card"] }),
  E("CC1", "C-3", 16, { channels: ["card"] }),
  E("CC1", "B-7", 9, { channels: ["card"] }),
  E("CC1", "B-11", 8, { channels: ["card"] }),
  E("CC1", "B-3", 7, { channels: ["card"] }),
  E("B-1", "B-2", 11, { channels: ["wire"] }),
  E("B-1", "B-3", 9, { laundering: true }),
  E("B-1", "B-4", 7),
  E("B-1", "B-5", 6),
  E("B-1", "B-6", 4),
  E("B-1", "B-7", 8, { laundering: true }),
  E("B-1", "B-8", 5),
  E("B-1", "B-9", 4),
  E("B-1", "B-10", 3, { channels: ["wire"] }),
  E("B-1", "P-1", 6),
  E("B-1", "P-2", 4),
  E("P-1", "B-3", 9, { laundering: true }),
  E("P-2", "B-4", 5),
  E("C-2", "B-5", 7, { laundering: true, channels: ["card"] }),
  E("C-2", "B-8", 3, { channels: ["card"] }),
  E("P-3", "B-6", 4),
  E("P-3", "B-13", 3),
  E("D-1", "P-1", 1),
  E("D-2", "P-2", 1),
  E("D-3", "P-3", 1),
  E("B-2", "D-1", 2, { channels: ["wire"] }),
  E("C-3", "B-11", 6, { channels: ["card"] }),
  E("C-3", "B-12", 5, { channels: ["card"] }),
  E("B-10", "P-3", 3, { channels: ["wire"] }),
  E("B-12", "B-14", 2),
  E("B-9", "B-14", 2),
];

export const DEMO_GRAPH = {
  source: "demo",
  fetchedAt: Date.now(),
  alert: {
    alert_id: "demo-CC1",
    account_id: "CC1",
    trigger: "rule_card_velocity",
    trigger_reason: "card testing burst",
    status: "PENDING",
    window_start: "2020-05-06",
    window_end: "2020-05-19",
  },
  focal: nodes[0],
  nodes,
  edges,
  summary: {
    tx_count: 8,
    tx_capacity: 14,
    amount_total: 157,
    amount_capacity: 333,
    inflow: 96,
    outflow: 61,
    max_amount: 58,
    high_risk_nodes: 4,
  },
  transactions: TX.map(([ts, amount, counterparty, name], i) => ({
    tx_id: `demo-tx-${String(i + 1).padStart(2, "0")}`,
    ts: ts.replace(" ", "T") + "+00:00",
    amount,
    currency: "USD",
    channel: "card",
    tx_type: "card_purchase",
    memo: null,
    direction: i % 3 === 0 ? "IN" : "OUT",
    counterparty,
    counterparty_name: name,
  })),
};

export const DEMO_ALERTS = [
  { alert_id: "alert-demo-rapid", account_id: "acct-000", customer_name: "Allison Hill", trigger: "rule_48h_passthrough", trigger_reason: "rapid pass-through", status: "PENDING" },
  { alert_id: "alert-demo-clean", account_id: "acct-001", customer_name: "Taylor Inc", trigger: "ml_stream", trigger_reason: "routine review", status: "PENDING" },
  { alert_id: "alert-demo-inject", account_id: "acct-002", customer_name: "Yang, Gardner and Garza", trigger: "ml_stream", trigger_reason: "memo screening", status: "PENDING" },
];
