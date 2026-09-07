# Implementation status

Status date: 2026-09-08

## Implemented

- Dedicated Ubuntu 24.04 WSL2 distribution `FlyBrain` at `D:\WSL\FlyBrain`, with data, environments, and compiler caches under `/srv/flybrain-data`.
- Verified 8 GiB WSL swap at `D:\WSL\FlyBrain\wsl-swap.vhdx`; the obsolete `F:` swap was removed only after the new device was active.
- After streaming ingestion completed, the production WSL memory cap was raised to 16 GiB;
  current WSL reports 15 GiB usable RAM and 8 GiB swap on `D:`.
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
- Source-faithful linear state/event semantics for the 41-neuron transfer: NumPy and Brian2
  match to numerical precision, while float64 reference GeNN matches spike identity/count/rate
  and remains within the registered 0.1-ms timing step.
- All 11 Figure 5g frequencies, an explicit three-frequency `ND-04` training split, and an
  eight-frequency held-out split. The frozen global scale fails held-out activation, and that
  negative result is retained in the immutable report.
- Versioned `male-cns-cell-dynamics-v0.1` registry plus NumPy, Brian2 and PyGeNN per-edge
  type-pair scale hooks. In the first circuit, 39 JO-F bodies have class-level spiking priors
  and both `SAD093` readouts remain explicit spiking-versus-graded alternatives.
- Checksum-locked Shiu Figure 2 Supplementary Table 3 and its 106-type source population map.
  The source behavioral screen confusion matrix is reproduced exactly, and the transfer audit
  records 63 fully mapped, 38 partially mapped and 5 unresolved MaleCNS type populations.
- Frozen, label-blind Figure 2 MaleCNS screen over all 101 mapped types and 30 trials per type,
  using a bounded 2,714-neuron/258,586-edge circuit and direct batched PyGeNN. Exact,
  shuffled-connectivity, cell-type-only, uniform/randomized-weight, weak-edge, four sign-policy,
  zero-weight, and 50-microsecond timestep conditions are immutable and resumable.
- Stage 1 baseline exit gate passed: exact balanced accuracy/AUROC are both 0.8077, shuffled
  connectivity is 0.5, all states are finite, zero weights yield no MN9 response, and timestep
  classifications agree 100%.
- Kinematic body/world engine for the first controller-only storyboard.
- Eon-like engineering state machine and causal ablation hooks.
- Full-graph Track A runtime over all 165,122 traced bodies and 25,563,197 aggregate edges.
  Its exact nine-bucket/81-projection GeNN layout retains every logical edge while reducing sparse
  row padding from about 1.849 billion to 128,941,699 slots.
- Numeric Track A populations for DNa01/DNa02, DNg97, MN9, JO-F, the bilateral
  DNg62/DNge078/DNg21 grooming candidates, bilateral DM1/DM4 projection-neuron odor relays, and
  bilateral GNG588/Fdg sweet relays.
- Checksum-locked Ozdil et al. Figure 1 panel C grooming trajectory converted to a portable
  300-sample, 2.99-second, 21-signal radian derivative and replayed through FlyGym position
  actuators.
- Causal full-graph FlyGym sequence: seek, antennal contamination, groom, resume seeking, reach
  food, and initiate rostrum/haustellum extension.
- Track A acceptance matrix: all 10 preregistered seeds passed at each of three held-out food
  positions (30/30), exceeding the required 8/10 per position.
- Required Track A controls pass: contamination-input, grooming-readout, sucrose-input and MN9
  ablations block their transitions; zero-weight and shuffled-connectome controls do not complete;
  controller-only and neural-bypass conditions are recorded.
- A physical FlyGym MP4 was produced. Viewer and headless runs have identical transition identities
  and reasons; feed and completion occur 30 ms earlier in the viewer trace.
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
- Checksum-locked first Stage 2 projection-neuron physiology pack: three published DM1 passive
  model fits plus six official Gugel et al. eLife source workbooks.
- Lossless Figure 7 derivatives with 7,280 DL5 current/firing-rate rows and 24,012 unitary-EPSC
  waveform rows. The split is frozen by recorded cell: six fit recordings and five held out.
- `male-cns-cell-dynamics-v0.2` registers DM1 as a proposed reduced-compartment spiking candidate,
  preserves DM4 vPN as unresolved, and links the DM1 passive prior without promoting it to V1.
- `flysim stage2 readiness` validates four immutable artifact hashes, units, split separation,
  loss definitions, and the scientific claim boundary; the first fit contract has zero blockers.
- The first frozen Stage 2 fit has been evaluated. Its causal uEPSC kernel passes the aggregate
  baseline-corrected normalized-error gate (1.105 <= 1.2), while the steady-state LIF F-I model fails narrowly
  (1.228 > 1.2). No fitted continuous parameter lies on a search boundary.
- A checksum-gated post-freeze uEPSC feature review changes no parameter. It reports held-out peak
  amplitude, peak-time, and one-over-e decay errors and records the missing failure-probability and
  short-term-plasticity evidence that still blocks V2.

