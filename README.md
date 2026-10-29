# Customer 360 Data Engineering Pipeline

A reproducible, local-first data engineering project that combines customer, account, order, and interaction CSV files into a unified customer view in PostgreSQL. The implementation emphasizes deterministic identity resolution, source lineage, quarantine, idempotent reruns, operational metrics, tests, and reconciliation.

## Architecture

```text
Four CSV inputs
    -> strict schema validation and row-level checks
    -> valid records upserted into PostgreSQL raw tables
    -> invalid records stored in quarantine_records with source coordinates
    -> deterministic identity resolution -> customer_identity_map
    -> SQL aggregates -> unified_customers
    -> pipeline_runs + reconciliation SQL + automated tests
```

## Requirements

- Python 3.11+
- Docker Desktop (or a local PostgreSQL 16 instance)
- Git (recommended)

## Quick start (Docker + Python)

From this directory:

```bash
# 1. Start PostgreSQL
cp .env.example .env
docker compose up -d

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# Windows PowerShell: .venv\\Scripts\\Activate.ps1

# 3. Install the project and test dependencies
python -m pip install -e '.[test]'

# 4. Generate a small, reproducible demo batch
customer360 generate --out data/sample --customers 100 --seed 42

# 5. Run the pipeline
customer360 run --input data/sample

# 6. Run unit tests
pytest -q
```

If you do not install the console entry point, run commands with `PYTHONPATH=src python -m customer360.cli ...`. The default connection string is in `.env.example`; change credentials for any non-local deployment. Never commit `.env` or production credentials.

## Generate a larger batch

```bash
customer360 generate --out data/large --customers 100000 --seed 42
customer360 run --input data/large
```

The generator is deterministic for a fixed seed. It includes duplicate customer identities, missing optional contact values, ambiguous shared phones, a deliberately invalid customer, a negative order amount, an invalid customer reference, and a duplicate interaction ID. `--no-edge-cases` disables deliberately injected invalid rows.

## Data dictionary

All identifiers are strings from the source. Timestamps are parsed as ISO-8601 and stored as PostgreSQL `TIMESTAMPTZ` in UTC. Monetary values are `NUMERIC`, not floating-point.

| Input | Grain / primary key | Required fields | Important rules |
|---|---|---|---|
| `customers.csv` | One source customer / `customer_id` | `customer_id`, `name`, and at least one of email or phone | Email/phone are normalized for matching; `updated_at` optional |
| `accounts.csv` | One account / `account_id` | account ID, customer ID, account type, status | Customer reference must exist in current or previously ingested raw customers |
| `orders.csv` | One order / `order_id` | order ID, customer ID, numeric amount, currency, ISO timestamp | Amount must be non-negative; currency is uppercased |
| `interactions.csv` | One interaction event / `interaction_id` | event ID, customer ID, channel, event type, ISO timestamp | Channel and event type are lowercased |

### Target tables

- `raw_customers`, `raw_accounts`, `raw_orders`, `raw_interactions`: accepted source records plus `source_file`, `source_row_number`, `source_hash`, and `last_seen_run_id`.
- `customer_identity_map`: one row per source customer ID and its canonical UUID, match rule, and lineage.
- `unified_customers`: one row per canonical customer with account, order, and interaction aggregates.
- `quarantine_records`: rejected row payload and reason code, linked to source file and row number.
- `source_record_history`: PostgreSQL triggers preserve old/new row payloads when a source record with the same key changes content; identical reruns do not create history entries.
- `uncertain_matches`: pairs that share a phone but have conflicting email values and therefore are not merged automatically.
- `pipeline_runs`: run ID, input batch hash, start/end time, status, counts, and failure reason.
- `v_reconciliation`: quick counts for accepted raw rows and quarantined rows.

## Deterministic identity rules

