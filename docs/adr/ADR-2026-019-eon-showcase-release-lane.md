# ADR-2026-019 — A separate engineering release lane for the Eon-class showcase

Status: accepted  
Date: 2026-09-12  
Provenance: `E`

## Context

The repository contains several scientifically useful negative results and an older Track A
storyboard that already executes the complete traced MaleCNS aggregate graph with declared
central sensory bridges and ideal body controllers. The user wants a compact, visible
demonstration comparable in presentation scope to Eon's fly upload. Turning that request into a
new scientific claim would erase the most important result of the audits: the available neural,
sensory and neuromuscular evidence does not support such a claim.

DEMO-01 and DEMO-02 also have frozen contracts and different experimental questions. Combining
their internals into a new controller would make those earlier artifacts impossible to interpret.
The showcase therefore uses the existing `eon-malecns-v0.2` path without modifying its biological
meaning.

## Decision

Add `eon-showcase-v1` as a separate engineering release contract and command. It:

- runs exact seeds 1, 2 and 3 from one clean commit and requires at least two completions;
- requires the hero seed to complete grooming, resumed seeking and feeding initiation;
- runs contamination-input, grooming-readout, sucrose-input and MN9-readout ablations;
- records zero-weight and shuffled-connectome runs as diagnostics only, because they are not
  activity matched and cannot support topology specificity;
- accepts only the complete 165,122-neuron, 25,563,197-edge aggregate graph;
- renders only after simulation, so video production cannot change simulator timing;
- displays the central bridges, controller-mediated female-body prior, missing VNC-to-muscle
  pathway and feeding-initiation-only boundary in the video; and
- can report only `accepted_as_engineering_showcase`; it can never award a V0-to-V8 tier.

The feeding chapter deliberately uses the already registered GNG588/Fdg central-relay bridge and
MN9 rostrum readout. It does not claim the unresolved peripheral tarsal-taste route, pharyngeal
pumping, ingestion or metabolism. The showcase likewise keeps the existing kinematic grooming
replay instead of claiming autonomous grooming execution.

## Consequences

This lane can produce a coherent public video without weakening scientific gates. Passing it does
not accept Track A: the 2.5 mm grooming-displacement cap and 0.5 biological-seconds-per-wall-second
target remain failed. It does not change V0 Structural, Stage 2's 0-of-3 gate, or Stage 3's sealed
state.

The Git history was separately rewritten at the user's request to remove co-author trailers before
publication. That changed all historical commit identifiers. Existing artifact hashes are retained,
but narrative references to old commits are legacy provenance until mapped or reissued; the
showcase itself starts from the post-rewrite history and requires one current clean commit.

## Presentation addendum

The first compact renderer made the 1.0 mm thorax-proximity sucrose zone invisible and drew only a
0.25 mm food marker. The state transition was numerically correct under its contract, but the
video looked as though the fly had stopped short. A separate cinematic renderer now records
sparse full-graph spike counts and the complete MuJoCo pose during one clean-commit hero rerun,
requires its transition signature to match the accepted hero, and then renders a 1080p dashboard
offline. It shows the released soma cloud, actual replayed body pose, synchronized traces and both
food geometries. The larger geometry is labelled an engineered proximity zone, not contact.
