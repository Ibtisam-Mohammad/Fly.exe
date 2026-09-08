# ADR-2026-010 — Cell-dynamics v0.4, a strict cellular exit criterion, and ORN→PN depression from a fit to the depression trajectory

Status: accepted

Date: 2026-09-08

Changes assumptions: ND-06

```yaml
decision_id: ADR-2026-010
date: 2026-09-08
changes_assumptions: [ND-06]
old_decision: >-
  ADR-2026-009 left two decisions open. First, the MBON07 alpha1 parameter values were shown to
  depend on the measurement rule that produced them by 3.4 mV in threshold and 15 ms in
  membrane time constant, and the ADR deferred which rule a v0.4 registry should adopt. Second,
  the cellular leg of the Stage 2 exit gate compared a normalised error against a cohort-mean
  predictor without stating what would count as passing. Separately, ND-06 permitted
  class-specific short-term plasticity only where evidence existed, and no registry existed.
new_decision: >-
  Registry v0.4 adopts the free-asymptote membrane time constant of 47.577 ms, the minimum-ISI
  refractory period of 15.8 ms, and the 10-percent-slope threshold of -41.838 mV, each chosen by
  a stated criterion rather than by convention, and carries the full rule-dependent spread of
  every value alongside it. The cellular exit criterion is a normalised error ratio strictly
  below 1.0 against the cohort-mean predictor. A short-term-plasticity registry is issued that
  binds ORN-to-uniglomerular-PN edges to a depression-only Tsodyks-Markram rule with both
  parameters taken from Nagel, Hong and Wilson 2015, which fits that exact equation to measured
  EPSC amplitude versus stimulus number.
reason: >-
  The first two were decidable from data already in the repository: an LIF F-I consistency
  ranking separates the time-constant and refractory candidates decisively, and measurement
  definedness separates the threshold candidates that the fit cannot. The third came from
  reading a source the corpus did not yet contain, which turned out to publish both parameters
  the registry had left unresolved and to contradict the quantity the first draft had bound to
  utilisation.
primary_sources:
  - https://doi.org/10.1038/nn.3895
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC4289142/
  - https://doi.org/10.1016/j.neuron.2008.02.030
  - https://doi.org/10.7554/eLife.34550
alternatives_tested:
  - pinning the membrane time constant to the 32.566 ms two-parameter fit used by v0.3
  - the 10 mV/ms upstroke threshold of -38.402 mV instead of the 10-percent-slope value
  - the 2.2 ms fallback refractory period instead of the observed minimum interspike interval
  - reading Kazama and Wilson's release probability of 0.79 as the Tsodyks-Markram utilisation
  - leaving the recovery time constant unresolved inside an engineering search window
validation_effect: >-
  No tier is awarded and no gate changes verdict. The cellular leg of the exit gate now has a
  criterion it can fail, and it does fail: the normalised error ratio is not below 1.0. ND-06
  moves from "no quantitative evidence registered" to "one synapse class carries fitted
  parameters from a published recording", still with no MaleCNS measurement behind it, so the
  rule remains a labelled executable alternative that awards nothing.
approved_by: project-owner
```

## 1. The MBON07 parameter rule (decision 1)

ADR-2026-009 showed that three of the registered MBON07 alpha1 values change with the rule used
to extract them, and declined to pick. Picking by convention would have hidden the problem, so
each value was decided against a stated criterion.

**The criterion.** An LIF neuron's steady firing rate under constant current has a closed form,
`rate = 1000 / (t_ref + tau * ln(R*I / (R*I - (V_th - V_rest))))`. The cell's own current-step
family therefore over-determines the parameter set: given a candidate `(tau, V_th, t_ref)` there
is one best-fitting input resistance, and the residual against the observed F-I curve measures
whether that candidate is self-consistent. All eight combinations of the two time constants, two
thresholds and two refractory periods were ranked against three independent spike detectors, so
the ranking does not depend on how spikes were counted.

