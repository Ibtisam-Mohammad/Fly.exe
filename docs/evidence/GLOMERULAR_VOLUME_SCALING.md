# Glomerular volume scaling: a blind test, and a self-correction it forces

Status: complete and **inconclusive**. No validation tier is awarded.

Artifact: `evidence/male-cns-v1.0/glomerular-volume-scaling-v1.json`
SHA-256 `e2553056b5e530a9315a09f9ffc12b15936b67839c01d0933f6407d5f03f0380`
Contract: [`glomerular-volume-scaling-v1.json`](../../configs/experiments/glomerular-volume-scaling-v1.json)
Clean worktree, evidence-grade. 50 glomeruli, 298 shards streamed, ~20 min.

## What was tested and why

Kazama and Wilson 2008 measured unitary EPSC amplitude against the glomerular volume occupied by
the PN dendritic tuft (r = 0.75, n = 39) and showed the scaling is carried by the number of
release sites per ORN axon per PN, while release probability and quantal size stay constant
across glomeruli. If contacts are release sites, contacts per ORN→PN connection should rise with
glomerular volume.

The project's earlier synaptic-structure test substituted converging ORN count for volume and
found no scaling. On 2026-09-09 this repository recorded that substitution as the reason the test
failed — a "proxy failure" — on the grounds that contacts anti-correlate with ORN count while the
contact ordering on Kazama and Wilson's four recorded glomeruli reproduces their uEPSC ordering.
That reasoning required volume never to have been measured. This contract measured it, blind.

**Volume** is the occupied-bin count of each glomerulus's ORN→PN postsynaptic cloud on a 1 µm
lattice (125 voxels at 8 nm), rarefied to a common 4,087 points per glomerulus over 25 seeded
repeats so that synapse count cannot masquerade as extent. Rarefaction did its job: it collapses
a full-sample range of 2,175–23,104 µm³ to 2,175–3,666 µm³ while preserving the ordering at
ρ = +0.954.

## Both preregistered hypotheses fail

| | ρ | p | verdict |
|---|---|---|---|
| **H1** contacts per connection ~ rarefied volume | **+0.070** | 0.629 | **fails** — no correlation |
| H1 unrarefied, as a check | −0.068 | 0.638 | also nothing |
| **H2** rarefied volume ~ ORN count | **+0.329** | **0.020** | **fails** — volume *does* track ORN count |

## The self-correction

**H2's failure withdraws yesterday's "proxy failure" explanation.** Kazama and Wilson state that
glomerular volume is linearly correlated with the number of presynaptic ORNs, and in MaleCNS it
is: ρ = +0.329 at p = 0.020, rising to +0.481 at p = 0.013 among well-reconstructed glomeruli. So
converging ORN count was a *directionally valid* proxy for volume after all, and the earlier
test was not testing the wrong variable. The correction recorded in STATUS on 2026-09-09 is
withdrawn.

The contract anticipated this outcome and said what it would mean: *"If that also holds in
MaleCNS then H1 and the observed negative contacts-versus-ORN-count correlation cannot both be
true, and this contract will have found a genuine inconsistency rather than a proxy failure."*

**The four-glomerulus ordering was a small-sample coincidence.** The contact ordering
DL5 81 > DM4 63 > VM2 40 > DM6 28 matched Kazama and Wilson's stated uEPSC ordering. The measured
volumes for the same four do not order the same way:

| glomerulus | rarefied volume (µm³) | median contacts |
|---|---|---|
| DM4 | 3,156.6 | 63.0 |
| DL5 | 2,972.4 | 81.0 |
| DM6 | 2,635.6 | 28.0 |
| VM2 | 2,229.7 | 40.0 |

Volume orders DM4 > DL5 > DM6 > VM2; contacts order DL5 > DM4 > VM2 > DM6. Two of the three
adjacent pairs are swapped. An ordinal agreement over two groups of two carries little
information, and the volume measurement says the mechanism Kazama and Wilson proposed is not what
produces it.

## But the result is inconclusive, not a clean negative

Stratifying by the convergence-test completeness changes the picture, and in a way that is
mechanistically expected rather than convenient:

