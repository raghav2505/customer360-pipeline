"""CSV -> validated PostgreSQL raw tables -> identity map -> customer 360 output."""
from __future__ import annotations
import csv, hashlib, json, logging, os, time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4
from .generator import SCHEMAS
from .identity import resolve_customers, normalize_email, normalize_phone

LOG = logging.getLogger("customer360")
REQUIRED = {
    "customers": {"customer_id", "name"},
    "accounts": {"account_id", "customer_id", "account_type", "status", "opened_at"},
    "orders": {"order_id", "customer_id", "amount", "currency", "order_ts"},
    "interactions": {"interaction_id", "customer_id", "channel", "event_type", "event_ts"},
}
ID_FIELDS = {"customers": "customer_id", "accounts": "account_id", "orders": "order_id", "interactions": "interaction_id"}
TABLES = {"customers": "raw_customers", "accounts": "raw_accounts", "orders": "raw_orders", "interactions": "raw_interactions"}


def parse_ts(value: str | None):
    if not value or not value.strip():
        raise ValueError("timestamp is required")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def read_csv(path: Path, source: str) -> tuple[list[dict], list[dict], int]:
    """Read a file; schema drift is a batch-level failure, row errors are quarantined."""
    if not path.exists():
        raise FileNotFoundError(f"Required input file not found: {path}")
    accepted, rejected = [], []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        actual = set(reader.fieldnames or [])
        expected = set(SCHEMAS[source])
        if actual != expected:
            raise ValueError(f"Schema mismatch for {source}: expected columns {sorted(expected)}, got {sorted(actual)}")
        seen_ids: set[str] = set()
        for row_num, row in enumerate(reader, start=2):
            raw = {k: v for k, v in row.items() if k is not None}
            rid = (raw.get(ID_FIELDS[source]) or "").strip()
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("malformed row: column count does not match header")
                for field in REQUIRED[source]:
                    if not (raw.get(field) or "").strip():
                        raise ValueError(f"missing required field: {field}")
                if not rid:
                    raise ValueError(f"missing required field: {ID_FIELDS[source]}")
                if rid in seen_ids:
                    raise RowError("duplicate_key", f"duplicate {ID_FIELDS[source]} within input batch")
                # Validate types and normalize values without silently changing source IDs.
                if source == "customers":
                    if not (raw.get("email") or "").strip() and not (raw.get("phone") or "").strip():
                        raise ValueError("customer must have email or phone for identity resolution")
                    raw["updated_at"] = parse_ts(raw["updated_at"]) if raw.get("updated_at", "").strip() else None
                elif source == "accounts":
                    raw["opened_at"] = parse_ts(raw["opened_at"]) if raw["opened_at"].strip() else None
                elif source == "orders":
                    try: amount = Decimal(raw["amount"])
                    except (InvalidOperation, ValueError) as exc: raise ValueError("amount must be numeric") from exc
                    if amount < 0: raise ValueError("amount must be >= 0")
                    if not raw["currency"].strip(): raise ValueError("currency is required")
                    raw["amount"] = amount
                    raw["order_ts"] = parse_ts(raw["order_ts"])
                elif source == "interactions":
                    raw["event_ts"] = parse_ts(raw["event_ts"])
                seen_ids.add(rid)
                accepted.append({"row": raw, "row_number": row_num, "source_file": path.name,
                                 "source_hash": hashlib.sha256(json.dumps({k: str(v) for k,v in raw.items()}, sort_keys=True).encode()).hexdigest()})
            except RowError as exc:
                rejected.append(quarantine_item(source, path.name, row_num, rid, exc.code, str(exc), raw))
            except (ValueError, TypeError) as exc:
                rejected.append(quarantine_item(source, path.name, row_num, rid, "invalid_record", str(exc), raw))
    return accepted, rejected, len(accepted) + len(rejected)


class RowError(ValueError):
    def __init__(self, code: str, message: str): self.code = code; super().__init__(message)


def quarantine_item(source, filename, row_number, record_id, code, detail, raw):
    return {"source": source, "filename": filename, "row_number": row_number,
            "record_id": record_id, "code": code, "detail": detail, "raw": raw}


