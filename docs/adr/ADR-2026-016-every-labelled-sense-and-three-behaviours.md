# ADR-2026-016: Every labelled sense, and the three behaviours that can be built on them

Date: 2026-09-11
Status: accepted 2026-09-11. Assumption set `foundation-v0.8` → `foundation-v0.9`.
Extends ADR-2026-014 and ADR-2026-015, whose numbers are unchanged.

```yaml
decision_id: ADR-2026-016
date: 2026-09-11
changes_assumptions: [SENS-01, SENS-04, SENS-05, MOTOR-03, BODY-01, BODY-02, ND-07]
old_decision: >-
  Taste, audition, wind, gravity, haltere, thermo/hygro and nociception are deferred
  modalities, present in the register only as names. Feeding and free flight are out of V1
  scope. SENS-01 requires every sensory population to declare an organ, a side and body
  coordinates, and no population in the codebase declares any of them. The embodied body
  actuates 42 leg degrees of freedom and publishes no sensor channel. The actuator bridge
  carries four commands, two of which are hardwired to zero.
new_decision: >-
  Every sense the release labels is resolved into a named channel carrying an organ and a
  side, as an ordered partition of the sensory set, and each channel is classified as real
  (it has a MuJoCo referent), declared (it has an invented world field, named as one) or
  absent (it has neither, and is never driven). Three behaviours are built on the channels
  that measure strongest: antennal grooming, proboscis extension, and escape takeoff. Each
  is a separate preregistered experiment with its own contract, its own controls and its own
  claim ceiling. Feeding enters scope strictly as a proboscis-extension pose with no
  ingestion. Escape takeoff enters scope strictly as a ballistic leg extension with zero
  aerodynamic force, which is not flight and does not move free flight into scope.
reason: >-
  A degree-matched-null route survey (scripts/measure_demo02_routes.py, schema 2.0, commit
  0ae123e) measured every labelled sense against every candidate output. The grooming
  subclass reaches its declared descending readout at 106x the null at the 100th percentile;
  LC4 and LPLC2 supply 30.6 percent of DNp01's input contacts monosynaptically at 82.9x and
  72.5x; labellar bristles reach MN9 at 48.6x over four hops with zero direct edges. A
  second instrument (scripts/measure_sensory_live_edges.py, commit 8981962) then established
  that these populations can actually drive something: every entry population the three
  behaviours need carries a live presynaptic sign for 99 to 100 percent of its bodies. The
  register must stop reading "deferred" for senses the code is about to drive, and must
  start supplying the organ and side it has always required.
primary_sources:
  - "10.1038/s41467-026-72152-x"  # Ozdil 2026 grooming kinematics; already checksum-locked
                                  # in configs/datasets as sha256 89826e64...
  - "UNVERIFIED-IN-REPO: the giant fibre's mixed electrical and chemical contact onto TTMn
     and PSI. Cited for the ND-07 curation below and NOT yet checked against a source in
     this repository. The curation may not proceed until it is."
  - "UNVERIFIED-IN-REPO: MN9 as the pharyngeal pump motor neuron and MN10/11/12 as the
     proboscis extensors. Cited for the feeding readout choice and not yet checked here."
alternatives_tested:
  - enter-at-LC4-directly          # rejected by ADR-2026-014; bypasses 99128 optic lobe neurons
  - MN9-as-the-feeding-readout     # rejected: it is the pump, and has no body counterpart
  - labellar-bristle-entry         # rejected: NeuroMechFly has no labellum to stimulate
  - dust-scalar-grooming-stimulus  # rejected: Track A's contamination scalar is read
                                   # directly by the arbiter, the shortcut DEMO-01 removed
  - FlyBody-model-for-aerodynamics # rejected: un-checksummed S3 mesh download
  - one-combined-takeoff-command   # rejected: hides which effector produced the motion
  - filters-instead-of-a-partition # rejected: selectors overlap, SignalFrame rejects
                                   # duplicate ids, and the failure would land mid-run
validation_effect: >-
  No tier moves. V0 Structural remains the highest supported tier and the Stage 2 exit gate
  remains v4 at 0 of 3. Each behaviour is engineering acceptance only. The DEMO-01 verdict is
  explicitly NOT inherited: adding actuators changes the plant, so DEMO-01's 0.12 integral
  gain, its 2.294 mm residual standing drift and the +11.5 degree drift bearing that chose
  its cue placement are void for any new body and must be re-measured with no brain attached
  before any threshold depending on them is frozen. Any change to station-keeping is
  MOTOR-05 attempt 2 and runs under the already-registered commit-reveal protocol in
  configs/experiments/motor-05-validation-protocol-v1.json.
approved_by: project-owner, delegated 2026-09-11 ("take the best decisions along the way yourself")
```

