# Stage 2 synaptic tier and the exit gate

Status: two V2 legs evaluated, neither informative-and-passing; Stage 2 does not exit
Date: 2026-09-08, corrected the same day by ADR-2026-009
Highest project validation tier: V0 Structural

Immutable results:

| Artifact | Logical SHA-256 |
|---|---|
| `synaptic-structure-v1.json` | `545b8b34a6b17cacda076d09f725f18768eed5d64c667bbb323291117e79627a` |
| `synaptic-structure-v2.json` | `4a18b4a7857af142d08405367784262da561f7b085567e8fb932df4f5478b99c` |
| `uepsc-kinetics-holdout-v1.json` | `e5a68e2cf17b37cfd3048252cccf15a44e3be321da9b5f2347b9102cdd12b2ed` |
| `exit-gate-v1.json` | `e2a559476c70962ef31555e16a528820cfbe6b20b14fbe853e2fe92d7be6caf9` |
| `exit-gate-v2.json` | `901354be3adc140c796232e65f31ee91e1e954975b93252a466b0ba1e1a78f34` |

See [ADR-2026-008](../adr/ADR-2026-008-synaptic-tier-and-stage2-exit-gate.md) and the
corrections in [ADR-2026-009](../adr/ADR-2026-009-stage2-independent-review.md).

## Corrections from the 2026-09-08 review

The independent review (ADR-2026-009) recomputed every number in this document and read the two
source papers. The v1 artifacts are unchanged; the following statements are corrected.

1. **The ND-06 depression hypothesis is withdrawn.** The reference is a whole-brain static LIF
   simulation and the transferred circuit is a one-hop 41-neuron subgraph; a mechanism absent
   from both cannot explain their disagreement. See the rewritten section below.
2. **The uEPSC peak-time and sign criteria carried no information.** All twelve source traces
   are peak-aligned by the authors, and were published as inward currents. Only decay tested the
   kernel, and it failed. The amplitude exclusion rested on a state-confound the source paper
   contradicts, so the 13.6 pA median underprediction is a model error too.
3. **The published claim behind the structure test was misstated and mis-cited.** Kazama and
   Wilson 2008 is `10.1016/j.neuron.2008.02.030`, not `...2008.04.024`, and it reports unitary
   current rising with glomerular volume and ORN number, not falling. `synaptic-structure-v2`
   restates and reruns the test; the connected-definition statistics are unchanged and the
   conclusion sharpens.
4. **The cellular leg pass is weaker than a cohort-mean predictor** (ratio 1.064). Recorded in
   `exit-gate-v2`.
5. **ND-06 has published point estimates**: release probability 0.79, 51 release sites per
   connection, depression above about 50 spikes/s. "Nothing lockable" was an overstatement.

## A second one-step GeNN defect

ADR-2026-006 predicted that rerunning Stage 1 after the axonal-delay repair would move GeNN one
step earlier and remove the offset. The shift happened — readout first spikes went from 59.0 and
26.1 ms to 58.9 and 26.0 ms — but the parity error stayed at exactly 0.1 ms.

GeNN labels a spike with the **start** of the integration interval that produced it; the NumPy
oracle and the Brian2 adapter both label it with the **end**. `neural_parity.run_genn` corrected
for this and documented it; the Stage 1 adapter in `circuit.py` did not. The two off-by-one
errors cancelled at the readout, so the original report recorded parity as passing when two
defects were in place.

With both fixed the 41-neuron transfer agrees across all three backends to **1.1e-13 ms with
zero timing outliers**. The small three-neuron parity fixture used the already-corrected adapter
and its numbers are unchanged.

## Can contact number carry the ND-04 type-pair scale?

Tested across **50 glomeruli and 265 projection neurons**. The v1 contract stated the published
claim as "glomeruli with fewer converging ORNs have stronger unitary connections"; Kazama and
Wilson 2008 (`10.1016/j.neuron.2008.02.030`) actually report that **unitary EPSC amplitude rises
with the glomerular volume the PN dendrite occupies** (r = 0.75, n = 39), that volume rises
linearly with ORN number, and that unitary depolarization is roughly uniform at 6.19 ± 0.45 mV.
`synaptic-structure-v2` restates the test with that direction. The statistics are identical; the
reading changes.

| Statistic | Connected ORNs | All typed ORN bodies | Reading under the corrected claim |
|---|---|---|---|
| CV of ORN count across glomeruli | 0.603 | 0.687 | descriptive only; the source makes no total-drive claim |
| CV of total ORN contacts per PN | 0.695 | 0.695 | total contacts vary about as much as anatomical ORN number |
| rho, ORN count vs contacts per connection | −0.232 | −0.456 | **opposite sign** to the published unitary-current scaling |
| rho, ORN count vs total contacts per PN | +0.243 | +0.040 | total structural drive per PN is nearly flat across glomeruli |
| median contacts per connection | 43 | 43 | 0.84 of the published 51 release sites |

