-- SQLite-compatible subset of schema_canonical.sql for local dev/test.
-- No pgvector (embedding stored as JSON text), no pgcrypto (app generates
-- UUID strings), RAISE(ABORT) triggers emulate append-only guards.
-- Canonical contract remains Postgres; this file is a dev fallback only.

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    customer_name TEXT,
    account_type TEXT,
    occupation_category TEXT,
    occupation TEXT,
    risk_jurisdiction TEXT,
    high_risk_jurisdiction INTEGER,
    onboarding_date TEXT,
    onboarded_at TEXT,
    account_purpose TEXT,
    parent_entity_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    src_account TEXT NOT NULL,
    dst_account TEXT NOT NULL,
    amount NUMERIC NOT NULL CHECK (amount >= 0),
    currency TEXT NOT NULL DEFAULT 'USD',
    direction TEXT CHECK (direction IN ('IN','OUT')),
    tx_type TEXT,
    channel TEXT,
    memo TEXT,
    counterparty_name TEXT,
    alert_id TEXT,
    is_laundering INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS tx_src_ts_idx ON transactions (src_account, ts);
CREATE INDEX IF NOT EXISTS tx_dst_ts_idx ON transactions (dst_account, ts);
CREATE INDEX IF NOT EXISTS tx_alert_idx ON transactions (alert_id);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    trigger TEXT NOT NULL,
    rule_id TEXT,
    trigger_reason TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS graph_features (
    alert_id TEXT PRIMARY KEY REFERENCES alerts(alert_id),
    pagerank REAL,
    betweenness REAL,
    in_degree INTEGER,
    out_degree INTEGER,
    is_in_cycle INTEGER,
    community_id INTEGER,
    shortest_path_hr INTEGER,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS policy_notes (
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    version_hash TEXT NOT NULL,
    typology_tag TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    embedding TEXT, -- JSON array of floats (1024d)
    PRIMARY KEY (policy_id, version)
);
CREATE INDEX IF NOT EXISTS policy_tag_idx ON policy_notes (typology_tag);

CREATE TABLE IF NOT EXISTS investigation_runs (
    run_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES alerts(alert_id),
    thread_id TEXT NOT NULL,
    tx_watermark TEXT NOT NULL,
    features TEXT NOT NULL,
    graph_features TEXT,
    ml_scores TEXT NOT NULL,
    shap_explanation TEXT,
    injection_scan TEXT NOT NULL,
    retrieved_policies TEXT NOT NULL,
    investigator_output TEXT,
    challenger_output TEXT,
    verifier_result TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('RECOMMEND_ESCALATE','RECOMMEND_CLOSE','CONFLICT_HUMAN_REVIEW')),
    prompt_version_hash TEXT NOT NULL,
    model_id TEXT NOT NULL,
    token_cost TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS runs_alert_idx ON investigation_runs (alert_id, created_at);

CREATE TABLE IF NOT EXISTS human_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES investigation_runs(run_id),
    alert_id TEXT NOT NULL,
    analyst_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('ESCALATE','CLOSE','REQUEST_RERUN','RETURN_FOR_RERUN')),
    rationale TEXT NOT NULL,
    stale_rerun INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS model_promotions (
    promotion_id TEXT PRIMARY KEY,
    model_type TEXT NOT NULL,
    old_version TEXT,
    new_version TEXT NOT NULL,
    regression_results TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS risk_concerns (
    concern_id TEXT PRIMARY KEY,
    concern_text TEXT NOT NULL,
    submitted_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scenario_sets (
    set_id TEXT PRIMARY KEY,
    concern_id TEXT REFERENCES risk_concerns(concern_id),
    version INTEGER NOT NULL DEFAULT 1,
    scenarios TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    generated_txs TEXT NOT NULL,
    challenger_findings TEXT,
    diversity_score REAL,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expected_outcomes (
    outcome_id TEXT PRIMARY KEY,
    set_id TEXT REFERENCES scenario_sets(set_id),
    expectations TEXT NOT NULL,
    expectation_hash TEXT NOT NULL,
    locked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS control_runs (
    run_id TEXT PRIMARY KEY,
    set_id TEXT REFERENCES scenario_sets(set_id),
    control_id TEXT NOT NULL,
    control_version TEXT,
    results TEXT NOT NULL,
    summary TEXT NOT NULL,
    coverage_gaps TEXT NOT NULL, -- JSON array
    evidence_pack_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only guards (SQLite equivalent of audit.block_mutation).
-- NOTE: this SQLite build does not accept multi-event triggers
-- (BEFORE UPDATE OR DELETE), so each table gets two single-event triggers.
DROP TRIGGER IF EXISTS runs_no_update;
CREATE TRIGGER runs_no_update
BEFORE UPDATE ON investigation_runs
BEGIN SELECT RAISE(ABORT, 'investigation_runs is append-only'); END;
DROP TRIGGER IF EXISTS runs_no_delete;
CREATE TRIGGER runs_no_delete
BEFORE DELETE ON investigation_runs
BEGIN SELECT RAISE(ABORT, 'investigation_runs is append-only'); END;

DROP TRIGGER IF EXISTS decisions_no_update;
CREATE TRIGGER decisions_no_update
BEFORE UPDATE ON human_decisions
BEGIN SELECT RAISE(ABORT, 'human_decisions is append-only'); END;
DROP TRIGGER IF EXISTS decisions_no_delete;
CREATE TRIGGER decisions_no_delete
BEFORE DELETE ON human_decisions
BEGIN SELECT RAISE(ABORT, 'human_decisions is append-only'); END;

DROP TRIGGER IF EXISTS promotions_no_update;
CREATE TRIGGER promotions_no_update
BEFORE UPDATE ON model_promotions
BEGIN SELECT RAISE(ABORT, 'model_promotions is append-only'); END;
DROP TRIGGER IF EXISTS promotions_no_delete;
CREATE TRIGGER promotions_no_delete
BEFORE DELETE ON model_promotions
BEGIN SELECT RAISE(ABORT, 'model_promotions is append-only'); END;

DROP TRIGGER IF EXISTS outcomes_no_update;
CREATE TRIGGER outcomes_no_update
BEFORE UPDATE ON expected_outcomes
BEGIN SELECT RAISE(ABORT, 'expected_outcomes is append-only'); END;
DROP TRIGGER IF EXISTS outcomes_no_delete;
CREATE TRIGGER outcomes_no_delete
BEFORE DELETE ON expected_outcomes
BEGIN SELECT RAISE(ABORT, 'expected_outcomes is append-only'); END;

DROP TRIGGER IF EXISTS control_runs_no_update;
CREATE TRIGGER control_runs_no_update
BEFORE UPDATE ON control_runs
BEGIN SELECT RAISE(ABORT, 'control_runs is append-only'); END;
DROP TRIGGER IF EXISTS control_runs_no_delete;
CREATE TRIGGER control_runs_no_delete
BEFORE DELETE ON control_runs
BEGIN SELECT RAISE(ABORT, 'control_runs is append-only'); END;