## Not implemented or not yet validated

- Track A's functional whole-graph dynamics are an explicit Shiu-style engineering regression, not
  fitted whole-CNS physiology. The Stage 2 data foundation is implemented, but fitted hybrid
  dynamics have not yet been implemented or validated.
- The v0.2 dynamics registry is an executable uncertainty and prior boundary, not a fitted hybrid
  model. Type-pair parameters remain unset and typed spiking/graded execution remains disabled.
- Track A is an offline prototype: observed throughput was 0.117 minimum and 0.169 median
  biological seconds per wall second, below the 0.5 interactive target.
- Track A is not autonomous connectome-generated behavior. It injects central DM1/DM4 and GNG588
  relays, applies a 10x entry-path gain, drives DNg97 with a 20-Hz odor-gated intent scaffold, and
  combines DNa activity with an explicit odor-gradient steering controller.
- Grooming and feeding execution use joint-position controllers. They do not preserve the complete
  biological VNC, motor-neuron, NMJ, muscle, or tendon pathway. The FlyGym body is a female-body
  prior with ideal joint actuators.
- Track B full-VNC walking is readiness-gated and cannot be claimed.
- No cellular, synaptic, circuit, brain-wide, motor-interface, embodied, behavioral, or
  generalization tier has passed. V0 does not validate functional dynamics.
- The first Shiu transfer preserves a rising frequency-response direction but overpredicts
  response amplitude with the source fallback scale. Numerical backend parity now passes.
  A preregistered global `ND-04` fit selects 0.075 mV/contact but produces zero responses on all
  eight positive held-out frequencies. The mapped `CB0496` silencing population is also absent
  from MaleCNS annotations. This remains a negative transfer result and awards no V3 evidence.
- The Figure 2 screen passes the Stage 1 baseline but fails its stronger preregistered V3
  specificity gate: the exact-graph AUROC exceeds cell-type-only by only 0.0105, below 0.05.
  Population-level topology is supported over shuffled connectivity, but individual MaleCNS
  wiring is not shown to add enough predictive value. No V1, V2, or V3 tier is awarded.
- Receptor-aware polarity, fitted type-pair conductances/kinetics/delays, tonic drive, reduced
  compartments, and held-out cellular/synaptic physiology remain Stage 2 work.
- The first Stage 2 PN model is fitted, frozen, and evaluated, but it is not accepted as a complete
  cellular/synaptic model: the F-I gate fails and feature-level uEPSC review remains pending. The
  original held-out cells are now consumed; a revised cellular family needs a new independent
  holdout. V1 and V2 remain unawarded.

Detailed structural evidence: [V0 Structural](evidence/V0_STRUCTURAL.md),
[full flat-connectome profile](evidence/FULL_PROFILE_INTEGRITY.md), and
[morphology canaries](evidence/MORPHOLOGY_CANARIES.md). Numerical implementation evidence:
[LIF backend parity](evidence/LIF_BACKEND_PARITY.md) and
[transmitter-only sign control](evidence/TRANSMITTER_SIGN_CONTROL.md). First Stage 1 experiment:
[Shiu antennal-grooming transfer](evidence/STAGE1_SHIU_GROOMING.md) and
[Shiu feeding-screen execution and review](evidence/STAGE1_SHIU_FEEDING.md). Track A engineering
evidence: [full-graph Eon-like demonstration](evidence/TRACK_A_EON_MALECNS.md).
First Stage 2 data decision and evidence boundary: [ADR-2026-004](adr/ADR-2026-004-projection-neuron-physiology-pack.md)
and [projection-neuron physiology foundation](evidence/STAGE2_PN_PHYSIOLOGY_FOUNDATION.md).

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
| Automated tests | 78 passing |

The GPU measurements are topology-allocation results, not biological-time performance for fitted neural dynamics. `DATA-04` and [ADR-2026-002](adr/ADR-2026-002-traced-neuron-universe.md) are accepted; Assign/Anchor and all-segment universes remain explicit sensitivity alternatives.

| GeNN structural scale | Edges | GPU delta | Load | One 0.1 ms step host call |
|---:|---:|---:|---:|---:|
| 1% | 255,632 | 205 MiB | 0.242 s | 0.171 ms |
| 10% | 2,556,320 | 788 MiB | 0.972 s | 0.180 ms |
| 100% | 25,563,197 | 7,165 MiB | 12.466 s | 0.483 ms |

The 100% model left 3,775 MiB GPU memory free during measurement, exceeding the required 1.5 GB headroom.

Highest validation tier: **V0 Structural**. It establishes dataset identity, lossless structural
transformation, selected identity/motif preservation, confidence sensitivity, and a bounded
cross-connectome comparison. It makes no physiological or behavioral claim. Stage 1's deliberately
simple open-loop baseline is complete; Track A is complete as an offline engineering prototype;
Stage 2 fitted neural dynamics is now active.