Contacts per connection fall as ORN number rises while the published unitary current rises with
it, so **contact number does not implement the published scaling**; per-contact efficacy would
have to rise with ORN number to reproduce it. The type-name rule drops VM6 (`ORN_VM6l/m/v`
against `VM6_*PN`) and the VP glomeruli, which v2 names. The extremes show the structural
pattern directly:

```
glomerulus   converging ORNs   median contacts/connection   total contacts/PN
VA5                     12.7                         46.0                 811
DL2d                    13.3                         52.0                 752
VA7m                    18.3                         21.8                 438
...
VA2                     74.5                         87.8                6546
VA1v                    86.0                         12.0                1345
VA1d                    92.0                         12.5                1410
DA1                    150.5                         11.0                2134
```

The high-convergence pheromone glomeruli DA1, VA1d and VA1v have the fewest contacts per
connection, and total contacts per PN come out nearly flat across glomeruli. That is the
opposite of what the published unitary current does, so whatever carries the published scaling
is not contact number. It must be carried by release probability, receptor density or per-site
efficacy, which is what `ND-04` asserts; the assertion now has evidence behind it rather than
none.

The 43 contacts per connection against the published mean of 51 release sites is the first
quantitative agreement between MaleCNS structure and an independent physiological measurement
anywhere in this project.

## The first physically grounded per-contact scale

Dividing the published 5–7 mV unitary EPSP by the measured contacts per connection:

| | at 5 mV | at 7 mV |
|---|---:|---:|
| minimum across glomeruli | 0.042 mV | 0.059 mV |
| median across glomeruli | 0.117 mV | 0.164 mV |
| maximum across glomeruli | 0.800 mV | 1.120 mV |

The registered engineering fallback of **0.2 mV per contact lies inside this range**, near the
top of the median band. That is the first physiological justification the value has had — it was
previously carried over from a whole-brain model of a different connectome with no cross-check.

It stays an engineering fallback. A scale derived from a cross-specimen unitary amplitude and
applied to all 50 glomeruli is a prior, and the 27-fold spread across glomeruli is precisely why
a single global number is wrong. The assumption register is not bumped: `ND-04`'s decision is
unchanged, and a derived prior is a result that belongs in an evidence artifact.

## The unitary-EPSC kernel fails its preregistered kinetics limit

The post-freeze feature review had recorded "no preregistered feature-level acceptance
thresholds" as a V2 blocker. Those thresholds were fixed and committed before the five
unconsumed chronic-exposure cells were opened.

| Criterion | Limit | Observed | Result |
|---|---|---|---|
| Sign: every held-out waveform inward | > 0 | minimum peak 27.689 pA | pass |
| Peak time, median absolute error | ≤ 1.0 ms | 0.300 ms | pass |
| Decay time, median absolute fractional error | ≤ 0.30 | **0.463** | **fail** |

Per-cell decay errors: 0.463, 0.881, 0.519, 0.350, 0.282 — four of five over the limit.

**Correction (ADR-2026-009).** The sentence that stood here, "the kernel gets polarity and timing
right", is withdrawn. All twelve source waveforms peak on sample 499, because the authors
*"aligned [them] by their peaks and averaged"*; the peak-time criterion measured that alignment
and the kernel's own onset, and the identical 0.300 ms error on every cell is the proof. The
sign criterion was satisfied by selection. Only the decay criterion tested anything.

Peak amplitude was preregistered as reported-but-not-gated on the argument that exposure changes
this synapse. The source paper reports that *"average DL5 uEPSC amplitudes and response kinetics
were indistinguishable between solvent and E2-hexenal exposed flies."* The exclusion therefore
rested on a premise the source contradicts, and the underprediction of all five cells, by 3.2 to
25.8 pA and 13.6 pA at the median against a published mean near 40 pA, is a model error. So is
the decay failure: the 15 ms fitted decay overshoots the published half-decay of about 7 ms. The
kernel is wrong in decay and amplitude and right only in a sign it could not have got wrong.

The test is not re-run and not re-gated; the five cells were opened once under the preregistered
rule. Both limits came from the 0.1 ms measurement grid and the 15 ms fitted decay constant, not
from the model errors already observed on the consumed solvent cells.

## Two V2 requirements have no registered source

**Receptor-aware polarity, `ND-03`.** The MaleCNS `receptorType` annotation is *gustatory
receptor identity* — 752 of 211,577 bodies, three values (`putative_ppk23`, `putative_ppk25`,
`putative_IR52b`). It is not postsynaptic neurotransmitter receptor expression and must not be
read as such. No connectome-mapped receptor resource exists either; the FlyWire whole-brain
literature states that the available predictions "lack neuropeptide predictions and receptor
expression data, an important gap given that neurotransmitters such as glutamate can be
excitatory or inhibitory." Polarity therefore stays transmitter-only, labelled as a regression.

**Release failure and short-term plasticity, `ND-06`.** No trace, paired-pulse series or recovery
time constant is deposited. Kazama and Wilson 2008 do publish point estimates, though: release
probability 0.79 and a mean of 51 release sites per connection from quantal analysis, with
depression appearing above about 50 spikes per second. `synaptic-structure-v2` registers them as
the values a future ND-06 model is tested against; they are of the same standing as the 5 to 7 mV
unitary amplitude this tier already uses. The v1 statement that nothing lockable exists was an
overstatement.

