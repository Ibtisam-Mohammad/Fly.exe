# DEMO-02: three behaviours, three negatives, and one control that misbehaves

Status: complete and negative. Twelve runs, all at commit `7b292e3a` with a clean worktree.
Tier unchanged at **V0 Structural**. The Stage 2 exit gate is untouched at v4, 0 of 3.

| behaviour | verdict | behaviour-exists criterion |
|---|---|---|
| grooming | **NO DEMONSTRATION** | `G1` fail |
| feeding | **NO DEMONSTRATION** | `F1` fail |
| escape | superseded -- see the addendum | re-run after a registered search |

No fly groomed, extended its proboscis, or took off. Each contract's claim ladder sends a
failed behaviour-exists criterion straight to NO DEMONSTRATION, so nothing else can rescue
the result and no video may be presented as a brain driving a body.

This document records what was measured instead, because the negatives are not uniform and
the differences between them are the informative part.

## What was built

The pipeline runs end to end and is not in doubt. Each run closes this loop 400 to 800 times:

    world quantity -> sensory bus -> 165,122 neurons, 25,563,197 edges -> declared readout
    -> causal filter -> decoder that sees nothing else -> body -> the world changes -> again

Three pieces are new and are described in `ADR-2026-016`:

* a **sensory atlas** resolving 15,856 of 15,912 in-graph sensory bodies into 122 channels
  across 30 modalities, each carrying an organ and a side taken from `entryNerve` and
  `rootSide`. This is the first time the organ-and-side requirement in `SENS-01` has been met
  by anything in this codebase;
* a **live-edge gate** that asks, per channel, whether a population can drive anything at
  all. It reproduces the known photoreceptor case exactly -- `visual` is 0.0 percent live,
  all 66,533 output edges dead against a transmitter model with no histamine -- which is how
  the instrument was shown to work rather than merely to run;
* a **sensory bus** with one saturating transducer per channel, baseline rate zero, and one
  frame per coupling interval.

## The three results

### Grooming: the drive arrives and the readout does not move

The stimulus is real physics. A scripted torque on the funiculus produces 0.0735 rad of
deflection on the stimulated side against 0.0001 rad on the other, a 727-fold asymmetry,
transducing to 29.6 Hz across 40 labelled Johnston-organ afferents.

The network responds: 274 neurons active per coupling interval, peaking at 3,819.

The six grooming descending neurons never spike. Not once, in 800 intervals.

It is not that the activity fails to arrive. Of the 1,149 neurons presynaptic to those six
cells, **325 spiked, carrying 30.2 percent of the readout total input contacts**, and the
readout still did not reach threshold.

    JO-F direct onto the groom DNs:  11 edges, 26 contacts = 0.162% of their input
    presynaptic neurons that spiked:  325 of 1149 (28.3%), 30.23% of input contacts
    groom-DN spikes:                  0

The route scores 106 times a degree-matched null structurally, the strongest measured
anywhere in this project. It does not carry dynamically at the DEMO-01 frozen operating
point.

### Feeding: the strongest route works, and it is the one that cannot be used

> **Corrected 2026-09-12 (ADR-2026-018): the readout labels below are reversed.**
> `MN9` is not the pharyngeal pump. McKellar and colleagues (eLife 2020;9:e54978) list the
> eight positioning muscles as 1, 2D, 2V, 3, 4, 6, 7 and **9** and the eight pharyngeal ones
> as 5, 8, **10, 11D, 11V, 12D**, 12V and 13, state that muscle 9 protracts the rostrum and
> that its motor neuron elicits proboscis extension, and name each motor neuron after its
> muscle. Schwarz and colleagues 2017 independently put muscle groups 5, 10, 11 and 12 on the
> pump. So this experiment decoded the **pump** and recorded the **extensor**.
>
> The sentences below are kept as written because the measurement is right and only the
> labels are wrong, and because reading them with the labels swapped is the clearest possible
> statement of what happened: the population that responded was the correct readout, and the
> contract refused to decode it. `MOTOR-07` now registers the mapping with its source and
> with the `exitNerve` check that could have refuted it. `demo02-feeding-v2` supersedes the
> contract.



