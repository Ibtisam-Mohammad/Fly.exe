# MaleCNS Virtual Fly — Agent Source of Truth

Status: canonical project direction  
Version: 1.17
Last evidence review: 2026-09-08
Last implementation audit: 2026-09-13
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
CURRENT_STAGE: Stage 2 fitted neural dynamics (active); the ADR-2026-006 evidence-chain repair is complete and V0 is reissued
DATA_STATUS: seven-artifact MaleCNS v1.0 flat-connectome profile checksum-locked; lossless contact derivative and independent dual-layout rebuilds validated
HIGHEST_VALIDATION_TIER: V0 Structural, reissued 2026-09-08 as bundle 20260908T060641Z_V0 under ADR-2026-006; unchanged by every DEMO-01 and DEMO-02 result, and the only tier names that exist are V0 to V8 in flysim.evidence.ValidationTier
ENGINEERING_STATUS: the Stage 2 exit gate is contract stage2-exit-gate-v4 and is 0 of 3 -- see STAGE2_EXIT_GATE below, which this line used to contradict by reporting the superseded v2 and its one passing leg; the uEPSC kernel is wrong in decay (0.463 against 0.30) and amplitude (13.6 pA median under), contact number is shown to move opposite to the published unitary-current scaling, the heterogeneous GeNN kernel is verified bit-identical to the homogeneous one on the full graph, and two registered MBON07 values are shown to depend on their measurement rule; NO tier is awarded anywhere, and the V1-limited and V2-restricted labels that appeared in four contracts and three documents were never members of the V0-to-V8 ladder and are removed (ADR-2026-018)
EON_SHOWCASE_STATUS: eon-showcase-v1 is retained as a reproducible limited preview but is withdrawn as the final public showcase under ADR-2026-020. Its frozen evaluator accepted 2 of 3 serial-story seeds, but it omitted its own 2.5 mm grooming gate; the hero records 8.477 mm. Navigation also uses a raw odour-gradient controller term and central relays, and two alleged causal controls are only serial-sequence dependency checks. The corrected evaluator now fails closed on a recorded behavioural violation. No tier changes
EON_SHOWCASE_V2_STATUS: eon-showcase-v2 is preregistered and blocked. It assembles three separately executed contracts: DEMO-01 visual-target approach at three frozen held-out targets, DEMO-02 grooming with G1-G6 including the 2.5 mm bout cap, and corrected MN9 feeding after a neural-only tarsal-taste operating-point search. Every component requires readout-ablated, stimulus-absent, command-replay and graph-free controller-only controls. The 60-90 s 1080p final cut must compare exact against ablation and say the chapters are separate. The validator is fail closed and awards no tier
EON_CINEMATIC_STATUS: the v1 1920x1080 H.264 cut remains checksum-locked as a historical limited preview, not the final showcase. Its simulation content is unchanged: it visibly distinguishes the 0.25 mm red food object from the engineered 1.0 mm thorax-proximity sucrose halo, but it inherits v1's bypasses and failed 8.477 mm grooming displacement. Video SHA-256 97a3790ed0ab6ffb2eca3c3e49f5f6807bda67cf1b6f489ed575252792c268b7
LIVE_MULTIFLY_STATUS: implementation candidate complete in the working tree under ADR-2026-021. The browser can place world stimuli but cannot write neural, motor or body state. Exact full-CNS states share one 25,563,197-edge connectivity allocation while retaining independent state for all 165,122 neurons. The 2.01-s dirty-tree engineering benchmark completed for 2 and 4 states; every state reduced distance to the calibrated target. Measured biological/wall rates were 0.167 and 0.080, so neither mode is real time. The artifact is /srv/flybrain-data/evidence/multifly/multifly-capacity-working-tree.json, SHA-256 8e64e3cecc00df9d9cec32e23208fa1619eb357edbd52a077462b12fc2b3d260. CPU preview is explicitly no-CNS; the shared collision-disc body is E; no tier, social-behaviour or cross-animal claim is awarded
SWARM_CINEMATIC_STATUS: swarm-cns-scientific-v2 supersedes the childish infographic-style v1 presentation without changing its recorded simulation. The 37.0-s 1920x1080 H.264 cut uses the restrained DEMO-01 instrument language: dominant released-soma CNS activity, a measured arena, continuous distance/readout/decoder traces and a real NeuroMechFly default-pose mesh as an explicitly labelled display proxy. Eight independent neural states, each retaining all 165,122 neurons, shared one 25,563,197-edge connectivity allocation; all 8 reduced target distance from about 13.0 mm to 1.24-3.38 mm, and the decoder received no target coordinates. Video SHA-256 c23de7ee15d057937c1e1649ec15d959080ae96983bc910740bfe49fca2a9d07. The source remains a dirty-tree presentation recording and is not evidence-grade; the mesh does not imply eight MuJoCo gait trajectories, and visual encoding, LIF dynamics, decoder and kinematic body remain P/E. This is cohort target approach, not biological swarming, social coordination or an added validation tier
SWARM3D_STATUS: the embodied twelve-fly showcase is complete under ADR-2026-023 and registers SWARM-01; the assumption set moves to foundation-v0.13. Twelve full NeuroMechFly bodies run in one compiled MuJoCo model with food spheres and pillars as real contact geoms, each fly executing all 165,122 neurons and all 25,563,197 edges every 15 ms coupling interval over one shared connectivity allocation, steering on two descending population rates and nothing else. The shipped recording is the third arena: 30.0 simulated seconds, 2,000 intervals, flies placed uniformly over a 30 mm disc and aimed at random under seed 11, 0.015x biological real time, 4.2 GB of device memory. Against an identical-seed stimulus-absent control: 12/12 flies walked against 0/12, 12/12 ended within 1 mm of an object's surface against 0/12, and 9,337 neurons spiked per fly per interval against 164. Eleven of twelve ended at food and one at a pillar; the encoder has no colour channel and separates them only by angular size. Closing distance to food is NOT the discriminator -- both runs end nearer food, +11.48 mm against +2.25 mm, because a standing body drifts along its own axis and headings are bounded so that food lies inside the mapped visual field -- and the video states this on screen rather than reporting the flattering half. Two discarded arenas are kept as measurements in ADR-2026-023: angular salience makes a near thin pillar beat far fat food, an inward-facing start geometry made the null control look successful at +3.99 mm, and targets beyond the retina map's declared -10 to +160 degree span receive 0.000-0.03 Hz and never steer. Two properties are checked rather than asserted: one fly through SwarmWorld and through Demo01VisualBody agree to 0.0 on all 133 qpos components, and the multi-object lamina encoder reproduces RetinotopicVisualEncoder for a single cue to 1.1e-13 Hz. The source tree was dirty and the run is presentation-grade, not evidence-grade; validation_tier_awarded is null in both the run summary and the render manifest; no social-behaviour, foraging, feeding or cross-animal claim is awarded and the project remains at V0 Structural
HISTORY_REWRITE_STATUS: the history has been rewritten twice, both times user-authorized. On 2026-09-12 the rewrite removed Co-authored-by trailers. On 2026-09-14, before the repository was made public, every author and committer email was rewritten from a work address to the owner's personal address across all 212 commits; the root tree hash is byte-identical before and after, so no file content changed. Both rewrites changed every pre-existing commit identifier. Artifact content hashes are unaffected, but any commit identifier quoted by narrative evidence, by a run manifest under the data root, or by an evidence bundle predates one or both rewrites and is a legacy identifier: it requires an explicit old-to-new mapping or a reissue before being used as a current Git-provenance claim. The pre-rewrite history was bundled before the 2026-09-14 pass and is not published
NEXT_GATE: decide cell-dynamics v0.4 for the MBON07 set (threshold -41.8 mV at 10 percent of peak slope or a bracket, membrane tau as 33 to 48 ms, refractory back to the fallback with the 15.8 ms bound noted); acquire new recordings of any kind, because after the uEPSC holdout the corpus contains no unconsumed cellular or synaptic recording at all; specifically a unit-resolved multi-animal current-step source for a projection-neuron type, an independent held-out set for a refitted uEPSC kernel whose contract does not gate on the peak time of peak-aligned traces, and a rate-dependent recording for ND-06 to be tested against the registered 0.79 release probability and 50 spikes/s depression onset. The Nanami units question is closed by ADR-2026-007 and that trace is retired as a scoring source
FOUNDATION_JOB: complete; bundle 20260908T060641Z_V0 pins a scoped DATA-* snapshot. The first bundle 20260906T065413Z_V0 is withdrawn because it pinned the mutable assumption register
FOUNDATION_REBUILD: complete; canonical, 262144-row-group, and 131072-row-group contact layouts are logically identical
NEURAL_PARITY: three-neuron fixture and 41-neuron Shiu transfer pass NumPy/Brian2/PyGeNN at 100 us; numerical evidence only
NEURAL_SIGN_VARIANT: Shiu transmitter-only regression is executable with explicit unresolved policies; never the physiological default
STAGE1_SHIU_REFERENCE: Edmond v3.0 archive checksum-locked; Figure 5g published-output analysis reproduced
STAGE1_SHIU_TRANSFER: immutable report 1290b8d717eaff49; 41 neurons, 129 edges; three-backend parity passes; global scale fails 0/8 held-out positive-response coverage; no V3 awarded
STAGE2_ND04_SCALE_CONFLICT: matching the 220 Hz grooming reference needs about 0.083 mV per contact and the 100 Hz reference about 0.153 mV, so no single global scale fits both; the reference is a whole-brain static LIF simulation and the circuit a one-hop 41-neuron subgraph, so the mismatch is structural (missing recurrent inhibition, different contact counts) and the earlier ND-06 depression hypothesis is withdrawn by ADR-2026-009 as a category error
STAGE1_REPRODUCTION_AFTER_FIXES: the grooming transfer parity improves to 1.1e-13 ms and the feeding screen is bit-identical, so both Stage 1 verdicts stand under the corrected code
STAGE2_SYNAPTIC_STRUCTURE: v2 corrects v1's citation (Kazama and Wilson 2008 is 10.1016/j.neuron.2008.02.030) and claim (unitary current rises with glomerular volume and ORN number, unitary depolarization is uniform at 6.19 mV); 50 glomeruli, 265 PNs; contacts per connection fall with ORN number (rho -0.232 connected, -0.456 anatomical), the opposite of the published current, so contact number does not carry the scale; total contacts per PN are nearly flat (rho 0.04 anatomical); median 43 contacts per connection is 0.84 of the published 51 release sites; derived per-contact scale 0.042-1.12 mV brackets the registered 0.2 mV; VM6 and VP glomeruli are dropped by the type-name rule
STAGE2_UEPSC_HOLDOUT: preregistered limits scored once on the five unconsumed chronic-exposure cells; decay fails at 0.463 against 0.30; the sign and peak-time passes carry no information because the source traces are peak-aligned and inward by selection, and the amplitude exclusion rested on a state-confound the source paper contradicts, so the 13.6 pA median underprediction is a model error; the corpus now has no unconsumed synaptic recording
STAGE2_EXIT_GATE: executable contract stage2-exit-gate-v4 (ADR-2026-011); the cellular and synaptic legs are retired to recorded priors because the raw traces they need are not public for anyone, and the scored legs are circuit, ensemble and structural, all failing, so the gate is 0 of 3; the structural leg is the bilateral ORN-to-PN symmetry test, whose criterion was registered at 564bdb9 before the run that scores it and which is rejected at p = 2.7e-31; retiring a leg is not passing it and the scored gate is narrower than the AGENTS section 9 statement; Stage 2 does not exit
GENN_SPIKE_TIME_CONVENTION: GeNN labels a spike with the start of the interval, NumPy and Brian2 with the end; circuit.py lacked the correction that neural_parity.py had, and it cancelled the axonal-delay defect at the readout so Stage 1 parity looked clean
STAGE2_CELLULAR_OBSERVABLES: contracts v1 and v2 (v2 reproduces every v1 value and adds diagnostics); MBON-alpha1 is the only unit-resolved current-step protocol in any registered source; tau_m 32.566 ms with the asymptote pinned to the pre-step baseline, 47.6 ms with it free; threshold -38.402 mV at a 10 mV/ms criterion that only 51 percent of spikes reach, -41.838 mV at 10 percent of peak slope; spikes 9-14 mV high so every count is detector-marginal; LN resting -50.79 mV whole-trace, -49.02 mV before the first spike; input resistance unmeasurable because every sweep is suprathreshold; no tier awarded
STAGE2_PN_ENSEMBLE: contract stage2-pn-uncertainty-ensemble-v1 meets VAL-01 five-by-four; 130 of 768 candidates accepted at a 25 percent tolerance spanning 26.6-fold refractory and 38.4-fold adaptation tau, zero-adaptation included; unscored because every registered F-I cell is consumed
STAGE2_NANAMI_UNITS: closed; step levels 3-10 are the dimensionless in-silico PQN model stimulus, the in vivo amplitudes are irrecoverable, and the reserved PN trace is retired as a scoring source
HETEROGENEOUS_CELLS: cell-dynamics-v0.3 binds MBON07 to a measured parameter set; GeNN promotes eight coefficients to per-neuron vars only when heterogeneous; both engines refuse the graded regime because no graded transmission model is registered; verified on the full graph 2026-09-08: fallback-everywhere per-neuron kernel is bit-identical to the homogeneous one (294,893 spikes, 0 of 165,122 neurons differ) and v0.3 changes MBON07 from 68/64/65/70 to 13/13/13/13 spikes with 9,972 downstream neurons following
STAGE2_REVIEW_2026_09_08: ADR-2026-009; every hash and implementation held, four interpretations were corrected (ND-06 conflict hypothesis, uEPSC criteria and amplitude exclusion, synaptic-structure citation and claim, cellular-leg sufficiency), three measurement rules were shown to carry assumptions (relaxation asymptote, upstroke criterion, LN resting window), and v2 contracts record all of it without touching a v1 artifact
ND06_PUBLISHED_POINT_ESTIMATES: Kazama and Wilson 2008 give release probability 0.79, 51 release sites per connection and depression onset near 50 spikes/s; registered in stage2-synaptic-structure-v2 as the values an ND-06 model is tested against; no trace is deposited
STAGE1_DYNAMICS_REGISTRY: male-cns-cell-dynamics-v0.1; 39 JO-F bodies have class-level spiking priors and two SAD093 bodies remain unresolved; hybrid execution disabled
STAGE1_SECOND_CIRCUIT: immutable review 3da6ffefaf9bdc6d; 101 mapped types x 30 trials; exact BA/AUROC 0.808; shuffled 0.500; cell-type-only 0.797; Stage 1 baseline passed but selected V3 specificity failed and no tier was awarded
DEMO01_STATUS: FULL-GRAPH CAUSAL EMBODIMENT on the visual-lateral contract; A5 and the word TOPOLOGY-SPECIFIC are SUSPENDED as of 2026-09-12, because the degree-preserving shuffle it used compares a 9 Hz network against a 56 Hz one and at matched activity a random rewiring drives the readout just as hard while reproducing none of its lateralisation (ADR-2026-018)
DEMO02_STATUS: no multi-seed claim is supported -- the runner executed seeds[0] of every registered seed set and wrote each seed to one artifact path until 2026-09-12; the feeding readout was biologically reversed and is corrected under MOTOR-07 with demo02-feeding-v2, which is NOT runnable until a registered operating-point search for the tarsal-taste to MN9 route exists; escape-legs is NO DEMONSTRATION and grooming is a route-level negative across 36 searched points
DEMO02_REQUIRED_BEFORE_QUOTING: one commit for the whole matrix, every required control present, entry-swapped implemented or struck; the acceptance evaluator now returns EVIDENCE CHAIN BROKEN when those fail
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

