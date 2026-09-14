# ADR-2026-021: Interactive multi-fly showcase boundary

Status: accepted 2026-09-13  
Decision owner: project owner, by the explicit request to implement the multi-fly steps  
Assumption set: `foundation-v0.11` to `foundation-v0.12`

## Decision

The project will expose a live shared arena in which a user may place or remove food,
visual targets, dust and obstacles. User actions mutate the world only. They cannot write
neural state, neural output, actuator commands or body pose.

The first causal route is the existing DEMO-01 route:

```text
world target geometry
-> retinotopic lamina encoder
-> complete MaleCNS runtime graph
-> declared bilateral descending readout
-> causal engineering decoder
-> body
```

The decoder receives only neural rates. It is not passed target coordinates, distance,
bearing, body pose or the browser event. A command computed from activity over one
coupling interval becomes active only in the next interval.

Several exact-graph agents use PyGeNN batch state over one shared sparse-connectivity
allocation. Each batch has independent neuron, spike, delay and input state. This is a
performance representation, not a biological population: all agents reuse the anatomy of
one MaleCNS donor. A shuffled-connectome comparison needs a second graph allocation and is
opt-in because it may not fit alongside the exact cohort on the development GPU.

The initial shared body is a kinematic collision disc. It provides deterministic arena
bounds, obstacle blocking, pair contact and food depletion. It is an `E` web-demonstration
scaffold and does not replace the FlyGym body, the complete VNC-to-motor path, or any
scientific validation gate. Controller-only and passive agents are always labelled.

The CPU fallback contains no neural engine and must display
`controller-preview-no-cns`. The application must display biological time even when it
runs slower than wall time.

## Consequences

- Multiple flies can share stimuli and contact geometry without duplicating immutable
  exact connectivity for every full-CNS state.
- One exact and one sensory-ablated fly form the default causal comparison; a
  controller-only and a passive body make the engineering baselines visible.
- A browser session can never be used as scientific evidence. It awards no tier.
- Courtship, aggression, pheromone communication, social learning, personality and
  cross-animal generalisation claims remain prohibited until separately sourced,
  preregistered and validated.
- The web transport is optional. Scientific execution remains local and has no cloud
  dependency.

## Required checks

- Target placement changes only the world revision.
- Commands exposed by the coordinator contain no target coordinates.
- The first interval uses an explicit zero command.
- Collision and food depletion are deterministic and bounded.
- Food depletes only under physical contact plus a proboscis command.
- Batched engines expose one connectivity allocation and separate batch-labelled output.
- Two- and four-agent memory and throughput runs are recorded before claiming local
  interactive capacity.

## Implementation result

Completed in the 2026-09-13 working tree. The final local engineering benchmark ran each cohort
for 2.01 biological seconds. Both two-state and four-state batches completed with one connectivity
allocation, and all six measured states reduced their distance to the calibrated target after the
causal quiescent period. Throughput was 0.167 biological seconds per wall second for two states and
0.080 for four. This supports slow live interaction, not real-time execution.

The benchmark was deliberately marked `evidence_grade: false` because the repository already had
uncommitted work. Its artifact is
`/srv/flybrain-data/evidence/multifly/multifly-capacity-working-tree.json`, SHA-256
`8e64e3cecc00df9d9cec32e23208fa1619eb357edbd52a077462b12fc2b3d260`. No validation tier changed.
