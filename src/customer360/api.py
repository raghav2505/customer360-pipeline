
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")

app = FastAPI(
    title="Customer360 API",
    description="Read-only analytics API for the Customer360 data pipeline",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)



@contextmanager
def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from .env")

    with psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=5,
    ) as conn:
        yield conn


@app.get("/api/health")
def health():
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")

        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Check PostgreSQL and DATABASE_URL.",
        ) from exc


@app.get("/api/overview")
def overview():
    query = """
        SELECT
            (SELECT COUNT(*) FROM raw_customers) AS source_customers,
            (SELECT COUNT(*) FROM unified_customers) AS unified_customers,
            (SELECT COUNT(*) FROM raw_accounts) AS accounts,
            (SELECT COUNT(*) FROM raw_orders) AS orders,
            (SELECT COALESCE(SUM(amount), 0) FROM raw_orders)
                AS total_order_value,
            (SELECT COUNT(*) FROM raw_interactions) AS interactions,
            (SELECT COUNT(*) FROM quarantine_records)
                AS quarantined_records,
            (SELECT COUNT(*) FROM uncertain_matches)
                AS uncertain_matches,
            (SELECT COUNT(*) FROM pipeline_runs
                WHERE status = 'succeeded') AS successful_runs,
            (SELECT COUNT(*) FROM pipeline_runs
                WHERE status = 'failed') AS failed_runs
    """

    try:
        with get_db() as conn:
            return conn.execute(query).fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load overview metrics.",
        ) from exc


@app.get("/api/runs")
def runs(limit: int = Query(default=10, ge=1, le=100)):
    query = """
        SELECT run_id, batch_id, started_at, ended_at, status,
               input_counts, output_counts, rejected_count, error_message
        FROM pipeline_runs
        ORDER BY started_at DESC
        LIMIT %s
    """

    try:
        with get_db() as conn:
            return conn.execute(query, (limit,)).fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load pipeline runs.",
        ) from exc


@app.get("/api/reconciliation")
def reconciliation():
    try:
        with get_db() as conn:
            return conn.execute(
                """
                SELECT entity, accepted_source_rows, quarantined_rows
                FROM v_reconciliation
                ORDER BY entity
                """
            ).fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load reconciliation data.",
        ) from exc


@app.get("/api/quarantine")
def quarantine():
    query = """
        SELECT source_name, reason_code, COUNT(*) AS record_count
        FROM quarantine_records
        GROUP BY source_name, reason_code
        ORDER BY record_count DESC, source_name
    """

    try:
        with get_db() as conn:
            return conn.execute(query).fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load quarantine summary.",
        ) from exc


@app.get("/api/customers")
def customers(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    query = """
        SELECT canonical_customer_id, customer_name, email_normalized,
               phone_normalized, account_count, active_account_count,
               order_count, lifetime_order_value, interaction_count,
               last_order_at, latest_interaction_at
        FROM unified_customers
        ORDER BY lifetime_order_value DESC, customer_name
        LIMIT %s OFFSET %s
    """

    try:
        with get_db() as conn:
            return conn.execute(query, (limit, offset)).fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load unified customers.",
        ) from exc
