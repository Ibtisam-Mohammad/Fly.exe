# ADR-2026-003: Lossless bounded-memory contact storage

```yaml
decision_id: ADR-2026-003
date: 2026-09-05
changes_assumptions: [DATA-01, DATA-02, DATA-05, ND-09]
old_decision: Contact-level storage, normalization, and memory limits were not fixed.
new_decision: Preserve official Feather artifacts immutably; stream lossless normalized contacts into versioned Zstandard Parquet shards under a 3 GiB RSS budget; keep contact rows CPU-side and use only aggregate pair edges in GeNN.
reason: The official contact tables exceed WSL memory, while V0 requires coordinates, confidence, polyadic identity, and complete transmitter probabilities to remain auditable.
primary_sources:
  - https://male-cns.janelia.org/download/
alternatives_tested: [whole-table Arrow materialization, contact-level GPU graph, aggregate-only storage]
validation_effect: Enables the Stage 0 contact/polyad audit; does not itself pass V0.
approved_by: project-owner
```

## Fixed implementation parameters

- Maximum process RSS: 3 GiB under the current 8 GiB WSL limit.
- DuckDB worker threads: 2.
- Temporary directory: `/srv/flybrain-data/tmp/contact-audit`.
- Minimum free space before derivative construction: 80 GiB.
- Preserve native 65,536-row IPC input batches.
- Write 262,144-row Parquet row groups and 1,048,576-row shards.
- Normalize the three contact tables and a bounded copy of the official aggregate table used
  exclusively for exact contact-count reconciliation.
- Use Zstandard level 3, statistics, and page checksums.
- Preserve raw 8-nm voxel coordinates, stable IDs, confidence, ROI labels, polyadic
  presynaptic identity, and all transmitter probabilities.

## Consequences

The contact store is evidence and audit infrastructure, not the neural runtime graph. Any
thresholded, sampled, or body-universe-specific view is a separately manifested derivative.
An unexplained contact join or aggregate-reconciliation discrepancy blocks V0.
