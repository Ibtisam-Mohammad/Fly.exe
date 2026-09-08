# ADR-2026-006: Evidence-chain repair after the 2026-09-08 audit

Status: accepted

```yaml
decision_id: ADR-2026-006
date: 2026-09-08
changes_assumptions: [NUM-01, BODY-01, MOTOR-03, DATA-01]
old_decision: >-
  V0 pinned the whole mutable assumption register; run manifests named the project tier as a
  literal; evidence runs were permitted from an uncommitted worktree; GeNN executed the
  registered synaptic delay one step late; registered interface delays were quantised
  silently; the decoder labelled normalized drives as mm/s and rad/s; the settled FlyGym body
  began inside the dust patch; the shuffled-connectome control had no falsifiable criterion;
  and the Track A held-out food positions had already been used by a discarded round.
new_decision: >-
  V0 pins an immutable, V0-scoped snapshot of the DATA-* foundation records and is gated on
  their content rather than on the project-wide assumption-set identifier. Any command that
  names a tier resolves it by validating a bundle. Evidence-grade runs and both Track A
  scripts refuse a dirty worktree and refuse to reuse a run from another commit. GeNN's
  inherent one-step delivery latency is compensated so the registered delay is realised
  exactly. Effective coupling-quantised interface delays are registered and asserted. The
  decoder's forward and yaw outputs are normalized descending drives. The dust patch is
  placed to leave a checked clearance after settling, grooming-phase displacement is measured
  and capped at one body length, and the shuffled-connectome control must both fail to
  complete and degrade its readout below half the exact-graph reference.
reason: >-
  An independent audit confirmed that the live V0 bundle no longer validated and could not be
  rebuilt, that every Track A acceptance artifact came from an uncommitted tree, and that the
  headline behavioural narrative was substantially a physics artefact of the settled spawn
  position and the grooming replay.
primary_sources:
  - https://male-cns.janelia.org/download/
  - https://doi.org/10.1038/s41592-024-02497-y
  - https://doi.org/10.1038/s41467-026-72152-x
alternatives_tested:
  - keeping the whole-register pin and re-issuing V0 on every register edit
  - leaving the interface delays at their registered values and shortening the coupling interval
  - retaining the mm/s label and documenting the conversion only in prose
validation_effect: >-
  V0 Structural was withdrawn and has been reissued as bundle 20260908T060641Z_V0, which
  validates. Track A acceptance evidence v1 and v2 are withdrawn permanently; the v3 matrix ran
  from clean commit 4a061ac and fails its own behavioural criterion in 30 of 30 runs, so no
  acceptance claim stands. Stage 1 conclusions are unchanged, but the gate-split disclosure is
  now part of the evidence record.
approved_by: project-owner
```

## Outcome

The repair is complete. V0 is reissued and validates, and Stage 2 has resumed. Two engineering
defects that the repair surfaced remain open and are tracked in
[docs/STATUS.md](../STATUS.md) and
[the Track A evidence report](../evidence/TRACK_A_EON_MALECNS.md): the FlyGym body cannot hold
station while grooming, and enabling the renderer shifts the last two transitions by 1.44 s
under no criterion that bounds it.

## Consequences

- The repaired bundle is written to a new path. The historical `V0-evidence.json` and its
  revision-1 raw-profile review stay on disk unchanged so that the withdrawn claim remains
  inspectable.
- Fixing the GeNN delay changes numerical output for every GeNN backend. The Stage 1 reports
  recorded a systematic one-step GeNN offset against NumPy and Brian2; that offset was this
  defect, and the affected reports predate the fix.
- Grooming now blends the published trajectory in over a registered interval. This is an
  actuator scaffold introduced to suppress the onset impulse of replaying a tethered-fly
  trajectory on a free-standing body, and it is registered in `MOTOR-03`, not presented as
  part of the published kinematics.
- `foundation-v0.5` becomes `foundation-v0.6`. Because V0 no longer pins the register, that
  bump no longer touches structural evidence.
