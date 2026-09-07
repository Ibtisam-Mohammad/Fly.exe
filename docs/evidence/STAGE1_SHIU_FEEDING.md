# Stage 1 Shiu feeding-screen preparation

- Implementation commit: `2e909709b0c05d4f9ab023fd27693a36252bc3dc`
- Preparation report: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-feeding-screen-preparation.json`
- Preparation report SHA-256: `f32fb88863630cfcaf208b08439a2613a6605b3a7e1d610b344b530f7e4b8559`
- Validation tier awarded: **none; V0 Structural remains the project maximum**

## Source result locked

The source repository remains pinned at commit
`91bdd1e7dcf193f3e7ca5a8933497fcef63b7960`. Its primitive `sez_neurons.pickle` artifact is
checksum-locked and read by a restricted unpickler that cannot import executable globals.
The peer-reviewed Supplementary Tables workbook is locked at 2,539,037 bytes and SHA-256
`6922e16825aa0c92a28e2a634b073dcad7641e9c9283c4b9d8ee1e34e6d9b8d9`.

Supplementary Table 3 supplies the model's bilateral MN9 rates and the independent
optogenetic rostrum-extension fraction for 106 SEZ cell types. Using the paper's 50-Hz rule,
with both bilateral MN9 rates required to be positive, the local extraction reproduces the
source confusion matrix exactly:

| Source Figure 2 result | Count |
|---|---:|
| True positive | 10 |
| False positive | 1 |
| True negative | 91 |
| False negative | 4 |

This reproduces a published table and acceptance rule. It does not yet evaluate a MaleCNS
simulation.

## MaleCNS transfer boundary

The 372 FlyWire identities belonging to the 106 screened types are transferred through the
paper-author MaleCNS/FlyWire mapping. Every target label is then resolved against both the
`type` and `flywireType` fields of the traced MaleCNS annotations.

| Mapping status | Screened types |
|---|---:|
| Every source identity mapped | 63 |
| At least one, but not every, source identity mapped | 38 |
| No source identity mapped | 5 |

All 101 types with at least one crosswalk label resolve to one or more traced MaleCNS bodies.
The preparation report preserves every source identity, target label, target body ID, partial
mapping and missing mapping. It does not guess replacements.

## Next executable gate

The next step is to freeze the 101-type mapped subset and the bilateral MN9 decision rule before
running MaleCNS. Exact-graph predictions must be compared with shuffled-connectivity,
cell-type-only and sign alternatives. The optogenetic labels cannot be used for parameter
fitting; they remain the held-out biological evaluation. Until those runs complete, the
simulation status is `not-run`, Stage 1 remains active, and no V3 evidence is awarded.