| subset | n | contacts ~ volume | volume ~ nORN | contacts ~ nORN |
|---|---|---|---|---|
| all glomeruli | 50 | +0.070 (p=0.63) | +0.329 (p=0.020) | **−0.475 (p<0.001)** |
| completeness ≥ 0.85 | 26 | +0.381 (p=0.055) | +0.481 (p=0.013) | −0.174 (p=0.40) |
| completeness ≥ 0.90 | 17 | +0.314 (p=0.22) | +0.519 (p=0.033) | −0.116 (p=0.66) |
| completeness ≥ 0.95 | 11 | +0.527 (p=0.096) | +0.401 (p=0.22) | **−0.046 (p=0.89)** |

**The strong negative contacts-versus-ORN-count correlation is largely an artifact of
incompleteness.** It goes from −0.475 at p < 0.001 across all 50 glomeruli to −0.046 at p = 0.89
among the best-reconstructed eleven. That is exactly the bias the
[convergence test](ORN_PN_CONVERGENCE.md) characterised: median contacts is measured over
*realised* pairs, so it is inflated where weak connections have dropped out, and completeness is
lowest in glomeruli with many ORNs and many PNs. The measurement was reading reconstruction
quality as biology.

And contacts-versus-volume moves the other way, from +0.070 to +0.381 and +0.527 — the direction
Kazama and Wilson predict — but never reaches p < 0.05, and the n = 11 subset is far too small to
settle anything.

**So neither conclusion survives.** The earlier negative — "contact number does not implement the
published homeostatic matching" — is not reinstated as established, because the statistic behind
it is contaminated. Nor is the claim confirmed, because the uncontaminated subset is
underpowered. The honest verdict is that this connectome cannot settle the question with this
measurement, and it fails in the specific direction of being unable to measure the quantity where
the effect should be largest: the big glomeruli.

## What would settle it

A completeness-corrected contact estimate. The convergence test gives, per glomerulus, the
fraction of known connections recovered and the contact distribution of those recovered; together
those constrain what the missing connections carried, because weak connections are specifically
what goes missing. Correcting the contact median for that censoring, and rerunning H1 against
it, is the indicated next step. Nothing else on hand adds statistical power: there are only 50
glomeruli and only eleven are well reconstructed.

## Caveats

1. **Occupied-bin volume is a proxy for glomerular volume, not a segmentation of the glomerulus.**
   It is the extent of the ORN→PN postsynaptic cloud, which lies on the PN dendritic tuft Kazama
   and Wilson measured, but it is not that measurement.
2. **One anatomical contact is treated as one release site.** The convergence contract records
   this assumption too. Kazama and Wilson's release-site counts come from current-fluctuation
   analysis, not anatomy, so both sides are indirect estimates.
3. **Even after rarefaction, volume correlates with total synapse count at ρ = +0.826.** That is
   expected rather than a residual artifact: at a fixed 4,087 sampled points, a larger true extent
   spreads them over more bins, and glomeruli with more synapses genuinely occupy more space.
   Rarefaction removed the count-driven inflation of the magnitude, not the underlying biological
   relationship.
4. **The stratified analysis is post-hoc.** H1 and H2 were preregistered on all 50 glomeruli and
   both failed there. The completeness stratification was run afterwards, prompted by the
   convergence test's finding, and it is reported as an explanation for why the preregistered
   test is uninformative rather than as a result in its own right. It must not be read as a pass.

## Record of corrections around this claim

| date | recorded | status |
|---|---|---|
| earlier | "contact number does not implement the published homeostatic matching" | contaminated statistic; neither confirmed nor refuted |
| 2026-09-09 | that negative was a proxy failure, since volume does not track ORN count | **withdrawn** — volume does track ORN count, ρ = +0.329, p = 0.020 |
| 2026-09-09 | contacts reproduce the uEPSC ordering on the four recorded glomeruli | **withdrawn as evidence** — the measured volumes for those four order differently, and two groups of two carry little information |
| now | the question is not settleable on this connectome with this measurement | current |

Two of those three were recorded in this repository within a day of being withdrawn. The
preregistered blind test is what withdrew them, which is the argument for preregistering rather
than for trusting a plausible mechanism.
