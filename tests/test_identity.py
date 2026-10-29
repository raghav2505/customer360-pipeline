from customer360.identity import resolve_customers, normalize_email, normalize_phone


def test_normalization():
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"
    assert normalize_phone("+91 (987)-654 3210") == "919876543210"
    assert normalize_email(" ") is None


def test_exact_email_merges_deterministically_regardless_of_input_order():
    rows = [
        {"customer_id":"C2", "name":"Ada Lovelace", "email":"ADA@example.com", "phone":"111", "updated_at":"2026-01-02T00:00:00+00:00"},
        {"customer_id":"C1", "name":"Ada", "email":"ada@example.com", "phone":"222", "updated_at":"2026-01-01T00:00:00+00:00"},
    ]
    first, _ = resolve_customers(rows)
    second, _ = resolve_customers(list(reversed(rows)))
    assert first["C1"]["canonical_customer_id"] == first["C2"]["canonical_customer_id"]
    assert first["C1"]["canonical_customer_id"] == second["C1"]["canonical_customer_id"]
    assert first["C1"]["customer_name"] == "Ada Lovelace"


def test_phone_only_match_when_no_conflicting_emails():
    rows = [
        {"customer_id":"C1", "name":"Sam", "email":"sam@example.test", "phone":"+1 555 123", "updated_at":""},
        {"customer_id":"C2", "name":"Sam S", "email":"", "phone":"1555123", "updated_at":""},
    ]
    resolved, uncertain = resolve_customers(rows)
    assert resolved["C1"]["canonical_customer_id"] == resolved["C2"]["canonical_customer_id"]
    assert not uncertain


def test_conflicting_emails_sharing_phone_are_flagged_not_merged():
    rows = [
        {"customer_id":"C1", "name":"Pat A", "email":"a@example.test", "phone":"12345", "updated_at":""},
        {"customer_id":"C2", "name":"Pat B", "email":"b@example.test", "phone":"12345", "updated_at":""},
    ]
    resolved, uncertain = resolve_customers(rows)
    assert resolved["C1"]["canonical_customer_id"] != resolved["C2"]["canonical_customer_id"]
    assert len(uncertain) == 1


def test_name_alone_never_merges():
    rows = [
        {"customer_id":"C1", "name":"Jordan Lee", "email":"", "phone":"", "updated_at":""},
        {"customer_id":"C2", "name":"Jordan Lee", "email":"", "phone":"", "updated_at":""},
    ]
    # Resolver is deliberately conservative even though validation normally rejects these rows.
    resolved, _ = resolve_customers(rows)
    assert resolved["C1"]["canonical_customer_id"] != resolved["C2"]["canonical_customer_id"]
