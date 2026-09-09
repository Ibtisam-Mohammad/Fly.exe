# Implementation status

Status date: 2026-09-09

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
- Track A v3 acceptance matrix executed from clean commit `4a061ac` at three genuinely unused
  food positions, 10 seeds each. 29 of 30 runs complete the required sequence and all 30 clear
  the pre-groom seek floor, but **0 of 30 clear the grooming-displacement cap**, so the matrix
  does not pass. See [the Track A evidence report](evidence/TRACK_A_EON_MALECNS.md).
- All nine required Track A controls pass against criteria that can now fail, but they are not
  equally strong: five are causal ablations, one is a quantitative degradation control, one is
  an equivalence check, and two are recorded baselines whose criterion is that an artifact
  exists. The shuffled-connectome control cleared its degradation criterion by 14%: peak
  grooming readout 66.7 Hz against an allowance of 77.8 Hz.
- A physical FlyGym MP4 was produced. Viewer and headless runs have identical transition
  identities and reasons, but the last two transitions differ by 1.44 s, up from 30 ms in v2.
  The equivalence control tests the signature, not timing, so it passes while the divergence
  grew 48-fold. A rendered run is not a timing replica of a headless one.
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
- Immutable V0 evidence bundle `20260908T060641Z_V0`; all twelve required gates pass, the
  seven raw artifacts' upstream MD5 values are recomputed from local bytes, and the bundle
  pins a scoped snapshot of the `DATA-*` records rather than the mutable register. The first
  bundle, `20260906T065413Z_V0`, is withdrawn and still fails validation; see
  [ADR-2026-006](adr/ADR-2026-006-evidence-chain-repair.md).
- Runtime graph arrays are SHA-256 pinned in their manifest and verified on every load.
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
- Pinned Nanami et al. 2024 PN source at commit `c064f47da7a1f8c4e9137c09b5e327d1a38ab9f4`;
  its one 200,000-sample, 10-kHz voltage trace and protocol-analysis notebook are checksum-locked.
- `flysim data import-nanami-pn` produces a lossless float64 voltage Parquet derivative and a
  manifest that preserves the female/age/type mismatch, single-cell limit, unresolved current
  units, and source notebook's threshold-based timing reconstruction.
- Accepted ADR-2026-005 reserves the Nanami cell as an external challenge only. It cannot be used
  for fitting, model-family selection, or retrospective acceptance-threshold changes.
- A second Stage 2 contract freezes a 100-us ramp-aware adaptive LIF family before external
  scoring and excludes the consumed Gugel held-out cells. Its four artifact hashes pass readiness.
- The fitted active-cell object is now an empirical two-draw PN-family distribution rather than
  one identical neuron. On its two training cells it reduces RMSE from 15.528 Hz for the original
  shared steady-state LIF to 7.630 Hz. This is training evidence only; the external cell is unscored.
- A separately frozen condition-shift contract then opened four previously excluded chronic-
  exposure DL5 cells exactly once. The adaptive population mean achieves 13.174 Hz held-out RMSE
  versus a 12.376 Hz training-cohort biological baseline, normalized ratio 1.064, and passes the
  preregistered 1.2 F-I sub-gate. The result remains below a complete V1 tier.
- A separately preregistered 100-to-50-us review preserves that sub-gate: normalized ratio changes
  from 1.064444 to 1.064332 and all predictions remain finite. No parameters or limits changed.

- The Nanami stimulus-unit question is closed. The step levels recorded as the in vivo protocol
  are the in-silico PQN model's dimensionless amplitudes; the real amplitudes are never published
  and are irrecoverable. The reserved PN trace is retired as a scoring source, so the planned
  sealed evaluation will not happen.
- The project has its first measured cellular observables in physical units. MBON-alpha1 is the
  only unit-resolved current-step protocol in any registered source and gives resting potential
  -60.354 mV, membrane time constant 32.566 ms at R squared 0.911, threshold -38.402 mV, a
  monotonic F-I of 1, 10, 17, 21 and 24 Hz at 2 to 10 pA, and an adaptation ratio of 0.749. Four
  Seki et al. 2010 LN animals give the only multi-animal distribution: resting potential median
  -50.789 mV.
- Both neural engines carry per-neuron membrane parameters. GeNN promotes eight kernel
  coefficients to per-neuron variables only when the resolution is heterogeneous, so recorded
  Track A runs are unchanged, and both engines refuse a graph containing graded-regime neurons
  because no graded transmission model is registered.

- The Stage 2 exit gate is an executable contract that reads each leg from a checksum-pinned
  artifact. One leg of four passes: the cellular F-I sub-gate, at a normalized error ratio of
  1.064 that a two-cell training mean satisfies better. Synaptic, circuit and ensemble fail,
  and Stage 2 does not exit. `stage2-exit-gate-v2` carries the review caveats.
- An independent review (ADR-2026-009) recomputed every Stage 2 number and verified every
  hash. It withdrew the ND-06 depression hypothesis for the contact-scale conflict as a
  category error, recorded the uEPSC peak-time and sign criteria as vacuous on peak-aligned
  traces and the kernel as wrong in decay and amplitude, corrected the synaptic-structure
  contract's citation and claim in a v2, and added contract-gated diagnostics that show the
  MBON07 time constant moving from 32.6 to 47.6 ms with a free asymptote and the threshold
  from -38.4 to -41.8 mV under a fraction-of-slope rule.
- The heterogeneous GeNN kernel is executed on the full graph. With the fallback set on every
  neuron it is bit-identical to the homogeneous kernel; with cell-dynamics-v0.3 the four
  MBON07 neurons drop from 68/64/65/70 to 13/13/13/13 spikes in 300 ms.
