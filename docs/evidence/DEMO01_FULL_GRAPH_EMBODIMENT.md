# DEMO-01: a closed loop through the whole released MaleCNS graph

**Tier: V0 Structural. Nothing in this document is validated physiology, and nothing here
changes the project's scientific status.** It records an engineering demonstration: a
visual cue reaching a body through all 165,122 neurons and all 25,563,197 edges of the
released graph, with every dynamics parameter declared as P/E and the decoder and body as E.

The value of the exercise is not the video. It is that the demonstration is built so that
it can fail, and that it did fail several times in ways that were caught rather than
shipped.

## What this replaces, and why

The predecessor demonstration `eon-malecns-v0.2` reached its behaviour through two
engineered sensor-to-motor paths. Both were declared rather than hidden, but together they
meant the body's trajectory did not depend on the simulated brain. Measured on its own
recorded traces:

| quantity | value |
|---|---|
| correlation of steering with the raw odour gradient | +0.975 |
| correlation of steering with the descending readout | +0.132 |
| distance walked with **every synaptic weight zeroed** | 100.2 mm |
| correlation of that zero-weight walk with the gradient | +0.994 |

Both paths are gone. The controller has no sensory term to disable, because it takes no
sensor argument at all, and the body publishes no sensory channel for one to read.

## The route, chosen by measurement

The first attempt kept the olfactory route and searched 24 P/E operating points against
four neural criteria. **0 of 24 passed**, and the cause was structural rather than
parametric. Measured on the exact graph:

* no direct edges from olfactory receptor neurons to DNa01 or DNa02, so the path is three
  synapses;
* signed contact-share flow of 6.6e-05 of the injected signal arriving at those four
  cells, about one part in fifteen thousand;
* each of them integrating 756 to 1,201 inputs at an excitatory-to-inhibitory contact ratio
  between 1.17 and 2.04;
* laterality *contralaterally* biased at hop 1, index -0.835, and gone by hop 3 at +0.140.

A gain scales both sides equally, so no operating point on any grid could have repaired
that laterality. Ruled out by separate measurement: the unresolved-sign policy is not the
cause, zeroing 2.62% of edges globally and 0.4 to 0.5% of contacts at the readout cells;
readout width is not the cause, since widening to the whole 1,304-body descending pool
raised the response only to 0.58 Hz; and input magnitude is not the cause, since tripling
receptor drive changed descending output by under 3%.

Every alternative the released annotations offer was then measured with the same method
before any code was written:

| route | hops | direct contacts | share of target input | flow at first reach |
|---|---|---|---|---|
| ORN_DM1/DM4 -> DNa01/02 (the failed route) | 3 | 0 | 0.00% | 6.6e-05 |
| LC4 -> DNp02/03/04/06 | 1 | 19,465 | **19.95%** | 1.35e-01 |
| LC4 -> DNp01 giant fibre | 1 | 6,362 | 17.32% | 4.47e-02 |
| LC10 -> AOTU019 | 1 | 26,692 | **43.52%** | 2.63e-02 |
| LC10 -> DNa02 | 2 | 0 | - | 5.96e-03 |
| JO -> descending pool | 1 | 48,225 | 1.05% | 1.56e-01 |
| gustatory -> GNG588 | 1 | 59 | 0.91% | 4.8e-05 |

The looming visual route is about 2,000 times stronger than the olfactory one and reaches
its target in one synapse instead of three.

## The retina is not executed, and that is stated on every frame

Photoreceptors would have been the honest entry point. They cannot be. They carry 66,533
outgoing edges over 4,045 of 4,114 bodies, and **100.0% of those edges and 100.0% of their
contacts are zeroed by the frozen ND-10 sign policy**: fly photoreceptors are histaminergic,
histamine is absent from the transmitter model, so every prediction is unresolved and the
registered `zero` policy removes them.

Inventing a sign for 66,533 edges to make a demonstration work would have been a larger
fabrication than entering one synapse downstream. So entry is at the lamina monopolar cells
and the missing retina-to-lamina synapse is declared in the code, in the contract, in the
scenario and on every rendered frame.

## Entry: the retinotopic lamina

L1, L2 and L5: 5,342 bodies declared, of which **5,307 carry released
`assignedOlHex1`/`assignedOlHex2` column coordinates** over 877 distinct left-eye columns.
The 35 without one are held at baseline rather than given an invented retinal position. L3 and L4 are excluded, and the reason is a
property of the release rather than a modelling choice: released columns cover L3 on the
right only, 892 of 892 against 0 of 880 on the left, and L4 on neither side. Driving them
would have put a two-fold left-right imbalance into the entry layer before any dynamics ran.

