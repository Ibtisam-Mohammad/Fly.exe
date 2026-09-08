# MaleCNS Virtual Fly — Agent Source of Truth

Status: canonical project direction  
Version: 1.11
Last evidence review: 2026-09-08
Last implementation audit: 2026-09-08
Applies to: this repository and every subdirectory

## 1. Agent bootstrap

Read this file before planning or changing the project. The project's target is:

> A scientifically honest, stochastic, MaleCNS-constrained embodied sensorimotor model of a representative adult male *Drosophila*.

It is **not** a recovered copy of the imaged fly, a complete biological emulation, or a digital twin. MaleCNS fixes much of the anatomical wiring. It does not fix the living dynamics, peripheral sensors, internal state, neuromuscular transformation, body, or environment.

Current first milestone:

> Closed-loop, flat-ground walking with limited sensory input, while preserving the MaleCNS brain–VNC–motor pathway and exposing every borrowed, fitted, or engineered parameter.

Agents must preserve these decisions unless the user explicitly changes the goal or a documented project decision supersedes them.

### Quick retrieval index

These stable keys are intended for agent search and handoff:

```text
PROJECT_GOAL: MaleCNS-constrained embodied adult-male sensorimotor model
CLAIM_BOUNDARY: population-plausible model; not source-fly recovery or digital twin
CANONICAL_CONNECTOME: MaleCNS v1.0
CURRENT_STAGE: evidence-chain repair (ADR-2026-006); Stage 2 fitted dynamics paused until the repair completes
DATA_STATUS: seven-artifact MaleCNS v1.0 flat-connectome profile checksum-locked; lossless contact derivative and independent dual-layout rebuilds validated
HIGHEST_VALIDATION_TIER: V0 Structural, reissued 2026-09-08 as bundle 20260908T060641Z_V0 under ADR-2026-006
ENGINEERING_STATUS: ramp-aware adaptive PN distribution passes a preregistered four-cell chronic-condition F-I sub-gate at ratio 1.064 and preserves it at 50 us; it is not complete V1 and no V1/V2 tier is awarded
NEXT_GATE: lock independent resting-voltage/time-constant/adaptation holdouts for complete V1; resolve Nanami units before its sealed score; source release-failure/STP evidence for V2
FOUNDATION_JOB: complete; bundle 20260908T060641Z_V0 pins a scoped DATA-* snapshot. The first bundle 20260906T065413Z_V0 is withdrawn because it pinned the mutable assumption register
FOUNDATION_REBUILD: complete; canonical, 262144-row-group, and 131072-row-group contact layouts are logically identical
NEURAL_PARITY: three-neuron fixture and 41-neuron Shiu transfer pass NumPy/Brian2/PyGeNN at 100 us; numerical evidence only
NEURAL_SIGN_VARIANT: Shiu transmitter-only regression is executable with explicit unresolved policies; never the physiological default
STAGE1_SHIU_REFERENCE: Edmond v3.0 archive checksum-locked; Figure 5g published-output analysis reproduced
STAGE1_SHIU_TRANSFER: immutable report 1290b8d717eaff49; 41 neurons, 129 edges; three-backend parity passes; global scale fails 0/8 held-out positive-response coverage; no V3 awarded
STAGE1_DYNAMICS_REGISTRY: male-cns-cell-dynamics-v0.1; 39 JO-F bodies have class-level spiking priors and two SAD093 bodies remain unresolved; hybrid execution disabled
STAGE1_SECOND_CIRCUIT: immutable review 3da6ffefaf9bdc6d; 101 mapped types x 30 trials; exact BA/AUROC 0.808; shuffled 0.500; cell-type-only 0.797; Stage 1 baseline passed but selected V3 specificity failed and no tier was awarded
TRACK_A_STATUS: not accepted; grooming-displacement cap fails 30/30; steady-state speed 0.332 minimum/0.353 median vs 0.5 target; awards no tier
TRACK_A_POPULATIONS: DNa01/DNa02, DNg97, MN9, JO-F, DNg62/DNge078/DNg21, DM1/DM4 PNs, and GNG588 resolve numerically
STAGE2_DATA: Gouwens-Wilson DM1 priors and Gugel DL5 F-I/uEPSC data locked; one external Nanami PN trace is normalized and reserved but is not population evidence
STAGE2_READINESS: dynamic revision contract 8ddb0b77770d passes four hashes; two original Gugel cells are training-only, four chronic-condition cells are now consumed holdouts, and the Nanami cell remains unscored
STAGE2_FIT: first frozen F-I ratio 1.228 fails and uEPSC ratio 1.105 passes; adaptive distribution training RMSE 7.630 vs 15.528 baseline, chronic-condition held-out ratio 1.064 passes, and 100-to-50-us conclusion is stable; no tier awarded
TRACK_A_EVIDENCE: v3 primary bb5674a4ab942e0c; v3 controls 249353025c770080; population registry 3b0c53a38230be21; v1 and v2 evidence withdrawn
FIRST_EMBODIMENT: closed-loop flat-ground walking
NEURAL_BASELINE: hybrid graded/spiking with explicit uncertainty
INITIAL_STATE: awake, fed, water-replete, unmated, daytime, artificial naive memory
BODY_BASELINE: FlyGym/NeuroMechFly with explicit female-body and actuator mismatch
PLASTICITY_V1: disabled
SUCCESS_RULE: behavioral resemblance alone is insufficient
```