Track A checkpoint, 2026-09-08 (supersedes the withdrawn 2026-09-07 checkpoint): the full
165,122-body, 25,563,197-edge traced graph executes in direct PyGeNN through an exact
degree-bucketed sparse layout and a FlyGym 2.1/MuJoCo 3.9 body. The v3 matrix ran from clean
commit `4a061ac` at three food positions no earlier round had used, with every run recording
`git.dirty: false`. 29 of 30 runs complete the required sequence and all nine required controls
pass, but 0 of 30 clear the preregistered 2.5 mm grooming-displacement cap, so the milestone is
**not accepted**. The primary matrix is SHA-256
`bb5674a4ab942e0c80ce3a03b1d96df9a3f8cb428c8850e899a9284afac5a492` and the controls bundle is
SHA-256 `249353025c770080a5a96d347f5c3a8df6b30aef5ba300649b4a8faea740a0f5`. Steady-state
throughput is 0.332 minimum and 0.353 median biological seconds per wall second, about 71% of
the 0.5 target; the cold-start figure including graph load and GeNN build is 0.114 minimum. The
v1 and v2 matrices are withdrawn: they ran from an uncommitted tree, at positions a discarded
round had already used, with a shuffled-connectome control that could not fail, and with the
body settling inside the dust patch. Track A still injects DM1/DM4 and GNG588 central relays,
applies a 10x entry-path gain, drives DNg97 with an odor-gated intent bias, uses explicit
odor-gradient steering, and replays a published grooming trajectory through ideal joint
actuators. It is not autonomous connectome-generated behavior and awards no validation tier.

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

