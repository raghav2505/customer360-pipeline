# Design and Trade-off Note

## Decisions

- **PostgreSQL over a local file database:** provides typed tables, transactional publishing, constraints, JSONB quarantine payloads, and a familiar analytical target.
- **Python CSV processing:** keeps the assignment runnable without API credentials or external source services.
- **Deterministic matching over fuzzy matching:** exact normalized email is strong evidence; phone is used only when not contradicted by multiple emails; names alone never merge people. This favors avoiding false merges over maximizing match rate.
- **UUIDv5 canonical IDs:** same identity token produces the same identifier across reruns. Identity token changes are not silently reconciled.
- **Quarantine rather than drop:** every rejected row keeps the source file, row number, raw payload, reason code, and reason detail.
- **Full output rebuild from retained raw tables:** keeps aggregate calculations idempotent and easy to reason about. Child aggregates use grouped SQL, not per-customer query loops.
- **Upsert-oriented source loading:** supports corrections and retries but does not interpret missing rows as deletions. PostgreSQL triggers retain old/new payloads in `source_record_history` when an existing source key changes.

## Limitations

The project is a strong local vertical slice, not a production MDM platform. It has no CDC offset management, deletion-aware snapshot semantics, fuzzy matching, merge approval UI, multi-currency conversion, or schema migration framework. The identity map is rebuilt from all retained customer rows on each successful run. For very large continuously changing datasets, introduce incremental identity mapping, versioned source snapshots, and explicit history tables.

## Recovery behavior

A run record is committed before processing begins. Source upserts, quarantine writes, identity mapping, unified publishing, and success status are committed in a transaction. If processing fails, that transaction rolls back and the run is marked failed separately. Re-running the same inputs is safe because raw keys are upserted and outputs are rebuilt from raw state.
