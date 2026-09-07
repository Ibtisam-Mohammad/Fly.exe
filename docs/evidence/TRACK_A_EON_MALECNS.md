# Track A full-graph Eon-like demonstration

Evidence date: 2026-09-07  
Milestone status: complete as an offline engineering prototype  
Validation tier awarded: none; project-wide highest tier remains V0 Structural

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