Stage 2 cellular checkpoint, 2026-09-08: ADR-2026-007 closes the Nanami stimulus-unit question
and the answer removes a planned evaluation. The step levels recorded as the in vivo protocol are
the list `I4` in the pinned plotting notebook, which sets the amplitudes of the in-silico PQN
model; the paper states that model is dimensionless. The in vivo amplitudes are never published,
so they are irrecoverable, and the extraction offset is 303.5 ms rather than 306.5 ms. The
reserved PN trace is retired as a scoring source, because without amplitudes no current-referenced
observable is comparable and its somatic spikes fall below the primary detection prominence. The
superseded manifest is left unchanged so the frozen dynamic-revision contract stays reproducible.

The other in vivo recordings redistributed with the same commit are locked as
`nanami-2024-invivo-cellular-pack-v1`, 47 checksum-verified files, and measured under contract
`stage2-cellular-observables-v1`. MBON-alpha1 is the only unit-resolved current-step protocol in
any registered source: five 1 s pulses at 2, 4, 6, 8 and 10 pA, matching the quoted Methods
exactly. It yields resting potential -60.354 mV, membrane time constant 32.566 ms at R squared
0.911, threshold -38.402 mV at a 10 mV/ms upstroke criterion, a monotonic F-I of 1, 10, 17, 21 and
24 Hz, and an adaptation ratio of 0.749. Input resistance is unmeasurable because every sweep is
suprathreshold. Four Seki et al. 2010 antennal-lobe LN animals give the only multi-animal
distribution in the project: resting potential median -50.789 mV. Two analysis rules were
corrected before any number was believed: a 50 ms spike-prominence window conflated the step
depolarization with spikes, and an ungated exponential fit reported a 268 ms time constant from a
relaxation that overshoots and drifts.

