"""Deterministic customer identity resolution; no probabilistic/fuzzy merges."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID, uuid5, NAMESPACE_URL
import re


def normalize_email(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return value.strip().casefold()


def normalize_phone(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def canonical_uuid(token: str) -> UUID:
    """Stable UUID for an identity token; identical tokens yield identical IDs."""
    return uuid5(NAMESPACE_URL, f"customer360:{token}")


def resolve_customers(customers: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Return source_id -> resolution and pairs needing human review.

    Rules:
    1. Exact normalized email is a strong match.
    2. Exact normalized phone can match records only when that phone maps to
       at most one distinct non-empty email. Blank-email records may join it.
    3. A phone associated with multiple distinct emails is ambiguous: do not
       merge via phone and emit pairwise review flags.
    4. Names alone never trigger a merge. Isolated records use phone, email,
       or source ID as a deterministic identity token in that order.
    """
    by_id = {str(c["customer_id"]): c for c in customers}
    ids = sorted(by_id)
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Deterministic representative, independent of input row order.
            parent[max(ra, rb)] = min(ra, rb)

    emails: dict[str, list[str]] = defaultdict(list)
    phones: dict[str, list[str]] = defaultdict(list)
    email_by_id: dict[str, str | None] = {}
    phone_by_id: dict[str, str | None] = {}
    for sid, c in by_id.items():
        e, p = normalize_email(c.get("email")), normalize_phone(c.get("phone"))
        email_by_id[sid], phone_by_id[sid] = e, p
        if e:
            emails[e].append(sid)
        if p:
            phones[p].append(sid)

    for members in emails.values():
        for sid in sorted(members)[1:]:
            union(sorted(members)[0], sid)

    uncertain: list[dict] = []
    for phone, members in sorted(phones.items()):
        distinct_emails = sorted({email_by_id[s] for s in members if email_by_id[s]})
        if len(distinct_emails) > 1:
            for i, a in enumerate(sorted(members)):
                for b in sorted(members)[i + 1:]:
                    if email_by_id[a] != email_by_id[b] and (email_by_id[a] or email_by_id[b]):
                        uncertain.append({"source_customer_id_a": a, "source_customer_id_b": b,
                                          "reason": f"shared phone {phone} but conflicting email values"})
            continue
        sorted_members = sorted(members)
        for sid in sorted_members[1:]:
            union(sorted_members[0], sid)

    groups: dict[str, list[str]] = defaultdict(list)
    for sid in ids:
        groups[find(sid)].append(sid)

    result: dict[str, dict] = {}
    for members in groups.values():
        members = sorted(members)
        group_emails = sorted({email_by_id[s] for s in members if email_by_id[s]})
        group_phones = sorted({phone_by_id[s] for s in members if phone_by_id[s]})
        if group_emails:
            token, rule = f"email:{group_emails[0]}", "exact_email"
        elif group_phones:
            token, rule = f"phone:{group_phones[0]}", "exact_phone_or_blank_email"
        else:
            token, rule = f"source_customer_id:{members[0]}", "source_id_fallback"
        cid = canonical_uuid(token)
        # Name chosen by newest valid updated_at; ties resolved by source ID.
        def rank(sid: str):
            raw = by_id[sid].get("updated_at") or ""
            try:
                stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                stamp = float("-inf")
            return (stamp, sid)
        chosen = sorted(members, key=rank, reverse=True)[0]
        for sid in members:
            result[sid] = {
                "canonical_customer_id": cid,
                "match_rule": rule if len(members) > 1 else ("exact_email" if email_by_id[sid] else "exact_phone_or_blank_email" if phone_by_id[sid] else "source_id_fallback"),
                "customer_name": (by_id[chosen].get("name") or "").strip() or None,
                "email_normalized": group_emails[0] if group_emails else None,
                "phone_normalized": group_phones[0] if len(group_phones) == 1 else None,
                "source_customer_ids": members,
            }
    return result, uncertain