## Context

DEMO-01 executes 165,122 neurons and 25,563,197 edges. It drives **one** sensory population,
a declared retinotopic map onto lamina L1/L2/L5, and it emits **two** numbers. The body has
133 degrees of freedom and 42 are actuated. Every other sense the release labels — 15,912
bodies across eleven classes and nineteen subclasses — is in the graph, is executed every
step, and receives nothing.

That was a reasonable place to stop. It is not a reasonable place to stay, and the reason is
that the register does not describe it honestly. `SENS-05` says taste, audition, wind,
gravity, haltere, thermo/hygro and nociception "remain explicit extension modules, not fake
generic channels", which reads as a scope boundary but is really a standard: *if you build
them, build them specifically*. `SENS-01` requires every sensory population to declare an
organ, a side, body coordinates, a receptive field, a transducer, a delay, a source and a
confidence. **No population in this codebase declares any of them.** DEMO-01's lamina entry
is selected by cell type and `somaSide` and nothing else.

Three measurements changed what is buildable.

**The routes were measured, with a null.** Schema 2.0 of the route survey scored every
labelled sense against every candidate output, against populations matched in size and
out-contact profile. Grooming, feeding and escape all came back stronger than the visual
route currently in production. Two of the previous conclusions were overturned in the
process, and are recorded in commit `0ae123e` rather than quietly dropped.

**The organ and side were in the release the whole time.** `entryNerve` names the nerve an
afferent enters through and `rootSide` carries the side. Together they resolve 15,856 of the
15,912 in-graph sensory bodies to an organ and a side. This is exactly what `SENS-01` has
required since the register was written, and nothing had ever read those two columns.
`somaSide` cannot do it, because sensory somata are peripheral and outside the volume.

**And it was verified that these afferents can drive anything at all.** A population can be
well annotated, sit in the graph, take injected drive, produce a spike raster that renders
convincingly, and change nothing downstream, because every one of its outgoing edges carries
a zero sign. That is already true of the photoreceptors: histaminergic, against a
transmitter model with no histamine, all 66,533 output edges dead. Nothing had checked the
other fifteen thousand. Commit `8981962` checks them, and reproduces the photoreceptor case
exactly — the `visual` channel is 0.0 percent live with zero live edges, which is how the
instrument was shown to work rather than merely to run.

## Decision

**1. The sensory space is an ordered partition, not a set of filters.** Selectors overlap in
the real data: subclass `pharyngeal sensillum` spans class `gustatory` (48) and class
`mechanosensory` (39); subclass `haltere` spans two classes; subclass `abdomen` spans three;
and 8,062 bodies, including every visual and every olfactory one, carry no subclass at all.
Independent filters would hand the same body to two encoders, and `SignalFrame` rejects
duplicate ids, so that failure would land inside a run rather than where the selector was
written. A priority ladder assigns every in-graph sensory body exactly once: **122 channels
over 30 modalities, 15,856 assigned, 56 unassignable and named.**

