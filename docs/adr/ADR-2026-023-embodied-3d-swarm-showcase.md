# ADR-2026-023: The embodied 3D swarm showcase

Date: 2026-09-13, amended 2026-09-14 with what two discarded arenas measured
Status: Accepted
Assumption set: `foundation-v0.12` to `foundation-v0.13` (adds `SWARM-01`)
Supersedes as the public demonstration: nothing. ADR-2026-022's scientific swarm video and
its artifacts are left exactly as recorded.

## The problem this fixes

`flysim.multifly` puts every agent on a `SharedKinematicArena`: a disc integrated forward
from a forward speed and a yaw rate. That arena was built to answer a capacity question --
can one GPU hold N independent 165,122-neuron states over one connectivity allocation -- and
it answers it honestly. The neural half of that stack is real: the full released graph, all
25,563,197 edges, executed per fly per interval on the GPU.

The embodied half did not exist. There were no legs, no ground, no contact, no
three-dimensional scene, and consequently the videos rendered from it were diagrams of
discs with fly meshes drawn on top. ADR-2026-022 was explicit that the mesh was a labelled
proxy, which was the right disclosure and the wrong artifact: a labelled proxy is still a
proxy, and a project that has a working NeuroMechFly body, a working closed visual loop and
a working batched full-graph runtime should not be publishing a picture of a disc.

A second problem sat beside it. The prior swarm recording had no control arm at all, so
"eight of eight moved closer to the target" had no floor to beat. A number with no floor is
not a result.

## Decision

Build the embodied counterpart, from the parts that already exist and are already checked.

**One MuJoCo scene holding every fly.** `flysim.swarm3d.SwarmWorld` attaches N full
NeuroMechFly bodies to one `FlatGroundWorld` and steps them together, so the objects stop
them through the solver rather than through a rule. They do not collide with each other; see
the audit section at the end of this document. Measured at
twelve flies: `nq` 1596, 2.07 ms per 500 us physics step at eight, and the whole scene is
one compiled model.

**Objects are real.** Food spheres and obstacle pillars are geoms in the compiled model with
explicit contact pairs against the same body segments the ground touches. FlyGym gives both
the ground plane and every fly geom `contype` 0 and relies entirely on explicit pairs, so
without those pairs a fly walks through a pillar. They are added.

**The per-fly actuation is DEMO-01's, and that is checked rather than asserted.**
`Demo01VisualBody` owns a world of its own and cannot hold twelve, so `SwarmWorld`
reimplements the per-fly path: the published `HybridTurningController` on two normalised
descending drives, Track A's standing controller when both drives are zero, leg adhesion at
a fixed gain, and the same settle window. A fork that drifted would mean the swarm's flies
are not the fly the DEMO-01 evidence describes, so `tests/test_swarm3d.py` walks one fly
through both under an identical command sequence and requires the full generalised position
vector to agree. Measured over 170 coupling intervals including turns: maximum absolute
difference **0.0** on every one of 133 `qpos` components.

**The encoder is extended, not replaced.** DEMO-01's `RetinotopicVisualEncoder` takes one
cue. `flysim.swarm3d_vision.MultiObjectLaminaEncoder` composes over many by giving each
lamina cell the strongest drive reaching it from any visible object. With one object the
maximum is the single term, so it reduces to the frozen encoder exactly; the test requires
agreement to 1e-9 Hz on rates spanning 1 to 400 Hz and measures 1.1e-13 at worst. The frozen
module is not edited.

**The flies are visible to each other.** Each fly enters the others' encoders as a sphere of
0.55 mm radius, about the half-width of a NeuroMechFly thorax. This is what makes the swarm
a swarm rather than twelve independent runs sharing a floor, and it is a scaffold: a fly is
not a sphere and nothing here models how a fly looks to a fly.

**Rendering is offline and structurally cannot touch the run.** The run records the whole
scene's `qpos` once per coupling interval and no frames at all. `SwarmReplay` rebuilds the
identical world and writes recorded states into it, and `render_replay_frame` refuses a
world that has ever been stepped. Every camera move is therefore a pure function of the
recording and a clock, which is what lets the shot list be chosen after seeing what the
flies did -- the only honest order to choose it in.

**There is a control arm, and it is in the video.** `stimulus-absent` runs the identical
seed, the identical graph, the identical bodies and the identical decoders with the encoder
held at its baseline. It appears as a split-screen shot, so a viewer sees the floor rather
than being told about it.

## What is claimed, and what is not

