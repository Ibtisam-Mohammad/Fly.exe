# ADR-2026-009 — Independent review of Stage 2: corrections, diagnostics and a verified engine path

Status: accepted

Date: 2026-09-08

Changes assumptions: none

```yaml
decision_id: ADR-2026-009
date: 2026-09-08
changes_assumptions: []
old_decision: >-
  ADR-2026-007 and ADR-2026-008 recorded the first measured cellular observables, a synaptic
  structure test of ND-04 against "the published homeostatic-matching claim", a preregistered
  uEPSC kinetics holdout in which sign and peak time passed and decay failed, an executable
  exit gate with one leg of four passing, and a hypothesis that ND-06 short-term depression
  would reconcile a two-frequency contact-scale conflict. Both engines were said to carry
  per-neuron parameters; the GeNN path had not been executed.
new_decision: >-
  Several of those statements are corrected. The scale-conflict hypothesis is withdrawn as a
  category error. The uEPSC peak-time and sign criteria are recorded as uninformative and the
  amplitude exclusion as resting on a premise the source paper contradicts. The synaptic
  structure contract is reissued as v2 with the correct citation and the claim Kazama and
  Wilson 2008 actually make. The cellular contract is reissued as v2 with diagnostics that
  expose the assumptions inside the registered MBON07 values and correct the LN resting
  potential. The exit gate is reissued as v2 with the missing sufficiency caveats. The
  heterogeneous GeNN kernel is executed on the full graph and shown to reproduce the
  homogeneous kernel exactly when every neuron carries the fallback set.
reason: >-
  A review that recomputed every Stage 2 number from the locked data found the code sound and
  the checksums intact, but found the interpretation wrong in four places and the measurement
  rules dependent on unstated assumptions in three. Recording them is what keeps the next
  stage from building on them.
primary_sources:
  - https://doi.org/10.1016/j.neuron.2008.02.030
  - https://doi.org/10.7554/eLife.85443
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC3933953/
  - https://doi.org/10.1038/s41586-024-07763-9
alternatives_tested:
  - editing the v1 artifacts or contracts in place instead of issuing v2 contracts
  - revising the cell-dynamics registry values now rather than recording what a v0.4 must carry
  - re-gating the uEPSC holdout on amplitude after the held-out cells were opened
validation_effect: >-
  No tier is awarded. The Stage 2 exit gate still passes one leg of four, and that one leg is
  now recorded as weaker than a cohort-mean predictor. The heterogeneous execution path is
  verified on hardware. Two measured values in the MBON07 parameter set are shown to depend on
  the rule that produced them by 3.4 mV and by 15 ms.
approved_by: project-owner
```

## What was reviewed and how

Every Stage 2 source module, contract, evidence artifact and document from ADR-2026-004 through
ADR-2026-008 was read fresh, and every number that could be recomputed from the locked data was
recomputed independently: the MBON-alpha1 spike counts with a fixed-threshold detector, the
relaxation time constant with a three-parameter fit, the threshold under seven upstroke
criteria, the LN resting level in three windows, every synaptic-structure statistic under two
definitions of convergence, the uEPSC peak positions of all twelve source traces, and the file
and logical hashes of every artifact the exit gate pins. The two source papers behind the
synaptic tier were read for the sentences the contracts attribute to them.

What held: every pinned hash matches its file, every logical hash recomputes, the rank
correlation and coefficient-of-variation implementations are correct, the second one-step GeNN
fix is correct and both Stage 1 circuits reproduce, the consumed-cell guard sits at the read,
and the derived per-contact scale and the contact-per-connection count are computed as
described. Everything below is what did not hold.

## 1. The contact-scale "conflict" cannot be explained by short-term depression

ADR-2026-008 read the ND-04 sweep against the derived scale and proposed that missing
short-term depression, `ND-06`, would let one contact scale fit both the 100 Hz and 220 Hz
reference points. That reasoning is withdrawn.