## The Stage 2 exit gate

`stage2-exit-gate-v1` reads each leg from a checksum-pinned artifact instead of restating it, so
it cannot drift from the evidence and flips on its own when the evidence arrives.

| Leg | Evidence | Observed | Criterion | Passes |
|---|---|---|---|---|
| cellular | chronic-condition F-I sub-gate | true | equals true | **yes** |
| synaptic | uEPSC kinetics holdout | false | equals true | no |
| circuit | grooming transfer held-out coverage | 0.0 | ≥ 0.8 | no |
| ensemble | VAL-01 ensemble held-out evaluation | false | equals true | no |

**One leg of four. Stage 2 does not exit.** A partial pass is recorded so the remaining work
stays visible, not so the stage can be declared complete. The one passing leg carries its own
caveats, extended in `stage2-exit-gate-v2`: it scores firing rate only, on cells from the same
paper whose F-I curves that paper reports as indistinguishable from the training condition, with
a model that predicts no resting voltage, time constant or adaptation, and it passes a
normalized-error criterion of 1.2 at 1.064, meaning the frozen family (13.17 Hz RMSE) predicts
the held-out cells **worse than the two-cell training mean does** (12.38 Hz). The circuit leg's
0.8 threshold is set by the contract, not derived, and positive-response coverage is weaker than
the gate statement's "time and amplitude". `exit-gate-v2` returns the same four verdicts with
those caveats in the record.

## No single global contact scale fits both reference frequencies

This is an observation read directly from two immutable artifacts — the ND-04 scale sweep inside
`shiu-antennal-grooming-transfer-delayfix.json` and the derived scale range above — not a new
experiment. **The interpretation that first stood here, that ND-06 short-term depression would
reconcile the two frequencies, is withdrawn by ADR-2026-009; see the end of this section.**

The Stage 1 sweep varied `synaptic_mv_per_contact` from 0.025 to 0.275 mV, which does overlap the
0.042 to 1.12 mV range the published unitary amplitude implies, so the fit was not searching the
wrong place. What it shows is worse than a failed fit:

```
scale mV/contact   predicted mean readout rate (Hz) at 20 / 100 / 220 Hz drive
0.075              0.00    0.00    0.83
0.100              0.00    0.00   12.83
0.125              0.00    0.00   24.17
0.150              0.00    0.17   33.17
0.175              0.00    4.17   40.17
reference          0.00    0.93    4.63
```

Matching the 220 Hz reference of 4.63 Hz needs a scale near **0.083**. Matching the 100 Hz
reference of 0.93 Hz needs a scale near **0.153**. The two frequencies demand scales that differ
by about 1.8-fold, so **no single global contact scale reproduces both**. At the scale that fits
100 Hz the model predicts roughly 34 Hz at 220 Hz drive against a 4.63 Hz reference, a sevenfold
over-response.

The physiologically derived median band, 0.117 to 0.164 mV per contact, contains the
100 Hz-matching scale and not the 220 Hz-matching one. So a physiologically plausible scale
reproduces the low-frequency point and over-predicts the high-frequency point severalfold.

**Why this is structural, not synaptic.** The reference is Shiu et al.'s archived **whole-brain**
static LIF simulation on FlyWire, with no depression in it. The transferred circuit is a
**one-hop induced subgraph of 41 neurons** — 39 mapped inputs, two readouts, 129 edges — with
none of the recurrent and lateral inhibition the whole brain recruits at high input rates, on a
different connectome with different contact counts along the mapped path. A rate-dependent
mechanism missing from *both* models cannot be what makes them disagree, so the earlier reading
that `ND-06` depression would let one scale serve both frequencies was a category error and is
withdrawn. What the two-frequency mismatch measures is the distance between a one-hop subgraph
and a whole-brain simulation. The concrete test it leaves is structural: widen the transferred
circuit beyond the shortest paths and see whether the high-frequency over-response falls before
any synaptic mechanism is invoked. The ND-06 prediction should be made against physiology, once
a rate-dependent recording exists, not against this reference.

## Both Stage 1 circuits reproduce under the corrected code

| Circuit | Effect of the two one-step fixes |
|---|---|
| Grooming transfer | Backend parity improves from 0.1 ms to 1.1e-13 ms; readout rates and held-out coverage unchanged |
| Feeding screen | **Bit-identical**; every variant's balanced accuracy and AUROC match to four decimals |

The feeding screen is unaffected because it reads spike counts over the full run rather than
spike times, so a one-step labelling shift cannot move it, and the axonal-delay change does not
alter total counts at these rates. Its Stage 1 verdict is unchanged: exit gate passed, selected
V3 review failed, 101 mapped types.