- A second one-step GeNN defect is fixed. GeNN labels a spike with the start of the integration
  interval while NumPy and Brian2 label it with the end, and the Stage 1 adapter lacked the
  correction the parity harness already had. It had been cancelling the axonal-delay defect at
  the readout, so the recorded Stage 1 parity pass came from two compensating errors. All three
  backends now agree to 1.1e-13 ms on the 41-neuron transfer, down from 0.1 ms.
- ND-04 is tested rather than asserted. Across 50 glomeruli and 265 projection neurons, contact
  number does not implement the published homeostatic matching, and the median 43 contacts per
  connection agrees with the published several-dozen estimate. The registered 0.2 mV per contact
  lies inside the 0.042 to 1.12 mV range the published unitary amplitude implies.
- The frozen unitary-EPSC kernel was scored once against preregistered numeric limits on the five
  unconsumed chronic-exposure cells. Sign and peak time pass; decay fails at 0.463 median
  fractional error against a 0.30 limit.
- Both Stage 1 circuits reproduce under the corrected code. The grooming transfer's backend
  parity improves from 0.1 ms to 1.1e-13 ms with unchanged rates and coverage; the feeding screen
  is bit-identical across all eleven variants, so both Stage 1 verdicts stand.
- No single global contact scale fits the grooming reference at both frequencies: 220 Hz needs
  about 0.083 mV per contact and 100 Hz about 0.153 mV. The physiologically derived band contains
  the second and over-predicts the first sevenfold. [ADR-2026-009](adr/ADR-2026-009-stage2-independent-review.md)
  withdrew the earlier reading that missing ND-06 short-term depression explains this: the
  reference is a static whole-brain simulation with no depression in it and the transferred
  circuit is a 41-neuron one-hop subgraph, so a mechanism absent from both cannot be what makes
  them disagree. The structural reading is under test by the bounded-path sweep below.

## Not implemented or not yet validated

- Track A's functional whole-graph dynamics are an explicit Shiu-style engineering regression, not
  fitted whole-CNS physiology. The Stage 2 data foundation is implemented, but fitted hybrid
  dynamics have not yet been implemented or validated.
- The v0.3 dynamics registry binds exactly one cell type to measured values. Against the full
  traced graph that is 4 of 165,122 neurons across 11,752 cell types, a measured fraction of
  0.0024%; everything else runs the Shiu-style engineering fallback, and engines report that
  fraction in run metadata. Type-pair parameters remain unset, and Stage 1 keeps execution on the
  source-faithful LIF baseline so its frozen numbers stay reproducible.
- Track A is an offline prototype. Steady-state throughput is 0.332 minimum and 0.353 median
  biological seconds per wall second, about 71% of the 0.5 interactive target; including graph load and
  GeNN model build the cold-start figure is 0.114 minimum. The previously reported 0.117/0.169
  figures were cold-start numbers presented as throughput.
- The Track A body cannot hold station while grooming. It translates a median 6.26 mm during a
  3-second bout under a zero forward command, against a 2.5 mm one-body-length cap. Separate
  probes show 2.16 mm of drift while standing under no command and 4.92 mm while grooming with
  the trajectory replay suppressed, both far above the cap. MuJoCo contact dynamics are
  nonlinear, so these are localizing probes rather than an additive breakdown, but they are
  enough to show the defect is stance station-keeping and not the replay. This blocks Track A
  acceptance and is unresolved.
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
  cellular/synaptic model: its F-I gate fails, while its uEPSC aggregate passes but lacks
  preregistered feature, failure-probability, and short-term-plasticity evidence.
- The ramp-aware adaptive replacement currently passes only an internal training comparison. Its
  chronic-condition F-I holdout sub-gate passes, but this is the same source paper and state-shifted
  cohort, and the family carries two draws against the VAL-01 requirement of five samples by four
  seeds. No projection-neuron type has a multi-animal, type-resolved measurement of resting
  voltage, membrane time constant or adaptation, and no registered source publishes a
  unit-resolved current step for any PN type. Input resistance is unmeasurable even from the one
  unit-resolved protocol, because every sweep is suprathreshold. V1 and V2 remain unawarded.
- The Gugel Dryad deposit holds four source-data files the eLife CDN does not carry, including two
  more Figure 7 files. Dryad now serves downloads behind a proof-of-work bot wall, so scripted
  acquisition under the project checksum-locking rule is currently blocked.
- After the uEPSC holdout the corpus contains no unconsumed cellular or synaptic recording at
  all. Both the synaptic and ensemble exit legs now need new data, not new code.
- Receptor-aware polarity has no source. The MaleCNS `receptorType` column is gustatory receptor
  identity, not postsynaptic receptor expression, and no connectome-mapped receptor resource
  exists. For release and short-term plasticity Kazama and Wilson 2008 publish point
  estimates (release probability 0.79, 51 sites per connection, depression above about
  50 spikes/s), registered in `stage2-synaptic-structure-v2`, but no trace is deposited.
- The MBON07 parameter set in `cell-dynamics-v0.3` carries values that depend on their
  measurement rule by 15 ms and 3.4 mV, and a refractory period that is an upper bound used
  as a value. A v0.4 revision is an open decision (AGENTS section 15).

