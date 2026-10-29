import csv
from pathlib import Path
import pytest
from customer360.generator import SCHEMAS, generate
from customer360.pipeline import read_csv, parse_ts


def test_generator_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ca = generate(a, customers=20, seed=7)
    cb = generate(b, customers=20, seed=7)
    assert ca == cb
    for name in SCHEMAS:
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes()


def test_missing_required_field_is_quarantined(tmp_path):
    path = tmp_path / "customers.csv"
    path.write_text("customer_id,name,email,phone,updated_at\nC1,,a@example.test,123,2026-01-01T00:00:00Z\n", encoding="utf-8")
    accepted, rejected, total = read_csv(path, "customers")
    assert not accepted and total == 1
    assert rejected[0]["code"] == "invalid_record"
    assert "name" in rejected[0]["detail"]


def test_duplicate_key_within_batch_is_quarantined(tmp_path):
    path = tmp_path / "customers.csv"
    path.write_text("customer_id,name,email,phone,updated_at\nC1,One,one@example.test,,\nC1,Two,two@example.test,,\n", encoding="utf-8")
    accepted, rejected, total = read_csv(path, "customers")
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["code"] == "duplicate_key"


def test_schema_drift_fails_fast(tmp_path):
    path = tmp_path / "customers.csv"
    path.write_text("customer_id,name,email,phone,unexpected\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Schema mismatch"):
        read_csv(path, "customers")


def test_empty_input_file_is_valid_batch_component(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(",".join(SCHEMAS["orders"]) + "\n", encoding="utf-8")
    accepted, rejected, total = read_csv(path, "orders")
    assert accepted == rejected == []
    assert total == 0


def test_bad_timestamp_rejected():
    with pytest.raises(ValueError, match="invalid ISO-8601"):
        parse_ts("not-a-date")
