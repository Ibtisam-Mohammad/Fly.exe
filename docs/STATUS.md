# Implementation status

Status date: 2026-09-07

## Implemented

- Dedicated Ubuntu 24.04 WSL2 distribution `FlyBrain` at `D:\WSL\FlyBrain`, with data, environments, and compiler caches under `/srv/flybrain-data`.
- Verified 8 GiB WSL swap at `D:\WSL\FlyBrain\wsl-swap.vhdx`; the obsolete `F:` swap was removed only after the new device was active.
- Python 3.12 production environment with FlyGym 2.1.0, MuJoCo 3.9.0, Brian2 2.10.1, and pinned GeNN/PyGeNN 5.4.0.
- CUDA 12.0 compilation and execution on the RTX 3060; a GeNN LIF smoke model advances on device 0.
- GPL project and reproducible Python package foundation.
- Machine-readable assumption and dataset registries.
- Typed, unit-carrying neural/sensory/motor interface frames.
- Causal multi-rate scheduler with a one-coupling-cycle actuator delay.
- Streaming official-artifact downloader with local immutable checksums and pinned GCS object identities.
- Windows-host download supervisor that keeps WSL attached, resumes partial HTTP ranges, and
  requires a complete full-profile checksum validation before declaring completion.
- Aggregate connectome importer with reversible `uint64` body IDs and `uint32` dense IDs.
- NumPy reference neural engine for interface tests and a small engineering circuit.
- Sparse small-circuit LIF oracle that requires explicit functional edge signs.
- Deterministic three-neuron LIF parity harness across NumPy, Brian2 2.10.1, and direct
  float32 PyGeNN 5.4.0; all 14 ordered spikes match within the 100-microsecond gate.
- Executable Shiu transmitter-only sign regression with named zero, excitatory, inhibitory,
  and seeded-balanced unresolved-sign policies. None is the physiological default.
- Pinned Shiu et al. FlyWire v630 repository and 4.5-GB archived output dataset, including
  source MD5/local SHA-256 identity and a resumable-download repair for ignored HTTP ranges.
- Figure 5g JON-F-to-aBN1 published-output analysis reproduction and an evidence-backed
  FlyWire-to-MaleCNS crosswalk. The transferred circuit resolves 41 neurons and 129 edges.
- `flysim benchmark circuit --experiment shiu-antennal-grooming`, with NumPy, Brian2 and
  direct PyGeNN execution plus cell-type, connectivity, weight, weak-edge and sign controls.
- Kinematic body/world engine for the first controller-only storyboard.
- Eon-like engineering state machine and causal ablation hooks.
- Run manifests, traces, validation reports, deterministic replay, and MP4 rendering.
- CLI surface for data, benchmarks, runs, rendering, and validation.
- Checksum-locked official MaleCNS starter profile (annotations, transmitter predictions, body statistics, and aggregate segment weights).
- Accepted `DATA-04` traced-neuron derivative: 165,122 bodies and 25,563,197 directed aggregate edges, with every excluded all-segment edge/contact counted in its manifest.
- Measured GeNN structural load tests at 1%, 10%, and 100%; the full graph used a 7,165 MiB GPU delta and left 3,775 MiB free during the measurement.
- Controller-only NeuroMechFly baseline: 4,000 MuJoCo steps at 500 microseconds, deterministic 2-second video, and a separate `P/E` manifest.
- Eon-like causal engineering storyboard with deterministic trace, ablation tests, and MP4; it remains a placeholder neural circuit.
- Checksum-locked seven-artifact MaleCNS v1.0 flat-connectome profile with source byte counts,
  SHA-256 hashes, Feather schemas, and pinned GCS generation/ETag/MD5/CRC32C identities.
- Lossless contact derivative covering 357,489,383 points, 311,833,243 partner rows,
  151,856,684 aggregate body-pair rows, and 45,656,140 T-bar transmitter rows.
- Exact endpoint/body/kind/confidence joins, packed-point-ID bijection, polyadic fan-out,
  transmitter probability, and partner-to-aggregate reconciliation audits with zero failures.
- Two independent clean derivative rebuilds using 262,144- and 131,072-row Parquet groups.
  Both match the canonical logical content and one another; every peak RSS was below 3 GiB.