Detailed structural evidence: [V0 Structural](evidence/V0_STRUCTURAL.md),
[full flat-connectome profile](evidence/FULL_PROFILE_INTEGRITY.md), and
[morphology canaries](evidence/MORPHOLOGY_CANARIES.md). Numerical implementation evidence:
[LIF backend parity](evidence/LIF_BACKEND_PARITY.md) and
[transmitter-only sign control](evidence/TRANSMITTER_SIGN_CONTROL.md). First Stage 1 experiment:
[Shiu antennal-grooming transfer](evidence/STAGE1_SHIU_GROOMING.md) and
[Shiu feeding-screen execution and review](evidence/STAGE1_SHIU_FEEDING.md). Track A engineering
evidence: [full-graph Eon-like demonstration](evidence/TRACK_A_EON_MALECNS.md).
First Stage 2 data decisions and evidence boundary: [ADR-2026-004](adr/ADR-2026-004-projection-neuron-physiology-pack.md),
[ADR-2026-005](adr/ADR-2026-005-independent-pn-trace-challenge.md), and
[projection-neuron physiology foundation](evidence/STAGE2_PN_PHYSIOLOGY_FOUNDATION.md).
Cellular-tier sources, the Nanami stimulus resolution, and heterogeneous-cell execution:
[ADR-2026-007](adr/ADR-2026-007-cellular-tier-sources.md) and
[Stage 2 cellular observables](evidence/STAGE2_CELLULAR_OBSERVABLES.md).
The independent Stage 2 review and its corrections:
[ADR-2026-009](adr/ADR-2026-009-stage2-independent-review.md).
Synaptic-tier evidence and the executable exit gate:
[ADR-2026-008](adr/ADR-2026-008-synaptic-tier-and-stage2-exit-gate.md) and
[Stage 2 synaptic tier](evidence/STAGE2_SYNAPTIC_TIER.md).

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
| V0 evidence gates | 12 of 12 passing in the reissued bundle |
| Automated tests | 83 passing |

The GPU measurements are topology-allocation results, not biological-time performance for fitted neural dynamics. `DATA-04` and [ADR-2026-002](adr/ADR-2026-002-traced-neuron-universe.md) are accepted; Assign/Anchor and all-segment universes remain explicit sensitivity alternatives.

| GeNN structural scale | Edges | GPU delta | Load | One 0.1 ms step host call |
|---:|---:|---:|---:|---:|
| 1% | 255,632 | 205 MiB | 0.242 s | 0.171 ms |
| 10% | 2,556,320 | 788 MiB | 0.972 s | 0.180 ms |
| 100% | 25,563,197 | 7,165 MiB | 12.466 s | 0.483 ms |

The 100% model left 3,775 MiB GPU memory free during measurement, exceeding the required 1.5 GB headroom.

Highest validation tier: **V0 Structural**, reissued on 2026-09-08 as bundle
`20260908T060641Z_V0` (SHA-256
`38366a8df86861501ca2fd4eff3e3c9329e0e089ec0e188b4af4f1a66c085958`). It pins an immutable
snapshot scoped to the `DATA-*` foundation records instead of the whole mutable register, and it
recomputes each of the seven raw artifacts' upstream MD5 from local bytes; all seven match. The
superseded bundle `20260906T065413Z_V0` remains on disk and is still rejected by
`flysim evidence validate`, which is what a withdrawn claim should look like. CRC32C is pinned
but not recomputed, because no native CRC32C implementation is installed; the review artifact
records that explicitly rather than implying the check ran. The evidence establishes dataset identity, lossless structural
transformation, selected identity/motif preservation, confidence sensitivity, and a bounded
cross-connectome comparison, and it makes no physiological or behavioral claim. Stage 1's
deliberately simple open-loop baseline is complete, with the gate split disclosed below. The v1
and v2 Track A acceptance evidence is withdrawn permanently; the v3 rerun from a clean commit
fails its own behavioural criterion, so Track A is not an accepted milestone. The
[ADR-2026-006](adr/ADR-2026-006-evidence-chain-repair.md) evidence-chain repair is complete and
Stage 2 fitted neural dynamics has resumed.

## Evidence-chain repair (completed 2026-09-08)

An independent audit confirmed ten defects that this status page previously did not disclose.
All are repaired under [ADR-2026-006](adr/ADR-2026-006-evidence-chain-repair.md), V0 is
reissued and validates, and Stage 2 has resumed. Two engineering defects that the repair
*surfaced* remain open and are listed after the table.

| Defect | Status |
|---|---|
| The V0 bundle pinned the mutable assumption register and stopped validating | Repaired and **reissued** as `20260908T060641Z_V0`, which validates |
| The V0 builder required assumption set `foundation-v0.3` while the register had moved on | Gate is now content-based; the set identifier no longer affects V0 |
| Every Track A acceptance and control artifact was produced from an uncommitted worktree | Evidence-grade runs and both Track A scripts now refuse a dirty tree |
| The settled FlyGym body began inside the dust patch, so grooming began on a fixed schedule | Dust patch moved; a startup guard fails closed if clearance is lost |
| The grooming replay translated the body 5 to 8 mm while the forward command was zero | Measured, capped at one body length, enforced in acceptance; **the cap fails in 30 of 30 runs and the defect is stance station-keeping, not the replay** |
| The registered 0.1 ms GeNN synaptic delay executed as 0.2 ms | Corrected, with a one-synapse impulse test across three delays |
| Registered 2 ms interface delays were realised as 15 ms without being registered | Effective delays are computed, registered, and asserted at build time |
| The shuffled-connectome control could not fail | Replaced with a preregistered degradation criterion |
| The forward and yaw commands were labelled mm/s and rad/s | Renamed to normalized descending drives |
| The Track A held-out positions had already been used by a discarded v1 round | Three genuinely unused positions preregistered and executed as v3 |
| Every Track A transition fired at an identical time in all 30 runs | Grooming now begins across 12 distinct times between 330 and 690 ms, after a measured approach |

### Open engineering issues surfaced by the repair

