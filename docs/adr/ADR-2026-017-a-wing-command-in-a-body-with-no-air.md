# ADR-2026-017: A wing command in a body with no air

Date: 2026-09-12
Status: PROPOSED

```yaml
decision_id: ADR-2026-017
date: 2026-09-12
changes_assumptions: [MOTOR-03, DEMO-02, BODY-02]
old_decision: >-
  The escape decoder emits two commands, actuator:jump-extension and
  actuator:wing-depression, kept separate so that each effector's contribution to a takeoff
  stays measurable from the trace.
new_decision: >-
  The escape decoder emits actuator:jump-extension only. actuator:wing-depression stays in
  the MOTOR-03 vocabulary, stays actuated in the plant and stays runnable as a control; the
  decoder binds it to zero. The wing joints are NOT removed, so the actuator-set digest is
  unchanged and every threshold measured on this plant still holds.
reason: >-
  The two-command split did its job and returned an answer. Commanding wing depression in
  this body produces no force and inverts the fly. wing-only rises 0.219 mm against a
  measured 0.204 to 0.211 mm standing noise floor -- indistinguishable from doing nothing --
  while the jump-plus-wings run reaches 180 degrees of roll and ends upside down with its
  thorax below standing height. jump-only reaches 17.1 degrees and lands upright.
  A wing stroke in a model with no density, no viscosity and fluid enabled on no geom is
  not a wing stroke. It is a mass being swung, and the only thing it can transfer is angular
  momentum.
validation_effect: >-
  No tier moves. The plant is unchanged and its measured thresholds carry over: the 5.0 to
  5.5 ms contact-chatter floor, the 0.204 to 0.211 mm standing excursion band, and the jump
  envelope. This is a decoder binding change, not a body change.
```

## What the two-command split bought

`ADR-2026-016` split the takeoff into two commands specifically so that "the wings
generated no lift" would be verifiable from the trace rather than asserted. It records the
reason: one combined command "would hide which produced the motion and make the zero-lift
statement unverifiable".

That was right, and the split has now paid for itself twice. It produced the zero-lift
measurement, and it produced something the contract did not predict: the wing command is not
merely useless here, it is harmful.

    variant      thorax rise   longest off-ground   max roll   roll at end
    exact           1.562 mm          2,216,000 us     180.0        179.4
    jump-only       1.617 mm             17,000 us      17.1          0.4
    wing-only       0.219 mm              5,500 us       1.9          0.2

The exact run's 2,216,000 us is not flight time. It is a fly that hopped, turned over, and
never put a foot down again, because every airborne test in this pipeline is "no tarsus
touching" and a fly on its back satisfies that permanently.

## Why this is a decoder decision and not a body decision

The wing joints stay actuated. Nothing about the plant changes, so the actuator-set digest
is identical and every quantity measured against it carries over unexamined. What changes is
that the escape decoder no longer emits a command for an effector whose physics is absent
from the model.

This is the narrow reading and it is the correct one. A real fly's wings generate lift and
stabilise a takeoff. Ours cannot, because the fluid model is off. Commanding them is
modelling an effector we have chosen not to simulate, and the measured consequence is a
torque with no counterpart.

## Why not simply add air

Measured rather than assumed, and the units were pinned by drag rather than by arithmetic:
air is 1.204e-6 g/mm^3 in this model's mm/g/s units, giving 31 per cent of body weight of
drag at 1 m/s and a terminal velocity near 1.8 m/s, which is right for a fruit fly.

    condition                      rise      airborne     max roll
    vacuum, wings ON             1.825 mm   1,881,500 us     180.0
    air, wings ON                1.638 mm     844,000 us     180.0
    air + ellipsoid wings ON     1.721 mm      19,000 us     165.4
    vacuum, wings OFF            1.651 mm     964,500 us     180.0

Air alone halves the time on its back and does not stop the flip. The ellipsoid wing model
does bring the airborne time to 19,000 us, which is the ballistically correct flight time for
a 1.7 mm hop and is strong evidence the long numbers are an artifact -- but it still reaches
165 degrees of roll, and it changes the plant.

Changing the plant voids the 5.0 to 5.5 ms chatter floor, the 0.204 to 0.211 mm standing
band and the entire jump envelope, all of which are measurements on the current body. It also
is not caught by the actuator-set digest, because density is not an actuator. Air is a larger
decision that deserves its own ADR and its own re-measurement, and it is not this one.

## What this does not fix, stated before the run

`jump-only` is airborne for 17,000 us. The escape criteria require 20,000 us, a threshold
derived from the measured 5.0 to 5.5 ms contact-chatter floor with roughly a four-fold
margin, and frozen before anyone measured how long this body's leg-only hop lasts.

So this decision is expected to trade one failure for another: the roll clause should pass
and the airborne clause should fail, by three milliseconds. That prediction is recorded here,
before the run, precisely so that it cannot be presented afterwards as a surprise or
quietly resolved by moving the number. A 1.6 mm hop that clears the ground for 17 ms is a
real takeoff and the threshold that excludes it was calibrated against noise rather than
against the behaviour.

The threshold is not moving. If the run fails that way, the failure is the result.

## Alternatives rejected

**Lower the airborne threshold to admit 17 ms.** Rejected. It is the measured value, and a
threshold set to the number that was observed is not a threshold.

**Increase the jump extension for a longer hop.** Rejected. The envelope is strongly
non-monotone -- 1.8 rad produces less height than 1.0 rad -- so this is tuning a scaffold
against an acceptance outcome, which is the failure mode this project exists to avoid.

**Add air and the ellipsoid wing model.** Deferred to its own ADR, for the re-measurement
reasons above. It also still reaches 165 degrees of roll, so it does not clearly solve the
problem it would be brought in for.

**Remove the wing command from MOTOR-03 entirely.** Rejected. The zero-lift claim has to stay
verifiable from a trace, and the wing-only control has to stay runnable. The command keeps
existing; this decoder stops emitting it.