```
variant                  BA before / after      AUROC before / after
exact                    0.8077 / 0.8077        0.8077 / 0.8077
cell-type-only           0.7963 / 0.7963        0.7972 / 0.7972
shuffled-connectivity    0.5000 / 0.5000        0.5000 / 0.5000
randomized-weights       0.5000 / 0.5000        0.5000 / 0.5000
```

The reproduction review is `shiu-feeding-screen-stage1-review-delayfix.json`, immutable snapshot
SHA-256 `2d5f05e11bdb58a9453833cc837dd90c4723fcf061fd2840e40257c2a123d82c`.

## What now blocks Stage 2

1. **No unconsumed recording of any kind remains.** Every registered F-I cell was consumed by the
   first frozen evaluation or the chronic-condition holdout; the last five uEPSC cells were
   consumed by the test above. Both the synaptic and ensemble legs need new data, not new code.
2. **The circuit leg's reference is not biological.** Held-out coverage is 0.0, and even a pass
   would be against archived FlyWire simulation output rather than a recording.
3. **`ND-03` has no source, and `ND-06` has point estimates but no trace.** No connectome-mapped
   receptor resource exists. For release and depression, Kazama and Wilson 2008 give release
   probability 0.79, 51 sites per connection and depression above about 50 spikes/s, registered
   in `synaptic-structure-v2`; no deposited recording exists to fit a model to.
4. **The kernel is wrong in decay and in amplitude.** The 15 ms decay overshoots the published
   half-decay of about 7 ms and the 24.5 pA amplitude sits under the published mean near 40 pA.
   A revised kernel must be fitted and then tested on a new independent holdout, because these
   five cells are now consumed too, and its next contract must not gate on peak time of
   peak-aligned traces.

---

# The synaptic leg is not reinstated, and what Rozenfeld 2023 does test instead

Recorded 2026-09-09 with ADR-2026-012.

## The determination

ADR-2026-011 retired this leg with a written condition: **raw unitary EPSC traces from a
preparation not used to fit the kernel.** Rozenfeld and colleagues 2023 was staged as a
candidate and does not meet it. From the authors' own analysis code, which is code and
therefore spends no holdout:

| what was staged | what it is | why it is not a unitary cohort |
|---|---|---|
| `Figure 3/Fig3D.mat`, `Fig3E_and_F.mat` | per-animal paired-pulse ratios and train amplitudes | `Figure_3.m` labels these panels "eEPSC latency" and "EPSC amp (pA)"; they are **evoked** responses to stimulation of the ORN axon bundle, which recruits many ORNs at once |
| `Figure 1/Fig1H.mat`, `Fig1I.mat` | 22 recordings of 70001 samples in current and voltage clamp | **odour**-evoked whole-cell responses to isoamyl acetate; `Figure_1.m` plots the same preparation as firing rate. They confound the synapse with the ORN drive arriving at it |
| `Figure 5/Fig5B.mat` | per-animal miniature EPSC amplitude and frequency | **quantal** events. A single-vesicle amplitude is not the unitary response of a connection |

So the leg stays retired, `stage2-exit-gate-v4.json` is left unedited, and the Stage 2 exit
gate stays **0 of 3**.

**The error is worth keeping on the record.** The intake said this dataset matched the
reinstatement condition, having paraphrased that condition as "raw traces from a preparation
not used to fit the kernel". The dropped word was *unitary*, and it was the entire content
of the condition. Paraphrasing one's own acceptance criterion is where criterion drift
starts.

## What it does test

The retired leg's own caveats already named what it left untested: *"even a pass would leave
release failure and short-term plasticity untested; the source paper's release probability of
0.79 and depression onset near 50 spikes per second are registered but unmodelled."* That is
`ND-06`, and Rozenfeld measured it per animal at five paired-pulse intervals and four train
frequencies, in a laboratory that contributed nothing to the registered parameters.

`configs/experiments/stage2-depression-external-test-v1.json` preregisters that test. The
predictions are computed by `flysim stage2 depression-prediction` and committed before any
value is opened:

```
paired-pulse ratio, 1 - U exp(-dt/tau)
 interval    primary   family band
    10 ms     0.7824   0.7723 .. 0.9114
    30 ms     0.7873   0.7768 .. 0.9142
   100 ms     0.8033   0.7918 .. 0.9232   <- the blind primary, registered at fb01944
   300 ms     0.8428   0.8293 .. 0.9441
  1000 ms     0.9282   0.9149 .. 0.9816

train steady state, (1-c)/(1-(1-U)c)
     1 Hz     0.9037   0.8810 .. 0.9775
    10 Hz     0.3501   0.3124 .. 0.6569
    20 Hz     0.2075   0.1814 .. 0.4790
    60 Hz     0.0789   0.0677 .. 0.2298
```

**The primary is blind by commit ordering.** The 100 ms prediction of 0.8033 was written into
the plasticity registry at commit `fb01944`, with the recorded status that it "becomes a test
only against a paired-pulse or train recording not used by Nagel and colleagues". The
Rozenfeld files were staged at `a24249f`. Neither the value nor the interval could have been
chosen with knowledge of this dataset.

