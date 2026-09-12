# Eon showcase v1 — recorded engineering result

Date: 2026-09-12

Verdict: accepted as an engineering showcase

Scientific tier awarded: none

Execution commit: `efe5c0de0094cd81337c55deb036b08bc208320e`

## Result

The frozen `eon-showcase-v1` matrix ran nine full-graph conditions from one clean commit:

| Group | Condition | Observed result | Contract result |
|---|---|---|---|
| Exact | seed 1 | full sequence through `COMPLETE` | pass; hero |
| Exact | seed 2 | full sequence through `COMPLETE` | pass |
| Exact | seed 3 | stopped after `FEED_INITIATION` | does not pass; two-of-three still met |
| Causal | contamination input ablated | no state transition | blocks `GROOM`; pass |
| Causal | grooming readout ablated | no state transition | blocks `GROOM`; pass |
| Causal | sucrose input ablated | stops after `SEEK_RESUME` | blocks feeding initiation; pass |
| Causal | MN9 readout ablated | stops after `SEEK_RESUME` | blocks feeding initiation; pass |
| Diagnostic | zero weight | no state transition | recorded; non-gating |
| Diagnostic | shuffled connectivity | grooming and seeking resume | recorded; non-gating |

Every run records 165,122 neurons, 25,563,197 aggregate edges, no edge threshold, a clean tree,
and the same execution commit. The acceptance report contains no failures.

## Immutable release files

| File | SHA-256 |
|---|---|
| `acceptance.json` | `ee0b515c9e3d8b7236a1d42c75af1c50fa254bb7a19c22949309e5053edec672` |
| `showcase-manifest.json` | `dd02aba525240f0649a8217003e73f90ac507958048cd766c45f3a1f541ad4ec` |
| `render-manifest.json` | `533b6e1f7f706958b28a8f740720edaa8c4109aea568f079307f9ebb6cb07c34` |
| `demo.mp4` | `7cc50aebf1382d3d8527e24e7d547e81263530658e3ef2d1ade5b201ae1b15a7` |

The MP4 independently probes as H.264, 960 by 544 pixels, 30 frames per second, 6.6 seconds,
and 93,629 bytes. Rendering happened after simulation from the immutable hero trace.

## Claim boundary

Supported:

> A full-MaleCNS, controller-mediated, closed-loop engineering demonstration using declared
> central sensory bridges and body controllers.

Not supported: autonomous connectome-generated behaviour, topology specificity, validated neural
physiology, a biological VNC-to-muscle route, ingestion, a digital twin, or any new validation
tier. Track A's stricter grooming-displacement and throughput gates are unchanged and remain
failed.