**2. Every channel declares what kind of thing its world quantity is.** `real` has a genuine
MuJoCo referent — contact, joint angle, load, orientation, angular velocity, antennal
deflection. `declared` has an invented field carried under a named assumption — sucrose
concentration, odour plume, wind. `absent` has neither, and is never driven. Thermosensory
(25 bodies) and hygrosensory (66) are `absent`: MuJoCo carries no temperature and no
humidity field, and inventing one is precisely the fake generic channel `SENS-05` forbids.
**This is what "enable every labelled sense" honestly resolves to.** Two senses are enabled
by being named as unbuildable, with the reason attached, rather than by being given a
plausible-looking number.

**3. A channel with zero live outgoing edges may not be driven.** The gate is a bright line
and not a tuned threshold, because the live fraction runs from 0 to 1 across the labelled
senses and any cut-off in between would be a number chosen after seeing the data. Partial
muting is *reported and never used to exclude*, so that the fraction travels with any claim
built on that channel. Under this rule the `visual` channel is refused and vision enters at
the lamina surrogate, which is 100 percent live — reproducing DEMO-01's existing choice from
a measurement rather than inheriting it.

**4. Three behaviours, three contracts, three claim ceilings — never one narrative.** Track
A's `required_sequence` made every claim conditional on every other, which is how one failing
criterion sank a thirty-run matrix. Grooming, feeding and escape are separate preregistered
experiments with separate `experiment_sha256` stamps. Their honest ceilings differ by a wide
margin: escape has a monosynaptic 30.6 percent input share, feeding has no labellum, no pump
and no ingestion. Bundling them would let the strongest launder the weakest, and a joint
presentation is permitted only if it carries all three `may_never_claim` blocks verbatim.

**5. Feeding enters scope as a pose, and the strongest route is the one that cannot be
built.** Labellar bristles reach MN9 at 48.6x the null — the best feeding number measured —
and NeuroMechFly has no labellum on which to place a stimulus, and no pharynx for MN9 to
pump. So the entry becomes tarsal taste bristles, which sit on the legs and have real
contact physics, and the readout becomes the proboscis motor neurons rather than MN9,
because MN9 is the pump and decoding it to a rostrum command would fabricate function rather
than merely magnitude. **The route that was not built is named in the contract's declared
limitations, with the reason.**

**6. Escape takeoff enters scope, and is not flight.** NeuroMechFly sets no `density` and no
`viscosity` and has no fluid geoms, and `add_fly` re-applies the fly's globals over the
world's, so **wing motion generates exactly zero lift**. All height comes from leg extension
against the floor, which MuJoCo computes correctly with no fluid model. The `fruitfly.xml`
carrying `density="0.00128"` and `wing-fluid` ellipsoids belongs to **FlyBody**, a different
model requiring an un-checksummed mesh download. §7.2 keeps `Free flight` in the
out-of-scope list, and gains a sentence saying a zero-aerodynamic ballistic takeoff does not
move it.

**7. `ND-07`'s curation clause is invoked for exactly one pair, and only after verification.**
The giant fibre's contacts onto TTMn are 1.49 percent of TTMn's input by chemical contact
alone, and in the real animal that synapse is substantially electrical. `ND-07` permits
"curate established pairs". That curation is the honest route, and it is blocked until its
source is verified in this repository — it may not be replaced by raising a gain until the
jump happens.

## What this changes in the register