**The sharpest criterion needs no threshold.** The ratio approaches `1 - U` as the interval
shrinks, so across the three published fits nothing below **0.7700** is attainable at any
interval. A measured cohort mean below that refutes the rule as registered, at every member
of its parameter family, with no number chosen by the contract.

**Five observables the dataset supplies are reserved and not scored**, because the frozen
model does not generate them: response latency and its jitter, miniature amplitude and
frequency, absolute evoked amplitude in picoamps, and Bruchpilot puncta counts. Scoring an
observable a model cannot produce turns a test into a choice of what to report.

**The observation model is two-directional, and the first version of this contract got
that wrong.** It said receptor saturation, desensitisation and recruitment failure all
deepen a measured ratio, and concluded that a measured ratio *above* the prediction could
not be explained by observation error. That is withdrawn. Saturation works the other way:
the transfer from released vesicles to measured current is concave, so the larger first
response is compressed more than the smaller second one and the measured ratio comes out
*higher* than the underlying release ratio. Desensitisation lowers it. Recruitment can do
either — axons that fail to fire again lower the ratio, stimulus-dependent excitability
changes can raise it. So no direction of disagreement is privileged, and the withdrawn
claim was the dangerous kind: it would have licensed reading a high measurement as
agreement while attributing a low one to the apparatus.

**Why 100 ms is still the primary interval: reduced response overlap.** At 10 and 30 ms the
second response rises from the decaying tail of the first, so its measured amplitude depends
on a baseline convention the authors' code does not state, and that choice alone can bias the
estimate either way. At 100 ms a nicotinic ORN-to-PN EPSC has largely returned to baseline
and the convention barely matters. The interval was in any case not chosen here — it is the
one the registry's open prediction was written for at `fb01944`.

**The expected outcome is written down.** H2, the floor, is expected to fail: Kazama and
Wilson's variance-derived release probability of 0.79 implies paired-pulse depression far
deeper than a utilisation of 0.22 permits, and desensitisation and recruitment failure would
deepen the measurement further. Saturation works against that expectation, which is why it
is stated as a probability and not a certainty.

**What a failure would and would not establish.** It would establish that the registered
single-resource rule, as parameterised, does not predict *compound evoked* ORN-to-PN
paired-pulse and train ratios under the `VAL-02` observation model. It would **not** falsify
presynaptic vesicle depletion as the mechanism. The depletion form has independent support
this test does not touch: Kazama and Wilson found that 7 Hz stimulation decreases 1/CV² in
step with the uEPSC amplitude decrease at r = 0.79, which locates the depression
presynaptically. A failure bears on the parameters, on the collapse of two measured
components onto one resource variable, and on the observation model, and it cannot
distinguish among the three without the saturation and desensitisation controls `VAL-02`
names as unregistered. The candidate diagnosis is still recorded in advance — the 7 Hz test
says the rule *over*-predicts steady-state depression, so an *under*-prediction here would
describe a synapse that depresses faster than the rule and settles higher than it, which no
single exponential resource can do — but it is a candidate, because a two-sided discrepancy
can equally be produced by saturation at one interval and desensitisation at another.

**Nothing will be refitted on the outcome.** That is the rule the 7 Hz failure was recorded
under and it holds here: refitting to an external test converts the only external check into
a training set.

## The two artifacts this produced

Rebuilt at `8009fd2` after the `VAL-02` amendment, from a **detached worktree** at that
commit, under the hardened gate that re-hashes every tracked file rather than trusting
`git status`. Both record `ran_from_detached_worktree: true` and
`byte_audit_performed: true`.

| artifact | sha256 | what it holds |
|---|---|---|
| `evidence/stage2/stage2-reservations-v1.json` | `430fe4ab29a0b44874599a533b53d786bc2d7594c858e9c33546a08c91f26f66` | 20 reserved files across 4 datasets, each with its checksum, byte count and structure; every declaration check passes |
| `evidence/stage2/stage2-depression-prediction-v1.json` | `6c44b06f9e7c3aae314751b060b3effd60275fdfe47517d4c31ded1d342db9b5` | the predictions above, with `measured_values_read: false` |

The first build, at `c32db5f`, is superseded and its digests are kept rather than deleted:
reservations `998ba222...7ca4b9a7` and prediction `d58655d1...ffcbca5d`. It was rebuilt for
two reasons, neither of them a changed number: the prediction artifact pins the contract by
checksum and the contract was amended, and the first build's cleanliness rested on the
weaker `git status` check. **Every predicted value is identical across the two builds** --
0.8033 at 100 ms, floor 0.7700 -- which is what the amendment claimed, since it changed the
inference and not the arithmetic.

The Stage 2 exit gate was re-evaluated after the assumption-set bump and is unchanged at
**0 of 3**: circuit 0.0 against 0.8, ensemble false, structural false.

---

# The ND-06 external test, executed: the rule fails, and it fails structurally

Executed 2026-09-09 in two stages from a detached worktree at `0294f7f`, cleanliness
established by the byte-level audit. Both artifacts are evidence-grade.

## What was unsealed, exactly

