# Eon-class MaleCNS showcase

Status: implementation complete; clean-commit GPU matrix pending  
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