`cell-dynamics-v0.3` adds numeric parameter sets with per-value provenance and binds `MBON07` to
the measured set; the MaleCNS identity is confirmed from the annotation table, where `MBON07`
carries instance `MBON07(a1)`. Both engines now accept per-neuron membrane parameters. GeNN
promotes the eight kernel coefficients from shared parameters to per-neuron variables only when
the resolution is heterogeneous, so recorded Track A runs are bit-for-bit unchanged, and the model
identity hash covers the per-neuron values. Both engines refuse a graph containing graded-regime
neurons rather than substituting the spiking model. Against the full traced graph, 4 of 165,122
neurons across 11,752 cell types have a measured parameter set, a measured fraction of 0.0024%,
and engines report that fraction in run metadata. Stage 1 records the resolution but keeps
execution on the source-faithful LIF baseline. No V1 or V2 tier is awarded.

The VAL-01 ensemble was then built from the two registered training cells alone, by rejection
sampling over candidates within 25 percent of the best training loss and by varying the unobserved
onset state across seeds. It reaches the required five samples by four seeds and exposes that the
family is not constrained: 130 of 768 candidates are accepted, spanning 3.7-fold in rheobase,
26.6-fold in refractory period and 38.4-fold in adaptation time constant, and the accepted set
includes a zero-adaptation model. The ensemble mean scores 18.847 Hz training RMSE against the
7.630 Hz previously reported, which shows that figure was a property of scoring each per-cell best
fit on the cell that selected it. The ensemble is unscored because every registered F-I recording
is consumed.