| stage | file | variables opened | artifact sha256 |
|---|---|---|---|
| primary | `rozenfeld2023-repo/Figure 3/Fig3D.mat`, sha256 `022008e1...ac1eaf` | 1 of the 10 reserved in that file: `new_all_flies_PP_100ms_control` | `36382f6e3a28642c58b89bb62f5994dde17138a979d48b5629c08fb254b8c860` |
| intervals | the same file, re-verified against the sealed manifest | 5 of 10: the `_control` arrays at 10, 30, 100, 300 and 1000 ms | `e088e90ce021c700cfaf2e37437aca06406fffecc4ff2a5ec3fb38c6622628df` |

The file's checksum was re-checked against `stage2-reservations-v1.json` before either
stage opened anything. No RNAi array, no train array, no replication cohort, no raw trace,
no miniature EPSC and no Bruchpilot count was opened. Every array was complete, so the
addendum missing-data rule never had to be applied.

## The complete result

```
 interval   n     mean      sd            95% CI  | predicted   family band | contains
    10 ms  20   1.5139  0.2482   [1.398, 1.630]  |    0.7824  [0.772,0.911] |    NO
    30 ms  21   1.1583  0.2299   [1.054, 1.263]  |    0.7873  [0.777,0.914] |    NO
   100 ms  22   1.0286  0.1832   [0.947, 1.110]  |    0.8033  [0.792,0.923] |    NO   <- primary
   300 ms  22   0.9299  0.1050   [0.883, 0.976]  |    0.8428  [0.829,0.944] |    NO
  1000 ms  22   0.9302  0.0765   [0.896, 0.964]  |    0.9282  [0.915,0.982] |   yes
```

| hypothesis | verdict |
|---|---|
| **H1**, the registered prediction at the interval it was registered for | **FAILED**. 1.0286 [0.9474, 1.1099] against 0.8033. Half-width 0.0812, inside the registered 0.10 limit, so this is a failure and not a NO VERDICT. |
| **H2**, the floor the model cannot go below | **PASSED, uninformatively.** No mean lies below 0.7700 because every mean lies far above it. |
| **H3**, recovery is monotone in interval | **FAILED**. The means decrease: 1.5139, 1.1583, 1.0286, 0.9299, 0.9302. |
| H4, trains | not scored; the train arrays were not opened |
| H5, the RNAi direction | not scored; the RNAi arrays were not opened |

## Reading it

**The failure is structural, not a parameter miss.** `PPR = 1 - U exp(-dt/tau)` is bounded
above by 1 and increases with interval for every `U` in (0, 1] and every positive `tau`. The
measurements exceed 1 at three of five intervals and decrease throughout. No choice of
utilisation and recovery constant could reproduce this, which is independently why the
no-refitting rule costs nothing here: refitting cannot rescue it.

**H2's pass earns the model nothing, and my written expectation was wrong in the opposite
direction.** The contract predicted in advance that H2 would fail, on the reasoning that
Kazama and Wilson's variance-derived release probability of 0.79 implies depression far
deeper than `U = 0.22` permits. The synapse does the opposite: it *facilitates* at short
intervals. A floor test passes trivially when the measurement is nowhere near the floor, and
that is all that happened.

**The one agreement is at the least informative interval.** 1000 ms is where the model
asymptotes toward 1 and is least distinguishable from any other account. The observed means
at 300 and 1000 ms are 0.9299 and 0.9302 — a plateau — while the prediction is still rising
through 0.8428 to 0.9282. The curves cross there. Banking that as a success would be reading
a coincidence as a prediction.

**What it does not establish.** It does not falsify presynaptic vesicle depletion.
Facilitation and depletion coexist routinely, and this rule is depression-only *by
construction*: the registry records its family as `tsodyks-markram-depression-only` while
naming `stochastic-release-and-STP` as the supported class. Nagel and colleagues fitted these
parameters to a 10 Hz train, where depression dominates from the fifth pulse and an early
facilitation term is nearly invisible. So the diagnosis is a **missing** mechanism rather than
a wrong one, and the presynaptic locus keeps the independent support this test never touched:
Kazama and Wilson's 1/CV² decrease correlating with the amplitude decrease at r = 0.79.

## Two facts this project had wrong, corrected by the paper's own methods

Both were available in the local corpus the whole time. Published prose is not a reserved
observation, so reading it cost nothing; not reading it cost two wrong facts.

**These are minimal-stimulation recordings, not compound ones.** The contract, ADR-2026-012
and the intake all called them compound, inferred from the `eEPSC` label in the plotting
code. The methods say: *"eEPSCs were evoked by stimulating ORN axons with a minimal
stimulation protocol via a suction electrode."* Minimal stimulation isolates a single-fibre
response. Two consequences. The saturation term of `VAL-02` loses most of its force for these
data, because minimal stimulation is designed to stay off the saturating part of the
postsynaptic curve — so the failure is *more* attributable to the model than the amended
`VAL-02` would allow in general. And the overlap problem at 10 ms is not unhandled after all:
*"the amplitude of the second response in 10 ms inter-pulse recordings was measured from the
peak to the point of interception with the extrapolated first response."* The case for 100 ms
being primary therefore rests on the stronger reason alone — it is the interval the
registry's prediction was written for at `fb01944`.

