# Schema v1
SQLAlchemy metadata creates users, audits, datasets, plans, traces. Natural names are unique; foreign keys reference parent entities. Each trace stores immutable JSON input snapshots. PostgreSQL persists metadata and teaching datasets; the bounded Python operators execute the plan.

Sweeps persist one threshold sweep per trace snapshot: name, trace_id, step_index, status, interval ledger JSON (cursor, intervals, published/merged results). Intervals commit one at a time so a restart resumes at the stored cursor without republishing confirmed ranges.