Stage 2 synaptic checkpoint, 2026-09-08: ADR-2026-008. Rerunning the Stage 1 grooming transfer
after the axonal-delay repair moved GeNN one step earlier as predicted but left the parity error
at exactly 0.1 ms. The cause is a second defect: GeNN labels a spike with the start of the
integration interval and the NumPy and Brian2 adapters with the end, and `circuit.py` lacked the
correction `neural_parity.py` already carried. The two errors cancelled at the readout, so the
original Stage 1 parity pass was the product of two compensating defects. With both fixed the
41-neuron transfer agrees across three backends to 1.1e-13 ms with zero timing outliers.

Contract `stage2-synaptic-structure-v1` tests `ND-04` against the published homeostatic-matching
claim across 50 glomeruli and 265 projection neurons. Total contacts per projection neuron vary
more than converging ORN count (CV 0.695 against 0.603), so contact number does not implement the
matching, though the direction is weakly right at Spearman -0.232. The median of median contacts
per connection is 43, inside the published several-dozen estimate: the first quantitative
agreement between MaleCNS structure and an independent physiological measurement in this project.
Dividing the published 5 to 7 mV unitary EPSP by the measured contacts gives 0.042 to 1.12 mV per
contact, and the registered 0.2 mV engineering fallback lies inside that range. The assumption
register is not bumped, because `ND-04`'s decision is unchanged and a derived prior is a result.

Contract `stage2-uepsc-kinetics-holdout-v1` fixed numeric feature limits before opening the five
unconsumed chronic-exposure cells, which is the V2 blocker the post-freeze review recorded. Sign
passes at a 27.689 pA minimum inward peak and peak time passes at 0.300 ms against a 1.0 ms
limit, but decay fails at 0.463 median fractional error against a 0.30 limit, with four of five
cells over. Peak amplitude was preregistered as reported-but-not-gated because the source paper's
subject is that exposure changes this synapse. After this evaluation the corpus contains no
unconsumed cellular or synaptic recording at all.

Receptor-aware polarity and release/STP evidence have no registered source. The MaleCNS
`receptorType` column is gustatory receptor identity, 752 of 211,577 bodies across three values,
and must not be read as postsynaptic receptor expression; no connectome-mapped receptor resource
exists. Contract `stage2-exit-gate-v1` reads each Stage 2 exit leg from a checksum-pinned
artifact: cellular passes, synaptic, circuit and ensemble fail, and Stage 2 does not exit.

