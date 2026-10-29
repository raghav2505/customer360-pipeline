from __future__ import annotations
import argparse, json, logging, os
from pathlib import Path
from dotenv import load_dotenv
from .generator import generate
from .pipeline import run_pipeline


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="customer360", description="Unified customer data pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate reproducible synthetic CSVs")
    gen.add_argument("--out", default="data/sample")
    gen.add_argument("--customers", type=int, default=100)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--no-edge-cases", action="store_true")
    run = sub.add_parser("run", help="run the pipeline")
    run.add_argument("--input", default="data/sample")
    run.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command == "generate":
        print(json.dumps(generate(args.out, args.customers, args.seed, not args.no_edge_cases), indent=2)); return
    if not args.database_url:
        parser.error("Set DATABASE_URL in .env or pass --database-url")
    report = run_pipeline(args.database_url, args.input)
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/latest_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__": main()