V0 checkpoint, 2026-09-06: evidence bundle `20260906T065413Z_V0` (SHA-256
`d8a95e151daf3e2bb70b13052f52a2b794e9bf6887121d64d34727f37cccf0b0`) passes all twelve
required structural gates. The full-profile boundary remains the seven registered flat-connectome
artifacts; it excludes bulk skeleton collections, segmentation volumes, and the neuPrint database.
Ten fixed bilateral descending, antennal-sensory, and motor SWC canaries provide lazy morphology
coverage. V0 is structural evidence only: it validates neither neural dynamics nor behavior.

Stage 1 checkpoint, 2026-09-07: immutable transfer report
`shiu-antennal-grooming-transfer-1290b8d717eaff49.json` (SHA-256
`1290b8d717eaff4956fa90f0e5fe233a5ab25022e4a72d1de5165ead3d9aa577`) executes all
11 Figure 5g frequencies and five structural controls. NumPy, Brian2 and float64 reference GeNN
pass the registered spike-count/rate/timing parity gate. A preregistered one-parameter `ND-04`
fit selected 0.075 mV/contact but produced zero positive responses at all eight held-out
frequencies. This is a recorded negative cross-connectome result from the first experiment; no
V1, V2 or V3 tier is awarded. Whole-CNS production precision remains float32; float64 GeNN is
used only for this bounded numerical oracle.

The versioned `male-cns-cell-dynamics-v0.1` registry now resolves the selected circuit's
class-level signaling evidence without changing its source-faithful LIF execution: 39 JO-F
bodies receive a class-level spiking prior and both `SAD093` readouts remain explicit
spiking-versus-graded alternatives. Per-edge type-pair scale hooks exist in NumPy, Brian2 and
PyGeNN, but no typed scales are fitted or enabled.

Stage 1 completion checkpoint, 2026-09-07: the label-blind Figure 2 preregistration is locked at
SHA-256 `51635491cb9384240f5d6b83a8e2161ef5b0f46da21646a85330758a48cdbfc2`, followed by
an immutable prediction artifact and review
`shiu-feeding-screen-stage1-review-3da6ffefaf9bdc6d.json` (SHA-256
`3da6ffefaf9bdc6d753b0341612bd195af3d093a4033b9b3944f47840f7db927`). The complete
101-mapped-type by 30-trial screen used a 2,714-neuron, 258,586-edge bounded MaleCNS circuit.
Exact balanced accuracy and AUROC are both 0.8077; shuffled connectivity falls to 0.5, while
cell-type-only remains 0.7972. All states are finite, the 50-microsecond sensitivity run gives
identical classifications/AUROC, and zero weights give no MN9 response. These results pass the
Stage 1 baseline exit gate. They fail the frozen 0.05 AUROC margin over cell-type-only (observed
margin 0.0105), so they do not establish individual-connectome specificity and award no V3 tier.

Track A checkpoint, 2026-09-07: the full 165,122-body, 25,563,197-edge traced graph executes in
direct PyGeNN through an exact degree-bucketed sparse layout and a FlyGym 2.1/MuJoCo 3.9 body.
All ten seeds completed the required sequence at each of three held-out food positions (30/30).
The contamination/grooming and sucrose/MN9 ablations block their respective transitions;
zero-weight, shuffled-connectome, controller-only and neural-bypass controls are recorded. The
primary matrix is SHA-256 `6fb57a6fe536ed559360bb91c1b41554cbab0056d2aae22a1df17ae35caeaa57` and
the controls bundle is SHA-256 `65250db0fc473b9011a3fd25e116752135419b2ec009b8a75478d9b03a352731`.
Observed throughput is 0.117 minimum and 0.169 median biological seconds per wall second, below
the 0.5 target, so the milestone is an offline engineering prototype. It injects DM1/DM4 and
GNG588 central relays, applies a 10x entry-path gain, drives DNg97 with an odor-gated intent bias,
uses explicit odor-gradient steering, and replays a published grooming trajectory through ideal
joint actuators. It is not autonomous connectome-generated behavior and awards no validation tier.

Stage 2 checkpoint, 2026-09-07: ADR-2026-004 locks the first projection-neuron physiology
pack and a recorded-cell split. Three published DM1 passive cable fits are retained as `P/F`
priors. Official Gugel et al. Figure 7 source data yield 7,280 DL5 F-I rows and 24,012 unitary-EPSC
rows, split into six fit and five held-out recordings. The data/loss contract is fit-ready. This
checkpoint established acquisition and preregistration. The subsequently frozen first fit selected a
steady-state LIF family (31 pA rheobase, 30.6 ms membrane tau, 24 ms refractory) and a causal uEPSC
kernel (47.25 ms onset, 0.75 ms rise tau, 15 ms decay tau). On held-out cells, the F-I normalized
error ratio is 1.228 and fails the preregistered 1.2 limit; the baseline-corrected uEPSC ratio is
1.105 and passes that
one aggregate gate. No continuous parameter is on a search boundary. Result artifact
`projection-neuron-fit-v3.json` has SHA-256
`5ee63453c3c12d7ada3754245b93c172567e1ecaf6b0c4a4a51fec958a336780`. The held-out cells are
now consumed and cannot validate a revised model. No V1/V2 tier is awarded.