Stage 2 review checkpoint, 2026-09-08: ADR-2026-009. An independent review recomputed every
Stage 2 number from the locked data and read the source papers. Every pinned hash, logical
hash and statistical implementation held. Four interpretations did not. The ND-06 depression
hypothesis for the two-frequency contact-scale conflict is withdrawn: the reference is a
whole-brain static simulation and the circuit a one-hop 41-neuron subgraph, so the mismatch is
structural. The uEPSC peak-time and sign criteria were vacuous on peak-aligned, inward traces,
and the amplitude exclusion rested on a state-confound the source paper contradicts, so the
kernel is wrong in decay and amplitude. `stage2-synaptic-structure-v1` cited
`10.1016/j.neuron.2008.04.024` (Kruglikov and Rudy 2008) for Kazama and Wilson 2008
(`10.1016/j.neuron.2008.02.030`) and stated the published claim with the wrong sign; v2
restates it, and contacts per connection fall with ORN number (rho -0.232 connected, -0.456
anatomical) while the published unitary current rises with it. The one passing exit-gate leg
passes at ratio 1.064, worse than the two-cell training mean. Three cellular rules embed
assumptions: the surviving membrane time constant is 32.6 ms with the asymptote pinned and
47.6 ms free; the 10 mV/ms threshold criterion sits at the median peak slope so only 51
percent of spikes reach it and a 10 percent-of-slope rule gives -41.8 mV against -38.4 mV;
the LN resting median moves from -50.79 to -49.02 mV when read before the first spike. v2
contracts for cellular observables, synaptic structure and the exit gate record all of this
without touching a v1 artifact, and the heterogeneous GeNN kernel is verified on the full
graph: bit-identical to the homogeneous kernel with the fallback everywhere, and changing
MBON07 from 68/64/65/70 to 13/13/13/13 spikes under cell-dynamics-v0.3. The v0.4 registry
revision those brackets imply is left to the project owner.

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
| `ND-03` | Presynaptic transmitter identity | Per-body consensus transmitter from the connectome annotation; unclear stays unresolved. It does **not** resolve an edge's sign. | `M/P` | Verified per-cell-type transmitter assignments at a stated confidence floor — but only **169** MaleCNS cell types join, 89 optic lobe and **zero** antennal lobe, so `ND-03` cannot be validated where stages 2 and 3 use it. Preregistered as `stage2-nd03-transmitter-validation-v1`; unopened. |
| `ND-10` | Receptor identity and edge polarity | Sign is a function of `ND-03` plus the postsynaptic receptor; where receptor evidence is absent the sign stays unresolved and is carried as a latent alternative, never defaulted. A transmitter-only sign rule is a named regression control. | `P/F` | Domain- and partner-resolved receptor localisation with paired physiology. Not available at scale. |
| `ND-04` | Synaptic strength | `synapse_count × type_pair_scale`, optionally adjusted for location/input resistance. | `M/F` | Unitary PSP/EPSC, perturbation and functional-imaging data. |
| `ND-05` | Kinetics and delay | Receptor-family kernels; path-length-aware conduction plus release latency. Unknowns receive explicit ranges. | `P/F` | Paired physiology and timing-sensitive circuit responses. |
| `ND-06` | Release and STP | Static deterministic transmission only for the cheapest baseline; add class-specific stochastic release/STP where evidence exists. | `P/F/E` | Failure, paired-pulse, sustained-response and recovery measurements. |
| `ND-07` | Electrical synapses | Omit globally at first, curate established pairs, and run omission sensitivity. One curation candidate is named: the giant fibre onto `TTMn` and `PSI`, **blocked** until its source is verified in this repository, and never to be replaced by raising a gain. | `P/E` | Paired recordings, innexin evidence and circuit perturbations. |
| `ND-08` | Baseline and noise | Fit type/region/state-conditioned tonic drive; separate structural, membrane, vesicle and observation noise. | `F/E` | Resting and behaving activity with a measurement model. |
| `ND-09` | Morphology | Whole-CNS point/reduced models first; retain skeleton/site data and upgrade behavior-critical cells to compartments. | `M/F/E` | Compartmental physiology and subcellular response timing. |
| `TRACKA-01` | Eon-like baseline | Run the complete traced aggregate graph with the named Shiu-style, central-relay, intent-drive and controller scaffolds recorded in `foundation-v0.5`. | `M/P/E` | Track A controls only; replace with Stage 2 dynamics and Track B sensory/motor pathways before scientific claims. |
| `STATE-01` | Initial condition | Default short-run state: awake, fed, water-replete, unmated, daytime, artificial laboratory-naive memory. | `E/I` | Explicit experiment-specific state or user decision. |
| `STATE-02` | Slow modulation | Freeze most peptide/endocrine variables in v1; later add only sourced ligand–receptor pathways. | `P/E` | State-dependent neural and behavioral recordings. |
| `LEARN-01` | Long-term learning | Disabled in v1. Later restrict first plasticity to experimentally supported dopamine-gated mushroom-body compartments. | `P/E` | Acquisition, recall, extinction and intervention datasets. |
| `SENS-01` | Sensor registry | Every sensory ID maps to organ, side, body coordinates, receptive axis/field, transducer, delay, source and confidence. | `M/P/F` | Anatomical registration and receptor recordings. |
| `SENS-02` | Vision | Start with luminance/motion, measured eye geometry where available, photoreceptor noise/adaptation, and FlyVis-like type priors. | `P/F` | Photoreceptor, L1–L5 and T4/T5 responses plus optic-flow behavior. |
| `SENS-03` | Olfaction | Small named odor panel; receptor-specific saturating/adaptive filters; independent left/right plume samples. | `P/F/E` | ORN/PN dose-response, timing and plume-navigation data. |
| `SENS-04` | Proprioception/touch | Generate claw/hook/club, load, joint-limit and bristle signals from body physics with delays/noise. Antennal deflection is read from `l_pedicel`/`r_pedicel` `qpos`, so the grooming stimulus has units and a side; the dust/contamination scalar leaves the critical path. | `P/F` | Passive/active tuning, reflex, ablation and perturbation data. |
| `SENS-05` | Modality scope, per modality | Every labelled sense is a named channel carrying an organ and a side, classified `real` (a MuJoCo referent), `declared` (an invented field, named as one) or `absent`. Taste is no longer deferred: it is a side-resolved leg-taste-bristle module. Thermo, hygro and nociception are **absent because no world quantity exists to transduce** — not because their route scores are low. `generic_substitution_allowed: false` is binding, so `SENSOR_SUCROSE` is retired as a decoder input. | `P/E` | Modality-specific milestones; the per-channel live-edge gate. |
| `MOTOR-01` | Motor identity | Create versioned MaleCNS ID→MANC type→nerve/side/segment→muscle mappings; enable high-confidence targets first. | `M/P` | Anatomy, backfills, activation/silencing and muscle recordings. |
| `MOTOR-02` | NMJ/muscle | Provisional causal delay + saturating activation filter, with slow/intermediate/fast unit priors. | `P/F/E` | Spike→EMG/calcium/force, saturation, fatigue and recovery. |
| `MOTOR-03` | Actuator bridge | Initially decode motor populations to FlyGym-compatible commands, but keep this visibly marked as a non-biological bridge. Six commands: forward, yaw, grooming intensity, proboscis extension, jump extension and wing depression. The last two stay separate so each effector's contribution to a takeoff remains measurable from the trace. | `E` | Incremental replacement by validated muscle–tendon units. |
| `BODY-01` | Body | Use FlyGym/NeuroMechFly as the initial walking substrate; retain published female-body mismatch in metadata. The actuated DOF set is declared **per experiment**, and station-keeping gains are re-derived per set and never inherited: DEMO-01's integral gain, its 2.294 mm residual drift and the +11.5° drift bearing that chose its cue placement are properties of a 42-actuator plant. | `P/E` | Male morphometry, mass, joint and kinematic data. |
| `BODY-02` | Contact/adhesion | Published contact plus bounded stance-dependent adhesion as a provisional effective model. Adhesion may be conditioned on replayed limb kinematics; adhesion gain, contact stiffness, force limits and floor damping remain frozen. | `P/F/E` | Ground-reaction forces, slip, attachment and detachment data. |
| `NUM-01` | Timing | Multi-rate causal integration with explicit sensory/motor delay queues; never expose future or zero-delay simulator state. | `P/F/E` | Timestep-halving convergence and latency sweeps. |
| `VAL-01` | Uncertainty | Run parameter/model ensembles and retain train/validation separation. | `E` | Robust predictions across model families and held-out animals/tasks. |
| `MOTOR-05` | Station keeping | Stance-conditioned channel selection during a grooming bout, attempt 2. Fixes a defect where two of six control channels were computed and discarded while the integral accumulated their error. | `E` | The registered MOTOR-05 commit-reveal validation draw. |
| `MOTOR-06` | Graded commands | Grooming blend and proboscis extension scale with the decoded drive rather than latching on. | `E` | The dose-response criteria in the behaviour contracts. |
| `DEMO-02` | Behaviour scenarios | Antennal grooming, proboscis extension and escape takeoff, as three separate preregistered demonstrations. Feeding is a pose, not ingestion; takeoff carries zero aerodynamic force. Awards no tier. | `E` | Per-behaviour acceptance contracts. |
| `DEMO-03` | Sensory encoder | One saturating transducer per channel, baseline rate zero, delay quantised to the 15 ms coupling interval. | `P/E` | The live-edge gate and each contract's stimulus-absent control. |

