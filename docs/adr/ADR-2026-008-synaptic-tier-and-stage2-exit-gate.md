# ADR-2026-008 — Synaptic-tier evidence and an executable Stage 2 exit gate

Status: accepted

Date: 2026-09-08

Changes assumptions: none

```yaml
decision_id: ADR-2026-008
date: 2026-09-08
changes_assumptions: []
old_decision: >-
  The Stage 2 exit gate existed only as prose in AGENTS section 9. The frozen unitary-EPSC
  kernel had passed an aggregate RMSE gate with no preregistered feature threshold, which the
  post-freeze review recorded as a V2 blocker. ND-04 asserted that contact count is not
  synaptic strength without evidence either way, and the registered 0.2 mV per contact had no
  physiological justification at all. Stage 1 backend parity was recorded as passing.
new_decision: >-
  The exit gate is an executable contract that reads checksum-pinned artifacts and reports each
  leg separately. Numeric feature limits for the uEPSC kernel were preregistered and then
  scored once on the five unconsumed cells. The ORN-to-PN contact structure of the whole locked
  graph is tested against the published homeostatic-matching claim, and the per-contact scale
  that claim implies is derived. A second one-step GeNN defect, masked by the first, is fixed.
reason: >-
  Three of the four Stage 2 exit legs could be evaluated with data already locked, and doing so
  turned two open assertions into measured results and exposed a real timing defect.
primary_sources:
  - https://doi.org/10.1016/j.neuron.2008.04.024
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC3933953/
  - https://doi.org/10.7554/eLife.85443
alternatives_tested:
  - gating the uEPSC test on peak amplitude as well as kinetics
  - bumping the assumption register to record the derived per-contact scale against ND-04
  - sourcing receptor expression per connectome cell type for receptor-aware polarity
validation_effect: >-
  One of four Stage 2 exit legs passes. The synaptic leg fails on decay kinetics at 0.463
  fractional error against a preregistered 0.30 limit. No tier is awarded and Stage 2 does not
  exit.
approved_by: project-owner
```

## A second one-step GeNN defect, which the first was hiding

ADR-2026-006 fixed the axonal-delay defect and predicted that rerunning the Stage 1 grooming
transfer "would move the GeNN spike times one step earlier and remove the offset". The first
half happened: readout first-spike times moved from 59.0 and 26.1 ms to 58.9 and 26.0 ms. The
second half did not. The parity error against NumPy stayed at exactly 0.1 ms.

The cause is independent of synaptic delay. **GeNN labels a spike with the start of the
integration interval that produced it, while the NumPy oracle and the Brian2 adapter both label
it with the end.** `neural_parity.run_genn` already corrected for this and said so in a comment;
the Stage 1 circuit adapter in `circuit.py` did not. The two off-by-one errors cancelled at the
readout, which is why the original Stage 1 report recorded backend parity as passing.

That is worth stating plainly: the previously recorded Stage 1 parity pass was the product of two
compensating defects, and fixing only the documented one would have left a real disagreement in
place. With both fixed, the 41-neuron transfer agrees across NumPy, Brian2 and GeNN to
**1.1e-13 ms with zero timing outliers**, down from 0.1 ms.

The small three-neuron parity fixture was never affected, because it used the already-corrected
adapter. Its numbers are unchanged.

## Does contact number carry the type-pair scale?

`ND-04` says `contact_count * type_pair_scale` and `contact_count_is_strength: false`. Until now
that was an assertion. Contract `stage2-synaptic-structure-v1` tests it against the published
claim that ORN-to-PN connections are homeostatically matched, across **50 glomeruli and 265
projection neurons** of the V0-locked graph.

| Hypothesis | Result | Supports structural matching |
|---|---|---|
| H1 total contacts per PN vary less than ORN count | CV 0.695 vs 0.603 | **no** |
| H2 contacts per connection fall as ORN count rises | Spearman rho −0.232 | weakly yes |
| H3 contacts per connection are "several dozen" | median of medians 43 | consistent |

The compensation is real but partial. The extremes make it visible: DA1 has 150 converging ORNs
at a median 11 contacts per connection, while VA2 has 74 ORNs at 88 contacts. The direction is
right, but total drive per PN still varies more across glomeruli than ORN number does, so
**contact number alone does not implement the matching**. If the published matching is real, it
must be carried by release probability or receptor density, which is exactly `ND-04`'s position.
The assertion now has evidence behind it.

H3 is the first quantitative agreement between MaleCNS structure and an independent physiological
measurement in this project: a median of 43 contacts per connection sits inside the "several
dozen" the paired recordings estimated.

## The first physically grounded per-contact scale

Dividing the published 5 to 7 mV unitary EPSP by the measured contacts per connection gives, per
glomerulus, a per-contact scale of **0.042 to 1.12 mV**, median 0.117 mV at the low end of the
published unitary range and 0.164 mV at the high end.