1. **Body station-keeping. Diagnosed 2026-09-08, not fixed** — see
   [the station-keeping report](evidence/TRACK_A_STATION_KEEPING.md). The 6.26 mm grooming
   displacement decomposes into 2.161 mm of baseline creep while standing under no command,
   2.756 mm more from lifting front-leg adhesion so the front legs can groom, and only about
   1.34 mm from the grooming replay itself. Creep runs at about 0.88 mm/s and is linear over six
   seconds, not a settling transient, and re-zeroing velocities changes it by nothing; the
   position actuators are saturated at their 240-unit force ceiling while the body is nominally
   still. **The 2.5 mm cap is unreachable before grooming begins**, since a stationary body
   passes it after about 2.8 s. Adhesion already suppresses about 85% of the slide — with it off
   the body travels 14.297 mm in 3 s. The obvious fix was tested and refuted: holding the pose
   the body actually settles into, rather than the pose the settle phase commanded, doubles the
   drift to 4.708 mm, because the residual actuator force is load-bearing. A legitimate fix is a
   closed-loop station-keeping controller, which the FlyGym locomotion scaffold does not have;
   raising adhesion, stiffening contacts, lifting force limits or welding the body during
   grooming are all excluded. The analytically correct criterion is a differential against
   standing displacement, which the report states and deliberately does not adopt, because
   restating a criterion that has just failed would convert a failing acceptance run into a
   passing one by fiat.
2. **Rendered-timing divergence.** Enabling the renderer shifts the last two transitions by
   1.44 s, and no preregistered criterion bounds it. The equivalence control should gain a
   timing tolerance rather than testing the transition signature alone.

## Stage 2 open decisions closed (2026-09-08)

[ADR-2026-010](adr/ADR-2026-010-cell-dynamics-v0.4-and-registered-depression.md) closes the two
decisions ADR-2026-009 left open and registers the first quantitative short-term-plasticity rule.
No tier is awarded and no gate changes verdict.

- **Cell-dynamics v0.4.** The MBON07 alpha1 parameter rule is decided by an LIF F-I consistency
  ranking over all eight candidate combinations against three independent spike detectors. The
  free-asymptote membrane time constant of 47.577 ms beats the pinned 32.566 ms under every
  detector (RMSE 1.80 vs 4.48, 1.61 vs 3.06, 2.46 vs 2.72 Hz) and the minimum-ISI refractory
  period of 15.8 ms beats the 2.2 ms fallback (1.80 vs 5.51 Hz). The threshold is formally
  unidentifiable from the fit, because threshold and input resistance trade off exactly, so it is
  decided on measurement definedness: -41.838 mV is defined for every spike, -38.402 mV for 51%
  of them. Every value now carries its rule-dependent range, which the loader validates.
- **A parameter set inconsistent with its own rheobase, disclosed not resolved.** Every
  self-consistent candidate implies 4.4 to 6.4 GOhm input resistance while the observed 2 pA
  rheobase requires at least 9.26 GOhm, and published fly central-neuron values are an order of
  magnitude lower again. This is a fitting artifact of the single-compartment LIF form; v0.4
  records it in `value_notes` and claims no resolution.
## Session of 2026-09-09

- **The Track A station-keeping defect is fixed, and the criterion it failed is refuted.**
  `MOTOR-04` adds proportional-integral feedback on thorax pose through the femur-tibia pitch
  of all six legs, provenance `E`, no physics parameter changed. Standing drift falls from
  2.161 to 0.357 mm at 3 s at the registered pose, and worst-case 12-second displacement from
  10.6 to 3.2 mm across seven settled poses; criterion B2 goes from failing 4 of 7 poses to
  passing 7 of 7. **B3 does not pass as written and is not restated.** Its ratio statistic is
  degenerate: it fails this controller while passing a strictly worse one, it passes a case
  leaking to 3.16 mm at 12 s, and it passes a diverged configuration that has travelled
  30.8 mm and rotated 2.69 rad. The well-conditioned replacement is preregistered in
  `track-a-acceptance-v5-criteria.json` and marked **not adopted**, disclosing that the
  current controller would fail it at 2 of 7 poses. **Track A remains not an accepted
  milestone**: B2 passes, B3 fails, B1 and B4 are unmeasured, and the 30-run matrix was not
  executed because it would spend hours reproducing a known failure.
- **The renderer is cleared as the cause of the 1.44 s rendered-timing divergence.** A rendered
  and a headless body driven with identical commands stay bit-identical in `qpos` for a whole
  run, maximum absolute difference exactly zero. The divergence originates elsewhere in the
  brain-body loop and the amendment remains unresolved.
- **The completeness-corrected contact estimate was built and it fails its own gate.**
  Modelling connectome incompleteness as independent per-synapse binomial thinning at the
  released 42% rate is falsified: **45 of 50 glomeruli have a measured completeness below the
  floor that model can produce at any survival rate**, because the recovered pairs carry too
  many contacts to explain how many whole pairs went missing. H1, the registered gate, gives
  rho = 0.635 against 0.7; H2 recovers a survival rate for 1 glomerulus of 50; H3 shows the
  correction *strengthened* the confound it targeted, from rho = -0.475 to -0.554. The loss is
  per-axon truncation, which the convergence test had already measured at r = +0.836 to
  +0.847. **No recorded contact statistic is revised by it.**
- **The glomerular volume question is now bounded and stays unsettled.** The two candidate
  correction models bracket the correlation at rho = +0.209, p = 0.146 and rho = +0.262,
  p = 0.066. The release-site scaling is unsupported for want of *power* at 50 glomeruli, not
  for want of a correction, and the volume report's hope that a correction would substitute
  for power is withdrawn.
- **One anatomical contact is probably not one release site.** Two independent results now
  say so: corrected contact counts run 2.06 times the Kazama and Wilson release-site estimate,
  and the bilateral test finds a 1.56-fold contact asymmetry where they measured no amplitude
  asymmetry. This is now the most load-bearing untested assumption in every contact-based
  claim here.
- **The bilateral ORN-to-PN symmetry prediction is rejected.** Ipsilateral connections carry a
  median 1.561 times the contacts of contralateral ones onto the same PN, 220 of 260 neurons
  individually, sign test p = 2.7e-31. The preregistered H2 control rules out a left/right
  reconstruction artifact, and a post-hoc within-ORN control — same axon, same reconstruction
  quality — gives the same 1.552 over 1799 ORNs at p = 2.0e-139. Loss within an axon's
  commissural branch remains unexcluded. Because the published p > 0.54 is a failure to reject
  rather than a demonstration of equality, this is best read as **a quantitative prediction
  their experiment lacked the power to test**, checkable in one targeted experiment.