This is the sharpest result of the three.

`MN9` -- labelled the pharyngeal pump here, and in fact the rostrum protractor --
**responds**: 10 spikes, peak 4.53 Hz. The twelve motor neurons the contract decodes as
proboscis extensors, and which are in fact the pharyngeal pump, produce nothing. Not in the
exact run, not in any variant, across all 600 intervals.

Two consequences that were not visible while the labels were wrong. The `readout-ablated`
control was **vacuous**: ablation zeroes only the decoded populations, so it silenced a pool
that was already silent and `F2` passed by measuring nothing. And `MN9`'s 10 spikes fall to
**0** in `stimulus-absent` and to **0** in `shuffled-connectome`, which is the signature of a
stimulus-gated, topology-gated route -- recorded here under the name of a pump.

`MN9` is exactly where the route survey pointed -- labellar bristle to MN9 at 48.6 times a
matched null over four hops with zero direct edges. The contract declared, before the run,
that this route could not be built: NeuroMechFly has no labellum on which to place a
stimulus, and no pharynx for a pump to pump. So the entry moved to the leg taste bristles and
the readout to the proboscis extensors, and both substitutions were recorded as limitations
rather than hidden.

The dynamics have now confirmed the structural survey was pointing at the right place, and
the body is what prevents using it. The pump motor neuron fires with nothing to pump.

### Escape: SUPERSEDED. Read the addendum at the end of this document first.

> The section below records what happened at DEMO-01's operating point and is left
> unedited. Its conclusion does not survive: a registered search found 11 of 36
> candidates that fire the giant fibre cleanly, and the single parameter responsible
> was one DEMO-01 had selected at the top of its own grid.

#### (superseded) the visual pathway computes, the giant fibre does not fire

The visual stimulus enters at the lamina through the frozen DEMO-01 retinotopic encoder,
unchanged, and the optic lobe computes on it: 5,307 lamina cells driven, 2,948 neurons active
per interval, the object growing from 4.78 to 38.68 degrees of angular radius.

    dn-loom-left   (4 cells)   78 spikes   peak 15.93 Hz     <- responds, lateralised 78:1
    dn-loom-right  (4 cells)    1 spike    peak  1.59 Hz
    giant fibre    (2 cells)    0 spikes   peak  0.00 Hz     <- never fires
    PSI            (2 cells)    0 spikes

The `DNp02/03/04/06` companion pool -- the same population DEMO-01 decodes -- responds
clearly and with a 78-to-1 side preference. The two-cell giant fibre never crosses threshold,
despite `LC4` and `LPLC2` supplying 30.6 percent of its input contacts monosynaptically.

The contract predicted this fragility and required the companion pool for exactly that
reason. What it did not anticipate is that the companion would fire while the primary stayed
silent.

**The decoded readout was not switched to `dn-loom` or to `pump-mn9` after seeing these
numbers.** That would be criterion shopping against frozen contracts. The honest statement is
that these routes carry signal at a readout other than the one declared, and that is recorded
here rather than converted into a pass.

## The control that does not do what a control should

The degree-preserving target shuffle is supposed to remove structure and keep statistics. It
does not behave that way here.

    run                            active/interval   peak/interval   readout spikes   acted
    escape/exact                             2,948           7,136               80   False
    escape/shuffled                         14,025          29,218            1,497   True
    grooming/exact                             274           3,819                0   False
    grooming/shuffled                            8             320                6   True
    feeding/exact                            1,721           4,712               10   False
    feeding/shuffled                            52             445                0   False

The escape shuffle is **4.8 times more active** than the intact network and fires the giant
fibre 242 times at a peak of 100 Hz, where the real connectome fires it zero times. Both
shuffled runs that reached ACTING did so on networks whose behaviour is nothing like the
intact one in either direction: one hyperactive, one nearly silent.

