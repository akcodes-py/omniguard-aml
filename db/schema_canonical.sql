-- OmniGuard AML — canonical PostgreSQL 16 + pgvector DDL (Phase 0 freeze).
-- Reconciles PRD Sec 4 (5 schemas) with schema.sql starter.
--
-- DECISIONS (deviations from PRD md, Dirctor-approved for local run):
-- D1. PKs are TEXT holding UUID strings (uuid4 hex). Satisfies PRD "UUID"
--     format + starter "text" practicality. Postgres default:
--     gen_random_uuid()::text. App code uses uuid4().hex / str(uuid4()).
-- D2. Embedding dim 1024 (Titan Text Embeddings v2 default, starter sql)
--     NOT 1536 (PRD md assumed OpenAI). HNSW index per starter sql.
-- D3. policy table name policy_notes (starter) not typology_notes (PRD);
--     PRD field `content` == starter `body`.
-- D4. core.transactions keeps src/dst_account (NetworkX needs directed edges)
--     and ADDS PRD-compat columns: direction, currency, counterparty_name,
--     alert_id. Memo is RAW/attacker-controlled, never modified.
-- D5. audit keeps starter's stricter TRUNCATE guards + app_worker role;
--     same guard extended to scenario.control_runs + expected_outcomes.
-- D6. ADDED missing tables: core.graph_features, audit.model_promotions,
--     full scenario.* schema (PRD Sec 4 + Sec 6).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS policy;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS scenario;
CREATE SCHEMA IF NOT EXISTS agent_state;
-- agent_state tables are created by LangGraph AsyncPostgresSaver via
-- checkpointer.setup(); this schema stays empty in DDL on purpose
-- (mutable checkpoints must never mix with immutable audit).

