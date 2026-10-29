# Data Dictionary

## Input files

| File | Column | Type / format | Nullable | Rule |
|---|---|---|---|---|
| customers.csv | customer_id | string | No | Unique per source batch; source identifier |
| customers.csv | name | string | No | Non-empty display name |
| customers.csv | email | string | Yes | Trimmed and case-folded for identity matching |
| customers.csv | phone | string | Yes | Non-digits removed for matching |
| customers.csv | updated_at | ISO-8601 timestamp | Yes | Parsed to UTC; newest record wins name selection |
| accounts.csv | account_id | string | No | Primary key |
| accounts.csv | customer_id | string | No | Must reference an accepted current/prior source customer |
| accounts.csv | account_type | string | No | Source account category |
| accounts.csv | status | string | No | `active` is counted case-insensitively |
| accounts.csv | opened_at | ISO-8601 timestamp | Yes | Stored in UTC |
| orders.csv | order_id | string | No | Primary key |
| orders.csv | customer_id | string | No | Must reference an accepted current/prior source customer |
| orders.csv | amount | decimal | No | Must be numeric and >= 0 |
| orders.csv | currency | string | No | Uppercased; values are not converted |
| orders.csv | order_ts | ISO-8601 timestamp | No | Stored in UTC |
| interactions.csv | interaction_id | string | No | Primary key; duplicate within one file is quarantined |
| interactions.csv | customer_id | string | No | Must reference an accepted current/prior source customer |
| interactions.csv | channel | string | No | Lowercased |
| interactions.csv | event_type | string | No | Lowercased |
| interactions.csv | event_ts | ISO-8601 timestamp | No | Stored in UTC |

## Derived target fields

| Field | Meaning |
|---|---|
| canonical_customer_id | UUIDv5 generated from normalized identity token |
| match_rule | `exact_email`, `exact_phone_or_blank_email`, or `source_id_fallback` |
| source_customer_ids | Sorted list of source customer IDs represented by the canonical customer |
| account_count | Number of accepted account records for the canonical customer |
| active_account_count | Accepted accounts whose status is `active`, case-insensitive |
| order_count | Number of accepted order records |
| lifetime_order_value | Sum of accepted order amounts, without cross-currency conversion |
| interaction_count | Number of accepted interaction events |
| first_order_at / last_order_at | Minimum / maximum order timestamp |
| latest_interaction_at | Maximum interaction timestamp |
| source_file / source_row_number | Original input filename and CSV row number (header is row 1) |
| source_hash | SHA-256 of normalized parsed source row content |
| run_id | Unique UUID for a pipeline attempt |
| batch_id | SHA-256 of all four input files in sorted source-name order |

## Operational tables

- `pipeline_runs`: one row per attempt; `status` is `running`, `succeeded`, or `failed`.
- `quarantine_records`: row-level failures with source file, source row number, reason, and raw payload.
- `source_record_history`: old/new row payload and source hashes when an existing raw source key is corrected. Database triggers write this history automatically.
- `uncertain_matches`: current set of ambiguous identity pairs requiring review.