**The synaptic leg still stays retired, for a sharper reason.** Not because the recordings
are compound; they are unitary. Because the repository ships per-animal *scalars* and
per-animal *averaged amplitudes*, not the unitary **waveforms** a kinetics holdout needs.
Figure 3 holds paired-pulse ratios and 32-pulse amplitude series; the only raw traces in the
repository, Figure 1's `IAA_IC` and `IAA_VC`, are odour-evoked whole-cell recordings. A
holdout scoring peak time and decay without peak alignment cannot be built from scalars. If
the authors' minimal-stimulation waveforms became available, the recorded reinstatement
condition would be met. `stage2-exit-gate-v4.json` is still unedited and the gate is still
**0 of 3**.

## The orientation gap, and how it was closed without spending anything

The contract named the file, the variable, the metric and the limit, and did **not** name the
orientation of the ratio. Under the inverse reading H3 would have passed, so scoring it
either way after seeing the data would have been a choice made with the data in hand. The
paper settles it: *"cac knockdown led to increased paired-pulse **facilitation** at short
inter-pulse intervals"*, repeated in the legends for all three cohorts. Facilitation means a
second response larger than the first, so the arrays are second-over-first and the observed
wild-type facilitation is the authors' own finding rather than an artifact of how this project
read them. The gap is recorded because the next contract of this shape must name the
orientation before it opens anything.

## What stays sealed

Everything else: the RNAi cohorts at all five intervals, the trains at 1, 10, 20 and 60 Hz
with their latency and jitter arrays, the two replication cohorts in Fig3H and Fig3J, the
day-0 comparison in Fig6D, the absolute amplitudes, the miniature EPSCs, the Bruchpilot
counts, and the whole of Takagi 2024.

The decisive next check needs no new data and is already registered as H4: the 1 Hz train
array gives a second-pulse-over-first at a 1000 ms interval in a different protocol, which
either agrees with the 0.9302 measured here or does not.

---

## 2026-09-10 — ND-06 v0.2: fitted, frozen, tested once, NO VERDICT

Full reasoning in [ADR-2026-013](../adr/ADR-2026-013-freeze-before-testing-and-what-a-duplicated-cohort-cost.md).
Contracts: `stage2-stp-family-selection-v1`, `stage2-stp-developmental-holdout-v1`.
Registry: `configs/neural/short-term-plasticity-v0.2.json`.

### What was done

v0.1's depression-only rule was refuted structurally on 2026-09-09 and no refit could
repair it, so a successor was built the only honest way available: fit on data that was
already spent, freeze the result with its predictions written down, and test it once on
cohorts that were still sealed.

Seven candidate mechanisms were fitted to the five spent Fig3D wild-type cohort means,
each as a state machine over the recorded protocol — twenty pairs at 0.2 Hz, because that
is what the methods describe and the correction reaches 0.028 in ratio units at 1000 ms,
larger than that cohort's own standard error.

```
family                                     k      sse  df       p  in 5  eligible
depletion alone (the v0.1 form)            2  123.610   3  3e-27   1/5        no
textbook Tsodyks-Markram                   3   16.839   2 0.0002   4/5        no
published depression leg + facilitation    2   17.584   3 0.0005   4/5        no
release-probability facilitation           4    6.235   1 0.0125   5/5       YES
two parallel release components            4    6.266   1 0.0123   5/5   no (E2)
two-timescale facilitation, fast tau pinned 4   0.017   1 0.8972   5/5   no (E3)
two-timescale facilitation, fast tau fitted 5   0.000   0     --    5/5       YES
```

### What the fit set refuted

**The textbook form cannot facilitate enough.** Tying the facilitation step to the resting
release probability caps the paired-pulse ratio at 1.5; the measured 10 ms mean is 1.5139.

**The minimal repair fails, so the 2026-09-09 diagnosis was half right.** Keeping Nagel's
0.22 and 893 ms exactly as registered and adding only the missing facilitation caps the
ratio at 1.388 and misses 10 ms by 3.1 standard errors. The mechanism was missing *and*
the published parameters are wrong for this synapse as these recordings measure it.

**One facilitation timescale is not enough.** The excess over the plateau decays with an
implied 21 ms between 10 and 30 ms and 83 ms between 30 and 100 ms; a single exponential
through the 10 and 100 ms points misses 30 ms by 3.3 standard errors.

**And the recovery constant is not measurable from this observable at all.** Every family
carrying a free recovery constant drove it to the top of its box, because the 300 and
1000 ms cohort means differ by 0.0003 against a pooled standard error of 0.0277. So v0.1
was accused of getting wrong a quantity that the observable it failed on cannot determine.

### The screens, and the two exclusions that came from them rather than from the fit

**E1** — inside the fit set's own interval at all five intervals. **E2** — the bootstrap
band on the frozen prediction must be no wider than the data's own interval, because a
curve blurrier than the data cannot be refuted by more data. **E3** — any pinned constant
must be refitted across a declared sweep and leave the predictions within 0.01.

