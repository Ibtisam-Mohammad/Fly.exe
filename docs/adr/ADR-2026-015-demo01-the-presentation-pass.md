# ADR-2026-015: DEMO-01, the presentation pass, and the picture that contradicted its caption

Date: 2026-09-11
Status: accepted
Supersedes nothing. Extends ADR-2026-014, whose numbers are unchanged.

## Context

DEMO-01 passed its frozen acceptance contract and shipped four videos. The science was
sound and the video was not: it was a laboratory instrument panel that happened to be
animated. Compared frame by frame against the EON Systems embodied-fly demonstration of
March 2026, ours was better evidence and much worse film, and two of its defects were not
matters of taste.

**The body camera was baked into the recording.** Frames were rendered inside the
simulation loop, so one framing formula had to serve the whole run and any correction cost
a full re-simulation of four control variants. The formula aimed at the midpoint between
fly and cue at a distance proportional to their separation. That is backwards: as the fly
arrives the separation goes to zero, the camera closes in, and a 2.5 mm sphere fills a
frame the 3 mm fly has left. The climax of the run was the one moment that could not be
watched.

**The brightness map was destroying the result.** Measured against the recordings that
shipped, a decayed spike count of 1.0 already rendered at 0.95 of full white and 2.0 at
0.998, while the actual per-neuron range in the exact run reaches 76.3 with a median
99.9th percentile of 47.2. The entire top two decades were flattened into white. The cost
was not cosmetic: the shuffled-connectome control's median 99.9th percentile is 5.96
against the exact run's 47.2, an eightfold difference in how hard the graph drives itself,
and the display was erasing it. The control comparison's central visual claim was being
destroyed by its own colour map.

**And one frame said the opposite of its caption.** The renderer drew the cue
unconditionally, so the stimulus-absent control -- the panel whose entire claim is that
there is nothing in the world to react to -- showed a cue sitting in front of a fly that
could not see it. No number was ever affected. The picture contradicted the caption above
it, which is the failure mode this project exists to avoid, in the medium most people will
actually look at.

## Decision

**1. Rendering is separated from simulation by construction, not by convention.** The run
records `qpos`, the model's full generalised position vector, once per coupling interval,
and writes no video at all. Rendering rebuilds the identical model and writes a recorded
state into it. This is exact rather than approximate, because the model plus `qpos`
determines every body frame in the scene. It is also 40 times smaller: 343 kB of poses
against 14 MB of baked video for the same five seconds. The replay entry point refuses to
run on a body whose clock has advanced, so a live simulation cannot reach it.

**2. Every display constant is measured, and the two that matter are measured against the
control contrast.** Brightness is logarithmic against a fixed reference of 48.0, the
measured median 99.9th percentile of the exact run, and activity is averaged over the
neurons drawn at a pixel rather than summed, so the optic lobes stop rendering white merely
because more somata project there. The gain of 2.2 is the value that maximally separates
the exact run's 99th-percentile lit pixel from the shuffle's, which is
`ln(0.308/0.127) / (0.308 - 0.127) / exposure`. The scale is fixed rather than per-run,
because per-run normalisation would make the four control panels incomparable, and that is
the one thing this video may not do.

**3. The shot list is a pure function of the recording, and it cuts on the run's own
events.** The first cut lands on the interval in which the decoder first commanded
locomotion, so the shot changes because the fly moved. The camera aims at the fly rather
than the midpoint in every shot but the establishing one. The camera track is smoothed over
a third of a second, and only the camera track: every recorded quantity, the trajectory
inset, the displacement and the acceptance contract all read raw poses, and the frame says
so.

**4. The cue is drawn as what it actually is, which is not solid.** The encoder models the
cue in the horizontal plane with no height and no collision, and explicitly saturates its
angular radius at a hemisphere once the fly is nearer than the radius. So a successful run
ends with the fly standing *inside* a sphere wider than itself, and no camera angle
rescues that. Drawing it opaque asserts a solidity that does not exist and hides the animal
at the exact moment the demonstration succeeds. It is drawn translucent, a cue-size floor
keeps it under 45 percent of frame height in every shot, and the missing collision is now
named in the declared scaffolds where it should have been from the start.

**5. What was cut from the frame was moved, not dropped.** The fourth strip chart became
four live population rates beside the brain, where they describe the picture they sit next
to. The third footer line became a section on the opening card. Nothing that qualified a
claim was removed to make room.

## What this cost, and what it caught

| what | how it was caught |
|---|---|
| the stimulus-absent control's video drew the cue it is defined by lacking | looking at the control's own frames, which nobody had done |
| the brightness map was saturating at about 2 against a real range of 76 | measuring the glow distribution instead of judging it by eye |
| the exact and shuffled brains differ eightfold and rendered identically | the same measurement, applied to both variants |
| the cue has no collision, and the scaffolds did not say so | asking why no camera angle could frame the arrival |
| the legend was drawn over the left optic lobe it explains | rendering a frame and looking at the left third of it |
| the structural cloud was fainter in the hero view than in the small panels | rendering both at once and seeing them disagree |
| the leg shot was scheduled after the fly had stopped walking | printing the separation at each cut rather than assuming |

## Consequences

**No scientific claim changes, and the numbers were re-derived rather than asserted.** The
four variants were re-run from a clean tree at the new commit, and the frozen acceptance
contract was applied to the new recordings. Everything in ADR-2026-014 stands. The tier
remains V0 Structural.

**The simulation code path is unchanged in every respect that could alter a trajectory.**
Recording `qpos` is a read. The appearance work touches material, texture and lighting
constants that no solver reads, and it happens in a separate object that is built only for
rendering. The reproduction check in the evidence record is what makes that a measurement
rather than a claim.

**Two limitations are now stated that were not before.** The cue has no collision and the
fly walks through it. And the compiled world carries no light source at all, so nothing in
the scene casts a shadow; a contact shadow was not added under the fly, because an invented
shadow is invented light transport and this project does not draw what it did not compute.

## Alternatives considered

**Keep rendering during the run and just fix the camera formula.** Rejected. It would have
made every future shot correction cost four re-simulations, and the defect was the coupling
itself rather than the particular formula.

**Normalise brightness per run so every variant looks well exposed.** Rejected, and it is
the most tempting of these. It would make each panel individually handsome and the
comparison meaningless, because the comparison's entire content is that one brain is
quieter than another.

**Add a contact shadow under the fly so it looks grounded.** Rejected. The model has no
light source; a shadow would be drawn light transport that was never computed.

**Move the cue, or raise it, so the fly stops walking inside it.** Rejected. The cue
position is part of a scenario whose verdict is on the record, and changing the scenario to
make the video prettier is changing the experiment after seeing the result. The rendering
was changed to tell the truth about the geometry instead.

**Copy EON's arena: banana slices, pebbles, trees.** Rejected. The encoder models exactly
one object, so exactly one object is drawn. Scenery a viewer would take for things the fly
can see, when the brain receives nothing from them, is the same class of error as drawing a
cue in the control that has none.