The reference is Shiu et al.'s archived **whole-brain static LIF simulation** on FlyWire, with no
depression in it. The transferred circuit is a **one-hop induced subgraph of 41 neurons**: 39
mapped inputs and two readouts, 129 edges. A mechanism absent from both models cannot be what
makes them disagree. The over-response at high drive is structural before it is biophysical:
the subgraph carries none of the recurrent and lateral inhibition the whole-brain reference
recruits at high input rates, and the two connectomes differ in contact number on the mapped
path. The observation that no single scale reproduces both frequencies stands as a fact about
that subgraph against that reference; the ND-06 prediction built on it does not. The retrieval
key `STAGE2_ND04_SCALE_CONFLICT` and the evidence document are corrected accordingly.

## 2. Two of the three uEPSC criteria carry no information, and the third fails for the reason it seems to

Every one of the twelve recorded uEPSC waveforms in the Gugel et al. source data peaks on sample
499, at 49.9005 ms. The paper says why: *"individual uEPSCs from each condition were aligned by
their peaks and averaged."* The preregistered peak-time criterion therefore measured the
alignment convention and the kernel's own onset, and the constant 0.300 ms error on every cell
is the distance between the fitted onset plus rise and that alignment point. The sign criterion
is satisfied by selection: the source published inward unitary currents. Only the decay
criterion tested the kernel, and it failed.

The amplitude criterion was excluded on the argument that chronic exposure changes this synapse,
so an amplitude mismatch on exposed cells would be uninterpretable. The source paper says the
opposite: *"Average DL5 uEPSC amplitudes and response kinetics were indistinguishable between
solvent and E2-hexenal exposed flies,"* and likewise for the F-I curves and input resistance.
The exclusion therefore rested on a premise the source contradicts. Read honestly, the kernel
underpredicts every held-out cell, by 3.2 to 25.8 pA and 13.6 pA at the median, against a
published mean near 40 pA, and its 15 ms decay overshoots the published half-decay of about 7 ms.
The decay failure is a model error, not a state effect. The verdict is therefore worse than
ADR-2026-008 recorded: the kernel is wrong in decay and in amplitude, and right only in a sign it
could not have got wrong.

The test is not re-run and not re-gated. Its five cells were opened once under the preregistered
rule, and moving the amplitude criterion into the gate after seeing the data would be exactly the
practice the preregistration exists to prevent. The correction lives here and in the exit-gate v2
caveats; `evaluate_uepsc_kinetics_holdout` gains an optional check that reports when every
held-out peak shares one sample, so the next contract cannot register a vacuous timing criterion
without saying so.

## 3. The synaptic-structure contract cited the wrong paper and tested a claim it does not make

`stage2-synaptic-structure-v1` gives `https://doi.org/10.1016/j.neuron.2008.04.024` as Kazama and
Wilson 2008. That DOI resolves to Kruglikov and Rudy 2008, *Perisomatic GABA release and
thalamocortical integration onto neocortical excitatory cells are regulated by neuromodulators*.
Kazama and Wilson 2008 is `10.1016/j.neuron.2008.02.030`, which the cell-dynamics registry already
cites correctly for `DM4_adPN`.