The post-freeze uEPSC feature audit changes no parameter. Its population kernel underpredicts the
three held-out peak amplitudes by 31.323, 4.807, and 11.584 pA; peak time is 0.300 ms early for all
three, and one-over-e decay errors are -1.200, -3.300, and +5.000 ms. Sign, amplitude, and kinetics
are descriptively covered, but numeric feature thresholds were not preregistered and release-failure
and short-term-plasticity evidence are missing. Review artifact
`projection-neuron-feature-review-v1.json` has SHA-256
`9cec459676980403ecf4bc95438fbe53514a2fd77da5de7403dde343123c20d0`; no V2 tier is awarded.

Stage 2 dynamic-revision checkpoint, 2026-09-08: ADR-2026-005 reserves the pinned Nanami et al.
PN recording as a strictly external challenge. The source contains one 200,000-sample, 10-kHz
current-clamp trace from a three-day-old female driver-defined PN. It is normalized losslessly, but
the repository code leaves the physical units of stimulus levels 3 through 10 unstated and derives
step alignment with a voltage-threshold heuristic. It cannot award V1 or characterize a population.

Before quantitative external scoring, experiment contract
`stage2-projection-neuron-dynamic-revision-v1` froze a 100-us ramp-aware adaptive LIF family and
prevented reuse of the consumed Gugel held-out cells. Two per-training-cell parameter draws reduce
training RMSE from 15.528 Hz for the original shared steady-state LIF to 7.630 Hz. This is a fitting
result, not held-out validation. Frozen result `projection-neuron-dynamic-fit-v5.json` has SHA-256
`8d97c40c094bbc06df9d83aa7b9cc057ef89cfb46b8162d806a9c134ba5f4bac`; the external trace remains
unscored pending unit resolution or a better independent multi-animal source. No V1/V2 tier is
awarded.

The adaptive distribution was then evaluated once on four previously excluded chronic-exposure DL5
cells under preregistered contract `stage2-pn-dynamic-chronic-condition-holdout-v1`. Population-mean
model RMSE is 13.174 Hz versus 12.376 Hz for the training-cohort biological baseline, giving a
normalized ratio of 1.064 and passing the 1.2 F-I sub-gate. The immutable result SHA-256 is
`401812a90bd8bffa77ab6381676f7717e62368089545d04a50595eec41c0a434`. These cells are now
consumed. The same-paper, chronic-condition result is not an independent-laboratory population
validation and lacks the resting-voltage, membrane-time-constant, and adaptation evidence required
for complete V1, and no tier is currently awarded.

The preregistered numerical review then halved adaptive-model integration from 100 to 50 us
without changing parameters or acceptance limits. The normalized ratio changes from 1.064444 to
1.064332, all predictions remain finite, and the F-I sub-gate conclusion is preserved. Immutable
review `projection-neuron-dynamic-timestep-review-v1.json` has SHA-256
`5fa0f39fe15e239d441c57a16b4d2cb1c76c2175c7fe50e65c475fc4b5e088b8`. This closes a
numerical-sensitivity check only and does not add biological evidence or award a tier.

Useful retrieval commands:

```powershell
rg -n "PROJECT_GOAL|CURRENT_STAGE|FIRST_EMBODIMENT" AGENTS.md
rg -n "ND-|SENS-|MOTOR-|BODY-|STATE-|VAL-" AGENTS.md
rg -n "Stage [0-7]|Exit gate|Non-negotiable" AGENTS.md
```

## 2. Canonical system boundary

```text
world fields
  -> body and peripheral mechanics
  -> receptor transduction
  -> MaleCNS sensory-entry neurons
  -> hybrid CNS dynamics (brain + neck + VNC)
  -> motor neurons
  -> peripheral axon / NMJ / muscle activation
  -> tendon / joint torque / body physics
  -> world fields and sensory feedback

slow state acts across the loop:
metabolism, hydration, arousal, sleep, circadian phase,
social/reproductive state, neuromodulation, learning and memory
```

MaleCNS directly constrains only part of this loop. Never describe an interface as biologically implemented merely because the interfaces on either side exist.

## 3. Evidence and assumption taxonomy

Every important parameter, mapping, model rule, dataset transform, and validation target must carry one provenance class:

| Code | Meaning | Required handling |
|---|---|---|
| `M` | Measured in the exact MaleCNS specimen | Preserve ID, coordinates, release version, confidence, and transformation history. |
| `P` | Population prior measured in another fly, sex, strain, age, or preparation | Record biological mismatch and use a distribution where possible. |
| `F` | Fitted from neural, muscular, kinematic, or behavioral data | Record training data, objective, held-out data, uncertainty, and identifiability. |
| `E` | Engineering scaffold chosen to make the system executable | Label it non-biological and maintain an ablation or replacement plan. |
| `I` | Irrecoverable for the source individual | Do not imply that optimization or more compute can recover it uniquely. |

Recommended metadata for every assumption:

