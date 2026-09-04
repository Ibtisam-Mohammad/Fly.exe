# ADR-2026-002: Provisional traced-neuron runtime universe

Status: proposed; project-owner review required

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
validation_effect: Defines a provisional V0 derivative; V0 remains unpassed until count, motif, cross-release, and status-sensitivity checks pass.
approved_by: pending-project-owner
```

## Evidence observed locally

- The official aggregate table contains 151,856,684 segment-pair rows.
- The annotation file contains 211,577 unique bodies.
- Status counts are: Traced 165,122; Assign 1,832; Anchor 611; Orphan 15,925; Glia 11,864; Unimportant 10,751; missing status 5,472.
- Restricting both endpoints to Traced bodies retains 25,563,197 directed aggregate edges.
- The derivative manifest records 126,293,487 excluded segment-pair rows and 187,808,197 excluded contacts.

This is a body-universe selection, not a synaptic-strength or weak-edge threshold. The source artifact remains checksum-locked and recoverable. `Assign` and `Anchor` alternatives must be measured before this proposal is accepted as the permanent default.
