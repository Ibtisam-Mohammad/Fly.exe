# ADR-2026-020 — Withdraw v1 as the final showcase and preregister v2

Status: accepted

Date: 2026-09-13

Provenance: `E`

## Context

The v1 release is reproducible, but its frozen acceptance question was too weak. The hero's own
validation record reports 8.477 mm of net grooming displacement against a 2.5 mm limit, while the
showcase evaluator looked only at file validity and state transitions. Its navigation uses the
`eon-malecns-v0.2` raw bilateral odour-gradient steering term plus declared central relays rather
than DEMO-01's causal visual route. Its contamination and grooming ablations produce no transition
at all because the serial state machine cannot reach later states without grooming; they establish
sequence dependency, not independent behaviour causality. Command replay, a graph-free
controller-only baseline, three target positions and an exact-versus-ablation explanatory cut are
absent.

## Decision

Keep every v1 artifact and hash unchanged, but withdraw v1 as the final public showcase. The
software evaluator now fails closed when a run's recorded behavioural criteria contain a failed
grooming-displacement gate and identifies the two chain-coupled controls by class.

Preregister `eon-showcase-v2` before running new experiments. It is an edited presentation of
three independent runs rather than a new serial behaviour controller:

1. DEMO-01 visual-target approach, at three frozen held-out target positions, must pass A1--A4
   and finish within the cue's 2.5 mm radius. No world-coordinate, bearing, odour-gradient, DM1/DM4
   or direct DNg97 term may enter its decoder.
2. DEMO-02 grooming must pass G1--G6, including the unchanged 2.5 mm bout-displacement cap.
3. DEMO-02 feeding must use corrected MN9 and may run only after
   `demo02-feeding-operating-point-v1` selects an operating point on neural criteria without a body.

Each chapter requires readout ablation, stimulus absence, command replay and a graph-free fixed
controller baseline. The final MP4 must be 60--90 seconds, 1920 by 1080 at at least 30 fps, include
an exact-versus-ablation view, and state that the chapters were separately executed.

## Consequences

The archived v1 video remains useful as a visual integration preview but may not be described as
the corrected showcase. The v2 validator is implemented before any v2 outcome is opened and cannot
run or tune a simulation. v2 remains blocked until all three component contracts pass. V0
Structural remains the only tier; Stage 2 stays 0 of 3 and Track A remains unaccepted.