| location | change |
|---|---|
| `SENS-01` | Unchanged in wording, satisfied for the first time. Every channel now declares organ, side and transducer; body coordinates and delay follow with the bus. |
| `SENS-04` | Append: antennal deflection is driven from body physics as a real mechanical quantity (`l_pedicel`/`r_pedicel` `qpos`) and transduced to the 65-body grooming subclass; the dust/contamination scalar leaves the critical path. |
| `SENS-05` | Narrow. Taste is no longer deferred: it is a side-resolved leg-taste-bristle module (subclass `taste bristle`, 70 bodies). Audition, wind, gravity and haltere are enabled as named channels with declared or real referents. Thermo/hygro stay absent, now **with a measured reason**. `generic_substitution_allowed: false` is unchanged and becomes binding: `SENSOR_SUCROSE` is retired as a decoder input. |
| `MOTOR-03` | Append the two new commands, `actuator:jump-extension` and `actuator:wing-depression`, kept separate so each effector's contribution stays measurable. |
| `BODY-01` | Append: the actuated DOF set is declared per experiment, not globally, and station-keeping gains are re-derived per set and never inherited. |
| `BODY-02` | Append: adhesion may be conditioned on replayed limb kinematics; adhesion gain, contact stiffness, force limits and floor damping remain frozen. |
| `ND-07` | Append the single curation candidate and its blocking condition. |
| new rows | `MOTOR-05` (stance-conditioned station-keeping, attempt 2). **And `DEMO-02`, `DEMO-03` and `MOTOR-06`, which are cited as `assumption_ids` in committed contracts and stamped into every DEMO-01 `ActuatorCommandFrame`, yet return zero hits in `configs/assumptions.json`.** Closing that is a defect fix, not a new decision. |
| AGENTS.md §7.1 | Add the three behaviours. |
| AGENTS.md §7.2 | Replace `feeding` with "gut physiology, ingestion, pharyngeal pumping and any feeding claim beyond a proboscis-extension pose". Keep `Free flight`, and add the ballistic-takeoff sentence. |
| AGENTS.md §14 | One log row. |

## Consequences

**No scientific claim changes and no tier moves.** V0 Structural stands. The Stage 2 exit
gate stays v4 at 0 of 3. Every artifact here is structural or engineering acceptance.

**DEMO-01's calibration does not transfer, and this must not be discovered later.**
`demo01-visual-lateral.json` records that the 0.12 integral gain was doubled relative to
Track A *because that body actuates legs only*. Add actuators and the gain, the 2.294 mm
residual drift and the +11.5 degree drift bearing that chose the cue placement are all void.
An actuator-set digest is stamped into every recording and contract, with a fail-closed
assertion, because `qpos` stays 133 and a mismatched replay would otherwise look fine.

**One capability is given up permanently.** Freezing a single entry union of 21,254 bodies
means enabling a modality never forces a CUDA rebuild — but `central_entry_outgoing_gain`
becomes all-or-nothing across every modality and is committed to 1.0. It is a searched axis
today with a registered value of 10.0. That is a real loss and it belongs here rather than
in a comment.

**Sensory delay is quantised to the coupling interval.** Because `push_inputs` zeroes every
neuron's rate on each call, all senses merge into one frame per 15 ms boundary, so a 5 ms
antennal conduction delay and a 12 ms leg delay are indistinguishable. Declared, not fixed.

**Two senses are enabled by being declared unbuildable.** Thermo and hygro resolve, are
counted, and are refused a transducer. Anyone reading the artifact can see the sense exists
in the data, see that it is off, and see why.

## Alternatives considered

**Build the senses without touching the register.** Rejected, and it was the tempting one —
Track A and DEMO-01 both ship under explicit claim boundaries without amending anything. But
`SENS-05` would then read "deferred" for senses the code drives every 15 ms, which is the
register describing a system that no longer exists.

**Enable every labelled sense, including thermo and hygro.** Rejected on `SENS-05`'s own
terms. A temperature channel with no temperature field is a fake generic channel, and its
0.82x null score is not the reason — DEMO-01's own validated entry scores 0.44x, so a low
score cannot rule anything out. The reason is that there is nothing to transduce.

**Use the labellar route for feeding, since it is the strongest.** Rejected: there is no
labellum in the body. Building it would mean inventing a mouth part and then reporting the
48.6x figure beside a behaviour that number did not produce.

**Collapse the takeoff into one command.** Rejected. Two effectors on two anatomical paths
(DNp01→TTMn direct, DNp01→PSI→DLMn) need two commands, or "the wings produced no lift"
becomes unverifiable from the trace and the `wing-only` control cannot be run.

**Switch to FlyBody for real aerodynamics.** Rejected: an un-checksummed S3 mesh download,
against the dataset-locking rule that every other input in this project obeys.