- **The Stage 2 gate is restructured and is 0 of 3 (ADR-2026-011).** The cellular and synaptic
  legs are **retired as gates** because the raw traces they need are not public for anyone, a
  reason independent of whether they pass, and are demoted to recorded priors: still read,
  still checksum-verified, no longer scored. The scored legs are circuit, ensemble and
  structural, and all three fail. The rule that stops this being criterion-shopping is in the
  contract: a structural leg may only enter at a criterion registered before the test that
  scores it was run. **Retiring a leg is not passing it**, the scored gate is narrower than the
  `AGENTS.md` section 9 statement, and each retired leg records what reinstates it.
- **The whole-graph Shiu protocol does not need spike injection; that characterisation was
  wrong.** `TrackAGeNNEngine.push_inputs` already drives any body at any firing rate and
  resolves each body to its bucket and local index, so the bucketed whole-graph layout has an
  injection path. The actual gap is that the protocol semantics — `StimulusSchedule`, windowed
  readouts, `CircuitRun` — live in `circuit.run_genn_circuit`, which is built on a *single*
  sparse projection whose padding is what makes the whole graph cost 13.8 GiB against 12 GiB of
  VRAM. Running Shiu on all 165,122 neurons therefore means reimplementing the protocol on the
  bucketed layout, and the two paths use **different neuron models**: the bucketed engine drives
  an `InputRateHz` variable while the circuit path clamps an `InputCell` flag with its own reset
  code. So the work is a bucketed protocol runner *plus* a parity check against the existing
  path on a circuit small enough for both, in the shape `neural_parity` and
  `compare_backend_runs` already establish. That is the largest of the four items and it gates
  nothing, so it is scoped and deliberately not started: a half-built parallel engine is exactly
  the kind of thing that later yields a wrong number nobody notices.
- **ORN odour-response data is available; PN data is not.** DoOR 2.0 is downloadable under
  CC BY-SA 4.0, actively maintained, 78 responding units and 693 odorants normalised to [0,1].
  It contains **exclusively OSN and receptor data — no projection-neuron recordings**, so the
  activity-prediction route has a usable input and no per-PN held-out target. What it can be
  scored against is published population statistics of the ORN-to-PN transformation, which is
  a materially weaker but not empty target; the design is preregistered and unexecuted.

- **The cellular exit criterion is now failable, and fails. The Stage 2 gate is 0 of 4.** The
  leg requires the normalised error ratio strictly below 1.0 against a cohort-mean predictor and
  observes 1.0644: held-out RMSE 13.17 Hz against 12.38 Hz for the two-cell training mean, so the
  model is 6.4% worse than the cohort average. The gate previously failed three legs of four; it
  now fails all four. **This is a post-hoc tightening, not a regression** — the holdout's own
  preregistered limit was a ratio of at most 1.2 and 1.064 met it, the v1 and v2 gates read a
  boolean recording that pass, nothing about the model changed, and no new measurement was taken.
  ADR-2026-009 had already recorded in prose that a ratio above 1.0 loses to a cohort mean; v3
  makes that the criterion rather than a caveat under a leg marked passed. Issued as
  `stage2-exit-gate-v3.json` with result `evidence/stage2/exit-gate-v3.json`; v1, v2 and every
  artifact under them are untouched.
- **ND-06 carries its first fitted parameters.** `male-cns-short-term-plasticity-v0.1` binds
  same-glomerulus ORN-to-uniglomerular-PN edges to a depression-only Tsodyks-Markram rule with
  utilisation 0.22 and recovery 893 ms, from Nagel, Hong and Wilson 2015, which fits that exact
  equation to measured EPSC amplitude versus stimulus number in 19 PNs from 19 flies. The
  registered spread is [0.09, 0.23] and [629, 1006] ms across their three fits. The first draft
  had bound Kazama and Wilson's release probability of 0.79 to utilisation and invented a 500 ms
  recovery ceiling that excluded the published value; 0.79 mispredicts the measured 10 Hz
  paired-pulse ratio by a factor of 2.735, so the reading is recorded and not run. Implemented on
  the NumPy runner only; Brian2, GeNN and the Track A engine refuse a run that asks for it. No
  MaleCNS synapse was measured, so it awards nothing.
- **Data acquisition, mostly negative.** No public repository hosts raw *Drosophila* PN or
  ORN-to-PN patch-clamp traces, so the cellular tier stays single-specimen and the uEPSC prior
  keeps an empty holdout and labels all twelve cells as fitted. Croset, Treiber and Waddell 2018
  (eLife 7:e34550, GSE95361 / SRP128516) is located but unusable for ND-03: it is a midbrain
  Drop-Seq atlas whose PN receptor statements are inferential and which has no published mapping
  to MaleCNS body IDs.

## Structural test of the transferred grooming circuit (2026-09-08)

The bounded-path sweep ADR-2026-009 implied has been executed. See
[the widened-circuit evidence report](evidence/STAGE2_WIDENED_GROOMING_CIRCUIT.md). No tier is
awarded.

- **The structural reading is right about the cause and wrong about the cure.** The shortest-path
  selection rule dropped every inhibitory input to the aBN1 readout — all inhibition onto it
  arrives by paths of length two or more, so a one-hop induced subgraph is necessarily purely
  feedforward-excitatory there, and that alone explains a monotone over-response to drive. But
  widening does not moderate the response toward the reference: at K = 2 and K = 3 the readout
  produces 0.0 Hz at all eleven candidate scales and all three frequencies, against a one-hop
  33.2 Hz and a reference 4.63 ± 2.01 Hz at 220 Hz. H1 is `suppressed` and H2 fails at both.
  NumPy/GeNN parity passes at both, so it is not a backend artifact.