**Result.** The free-asymptote time constant of 47.577 ms beat the pinned 32.566 ms under every
detector — RMSE 1.80 against 4.48 Hz, 1.61 against 3.06 Hz, and 2.46 against 2.72 Hz — and the
minimum-ISI refractory period of 15.8 ms beat the 2.2 ms fallback by 1.80 against 5.51 Hz. Those
two are decided on fit quality, and the margins are not close.

**The threshold is formally unidentifiable from this fit**, and that is the honest finding rather
than a limitation to work around. Threshold and input resistance enter the F-I expression only
through `R*I` and `V_th - V_rest`, so raising the threshold and raising the resistance trade off
along a ridge of equal residual: the two candidates fit equally well at 6.01 and 5.07 GOhm
respectively. It is therefore decided on measurement definedness instead. The 10-percent-slope
threshold of -41.838 mV is defined for every spike in the record; the 10 mV/ms threshold of
-38.402 mV is reached by only 51 percent of spikes, so it is a statement about half the data.
v0.4 adopts -41.838 mV.

**What the fit exposes about input resistance, recorded as a defect and not resolved.** Every
self-consistent candidate implies an input resistance between 4.4 and 6.4 GOhm, and the observed
2 pA rheobase requires at least 9.26 GOhm at the adopted threshold. The parameter set is
therefore internally inconsistent with the cell's own rheobase by roughly a factor of two, and
`value_notes` in the registry says so. Published whole-cell input resistances for *Drosophila*
central neurons are far lower still — Nagel and colleagues set `R_m` to 800 MOhm in their PN
model, an order of magnitude below the value this fit implies — which makes the implied
resistance a fitting artifact of the single-compartment LIF form rather than a measurement of
the cell. A conductance-based or multi-compartment form is what would resolve it; nothing in
v0.4 claims it is resolved.

Every value in v0.4 carries its rule-dependent range in `value_ranges`, which the loader
validates contains the registered value, so no downstream report can quote a value as tighter
than the measurement rules left it.

## 2. The cellular exit criterion (decision 2)

The cellular leg now reads `metrics.normalized_error_ratio` and requires it strictly below 1.0.
The ratio is the model's normalised error divided by that of a cohort-mean predictor, so the
criterion states the weakest defensible claim: the model must beat predicting every cell by the
population mean. `evaluate_stage2_exit_gate` gained an `expect_below` branch that compares with
a strict inequality, so a ratio of exactly 1.0 fails.

The leg fails under this criterion, at an observed ratio of 1.0644: the frozen family's
held-out RMSE is 13.17 Hz against 12.38 Hz for the two-cell training mean, so the model is 6.4
percent worse than predicting every cell by the cohort average. The whole gate now fails all
four legs where it previously failed three.

**This is a post-hoc tightening and must be read as one.** The holdout's own preregistered limit
was a ratio of at most 1.2, and 1.064 met it; the v1 and v2 gates read a boolean recording that
pass. Nothing about the model got worse and no new measurement was taken. What changed is that
ADR-2026-009 had already recorded in prose that a ratio above 1.0 means the model loses to a
cohort mean, and v3 makes that prose the criterion instead of leaving it as a caveat under a
leg marked passed. Choosing a stricter criterion than the one preregistered is only defensible
if it is labelled, so it is labelled here: the 1.2 limit was met, the 1.0 limit was chosen
afterwards, and the reason is that a model which cannot beat its own training mean should not
be reported as clearing a leg of an exit gate.

The gate result is `evidence/stage2/exit-gate-v3.json`, logical SHA-256
`520e4dae713970bf2f41f0e8cde7fb3304b2fc31769f2f4783f9642dd8a3521d`, with the synaptic leg false,
the circuit leg at 0.0 against a 0.8 floor, and the ensemble leg false. The contract is issued as
`stage2-exit-gate-v3.json`; v1 and v2 and every artifact under them are untouched.