## 7. V1 scope and non-goals

### 7.1 In scope

- One representative five-day-old adult male condition, not the historical source individual.
- MaleCNS v1.0 brain, neck and VNC topology.
- Flat-ground walking, rest, turning and perturbation recovery.
- Luminance/motion vision.
- Leg proprioception and touch.
- Antennal grooming from a mechanical antennal stimulus; a proboscis-extension pose from leg taste contact; a ballistic escape takeoff from a visual object.
- A deliberately small, chemically named odor set after basic walking closes successfully.
- Fixed internal state and fixed long-term synaptic weights.
- A provisional, explicit motor-population→body-actuator bridge.
- Reproducible uncertainty ensembles and intervention experiments.

### 7.2 Out of scope until prerequisites pass

- Claims of consciousness, subjective experience, a digital twin, or complete fly emulation.
- Recovering the donor's memories or physiological state.
- Full-color/polarization vision, complete olfaction or all peripheral modalities.
- Free flight, courtship, aggression, song, gut physiology, ingestion, pharyngeal pumping, any feeding claim beyond a proboscis-extension pose, sleep/circadian cycles, development or ageing. A ballistic takeoff with zero aerodynamic force is not flight and does not move free flight into scope: this body has no `density`, no `viscosity` and no fluid geoms, so wing motion generates no lift.
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

**Amended 2026-09-09 by ADR-2026-011.** The cellular and synaptic legs are **retired as
gates** and demoted to recorded priors: still parameterised, still checksum-verified and
still reported at every evaluation, no longer scored. They require raw patch-clamp traces
that are not public for anyone — confirmed absent for Kazama and Wilson 2008 and 2009,
Gouwens and Wilson 2009, and Nagel and Wilson 2015 — so they measured the availability of
somebody else's unpublished data rather than this model.

The scored gate is now **circuit, ensemble and structural**, executed by
`stage2-exit-gate-v4`, and it is **0 of 3**. A structural leg may only enter at a criterion
registered before the test that scores it was run.

Two things must be said whenever Stage 2 is described:

- **The scored gate is narrower than the statement above.** It scores one of the three
  response types the statement requires. Any claim of Stage 2 progress must name which legs
  were scored.
