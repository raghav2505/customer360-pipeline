"""Benchmark CSV parsing/validation separately from the full database pipeline."""
import argparse, json, time
from pathlib import Path
from customer360.generator import generate, SCHEMAS
from customer360.pipeline import read_csv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--customers", type=int, default=100000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default="data/benchmark")
    args = p.parse_args()
    generated = generate(args.out, args.customers, args.seed)
    start = time.perf_counter()
    totals = {"accepted": 0, "rejected": 0, "rows": 0}
    for source in SCHEMAS:
        good, bad, total = read_csv(Path(args.out) / f"{source}.csv", source)
        totals["accepted"] += len(good); totals["rejected"] += len(bad); totals["rows"] += total
    elapsed = time.perf_counter() - start
    report = {"customers_requested": args.customers, "generated_rows_by_source": generated,
              "validation_totals": totals, "validation_elapsed_seconds": round(elapsed, 3),
              "rows_per_second": round(totals["rows"] / elapsed, 1) if elapsed else None,
              "note": "This measures CSV validation only, not PostgreSQL load/publish time."}
    print(json.dumps(report, indent=2))

if __name__ == "__main__": main()