The contract stated the published claim as "glomeruli with fewer converging ORNs have stronger
unitary connections". The paper reports the reverse direction for unitary current: *"Unitary
EPSC amplitude is correlated with the glomerular volume occupied by the PN dendritic tuft
(Pearson's r = 0.75, p < 10^-4, n = 39),"* alongside *"a strong linear correlation between
glomerular volume and the number of ORNs presynaptic to each glomerulus."* The matching in the
title is between unitary current and dendritic size or input resistance, producing a roughly
uniform unitary depolarization of 6.19 ± 0.45 mV (n = 23) across the four glomeruli recorded,
DM6, VM2, DL5 and DM4. It is not a claim about uniform total drive. H1 and H2 of v1 therefore
tested a proposition the source does not make. The "several dozen" bracket of 24 to 100 was this
project's operationalisation; the paper gives a mean of 51 release sites per connection from
quantal analysis, with release probability 0.79 and short-term depression above about 50 spikes
per second.

`stage2-synaptic-structure-v2` restates the claim, cites the right paper, and reruns the same
structural statistics on the same locked graph with the sign the source implies:

| Statistic | Connected definition | Anatomical definition |
|---|---:|---:|
| CV of converging ORN count across 50 glomeruli | 0.603 | 0.687 |
| CV of total ORN contacts per PN | 0.695 | 0.695 |
| Spearman rho, ORN count vs median contacts per connection | −0.232 | −0.456 |
| Spearman rho, ORN count vs total contacts per PN | +0.243 | +0.040 |

Contacts per connection **fall** as ORN number rises, the opposite of the published unitary
current, so contact number does not implement the published scaling; per-contact efficacy would
have to rise with ORN number to reproduce it. Under the anatomical definition total contacts per
PN are essentially uncorrelated with ORN number, so the spread that v1 read as a failure of
matching is, under the definition closer to the published variable, a flat total. The median of
43 contacts per connection is 0.84 of the published 51 release sites. The type-name rule drops
VM6, whose receptor types are `ORN_VM6l/m/v` while its projection types are `VM6_*PN`, and the VP
glomeruli, which have no `ORN_` type; v2 names them. The v2 numbers were seen before v2 was
written, and the contract says so: it is a corrected restatement on structural data, not a
blind test, and it consumes no recording.

## 4. The one passing exit-gate leg is worse than a cohort-mean predictor

The cellular leg reads `cellular_fi_subgate_pass` from the chronic-condition holdout, whose
preregistered criterion is a normalized error ratio of at most 1.2. The observed ratio is 1.064:
the frozen family's held-out RMSE is 13.17 Hz and predicting the two-cell training mean gives
12.38 Hz. The model is 6% worse than an average of its own training data. The pass shows the
family lies within the biological spread; it does not show prediction. The source paper also
reports F-I curves indistinguishable between conditions, so the "state shift" this leg was
credited with surviving is nominal. Exit-gate v2 records both. A future cellular criterion
should require the ratio to be below one.

## 5. Two registered MBON07 values depend on the rule that produced them

`stage2-cellular-observables-v2` reproduces every v1 primary value exactly and adds three
diagnostics. What they show:

**Membrane time constant.** The one accepted relaxation pins its asymptote to the pre-step
baseline of −57.58 mV. A free-asymptote fit over the same 200 ms after step offset settles at
−60.16 mV with a time constant of **47.6 ms**, against the gated **32.6 ms**. The pre-step
baselines of the five sweeps span 5.7 mV, so the pin is an assumption the data do not support.
Both fits have R² near 0.9. The honest value is a bracket, 33 to 48 ms.

**Spike threshold.** The median peak upstroke velocity of the 73 detected spikes is 10.03 mV/ms,
and the primary criterion is 10 mV/ms. Only 51% of spikes reach it, and those that do reach it
near their steepest point. A threshold at 10% of each spike's own peak slope gives **−41.8 mV**
against the registered **−38.4 mV**.

**Detector marginality.** Somatic spike height is 8.9 to 13.8 mV at a 10 mV prominence. The
in-step counts are 1, 10, 17, 21, 24 at the primary rule, 0, 10, 15, 23, 30 at a fixed −35 mV
crossing, and 1, 21, 26, 29, 40 at 5 mV prominence, which also fires on the step onset. The
shortest interspike interval is 15.8 ms or 14.4 ms depending on the detector. The v1 contract
called the first two "agreeing"; they differ by 25% at 10 pA. At 20 mV prominence the detector
misses every spike, the code then treats sweeps with 24 to 33 mV deflections as passive, and the
sensitivity block reports a 28.1 ms charging constant and a 2360 MΩ input resistance that must
not be quoted; v2 reports the deflection beside them so the hazard is visible.

**LN resting potential.** Each LN trial carries an unpublished stimulus from about 1.0 to 4.0 s
and ten seconds of after-hyperpolarization. The whole-trace masked median is that
post-stimulus level. Before the first spike of each trial the four animals rest at −47.55,
−48.38, −50.59 and −49.67 mV, median **−49.02 mV**, against the recorded −50.79 mV.

**Refractory period.** The registered 15.8 ms is the shortest interspike interval at the highest
tested current, an upper bound the registry labels `M/E` and uses as a value; it caps the
modelled rate at 63 Hz. It is a modelling choice, not a measurement.

None of these values is changed in `cell-dynamics-v0.3`. Changing a registered set alters every
run that binds it and is the project owner's call. A v0.4 should carry the threshold from the
fraction-of-slope rule or as a bracket, the time constant as 33 to 48 ms, and the refractory
period as the fallback with the 15.8 ms bound in the note.

## 6. ND-06 has published point estimates the tier never registered

ADR-2026-008 said release failure and short-term plasticity are described "only qualitatively"
with nothing lockable. Kazama and Wilson 2008 publish a release probability of 0.79, a mean of 51
release sites per connection, and depression onset above about 50 spikes per second. No trace
is deposited, but these are point estimates of the same standing as the 5 to 7 mV unitary
amplitude the synaptic tier already uses. v2 registers them as the values `ND-06` is tested
against.

## 7. The heterogeneous GeNN path is now executed, not only shipped

ADR-2026-007 said both engines carry per-neuron parameters. The GeNN path had never been run.
`scripts/review_heterogeneous_genn_check.py` builds three full-graph kernels and drives each with
the grooming JO-F population at 200 Hz for 300 ms at seed 1:

| Kernel | Total spikes | MBON07 spikes | Neurons differing from homogeneous |
|---|---:|---|---:|
| homogeneous, shared constants | 294,893 | 68, 64, 65, 70 | — |
| per-neuron vars, fallback everywhere | 294,893 | 68, 64, 65, 70 | **0 of 165,122** |
| per-neuron vars, `cell-dynamics-v0.3` | 294,328 | 13, 13, 13, 13 | 9,976 |

The promoted kernel is bit-identical to the compiled-constant kernel when the values match, and
the v0.3 resolution changes only the four MBON07 neurons directly, with 9,972 downstream neurons
following. Builds take 20 to 35 s and the 300 ms interval simulates in under a second. This is
an engineering verification, not evidence, and it awards nothing.

## 8. Smaller defects fixed

- The exit-gate circuit leg's 0.8 coverage threshold was set by the contract without derivation,
  and positive-response coverage is weaker than the gate statement's "time and amplitude". v2
  says so.
- `evaluate_uepsc_kinetics_holdout` hardcoded a 40 ms baseline the contract also stated; it now
  reads the contract, refuses a waveform whose decay is undefined instead of failing it silently,
  and can report the peak-alignment check.
- `CellParameterSet.from_mapping` raised `KeyError` before its own missing-key message.
- Result identifiers were hardcoded to `-v1`; they now follow the contract's `experiment_id`.

## Immutable results

| Artifact | File SHA-256 | Logical SHA-256 |
|---|---|---|
| `cellular-observables-v2.json` | `7cbacca867818a3927b83bfe75cc8fbaf99b03768de8b57e8cd9bacd497c482b` | `d6dc1c03331c814fc2f45f5239aec4eb33b75a9dce0193b53edf42a72f9afaa7` |
| `synaptic-structure-v2.json` | `0d55155008591c4ea389e8d055b452c0cffbc53a290296a2e66d45dd636a137c` | `4a18b4a7857af142d08405367784262da561f7b085567e8fb932df4f5478b99c` |
| `exit-gate-v2.json` | `45d946b0ff358727f4b56478fe68270e1dab836c41d04e3e579333715e8c5164` | `901354be3adc140c796232e65f31ee91e1e954975b93252a466b0ba1e1a78f34` |

Every v1 artifact is left on disk unchanged. Every v1 per-sweep value reproduces inside v2, and a
v1 contract run against the current code produces the v1 output, because every diagnostic is
enabled by a contract field the v1 contracts do not have.

## Alternatives considered

- **Edit the v1 artifacts and contracts in place.** Rejected: the exit gate pins them by hash and
  they are the record of what was believed before the review.
- **Revise the MBON07 registry values now.** Deferred: the review establishes brackets, and which
  rule the registry should carry is a decision that changes runs.
- **Re-gate the uEPSC test on amplitude.** Rejected: the cells were opened once under a
  preregistered rule, and a post hoc gate is the failure mode preregistration exists to prevent.

## Validation effect

No tier is awarded and none is withdrawn, since none was held. The Stage 2 exit gate still passes
one leg of four, and that leg is now recorded as passing a criterion a cohort-mean predictor
satisfies better. The synaptic verdict is corrected from "timing right, decay wrong" to "decay
and amplitude wrong". The blockers of ADR-2026-008 stand, with two changes: `ND-06` has published
point estimates to test against, and the cellular registry has a v0.4 to decide.
