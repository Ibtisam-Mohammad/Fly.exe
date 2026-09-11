# DEMO-02: three behaviours, three negatives, and one control that misbehaves

Status: complete and negative. Twelve runs, all at commit `7b292e3a` with a clean worktree.
Tier unchanged at **V0 Structural**. The Stage 2 exit gate is untouched at v4, 0 of 3.

| behaviour | verdict | behaviour-exists criterion |
|---|---|---|
| grooming | **NO DEMONSTRATION** | `G1` fail |
| feeding | **NO DEMONSTRATION** | `F1` fail |
| escape | **NO DEMONSTRATION** | `E1` fail |

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

This is the sharpest result of the three.

`MN9`, the pharyngeal pump, **responds**: 10 spikes, peak 4.53 Hz. The twelve proboscis motor
neurons that the contract decodes produce nothing.

`MN9` is exactly where the route survey pointed -- labellar bristle to MN9 at 48.6 times a
matched null over four hops with zero direct edges. The contract declared, before the run,
that this route could not be built: NeuroMechFly has no labellum on which to place a
stimulus, and no pharynx for a pump to pump. So the entry moved to the leg taste bristles and
the readout to the proboscis extensors, and both substitutions were recorded as limitations
rather than hidden.

The dynamics have now confirmed the structural survey was pointing at the right place, and
the body is what prevents using it. The pump motor neuron fires with nothing to pump.

### Escape: the loom pathway computes, the giant fibre does not fire

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

**This applies to DEMO-01 as well**, which uses the same permutation as its topology control.
Anything DEMO-01 concluded from its shuffled variant should be re-examined against this.

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
