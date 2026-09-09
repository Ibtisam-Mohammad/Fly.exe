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

---

# The controller, built 2026-09-09, and what it refutes

Status: the station-keeping defect is **fixed**. B2 passes at every pose tested. **B3 does
not pass as written, and this section shows that B3's statistic does not measure what it
claims to.** Track A is therefore still not an accepted milestone.

No physics parameter was changed. Adhesion force, contact stiffness, actuator force
limits, floor damping and the bout duration are all untouched, and nothing is welded.
The change is `MOTOR-04`, provenance `E`, a closed-loop controller in the standing branch.

## What the controller is

Proportional-integral feedback on thorax pose against the pose held when standing began,
acting through the **femur-tibia (FTi) pitch of all six legs**: common mode shifts the
body fore-aft over planted feet, differential mode yaws it. Registered gains:

```
station_keeping_gain_rad_per_mm            0.02
station_keeping_integral_rad_per_mm_s      0.06
station_keeping_yaw_gain_rad_per_rad       0.05
station_keeping_yaw_integral_rad_per_rad_s 0.4
station_keeping_max_offset_rad             0.07
station_keeping_max_yaw_offset_rad         0.02
station_keeping_settle_us                  2000000
```

The channel was not guessed. Every leg joint group was perturbed in common and
differential mode and the resulting 3-second drift measured; FTi pitch has the largest
authority in each mode, about -37.5 mm/rad fore-aft and -20 rad/rad yaw.

## Three design choices that are load-bearing, and why

**1. The offset limit is part of the control law, not a safety margin.** The plant is not
monotone. Static common-mode offset against measured fore-aft drift velocity:

```
offset (rad)   0.00   0.02   0.04   0.05   0.06   0.08   0.10   0.12   0.16   0.20
v (mm/s)      +1.016 +0.385 +0.478 +0.195 -0.210 -0.142 +0.353 +1.396 -0.353 -2.036
```

Zero crossing near 0.055 rad, then the sign reverses twice more. **At 0.12 rad the drift
is +1.40 mm/s, worse than no control at all.** The first PI sweep used a 0.12 rad limit,
the integral wound to the ceiling, and the controller sat on the single worst operating
point available to it in every run. The limit is 0.07 rad because that is the upper edge
of the first monotone branch.

**2. The integral persists across stances; only the position reference is released.** The
integral converges on the actuator bias that cancels the drift force, and that force is a
property of the standing configuration and the body's load, not of a position. Discarding
it on every walk makes each stance re-converge from zero, and the re-convergence
excursion is itself most of the displacement being measured.

**3. There is a 2-second settle window before t=0, and it changes nothing about the
body.** Its only purpose is to charge the integral. Every physics state it touches --
`qpos`, `qvel`, `act`, `ctrl`, `time` -- is saved and restored, so the body enters the run
exactly as it did before. The first attempt restored nothing, and the 2 s of drift it let
through moved the thorax about 1.2 mm into the dust patch; the settled-body guard caught
it, which is the guard doing its job.

**A rate term was implemented and rejected.** Differentiating thorax pose over a 500 us
step measures per-step contact jitter far more than drift, and injecting that at 2 kHz
into a near-saturated channel destroys the loop:

| damping gain | 3 s | 6 s | 12 s | heading |
|---|---|---|---|---|
| 0.00 | **0.357 mm** | 0.783 | 1.074 | 0.225 rad |
| 0.01 | 5.926 mm | 7.252 | 9.091 | 1.201 rad |
| 0.03 | 12.611 mm | 11.780 | 21.381 | 2.687 rad |
| 0.08 | 16.672 mm | 30.617 | 30.795 | 2.597 rad |

**A signed lateral channel exists and is deliberately unused.** Differential
coxa-trochanter roll gives clean antisymmetric lateral authority: +0.03 rad gives
+7.84 mm, -0.03 rad gives -7.97 mm, about 263 mm/rad. It is not used because lateral
error is only about 0.7 mm of the worst residual, and a 263 mm/rad actuator on a
contact-mode-switching plant is a stability risk for a 17 percent improvement. It is
recorded so it need not be rediscovered.

## What it achieves

Standing under no command, all six legs adhered, across seven settled poses. The spawn
heading and position are varied because **the seed does not reach the standing branch at
all** -- it only seeds the CPG, so every seed gives bit-identical standing runs. Pose is
the variation that matters, and the acceptance matrix produces it by walking to three
different food positions.

