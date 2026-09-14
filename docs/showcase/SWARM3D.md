# The embodied 3D swarm: how to reproduce it, and what it does and does not claim

This is the operator handoff for `swarm3d-showcase`. It is the demonstration video the
project publishes; ADR-2026-023 records why it exists and what changed.

## What is on screen

Twelve *Drosophila* bodies in one MuJoCo scene with food spheres and pillars between them.
Each fly runs its own copy of the released MaleCNS connectome's `Traced` universe -- 165,122
of the 166,700 annotated bodies, and all 25,563,197 edges between them, executed every
coupling interval -- over one shared connectivity allocation on one GPU. Each fly sees the
arena through DEMO-01's frozen retinotopic lamina encoder, steers on nothing but two
descending population rates, and walks on an engineered pattern generator. The bodies share
one solver step, so the objects stop them through the physics. They do **not** collide with each other: no fly-fly contact pair exists and every
fly geom carries `contype 0`, so two bodies pass through one another. The flies are coupled
through vision alone.

The vision is an analytic scene oracle, not an optical one. Each encoder is handed the exact
position and radius of every visible object -- food, pillars, and the other flies as 0.55 mm
spheres -- and computes bearing and angular size directly. No pixels, no rays, no occlusion,
no colour, no elevation, no optic flow.

The video carries four panel layouts:

* **stage** -- the arena beside one fly's brain, with that fly's descending readout and a
  raster of every fly's forward drive underneath;
* **grid** -- twelve brains at once, which is the only shot that can show that these are
  twelve independent neural states rather than one simulation drawn twelve times;
* **compare** -- the exact run beside the stimulus-absent control at the same instant, the
  same seed and the same bodies;
* **cards** -- an opening card naming every scaffold before anything is shown, and a
  closing card carrying the measured outcome, every omission, and the provenance line.

## Reproducing it

Inside the pinned production environment, with `FLYSIM_DATA_ROOT` set to the dataset root.

Record. Measured at about 33 minutes per variant for the 30 simulated seconds of the shipped
recording, on one RTX 3060, using about 4.2 GB of device memory:

```text
PYTHONPATH=src python scripts/run_swarm3d_showcase.py \
    --duration-s 30 \
    --variant exact --variant stimulus-absent --progress
```

Look at a cut before committing to a render. The contact sheet runs the identical
composition and writes PNGs, so a shot list can be judged in a minute:

```text
PYTHONPATH=src python scripts/render_swarm3d_showcase.py \
    --run RUN_DIR/exact --out OUT.mp4 --stills 5,26,37,63,83
```

Render:

```text
PYTHONPATH=src python scripts/render_swarm3d_showcase.py \
    --run RUN_DIR/exact --control RUN_DIR/stimulus-absent \
    --out artifacts/showcase/swarm3d-v1/swarm3d-showcase.mp4 --progress
```

The renderer chooses its own GL backend (`glfw` here, 1.7x faster than `osmesa`) and the
manifest records which one actually rasterised and whether it was hardware accelerated.
The still times above are shot boundaries of the shipped cut.

Rendering reads only finished artifacts. `SwarmWorld.render_replay_frame` refuses a world
that has ever been stepped, so the replay path cannot advance a simulation even by
accident, and the manifest records `rendering_advanced_simulator_state: false` as a fact
rather than an assurance.

## What ships, and what stays on the recording machine

| file | in git | what it is |
|---|---|---|
| `artifacts/showcase/swarm3d-v1/swarm3d-showcase-web.mp4` | yes, 19 MB | the published cut: 1920x1080, 30 fps, 1:38, H.264 CRF 26 |
| `artifacts/showcase/swarm3d-v1/swarm3d-showcase.mp4` | no, 41.5 MB | the renderer's own output, re-encoded to produce the file above and otherwise identical frame for frame. Re-rendered on 2026-09-14 after the audit, from the same recording, to correct one caption and the GL provenance field |
| `render-manifest.json`, `run-exact-summary.json`, `run-stimulus-absent-summary.json`, `SHA256SUMS` | yes | the provenance: every camera choice, the run digests, and a checksum for each file including the master |
| `preview/*.png` | no, 9.4 MB | one full-resolution still at each shot boundary |
| `docs/media/*.gif` | yes, 7.3 MB | the four loops in the README, cut from the same video |
| the run itself | no | whole-scene `qpos` per coupling interval plus per-fly spike counts, under `$FLYSIM_DATA_ROOT/runs/` |