What the choice buys, measured:

* **retinotopy survives to the lobula.** Two disjoint hex patches of the left lamina drive
  LC4 response vectors whose cosine similarity is **+0.000**, fully orthogonal, with a
  participation ratio of 15 to 23 of 126 LC4 cells per patch.
* **laterality survives to the descending layer.** A left-eye patch reaches descending
  neurons at hop 3 with left/right flow +2.5e-03 against -2.0e-05, index **+1.000**.
* **the optic lobe computes rather than decorates.** 59,799 of 99,154 optic-lobe neurons
  are reached at hop 1 and 99,128 at hop 2; all 1,304 descending neurons by hop 3.

Bilateral input contrast at the declared cue position is a factor of about 10, against the
odour route's measured 3.3% (0.374 against 0.362).

## Readout: the posterior descending group

The decoded pair is `DNp*` by released type prefix and `somaSide`, 160 left and 158 right.
Chosen by measurement, with laterality averaged over left-driver and right-driver so a fixed
anatomical asymmetry cancels:

| descending group | L | R | share of input from visual projection neurons | laterality h1/h2/h3 |
|---|---|---|---|---|
| all descending | 656 | 648 | 3.56% | +0.918 / +0.318 / +0.526 |
| DNp* | 160 | 158 | **8.83%** | +0.961 / +0.504 / +0.420 |
| DNa* | 26 | 26 | 2.71% | +0.721 / +0.241 / +1.000 |
| DNg* | 426 | 422 | **0.44%** | +0.727 / +0.098 / +0.312 |
| DNp02/03/04/06 | 4 | 4 | **38.03%** | +0.994 / +0.894 / +1.000 |

The whole pool is two thirds DNg and DNge, 848 of 1,304 bodies, which take 0.44% of their
input from visual projection neurons. Averaging a lateralised signal into a visually blind
majority is what held the measured selectivity index at 0.03 to 0.09. DNa01, DNa02, the four
DNp escape cells and the whole pool are all recorded every interval and none is steered on:
a 2-body or 4-body population cannot average away the spike quantum at a 15 ms interval,
which is exactly how the odour search manufactured indices of plus and minus 1.000 from
single spikes.

## The operating point, searched on neural criteria only

Contract `configs/experiments/demo01-visual-operating-point-v1.json`, preregistered and
committed before the search ran, with an exploratory pilot published in full at
`docs/demo01/PILOT.md` because it shaped the grid.

C1 to C4 carry the identical thresholds and arithmetic registered for the odour contract
that failed. The route changed; the bar did not. C5 was **added**, and it only tightens: a
minimum raw spike count per cue epoch, so the single-spike selectivity the odour search
produced is unreachable. `score_operating_point` in `flysim.demo01` was left untouched
because it is part of the recorded failed experiment.

**Result: 31 of 108 candidates met all five criteria.** Clean tree, commit `31736d2`,
evidence-grade, artifact sha256 `1f10b63d0bd3ab8c63c7b01d7d3994ca469624b210c323dfce95a1d3152bace5`.

Selected by the declared rule, largest selectivity swing inside the passing set:
0.5 mV per contact, inhibitory weight gain 1.5, adaptation 0.0 mV, lamina 400 Hz, ON/OFF
balance 1.0.

| quantity | measured | threshold |
|---|---|---|
| baseline descending drive | 0.000 Hz | <= 5.0 |
| cue-evoked response | 2.435 Hz | >= 2.0 |
| selectivity, left cue | +0.607 | reversal required |
| selectivity, right cue | -0.340 | reversal required |
| selectivity swing | 0.947 | >= 0.2 |
| recovery residual | 0.004 | <= 0.5 |
| descending active fraction | **0.0208** | in [0.02, 0.9] |
| readout spikes per cue epoch | 665 and 713 | >= 20 |

Which criteria bind, over all 108: C1 failed 62 times, C2 51, C4 13, C3 4, C5 never. The
stability-against-responsiveness tension is the whole problem, and it fails in opposite
directions. C3 almost never failing is what vindicates the readout choice, since on the
odour route it was unreachable at any gain.

The active fraction sits about one part in a hundred inside its floor. That is a fragile
margin, the pilot predicted it, and it is reported rather than hidden.

## Three P/E dynamics parameters were added, and one turned out unnecessary