## 3. ND-06: the first quantitative short-term-plasticity rule

The registry binds ORN-to-uniglomerular-PN edges within a glomerulus to a depression-only
Tsodyks-Markram rule: a spike delivers `weight * x` and then `x <- x - U*x`, with
`dx/dt = (1 - x)/tau` between spikes, normalised so the first spike after rest is undepressed
and every static result reproduces bit-for-bit when no edge depresses.

**The first draft bound the wrong quantity to `U`.** It used Kazama and Wilson's estimated
release probability of 0.79 and left `tau` unresolved inside an invented [25, 500] ms window.
Nagel, Hong and Wilson 2015 was then read against its open-access full text and turned out to
fit this registry's exact equation — the paper states its `r` "governs the rate of depression and
is equivalent to (1 - f)", and its Equation 1 is `A <- f*A` on a spike with
`A <- A + (1-A)dt/tau` between spikes, which is term for term the rule above with `U = r` and
`tau_rec = tau`. It publishes both parameters, from fits to measured EPSC amplitude versus
stimulus number in 19 PNs from 19 flies in DM6 or VM2.

Two things followed. The published recovery time constant of 893 ms lies **outside** the invented
500 ms ceiling, so the first draft's own validation would have refused the measured value. And
the two candidate utilisations are separated by data rather than by preference:

| reading | U | tau (ms) | predicted 2nd/1st EPSC at 10 Hz |
|---|---|---|---|
| Nagel Fig 1c, whole EPSC, control saline | 0.22 | 893 | 0.8033 |
| Kazama & Wilson release probability read as U | 0.79 | 893 | 0.2937 |

The 0.22 value was fitted to the 10 Hz trajectory itself, so 0.8033 is what that trajectory
shows; the 0.79 reading mispredicts it by a factor of 2.735. Kazama and Wilson estimated `p` from
trial-to-trial variance, and mapping it onto `U` needs the further assumptions of one vesicle per
release site and no recovery within the train. The directly fitted value is adopted, and the
variance-derived reading stays in the registry under `competing_reading` rather than being
dropped.

The registered spread comes from the three published fits of the same equation to the same
synapse — whole EPSC `f = 0.78, tau = 893 ms`; IMI-resistant fast component `f = 0.77,
tau = 1006 ms`; curare-resistant slow component `f = 0.91, tau = 629 ms` — giving
`U` in [0.09, 0.23] and `tau` in [629, 1006] ms. It is a spread across a pharmacological
decomposition, not a confidence interval, and the loader refuses a `U` or a `tau` outside it.
The paired parameters must not be mixed across fits.

Because the registry was corrected before it was ever committed, no artifact was produced under
the superseded values; `revision_note` records the correction so the history is not silently
clean.

**What this does not establish.** No MaleCNS synapse was measured, no recording independent of
Nagel and colleagues has been located, and the adopted whole-EPSC value collapses a genuinely
two-component response onto one resource variable. The rule awards no tier. Its one open
prediction is the 0.8033 paired-pulse ratio against a recording not used in the fit — which is
not evidence today, since the value was fitted to the trajectory that ratio comes from.

Depression is implemented on the NumPy circuit runner only. The Brian2 and GeNN runners and the
Track A engine must refuse a run that asks for it, and `engine_coverage` says so.

## 4. Data acquisition: what was searched and what does not exist

Four data targets were open. The outcome is mostly negative, and the negatives are the result.

- **A unit-resolved multi-animal PN current-step source** — not found. No public repository hosts
  raw patch-clamp traces for *Drosophila* PNs or ORN→PN synapses; neither Gouwens and Wilson
  2009 nor Kazama and Wilson 2008 deposited raw data, and no NWB, ABF or Dryad archive of
  antennal-lobe intracellular recordings was located. The cellular tier stays single-specimen.