```yaml
id: ND-03
name: type-pair synaptic conductance
value: null
units: si-unit-or-explicit-scale
provenance: F
applies_to: pre_type -> post_type
source: DOI-or-dataset-version
biological_mismatch: null
uncertainty: distribution-or-range
status: proposed | accepted | deprecated
validation: test-or-dataset-id
owner: subsystem
last_reviewed: YYYY-MM-DD
```

No unlabelled constants are allowed in scientific model code.

## 4. Fixed facts and limitations

### 4.1 What MaleCNS supplies

- MaleCNS v1.0 is the canonical connectome release.
- It covers the brain, optic lobes, neck and ventral nerve cord of one selected five-day-old male.
- It contains approximately 166,700 annotated neurons, morphology/skeletons, chemical-synapse locations and counts, cell/type annotations, predicted presynaptic transmitters, sensory-entry information, descending pathways, motor neurons, and many muscle-target annotations.
- Preserve body IDs, synapse coordinates, polyadic presynaptic sites, partner information, confidence values, annotations, and source version.
- The official data—not a copied or thresholded derivative—is the provenance root.

Primary sources: [MaleCNS paper](https://doi.org/10.1016/j.cell.2026.08.015), [official project](https://male-cns.janelia.org/), [v1.0 downloads](https://male-cns.janelia.org/download/).

### 4.2 What MaleCNS does not supply

- Live voltages, spikes, calcium activity, resting activity, or initial neural state.
- Cell-resolved membrane/channel parameters or universal knowledge of which cells spike versus signal with graded voltage.
- Postsynaptic receptor identity, functional edge sign, conductance, kinetics, release probability, short-term plasticity, or delays.
- A comprehensive electrical-synapse graph.
- Peptide diffusion, endocrine dynamics, glial dynamics, or state-dependent effective connectivity.
- Peripheral receptor organs and their transduction functions.
- NMJs, muscles, tendons, force production, living body mechanics, or the environment.
- The donor's hunger, hydration, arousal, circadian phase, mating history, memories, learned efficacy, hormone concentrations, or prior experience.

Some fine processes and synaptic partners are incomplete or uncertain, particularly at volume boundaries and in damaged sensory structures. “Complete CNS connectome” must not be translated into “lossless physiological model.”

### 4.3 Irrecoverable individual state

The exact source fly's dynamic and historical state is `I`. The project may construct a plausible population member conditioned on MaleCNS anatomy, but it cannot recover the original individual's mind, memories, physiology, or living body from EM.

## 5. Non-negotiable scientific rules

1. **Synapse count is not synaptic strength.** Use it as a structural prior, then fit or distribute functional conductance.
2. **Transmitter is not sufficient to determine sign.** Sign is a presynaptic-transmitter × postsynaptic-receptor property. Glutamate and acetylcholine do not have one universally valid sign.
3. **Do not make every neuron identical.** Use known graded/spiking classifications and uncertainty for unknown types.
4. **Do not call zero baseline an autonomous brain.** Autonomous runs require explicit sensory, tonic, spontaneous, and state-dependent drive.
5. **Keep morphology and synapse location available.** Point-neuron screening must not discard information needed for later compartmental models.
6. **Do not silently omit electrical, peptide, extrasynaptic, glial, or state effects.** An omission is an explicit model assumption with a sensitivity or replacement plan.
7. **Preserve the VNC and motor hierarchy.** A descending-neuron readout connected directly to a pretrained gait policy is an engineering control, not evidence that MaleCNS generated locomotion.
8. **Joint actuators are not muscles.** Position/torque commands from FlyGym or Flybody are temporary body interfaces unless the NMJ–muscle–tendon transformation is modeled and validated.
9. **Female anatomy is a prior, not an exact male body.** Record sex, strain, age, species, and specimen mismatches for every transferred dataset.
10. **Behavioral resemblance is insufficient.** Require neural, interface, body, causal-perturbation, and held-out validation.
11. **Do not hide stabilization.** Weight normalization, clipping, artificial inhibition, tonic current, regularization, controller assistance, and resets must be reported as `F` or `E`.
12. **Report ensembles, not a single arbitrary fly.** Predictions must be tested across plausible structural and parameter uncertainty.
13. **Separate peer-reviewed evidence from preprints and informal demonstrations.** Neither a repository demo nor task success upgrades an assumption to a measurement.
14. **Validate the interfaces, not only the components.** In particular: world→receptor, receptor→sensory activity, synapse→postsynaptic response, motor neuron→force, and force→motion.

## 6. Current assumption register

These are current starting decisions, not claims that the biology is solved.

| ID | Layer | Current decision | Class | Must be validated or replaced by |
|---|---|---|---|---|
| `DATA-01` | Connectome | Use MaleCNS v1.0 chemical topology and exact stable IDs. | `M` | Release checksums, schema tests, count/annotation audits. |
| `DATA-02` | Structural uncertainty | Keep strong edges fixed initially; retain weak edges and sample/drop them in sensitivity ensembles rather than deleting them silently. | `M/E` | Detector confidence, bilateral homologues, cross-connectome recurrence. |
| `DATA-03` | Cross-specimen mapping | Maintain explicit MaleCNS↔MANC/FANC/BANC/FlyWire/type crosswalks with confidence. | `P` | Morphology, type identity, side/segment and source evidence. |
| `DATA-04` | Runtime body universe | Use annotation `status=Traced`; the immutable source retains every segment, excluded segment edges/contacts are counted, and Assign/Anchor remain sensitivity alternatives. | `M/E` | V0 count, annotation-canary, motif and body-universe sensitivity audits. |
| `DATA-05` | Contact storage | Preserve official Feather files immutably and build lossless, versioned, sharded Parquet derivatives with reversible point IDs, explicit 8-nm coordinates, complete confidence/transmitter fields, and no biological threshold. | `M/E` | Contact/partner referential integrity, aggregate reconciliation, logical-digest reproducibility, and bounded-memory tests. |
| `ND-01` | Neuron formalism | Hybrid model: graded passive cells where established; LIF/AdEx for established spiking cells; competing variants for unknown types. | `P/F/E` | Type-resolved voltage, spike and calcium recordings. |
| `ND-02` | Membrane parameters | Use type-level distributions; use global Shiu-style values only as labelled fallbacks. | `P/F` | Resting voltage, input resistance, time constant, threshold and adaptation data. |
| `ND-03` | Edge polarity | Infer from transmitter plus receptor evidence; unresolved signs remain latent alternatives. | `M/P/F` | Receptor protein/transcript evidence and paired physiology. |
| `ND-04` | Synaptic strength | `synapse_count × type_pair_scale`, optionally adjusted for location/input resistance. | `M/F` | Unitary PSP/EPSC, perturbation and functional-imaging data. |
| `ND-05` | Kinetics and delay | Receptor-family kernels; path-length-aware conduction plus release latency. Unknowns receive explicit ranges. | `P/F` | Paired physiology and timing-sensitive circuit responses. |
| `ND-06` | Release and STP | Static deterministic transmission only for the cheapest baseline; add class-specific stochastic release/STP where evidence exists. | `P/F/E` | Failure, paired-pulse, sustained-response and recovery measurements. |
| `ND-07` | Electrical synapses | Omit globally at first, curate established pairs, and run omission sensitivity. | `P/E` | Paired recordings, innexin evidence and circuit perturbations. |
| `ND-08` | Baseline and noise | Fit type/region/state-conditioned tonic drive; separate structural, membrane, vesicle and observation noise. | `F/E` | Resting and behaving activity with a measurement model. |
| `ND-09` | Morphology | Whole-CNS point/reduced models first; retain skeleton/site data and upgrade behavior-critical cells to compartments. | `M/F/E` | Compartmental physiology and subcellular response timing. |
| `TRACKA-01` | Eon-like baseline | Run the complete traced aggregate graph with the named Shiu-style, central-relay, intent-drive and controller scaffolds recorded in `foundation-v0.5`. | `M/P/E` | Track A controls only; replace with Stage 2 dynamics and Track B sensory/motor pathways before scientific claims. |
| `STATE-01` | Initial condition | Default short-run state: awake, fed, water-replete, unmated, daytime, artificial laboratory-naive memory. | `E/I` | Explicit experiment-specific state or user decision. |
| `STATE-02` | Slow modulation | Freeze most peptide/endocrine variables in v1; later add only sourced ligand–receptor pathways. | `P/E` | State-dependent neural and behavioral recordings. |
| `LEARN-01` | Long-term learning | Disabled in v1. Later restrict first plasticity to experimentally supported dopamine-gated mushroom-body compartments. | `P/E` | Acquisition, recall, extinction and intervention datasets. |
| `SENS-01` | Sensor registry | Every sensory ID maps to organ, side, body coordinates, receptive axis/field, transducer, delay, source and confidence. | `M/P/F` | Anatomical registration and receptor recordings. |
| `SENS-02` | Vision | Start with luminance/motion, measured eye geometry where available, photoreceptor noise/adaptation, and FlyVis-like type priors. | `P/F` | Photoreceptor, L1–L5 and T4/T5 responses plus optic-flow behavior. |
| `SENS-03` | Olfaction | Small named odor panel; receptor-specific saturating/adaptive filters; independent left/right plume samples. | `P/F/E` | ORN/PN dose-response, timing and plume-navigation data. |
| `SENS-04` | Proprioception/touch | Generate claw/hook/club, load, joint-limit and bristle signals from body physics with delays/noise. | `P/F` | Passive/active tuning, reflex, ablation and perturbation data. |
| `SENS-05` | Deferred modalities | Taste, audition, wind, gravity, haltere, thermo/hygro and nociception remain explicit extension modules, not fake generic channels. | `P/E` | Modality-specific subsystem milestones. |
| `MOTOR-01` | Motor identity | Create versioned MaleCNS ID→MANC type→nerve/side/segment→muscle mappings; enable high-confidence targets first. | `M/P` | Anatomy, backfills, activation/silencing and muscle recordings. |
| `MOTOR-02` | NMJ/muscle | Provisional causal delay + saturating activation filter, with slow/intermediate/fast unit priors. | `P/F/E` | Spike→EMG/calcium/force, saturation, fatigue and recovery. |
| `MOTOR-03` | Actuator bridge | Initially decode motor populations to FlyGym-compatible commands, but keep this visibly marked as a non-biological bridge. | `E` | Incremental replacement by validated muscle–tendon units. |
| `BODY-01` | Body | Use FlyGym/NeuroMechFly as the initial walking substrate; retain published female-body mismatch in metadata. | `P/E` | Male morphometry, mass, joint and kinematic data. |
| `BODY-02` | Contact/adhesion | Published contact plus bounded stance-dependent adhesion as a provisional effective model. | `P/F/E` | Ground-reaction forces, slip, attachment and detachment data. |
| `NUM-01` | Timing | Multi-rate causal integration with explicit sensory/motor delay queues; never expose future or zero-delay simulator state. | `P/F/E` | Timestep-halving convergence and latency sweeps. |
| `VAL-01` | Uncertainty | Run parameter/model ensembles and retain train/validation separation. | `E` | Robust predictions across model families and held-out animals/tasks. |

## 7. V1 scope and non-goals

### 7.1 In scope

- One representative five-day-old adult male condition, not the historical source individual.
- MaleCNS v1.0 brain, neck and VNC topology.
- Flat-ground walking, rest, turning and perturbation recovery.
- Luminance/motion vision.
- Leg proprioception and touch.
- A deliberately small, chemically named odor set after basic walking closes successfully.
- Fixed internal state and fixed long-term synaptic weights.
- A provisional, explicit motor-population→body-actuator bridge.
- Reproducible uncertainty ensembles and intervention experiments.

### 7.2 Out of scope until prerequisites pass

- Claims of consciousness, subjective experience, a digital twin, or complete fly emulation.
- Recovering the donor's memories or physiological state.
- Full-color/polarization vision, complete olfaction or all peripheral modalities.
- Free flight, courtship, aggression, song, feeding, gut physiology, sleep/circadian cycles, development or ageing.
- Whole-body muscle fidelity.
- Unrestricted brain-wide STDP or generic reinforcement learning presented as fly learning.
- Replacing missing biology with an opaque policy and then attributing behavior to the connectome.

## 8. Required interface contracts

### 8.1 Connectome data

- Stable MaleCNS release and body IDs.
- Directed chemical contact counts plus individual synapse coordinates.
- Polyadic T-bar identity preserved.
- Edge/body confidence and boundary flags preserved.
- Transmitter probability preserved rather than prematurely collapsed.
- No irreversible thresholding in the canonical imported dataset.

### 8.2 Neural signals

- Every population declares its signal type: spike event, graded voltage, firing rate, transmitter release, or observation such as calcium.
- Conversions between signal types are explicit modules with units and provenance.
- Biological and simulator time are explicit; delays are causal.

### 8.3 Sensory signals

- World quantity and units are recorded before transduction.
- Left/right, organ, receptor class and body coordinates remain distinct.
- Self-motion updates vision, joint sensors, contact, antenna/odor sampling and other enabled modalities.

### 8.4 Motor signals

- Keep separate representations for motor-neuron activity, NMJ release, muscle activation, muscle force, joint torque and actuator command.
- Never use one field named `motor_output` across these boundaries.
- Ambiguous muscle mappings remain probabilistic or grouped; they are not silently resolved.

### 8.5 Experiment records

Each run must identify:

- code commit;
- MaleCNS and auxiliary dataset versions;
- parameter/assumption-set version;
- model family;
- random seed;
- initial physiological state;
- enabled omissions/scaffolds;
- training versus held-out inputs;
- validation metrics and artifacts.

## 9. Build sequence and exit gates

Do not attempt the whole fly at once.

### Stage 0 — Reproducible data foundation

Build importers, typed IDs, provenance records, confidence handling, graph/skeleton access and deterministic dataset checks.

Exit gate:

- Source files are checksummed and versioned.
- Counts and selected known motifs agree with the official release.
- Synapse locations, polyadic sites and confidence survive import.

### Stage 1 — Open-loop neural baseline

Reproduce selected published MaleCNS/FlyWire circuit-response experiments with a deliberately simple model. Implement the hybrid cell registry and uncertainty framework before scaling claims.

Exit gate:

- Known activation/ranking results are reproduced.
- Results are compared with shuffled-connectome and cell-type-only controls.
- Stability does not depend on undocumented clipping or resets.

### Stage 2 — Fitted neural dynamics

Add receptor-aware polarity, type-pair conductance, kinetics, delays, tonic drive and observation models. Upgrade selected cells to reduced compartments.

Exit gate:

- Held-out cellular, synaptic and circuit responses are predicted in time and amplitude, not merely activation order.
- Key predictions survive plausible parameter/model ensembles.

### Stage 3 — Sensory transduction and registration

Implement body-registered motion vision and leg proprioception/touch; add the small odor panel only after registration and plume assumptions are explicit.

Exit gate:

- Receptor and early-circuit tuning match published response distributions.
- Self-motion produces internally consistent optic flow and proprioception.
- Sensor delays and units pass automated tests.

### Stage 4 — Provisional closed-loop walking

Connect MaleCNS brain and VNC output to the body through the explicit actuator decoder. Retain a pretrained-controller-only condition as a negative/control baseline.

Exit gate:

- Stable walking, turning and perturbation recovery occur without bypassing the selected CNS pathway.
- Kinematics, contacts, ground reaction forces and intervention effects match held-out fly data within declared tolerances.
- Removing or shuffling relevant MaleCNS circuitry measurably degrades the corresponding behavior.

### Stage 5 — Neuromuscular replacement

Validate one motor unit and one leg before expanding to six legs. Replace actuator commands with NMJ, activation, Hill-type muscle/tendon and passive mechanics incrementally.

Exit gate:

- Single-MN spike→EMG/calcium→force timing and magnitude agree with experiments.
- Isolated-leg kinematics and force remain correct under load.
- Whole-body gait does not depend on compensatory hidden torque.

### Stage 6 — Behavioral expansion

Recommended order: robust walking → grooming → feeding → flight → social behavior. Each new behavior adds only the sensory, state and body modules it actually requires.

### Stage 7 — State and learning

Add hunger/hydration first, then selected neuromodulation and mushroom-body learning. Sleep, circadian and diffuse peptide dynamics come later.

Exit gate:

- State and learning effects predict held-out dose, timing, reversal and causal-intervention results.
- A new state variable is not accepted merely because it improves task reward.

## 10. Validation hierarchy

Every scientific release reports the highest tier it has passed:

| Tier | Required evidence |
|---|---|
| `V0 Structural` | Counts, motifs, identities, confidence sensitivity and cross-connectome comparisons. |
| `V1 Cellular` | Resting voltage, time constant, firing/adaptation or graded-response distributions. |
| `V2 Synaptic` | Sign, unitary amplitude, kinetics, failure and short-term plasticity for mapped pairs. |
| `V3 Circuit` | Held-out stimulation, silencing, epistasis and temporal response predictions. |
| `V4 Brain-wide` | Unseen spontaneous/stimulus activity with a valid calcium/electrophysiology observation model. |
| `V5 Motor interface` | Motor spike→muscle calcium/EMG/force and body state→proprioceptor response. |
| `V6 Embodied` | Joint distributions, contacts, ground-reaction forces, stability, energy and perturbation recovery. |
| `V7 Behavioral` | Held-out trajectories, choices, bout structure, state dependence and intervention effect sizes. |
| `V8 Generalization` | Unseen males, strains, environments and tasks. |

Mandatory controls where applicable:

- shuffled connectivity;
- cell-type-only versus exact individual graph;
- randomized or uniform weights;
- open-loop replay;
- controller-only embodiment;
- descending-neuron bypass versus full VNC;
- zero/alternative tonic drive;
- weak-edge dropout;
- sign, STP and gap-junction alternatives;
- timestep and solver convergence;
- held-out animals and perturbations.

Matching a trajectory is not sufficient if controls match it equally well.

## 11. Reuse existing work without inheriting its claims

| Work | Appropriate use | Do not claim |
|---|---|---|
| [MaleCNS](https://doi.org/10.1016/j.cell.2026.08.015) | Canonical male CNS topology, identity, morphology and chemical-contact prior. | Living dynamics, exact functional weights, body or source-fly state. |
| [Shiu et al. 2024](https://doi.org/10.1038/s41586-024-07763-9) | Minimal whole-brain LIF baseline and selected circuit tests. | Its global LIF constants or transmitter sign rules are MaleCNS physiology. |
| [Effectome framework](https://doi.org/10.1038/s41586-024-07982-0) | Treat connectome weights as priors for fitted causal effects. | Anatomy alone determines state-dependent causal strength. |
| [FlyVis](https://doi.org/10.1038/s41586-024-07939-3) | Visual type sharing, graded dynamics and task/physiology fitting precedent. | Its learned visual parameters cover the rest of the CNS or phototransduction. |
| [BrainTrace](https://doi.org/10.1038/s41467-026-68453-w) | Scalable fitting and evidence that background drive matters. | Region-level calcium fitting recovers cell/synapse physiology. |
| [NeuroMechFly/FlyGym v2](https://doi.org/10.1038/s41592-024-02497-y) | Initial walking body, contact, proprioception and benchmark framework. | Joint commands and ideal sensors are biological MN/muscle/receptor signals. |
| [Flybody](https://doi.org/10.1038/s41586-025-09029-4) | Later whole-body and flight physics baseline. | Female rigid-body geometry, learned control and phenomenological aero are an exact male. |
| [FlyMimic](https://openreview.net/forum?id=6lEjX1getx) | Partial muscle-level foreleg prior and validation ideas. | It is a complete six-leg or whole-body neuromuscular solution. |

Additional subsystem anchors:

- [Adult muscle motor-unit physiology](https://pmc.ncbi.nlm.nih.gov/articles/PMC7347388/)
- [Femoral chordotonal biomechanics](https://pmc.ncbi.nlm.nih.gov/articles/PMC10644877/)
- [DoOR olfactory response database](https://pmc.ncbi.nlm.nih.gov/articles/PMC4766438/)
- [Male gustatory connectome](https://doi.org/10.1016/j.cell.2026.08.016)
- [Adult mushroom-body connectome](https://doi.org/10.7554/eLife.62576)
- [Inter-individual connectome variability](https://doi.org/10.1038/s41586-024-07686-5)
- [Female brain-and-cord comparison, BANC](https://doi.org/10.1038/s41586-026-10735-w)

No peer-reviewed publication known at the evidence-review date combines MaleCNS v1.0, fitted whole-CNS dynamics, peripheral sensory transduction, motor-neuron-to-muscle dynamics, a physical body and closed-loop validation.

## 12. Agent workflow and drift prevention

Before starting work:

1. Read this file completely.
2. State which assumption IDs and validation tiers the task affects.
3. Inspect existing decisions, data provenance and tests before changing an interface.
4. Verify time-sensitive scientific claims using primary sources.
5. Distinguish a research baseline, an engineering scaffold and a biological claim.

While working:

1. Keep all units, delays, mappings and provenance machine-readable.
2. Prefer reversible adapters and registries at uncertain biological boundaries.
3. Preserve raw source information; derive thresholded or normalized views separately.
4. Add an ablation/control for every engineering shortcut that could explain success.
5. Never tune body physics to conceal a neural failure, or neural gains to conceal a body error, without reporting both.
6. Fit on one dataset or animal and validate on another whenever possible.

Before declaring completion:

1. Report what is implemented versus mocked, fitted, omitted or deferred.
2. Report the highest validation tier actually passed.
3. Run relevant controls and uncertainty sweeps.
4. Add or update tests and reproducibility metadata.
5. Update this document if—and only if—the accepted project direction, evidence boundary, assumption register or stage status changed.

## 13. Decision-change protocol

Do not silently replace a canonical decision. Propose a change with:

```yaml
decision_id: ADR-YYYY-NNN
date: YYYY-MM-DD
changes_assumptions: [ND-03, MOTOR-02]
old_decision: concise-text
new_decision: concise-text
reason: evidence-or-engineering-need
primary_sources: [DOI-or-stable-URL]
alternatives_tested: [ids]
validation_effect: tiers-or-tests
approved_by: user-or-project-owner
```

Once accepted, update the relevant table row and append a short entry below. Never rewrite history to make an assumption look measured in retrospect.

## 14. Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-09-04 | Define the target as a MaleCNS-constrained embodied sensorimotor model, not a digital twin. | The connectome is structural and the donor's dynamic/body state is absent. |
| 2026-09-04 | Make closed-loop flat-ground walking the first embodiment milestone. | It exercises brain, VNC, proprioception, motor output, contact and body physics without flight's additional sub-millisecond and aerodynamic gaps. |
| 2026-09-04 | Use hybrid graded/spiking dynamics with explicit uncertainty. | Adult fly cell types do not share one signaling regime or parameter set. |
| 2026-09-04 | Use a provisional actuator decoder, visibly separated from the biological motor interface. | Complete adult MN→NMJ→muscle→force data do not yet exist. |
| 2026-09-04 | Freeze most internal state and long-term plasticity in v1. | These variables are not recoverable from EM and would make early failures non-identifiable. |
| 2026-09-04 | Accept ADR-2026-001 for the initial local runtime and data stack. | The approved implementation plan fixes Python 3.12, direct PyGeNN/GeNN 5.4, official Feather to loss-aware sparse derivatives, FlyGym 2.1, ethyl acetate, local RTX 3060 execution and initial validation tolerances. |
| 2026-09-05 | Accept ADR-2026-003 for the contact-level storage and audit boundary. | Full contact tables remain immutable CPU-side evidence; bounded lossless derivatives support V0 without entering the GPU runtime graph. |
| 2026-09-06 | Accept `status=Traced` as the production neural-body universe; retain Assign/Anchor and all-segment alternatives for sensitivity analyses. | Expanding through Anchor changed traced contacts by 0.12% and edges by 0.24%, while all fixed sensorimotor annotation canaries remained uniquely traced. |
| 2026-09-07 | Accept the `foundation-v0.5` Track A full-graph engineering baseline and classify it as an offline prototype. | The 30-run matrix and required controls pass, but registered neural/body bridges remain non-biological and throughput misses the interactive target. |
| 2026-09-08 | Accept ADR-2026-006 and withdraw both the first V0 bundle and the Track A v1/v2 acceptance evidence. | An independent audit confirmed the bundle no longer validated and could not be rebuilt, that every Track A artifact came from an uncommitted tree, and that the behavioural narrative was largely a physics artefact. |
| 2026-09-07 | Accept ADR-2026-004 for the first Stage 2 projection-neuron physiology pack, recorded-cell split, and losses. | DM1 passive model fits and individual-cell DL5 F-I/uEPSC recordings provide complementary priors and held-out data while keeping sex, age, and cell-type transfer explicit. |
| 2026-09-08 | Accept ADR-2026-005 and freeze the ramp-aware PN revision before external scoring. | Reusing the consumed Gugel holdouts would leak validation; the single external Nanami trace is useful as a challenge but its unresolved current units and sample size prevent a V1 claim. |

## 15. Unresolved project-level choices

The following are deliberately not fixed yet. Agents may investigate them, but must not silently make them permanent:

- cell-type spiking/graded classification registry;
- physiological datasets and loss functions beyond the accepted first projection-neuron pack;
- weak-edge uncertainty model;
- male body scaling dataset;

Resolve these through evidence-backed decisions, not convenience alone.