So `G7` and `E7` "fail" in the sense that the shuffled network acted where the exact one did
not. Reporting that as a failed topology gate would be misleading. What the number actually
says is that this shuffle destabilises the network rather than neutralising it, and a control
that changes the operating regime cannot isolate the contribution of topology.

**DEMO-01 saw this first and said so.** `docs/STATUS.md` records that its own shuffled
variant walked 32.20 mm and ended further from the cue than it started, and reads it as "the
operating point selected for the exact graph does not transfer to a random rewiring of it:
the same synaptic scale that gives the exact network a 0.000 Hz baseline makes the shuffled
one drive locomotion continuously." That is the same effect, hedged correctly at the time.
These runs corroborate it with spike counts rather than trajectories, and extend it to a
second route.

What remains live is the DEMO-01 sentence "the exact connectivity rather than a network of
its size is responsible **at this operating point**". The qualifier is doing real work, and
the numbers here say how much: a shuffle that multiplies population activity by 4.8 has not
held the operating point fixed, so it cannot separate topology from excitability. The claim
is not refuted, but the control it rests on is weaker than a degree-preserving shuffle
sounds.

## Two defects in the contracts, disclosed rather than repaired

Criteria are frozen and are not being rewritten. Both of these are recorded so the numbers
above are read correctly.

**`E2` and `E3` are unpassable as written.** Both cap the control thorax rise at 0.15 mm, and
the justification text inside the same criterion states that the measured no-command standing
excursion is 0.204 to 0.211 mm. The bar was set below the noise floor that the same sentence
quotes. Every standing fly fails it, including a correct one. This is an error I made when
writing the contract, and it is why `E2` and `E3` report FAIL against controls that behaved
exactly as controls should: neither reached ACTING.

**`G2` is vacuous when `G1` fails.** It caps the ablated run joint excursion at one tenth of
the exact run value. When neither run grooms, both sit at the same passive-joint baseline of
0.0544 rad, so the test compares noise against noise divided by ten. It reports FAIL while
measuring nothing. A criterion of this shape should be `not_scored` when the behaviour it is
relative to did not occur.

Neither defect changes any verdict: all three behaviours already failed at `G1`, `F1`, `E1`.

## What was not run

Four to six variants per contract were not executed, and every criterion depending on them is
recorded as `not_scored` with its reason, never as a pass. Missing: `entry-swapped`,
`suppress-groom-replay`, `controller-only` and `zero-tonic-drive` for grooming;
`contact-without-sucrose` for feeding, which is the control that separates taste from touch;
`matched-size-static`, `command-replay`, `jump-only` and `wing-only` for escape. The
`wing-only` prediction -- approximately 0.0 mm of rise, because this model has no density, no
viscosity and no fluid geoms -- therefore remains untested.

## Five bugs the runs found that reading the code did not

Recorded because each one would have produced a confident wrong answer.

1. **`edge_signs` indexed by neuron index instead of edge index.** The first live-edge output
   said every sense was 100 percent live, including the photoreceptors, which are known to be
   entirely dead. A result that flatters the project is the one to distrust.
2. **The antennal stimulus measured at the wrong joint.** `c_head-l_pedicel` is servo-actuated
   in the grooming body, so a position controller held the antenna against the applied torque:
   0.00007 rad for a stimulus that should have been unmissable. The Johnston organ detects the
   *funiculus* rotating relative to the pedicel, and those joints are free hinges.
3. **The stimulus torque was three orders of magnitude too small**, far below the transducer
   own 0.02 rad threshold.
4. **Three funiculus axes summed as signed angles**, letting a pitch and a roll of opposite
   sign cancel: 0.023 rad reported for a real 0.073 rad deflection.