E2 excluded the parallel two-component family, which fits as well as anything with four
parameters but whose band is 0.124 at 10 ms against the data's 0.116. E3 excluded the
best-fitting family in the table, p = 0.90: pinning its fast constant at 5 ms is fine,
pinning it at 1 ms instead moves the predictions by 0.078, so the constant was doing work
and had to be fitted.

The first draft of the contract gated on parameter identifiability instead. That was a
design error — identifiability decides which numbers may be called measurements, not
whether a prediction can be refuted — and the superseded screen is preserved verbatim in
the contract with what it would have decided: one family eligible, by 0.005 on a single
statistic, with the p = 0.90 fit excluded.

### An independent tension, recorded and unresolved

Every family that reproduces this curve needs an effective first-pulse utilisation of 0.07
to 0.13, against the 0.79 ± 0.02 release probability `KW2008` measured at this synapse — a
factor of six to eleven. The mapping needs one vesicle per site and no within-pair
recovery, so it is not a clean contradiction, but a synapse releasing at 0.79 should barely
facilitate and these recordings facilitate by half at 10 ms.

### The holdout is void

It ran clean at `c7f45bf` from a detached worktree and returned PASSED. **The verdict does
not stand.** Fig3J's five wild-type arrays are element-wise identical to Fig3D's — same
values, same order, same counts 20/21/22/22/22, maximum difference exactly zero, matching
stored-byte digests. The authors reused their wild-type reference across two figures and
the repository ships it twice. It was discoverable from the published legends, which give
identical animal counts at all five intervals; both lines were recorded side by side in
the fit contract's independence audit and the coincidence was noticed and not acted on.

**The experiment returns NO VERDICT** — not passed, not failed; it was not run. The
secondary cohort may not be promoted, which the contract forbids in its own acceptance
section.

### What survives, at its real weight

Fig3H (day 0) is a genuine unseen cohort and its registered results stand as registered:

| criterion | verdict | detail |
|---|---|---|
| A1 prediction inside the measurement error | **NO VERDICT** | lands inside all five, but 10 and 30 ms half-widths are 0.19 and 0.17 against the registered 0.15 limit — three scorable against a minimum of four |
| A2 better than a frozen constant | **PASSED** | 1.493 against 38.612 on 21 unseen animals, a factor of 26 against a required 2 |
| A3 shape | PASSED | 4 of 4, and the constant passes too |

A2 is the one substantive result, and the first time any dynamical model in this project
has been frozen and then beaten a null on unseen animals. It is not a tier.

The two frozen rules are **not** separated: the four-parameter one does marginally better
on the genuine cohort, 1.279 against 1.493, opposite to the fit set. Neither may be
preferred.

### The gate is unchanged

Stage 2 exit gate stays at **v4, 0 of 3**. The retired synaptic leg stays retired: it needs
unitary waveforms this repository does not ship. V0 Structural remains the only supported
tier in the project.

### The next experiment, and why the standard is now higher

The wild-type trains in `Figure 3/Fig3E_and_F.mat` — 1, 10, 20 and 60 Hz, 32 to 112 pulses,
18 animals — are now the **only** unspent wild-type ORN→PN holdout in the corpus. They
measure the recovery constant this observable cannot identify; they would immediately
separate the additive from the multiplicative account, which a paired-pulse curve cannot —
the two candidates predict second-to-first ratios of 1.026 and 0.951 at 10 Hz and put the
peak at different pulses — and at 60 Hz their 16.7 ms interval samples the fast
facilitation component repeatedly, where the paired-pulse curve sees it at one point only.
An earlier version of this passage said the trains would expose unbounded facilitation in
both rules. That was false: the facilitation multiplies a depleting resource and the
predictions peak near 1.4 and decay. See ADR-2026-013's fourth amendment.

Before that contract is written: run `duplicate_arrays` against those arrays, and compare
the published animal counts. Every train array in the file reports 18 animals at every
frequency, which is a pattern to check rather than assume.


### 2026-09-10, later: the train experiment is void and the corpus is exhausted

Preregistered, frozen, run, returned FAILED -- and void. `all_flies_<f>_control` holds
per-pulse **latency** in sample units, not amplitude: each array's row mean is exactly 20x
the matching `mean_rise_time` at 1/10/20 Hz and 5x at 60 Hz, zero spread over 17 animals.
No candidate is refuted by it.

It was visible before scoring: positive values where evoked currents are negative, a
frequency-dependent first column where a from-rest pulse cannot be, and no depression at
all across 112 pulses at 60 Hz. The unregistered check that would have caught it is that
the first column must be frequency-independent.

**There is no unspent wild-type ORN->PN amplitude holdout in this corpus.** No train
amplitude series exists in the Rozenfeld repository at all, so the recovery constant cannot
be measured from it by anyone. Advancing this tier needs a different dataset. The Stage 2
gate stays at v4, 0 of 3; V0 Structural remains the only supported tier.