| pose | 3 s off to on | 6 s off to on | 12 s off to on |
|---|---|---|---|
| registered | 2.161 to **0.357** | 5.311 to 0.783 | 9.703 to 1.074 |
| heading +0.6 | 2.814 to **1.413** | 4.653 to 1.230 | 10.140 to 1.940 |
| heading -0.6 | 1.559 to **0.226** | 3.856 to 0.249 | 8.326 to 3.163 |
| heading +1.57 | 2.835 to **1.120** | 5.518 to 1.676 | 10.618 to 3.038 |
| heading -1.57 | 1.714 to **0.721** | 3.905 to 0.836 | 8.060 to 2.066 |
| shifted +2 mm | 2.738 to **0.395** | 5.097 to 0.668 | 9.293 to 1.362 |
| heading +0.3, -1 mm | 2.753 to **0.420** | 4.926 to 0.476 | 9.108 to 1.027 |

**B2, at most 2.5 mm at 3 s, fails at 4 of 7 poses uncontrolled and passes at 7 of 7
controlled.** Worst-case 12-second displacement falls from 10.6 mm to 3.2 mm. The
0.88 mm/s creep is gone: at the registered pose the residual velocity decays from
0.119 to 0.049 mm/s across 12 s, against a flat 0.72 to 1.05 mm/s uncontrolled.

## B3's statistic is refuted, by three independent demonstrations

B3 measures whether displacement at 6 s is less than 1.5 times displacement at 3 s. It
fails at 2 of the 7 poses above: registered, ratio 2.193, and shifted +2 mm, ratio 1.693.
Before concluding anything about the criterion, the controller was pushed to pass it,
which is what produced the damping sweep above. It cannot be passed that way. What the
data show instead is that the ratio is not a measure of station-keeping:

1. **It fails the better controller and passes a worse one.** An earlier build without the
   settle window gave 0.561 to 0.657 mm, ratio 1.171, **passing**. The current build gives
   0.357 to 0.783 mm, ratio 2.193, **failing** -- while being better at 3 s, better at
   12 s and better at every pose tested. Dividing by a smaller numerator is not a defect
   in the body.
2. **It passes a case that is leaking badly.** At heading -0.6 the ratio is 1.100, a
   comfortable pass, while displacement at 12 s is 3.163 mm, a 12 s over 3 s ratio of
   14.0. The six-second window is simply too short to see that leak.
3. **It passes a diverged controller.** At damping 0.03 the body has travelled 30.8 mm,
   twelve body lengths, and rotated 2.69 rad. The ratio is 0.934. **B3 passes.**

A criterion that a 30 mm runaway satisfies is not testing that drift is bounded. This is
the same defect class the project has repaired three times, a criterion satisfiable by a
degenerate outcome, and it was found the same way: by registering the criterion first and
then measuring against it.

## What is not done here, deliberately

**B3 is not restated, and no replacement is adopted.** Restating a criterion after it
fails, in the direction that makes it pass, is the move ADR-2026-006, ADR-2026-009 and the
widened-sweep v2 contract each had to repair, and the v4 contract itself was the third
such correction. That the case for changing it is strong this time does not make it a
decision to take while writing up the run that failed it. The analytically correct
statistic, an absolute bound on displacement at a long horizon, which none of the three
degenerate cases above would satisfy, is preregistered in
`configs/experiments/track-a-acceptance-v5-criteria.json` and marked **not adopted**.

**The 30-run acceptance matrix was not executed.** It would consume hours of GPU time to
reproduce a known B3 failure. B1 and B4 remain unmeasured. The paired control B1 requires
is implemented -- `--suppress-groom-replay` holds the grooming pose while leaving the
adhesion pattern, bout window, seed and food position identical -- but not yet run.

**Track A remains not an accepted milestone.** B2 passes, B3 fails as written, B1 and B4
are unmeasured, and the rendered-timing amendment is separately unresolved. The renderer
has however now been cleared as its cause: a rendered and a headless body driven with an
identical command sequence stay bit-identical in `qpos` for the whole run, maximum
absolute difference exactly zero, so the 1.44 s transition divergence originates elsewhere
in the brain-body loop and not in the renderer.


---

# Validation on unseen poses: B2 generalises, B3-v5 does not

Status: **evaluated once, and it fails.** Track A remains not an accepted milestone.

Artifact: `evidence/male-cns-v1.0/track-a-station-keeping-validation-v1.json`
Frozen commit `4c4a53f`, clean worktree, evidence-grade. 12 poses, 0 rejected by the
settled-outside-dust guard.

## Why this run exists

Every one of the seven poses in the table above also chose MOTOR-04's gains, its control
channel and its offset limit. Those numbers are training performance and cannot support a
claim about a pose the controller has not seen. The v5 criteria contract was adopted
prospectively, the seven poses were registered as development, twelve validation poses
were drawn from a seeded rule, the controller was frozen at `4c4a53f`, and the validation
set was evaluated once.

