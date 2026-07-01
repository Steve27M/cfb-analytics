# DE Pipeline Principles — a working checklist

A digest of practices distilled from the reference library, grouped by concern.
This is the *why* behind the repo's non-negotiables. Treat each `[ ]` as a
check to clear, not prose to admire. Citations are by chapter/section so you can
go read the source.

Sources:
- **FDE** — Reis & Housley, *Fundamentals of Data Engineering*
- **DQF** — Moses, Gavish & Vorwerck, *Data Quality Fundamentals*
- **RTA** — Needham, *Building Real-Time Analytics Systems*

---

## 1. Ingestion

The DE lifecycle is generation → ingestion → transformation → serving, wrapped by
undercurrents: security, data management, DataOps, orchestration, software
engineering. (FDE, ch. 2)

- [ ] **Decide bounded vs. unbounded and the frequency up front.** Batch, micro-
  batch, and streaming are points on a continuum; pick deliberately, don't drift.
  (FDE, ch. 7 — "Bounded Versus Unbounded", "Frequency")
- [ ] **Prefer insert-only / append over in-place mutation at the raw layer.** An
  immutable, append-only bronze gives you history and lets you replay/reprocess.
  (FDE, ch. 5 — "Insert-Only"; ch. 6 — "Replay")
- [ ] **Ingestion is idempotent.** Re-running an extract for the same window must
  not duplicate rows. "Even if the system guarantees exactly-once delivery, a
  consumer might fully process a message but fail right before acknowledging…
  an idempotent system handles this gracefully." (FDE, ch. 5 — "Idempotent")
- [ ] **Snapshot vs. differential extraction is a conscious choice.** Differential
  (incremental) is cheaper but needs a reliable watermark/cursor; full snapshots
  are simpler and self-healing. (FDE, ch. 7 — "Snapshot or Differential Extraction")
- [ ] **CDC over polling when you need low-latency change history.** Log-based CDC
  reads the database log rather than querying the table. (FDE, ch. 5 / RTA, ch. 7)
- [ ] **Have a dead-letter path.** Events that can't be parsed/validated get routed
  to a dead-letter queue so they don't block the rest of the stream and can be
  diagnosed. (FDE, ch. 7 — "Error Handling and Dead-Letter Queues")
- [ ] **Plan the backfill before you need it.** "If the source goes down, plan to
  backfill the lost data once it is back online." A backfill you didn't design is
  a backfill that duplicates. (FDE, ch. 7)

## 2. Transformation

- [ ] **ELT, not ETL-in-flight, for the warehouse.** Land raw, transform in the
  engine; keep raw recoverable. (FDE, ch. 7 — "ETL Versus ELT")
- [ ] **One grain per model; model the grain explicitly.** Conceptual → logical →
  physical; normalize deliberately, denormalize for serving. (FDE, ch. 8 —
  "Data Modeling", "Techniques for Modeling Batch Analytical Data")
- [ ] **Incremental models declare a `unique_key` / partition predicate** so a
  re-run merges instead of appends. Idempotency is a property of the write, not
  a hope. (FDE, ch. 7; mirrors dbt incremental semantics)
- [ ] **Materialized transformations are deterministic.** Given the same bronze
  partition, silver/gold rebuild identically. No `current_timestamp()` baked into
  business logic, no nondeterministic ordering driving results. (FDE, ch. 8)
- [ ] **Separate business logic from glue code** so the logic is unit-testable on
  tiny fixtures. (DQF, ch. 5 — "Unit testing")

## 3. Data Quality & Observability

The **six data-quality dimensions** to test against: accuracy, completeness,
consistency, timeliness, validity, uniqueness. (DQF, ch. 1 & ch. 3 — checks like
null values, freshness, distribution, uniqueness, validity ranges)

