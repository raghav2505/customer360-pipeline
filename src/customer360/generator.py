"""Generate deterministic synthetic CSV inputs for demos and scale tests."""
from __future__ import annotations
import argparse, csv, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMAS = {
    "customers": ["customer_id", "name", "email", "phone", "updated_at"],
    "accounts": ["account_id", "customer_id", "account_type", "status", "opened_at"],
    "orders": ["order_id", "customer_id", "amount", "currency", "order_ts"],
    "interactions": ["interaction_id", "customer_id", "channel", "event_type", "event_ts"],
}
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def generate(out_dir: str | Path, customers: int = 100, seed: int = 42, edge_cases: bool = True) -> dict[str, int]:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows = {k: [] for k in SCHEMAS}
    for i in range(1, customers + 1):
        # Every 20th row duplicates a previous email under a new source ID.
        base_i = i - 1 if edge_cases and i % 20 == 0 else i
        email = f"person{base_i}@example.test" if not (edge_cases and i % 17 == 0) else ""
        phone_num = 7000000000 + base_i
        phone = f"+91 {phone_num}" if not (edge_cases and i % 23 == 0) else ""
        # Deliberately ambiguous shared phone: two different emails, same phone.
        if edge_cases and i in (customers - 1, customers):
            phone = "+91 7999999999"
            email = f"conflict{i}@example.test"
        rows["customers"].append({
            "customer_id": f"C{i:06d}", "name": f"Customer {base_i:06d}", "email": email,
            "phone": phone, "updated_at": (BASE_TIME + timedelta(days=rng.randint(0, 365))).isoformat()
        })
    # Valid child records reference source customer IDs; amounts and timestamps are reproducible.
    for i in range(1, max(2, customers // 2) + 1):
        cid = f"C{rng.randint(1, customers):06d}"
        rows["accounts"].append({"account_id": f"A{i:07d}", "customer_id": cid,
            "account_type": rng.choice(["checking", "savings", "credit"]),
            "status": rng.choice(["active", "closed", "pending"]),
            "opened_at": (BASE_TIME + timedelta(days=rng.randint(0, 500))).isoformat()})
    for i in range(1, customers * 2 + 1):
        cid = f"C{rng.randint(1, customers):06d}"
        rows["orders"].append({"order_id": f"O{i:08d}", "customer_id": cid,
            "amount": f"{rng.uniform(1, 2500):.2f}", "currency": "INR",
            "order_ts": (BASE_TIME + timedelta(days=rng.randint(0, 600))).isoformat()})
    for i in range(1, customers + 1):
        cid = f"C{rng.randint(1, customers):06d}"
        rows["interactions"].append({"interaction_id": f"I{i:08d}", "customer_id": cid,
            "channel": rng.choice(["email", "phone", "chat", "web"]),
            "event_type": rng.choice(["support", "sales", "complaint", "feedback"]),
            "event_ts": (BASE_TIME + timedelta(days=rng.randint(0, 600))).isoformat()})
    # Explicit negative cases: missing required field, invalid amount, invalid FK, duplicate event ID.
    if edge_cases and customers >= 5:
        rows["customers"].append({"customer_id": f"BAD{customers:06d}", "name": "", "email": "", "phone": "", "updated_at": ""})
        rows["orders"].append({"order_id": f"OBAD{customers:06d}", "customer_id": "C999999", "amount": "-3.00", "currency": "INR", "order_ts": BASE_TIME.isoformat()})
        rows["interactions"].append(dict(rows["interactions"][0]))
    counts = {}
    for name, fields in SCHEMAS.items():
        path = out / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows[name])
        counts[name] = len(rows[name])
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/sample")
    parser.add_argument("--customers", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-edge-cases", action="store_true")
    args = parser.parse_args()
    print(generate(args.out, args.customers, args.seed, not args.no_edge_cases))

if __name__ == "__main__": main()