The registered engineering fallback is `0.2 mV` per contact, taken from a whole-brain model of a
different connectome. It **lies inside the derived range**, close to the upper end of the median
band. That is the first physiological justification the value has had. It remains an engineering
fallback: a scale derived from a cross-specimen unitary amplitude applied to all 50 glomeruli is
a prior, not a measurement, and the 27-fold spread across glomeruli is precisely why a single
global number is wrong.

The assumption register is deliberately **not** bumped for this. `ND-04`'s decision has not
changed — the scale must still be fitted, and a derived prior is a result, which belongs in an
immutable evidence artifact rather than in the register of decisions.

## The unitary-EPSC kernel fails its preregistered kinetics limit

The post-freeze feature review recorded "No preregistered feature-level acceptance thresholds" as
a V2 blocker. Contract `stage2-uepsc-kinetics-holdout-v1` fixes them and was committed before the
five unconsumed chronic-exposure cells were opened.

| Criterion | Limit | Observed | Result |
|---|---|---|---|
| Sign: every held-out waveform inward | > 0 | minimum peak 27.689 pA | **pass** |
| Peak time, median absolute error | ≤ 1.0 ms | 0.300 ms | **pass** |
| Decay time, median absolute fractional error | ≤ 0.30 | **0.463** | **fail** |

Per-cell decay errors are 0.463, 0.881, 0.519, 0.350 and 0.282; four of five exceed the limit. The
kernel gets polarity and timing right and the decay wrong by roughly a factor of one and a half.

Peak amplitude was preregistered as reported-but-not-gated, because the source paper's subject is
that chronic exposure changes this synapse, so an amplitude mismatch on exposure-state cells
cannot distinguish model error from a real state difference. For the record the kernel
underpredicts all five, by 3.2 to 25.8 pA, median 13.6 pA.

Both thresholds came from the measurement grid and the fitted decay constant, not from the model
errors already seen on the consumed solvent cells. Those errors were 0.300 ms and −1.200, −3.300
and +5.000 ms, and were deliberately not used.

## Two V2 requirements have no source at all

**Receptor-aware polarity (`ND-03`).** The MaleCNS annotation table has a `receptorType` column,
which on inspection is *gustatory receptor identity* — 752 of 211,577 bodies, three values
(`putative_ppk23`, `putative_ppk25`, `putative_IR52b`). It is not postsynaptic neurotransmitter
receptor expression and must not be used as such. Nor does a connectome-mapped receptor resource
exist: the FlyWire whole-brain literature states directly that neurotransmitter predictions
"lack neuropeptide predictions and receptor expression data, an important gap given that
neurotransmitters such as glutamate can be excitatory or inhibitory." Receptor-aware polarity is
therefore blocked on data, and the transmitter-only regression stays labelled as a regression.

**Release failure and short-term plasticity (`ND-06`).** Kazama and Wilson report high vesicular
release probability and strong short-term depression at this synapse, but qualitatively; no
paired-pulse ratio, failure distribution or recovery time constant is published in a form that
can be checksum-locked, and no dataset is deposited. V2 cannot be reached without it.

## The exit gate is now executable

`stage2-exit-gate-v1` reads each leg out of a checksum-pinned artifact rather than restating it,
so the gate cannot drift from the evidence and flips on its own when the missing evidence
arrives.

| Leg | Source | Observed | Passes |
|---|---|---|---|
| cellular | chronic-condition F-I sub-gate | true | **yes** |
| synaptic | uEPSC kinetics holdout | false | no |
| circuit | grooming transfer held-out coverage | 0.0, needs ≥ 0.8 | no |
| ensemble | VAL-01 ensemble held-out evaluation | false | no |

One leg of four. Stage 2 does not exit, and a partial pass is recorded so the remaining work
stays visible rather than so the stage can be declared complete. The cellular leg that does pass
carries its own caveat in the contract: it scores firing rate only, on state-shifted cells from
the same paper.

## Alternatives considered

- **Gate the uEPSC test on amplitude too.** Rejected: the held-out cells are the exposure
  condition the source paper is about, so an amplitude gate would be uninterpretable whichever
  way it went.
- **Bump the assumption register with the derived scale.** Rejected: `ND-04`'s decision is
  unchanged and would have forced a set-id bump through four configs for a result that belongs
  in an evidence artifact.
- **Source receptor expression per cell type.** Attempted and blocked; see above.

## Validation effect

Two V2 legs move from unevaluated to evaluated, one passing and one failing against
preregistered numeric limits. The Stage 2 exit gate becomes re-runnable and reports one of four
legs passing. A masked one-step timing defect is removed from every GeNN circuit result. No tier
is awarded, and after this evaluation the corpus contains **no unconsumed synaptic recording**.