5. **`initiation_hold_us = 0` made the decoder hold check vacuously true.** The escape decoder
   commanded a jump with no input at all. It surfaced as byte-identical exact and
   readout-ablated runs -- same displacement, same 1.736 mm rise, same 4,170,500 us airborne --
   which is precisely what a control is for.

A sixth was caught by provenance rather than by a control: three of the first seven recorded
runs were invalid, two carrying pre-fix commits and one with a truncated `summary.json`.
Without `code_commit` in every summary, a stale escape/readout-ablated showing ACTING on a
completely silent network would have been scored as a control result.

## What this does and does not license

It licenses saying that a full-graph closed sensorimotor loop runs, that every labelled sense
now resolves to an organ and a side, and that three specific routes were driven and measured.

It does not license any behavioural claim whatsoever. No tier moves. The correct one-line
summary is: **at the DEMO-01 frozen operating point, none of the three strongest structural
routes in the male CNS drives its declared readout to threshold.**

## The declared next step, and what it may not be

The operating point was **not** tuned to make these fire. That is the single most important
thing about this result. `synaptic_mv_per_contact` and the rest came from the registered
DEMO-01 search, which scored neural criteria alone before any behaviour existed, and changing
them after seeing a behavioural outcome would convert every contract here into a fitted
result.

The legitimate path is the one DEMO-01 itself took: a registered operating-point search for
these routes, scored on neural criteria only -- does the readout respond to the stimulus, is
it selective, is it stable -- with the behavioural criteria untouched and frozen exactly as
they are now. That search has not been run.

The other open question is whether 30.2 percent of a readout input being active while the
readout stays silent is a parameter problem at all, or whether it is the transmitter-only
sign model (`ND-10`, unresolved signs set to zero) doing the work. The two are separable and
neither has been tested.

---

# Addendum, 2026-09-12: the escape negative does not survive a search

The escape section above concluded that the route does not carry. That conclusion was
wrong, and the error is worth more than the correction.

**What was actually tested.** One operating point, selected by a registered search for a
different readout, with zero candidates searched for this one. DEMO-01 needed 108 candidates
to find the 31 that worked for its route. Reporting "the route does not carry" from a sample
of one is the same overclaim this project exists to avoid, pointed in the pessimistic
direction.

**The search.** `demo02-escape-operating-point-v1`, frozen before the probe that runs it.
36 candidates, five neural criteria carrying DEMO-01's thresholds unchanged wherever they
could travel. **11 passed.** Selected, by the rule declared before the run:

    lamina_max_rate_hz 800   synaptic_mv_per_contact 0.40   inhibitory_weight_gain 1.0

    baseline    left object (L,R)   right object (L,R)   recovery   descending active
         0           78, 0               0, 115              0          10.6%

Perfect ipsilateral separation, which is what zero cross-side edges from `LC4` and `LPLC2`
predicts. Silent at rest, silent on recovery, descending pool at 10.5 Hz against a 113.6 Hz
ceiling.

**One parameter carried the whole negative.** Every `lamina_max_rate_hz = 400` row in the
search is `0,0 / 0,0`. DEMO-01 searched that parameter over [200, 300, 400] and selected
400 -- the maximum of its own grid. A search that selects a boundary value has told you the
range was too narrow, and nobody read it that way at the time, including me.

## What the re-run found

With the searched point, the fly leaves the ground and the controls behave correctly:

    variant             acting   z rise    off-ground    roll at end
    exact                 yes    1.562 mm   2,835,000 us     179.4 deg
    readout-ablated        no    0.204 mm       5,500 us       0.7 deg
    stimulus-absent        no    0.204 mm       5,500 us       0.7 deg

The verdict is still **INVALID AS A CAUSAL CLAIM**, on four failures, and three of them are
defects in criteria I wrote rather than results.

**`E2` and `E3` are unpassable**, as this document already recorded: they cap the control's
rise at 0.15 mm while quoting a 0.204-0.211 mm noise floor in their own justification. Both
controls behaved exactly as controls should and both criteria fail them.