- Ten fixed 8-nm morphology canaries, body-universe sensitivity, exact annotation canaries,
  source-paper count comparisons, full confidence-threshold sensitivity, and a pinned
  MaleCNS-to-FlyWire central-brain comparison.
- Immutable V0 evidence bundle `20260906T065413Z_V0`; all twelve required gates pass.

## Not implemented or not yet validated

- The measured GeNN graph load uses zero functional weights; fitted whole-CNS neural dynamics have not been implemented or validated.
- FlyGym is proven as a controller-only baseline, but the Eon-like scenario still uses its kinematic preview body and has not been ported into NeuroMechFly.
- The current demo circuit uses semantic placeholder populations, not resolved MaleCNS body IDs.
- DNa01/DNa02, MN9, and JO-F populations resolve from official annotations. The sourced
  oDN1-to-DNg97 crosswalk now resolves MaleCNS bodies `13805` and `230783`. Ethyl-acetate
  entry neurons, sucrose entry neurons, and the grooming descending population remain unresolved.
- Özdil et al. Supplementary Data 1 is locally checksum-locked with a dataset card. It supplies
  FAFB/FlyWire aDN1-3 identities, but no direct MaleCNS body-ID crosswalk, so the grooming-DN
  gate remains unresolved rather than being filled by a name guess.
- Track B full-VNC walking is readiness-gated and cannot be claimed.
- No cellular, synaptic, circuit, brain-wide, motor-interface, embodied, behavioral, or
  generalization tier has passed. V0 does not validate functional dynamics.
- The first Shiu transfer preserves the rising frequency-response direction but overpredicts
  response amplitude. NumPy-to-GeNN passes the 0.1-ms gate; the transferred Brian2 comparison
  fails the 1% rate gate at 9.09%, and the mapped `CB0496` silencing population is absent from
  MaleCNS annotations. Stage 1 therefore remains active and no V3 evidence is awarded.

Detailed structural evidence: [V0 Structural](evidence/V0_STRUCTURAL.md),
[full flat-connectome profile](evidence/FULL_PROFILE_INTEGRITY.md), and
[morphology canaries](evidence/MORPHOLOGY_CANARIES.md). Numerical implementation evidence:
[LIF backend parity](evidence/LIF_BACKEND_PARITY.md) and
[transmitter-only sign control](evidence/TRANSMITTER_SIGN_CONTROL.md). First Stage 1 experiment:
[Shiu antennal-grooming transfer](evidence/STAGE1_SHIU_GROOMING.md).

## Measured foundation results

| Gate | Result |
|---|---:|
| Official all-segment aggregate rows | 151,856,684 |
| Official point rows | 357,489,383 |
| Official partner/contact rows | 311,833,243 |
| Official presynaptic/T-bar rows | 45,656,140 |
| Accepted traced neuron bodies | 165,122 |
| Retained traced-to-traced edges | 25,563,197 |
| Runtime graph storage | 294 MB |
| V0 evidence gates | 12 of 12 passing |
| Automated tests | 55 passing |

The GPU measurements are topology-allocation results, not biological-time performance for fitted neural dynamics. `DATA-04` and [ADR-2026-002](adr/ADR-2026-002-traced-neuron-universe.md) are accepted; Assign/Anchor and all-segment universes remain explicit sensitivity alternatives.

| GeNN structural scale | Edges | GPU delta | Load | One 0.1 ms step host call |
|---:|---:|---:|---:|---:|
| 1% | 255,632 | 205 MiB | 0.242 s | 0.171 ms |
| 10% | 2,556,320 | 788 MiB | 0.972 s | 0.180 ms |
| 100% | 25,563,197 | 7,165 MiB | 12.466 s | 0.483 ms |

The 100% model left 3,775 MiB GPU memory free during measurement, exceeding the required 1.5 GB headroom.

Highest validation tier: **V0 Structural**. It establishes dataset identity, lossless structural
transformation, selected identity/motif preservation, confidence sensitivity, and a bounded
cross-connectome comparison. It makes no physiological or behavioral claim. Stage 1 open-loop
neural validation is now the active scientific gate.
