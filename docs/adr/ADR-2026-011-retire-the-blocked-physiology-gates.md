# ADR-2026-011 — Retire the cellular and synaptic legs as Stage 2 gates; rebuild the gate on structural predictions

Date: 2026-09-09
Status: accepted
Supersedes: the leg composition of `stage2-exit-gate-v3`, not its verdicts

## Context

The Stage 2 exit gate has four legs — cellular, synaptic, circuit, ensemble — and it is
**0 of 4**. Two of those four cannot be satisfied or refuted by anyone, including this
project, for a reason that has nothing to do with the model.

**The cellular and synaptic legs require raw patch-clamp traces that are not publicly
available.** This was checked and recorded: no public repository holds raw Drosophila PN
or ORN→PN traces, confirmed absent for Kazama and Wilson 2008 and 2009, Gouwens and
Wilson 2009, and Nagel and Wilson 2015. What exists is published figures and summary
statistics, which is what the current legs are built from. The consequences are already
recorded in the gate's own `sufficiency_caveats`:

- the cellular holdout draws its held-out cells from the same paper and the same
  two-cell cohort, so it is a same-population holdout, and only firing rate is scored;
- the synaptic holdout's twelve source waveforms were peak-aligned by the authors, so
  the peak-time criterion measures the alignment convention rather than the model, and
  the inward-sign criterion is satisfied by selection.

Those are not defects in the criteria. They are the best that can be built from figure
data, and no amount of further work on this project's side changes them, because the
missing input is somebody else's unpublished recording.

## Decision

**1. The cellular and synaptic legs are retired as gates.** They are demoted to recorded
priors: still parameterised, still labelled with provenance, still reported at every
evaluation, and no longer scored toward the gate.

**2. The gate is rebuilt on structural predictions against the locked connectome.** These
are the tests that have proven able to pass *and* fail informatively here, needing no
biophysics, no fitting and no simulation.

**3. No tier is awarded by this change, and the gate does not become easier to pass.**

## Why this is not gate redefinition to manufacture a pass

An independent audit of this repository in September 2026 found gate redefinition among
its undisclosed problems. This decision is exactly the shape of that failure and has to
be justified against it, not merely distinguished from it in passing.

**The justification for retiring the two legs is independent of their failing.** They are
retired because the measurement they require does not exist for anyone. That reason would
hold identically if both legs were passing — and in fact both *did* pass in earlier gate
revisions, on criteria that were later tightened precisely because they were satisfiable
without predicting anything. A leg that cannot be advanced by any work this project could
do is not a test; it is a wait. Waits belong in the status document, not in a gate.

**The rebuilt gate must not be satisfiable by tests already run.** That constraint is what
stops this being criterion-shopping at the highest level, and it is the reason the new
structural leg is a test whose outcome was unknown when the leg was written. The
composition rule adopted here is:

> A structural leg may only enter the gate at a criterion registered before the test that
> scores it was run.

**The gate stays failing.** After this change it is **0 of 3**, so nothing is gained. The
circuit and ensemble legs are unchanged and still fail. The new structural leg fails too:
the bilateral-symmetry test was preregistered, then run, and its primary hypothesis was
rejected at p = 2.7e-31.

**Nothing recorded is withdrawn.** The v3 verdict of 0 of 4 stands. The cellular and
synaptic artifacts keep their checksums and their caveats, and the reason they are no
longer scored is recorded in the gate itself rather than only here.

## What is lost

This is the real cost and it should not be softened.

**The project gives up, for now, on the claim that most distinguishes it.** A connectome
model that predicts a held-out *cellular* or *synaptic* response in time and amplitude is
a stronger scientific object than one that predicts graph structure, however well. Stage
2's original gate statement — "held-out cellular, synaptic and circuit responses are
predicted in time and amplitude, not merely activation order" — was the right ambition.
Retiring two of its three legs narrows what a pass would mean, and any future statement of
Stage 2 has to say so in the same breath as claiming it.

**Structural predictions test the connectome, not the model.** Every structural result
recorded here — the convergence test, the volume test, the completeness correction, the
bilateral test — is a statement about MaleCNS v1.0 and about published anatomy. None of
them exercises a single membrane parameter, so none of them can validate the simulator.
A gate built from them measures whether the substrate agrees with the literature, which
is necessary and is not sufficient.

**The two retired legs must be reinstated if the data appears.** If raw traces are
released, or a collaboration supplies them, the cellular and synaptic legs return at
criteria at least as strict as v3's. They are retired for want of input, not because the
question was answered.

## The rebuilt gate

`stage2-exit-gate-v4`:

| leg | status | requirement |
|---|---|---|
| circuit | **retained**, fails | held-out circuit response predicted, not merely activation order |
| ensemble | **retained**, fails | key predictions survive a VAL-01-shaped parameter and model ensemble |
| structural | **new**, fails | a preregistered structural prediction from the literature holds on the locked graph |
| cellular | **retired to prior** | reported, not scored; raw traces unavailable |
| synaptic | **retired to prior** | reported, not scored; raw traces unavailable |

The structural leg is scored on the bilateral-symmetry test, whose H1 was registered
before it was run and is rejected. Two earlier structural tests are recorded alongside it
as context and are deliberately **not** scored, because their outcomes were known before
this leg existed: the convergence test, which fails its registered global criterion while
holding exactly where reconstruction permits, and the glomerular volume test, which is
unsettled for want of power.

## Consequences

- `AGENTS.md` section 9's Stage 2 statement is now narrower than the gate it describes and
  must be amended to say which legs are scored and why the others are not.
- `STATUS.md` must carry the retirement, the reason, and the reinstatement condition.
- The supported tier is unchanged. No evidence bundle changes. `V0 Structural` remains the
  highest tier this project supports, and Stage 2 remains unpassed.