**`E5` fails on a stray spike.** 249 of the 250 giant-fibre spikes land after the object
reaches 38.68 degrees, with nothing at all in the 3.4 seconds before -- the response is
tightly locked to the stimulus. But the criterion anchors on "the first giant-fibre spike",
and one stochastic spike at 90,000 us is the first. The real response also begins 10,000 us
after the approach window closes, one coupling interval late. My first implementation scored
only the first half of the criterion and returned PASS; implementing the second clause
turned a false positive built from a stray spike and a settling bounce into an honest FAIL.

**`E4` resolved as the contract predicted.** The object fires the giant fibre in the
matched-size-static case too, so **the word "loom" is struck from every artifact** and the
claim narrows to a visual object of sufficient angular size. The frozen encoder computes
angular size, not expansion rate, and said so before the run.

**`E1` passes hollowly, and this is the one I should have caught.** The airborne test
everywhere in this pipeline is "no tarsus touching", and the exact run ends at **179.4
degrees of roll with its thorax below standing height**. It hopped, turned over, and never
put a foot down again. Both `E1` clauses are literally satisfied. The degenerate case for
"lost ground contact" is a fly on its back, and checking new criteria against degenerate
outcomes is a rule already written down in this project.

## The wings generate nothing, and they are what turn the fly over

The prediction registered in the contract before the run -- wing depression alone produces
approximately 0.0 mm of rise -- holds exactly:

    jump-only    rise 1.651 mm   max roll  17.1 deg   lands upright
    wing-only    rise 0.219 mm   max roll   1.9 deg   inside the 0.204-0.211 mm noise floor

## Can air be added? Yes, and it was measured rather than assumed

Fluid is disabled: `density` 0, `viscosity` 0, and all 70 rows of `geom_fluid` zero. It can
be enabled at runtime with no download. The units were pinned by measurement:

    density 1.204e-6 g/mm^3   drag at  100 mm/s = 0.031   (0.31% of body weight)
                              drag at 1000 mm/s = 3.102   (31% of body weight)

Exactly quadratic, implying a terminal velocity near 1.8 m/s, which is right for a fruit
fly. The `g/cm^3` value would give 309 times body weight and is definitively wrong here.

Two corrections to claims made earlier in this project. MuJoCo's simple density model is
**velocity-dependent drag only and has no buoyancy term**. And the wing geoms are **meshes**,
not ellipsoids -- geom type 7 is `mjGEOM_MESH`.

What air does: air alone halves the time on its back and does not stop the flip (roll still
180). Enabling the ellipsoid wing model gives 19,000 us airborne and roll 165 -- and 19 ms is
the ballistically correct flight time for a 1.7 mm hop, against 1.88 s of lying inverted.
That is independent evidence that the long airborne numbers are an artifact.

**Air is not in the plant.** It voids every threshold measured on the current one, and the
actuator-set digest would not catch the change because density is not an actuator.

## Video

`evidence/demo02/video/escape-control-matrix.mp4` and `escape-effectors.mp4`. The subject is
the control matrix rather than the fly, because a single panel of the exact run shows a leap
and a tumble and reads as an escape. Roll is on every panel and turns red past 90 degrees;
the airborne clock is split into off-ground and inverted time; and the struck words are
unrepresentable rather than merely avoided -- the renderer raises if a caption contains
"loom", "flight", "flying" or "lift". The verdict is on every frame.

## What still stands from the original document

Grooming and feeding are unchanged and their negatives stand, because **no search has been
run for either**. By the argument above that makes them untested rather than refuted, and
`MN9` responding while the decoded pool stays silent remains the sharpest single result in
this experiment -- and as of 2026-09-12 it is sharper still, because `MN9` is the correct
extension readout and the decoded pool was the pharyngeal pump. Feeding is not a route-level
negative. It is a contract that decoded the wrong population, and its replacement has not
been run.
