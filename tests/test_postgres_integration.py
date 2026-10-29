"""Optional integration test; set TEST_DATABASE_URL to a disposable PostgreSQL DB."""
import os
from pathlib import Path
import pytest

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to run PostgreSQL integration test")


def test_rerun_is_idempotent():
    import psycopg
    from customer360.pipeline import run_pipeline, initialize
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(URL) as conn:
        initialize(conn)
        # This test intentionally clears project tables; only use a disposable test database.
        for table in ["unified_customers", "uncertain_matches", "customer_identity_map", "quarantine_records",
                      "raw_interactions", "raw_orders", "raw_accounts", "raw_customers", "pipeline_runs"]:
            conn.execute(f"TRUNCATE TABLE {table} CASCADE")
        conn.commit()
    first = run_pipeline(URL, root / "data" / "sample")
    with psycopg.connect(URL) as conn:
        before = conn.execute("SELECT count(*), coalesce(sum(order_count),0), coalesce(sum(lifetime_order_value),0) FROM unified_customers").fetchone()
        quarantine_before = conn.execute("SELECT count(*) FROM quarantine_records").fetchone()[0]
    second = run_pipeline(URL, root / "data" / "sample")
    with psycopg.connect(URL) as conn:
        after = conn.execute("SELECT count(*), coalesce(sum(order_count),0), coalesce(sum(lifetime_order_value),0) FROM unified_customers").fetchone()
        quarantine_after = conn.execute("SELECT count(*) FROM quarantine_records").fetchone()[0]
    assert first["status"] == second["status"] == "succeeded"
    assert before == after
    assert quarantine_before == quarantine_after


def test_source_record_history_trigger_rolls_back_safely():
    import uuid
    import psycopg
    from customer360.pipeline import run_pipeline

    root = Path(__file__).resolve().parents[1]
    run_pipeline(URL, root / "data" / "sample")

    test_hash = f"trigger-test-{uuid.uuid4().hex}"

    with psycopg.connect(URL) as conn:
        original = conn.execute("""
            SELECT source_customer_id, source_hash
            FROM raw_customers
            ORDER BY source_customer_id
            LIMIT 1
        """).fetchone()

    assert original is not None, "Expected at least one raw customer"
    customer_id, original_hash = original

    # Verify the trigger inside a transaction that always rolls back.
    with psycopg.connect(URL) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("""
                UPDATE raw_customers
                SET source_hash = %s
                WHERE source_customer_id = %s
            """, (test_hash, customer_id))

            history = conn.execute("""
                SELECT old_source_hash, new_source_hash
                FROM source_record_history
                WHERE source_record_id = %s
                  AND new_source_hash = %s
                ORDER BY history_id DESC
                LIMIT 1
            """, (customer_id, test_hash)).fetchone()

            assert history is not None, "Source history trigger did not create a record"
            assert history[0] == original_hash
            assert history[1] == test_hash

    # Confirm the test's temporary update and history row were rolled back.
    with psycopg.connect(URL) as conn:
        current_hash = conn.execute("""
            SELECT source_hash
            FROM raw_customers
            WHERE source_customer_id = %s
        """, (customer_id,)).fetchone()[0]

        persisted_history = conn.execute("""
            SELECT COUNT(*)
            FROM source_record_history
            WHERE source_record_id = %s
              AND new_source_hash = %s
        """, (customer_id, test_hash)).fetchone()[0]

    assert current_hash == original_hash
    assert persisted_history == 0
def test_failed_pipeline_run_is_recorded(tmp_path):
    import csv
    import psycopg
    from customer360.pipeline import run_pipeline

    input_dir = tmp_path / "invalid_input"
    input_dir.mkdir()

    # Create all four required files.
    # customers.csv deliberately has the wrong columns.
    files = {
        "customers.csv": ["wrong_column"],
        "accounts.csv": [
            "account_id", "customer_id", "account_type",
            "status", "opened_at"
        ],
        "orders.csv": [
            "order_id", "customer_id", "amount",
            "currency", "order_ts"
        ],
        "interactions.csv": [
            "interaction_id", "customer_id", "channel",
            "event_type", "event_ts"
        ],
    }

    for filename, columns in files.items():
        with (input_dir / filename).open(
            "w", newline="", encoding="utf-8"
        ) as f:
            writer = csv.writer(f)
            writer.writerow(columns)

    with psycopg.connect(URL) as conn:
        before = conn.execute(
            "SELECT count(*) FROM pipeline_runs"
        ).fetchone()[0]

    with pytest.raises(ValueError, match="Schema mismatch"):
        run_pipeline(URL, input_dir)

    with psycopg.connect(URL) as conn:
        after = conn.execute(
            "SELECT count(*) FROM pipeline_runs"
        ).fetchone()[0]

        failed_run = conn.execute("""
            SELECT status, error_message, ended_at
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT 1
        """).fetchone()

    assert after == before + 1
    assert failed_run is not None
    assert failed_run[0] == "failed"
    assert "Schema mismatch" in failed_run[1]
    assert failed_run[2] is not None
