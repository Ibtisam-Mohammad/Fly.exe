# Eon showcase v1 — recorded engineering result

Date: 2026-09-12

Historical frozen-contract verdict: accepted as an engineering showcase

Current release status: withdrawn as the final showcase; archived limited preview

Scientific tier awarded: none

Execution commit: `efe5c0de0094cd81337c55deb036b08bc208320e`

## 2026-09-13 post-release correction

The matrix and hashes below are unchanged, but the original evaluator omitted a behavioural gate
already present in the run record. The hero reports 8.477 mm of net displacement during grooming
against a 2.5 mm limit. It also uses raw odour-gradient steering and central relays rather than the
DEMO-01 causal visual route. The contamination and grooming ablations are serial-sequence
dependency checks: each produces no transitions, so neither independently isolates a completed
grooming behaviour. The release contains no command-replay or graph-free controller-only
comparison and uses one food position.

For those reasons v1 is no longer the final public showcase. Its artifacts remain immutable and
reproducible as a limited integration preview. ADR-2026-020 and `eon-showcase-v2.json` define the
successor without revising this failed evidence.

## Historical recorded result

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

## Cinematic presentation artifact

The cinematic source is a separate clean-commit rerun of the already accepted hero, not a new
acceptance trial. Commit `f6e4a60b825fcd71892559085b5d413bb5917798` reproduced the exact
accepted transition signature: `GROOM` at 465,000 us, `SEEK_RESUME` at 3,465,000 us,
`FEED_INITIATION` at 5,595,000 us and `COMPLETE` at 6,600,000 us. The immutable presentation
record contains 440 trace intervals, 4,413,426 full-graph sparse spike events, and 440 complete
133-value MuJoCo poses.

Renderer commit `64a7a0bc7505fd54e749e26209a6273ac11b26a1` produced a 13.6-second,
1920 by 1080 H.264 video at 30 frames per second. The 0.25 mm red food core and engineered
1.0 mm thorax-proximity trigger halo are both visible and named. The video does not reinterpret
the trigger as physical mouth or tarsal contact.

| Cinematic file | SHA-256 |
|---|---|
| `cinematic-demo.mp4` | `97a3790ed0ab6ffb2eca3c3e49f5f6807bda67cf1b6f489ed575252792c268b7` |
| `cinematic-render-manifest.json` | `ac037ab3b77cc8ba30df2e881ca3faa4f6468a82f61623cdb0445c9aae59bc57` |
| `cinematic-source/presentation-manifest.json` | `4d2e5896fc2c0b74119196120570b7d94e951cc5f19be26b2a3ebc9724574e81` |
| `cinematic-source/trace.jsonl` | `cb46f09c4108e34ab32db705c0d39d66ba4133eeae4fa97f925c9f309d4c9427` |
| `cinematic-source/spikes.npz` | `b2cf2279fd02ad6db5fda343464f605e8b50369b41d88038a3a886394bb7a474` |
| `cinematic-source/poses.npz` | `babdce282609fca94855a177c3f362ff7b24734aa5d900513ee1ce3e48beb85e` |

## Claim boundary

Historically supported by the frozen v1 contract, and now restricted to an archived-preview label:

> A full-MaleCNS, controller-mediated, closed-loop engineering demonstration using declared
> central sensory bridges and body controllers.

Not supported: autonomous connectome-generated behaviour, topology specificity, validated neural
physiology, a biological VNC-to-muscle route, ingestion, a digital twin, or any new validation
tier. Track A's stricter grooming-displacement and throughput gates are unchanged and remain
failed.
