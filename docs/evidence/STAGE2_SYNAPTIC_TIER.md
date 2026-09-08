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