1. Trim and case-fold email addresses; exact normalized email matches are strong matches.
2. Normalize phone numbers to digits. Exact phone can link a record only if that phone is associated with at most one distinct non-empty email. A record with a blank email can join that group.
3. If the same phone is associated with conflicting non-empty emails, do not merge based on phone; create an `uncertain_matches` review record.
4. Names alone never merge customers.
5. Canonical UUIDs are UUIDv5 values based on the normalized email, otherwise normalized phone, otherwise source customer ID. This is deterministic and stable for a given identity token. If a person's identity token changes (for example, email changes and no safe phone match exists), this implementation does not infer that it is the same person.
6. For merged names, prefer the record with the newest `updated_at`; ties are resolved by source customer ID.

These rules deliberately favor precision over recall. Human review is required for ambiguous cases; there is no fuzzy matching or machine-learning model.

## Idempotency, retry, and backfill

- Raw source tables use source primary keys and `INSERT ... ON CONFLICT DO UPDATE`, so reprocessing the same source records does not duplicate them.
- The unified output is rebuilt from the retained raw tables in a transaction. Aggregates are recalculated rather than incremented, preventing duplicate totals on reruns.
- Every attempt gets a unique `run_id`; identical input files have the same SHA-256 `batch_id`.
- Validation failures are stored in quarantine. A schema mismatch or other batch-level error marks the run failed and is re-raised.
- This is an upsert-oriented snapshot/append design, not a deletion-aware CDC system. Removing a row from a later CSV does not delete it from raw storage. For a true full-snapshot replacement, implement a source snapshot marker and transactional delete/reconcile strategy before using it in production.
- A backfill can be rerun with the same IDs. Source ID collisions update existing records; operators should treat a changed source record with the same ID as a correction.

## Tests and evidence

Run `pytest -q` for unit tests covering normalization, deterministic matching, ambiguous matches, name-only non-matches, reproducible data generation, missing fields, duplicate keys, schema drift, empty files, and invalid timestamps. PostgreSQL end-to-end execution requires Docker/local PostgreSQL and the installed `psycopg` dependency.

After a run, inspect `outputs/latest_run.json`, then execute `sql/reconciliation.sql` using `psql` or a SQL client. Expected invariants include: each raw customer has an identity-map row; no child records lack an identity mapping; canonical customer IDs are unique in `unified_customers`; and active account count does not exceed total account count.

## Performance and optimization

The pipeline records elapsed wall-clock time in the run report. The synthetic generator supports 100,000+ customer rows. The main optimization in this implementation is aggregating accounts, orders, and interactions with grouped SQL queries rather than running three queries per customer. Indexes are created for canonical customer lookup and normalized email lookup. Benchmark on your machine and report observed throughput instead of claiming a fixed runtime.

## Known limitations / next steps

- No fuzzy matching, survivorship approval workflow, or identity merge/unmerge UI.
- Current customer identity mapping is recomputed from all retained raw customer records each run; very large continuously updated datasets may need incremental mapping and change history.
- Currency values are not converted; sums are only meaningful when the input currency is consistent. Add currency-aware aggregates before mixing currencies.
- Source schemas are strict: unexpected columns fail fast, preventing silent schema drift.
- For production, add structured log export, alerting, secret management, migrations, retention policies, and integration tests against a disposable PostgreSQL database.

## Data dictionary, trade-offs, and benchmark

- Detailed field-level definitions: [`docs/data_dictionary.md`](docs/data_dictionary.md)
- Design decisions and recovery limitations: [`docs/design_tradeoffs.md`](docs/design_tradeoffs.md)
- Validate/benchmark CSV processing independently of PostgreSQL:

```bash
PYTHONPATH=src python scripts/benchmark.py --customers 100000 --seed 42 --out data/benchmark
```

This benchmark measures generation and CSV validation separately from the full database load. For an end-to-end measurement, use the `elapsed_seconds` field emitted by `customer360 run` and retain the report with the machine specifications.

An optional PostgreSQL integration test checks that two identical runs preserve unified customer counts, order counts, totals, and quarantine counts. Run it against a **disposable test database only**:

```bash
TEST_DATABASE_URL=postgresql://customer360:customer360@localhost:5433/customer360_test pytest -q tests/test_postgres_integration.py
```

The integration test truncates the project tables before execution. Do not point it at a database containing data you need to keep.