Each defaults to the value that reproduces the pre-existing behaviour exactly, and each is
omitted from the model identity while it holds that value, so no recorded run's identity or
numbers change.

| parameter | default | outcome |
|---|---|---|
| per-target synaptic normalisation exponent | 0.0 | **refuted my own hypothesis.** It silences the network at every gain instead of rebalancing it. Fixed at 0.0 with the pilot table as the reason. |
| spike-frequency adaptation | 0.0 mV | **not needed at the selected point.** The winner uses 0.0, though 12 of 31 passing candidates use 1.0. Rebalancing excitation against inhibition did the work adaptation was introduced for. |
| inhibitory weight gain | 1.0 | **the one that mattered.** 25 of 31 passing candidates use 1.5. |

The inhibitory weight gain deserves its own note, because it looks like a fudge factor and
is not one. The engine previously asserted that a predicted-inhibitory contact and a
predicted-excitatory contact deflect the membrane equally. Nothing supports that: the signs
are transmitter *predictions*, and the cholinergic and GABAergic synapses being predicted
differ in receptor conductance and reversal potential. Making the ratio explicit and
searched states an assumption that was previously buried.

## The stance had to be fixed before any control was meaningful

The first four-variant control matrix returned INVALID and the acceptance evaluator was
right to. The two variants that were **never commanded to move** travelled 6.675 mm in three
seconds and rotated 81 degrees, with zero of 200 intervals carrying a nonzero command. That
is more than the 5.870 mm the exact run walked, so the criteria were failing on a body
artifact. The rule is to fix the stance, not the criterion.

Three faults, all mine, found by measuring the body with no brain attached:

| fault | effect | fix |
|---|---|---|
| invented a 1.35 mm spawn height where Track A registers 0.5 mm | the fly fell about 0.9 mm and landed hard; the thorax sank from 1.374 to 0.798 mm and slid | registered value, now pinned by a test |
| invented a 1000 us physics step where Track A registers 500 us | less stable leg contacts | registered value, now pinned by a test |
| omitted station keeping, then mis-ported it | the integral was discarded on every walk, so each stance re-converged from zero, and the pre-run convergence window was missing entirely | Track A's controller ported faithfully, including the reason its offset limits exist |

Residual standing drift, measured over the real 20 s duration with no brain attached:

| configuration | drift |
|---|---|
| station keeping off | 14.413 mm |
| Track A's registered integral gain, 0.06 | 6.026 mm |
| double that gain, which this body uses | **2.294 mm** |

The gain is re-derived rather than inherited because this body actuates legs only while
Track A also actuates head and proboscis joints. The criterion is a body-only one, that a
fly commanded to stand should stand, so no neural or behavioural quantity enters it and the
tuning cannot flatter the demonstration.

A latent fault was fixed on the way that would have been worse than a wrong number: the
shuffled-connectome control wrote its permuted array into `graph.target_indices` in place,
and those arrays are read-only memory maps of the released files, so the control could have
rewritten the release on disk. It now builds a new connectome and asserts that the edge
count, every out-degree and the multiset of contact counts survive.

## What may and may not be claimed

The acceptance contract `configs/experiments/demo01-acceptance-v1.json` was committed before
the control matrix ran, and the evaluator that applies it cannot run a simulation or alter a
threshold.

Never claimable, whatever the numbers say: that this is what a fly does; that any parameter
here is a measurement; that any mechanism is validated; that the tier has changed.

Limitations that travel with any claim: the retina-to-lamina synapse is not executed; leg
movement comes from an engineered pattern generator and no part of the simulated ventral
cord contributes to it; the body is a female prior driven by a male CNS; the turn direction
is an engineering choice, since the decoder's sign may be -1 or +1 and flipping it turns an
approach into an avoidance; the dynamics are a transmitter-sign regression rather than
fitted physiology; and 24,122 of the 165,122 executed neurons carry no released soma
position and so cannot be drawn, which every frame states.

## Corrections to my own earlier statements, recorded here rather than quietly fixed

1. I said photoreceptors carry zero outgoing edges. They carry 66,533. The flow was zero
   because the sign policy zeroes all of them.
2. I said the turn direction is "read off the frozen network, not chosen". It is not: the
   decoder carries a free sign. What the network determines is which descending side is
   stronger for a given cue side and that the asymmetry reverses.
3. I hypothesised that per-target synaptic normalisation would fix the failure. It makes it
   worse at every gain.
