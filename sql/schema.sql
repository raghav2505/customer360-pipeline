CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id UUID PRIMARY KEY,
    batch_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    input_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS raw_customers (
    source_customer_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    phone TEXT,
    updated_at TIMESTAMPTZ,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);
CREATE TABLE IF NOT EXISTS raw_accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    account_type TEXT NOT NULL,
    status TEXT NOT NULL,
    opened_at TIMESTAMPTZ,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);
CREATE TABLE IF NOT EXISTS raw_orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    currency TEXT NOT NULL,
    order_ts TIMESTAMPTZ NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);
CREATE TABLE IF NOT EXISTS raw_interactions (
    interaction_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_ts TIMESTAMPTZ NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);

CREATE TABLE IF NOT EXISTS source_record_history (
    history_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    old_source_hash TEXT NOT NULL,
    new_source_hash TEXT NOT NULL,
    old_payload JSONB NOT NULL,
    new_payload JSONB NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);

CREATE OR REPLACE FUNCTION log_source_record_change() RETURNS trigger AS $$
BEGIN
    IF OLD.source_hash IS DISTINCT FROM NEW.source_hash THEN
        INSERT INTO source_record_history(source_name, source_record_id, old_source_hash, new_source_hash, old_payload, new_payload, run_id)
        VALUES (TG_ARGV[0], to_jsonb(OLD)->>TG_ARGV[1], OLD.source_hash, NEW.source_hash,
                to_jsonb(OLD), to_jsonb(NEW), NEW.last_seen_run_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_history_customers ON raw_customers;
CREATE TRIGGER trg_history_customers AFTER UPDATE ON raw_customers
FOR EACH ROW EXECUTE FUNCTION log_source_record_change('customers', 'source_customer_id');
DROP TRIGGER IF EXISTS trg_history_accounts ON raw_accounts;
CREATE TRIGGER trg_history_accounts AFTER UPDATE ON raw_accounts
FOR EACH ROW EXECUTE FUNCTION log_source_record_change('accounts', 'account_id');
DROP TRIGGER IF EXISTS trg_history_orders ON raw_orders;
CREATE TRIGGER trg_history_orders AFTER UPDATE ON raw_orders
FOR EACH ROW EXECUTE FUNCTION log_source_record_change('orders', 'order_id');
DROP TRIGGER IF EXISTS trg_history_interactions ON raw_interactions;
CREATE TRIGGER trg_history_interactions AFTER UPDATE ON raw_interactions
FOR EACH ROW EXECUTE FUNCTION log_source_record_change('interactions', 'interaction_id');

CREATE TABLE IF NOT EXISTS customer_identity_map (
    source_customer_id TEXT PRIMARY KEY,
    canonical_customer_id UUID NOT NULL,
    match_rule TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);
CREATE INDEX IF NOT EXISTS ix_identity_canonical ON customer_identity_map(canonical_customer_id);

CREATE TABLE IF NOT EXISTS uncertain_matches (
    source_customer_id_a TEXT NOT NULL,
    source_customer_id_b TEXT NOT NULL,
    reason TEXT NOT NULL,
    run_id UUID NOT NULL REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (source_customer_id_a, source_customer_id_b, reason)
);
CREATE TABLE IF NOT EXISTS quarantine_records (
    source_name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_id TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL,
    reason_detail TEXT NOT NULL,
    raw_record JSONB NOT NULL,
    first_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (source_name, source_file, source_row_number, reason_code)
);

CREATE TABLE IF NOT EXISTS unified_customers (
    canonical_customer_id UUID PRIMARY KEY,
    customer_name TEXT,
    email_normalized TEXT,
    phone_normalized TEXT,
    source_customer_ids TEXT[] NOT NULL,
    account_count INTEGER NOT NULL DEFAULT 0,
    active_account_count INTEGER NOT NULL DEFAULT 0,
    order_count INTEGER NOT NULL DEFAULT 0,
    lifetime_order_value NUMERIC(16,2) NOT NULL DEFAULT 0,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    first_order_at TIMESTAMPTZ,
    last_order_at TIMESTAMPTZ,
    latest_interaction_at TIMESTAMPTZ,
    built_at TIMESTAMPTZ NOT NULL,
    last_seen_run_id UUID NOT NULL REFERENCES pipeline_runs(run_id)
);
CREATE INDEX IF NOT EXISTS ix_unified_email ON unified_customers(email_normalized);

CREATE OR REPLACE VIEW v_reconciliation AS
SELECT 'customers' AS entity,
       (SELECT count(*) FROM raw_customers) AS accepted_source_rows,
       (SELECT count(*) FROM quarantine_records WHERE source_name='customers') AS quarantined_rows
UNION ALL SELECT 'accounts', (SELECT count(*) FROM raw_accounts),
       (SELECT count(*) FROM quarantine_records WHERE source_name='accounts')
UNION ALL SELECT 'orders', (SELECT count(*) FROM raw_orders),
       (SELECT count(*) FROM quarantine_records WHERE source_name='orders')
UNION ALL SELECT 'interactions', (SELECT count(*) FROM raw_interactions),
       (SELECT count(*) FROM quarantine_records WHERE source_name='interactions');