`SHA256SUMS` covers the master as well as the published cut, so the master can be verified
against this repository wherever it is archived. Re-encoding is the only difference between
them: no frame, caption or camera is regenerated.

**One provenance repair.** The run summary records `code_commit: a8d86941c150f8897b53ef1e866164e359f315cc`,
and that object no longer exists: the 2026-09-14 authorship rewrite changed every commit
identifier in the repository. Its successor is
[`398e05dd46deb70d872f9b6967bd69ca6d4bc23e`](https://github.com/Ibtisam-Mohammad/Fly.exe/commit/398e05dd46deb70d872f9b6967bd69ca6d4bc23e)
-- same subject, same date, same position as the parent of the commit that landed this
showcase. The rewrite changed author and committer emails only and left the root tree hash
byte-identical, so the recorded content is unchanged; only the name for it moved. The run was
also recorded from a dirty worktree, which `worktree_dirty: true` in the summary has always
said, so the recording is presentation-grade and not evidence-grade and cannot be reproduced
byte-for-byte from a commit alone.

## The boundary

**No validation tier.** There is no preregistered biological hypothesis for a swarm and no
acceptance contract scoring one. The run summary and the render manifest both carry
`validation_tier_awarded: null` and `evidence_grade: false`.

**No social behaviour.** Flies aggregate because a nearby fly is a large object in the
visual field and the network approaches large objects. Each fly enters the others' encoders
as a sphere of 0.55 mm radius, which models no part of how a fly looks to a fly. This is
registered as `SWARM-01`.

**No foraging and no feeding.** Food is a coloured sphere with a radius and a contact pair.
The encoder has no colour channel and cannot tell food from a pillar; what separates them
is angular size, so the largest thing in view wins. Nothing ingests anything, no proboscis
extends and no taste channel exists in this run.

**The walking is engineered.** The gait comes from FlyGym's published `HybridTurningController`
driven by two normalised drives. No part of the simulated ventral nerve cord contributes to
leg movement.

**The retina-to-lamina synapse is not executed.** All 66,533 photoreceptor output edges are
zeroed by the frozen unresolved-sign policy, because fly photoreceptors are histaminergic
and histamine is absent from the transmitter model. The loop enters one synapse downstream,
exactly as DEMO-01 declares.

**The flies are not individuals.** Twelve parameterised copies of one specimen. They differ
in where they start, what they see from there, and their independent membrane-noise stream.

**24,122 simulated neurons are never drawn.** They carry no released soma position. They are
executed and recorded like every other neuron; the brain panels show the 141,000 that can be
placed, and the footer says so on every frame.

## What the recording measured

Twelve flies scattered uniformly over a 30 mm disc and aimed at random under seed 11, 30.0
simulated seconds, 2,000 coupling intervals of 15 ms, against an identical-seed
stimulus-absent control:

| | exact | stimulus-absent |
| --- | --- | --- |
| flies that entered the locomoting state | 12 / 12 | 0 / 12 |
| flies that ended within 1 mm of an object's surface | 12 / 12 | 0 / 12 |
| neurons spiking per fly per coupling interval | 9,337 | 164 |
| straight-line displacement | 5.0 to 25.6 mm | 3.0 to 7.3 mm |
| ended nearer a food object | 12 / 12, median +11.48 mm | 8 / 12, median +2.25 mm |
| nearest object at the end | 11 at food, 1 at a pillar | 3 at food, 9 at a pillar |

Eleven of twelve ended against a food sphere, final gaps -0.21 to +0.37 mm; the twelfth
ended against a pillar at 0.55 mm. They were stopped by the object rather than deciding to
stop: the decoder has no transition out of LOCOMOTING, so a blocked fly is still being
commanded forward, and the gap is a two-dimensional thorax-centre distance minus the object
radius, not MuJoCo contact telemetry. Every fly had to turn first, with
starting bearings to its target from -104 to +90 degrees.

**Read the last two rows carefully.** Distance closed to food is not the discriminator: a
body commanded to stand drifts forward along its own axis, which Track A measured and
`docs/evidence/TRACK_A_STATION_KEEPING.md` records, and the heading is bounded so that food
lies inside the encoder's mapped visual field, so the control leans the same way. What
separates the runs is whether a fly walked at all and whether it arrived at anything. No
threshold on the 1 mm contact measure was preregistered and none is scored; it describes
these two recordings.

## Three properties of the frozen route this showcase measured

Two arenas were built and discarded before this one. Each failure is a measurement.

**Salience is angular, so near and thin beats far and fat.** On a 26 mm ring with the pillars
between the flies and the food, a 1.3 mm pillar at 8.6 mm subtends 8.72 degrees against a
2.2 mm food sphere at 20.4 mm at 6.19. Nine of twelve flies locked onto a pillar at the first
interval and never switched, and at the last interval every fly still carried forward drive
0.31 to 0.43. The frozen operating point has `adaptation_increment_mv: 0.0` and the loop has
no avoidance term, so walking into the largest object and pushing is a stable fixed point.

**A directional start geometry can pass the null control.** With every fly facing inward, the
stimulus-absent control ended 12 of 12 nearer a food object at +3.99 mm against the exact
run's +7.19 mm -- a null control that looked like a result, purely because standing drift
runs along the body axis.

**The route has a blind zone where the declared map ends.** With headings from the full
circle, five of twelve flies had their target beyond the retina map's declared -10 to +160
degree azimuth span. Measured on one: descending readout 0.000 to 0.03 Hz throughout and a
yaw command of -0.001, so no steering signal at all; and because the drive was tiny rather
than exactly zero, the fly did not fall into the standing controller either and walked in a
straight line out of the arena. Every fly whose target started inside 105 degrees arrived;
five of seven past 116 degrees did not. The scenario now rejects a heading that leaves no
food inside the mapped field. That is a domain condition, declared in the scenario file, not
a convenience.

## What is checked rather than asserted

| Property | How | Result |
| --- | --- | --- |
| The swarm's per-fly actuation is DEMO-01's | one fly through `SwarmWorld` and through `Demo01VisualBody` under an identical 170-interval command sequence | max abs difference **0.0** across all 133 `qpos` components |
| The multi-object encoder is DEMO-01's encoder | same populations, same parameters, one cue, five geometries | max abs difference **1.1e-13 Hz** on rates spanning 1 to 400 Hz |
| Rendering cannot advance a run | `render_replay_frame` on a stepped world | raises `CausalityError` |
| The drawn arena is the run's arena | every fly pose and object geometry checked against the recording before the first frame | raises `ConfigurationError` on any drift |
| Objects are obstacles, not decorations | explicit contact pairs counted in the compiled model | reported in `describe()["model"]` |

`tests/test_swarm3d.py`, with the physics checks under `-m slow`.

## Two render-time choices, both declared

**The ground plane is drawn wider than the scenario declares.** A MuJoCo plane geom is a
half-space: infinite for collision, with `size` read by the visualiser alone. The replay
draws it as a true infinite plane so the horizon fades into haze instead of ending at a
visible edge. No contact, no recorded state and no number changes, and the manifest records
the choice.

**Brightness is a fixed map, never per run.** A neuron's brightness is its recorded spike
count summed over the preceding intervals with a declared per-interval decay, then
compressed logarithmically against a constant reference. It is not membrane voltage and it
is never normalised per run, so panels stay comparable frame to frame and run to run.
