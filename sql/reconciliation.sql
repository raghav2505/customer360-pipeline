-- Run these after the pipeline completes.

-- Current raw-row counts and quarantined-row counts by source.
SELECT * FROM v_reconciliation ORDER BY entity;

-- Identity-map coverage: each accepted raw customer should have exactly one mapping.
SELECT
  (SELECT count(*) FROM raw_customers) AS raw_customer_count,
  (SELECT count(*) FROM customer_identity_map) AS mapped_customer_count,
  (SELECT count(DISTINCT canonical_customer_id) FROM customer_identity_map) AS canonical_customer_count;

-- Orphan check: expected to return zero rows.
SELECT 'accounts' AS source, a.account_id AS record_id, a.customer_id
FROM raw_accounts a LEFT JOIN customer_identity_map m ON m.source_customer_id=a.customer_id
WHERE m.source_customer_id IS NULL
UNION ALL
SELECT 'orders', o.order_id, o.customer_id
FROM raw_orders o LEFT JOIN customer_identity_map m ON m.source_customer_id=o.customer_id
WHERE m.source_customer_id IS NULL
UNION ALL
SELECT 'interactions', i.interaction_id, i.customer_id
FROM raw_interactions i LEFT JOIN customer_identity_map m ON m.source_customer_id=i.customer_id
WHERE m.source_customer_id IS NULL;

-- Sanity checks: these should all return zero.
SELECT count(*) AS duplicate_canonical_ids
FROM (SELECT canonical_customer_id FROM unified_customers GROUP BY canonical_customer_id HAVING count(*) > 1) d;
SELECT count(*) AS negative_order_totals FROM unified_customers WHERE lifetime_order_value < 0;
SELECT count(*) AS invalid_account_counts FROM unified_customers WHERE active_account_count > account_count;

-- Inspect identity decisions requiring human review.
SELECT source_customer_id_a, source_customer_id_b, reason, run_id
FROM uncertain_matches ORDER BY source_customer_id_a, source_customer_id_b;

-- Inspect quarantined data with source lineage.
SELECT source_name, source_file, source_row_number, source_record_id, reason_code, reason_detail
FROM quarantine_records ORDER BY source_name, source_file, source_row_number;