The **five pillars of data observability**: *freshness, volume, distribution,
schema, lineage*. Monitor all five. (DQF, ch. 4 & ch. 5 — "five key pillars:
freshness, volume, distribution, schema, and lineage")

- [ ] **Test data, not just code.** Every model gets DQ tests: not_null + unique on
  the grain key, accepted_values for enums, relationships for FKs. (DQF, ch. 3 —
  dbt / Great Expectations / Deequ tests)
- [ ] **Freshness:** is the data as up-to-date as the SLA requires? Detect stale
  partitions, not just empty ones. (DQF, ch. 4 — "Monitoring for Freshness")
- [ ] **Volume:** row counts that crater or balloon are incidents. (DQF, ch. 4)
- [ ] **Distribution:** null rates, ranges, and value mix should sit in expected
  bands; drift is a signal. (DQF, ch. 4 — "Understanding Distribution")
- [ ] **Schema:** a hidden schema change breaks downstream — detect and version it.
  (DQF, ch. 4 — "Building Monitors for Schema and Lineage")
- [ ] **Lineage:** maintain field-level lineage so root-cause analysis is minutes,
  not days. (DQF, ch. 7 — "Building End-to-End Field-Level Lineage")
- [ ] **Use the right test type.** Unit (tiny fixtures, logic), functional
  (validation/integrity on large sets, pre-analytics), integration (fake data
  through the whole pipeline before prod). (DQF, ch. 5)
- [ ] **Install circuit breakers.** A failing DQ check halts the run rather than
  publishing bad data downstream. (DQF, ch. 3 — "Installing Circuit Breakers")

### SLAs / SLOs / SLIs for data (DQF, ch. 5)
- [ ] **SLI** = the number you measure (e.g., % of partitions fresh within 1h).
- [ ] **SLO** = the target for that SLI (e.g., 99% fresh, 95% of the time).
- [ ] **SLA** = the promise to consumers + consequence for missing the SLO.
- [ ] Track **TTD** (time to detection) and **TTR** (time to resolution) per incident.

## 4. Orchestration / DataOps

DataOps applies Agile + DevOps + lean to data: automation, observability,
incident response. It is cultural before it is tooling. (FDE, ch. 2 — "DataOps")

- [ ] **Pipelines are code in an orchestrator** (Dagster assets), version-controlled
  and reviewable — not cron + scripts. (FDE, ch. 2 — "Orchestration")
- [ ] **Backfills are first-class.** The orchestrator should backfill a DAG/asset
  for a historical window safely (idempotent writes make this true). (FDE, ch. 2)
- [ ] **Scheduler SLAs catch silent slowness** — a task that runs long is a visible
  SLA miss, with a callback. (DQF, ch. 3 — "Scheduler SLAs")
- [ ] **Incident management is a routine, not heroics:** detection → response →
  root-cause → resolution → blameless postmortem. (DQF, ch. 6)
- [ ] **CI runs on every change to pipeline code** (lint, types, dbt build, freshness)
  before merge. (FDE, ch. 2 — DataOps; ch. 4)

## 5. Streaming

- [ ] **Know your delivery semantics.** At-least-once can deliver duplicates;
  exactly-once is hard and still needs idempotent consumers to be safe. Design
  the consumer to be idempotent regardless. (FDE, ch. 5 — "Messages and Streams")
- [ ] **Handle late-arriving data with watermarks.** A watermark is the threshold a
  window uses to decide what's "late"; data older than the watermark is
  late-arriving and must be handled explicitly. (FDE, ch. 8 — "Watermarks")
- [ ] **Distinguish event time from ingestion/processing time.** Assuming they're
  equal yields wrong time-series results. (FDE, ch. 5 — "Types of Time"; ch. 7)
- [ ] **Replay is your reprocessing mechanism.** Retain stream data long enough to
  replay a historical range when you change downstream logic. (FDE, ch. 6 — "Replay")
- [ ] **Use a schema registry to version event schemas;** route bad events to a DLQ.
  (FDE, ch. 7 — "Schema Evolution")
- [ ] **Serving layer ≠ stream processor ≠ warehouse.** For user-facing real-time
  analytics, a purpose-built serving store (e.g., Pinot) handles high-QPS,
  low-latency reads a warehouse can't. (RTA, ch. 5; upserts in serving — RTA, ch. 9)

## 6. Governance / Security

- [ ] **Principle of least privilege.** Give each user/service the minimum access
  for the minimum time. Don't grant full database access. (FDE, ch. 10; ch. 9)
- [ ] **No writes to source/prod from the pipeline.** Read replicas / read-only
  roles for exploration. (FDE, ch. 10 — "Active Security")
- [ ] **Encrypt in flight and at rest;** anything over the public internet is
  encrypted. (FDE, ch. 10 — "Encryption")
- [ ] **PII/sensitive data is filtered, masked, or tokenized** and never logged.
  Know where it lives (catalog/lineage) so you can govern it. (FDE, ch. 9–10)
- [ ] **Treat data as a product** with an owner, an SLA, and a contract — that is
  what earns downstream trust. (DQF, ch. 8 — "Treating Your Data Like a Product")
- [ ] **A data catalog + lineage make governance enforceable**, not aspirational.
  (DQF, ch. 2 & ch. 8; FDE, ch. 6 — "Data Catalog")

---

### The five sharpest invariants (memorize these)
1. **Idempotent writes** — re-running never duplicates. (FDE, ch. 5 & 7)
2. **Bronze/raw is immutable; never write to source/prod.** (FDE, ch. 6 & 10)
3. **Schema contracts are versioned, not silently edited.** (DQF, ch. 4; FDE, ch. 7)
4. **Every model has DQ tests; every served table has freshness + volume checks.**
   (DQF, ch. 3 & 4)
5. **PII never in logs; least privilege everywhere.** (FDE, ch. 9–10)