Claimed: the machinery runs. Twelve embodied flies, each executing the whole released male
CNS connectome, each steering on nothing but two descending population rates, in one three
dimensional scene with objects they can see and collide with, recorded completely enough to
re-render from any camera.

Not claimed, and stated on the frames rather than in a footnote:

* **No validation tier.** There is no preregistered biological hypothesis for a swarm and no
  acceptance contract scoring one, so this run demonstrates machinery and validates no
  biology. `validation_tier_awarded` is `null` in both the run summary and the render
  manifest.
* **No social behaviour.** Flies aggregate because a nearby fly is a large object in the
  visual field and the network approaches large objects. That is a consequence of
  `SWARM-01`, not a model of anything a fly does.
* **No foraging.** Food is a coloured sphere with a radius. The encoder has no colour
  channel and cannot tell food from a pillar; what separates them is angular size. No
  ingestion, no proboscis extension and no taste channel exists in this run.
* **The walking is engineered.** The gait comes from a published pattern generator. No part
  of the simulated ventral nerve cord contributes to leg movement.
* **The retina-to-lamina synapse is not executed.** All 66,533 photoreceptor output edges
  are zeroed by the frozen unresolved-sign policy, so the loop enters one synapse
  downstream, exactly as DEMO-01 declares.
* **The flies are not individuals.** Twelve parameterised copies of one specimen, differing
  in where they start, what they see from there, and their independent membrane-noise
  stream.

## Why the composition rule is a maximum

A real lamina cell integrates photon flux over its receptive field, so two objects landing
on one column would sum. The maximum is used instead because summing drives that are each
already normalised to [0, 1] makes a cluster of small objects brighter than a large one at
the same distance, which inverts the looming signal the whole route is built on. The choice
is P/E, it is registered in `SWARM-01`, and it is declared on screen.

## Consequences

* `configs/scenarios/swarm3d-showcase.json` carries every station-keeping constant and the
  whole decoder verbatim from `demo01-visual-approach.json`, and a test fails if they ever
  diverge. Nothing about a wider arena changes what holds a standing body still.
* The operating point is read from the frozen artifact of the registered DEMO-01 visual
  search. The showcase cannot invent network parameters.
* The GeNN build key covers the parameters, the wiring digest, the seed **and** the batch
  size, because GeNN bakes all four into the generated code. Without the batch term a
  one-fly build would be silently loaded for a twelve-fly run.
* Cost, measured: twelve flies at 0.015 x real time, so 30 s of simulated behaviour is about
  33 minutes per variant on one RTX 3060, at 4.2 GB of device memory. The wall clock is not
  the GPU being slow: 30 s of biology at the registered 100 us neural step is 300,000
  timesteps over 165,122 x 12 neuron states, which is 594 billion state updates. Real time
  would need about 1.2 TB/s of memory bandwidth for the neuron state alone against the
  card's 360 GB/s, so a perfect implementation is still roughly 3x short at twelve flies.
* The prior swarm artifacts (`swarm-cns-cinematic-v1`, ADR-2026-021 and ADR-2026-022) are
  not withdrawn or rewritten. They recorded what they recorded.


## What two discarded arenas measured

The arena in `configs/scenarios/swarm3d-showcase.json` is the third. The first two were not
mistakes in the code; each exposed a property of the frozen DEMO-01 loop that no previous
experiment had tested, because DEMO-01 ran one fly against one cue at a 40 degree bearing.

**v1, twelve flies on a 26 mm ring facing inward.** Salience is angular, so a 1.3 mm pillar
at 8.6 mm (8.72 degrees) beat a 2.2 mm food sphere at 20.4 mm (6.19 degrees). Nine of twelve
locked onto a pillar at the first coupling interval and never switched; at the last interval
every fly still carried forward drive 0.31 to 0.43 with the object filling 36 to 57 degrees.
With `adaptation_increment_mv: 0.0` and no avoidance term anywhere, walking into the largest
object and pushing is a stable fixed point of this loop. The same arena also made the null
control look successful: every fly faced inward, a standing body drifts forward along its own
axis, and the stimulus-absent control ended 12 of 12 nearer a food object at +3.99 mm.

**v2, positions and headings both uniform at random.** Five of twelve flies had their target
beyond the retina map's declared -10 to +160 degree azimuth span. Measured: descending
readout 0.000 to 0.03 Hz throughout, yaw command -0.001. Because that drive is tiny rather
than exactly zero, the body never enters the standing controller either, so the fly walks in
a straight line out of the arena. Every fly whose target started inside 105 degrees arrived;
five of seven past 116 degrees did not.

