# Eon-class MaleCNS showcase

Status: accepted as an engineering showcase on 2026-09-12

Scientific tier: unchanged at V0 Structural

Contract: `configs/experiments/eon-showcase-v1.json`

## Purpose

This is the public demonstration lane, not a new scientific stage. It packages the existing
full-graph Track A scenario as an Eon-class controller-mediated story:

```text
SEEK -> GROOM -> SEEK_RESUME -> FEED_INITIATION -> COMPLETE
```

The whole 165,122-neuron, 25,563,197-edge traced MaleCNS aggregate graph is built and stepped.
World quantities enter named numeric populations, selected neural readouts drive engineered
controllers, and the resulting body motion changes the next sensory sample.

The demonstration does not traverse the biological VNC-to-muscle hierarchy. It uses central
sensory bridges, direct forward-intent drive, an odor-gradient steering term, a published
grooming trajectory, and a joint-actuated feeding pose. Those bridges are the point at which
this release is comparable to Eon's controller-mediated integration rather than to Track B.

## Stable command

From the pinned WSL environment:

```bash
flysim showcase build --root /srv/flybrain-data
```

For a matrix-only run while developing the presentation:

```bash
flysim showcase build --root /srv/flybrain-data --no-render
```

Build the rich 1080p presentation after the matrix has been accepted:

```bash
flysim showcase cinematic --root /srv/flybrain-data
```

After recording, a visual-only revision can reuse the immutable trace, spike, and pose files:

```text
flysim showcase cinematic --root /srv/flybrain-data --source-directory PRESENTATION_DIR
```

The source and renderer commits are recorded independently, and both recording and rendering
refuse a dirty worktree.

This performs one clean-commit hero rerun while recording sparse full-graph spike counts and the
complete MuJoCo pose at each coupling boundary. Rendering happens afterward. The rerun must
reproduce the accepted hero transition signature exactly or the command refuses to render.

The runner is resumable only within one code commit. A run from a dirty tree, another commit,
another scenario, or an invalid artifact is never reused.

## Matrix and acceptance

The release runs exact seeds 1, 2 and 3 at the fixed food position. Seed 1 is the declared hero,
and at least two of the three exact runs must complete the full sequence. Four controls are
gating:

1. contamination input ablated: must not reach `GROOM`;
2. grooming readout ablated: must not reach `GROOM`;
3. sucrose input ablated: must not reach `FEED_INITIATION`;
4. MN9 readout ablated: must not reach `FEED_INITIATION`.

Zero-weight and degree-preserving shuffled-connectome runs are diagnostic. Neither gates a
topology claim, because exact and shuffled networks have not been matched for activity regime.

The evaluator refuses mixed commits, dirty runs, missing run validation, a graph with the wrong
size, thresholded edges, a claimed validation tier, missing exact seeds, or missing controls.

## Rendering

Simulation is always headless. The hero MP4 is generated afterward from its immutable trace, so
rendering cannot change transition times or body dynamics. The video names the graph, central
bridges, controller boundary and V0 tier, and it states that no VNC-to-muscle or ingestion claim
is made.

## Claim boundary

Allowed:

> A full-MaleCNS, controller-mediated, closed-loop engineering demonstration using declared
> central sensory bridges and body controllers.

Not allowed: digital twin, recovered source fly, autonomous connectome-generated behaviour,
validated physiology, complete motor hierarchy, ingestion, or a validation tier above the
already supported V0 Structural tier.

The command writes `acceptance.json`, `showcase-manifest.json`, the hero video and render
manifest, plus the per-condition run manifests and validation reports. A failed matrix is still
packaged and remains a useful reproducible negative; no threshold is changed after seeing it.

## Recorded result

The complete matrix ran from clean commit `efe5c0de0094cd81337c55deb036b08bc208320e`.
Seeds 1 and 2 completed the sequence; seed 3 reached `FEED_INITIATION` but did not reach
`COMPLETE`. This satisfies the frozen two-of-three rule. All four causal ablations blocked their
specified state. Zero-weight produced no transitions; shuffled connectivity reached grooming and
resumed seeking, and remains a non-gating diagnostic because activity was not matched.

The first 6.6-second schematic hero video is H.264, 960 by 544 pixels at 30 frames per second.
It exposed a presentation problem: the red food disk represented a 0.25 mm object while the
engine's sucrose signal used an invisible 1.0 mm thorax-proximity radius. The cinematic renderer
therefore shows both geometries and labels the larger one as an engineered trigger zone rather
than physical mouth contact.

The compact release files are tracked under `artifacts/showcase/eon-showcase-v1/` with a
`SHA256SUMS` file. The primary hashes are:

- acceptance: `ee0b515c9e3d8b7236a1d42c75af1c50fa254bb7a19c22949309e5053edec672`;
- package manifest: `dd02aba525240f0649a8217003e73f90ac507958048cd766c45f3a1f541ad4ec`;
- hero video: `7cc50aebf1382d3d8527e24e7d547e81263530658e3ef2d1ade5b201ae1b15a7`.

This acceptance is only for the engineering release contract. The project's scientific tier
remains V0 Structural, Stage 2 remains 0 of 3, and Track A's stricter displacement and throughput
gates remain failed.
