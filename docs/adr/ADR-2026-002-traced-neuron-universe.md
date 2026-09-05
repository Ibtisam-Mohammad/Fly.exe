# ADR-2026-002: Traced-neuron runtime universe

Status: accepted

```yaml
decision_id: ADR-2026-002
date: 2026-09-04
changes_assumptions: [DATA-01, DATA-02, DATA-04]
old_decision: Treat the official connectome-weights artifact as if every body were a curated MaleCNS neuron.
new_decision: Preserve the all-segment artifact unchanged, but build the default runtime derivative from annotation status Traced; record every excluded segment edge and contact.
reason: The official weight table is a graph of all segmentation bodies, whereas the embodied model requires a declared biological neuron universe.
primary_sources:
  - https://male-cns.janelia.org/download/
alternatives_tested: [all-segment graph, all-annotation graph, Traced+Assign+Anchor graph]
validation_effect: Defines the V0 runtime derivative after count, motif, cross-connectome, annotation-canary, and status-sensitivity checks pass.
approved_by: project-owner via accepted V0 implementation plan
```

## Evidence observed locally

- The official aggregate table contains 151,856,684 segment-pair rows.
- The annotation file contains 211,577 unique bodies.
- Status counts are: Traced 165,122; Assign 1,832; Anchor 611; Orphan 15,925; Glia 11,864; Unimportant 10,751; missing status 5,472.
- Restricting both endpoints to Traced bodies retains 25,563,197 directed aggregate edges.
- The derivative manifest records 126,293,487 excluded segment-pair rows and 187,808,197 excluded contacts.

The completed sensitivity audit found that expanding `Traced` to
`Traced+Assign+Anchor` adds 2,443 annotation bodies (1.48%), 60,281 edges (0.24%),
and 149,409 contacts (0.12%) relative to the traced runtime graph. All ten fixed
sensorimotor annotation canaries are uniquely `Traced` and retain their expected
type, superclass, and side. The selected canary subgraph retains six internal edges
and 20 contacts.

`Traced` is therefore accepted as the production neural-body universe. `Assign` and
`Anchor` remain explicit sensitivity alternatives, not silently discarded source
data. This is a body-universe selection, not a synaptic-strength or weak-edge
threshold; the all-segment source and every excluded-row count remain checksum-locked
and recoverable.