4. I predicted the odour route's failure would be signal dilution across the optic lobe at
   hop 2. C3 failed as predicted but the mechanism was different: the antennal lobe was
   amplifying into saturation while the descending layer stayed silent.

## The first evaluation: INVALID, on one criterion of five

Four variants, identical seed, 20 s each, from a clean tree at commit `a6d750d`. Verdict at
`runs/demo01-visual/acceptance.json`.

| variant | displacement | heading change | cue distance | locomoted |
|---|---|---|---|---|
| exact | 15.29 mm | +130.6 deg | 13.39 -> **1.92 mm** | yes, onset 1.665 s |
| readout-ablated | 2.29 mm | +9.2 deg | 13.39 -> 11.48 mm | **no** |
| stimulus-absent | 2.29 mm | +9.2 deg | 13.39 -> 11.48 mm | **no** |
| shuffled-connectome | 36.48 mm | +159.5 deg | 13.39 -> **49.28 mm** | yes |

| criterion | result | measured | threshold |
|---|---|---|---|
| A1 starts still, then moves | PASS | 15.29 mm, locomoted | >= 3.0 mm |
| A2 caused by the neural readout | PASS | 0.150 of exact, never locomoted | <= 0.25 |
| A3 requires the stimulus | **FAIL** | approach **1.906 mm** | <= 1.0 mm |
| A4 turn is cue-locked | PASS | -0.291 Hz and -3.69 deg share a sign | same sign |
| A5 topology gate | PASS | shuffle diverges 21.196 mm | >= 3.0 mm |

**Verdict: INVALID AS A CAUSAL CLAIM.** No video from this run may be presented as a brain
controlling a body, and the rendered videos carry that verdict on their closing card.

### Why A3 failed, and why the threshold was not touched

Not because the behaviour failed to require the stimulus. The stimulus-absent control
**never reached the locomoting state at all** and moved only 2.29 mm, which is precisely the
residual standing drift measured with no brain attached. A3's own displacement clause passed
at 0.150 of the exact run. What failed is its second clause, the approach allowance.

The drift runs at **+11.5 degrees from the initial heading**, essentially straight ahead,
and the cue sat at 40.1 degrees and 14 mm away, so passive forward drift closes the distance
geometrically. Closure that this exact drift produces, by cue bearing at 14 mm:

| cue bearing | closure | within the 1.0 mm allowance |
|---|---|---|
| 0 deg | +2.243 mm | no |
| 45 deg | +1.783 mm | no |
| 60 deg | +1.302 mm | no |
| 75 deg | +0.738 mm | yes |
| 90 deg | +0.142 mm | yes |

So the clause was measuring the stance defect rather than a cue-driven approach. That is my
error: the 1.0 mm allowance was frozen before the drift's *direction* had been measured. The
threshold stays as written, this run stays on the record as a failure, and the response is a
second scenario rather than a looser standard.

### What the shuffled control showed, which is the strongest result here

The degree-preserving shuffle walked 36.48 mm and ended **49.28 mm** from a cue it started
13.39 mm from. Rewiring the same edges, preserving the edge count, every out-degree and the
multiset of contact counts, produces a hyperactive network that drives the body a long way in
the wrong direction. A5 passes on a 21.196 mm divergence against a 3.0 mm threshold.

The honest reading is not that the real connectome "works better" in some general sense. It
is that the operating point selected for the exact graph does not transfer to a random
rewiring of it: the same synaptic scale that gives the exact network a 0.000 Hz baseline
makes the shuffled one drive locomotion continuously. That is a statement about how narrow
the usable regime is, and it makes the topology control informative rather than a formality.

## The second evaluation: the same standard, a cue where drift cannot mimic it

`configs/scenarios/demo01-visual-lateral.json` places the cue at 90.0 degrees and 14.0 mm,
perpendicular to the measured drift. **Every acceptance threshold is byte-identical**,
because the acceptance contract is scenario-agnostic and is reused unmodified; the operating
point, the decoder, the body, the duration and the seed are all unchanged. The only change
is the cue bearing, and the bearing was chosen by measuring the drift direction rather than
by trying placements until one passed.

It is also the harder test. The decoder was tuned on development cues at 37.9, 40.2 and 40.4
degrees, so 90 degrees is outside its development range and the fly must turn twice as far.
Removing a body artifact from a control does not make the task easier for the brain. The
retinal lateralisation is stronger at 90 degrees, landing on column 21.59 of the ipsilateral
eye against -15.47 for the contralateral one, compared with 12.32 and -6.21 at 40 degrees.
