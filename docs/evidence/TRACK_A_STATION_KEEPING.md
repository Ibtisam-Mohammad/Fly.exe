# Track A station-keeping: root cause of the grooming-displacement failure

Status: diagnosed, not fixed. No physics parameter was changed.

Track A v3 acceptance fails in 30 of 30 runs on one criterion: the body translates a median
6.26 mm during a 3-second grooming bout against a 2.5 mm one-body-length cap. ADR-2026-006
listed this as an open engineering issue with the constraint that it "must be fixed in the
stance, contact or adhesion model, not by raising the cap". This is the diagnosis.

## The displacement decomposes into three parts, and the grooming replay is the smallest

| condition | displacement over 3 s | attributable to |
|---|---|---|
| standing, no command, all six legs adhered | **2.161 mm** | baseline creep |
| front-leg adhesion lifted, no grooming replay | **4.917 mm** | + 2.756 mm from lifting two legs |
| full grooming bout with replay (v3 acceptance median) | **6.26 mm** | + ~1.34 mm from the replay |
| adhesion fully off, standing | **14.297 mm** | what adhesion is already preventing |

The replay contributes the least of the three. The cap was introduced to check that the grooming
joint replay was not translating the body, and on this decomposition it does not principally do
that: 2.16 mm of the 6.26 mm is present with no command at all, and another 2.76 mm comes from
the adhesion pattern that grooming requires because the front legs must leave the ground.

**The 2.5 mm cap is therefore unreachable before grooming even begins.** Baseline creep runs at
about 0.88 mm/s, so a stationary body exceeds 2.5 mm after roughly 2.8 seconds of standing. A
3-second bout cannot pass, whatever the replay does.

## It is a persistent force, not a startup transient

Displacement measured every 0.5 s while standing under no command:

```
 t(s)   x(mm)     y(mm)    |disp|(mm)  incr/0.5s   heading(rad)
  0.5    1.3764  -0.0985     0.5944     0.5944   +0.05442
  1.0    1.7259  -0.2986     0.9824     0.3880   +0.15989
  1.5    1.5754  -0.3981     0.8808    -0.1016   +0.19146
  2.0    2.0106  -0.3295     1.2643     0.3835   +0.20241
  2.5    2.3808  -0.2342     1.6078     0.3435   +0.20333
  3.0    2.9476  -0.1317     2.1613     0.5535   +0.21865
  3.5    3.7154   0.0571     2.9255     0.7642   +0.20942
  4.0    4.2379   0.2393     3.4556     0.5301   +0.18417
  4.5    4.7858   0.4886     4.0249     0.5693   +0.11755
  5.0    4.7725   0.4639     4.0088    -0.0162   +0.12396
  5.5    5.4359   0.5133     4.6736     0.6648   +0.15717
  6.0    6.0724   0.5515     5.3105     0.6370   +0.18726
```

The increment per half-second is roughly constant across six seconds and the trajectory is
almost pure `+x`. A settling transient would decay; this does not. The heading also rotates by
up to 0.22 rad, so it is not pure translation. Re-zeroing `qvel` before the probe changes the
3-second figure by nothing at all — 2.161 mm either way — so it is not stored momentum from the
warmup.

The direct signature is in the actuators. At the settled pose the position actuators are
saturated: `qfrc_actuator` reaches 240.0, the force ceiling, with a sum of absolute forces of
1751, against constraint forces peaking at 252.7. The body is being pushed while it is nominally
standing still.

## The obvious fix was tested and makes it worse

`_standing_targets` holds the pose the settle phase *commanded*, not the pose the body actually
reached, and the two differ by up to 0.169 rad — 9.7 degrees — with a leg-DOF RMS of 0.079 rad.
That looked like the defect: a permanent position error feeding a permanent actuator torque.

It is not. Holding the achieved settled pose instead **doubles** the drift, from 2.161 mm to
4.708 mm over the same 3 seconds, a 118 percent increase. The residual actuator force is
load-bearing: it is part of what holds the body up, and removing it lets the body sag and slide
further. The commanded pose is holding station *better* than the body's own settled configuration
does.

So the standing pose is not a static equilibrium of this model, and neither is the pose the model
settles into. There is no configuration in the tested set at which this body stands still.

## What this is, and what would actually fix it

The FlyGym demonstration controller this scaffold is built on is a locomotion controller. It has
a CPG for walking and a turning layer on top; it has no station-keeping mode. The engine's
standing branch is an open-loop pose hold — set position targets, adhere all six legs, and step
the physics. Nothing in that loop measures body displacement or corrects it, so a persistent net
force integrates without opposition. Adhesion is already doing most of the available work: with
it off the body travels 14.3 mm in 3 s, so adhesion suppresses about 85 percent of the slide, and
the remaining 2.16 mm is what leaks past it.

A legitimate fix is a **closed-loop station-keeping controller**: sense thorax displacement and
heading against the settled pose and adjust leg targets to null them. That is a controller
addition, not a physics change, so it does not violate the ADR-2026-006 constraint. Two things
must be said about it in advance:

1. It would be an engineering scaffold with no biological content, provenance `E`, and it must be
   labelled that way. Real flies hold station with load-sensing reflexes this model does not have.
2. It would make the grooming-displacement criterion pass essentially by construction, which is
   the reason to be careful about what that criterion is taken to show.

What is **not** legitimate, and was not done: increasing adhesion force, stiffening contacts,
raising actuator force limits, adding damping to the floor, or welding the body during grooming.
Any of those would clear the cap by changing the physics rather than the controller.

## The criterion should be restated as a differential

The cap exists to bound how much the grooming replay moves the body. Now that baseline creep is
measured at 0.88 mm/s independent of grooming, an absolute cap on total displacement during a
bout does not measure that. It measures the stance controller, and it fails for a reason that has
nothing to do with grooming.

The criterion that measures the intended thing is the difference between displacement during a
grooming bout and displacement while standing for the same duration under the same adhesion
pattern. On the numbers above, the replay's own contribution is about 1.34 mm out of 6.26 mm,
which would clear a 2.5 mm allowance while the absolute figure does not.

**This has not been adopted.** Restating a criterion after it fails is exactly the move this
project has had to repair twice already, and it would be self-serving here: it converts a failing
acceptance run into a passing one. It is recorded as the analytically correct criterion and left
for an explicit decision, with the absolute cap and its 0-of-30 failure standing in the meantime.
Track A remains not an accepted milestone either way, because the station-keeping defect is real
regardless of which criterion names it.

## Reproducing

The probes are `probe_drift.py`, `probe_drift2.py` and `probe_drift3.py` in the session
scratchpad; they construct `FlyGymTrackABodyEngine` from the registered `BODY-01`, `NUM-01`,
`SENS-03`, `SENS-04` and `MOTOR-03` values and the checksum-locked grooming trajectory, and are
deterministic at seed 1. The baseline figure reproduces the previously reported 2.16 mm exactly,
and the grooming-adhesion figure reproduces the previously reported 4.92 mm exactly, which is
what establishes that the probes and the acceptance runs are measuring the same thing.

## Second open issue: rendered-timing divergence

Not addressed here. Enabling the renderer shifts the last two Track A transitions by 1.44 s, up
from 30 ms in v2, and the equivalence control passes because it compares transition identities
and reasons rather than times. The control needs a timing tolerance; a rendered run is not a
timing replica of a headless one, and until the control says so it is not testing what it claims.