- **The mechanism is a handful of neurons, not bulk connectivity.** Delivered excitation onto the
  readouts barely changes as the edge count grows a thousandfold (12,857 → 13,564 → 13,375 and
  16,159 → 17,804 → 17,932); at K = 3 only 27 of 296 and 35 of 386 excitatory sources are ever
  active. What widening adds that matters is 14 to 22 active inhibitory neurons delivering about
  1.8x the excitatory drive.
- **A bounded induced subgraph of a connectome is not a small whole-brain simulation.** Both
  readings of "make the subgraph more complete" fail in opposite directions, so `ND-04`'s derived
  per-contact scale cannot be rescued by a better scale or a wider subgraph.
- **Three self-corrections are disclosed rather than quietly fixed**: the v1 H1 criterion was
  satisfied by a silent readout and scored a vacuous pass; the v2 static contact-sum diagnostic
  has the wrong sign at K = 3 against delivered drive; and the first v3 round recorded a commit
  that did not describe the code that ran, so it is discarded and the sweep now fails closed on a
  dirty worktree. Two of the three were criteria written in the same session.
- **The obvious next control is untested**: only the `zero` unresolved-sign policy was run, and
  the result turns on an excitation/inhibition balance that the other three registered policies
  could move.
- **The uEPSC prior refit does not repair the decay failure** and slightly widens it. Refitted
  decay is 16.5 ms against the frozen 15.0 ms, and the kernel's 17.3 ms peak-to-1/e sits about
  50% above the 11.5 ms median of the twelve source recordings. The holdout is empty and all
  twelve cells are labelled fitted, so it is a prior and not a test.

## Literature corpus and the first connectome-versus-physiology test (2026-09-09)

Fourteen primary papers were read in full and consolidated into
[the literature parameter corpus](evidence/LITERATURE_PARAMETER_CORPUS.md), which is now the
single place to check before registering a parameter.

- **The connectome completion rates were undisclosed and now are not.** The MaleCNS paper reports
  94% presynaptic completion, 42% postsynaptic completion, and 40.1% of synaptic connections with
  both partners proofread. None appeared anywhere in this repository. More than half of all
  postsynaptic sites are not attributed to a proofread neuron, so every statement about the
  inputs a neuron receives rests on a minority sample, and out-degree is far better sampled than
  in-degree. Now recorded in [V0_STRUCTURAL.md](evidence/V0_STRUCTURAL.md) with a body-count
  reconciliation, and added as a caveat to the widened-circuit report whose central
  excitation/inhibition result depends on it.
- **First quantitative agreement between the connectome and independent physiology.** See
  [the ORN-to-PN convergence report](evidence/ORN_PN_CONVERGENCE.md). Kazama and Wilson 2009's
  complete-convergence prediction is parameter-free and testable directly on the locked graph.
  Both preregistered hypotheses fail globally — median completeness 0.865 against a 0.95 floor,
  minimum 0.485 — yet **four glomeruli are exactly complete bipartite graphs**: V, VC5, VM5v and
  VM7d, 718 ordered pairs with zero missing edges, which has probability 7.3e-46 under
  independent edge recovery at the observed median rate. Where the reconstruction supports the
  question, the answer is exactly the published one.
- **The shortfall is reconstruction quality and it is measurable per neuron.** An ORN's total
  out-contact budget predicts the fraction of its cognate PNs it reaches (r = +0.85 in VL2p and
  DA1), the distributions are smooth rather than bimodal, and weak connections are specifically
  what goes missing: the complete glomeruli have no pairs below 5 contacts, while VL2p at 0.485
  has ten pairs carrying exactly one. Zero PNs are orphaned, which rules out gross typing error.
  This gives the project a reusable reconstruction-quality statistic to report alongside any
  modelled circuit; the JON-F/aBN1 populations do not yet have one.
- **My own H2 argument was wrong and is marked so.** It assumed at least 10 contacts per pair, so
  per-synapse incompleteness could not push edge recovery below 0.99. Measured contacts per pair
  reach down to 1, so the arithmetic was right on a false premise.
- **ND-06 fails its first external test.** Kazama and Wilson 2008 independently measure about 40%
  depression at 7 Hz; the registered pair predicts 56%, over-predicting by roughly 16 points.
  Their 1/CV-squared analysis does independently validate the presynaptic depletion *form* of the
  model (r = 0.79, p < 1e-4).
- **The v0.4 input-resistance defect is confirmed with a measurement.** Gouwens and Wilson 2009
  measure PN input resistance at 598 +/- 69 MOhm, 7 to 15 times below the 4.4-6.4 GOhm the MBON07
  LIF fit implies, so ADR-2026-010's fitting-artifact conclusion no longer rests on another
  model's constant. The same paper shows electrode seal conductance depolarises measured somatic
  resting potentials by about 10 mV, with a larger error at more hyperpolarised potentials, which
  widens the true threshold-to-rest distance and makes the rheobase inconsistency worse.
- **ND-03 is a boundary, not a pending action.** Receptor class does match presynaptic
  transmitter, but different receptors for the same transmitter localise to different dendritic
  domains receiving different partners, so the refinement is partner-specific and no bulk
  expression atlas can supply it.
- **No raw traces exist.** Confirmed absent for all four Wilson-lab papers, so the cellular tier
  stays single-specimen and the uEPSC holdout stays empty for that reason rather than for want of
  searching.

### Reconstruction quality applied to the grooming circuit (2026-09-09)

The convergence test's calibration was applied to the Stage 1/Stage 2 grooming populations, and
it materially weakens what the widened-circuit result can claim.

- The two aBN1 readouts are excellently reconstructed, at the 99.4th percentile for outputs and
  above the 96th for inputs among all 165,122 traced neurons.