-- ---------------------------------------------------------------- core
CREATE TABLE IF NOT EXISTS core.accounts (
    account_id              text PRIMARY KEY,   -- UUID string (D1)
    customer_name           text,
    account_type            text,               -- personal, business, correspondent
    occupation_category     text,
    occupation              text,
    risk_jurisdiction       text,
    high_risk_jurisdiction  boolean,
    onboarding_date         date,
    onboarded_at            timestamptz,
    account_purpose         text,               -- trading, payroll, treasury, personal
    parent_entity_id        text,               -- corporate group linkage / challenger shared-parent check
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.transactions (
    tx_id               text PRIMARY KEY,       -- UUID string
    ts                  timestamptz NOT NULL,
    src_account         text NOT NULL,
    dst_account         text NOT NULL,
    amount              numeric(18,2) NOT NULL CHECK (amount >= 0),
    currency            text NOT NULL DEFAULT 'USD',
    direction           text CHECK (direction IN ('IN', 'OUT')),
    tx_type             text,
    channel             text,                   -- wire, ach, cash, check
    memo                text,                   -- RAW, attacker-controlled. Never modified, never deleted.
    counterparty_name   text,                   -- UNTRUSTED, attacker-controlled
    alert_id            text,
    is_laundering       boolean,                -- dataset ground truth; training/eval only, never a model input
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tx_src_ts_idx ON core.transactions (src_account, ts);
CREATE INDEX IF NOT EXISTS tx_dst_ts_idx ON core.transactions (dst_account, ts);
CREATE INDEX IF NOT EXISTS tx_alert_idx ON core.transactions (alert_id);

CREATE TABLE IF NOT EXISTS core.alerts (
    alert_id        text PRIMARY KEY,           -- UUID string
    account_id      text NOT NULL REFERENCES core.accounts(account_id),
    trigger         text NOT NULL,              -- which rule or model score raised it
    rule_id         text,
    trigger_reason  text,
    status          text NOT NULL DEFAULT 'PENDING', -- PENDING, INVESTIGATING, REVIEWED
    window_start    timestamptz NOT NULL,
    window_end      timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Pre-computed NetworkX graph features per alert (Graph1 Node 1 output, Node 2 input).
CREATE TABLE IF NOT EXISTS core.graph_features (
    alert_id          text PRIMARY KEY REFERENCES core.alerts(alert_id),
    pagerank          double precision,
    betweenness       double precision,
    in_degree         integer,
    out_degree        integer,
    is_in_cycle       boolean,
    community_id      integer,
    shortest_path_hr  integer,                  -- hops to nearest high-risk node
    computed_at       timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- policy
-- Titan Text Embeddings v2: 1024 dims (D2). Only place pgvector is used.
CREATE TABLE IF NOT EXISTS policy.policy_notes (
    policy_id       text NOT NULL,
    version         integer NOT NULL,
    version_hash    text NOT NULL,              -- sha256 of body
    typology_tag    text NOT NULL,              -- structuring, layering, pass_through, shell_company...
    title           text NOT NULL,
    body            text NOT NULL,
    effective_from  date NOT NULL,
    effective_to    date,                       -- NULL = current
    embedding       vector(1024),
    PRIMARY KEY (policy_id, version)
);
CREATE INDEX IF NOT EXISTS policy_tag_idx ON policy.policy_notes (typology_tag);
CREATE INDEX IF NOT EXISTS policy_embedding_idx ON policy.policy_notes
    USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------- audit (append-only)
CREATE TABLE IF NOT EXISTS audit.investigation_runs (
    run_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id             text NOT NULL REFERENCES core.alerts(alert_id),
    thread_id            text NOT NULL,
    tx_watermark         text NOT NULL,          -- latest tx_id seen; staleness check
    features             jsonb NOT NULL,         -- frozen deterministic feature snapshot
    graph_features       jsonb,
    ml_scores            jsonb NOT NULL,         -- {supervised, anomaly, composite}
    shap_explanation     jsonb,
    injection_scan       jsonb NOT NULL,         -- {flagged_fields, quarantined}
    retrieved_policies   jsonb NOT NULL,         -- [{policy_id, version, version_hash}]
    investigator_output  jsonb,
    challenger_output    jsonb,
    verifier_result      jsonb NOT NULL,         -- {citations_valid, math_valid, disposition}
    disposition          text NOT NULL CHECK (disposition IN
                            ('RECOMMEND_ESCALATE','RECOMMEND_CLOSE','CONFLICT_HUMAN_REVIEW')),
    prompt_version_hash  text NOT NULL,
    model_id             text NOT NULL,
    token_cost           jsonb,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_alert_idx ON audit.investigation_runs (alert_id, created_at);

CREATE TABLE IF NOT EXISTS audit.human_decisions (
    decision_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        uuid NOT NULL REFERENCES audit.investigation_runs(run_id),
    alert_id      text NOT NULL,
    analyst_id    text NOT NULL,
    decision      text NOT NULL CHECK (decision IN ('ESCALATE','CLOSE','REQUEST_RERUN','RETURN_FOR_RERUN')),
    rationale     text NOT NULL,
    stale_rerun   boolean NOT NULL DEFAULT FALSE,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_human_decisions_run_id ON audit.human_decisions(run_id);

CREATE TABLE IF NOT EXISTS audit.model_promotions (
    promotion_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type         text NOT NULL,            -- lightgbm_classifier, isolation_forest
    old_version        text,
    new_version        text NOT NULL,
    regression_results jsonb NOT NULL,          -- {precision, recall, f1, passed}
    promoted_by        text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION audit.block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (% blocked)', TG_TABLE_NAME, TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS runs_no_update_delete ON audit.investigation_runs;
CREATE TRIGGER runs_no_update_delete
    BEFORE UPDATE OR DELETE ON audit.investigation_runs
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();
DROP TRIGGER IF EXISTS runs_no_truncate ON audit.investigation_runs;
CREATE TRIGGER runs_no_truncate
    BEFORE TRUNCATE ON audit.investigation_runs
    FOR EACH STATEMENT EXECUTE FUNCTION audit.block_mutation();

DROP TRIGGER IF EXISTS decisions_no_update_delete ON audit.human_decisions;
CREATE TRIGGER decisions_no_update_delete
    BEFORE UPDATE OR DELETE ON audit.human_decisions
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();
DROP TRIGGER IF EXISTS decisions_no_truncate ON audit.human_decisions;
CREATE TRIGGER decisions_no_truncate
    BEFORE TRUNCATE ON audit.human_decisions
    FOR EACH STATEMENT EXECUTE FUNCTION audit.block_mutation();

DROP TRIGGER IF EXISTS promotions_no_update_delete ON audit.model_promotions;
CREATE TRIGGER promotions_no_update_delete
    BEFORE UPDATE OR DELETE ON audit.model_promotions
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();
DROP TRIGGER IF EXISTS promotions_no_truncate ON audit.model_promotions;
CREATE TRIGGER promotions_no_truncate
    BEFORE TRUNCATE ON audit.model_promotions
    FOR EACH STATEMENT EXECUTE FUNCTION audit.block_mutation();

-- ---------------------------------------------------------------- scenario (ScenarioLab, PRD Sec 4 + Sec 6)
CREATE TABLE IF NOT EXISTS scenario.risk_concerns (
    concern_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    concern_text  text NOT NULL,
    submitted_by  text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario.scenario_sets (
    set_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    concern_id          uuid REFERENCES scenario.risk_concerns(concern_id),
    version             integer NOT NULL DEFAULT 1,
    scenarios           jsonb NOT NULL,          -- array of scenario specs
    scenario_hash       text NOT NULL,           -- SHA-256 of scenarios JSON
    generated_txs       jsonb NOT NULL,          -- deterministic tx rows from specs
    challenger_findings jsonb,
    diversity_score     double precision,        -- pgvector pairwise similarity
    status              text NOT NULL DEFAULT 'DRAFT', -- DRAFT, LOCKED, APPROVED, EXECUTED
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario.expected_outcomes (
    outcome_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id          uuid REFERENCES scenario.scenario_sets(set_id),
    expectations    jsonb NOT NULL,              -- {scenario_idx: ALERT|NO_ALERT}
    expectation_hash text NOT NULL,             -- SHA-256, sealed before control runs
    locked_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario.control_runs (
    run_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id            uuid REFERENCES scenario.scenario_sets(set_id),
    control_id        text NOT NULL,             -- which rule or ML model was tested
    control_version   text,
    results           jsonb NOT NULL,            -- {scenario_idx: {expected, actual, verdict}}
    summary           jsonb NOT NULL,            -- {matches, misses, over_alerts, total}
    coverage_gaps     text[],                   -- explicit "what was NOT tested"
    evidence_pack_hash text NOT NULL,           -- SHA-256 of full evidence pack
    created_at        timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS outcomes_no_update_delete ON scenario.expected_outcomes;
CREATE TRIGGER outcomes_no_update_delete
    BEFORE UPDATE OR DELETE ON scenario.expected_outcomes
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();

DROP TRIGGER IF EXISTS control_runs_no_update_delete ON scenario.control_runs;
CREATE TRIGGER control_runs_no_update_delete
    BEFORE UPDATE OR DELETE ON scenario.control_runs
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();
DROP TRIGGER IF EXISTS control_runs_no_truncate ON scenario.control_runs;
CREATE TRIGGER control_runs_no_truncate
    BEFORE TRUNCATE ON scenario.control_runs
    FOR EACH STATEMENT EXECUTE FUNCTION audit.block_mutation();

-- ---------------------------------------------------------------- roles
-- Triggers alone do not stop a table owner/superuser from dropping them.
-- The app connects as app_worker: INSERT/SELECT on audit, SELECT on core/policy.
DO $$
BEGIN
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN
            CREATE ROLE app_worker LOGIN PASSWORD 'change-me'; -- replace via secret in deployment
        END IF;
        GRANT USAGE ON SCHEMA core, policy, audit, scenario, agent_state TO app_worker;
        GRANT SELECT ON ALL TABLES IN SCHEMA core, policy TO app_worker;
        GRANT INSERT, SELECT ON audit.investigation_runs, audit.human_decisions, audit.model_promotions TO app_worker;
        GRANT INSERT, SELECT ON scenario.risk_concerns, scenario.scenario_sets, scenario.expected_outcomes, scenario.control_runs TO app_worker;
        GRANT ALL ON SCHEMA agent_state TO app_worker;
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping CREATE ROLE / GRANT app_worker due to non-superuser privileges on cloud Postgres';
    END;
END $$;
