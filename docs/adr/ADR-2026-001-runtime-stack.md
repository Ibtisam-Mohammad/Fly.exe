# ADR-2026-001: Initial local runtime and data stack

```yaml
decision_id: ADR-2026-001
date: 2026-09-04
changes_assumptions: [DATA-01, DATA-02, ND-01, BODY-01, NUM-01, VAL-01]
old_decision: Runtime, storage, body backend, compute target, odor and tolerances unresolved.
new_decision: Python 3.12; direct PyGeNN/GeNN 5.4 production neural engine; Brian2 small-circuit oracle; official Feather to Arrow/Parquet and sparse CSR derivatives; FlyGym 2.1 NeuroMechFly body; local RTX 3060; ethyl acetate first odor; preregistered normalized-error criteria.
reason: Accepted end-to-end implementation plan and local hardware audit.
primary_sources:
  - https://male-cns.janelia.org/download/
  - https://github.com/eonsystemspbc/fly-brain
  - https://github.com/NeLy-EPFL/flygym
alternatives_tested: [Eon-Python-3.10-as-production, Brian2GeNN-production, cloud-runtime]
validation_effect: Establishes Stage 0 and performance gates; does not pass a validation tier.
approved_by: project-owner
```

## Consequences

- Eon remains a separate pinned reproduction environment because its Python/NumPy stack conflicts with the production body stack.
- Full source information remains immutable; optimized graphs are reproducible derivatives.
- If the whole graph misses interactive speed, it runs offline. A reduced interactive mode is separately labelled and never substituted for a scientific run.