- **The JON-F sensory inputs sit at the 24.2nd percentile**, below VL2p's ORNs at 58.7 — and VL2p
  is the glomerulus where only 48.5% of known connections were recovered. This is a caveat on the
  whole grooming transfer, not just the widened sweep: the inputs are drawn from a poorly
  reconstructed peripheral population whose edges are the most likely to be missing.
- **The inhibitory partners onto the readouts carry about 3 times the contact budget of the
  excitatory ones** (96.3rd against 79.6th percentile). Part is real biology, since inhibitory
  gain-control cells have broad dense arbors, but larger and better-reconstructed neurons also
  have their edges recovered more completely at 42% postsynaptic completion. The recovered
  excitation/inhibition balance therefore overstates inhibition by an unquantified amount. Since
  delivered inhibition exceeds delivered excitation by only about 1.8-fold while the
  reconstruction asymmetry is 3-fold, **the sign of the true balance is genuinely uncertain** and
  the mechanistic attribution of the readout silence is now qualified rather than established.

### The uEPSC kernel family is misspecified (2026-09-09)

Chasing an apparent independent validation found a real defect instead. Recorded in
[the literature corpus](evidence/LITERATURE_PARAMETER_CORPUS.md), final section.

- **The apparent agreement was spurious.** The refitted prior's 30.25 pA sitting near Kazama and
  Wilson's 29.0 ± 2.6 pA looked like the independent amplitude check the synaptic tier lacks. It
  was not: their 29.0 pA is pooled over four glomeruli differing at p < 1e-6, with DL5 one of the
  two large ones, and Gugel and colleagues state their own DL5 control amplitude as ~40 pA.
- **The data is faithful; the fit is biased.** Measuring the twelve traces directly gives a
  per-cell peak amplitude of **36.61 pA, SEM 2.92** (34.92 pA for the seven controls), which does
  agree with the published ~40 pA. The repository's kernel fit reports 30.25 pA, **17% low**, and
  the frozen fit 24.47 pA, 33% low.
- **The cause is the kernel family, and both source papers say so.** Kazama and Wilson: "The
  decay phase of these evoked EPSCs typically had two components, fast and slow." Nagel and
  colleagues fit exactly that at 9.3 ms and 80 ms. The project's kernel has one decay. Three
  alternative explanations were tested and rejected: pinning the decay to the published value
  recovers only 4% of the gap, the traces are already peak-aligned so there is no onset jitter to
  smear, and the Huber delta is worth 3%. Adding a second decay term reduces SSE by **23.2%** and
  moves the kernel half-decay from 11.20 ms to 9.80 ms against a published ~7 ms.
- **This reframes a recorded result.** ADR-2026-008 recorded the kernel's decay as failing its
  preregistered holdout at 0.463 median fractional error against a 0.30 limit, and treated it as
  an empirical finding. It is substantially a misspecification the literature predicted. A
  two-component kernel is the indicated fix and its parameters are published.
- **It does not unblock the synaptic leg.** A better kernel fitted to all twelve cells is a
  better prior, not a test, and even two decays leave the amplitude 7% low and the half-decay 40%
  above the published value.

### Homeostatic matching: the proxy-failure explanation is WITHDRAWN (2026-09-09)

**The section immediately below is superseded and must be read with this note.** A preregistered
blind measurement of glomerular volume, reported in
[GLOMERULAR_VOLUME_SCALING.md](evidence/GLOMERULAR_VOLUME_SCALING.md), withdraws its central
claim. Volume **does** track converging ORN count in MaleCNS, at Spearman +0.329 (p = 0.020) and
+0.481 (p = 0.013) among well-reconstructed glomeruli, exactly as Kazama and Wilson report. ORN
count was therefore a directionally valid proxy, so the earlier test was not testing the wrong
variable and the "proxy failure" reading is wrong. The four-glomerulus contact ordering is also
withdrawn as evidence: the measured volumes for those same four order DM4 > DL5 > DM6 > VM2 while
the contacts order DL5 > DM4 > VM2 > DM6, so two of three adjacent pairs disagree.

What replaces it is not the old negative either. Contacts per connection show no correlation with
volume across all 50 glomeruli (+0.070, p = 0.63), so H1 fails as preregistered — but the
statistic is contaminated. Stratifying by convergence completeness, the contacts-versus-ORN-count
correlation collapses from −0.475 (p < 0.001) over all 50 to −0.046 (p = 0.89) over the
best-reconstructed eleven, so it was reading reconstruction quality as biology. Contacts versus
volume moves the other way, +0.070 to +0.381 to +0.527, in the direction Kazama and Wilson
predict, but never reaches p < 0.05 and n = 11 settles nothing. **The honest verdict is that this
question is not settleable on this connectome with this measurement**, and it fails precisely
where the effect should be largest: the big glomeruli are the badly reconstructed ones. A
completeness-corrected contact estimate is the indicated next step.

### Superseded: homeostatic matching read as a proxy failure (2026-09-09)

This status page recorded that "contact number does not implement the published homeostatic
matching". That conclusion rests on a proxy the project substituted for the variable Kazama and
Wilson actually measured, and on the four glomeruli where they measured it the connectome
reproduces their result.

**Their claim, precisely.** Unitary EPSC amplitude correlates with the **glomerular volume**
occupied by the PN dendritic tuft (r = 0.75, n = 39), achieved by scaling the number of release
sites per ORN axon per PN while release probability and quantal size stay constant across
glomeruli (p > 0.36 and p > 0.07 respectively), so that unitary *depolarisation* is uniform
(p > 0.43) while unitary *current* is not (p < 1e-6).

**What the connectome shows.** Contacts per realised ORN-to-PN connection, against their stated
ordering that "uEPSC amplitudes are consistently larger for glomeruli DL5 and DM4 than for DM6
and VM2":

```
  DL5   81 contacts        }  large group, min 63
  DM4   63 contacts        }
  VM2   40 contacts        }  small group, max 40
  DM6   28 contacts        }
  clean separation, 1.57x, ordering reproduced exactly
```