- **Retiring a leg is not passing it.** The cellular and synaptic questions are open, and
  each retired leg records the condition that reinstates it, at a criterion at least as
  strict as the one it had.

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
| 2026-09-08 | Accept ADR-2026-007, retire the reserved Nanami PN trace as a scoring source, and lock the in vivo cellular pack. | The stimulus levels recorded as the in vivo protocol are the dimensionless in-silico model input, the real amplitudes are never published, and the trace's somatic spikes fall below the detection prominence, so the planned sealed evaluation cannot be run at all. |
| 2026-09-08 | Accept ADR-2026-008, make the Stage 2 exit gate executable and record that one of four legs passes. | Three legs could be evaluated from locked data; doing so turned two open assertions into measured results, failed the uEPSC kernel on a preregistered decay limit, and exposed a one-step GeNN spike-time defect that a compensating error had hidden. |
| 2026-09-08 | Accept ADR-2026-009, the independent Stage 2 review: withdraw the ND-06 scale-conflict hypothesis, correct the uEPSC and synaptic-structure interpretations, issue v2 contracts with diagnostics and caveats, and verify the heterogeneous GeNN kernel. | Every checksum and implementation held, but four interpretations were wrong in kind and three measurement rules embedded assumptions that moved registered values by 3.4 mV and 15 ms; recording them now stops Stage 3 from inheriting them. |
| 2026-09-11 | Accept ADR-2026-016: resolve every labelled sense into an organ-and-side channel, and build antennal grooming, a proboscis-extension pose and a zero-aerodynamic escape takeoff on the three strongest. | A degree-matched-null survey put grooming at 106x, the giant fibre at 82.9x monosynaptically and labellar taste at 48.6x, and a live-edge gate then showed every entry population those need is 99 to 100 percent live while the photoreceptors are 0 percent. The register was still reading "deferred" for senses the code was about to drive, and had never supplied the organ and side SENS-01 requires. |
| 2026-09-11 | Record DEMO-02 as three negatives and stop: no behaviour demonstrated, no video, no tier change, and the operating point deliberately not tuned to rescue it. | All three readouts stayed below threshold at DEMO-01's frozen operating point, with 30.2 percent of the grooming readout's input contacts active and zero spikes out. Tuning the network after seeing a behavioural outcome would convert every frozen contract into a fitted result. A registered neural-criteria search is the declared next step. |
| 2026-09-12 | Correct the DEMO-02 escape negative: it was a sample of one. A registered neural-criteria search found 11 of 36 operating points that drive the giant fibre cleanly, and the behaviour contract remains INVALID on four criteria, three of which are specification defects I wrote. | Reporting "the route does not carry" from a single untested operating point is the same overclaim this project exists to avoid, pointed pessimistically. DEMO-01 needed 108 candidates for its own route; escape had zero. The parameter responsible was one DEMO-01 selected at the top of its own grid, which is the signature of a range that was too narrow. |
| 2026-09-12 | Verify DEMO-01 rather than trust it: its build key omitted the seed and the wiring, so its topology control could have executed the exact graph. Re-ran all four variants; the verdict survives unchanged. | The one passing experiment in the project was probably fine and provably unverifiable. It is now verifiable: the shuffle has its own key, its own wiring digest and its own kernel hash. |
| 2026-09-12 | Withhold the wing command from the escape decoder (ADR-2026-017). Plant unchanged, digest unchanged. | The wings generate 0.219 mm against a 0.204-0.211 mm noise floor and invert the fly: 180 degrees of roll against jump-only's 17.1. Commanding an effector whose physics is absent from the model is modelling something we chose not to simulate. |
| 2026-09-12 | Do not use the grooming operating point the search selected, and record that my own N2 weakened DEMO-01's C5 while claiming it was carried over unchanged. | The single passing candidate's selectivity is +1.000 from one spike against zero, which is verbatim the outcome C5 exists to prevent. Under C5 as DEMO-01 actually wrote it, zero of 36 pass. |
| 2026-09-12 | Narrow every topology claim from responsiveness to selectivity, and require regime matching. | A shuffle at matched activity drives the giant fibre as hard as the real connectome (104 and 78 against 120 and 163) and does not reproduce its lateralisation (swing -0.098 against +2.000). A5 and E7 measure the wrong quantity. |

## 15. Unresolved project-level choices

The following are deliberately not fixed yet. Agents may investigate them, but must not silently make them permanent:

- cell-type spiking/graded classification registry — still open. ADR-2026-007 measured a six-fold spread in somatic spike amplitude across four classes, which constrains the observation model but cannot classify a cell as graded, because axonal initiation followed by somatic attenuation produces the same measurement. Engines refuse the graded regime rather than substituting a spiking model;
- physiological datasets and loss functions beyond the accepted first projection-neuron pack;
- which measurement rule the MBON07 parameter set should carry in cell-dynamics v0.4: the
  review (ADR-2026-009) left the time constant as a 33 to 48 ms bracket, the threshold at
  -38.4 or -41.8 mV depending on the upstroke rule, and the refractory period as an upper
  bound rather than a value;
- weak-edge uncertainty model;
- male body scaling dataset;

Resolve these through evidence-backed decisions, not convenience alone.