def batch_hash(input_dir: Path) -> str:
    h = hashlib.sha256()
    for name in sorted(SCHEMAS):
        p = input_dir / f"{name}.csv"
        if not p.exists(): raise FileNotFoundError(f"Required input file not found: {p}")
        h.update(name.encode()); h.update(p.read_bytes())
    return h.hexdigest()


def initialize(conn):
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
    conn.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def run_pipeline(database_url: str, input_dir: str | Path) -> dict:
    import psycopg
    from psycopg.types.json import Jsonb
    input_dir = Path(input_dir)
    bid = batch_hash(input_dir)
    run_id = uuid4()
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    counts_in, counts_out = {}, {}
    rejected = []
    LOG.info("Starting run_id=%s batch_id=%s", run_id, bid)
    with psycopg.connect(database_url) as conn:
        initialize(conn)
        # Persist a run record separately so a failed processing transaction remains observable.
        conn.execute("INSERT INTO pipeline_runs(run_id,batch_id,started_at,status) VALUES (%s,%s,%s,'running')",
                     (run_id, bid, started)); conn.commit()
        try:
            loaded = {}
            for source in SCHEMAS:
                good, bad, total = read_csv(input_dir / f"{source}.csv", source)
                loaded[source] = good
                rejected.extend(bad)
                counts_in[source] = total
            customer_ids = {x["row"]["customer_id"] for x in loaded["customers"]}
            existing_customer_ids = {r[0] for r in conn.execute("SELECT source_customer_id FROM raw_customers").fetchall()}
            known_customer_ids = customer_ids | existing_customer_ids
            # Invalid child references are quarantined before writing to raw tables.
            for source in ("accounts", "orders", "interactions"):
                keep = []
                for item in loaded[source]:
                    ref = item["row"]["customer_id"]
                    if ref not in known_customer_ids:
                        rejected.append(quarantine_item(source, item["source_file"], item["row_number"],
                            item["row"].get(ID_FIELDS[source], ""), "invalid_reference",
                            f"customer_id {ref!r} does not exist in this input batch", {k:str(v) for k,v in item["row"].items()}))
                    else: keep.append(item)
                loaded[source] = keep

            with conn.transaction():
                # Quarantine records are durable and source-traceable. A rerun updates detail but not first-seen run.
                for q in rejected:
                    conn.execute("""INSERT INTO quarantine_records(source_name,source_file,source_row_number,source_record_id,reason_code,reason_detail,raw_record,first_seen_run_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(source_name,source_file,source_row_number,reason_code)
                        DO UPDATE SET reason_detail=EXCLUDED.reason_detail, raw_record=EXCLUDED.raw_record""",
                        (q["source"],q["filename"],q["row_number"],q["record_id"],q["code"],q["detail"],Jsonb(q["raw"]),run_id))

                raw_insert_sql = {
                    "customers": """
                        INSERT INTO raw_customers(
                            source_customer_id, name, email, phone, updated_at,
                            source_file, source_row_number, source_hash, last_seen_run_id
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(source_customer_id) DO UPDATE SET
                            name=EXCLUDED.name, email=EXCLUDED.email,
                            phone=EXCLUDED.phone, updated_at=EXCLUDED.updated_at,
                            source_file=EXCLUDED.source_file,
                            source_row_number=EXCLUDED.source_row_number,
                            source_hash=EXCLUDED.source_hash,
                            last_seen_run_id=EXCLUDED.last_seen_run_id
                    """,
                    "accounts": """
                        INSERT INTO raw_accounts(
                            account_id, customer_id, account_type, status, opened_at,
                            source_file, source_row_number, source_hash, last_seen_run_id
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(account_id) DO UPDATE SET
                            customer_id=EXCLUDED.customer_id,
                            account_type=EXCLUDED.account_type,
                            status=EXCLUDED.status, opened_at=EXCLUDED.opened_at,
                            source_file=EXCLUDED.source_file,
                            source_row_number=EXCLUDED.source_row_number,
                            source_hash=EXCLUDED.source_hash,
                            last_seen_run_id=EXCLUDED.last_seen_run_id
                    """,
                    "orders": """
                        INSERT INTO raw_orders(
                            order_id, customer_id, amount, currency, order_ts,
                            source_file, source_row_number, source_hash, last_seen_run_id
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(order_id) DO UPDATE SET
                            customer_id=EXCLUDED.customer_id, amount=EXCLUDED.amount,
                            currency=EXCLUDED.currency, order_ts=EXCLUDED.order_ts,
                            source_file=EXCLUDED.source_file,
                            source_row_number=EXCLUDED.source_row_number,
                            source_hash=EXCLUDED.source_hash,
                            last_seen_run_id=EXCLUDED.last_seen_run_id
                    """,
                    "interactions": """
                        INSERT INTO raw_interactions(
                            interaction_id, customer_id, channel, event_type, event_ts,
                            source_file, source_row_number, source_hash, last_seen_run_id
                        )
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(interaction_id) DO UPDATE SET
                            customer_id=EXCLUDED.customer_id,
                            channel=EXCLUDED.channel,
                            event_type=EXCLUDED.event_type,
                            event_ts=EXCLUDED.event_ts,
                            source_file=EXCLUDED.source_file,
                            source_row_number=EXCLUDED.source_row_number,
                            source_hash=EXCLUDED.source_hash,
                            last_seen_run_id=EXCLUDED.last_seen_run_id
                    """,
                }

                for source, items in loaded.items():
                    if not items:
                        continue

                    params = []
                    for item in items:
                        r = item["row"]
                        common = (
                            item["source_file"],
                            item["row_number"],
                            item["source_hash"],
                            run_id,
                        )

                        if source == "customers":
                            values = (
                                r["customer_id"], r["name"].strip(),
                                r["email"].strip() or None,
                                r["phone"].strip() or None, r["updated_at"],
                                *common,
                            )
                        elif source == "accounts":
                            values = (
                                r["account_id"], r["customer_id"],
                                r["account_type"].strip(), r["status"].strip(),
                                r["opened_at"], *common,
                            )
                        elif source == "orders":
                            values = (
                                r["order_id"], r["customer_id"], r["amount"],
                                r["currency"].strip().upper(), r["order_ts"],
                                *common,
                            )
                        else:
                            values = (
                                r["interaction_id"], r["customer_id"],
                                r["channel"].strip().lower(),
                                r["event_type"].strip().lower(),
                                r["event_ts"], *common,
                            )

                        params.append(values)

                    with conn.cursor() as cur:
                        cur.executemany(raw_insert_sql[source], params)

                # Resolve across all retained raw customer records, including previous successful batches.
                cur = conn.execute("SELECT source_customer_id,name,email,phone,updated_at,source_file,source_row_number FROM raw_customers ORDER BY source_customer_id")
                all_customers = [{"customer_id": a, "name": b, "email": c, "phone": d,
                                  "updated_at": e.isoformat() if e else None, "source_file": f, "source_row_number": g}
                                 for a,b,c,d,e,f,g in cur.fetchall()]
                resolutions, uncertain = resolve_customers(all_customers)

                conn.execute("DELETE FROM customer_identity_map")
                identity_params = []
                for c in all_customers:
                    sid = c["customer_id"]
                    res = resolutions[sid]
                    identity_params.append((
                        sid,
                        res["canonical_customer_id"],
                        res["match_rule"],
                        c["source_file"],
                        c["source_row_number"],
                        run_id,
                    ))

                if identity_params:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """INSERT INTO customer_identity_map(
                                source_customer_id,canonical_customer_id,match_rule,
                                source_file,source_row_number,last_seen_run_id
                            ) VALUES (%s,%s,%s,%s,%s,%s)""",
                            identity_params,
                        )

                conn.execute("DELETE FROM uncertain_matches")
                uncertain_params = [
                    (
                        u["source_customer_id_a"],
                        u["source_customer_id_b"],
                        u["reason"],
                        run_id,
                    )
                    for u in uncertain
                ]

                if uncertain_params:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """INSERT INTO uncertain_matches(
                                source_customer_id_a,source_customer_id_b,reason,run_id
                            ) VALUES (%s,%s,%s,%s)
                            ON CONFLICT(source_customer_id_a,source_customer_id_b,reason)
                            DO UPDATE SET run_id=EXCLUDED.run_id""",
                            uncertain_params,
                        )


                # Full deterministic rebuild means totals cannot double-count on rerun.
                conn.execute("DELETE FROM unified_customers")
                grouped: dict = {}
                for sid, res in resolutions.items():
                    key = res["canonical_customer_id"]
                    if key not in grouped:
                        grouped[key] = {**res, "source_customer_ids": sorted(res["source_customer_ids"])}
                # Aggregate child entities in SQL once, rather than issuing 3 queries per customer.
                account_agg = {row[0]: (row[1], row[2]) for row in conn.execute(
                    """SELECT m.canonical_customer_id, count(*), count(*) FILTER (WHERE lower(a.status)='active')
                       FROM raw_accounts a JOIN customer_identity_map m ON m.source_customer_id=a.customer_id
                       GROUP BY m.canonical_customer_id""").fetchall()}
                order_agg = {row[0]: (row[1], row[2] or Decimal("0.00"), row[3], row[4]) for row in conn.execute(
                    """SELECT m.canonical_customer_id, count(*), sum(o.amount), min(o.order_ts), max(o.order_ts)
                       FROM raw_orders o JOIN customer_identity_map m ON m.source_customer_id=o.customer_id
                       GROUP BY m.canonical_customer_id""").fetchall()}
                interaction_agg = {row[0]: (row[1], row[2]) for row in conn.execute(
                    """SELECT m.canonical_customer_id, count(*), max(i.event_ts)
                       FROM raw_interactions i JOIN customer_identity_map m ON m.source_customer_id=i.customer_id
                       GROUP BY m.canonical_customer_id""").fetchall()}

                unified_params = []
                built_at = datetime.now(timezone.utc)

                for cid, res in grouped.items():
                    source_ids = res["source_customer_ids"]
                    account_count, active_count = account_agg.get(cid, (0, 0))
                    order_count, total_value, first_order, last_order = order_agg.get(
                        cid, (0, Decimal("0.00"), None, None)
                    )
                    interaction_count, latest_interaction = interaction_agg.get(
                        cid, (0, None)
                    )

                    unified_params.append((
                        cid,
                        res["customer_name"],
                        res["email_normalized"],
                        res["phone_normalized"],
                        source_ids,
                        account_count,
                        active_count,
                        order_count,
                        total_value,
                        interaction_count,
                        first_order,
                        last_order,
                        latest_interaction,
                        built_at,
                        run_id,
                    ))

                if unified_params:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """INSERT INTO unified_customers(
                                canonical_customer_id,customer_name,email_normalized,
                                phone_normalized,source_customer_ids,account_count,
                                active_account_count,order_count,lifetime_order_value,
                                interaction_count,first_order_at,last_order_at,
                                latest_interaction_at,built_at,last_seen_run_id
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            unified_params,
                        )

                counts_out = {
                    "customers": conn.execute("SELECT count(*) FROM raw_customers").fetchone()[0],
                    "canonical_customers": conn.execute("SELECT count(*) FROM unified_customers").fetchone()[0],
                    "accounts": conn.execute("SELECT count(*) FROM raw_accounts").fetchone()[0],
                    "orders": conn.execute("SELECT count(*) FROM raw_orders").fetchone()[0],
                    "interactions": conn.execute("SELECT count(*) FROM raw_interactions").fetchone()[0],
                    "uncertain_match_pairs": len(uncertain),
                }
                conn.execute("UPDATE pipeline_runs SET ended_at=%s,status='succeeded',input_counts=%s,output_counts=%s,rejected_count=%s WHERE run_id=%s",
                    (datetime.now(timezone.utc),Jsonb(counts_in),Jsonb(counts_out),len(rejected),run_id))
            elapsed = round(time.perf_counter() - t0, 3)
            report = {"run_id": str(run_id), "batch_id": bid, "status": "succeeded", "input_counts": counts_in,
                      "output_counts": counts_out, "rejected_count": len(rejected), "elapsed_seconds": elapsed}
            LOG.info("Completed run_id=%s elapsed_seconds=%s output_counts=%s", run_id, elapsed, counts_out)
            return report
        except Exception as exc:
            conn.rollback()
            conn.execute("UPDATE pipeline_runs SET ended_at=%s,status='failed',input_counts=%s,rejected_count=%s,error_message=%s WHERE run_id=%s",
                (datetime.now(timezone.utc),Jsonb(counts_in),len(rejected),str(exc)[:2000],run_id)); conn.commit()
            LOG.exception("Pipeline failed run_id=%s", run_id)
            raise