**Why the earlier test failed.** The `stage2-synaptic-structure-v2` H2 predicts contacts per
connection *rising* with converging ORN count, on the chain "unitary current rises with
glomerular volume and volume rises with ORN number". The first link is Kazama and Wilson's
measurement; the second is the project's own substitution, and it is what breaks. Across all 50
glomeruli contacts per connection **anti**-correlates with ORN count (Pearson -0.413, Spearman
-0.487) and with PN count (-0.626). ORN count is not a usable proxy for glomerular volume in
MaleCNS, so H2 tested the proxy rather than the claim.

**How much weight this carries.** Not much yet, and it is labelled accordingly. It is a post-hoc
ordinal check on four glomeruli in two groups of two, computed from the convergence artifact
rather than preregistered. Only the ordering is testable because Kazama and Wilson's
per-glomerulus amplitudes are figure-only. Median contacts is measured over realised pairs and is
biased upward where completeness is low, and DM4 has the lowest completeness of the four at
0.680 — though dropping DM4 leaves DL5 at 81 still cleanly above VM2 at 40 and DM6 at 28.

**What a real test needs.** Glomerular volumes, which the connectome can supply from synapse-cloud
extent or meshes and which this analysis did not compute. That would test Kazama and Wilson's
actual r = 0.75 correlation over all 50 glomeruli instead of an ordering over four, and it is the
indicated next experiment for the synaptic tier.

### The uEPSC kernel family, executed (2026-09-09)

`stage2-uepsc-kernel-family-v2`, artifact `evidence/stage2/uepsc-kernel-family-v2.json`
SHA-256 `d5081097f07147aa70f70e54b4c4786d6ef35dd3850382231a6c8cf53744b9aa`. All four hypotheses
pass and the fit converges on the interior of its grid.

| | single decay (frozen family) | two decays | published target |
|---|---|---|---|
| Huber training loss | 0.58737 | **0.45875** (−21.9%) | — |
| kernel half-decay | 12.20 ms | **9.00 ms** | ~7 ms |
| population amplitude | 30.25 pA (−17.4%) | **32.39 pA (−11.5%)** | direct measurement 36.61 pA |
| decay constants | 16.5 ms | fast 8.0 / slow 40.0 ms, fast fraction 0.85 | Nagel 9.3 / 80 ms, 0.786 |

The fitted fast constant of 8.0 ms sits close to Nagel and colleagues' 9.3 ms. The slow constant
does not, and that is a limitation of the recordings rather than a contradiction: the traces span
about 200 ms, so a 40 ms component cannot be separated from an 80 ms one with confidence, and the
contract says so.

**What it settles.** ADR-2026-008 recorded the frozen kernel's decay as failing its holdout at
0.463 median fractional error against a 0.30 limit and read that as a measured inadequacy. It is
substantially a misspecification both source papers predicted: the family had one decay where the
synapse has two. **What it does not settle:** neither family is validated, because both are
fitted to all twelve already-consumed cells, and even two decays leave the amplitude 11.5% below
the direct measurement and the half-decay 29% above the published value. A better prior, not a
tested model.

**Two process notes.** The v1 run hit a grid boundary — its slow decay pinned at the 30 ms floor —
so v2 widens the grid, converges interior, and adds H5 to make a future boundary hit fail a
criterion rather than appear only as a flag. And the contract declares in three places that it is
not blind: the comparison was explored before it was written.

### Track A v4 criteria, preregistered before any controller exists (2026-09-09)

[`track-a-acceptance-v4-criteria.json`](../configs/experiments/track-a-acceptance-v4-criteria.json)
splits the conflated grooming-displacement criterion. No run is executed and nothing is accepted
by registering it; Track A remains not an accepted milestone.

The v3 criterion capped total displacement during a grooming bout at 2.5 mm and failed 0 of 30.
The station-keeping diagnosis showed why that is the wrong measurement: the 6.26 mm decomposes
into 2.161 mm of baseline creep, 2.756 mm from lifting front-leg adhesion so the front legs can
groom, and about 1.34 mm from the replay itself — the smallest of the three. At 0.88 mm/s of
creep, a stationary body passes 2.5 mm after 2.8 s, so a 3-second bout cannot clear the cap
whatever the replay does.

- **B1** caps the replay's own contribution at 2.5 mm, isolated against a paired control identical
  but for replay suppression. The body is deterministic given seed and position, so the pairing is
  exact rather than statistical.
- **B3 is the point of the split and it fails now.** Standing drift must be sublinear in time:
  displacement at 6 s under 1.5x displacement at 3 s, which a settling transient satisfies and a
  constant leak does not. Observed 5.311/2.161 = 2.458 against a limit of 1.5. A criterion on the
  total at one duration cannot tell a transient from a leak; this one can, and it is what the
  defect actually violates. Physics escapes are named and forbidden — adhesion force, contact
  stiffness, actuator limits, floor damping, welding, shortening the bout — leaving a closed-loop
  station-keeping controller as the only permitted fix, labelled provenance E.
- **The renderer control gains a 100 ms timing tolerance**, justified against the 2 ms coupling
  cycle, and it fails now at 1,440 ms. Strictly added; nothing relaxed.
- The absolute displacement is still recorded at every run, the v3 0-of-30 verdict is not
  withdrawn, and acceptance requires B1, B2, B3 and B4 together.

**This is the third criterion correction in this project's history and the contract says so.** It
discloses that it is not blind, that applying B1 to existing v3 data would give 1.34 mm and pass,
and it carries a reviewer instruction: check that B3 is genuinely failing, that B1's pairing is
exact, and that the absolute figure is retained, or reject the contract as criterion-shopping.
Nine tests enforce exactly those three things plus the decomposition arithmetic, so a later edit
that quietly weakens any of them breaks the suite.
