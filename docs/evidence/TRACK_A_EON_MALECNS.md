# Track A full-graph Eon-like demonstration

Evidence date: 2026-09-07  
Revision date: 2026-09-08  
Milestone status: **acceptance evidence withdrawn**; the integration itself still runs  
Validation tier awarded: none; the project awards no tier while the V0 bundle is withdrawn

## Withdrawal notice, 2026-09-08

The v2 acceptance matrix and control bundle described below are withdrawn. The measurements are
real and the artifacts remain on disk, but four defects mean they cannot support the acceptance
claim they were used for. See [ADR-2026-006](../adr/ADR-2026-006-evidence-chain-repair.md).

1. **The evidence is not reproducible from its recorded commit.** All 30 primary runs, all eight
   control runs, the viewer run and the final smoke run record commit `aeb7c71` with
   `dirty=true`. `aeb7c71` is a documentation-only commit; the entire Track A implementation was
   uncommitted when the runs executed and only landed later in `013fd18`. The runs also carry a
   scenario hash that differs from the committed scenario.
2. **The food positions were not held out.** A first 30-run acceptance round exists at
   `/srv/flybrain-data/runs/track-a-acceptance` using the identical positions `(8,-1)`, `(8,0)`
   and `(8,1)`. Its `sucrose-input-ablation` control **failed**: with the sucrose input ablated
   the run still reached `FEED_INITIATION` and `COMPLETE`. The controller then gained a
   `feed_min_evoked_rate_hz` gate and the whole matrix was rerun as v2 at the same positions. The
   v2 documentation described those positions as preregistered and held out, and disclosed
   neither the discarded round nor the gate change.
3. **The behavioural narrative did not match the traces.** The settled thorax began inside the
   dust patch, so contamination accrued from the first physics step with a zero forward command,
   and `GROOM` fired at exactly 135 ms and `SEEK_RESUME` at exactly 3.135 s in all 30 runs. In
   every run the body then translated 5.2 to 7.8 mm, median 6.5 mm, **during** the grooming bout
   while the forward command was zero, which is most of the roughly 7 mm path to the food. Two
   runs were already inside the 1 mm food radius when grooming ended.
4. **One control could not fail.** The shuffled-connectome control was registered with no
   blocked transition, so its `passed` field was unconditionally true. The shuffled run in fact
   reproduced both `GROOM` and `SEEK_RESUME`.

The v3 matrix preregistered in `configs/experiments/track-a-acceptance.json` addresses all four:
three genuinely unused food positions, a clean-worktree requirement enforced by both scripts, a
dust patch that leaves checked clearance after settling, a grooming-displacement cap of one body
length, and a shuffled-connectome criterion that must both fail to complete and degrade its
grooming readout below half the exact-graph reference.

## v3 acceptance matrix, 2026-09-08

Preregistration: `configs/experiments/track-a-acceptance.json`, experiment
`track-a-eon-malecns-acceptance-v3`, SHA-256
`8335d3b10c15ea803d24cffd7aaa797b8c87dab034ccd7ed6dd624770dffc39f`.

- Primary matrix: `/srv/flybrain-data/runs/track-a-acceptance-v3/primary-progress.json`,
  SHA-256 `bb5674a4ab942e0c80ce3a03b1d96df9a3f8cb428c8850e899a9284afac5a492`.
- Controls: `/srv/flybrain-data/evidence/male-cns-v1.0/track-a-controls-v3.json`,
  SHA-256 `249353025c770080a5a96d347f5c3a8df6b30aef5ba300649b4a8faea740a0f5`.
- Viewer video: SHA-256
  `8a163ae920fca4f1ad96a4c6be1624083c68cf3ee59df75ea5d57f68423c97ca`.

Every one of the 30 primary runs and every control run records commit
`4a061ac7207a4f3b5abe4aa40ec58125de805493` with `dirty: false`. Zero runs came from an
uncommitted tree, and the acceptance script refuses to reuse a run recorded against any other
commit.

### Outcome: the matrix does not pass

| Gate | Result |
|---|---:|
| Held-out food positions | far-left `(7.5,-2)`, far-center `(9.5,0)`, far-right `(7.5,2)` mm, none previously used |
| Runs | 10 seeds at each of 3 positions, 30 total |
| Completed the required sequence | 29 of 30 |
| Pre-groom seek displacement, floor 0.5 mm | 30 of 30 pass; 0.741 to 1.379 mm, median 0.918 |
| Grooming displacement, cap 2.5 mm | **0 of 30 pass**; 5.166 to 7.532 mm, median 6.257 |
| Accepted conditions | **0 of 30** |
| `primary_matrix_passed` | **false** |
| Required controls | 9 of 9 pass |
| Throughput, steady state | 0.332 to 0.363, median 0.353 biological s per wall s |
| Throughput, cold start | 0.114 to 0.245 biological s per wall s |
| Interactive target 0.5 | not met |