- **A rate-dependent ORN→PN recording for ND-06** — found, as published fits rather than raw
  traces: Nagel, Hong and Wilson 2015, used above. This closes the parameter gap and leaves the
  independent-validation gap open.
- **An independent uEPSC holdout** — not found. `stage2-uepsc-prior-refit.json` therefore keeps
  `held_out_specimen_ids` empty and labels all twelve cells as fitted, which is what makes the
  refitted prior a prior and not a test.
- **A receptor-expression-to-connectome-type resource for ND-03** — located but not usable.
  Croset, Treiber and Waddell 2018 (eLife 7:e34550, GEO GSE95361 / SRA SRP128516) is a midbrain
  Drop-Seq atlas. Its PN-level receptor statements are inferential rather than per-cell-type
  measurements, and there is no published mapping from MaleCNS body IDs to its transcriptomic
  clusters. ND-03 is not advanced.

Two sources new to the corpus came out of this: Nagel, Hong and Wilson 2015, used above, and
Croset, Treiber and Waddell 2018, recorded as a lead that ND-03 cannot yet use.

## 5. Addendum: the two runs this ADR's code enabled

Both were executed after the sections above were written, from clean commits, and neither awards
a tier. They are recorded here because each corrected something in this ADR's own work.

**The bounded-path grooming sweep** tested the structural reading ADR-2026-009 substituted for
the withdrawn depression explanation. It is reported in full in
[the widened-circuit evidence report](../evidence/STAGE2_WIDENED_GROOMING_CIRCUIT.md). The
short version: the shortest-path rule had dropped *every* inhibitory input to the readout, since
all inhibition onto aBN1 arrives via paths of length two or more, so the structural reading is
right about the cause. But widening does not moderate the response toward the reference, it
abolishes it — 0.0 Hz at all eleven scales and all three frequencies at both K = 2 and K = 3,
against a one-hop 33.2 Hz and a reference 4.63 Hz. The transferred-circuit method is not
repaired by a wider selection rule.

Three corrections came out of running it, two of them to criteria written in this session:

- The v1 H1 criterion was one-sided and a silent readout satisfied it, so v1 scored a vacuous
  pass. v2 restates it three-way, and the outcome is `suppressed`, not supported.
- The v2 static contact-sum diagnostic is net *excitatory* at K = 3, +440 and +657 contacts onto
  readouts that never fire, because it counts hundreds of partners that never spike. Delivered
  drive has the opposite sign. v3 records both and whether they agree.
- The first v3 round recorded a commit that did not describe the code that ran, because
  `widened.py` used a bare `git rev-parse HEAD`. That is the dirty-tree provenance defect
  ADR-2026-006 banned for Track A, reappearing in a new code path. The round is discarded and
  disclosed, and the sweep now fails closed on a dirty worktree.

**The uEPSC prior refit** fits the difference-of-exponentials kernel to all twelve recordings as
a labelled, unvalidated prior — `evidence/stage2/uepsc-prior-refit-v1.json`, logical SHA-256
`df9ed7a405f7ab559c298e94fed0e395f33fe4ed2b8617d20c83b1f72dba3f78`. Decay time constant 16.5 ms
against the frozen 15.0 ms, rise 0.75 ms, population amplitude 30.25 pA against the frozen
24.47 pA, with no continuous parameter at a search boundary.

It does not repair the decay failure ADR-2026-008 recorded, and it slightly widens it. The
refitted kernel's peak-to-`1/e` time is 17.3 ms, while the median of the twelve source
recordings is 11.5 ms and the published 7.0 ms half-decay implies 10.1 ms. A population fit that
shares one shape across cells and one amplitude per cell therefore decays about 50 percent
slower than the median individual cell. `held_out_specimen_ids` is empty and all twelve cells are
labelled fitted, because no independent uEPSC recording was located; that is what makes this a
prior and not a test, and it must be labelled unvalidated wherever the type-pair registry uses
it.