The acceptance threshold was registered before the run: **10 of 12**, which is the same 80
percent the v3 matrix already requires as 8 successes of 10 seeds per position. It was
declared informed rather than blind, and set at a level the development set fails — 5 of 7
is 71 percent. The contract also recorded the expected outcome before the run: *"the
expected validation pass count is about 8 or 9 of 12, which would fail the threshold."*

## The result

```
 pose   heading    y_mm |      3s      6s     12s |  ratio | B2 B3v5
  v01   -3.0990  +1.217 |   0.580   1.840   1.398 |  3.173 | ok ok
  v02   +3.0246  +0.836 |   0.554   1.572   1.667 |  2.837 | ok ok
  v03   -3.0765  -0.534 |   0.669   1.273   2.308 |  1.904 | ok ok
  v04   -0.1664  +1.207 |   0.088   1.393   3.634 | 15.812 | ok NO
  v05   -0.7219  -0.189 |   0.309   0.837   1.511 |  2.709 | ok ok
  v06   +0.3136  +0.523 |   0.790   2.040   3.284 |  2.582 | ok NO
  v07   +2.4915  -0.877 |   0.506   2.376   3.951 |  4.692 | ok NO
  v08   -2.9403  -0.760 |   0.647   0.831   2.601 |  1.285 | ok NO
  v09   -0.3820  +0.965 |   0.175   0.649   1.517 |  3.701 | ok ok
  v10   -0.9210  -1.331 |   0.531   0.318   1.335 |  0.599 | ok ok
  v11   +1.5906  +0.977 |   0.464   1.276   1.602 |  2.749 | ok ok
  v12   -2.5797  -1.413 |   0.957   0.821   0.943 |  0.858 | ok ok
```

| criterion | passes | required | verdict |
|---|---|---|---|
| **B2**, displacement at 3 s within 2.5 mm | **12 of 12** | 10 | **passes** |
| **B3-v5**, displacement at 12 s within 2.5 mm | **8 of 12** | 10 | **fails** |

**The predicted count was 8 or 9 and the observed count was 8.**

## What the numbers say, and what they do not

**B2 generalises, comfortably.** Worst 3-second displacement across twelve unseen poses is
0.957 mm, against a 2.5 mm limit and against 2.835 mm uncontrolled at the worst
development pose. On the criterion that fails at 4 of 7 development poses without the
controller, the controller passes at 12 of 12 poses it never saw.

**B3-v5 does not, and this is a capability limit rather than an overfitting artifact.**
Development gives 5 of 7, which is 71 percent; validation gives 8 of 12, which is 67
percent. Those are the same number within the resolution of twelve samples. If the
controller had been overfitted to the development poses the validation rate would have
collapsed, and it did not. The controller is simply not good enough at the twelve-second
horizon at roughly a third of standing poses, and it was not good enough on development
either.

**The four failures are all late-time leaks.** v04 is the clearest: 0.088 mm at 3 s, the
tightest hold in the whole set, then 3.634 mm at 12 s. The diagnosis recorded above
applies unchanged — the common-mode offset saturates at the edge of its monotone branch
and the plant's restoring velocity there caps near 0.2 mm/s, which is less than the drift
force at some poses.

**The retired ratio disagrees with the adopted criterion on half the set.** It would have
passed only 3 of 12. It passes v08 at 1.285 while v08 has drifted 2.601 mm, and it passes
v10 and v12 while failing v01, v02, v05, v09 and v11, all of which end under 1.7 mm. That
is the fourth independent demonstration that the ratio does not measure bounded drift, and
it is why the number is now reported as a diagnostic rather than scored.

## What must not happen next

**These twelve poses are now spent.** The contract's terms are explicit: tuning against
them would make them development data, so any further work on MOTOR-04 requires a new
validation set drawn from a new registered seed, and this failed validation stays on the
record either way.

The improvement attempt that preceded the freeze is also on the record and it failed. A
second fore-aft channel on coxa roll at weight −1.0 cut the worst development displacement
from 3.163 to 1.710 mm on the three poses it was swept over, and those three had been
selected from the failing set: across all seven it was worse, at 3.893 mm and 3 of 7
passing. The channel ships implemented and disabled at weight 0.0.

## Where Track A stands

| | status |
|---|---|
| B1, grooming replay differential | **unmeasured**; the paired control is implemented as `--suppress-groom-replay` and not yet run |
| B2, standing at the bout duration | **passes**, 12 of 12 unseen poses |
| B3-v5, standing at four bout durations | **fails**, 8 of 12 against 10 required |
| B4, pre-groom seek minimum | **unmeasured** |
| renderer timing amendment | **fails**; the renderer itself is cleared as the cause |
| the nine controls | not re-run |

**Track A is not an accepted milestone.** The 30-run matrix was not executed, as
instructed, and executing it now would be premature: B3-v5 fails on poses the fly reaches
by standing still, and the matrix would spend hours confirming it against a criterion
already known to fail.