**v3 keeps uniform positions and bounds the heading** so that some food lies inside the
mapped field. That is a domain condition rather than a convenience -- the map is declared
over -10 to +160 degrees and nothing outside it has a defined value -- and it is written into
the scenario with the measurement behind it. It costs something and the video says so: the
bound leaves a weak lean that standing drift follows, so the control still ends 8 of 12
slightly nearer food at +2.25 mm against the exact run's +11.48 mm. The measure that is not
confounded, and the one the comparison panel leads with, is whether a fly ended against an
object: 12 of 12 against 0 of 12.

## Rendering is software here, and the manifest says so

Every GL backend available in this WSL distro reports `GL_RENDERER: llvmpipe`. `/dev/dri`
does not exist, `/sys/class/drm` holds only `version`, and `dmesg` carries
`misc dxg: dxgk: dxgkio_query_adapter_info: Ioctl failed: -2`, so Mesa's `d3d12_dri.so`
cannot reach the card even though it is installed. NVIDIA ships no Linux EGL or GLX driver
into WSL by design; graphics is meant to go through that gallium driver. CUDA takes a
separate path, which is why the 165,122-neuron network runs on the GPU at 4.2 GB while the
rasteriser cannot touch it. glfw is 1.7x faster than osmesa here, 282 against 487 ms a frame,
and is the default. The render manifest records `gl_renderer` and `hardware_accelerated` so
that a render on a machine where the GPU is reachable says so rather than looking the same.


## What a third-party audit found, 2026-09-14

An external review of the published repository raised seventeen findings. Every one was
checked against the code rather than against this document, and every one held. Three were
claims this ADR or its artifacts made and could not support.

**Flies do not collide with each other.** This ADR said "steps them together, so they collide
with each other and with the objects through the solver rather than through a rule". The
first half is false. FlyGym gives every fly geom `contype 0` and relies entirely on explicit
contact pairs; `SwarmWorld` writes fly-object pairs and never writes fly-fly pairs. Measured
on the compiled two-fly model: 220 explicit pairs, **zero** joining two flies; every fly geom
at `(contype, conaffinity) = (0, 0)`; two thorax free joints driven to the same point produce
48 contacts, **zero** of them fly-fly. The claim was asserted from the design and never
tested, which is the failure this project has a rule against. The swarm coupling that does
exist is visual: each fly enters the others' encoders as a sphere of one declared radius.
Implementing fly-fly contact is possible but would invalidate the published recording, so it
is registered as a gap rather than silently added.

**Locomotion onset is timer-determined.** The frozen decoder holds every fly in `QUIESCENT`
until `quiescent_us` = 1.5 s, then requires the drive to stay above `forward_threshold_hz`
= 0.6 Hz for `initiation_hold_us` = 150 ms. The registered operating point answers a cue at
2.435 Hz, so the threshold never binds and all twelve flies enter `LOCOMOTING` at exactly
1,665,000 us. The shot caption "What changed is descending activity, not a timer" was false
as written and has been replaced. The honest split: the timer sets *when*, and the stimulus
sets *whether* -- the stimulus-absent control never leaves the standing state.

**The renderer provenance field failed open.** `report_gl_backend` ran after the render, with
no current GL context, so `glGetString` returned `None`, the renderer string became
`"unknown"`, the substring test for `llvmpipe` found nothing in `"unknown"`, and the manifest
recorded `hardware_accelerated: true` for a render that software rasterisation drew every
frame of. The probe now opens a context of its own and records `null` when it cannot tell.

Four further findings were true and under-disclosed rather than false, and are now stated in
the README and the operator handoff: the visual encoder is an analytic scene oracle with no
pixels, rays or occlusion; "ended against an object" is a two-dimensional thorax-centre
proximity measure and the decoder has no stop transition, so a blocked fly is still being
commanded forward; the result rests on one seed and one arena; and the runtime graph is the
`Traced` induced subgraph, 165,122 of 166,700 annotated bodies, rather than every MaleCNS
record.

The remaining findings restated boundaries this project already documents: the gait is
engineered, `turn_sign` is a registered engineering choice whose mirror was measured, there
is no social behaviour or foraging, the cell dynamics are generic, no tier above V0 is
awarded, there is no aerodynamic flight, and green CI does not exercise the GPU or the body.

The controls the audit asked for and this recording does not have -- flies-invisible, a
swarm-specific readout ablation, a matched controller-only arm, an activity-matched shuffle,
a multi-seed matrix, and an equal-angular-size food-versus-pillar preference test -- are the
real scientific gap. The flies-invisible control is the one that decides whether the word
"swarm" means anything here, and until it is run, this remains twelve flies that can see each
other and cannot touch each other.
