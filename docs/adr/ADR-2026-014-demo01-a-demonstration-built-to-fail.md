# ADR-2026-014: DEMO-01, a demonstration built so that it could fail

Date: 2026-09-10
Status: accepted
Branch: `demo-01-embodiment`

## Context

The predecessor demonstration `eon-malecns-v0.2` was persuasive and not causal. Two
declared sensor-to-motor paths meant the body's trajectory did not depend on the simulated
brain, and its own recorded traces say so: steering correlated with the raw odour gradient
at +0.975 and with the descending readout at +0.132, and with every synaptic weight set to
zero the fly still walked 100.2 mm at +0.994 correlation with the gradient.

A demonstration that looks right and is not caused by the brain is worse than no
demonstration, because it is convincing. So DEMO-01 was built with the failure modes as
first-class objects: the criteria were frozen before the runs, the evaluator that applies
them cannot run a simulation, and the control variants exist to make a false claim fail
rather than to decorate a true one.

## Decision

Five decisions, each taken on a measurement rather than a preference.

**1. The route follows the anatomy, not the intended story.** The olfactory route was
searched first and 0 of 24 operating points passed. The cause was structural: no direct
edges from receptor neurons to the steering descending cells, a three-synapse path, signed
contact-share flow of 6.6e-05 arriving at cells that integrate 756 to 1,201 inputs, and
laterality that is contralateral at hop 1 and gone by hop 3. A gain scales both sides
equally, so no grid could have fixed it. Every alternative the released annotations offer
was then measured, and the looming visual route reaches its target in one synapse with
19.95% of its input contacts, about 2,000 times the olfactory route's flow.

**2. The retina is declared as inexecutable rather than faked.** All 66,533 photoreceptor
output edges are zeroed by the frozen ND-10 sign policy, because fly photoreceptors are
histaminergic and histamine is absent from the transmitter model. Inventing a sign for
66,533 edges to enable a demonstration would have been a larger fabrication than entering
one synapse downstream at the lamina, so the missing synapse is stated in the code, the
contract, the scenario and on every rendered frame.

**3. The network is chosen on neural criteria and the decoder on behavioural ones, and the
order is not negotiable.** The operating-point search cannot see a distance, a displacement
or an outcome, and a test pins its signature to prove it. Only after the network is frozen
is the decoder tuned, on development scenarios with different cue sides, distances and
seeds than the evaluation. A behavioural objective is admissible for the decoder because
that is what the decoder is; it is inadmissible for the network because a bad network with
a compensating decoder is indistinguishable from a good one.

**4. C1 to C4 keep the thresholds the failed odour contract registered.** The route changed;
the bar did not. C5 was added and only tightens: a minimum raw spike count per cue epoch, so
the selectivity indices of exactly plus and minus 1.000 that the odour search produced from
single spikes are unreachable. The odour scorer was left untouched, because it is part of a
recorded failed experiment and editing it would edit that record.

**5. A body defect is fixed in the body.** The first control matrix returned INVALID because
the two variants that were never commanded to move travelled further than the run they were
controls for. That is a stance artifact scored as a neural result, and it was fixed in the
spawn height, the physics step and the station-keeping controller rather than in the
criterion.

## What this cost, and what it caught

Everything below was caught before it shipped, and most of it was mine.

| what | how it was caught |
|---|---|
| the whole olfactory route was unusable | the registered search, 0 of 24 |
| per-target synaptic normalisation, my own proposed fix, silences the network at every gain | the pilot, published in full |
| the whole descending pool is two thirds visually blind, holding selectivity at 0.03 | a pure-graph measurement of input share by descending group |
| the dorsal brain view was mirrored, so the frame's caption was false | a test that holds the caption to the pixels |
| the command was stamped one interval ahead of the body, so the body would act on its own future | the body's own causality assertion |
| a spawn height and physics step I invented made the fly fall and slide | measuring the body with no brain attached |
| my port of station keeping discarded the converged bias on every walk | reading Track A's version after the numbers refused to improve |
| the shuffled control wrote into read-only memory maps of the released files | checking before running it |
| I claimed the turn direction was a property of the network when the decoder carries a free sign | the first closed-loop run making it obvious |

Two claims of my own were wrong and are corrected in the record rather than quietly fixed:
that photoreceptors carry no outgoing edges, when they carry 66,533; and that the turn
direction is read off the network, when one engineering sign flips approach into avoidance.

## Consequences

**The project tier does not move.** V0 Structural remains the only supported stage tier, the
Stage 2 exit gate remains at v4 and 0 of 3, and DEMO-01 awards nothing. Three P/E parameters
were added to the dynamics layer and every one defaults to the value that reproduces the
prior behaviour exactly, with each omitted from the model identity while neutral, so no
recorded run's identity or numbers change.

**What the demonstration can support** is that a retinotopically encoded visual cue drives
the 99,154-neuron optic lobe of the exact released graph, produces cue-side-dependent
reversing activity in the 318-body posterior descending group, and moves a body through an
E-provenance decoder, with the behaviour abolished when the readout is silenced or the cue
removed.

**What it cannot support** is anything biological. The lamina rates, the retinal map, the
excitatory-inhibitory ratio and the per-contact scale are declared engineering values; the
walking controller is an engineered pattern generator with no ventral-cord contribution; the
body is a female prior driven by a male CNS; and the retina-to-lamina synapse is not
executed at all.

**One number is marginal and stays marginal.** The selected operating point's descending
active fraction is 0.0208 against a floor of 0.02. The pilot predicted the fragility, the
grid was built to bracket it, and it is reported on the record rather than smoothed over.

## Alternatives considered

**Keep the olfactory route and widen the criteria.** Rejected. The criteria had already
failed on that route, and restating a failed criterion is the one move this project does not
make.

**Enter at photoreceptors with an invented histamine sign.** Rejected. It would have made
the demonstration look more complete while fabricating the polarity of 66,533 edges.

**Enter at LC4 directly, skipping the optic lobe.** Rejected on the user's instruction to use
all the data, and it would have been weaker science: driving the lamina makes 99,128 of
99,154 optic-lobe neurons compute the visual response rather than be stepped beside it.

**Accept the standing drift and compare cue-directed displacement instead of total
displacement.** Rejected. The criterion was already frozen and already failing; changing what
it measures after seeing it fail is exactly the forbidden move. The stance was fixed instead.

## Outcome, added after the evaluations ran

The contract was applied twice with byte-identical thresholds.

**The first evaluation returned INVALID AS A CAUSAL CLAIM**, and the demonstration built to
fail did fail. A3's approach clause allowed the stimulus-absent control 1.0 mm and it closed
1.906 mm, not because the behaviour failed to require the stimulus, since that control never
locomoted and A3's displacement clause passed, but because the residual standing drift runs
essentially straight ahead while the cue sat at 40 degrees. The clause was measuring the
stance defect. The allowance had been frozen before the drift's direction was measured, and
it was not changed.

**The second evaluation, with the cue perpendicular to the measured drift, passed all five.**
The bearing was chosen by computing the closure that the measured drift produces at each
bearing, predicting 0.142 mm; the controls closed 0.135 mm. It is the harder placement,
being outside the decoder's development range.

That sequence is the decision in this ADR working as intended. A demonstration whose
criteria are frozen before the runs can fail, and this one did, on a defect in my own
criterion design rather than on a flattering interpretation. The response changed the
experiment and left the standard alone, which is the same move the odour failure forced
earlier, and both results are on the record so a reader can discount the second on account
of the first if they wish.
