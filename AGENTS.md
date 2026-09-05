# MaleCNS Virtual Fly — Agent Source of Truth

Status: canonical project direction  
Version: 1.1
Last evidence review: 2026-09-04  
Last implementation audit: 2026-09-05
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
CURRENT_STAGE: Stage 0 — reproducible data foundation (active; exit gate not passed)
DATA_STATUS: seven-artifact MaleCNS v1.0 flat-connectome profile checksum-locked; contact normalization and structural audits pending
HIGHEST_VALIDATION_TIER: none (pre-V0)
ENGINEERING_STATUS: zero-weight GeNN topology load and controller-only/Eon-like scaffolds only
NEXT_GATE: full-profile lock -> streaming contact/polyad audit -> morphology and universe sensitivity -> V0 review
FOUNDATION_JOB: resumable bounded-memory contact normalization active under the Windows host supervisor; strict contact audit follows
FIRST_EMBODIMENT: closed-loop flat-ground walking
NEURAL_BASELINE: hybrid graded/spiking with explicit uncertainty
INITIAL_STATE: awake, fed, water-replete, unmated, daytime, artificial naive memory
BODY_BASELINE: FlyGym/NeuroMechFly with explicit female-body and actuator mismatch
PLASTICITY_V1: disabled
SUCCESS_RULE: behavioral resemblance alone is insufficient
```

Operational checkpoint, 2026-09-05: the aggregate MaleCNS foundation is executable, but
neither the zero-functional-weight GeNN load nor the controller-only and semantic-population
demonstrations are biological validation. “Full profile” refers only to the seven registered
flat-connectome artifacts; it does not include the skeleton collections, segmentation volumes,
or neuPrint database. Download completion alone does not pass Stage 0 or V0.

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
| `DATA-04` | Runtime body universe | Provisional starter derivative uses annotation `status=Traced`; the immutable source retains every segment, and excluded segment edges/contacts are counted. | `M/E` | Compare Traced against Traced+Assign+Anchor and review official count/motif sensitivity before acceptance. |
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

## 15. Unresolved project-level choices

The following are deliberately not fixed yet. Agents may investigate them, but must not silently make them permanent:

- cell-type spiking/graded classification registry;
- physiological datasets and loss functions for parameter fitting;
- weak-edge uncertainty model;
- male body scaling dataset;
- runtime body universe: retain only `Traced` bodies or include `Assign` and `Anchor` statuses after sensitivity review;

Resolve these through evidence-backed decisions, not convenience alone.