`far-right:seed-2` reached `SEEK_RESUME` and then stalled 1.9 mm short of the source at
`(5.95, 0.98)` mm for the remainder of the 12-second run. That is a genuine navigation failure
under the odor-gradient controller and is recorded rather than excluded.

### What the geometry repair fixed

The v2 matrix entered `GROOM` at exactly 135,000 microseconds in all 30 runs, because the
settled thorax was already inside the dust patch. With the patch moved to leave a checked
0.71 mm clearance after settling, grooming now begins between 330,000 and 690,000 microseconds
across 12 distinct times, always after the fly has walked 0.74 mm or more into the patch. The
first two transitions are seed-dependent for the first time, so calling these runs stochastic
is now accurate.

### What the repair did not fix: grooming-phase body translation

The body still travels a median 6.26 mm during a 3-second grooming bout while the forward
command is zero, against a preregistered cap of one adult body length. Three isolation probes
locate the cause, and it is mostly not the trajectory replay:

| Condition, 3 s | Net body displacement |
|---|---:|
| Standing, no command at all | 2.161 mm |
| Grooming, trajectory replay suppressed | 4.917 mm |
| Grooming, registered 200 ms blend-in | 5.876 mm |
| Grooming, 1000 ms blend-in | 5.507 mm |

The FlyGym body drifts 2.16 mm in three seconds while merely standing, and switching to the
grooming adhesion pattern, which releases the two forelegs, roughly doubles that before the
published trajectory contributes anything. The replay itself adds about 1 mm. Holding the
settled joint configuration instead of the nominal default pose was tested and made standing
worse, at 4.63 mm, so it was not adopted. The registered `groom_blend_in_us` scaffold removes
the position-target discontinuity at bout onset but is measured not to reduce the drift; it is
recorded as such rather than presented as a fix.

No further physics tuning was attempted. Adjusting the body until the number clears a gate that
was set from body length is the failure mode this repair exists to prevent. The honest position
is that the Track A body cannot presently hold station during a grooming bout, and that this
was invisible while the demo had no displacement criterion.

### Controls

All nine required controls pass, and unlike v2 they can now fail.

| Control | Criterion | Result |
|---|---|---|
| contamination-input-ablation | `GROOM` blocked | pass, no transitions |
| groom-readout-ablation | `GROOM` blocked | pass, no transitions |
| sucrose-input-ablation | `FEED_INITIATION` blocked | pass, stops at `SEEK_RESUME` |
| mn9-readout-ablation | `FEED_INITIATION` blocked | pass, stops at `SEEK_RESUME` |
| zero-weight | `GROOM` blocked | pass, no transitions |
| shuffled-connectome | must not complete **and** peak grooming-DN readout at most half the exact-graph median | pass: 66.7 Hz against an allowance of 77.8 Hz, from an exact median peak of 155.6 Hz, and did not complete |
| controller-only | baseline artifact recorded | pass |
| neural-bypass | connectome unused | pass |
| headless-viewer-equivalence | identical transition signature | pass |

The shuffled-connectome margin is 14%, so this control was close to failing. That is the point:
in v2 it was registered with no blocked transition and its `passed` field was unconditionally
true.

Rendering perturbs the trajectory more than it did in v2. The viewer and headless runs still
produce identical transition identities and reasons, but the last two transitions now differ by
1.44 seconds rather than 30 milliseconds. The equivalence control tests the transition
signature, not timing, so it passes; the timing divergence is recorded here because it means a
rendered run is not a faithful timing replica of a headless one.

### Workspace copies

Copies for human inspection are under `artifacts/track-a-v3`: the rendered viewer run in
`final-run`, and the primary matrix, controls, reissued V0 bundle and scoped assumption
snapshot in `evidence`. The `final-run` directory can be passed straight back to
`flysim validate`, which reports `valid: true` with `behavioral_criteria_passed: false`, since
the artifacts are intact and the behavioural cap is breached. The withdrawn v2 copies remain
under `artifacts/track-a`.

### Standing

Track A is a working full-graph integration: 165,122 bodies and 25,563,197 edges execute in
direct PyGeNN, coupled to a FlyGym body, with causal event gates, falsifiable controls, and
reproducible run records from a committed tree. It is not an accepted milestone. Its own
preregistered behavioural criterion fails in every run, and its throughput remains below the
interactive target even after the cold-start cost is separated out.

## Superseded v2 record

Everything below this line describes the withdrawn v2 evidence and is kept for audit.

## Outcome

`flysim run eon-malecns` executes the complete 165,122-body, 25,563,197-edge
`status=Traced` MaleCNS aggregate graph in direct PyGeNN and couples it causally to a FlyGym
2.1/MuJoCo 3.9 body. The physical fly seeks an ethyl-acetate source, enters an antennal-grooming
bout after dust contamination, resumes seeking, reaches the source, and initiates rostrum and
haustellum extension.

The exact graph uses nine out-degree buckets and 81 disjoint sparse projections. This retains all
25,563,197 logical edges while reducing GeNN row padding from about 1.849 billion slots to
128,941,699 slots. Contact rows remain CPU-side and no weak-edge threshold is applied.

## Acceptance evidence

| Gate | Measured result |
|---|---:|
| Held-out food positions | left `(8,-1)`, centre `(8,0)`, right `(8,1)` mm |
| Preregistered stochastic runs | 10 seeds per position, 30 total |
| Required pass rate | at least 8 of 10 at each position |
| Observed pass rate | 10 of 10 at every position; 30 of 30 total |
| Required sequence | `GROOM -> SEEK_RESUME -> FEED_INITIATION -> COMPLETE` |
| Sensor/readout ablations | contamination, grooming readout, sucrose, and MN9 each block its transition |
| Structural controls | zero-weight blocks grooming; shuffled-connectome recorded and does not complete |
| Integration controls | controller-only and neural-bypass recorded |
| Headless/viewer agreement | identical transition identities and reasons; last two transitions differ by 30 ms |
| Throughput target | 0.5 biological seconds per wall second |
| Observed throughput | minimum 0.117; median 0.169 biological seconds per wall second |
| Performance classification | offline prototype; interactive target not passed |

Immutable/local evidence roots:

- Primary matrix: `/srv/flybrain-data/runs/track-a-acceptance-v2/primary-progress.json`,
  SHA-256 `6fb57a6fe536ed559360bb91c1b41554cbab0056d2aae22a1df17ae35caeaa57`.
- Controls: `/srv/flybrain-data/evidence/male-cns-v1.0/track-a-controls-v2.json`,
  SHA-256 `65250db0fc473b9011a3fd25e116752135419b2ec009b8a75478d9b03a352731`.
- Population resolution: `/srv/flybrain-data/derived/male-cns-v1.0/population-resolution.json`,
  SHA-256 `3b0c53a38230be21e2e23ec5268a7a6ea96e1e1e404e58e1e40db6b78b813eef`.
- Viewer video: `/srv/flybrain-data/runs/track-a-controls-v2/viewer/20260907T160202Z_eon-malecns-v0.2_seed-1/flygym.mp4`,
  SHA-256 `4e9eb28e859b1da3b66679aea068ba5c4d417242cbf024bf53cbdc48b454250b`.
- Finalized CLI smoke run: `/srv/flybrain-data/runs/track-a-final-smoke/20260907T162258Z_eon-malecns-v0.2_seed-1`,
  complete and valid with 488 trace records. Its run manifest includes the physical MP4 checksum
  `62c4debed031fdf734c221d416a1bfa44e1ee32b30704d286e0d9043011e818d`.

Workspace copies for human inspection are under `artifacts/track-a/final-run` and
`artifacts/track-a/evidence`. The complete final-run directory can be passed back to
`flysim validate` without changing paths or filenames.

## Biological boundary

This result is not autonomous connectome-generated behavior. It deliberately includes these
registered `P/E` or `E` bridges:

- DM1/DM4 projection-neuron injection bypasses olfactory receptors and antennal-lobe local
  processing; GNG588/Fdg injection bypasses peripheral sweet receptors and upstream gustatory
  layers.
- Injected central-entry populations use a 10x outgoing gain, and the Shiu transmitter-only LIF
  fallback uses a uniform one-step synaptic delay. These are circuit-execution scaffolds, not
  physiology.
- DNg97 receives an odor-gated 20-Hz forward-intent drive because the fallback graph did not
  recruit it autonomously. Turning combines DNa readouts with an explicit bilateral odor-gradient
  controller.
- Grooming is a position-controller replay of the published Ozdil et al. trajectory. Feeding is
  joint-actuated initiation only. Neither traverses a validated VNC-to-muscle implementation.
- The body is the published female FlyGym/NeuroMechFly prior with ideal joint actuators.

Consequently this milestone proves that the full MaleCNS graph, numeric populations, causal event
gates, physical body, published grooming motion, controls, rendering, and reproducible run records
work together. It does not earn V1-V8 evidence and it does not replace Stage 2 fitted dynamics or
Track B scientific walking.
