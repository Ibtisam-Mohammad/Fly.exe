# Widened grooming circuit: the structural reading, tested

Status: complete. No validation tier is awarded and none can be.

Artifact: `evidence/male-cns-v1.0/shiu-grooming-widened-v3.json`
SHA-256 `b5149835e423587f8fc9e31b7ba21934f9ee60cbfa84acf06d38384a6713c150`
Contract: [`shiu-antennal-grooming-widened-v3.json`](../../configs/experiments/shiu-antennal-grooming-widened-v3.json)
Code commit `311c25c`, clean worktree, evidence-grade.

## The question

[ADR-2026-008](../adr/ADR-2026-008-synaptic-tier-and-stage2-exit-gate.md) found that no single
contact scale fits the archived Shiu Figure 5g reference at both 100 Hz and 220 Hz, and proposed
that missing `ND-06` short-term depression was the reason.
[ADR-2026-009](../adr/ADR-2026-009-stage2-independent-review.md) withdrew that as a category
error — the reference is a static whole-brain simulation with no depression in it, and the
transferred circuit is a 41-neuron one-hop subgraph — and substituted a structural reading: the
over-response at high drive comes from the paths the shortest-path selection rule excluded.

This is that test. The same `ND-04` contact-scale sweep is run on circuits that keep every
input-to-readout path of bounded length `K`, so the lateral and recurrent partners the
shortest-path rule dropped are present.

## The answer

**The structural reading is right about the cause and wrong about the cure.** The shortest-path
rule did drop something decisive — it dropped *every* inhibitory input to the readout. But
restoring those inputs does not moderate the response toward the reference. It abolishes it.

| | K = 1 (one-hop) | K = 2 | K = 3 | reference |
|---|---|---|---|---|
| neurons / edges | 41 / 129 | 322 / 11,140 | 1,706 / 139,215 | whole brain |
| JON-F inputs stimulated | 39 | 78 | 78 | — |
| 220 Hz readout rate at 0.15 mV/contact | 33.2 Hz | **0.0 Hz** | **0.0 Hz** | 4.63 ± 2.01 Hz |
| 100 Hz readout rate at 0.15 mV/contact | 0.17 Hz | **0.0 Hz** | **0.0 Hz** | 0.93 ± 0.96 Hz |
| readout rate at *any* of 11 scales | — | 0.0 Hz | 0.0 Hz | — |

The one-hop circuit over-responds sevenfold at 220 Hz. The widened circuits produce nothing, at
every one of the eleven candidate scales from 0.025 to 0.275 mV per contact and at all three
sweep frequencies. The truth is bracketed and neither circuit contains it.

- **H1 (does widening move the 220 Hz response toward the reference?)** — outcome `suppressed`
  at both path lengths. Not supported.
- **H2 (does some single scale reproduce both reference means within one SD?)** — fails at both
  path lengths, as it does for the one-hop circuit.
- GeNN and NumPy parity passes at both path lengths, so the result is not a backend artifact.

## Why the readout is silent

The mechanism is specific, and it is not bulk connectivity.

| | readout 11718 | | readout 521358 | |
|---|---|---|---|---|
| | static net | delivered net | static net | delivered net |
| K = 1 | **+57** (0 inhibitory inputs) | +12,857 | **+74** (0 inhibitory inputs) | +16,159 |
| K = 2 | −222 | −11,194 | −267 | −12,139 |
| K = 3 | **+440** | **−11,256** | **+657** | **−12,684** |

"Static net" is the signed contact sum over all incoming edges. "Delivered net" weights each
edge by how often its presynaptic partner actually fired, at 0.15 mV per contact and 220 Hz.

Three things follow.

**The one-hop circuit has no inhibition onto the readout at all.** Zero inhibitory inputs, on
both readouts. Every inhibitory path to aBN1 in MaleCNS is two hops or longer, so a
shortest-path induced subgraph is guaranteed to be purely feedforward-excitatory at the readout.
That is a property of the selection rule, not of the biology, and it is sufficient on its own to
explain a monotone over-response to increasing drive.

**Delivered excitation barely changes as the circuit grows.** 12,857 → 13,564 → 13,375 on one
readout and 16,159 → 17,804 → 17,932 on the other, while the edge count grows a thousandfold.
At K = 3 only 27 of 296 excitatory sources and 35 of 386 are ever active. Almost everything
widening adds is silent. What it adds that matters is 14 to 22 active inhibitory neurons which
between them deliver roughly 1.8 times the excitatory drive.

**The static contact sum is the wrong diagnostic, and it was our first one.** At K = 3 it is net
*excitatory* — +440 and +657 — onto readouts that never fire, because it counts hundreds of
excitatory partners that never spike. Delivered drive has the opposite sign. The contract records
`static_and_delivered_agree_in_sign` for exactly this reason: reporting the static sum alone
would have supported a confident and wrong mechanism, and at K = 2 it happens to agree, so the
error would not have shown up at the first path length.

## What this costs the transferred-circuit method

Widening the selection rule is not a repair for the one-hop circuit. Both readings of "make the
subgraph more complete" fail: keep the shortest paths and the readout has no inhibition and
over-responds sevenfold; keep every bounded path and the readout is held silent by a handful of
inhibitory partners. A bounded induced subgraph of a connectome is not a small version of the
whole-brain simulation, and the sweep is evidence that the difference is not a matter of degree.

This bears directly on what Stage 2 may claim from `ND-04`. The derived per-contact scale was
never validated against a held-out frequency, and this sweep shows the failure is not one a
better scale or a wider subgraph fixes.

## Caveats, in order of how much they could change the reading

1. **Only the `zero` unresolved-sign policy was run.** 7 neurons at K = 2 and 39 at K = 3 have
   unresolved transmitter predictions and contribute nothing under this policy. The excitatory,
   inhibitory and seeded-balanced policies are registered and were not swept here. Since the
   result turns on an inhibition/excitation balance, this is the control most likely to move it
   and it is the obvious next run.
2. **The stimulated drive roughly doubles between K = 1 and K = 2**, from 39 JON-F input bodies
   to 78, because more inputs reach a readout within two hops than within one. This strengthens
   the suppression finding — twice the drive, no output — and would have weakened a moderation
   finding. It is recorded in the contract as a known confound.
3. **K = 4 was excluded before registration** at 35,425 neurons and 6,458,359 edges, as too
   large for the NumPy runner in-session. Whether suppression persists or reverses at K = 4 is
   untested.
4. **The scale grid spans 0.025 to 0.275 mV per contact.** Because delivered drive is net
   inhibitory, scaling up cannot rescue the readout, and no window opens at the bottom of the
   grid either. A scale below 0.025 was not tested.
5. **The reference is simulation output, not a recording.** Even a pass on H2 would have been a
   fit of one scale to two points from another model.
6. **The excitation/inhibition balance is computed from a minority of each readout's inputs.**
   The MaleCNS paper reports 42% postsynaptic completion, so more than half of all postsynaptic
   sites are not attributed to a proofread neuron, and 40.1% of synaptic connections have both
   partners proofread. The entire result here is a signed sum over *recovered* edges onto the two
   readouts, and the direction of the bias from the missing majority is unknown. The
   [ORN-to-PN convergence test](ORN_PN_CONVERGENCE.md), run after this sweep, shows what that
   costs in practice: edge recovery is complete where connections are strong and degrades
   specifically at the weak end, and a neuron's total contact budget predicts whether its known
   connections are recovered. That statistic has since been computed for these populations and
   it changes how much weight this result can bear; see the section below.

## Rounds run, including the discarded one

| round | contract | outcome | disposition |
|---|---|---|---|
| v1 | `shiu-antennal-grooming-widened.json` | GeNN parity passed; readout silent at all scales; H2 failed; **H1 scored as passed** | Retained unedited. Its H1 verdict is superseded: the criterion was the one-sided "widened 220 Hz rate below the one-hop 33.167 Hz", which a silent readout satisfies. A criterion satisfied by silence is vacuous. |
| v2 | `...-widened-v2.json` | H1 corrected to a three-way outcome, `suppressed` at both K; K = 1 identity control added and passed; static readout drive and circuit activity added | Retained. Its H4 static-sum diagnostic was then found insufficient, per the sign disagreement above. |
| v3, first attempt | `...-widened-v3.json` | recorded `code_commit` 6ad1c17 while running with uncommitted changes | **Discarded**, moved to `evidence/male-cns-v1.0/discarded/`. `widened.py` had called a bare `git rev-parse HEAD` instead of checking the worktree — the same provenance defect the evidence-chain repair banned for Track A, in a new code path. The sweep now calls `require_clean_worktree` and records `worktree_dirty` and `evidence_grade`. |
| v3, rerun | `...-widened-v3.json` | the artifact above, from clean commit `311c25c` | Current. |

Two of those three corrections were to criteria and diagnostics this session had itself just
written. Both are recorded rather than quietly fixed, because the v1 artifact is issued and a
reader who finds it needs to know why its H1 says what it says.

## Reconstruction quality of these populations, measured after the fact

The [convergence test](ORN_PN_CONVERGENCE.md) established that a neuron's total contact budget
predicts whether its known connections are recovered, and calibrated what good and bad look
like. Applying that instrument here, in percentile terms against all 165,122 traced neurons
(graph median 442 out-contacts, 349 in-contacts):

| population | out-contacts | percentile | in-contacts | percentile |
|---|---|---|---|---|
| JON-F inputs (n = 78) | 260 median | **24.2** | 36 median | — |
| aBN1 readout 11718 | 6,962 | **99.4** | 3,158 | 96.1 |
| aBN1 readout 521358 | 7,055 | **99.4** | 3,710 | 97.1 |
| VM7d ORNs (convergence 1.000) | 834 median | 78.0 | — | — |
| VL2p ORNs (convergence 0.485) | 533 median | 58.7 | — | — |

Three things follow, and the second is the one that matters.

**The readouts are excellently reconstructed.** Both aBN1 cells sit at the 99.4th percentile for
outputs and above the 96th for inputs. Whatever else is wrong here, it is not that the readouts
are poorly reconstructed neurons.

**The inhibitory and excitatory partners are not equally well reconstructed, and the asymmetry
runs the same way as the result.** Median out-contact budget of the sources delivering onto each
readout at K = 2:

| readout | inhibitory sources | percentile | excitatory sources | percentile | ratio |
|---|---|---|---|---|---|
| 11718 | 2,884 | 96.3 | 882 | 79.6 | **3.3×** |
| 521358 | 2,530 | 95.5 | 853 | 78.6 | **3.0×** |

The inhibitory partners carry roughly three times the contact budget of the excitatory ones. Part
of that is real biology — the gain-control literature describes antennal-lobe inhibition as
coming from cells with broad dense arbors, and large cells genuinely have more synapses — but
larger and better-reconstructed neurons also have their edges recovered more completely, at 42%
postsynaptic completion. **The recovered excitation/inhibition balance therefore overstates
inhibition relative to the truth, by an amount this data cannot quantify.** The suppression
finding is not thereby explained away: delivered inhibition exceeds delivered excitation by about
1.8-fold, and the reconstruction asymmetry is 3-fold in contact budget, so the two are the same
order of magnitude and the sign of the true balance is genuinely uncertain. That is a materially
weaker claim than this report made before the statistic existed.

**The JON-F inputs are worse reconstructed than the worst glomerulus in the convergence test.**
At the 24.2nd percentile they fall below VL2p's ORNs at 58.7, and VL2p is the glomerulus where
only 48.5% of known connections were recovered. This is a caveat on the entire Stage 1 grooming
transfer, not only on this sweep: the 39 JON-F inputs of the one-hop circuit and the 78 of the
widened circuits are drawn from a poorly reconstructed sensory population, which is expected for
axons entering from the periphery and is exactly the population whose edges are most likely to be
missing. Any claim about how much drive reaches aBN1 inherits that.

**Net effect on the reading.** H1's `suppressed` outcome and H2's failure stand as measurements of
the model as built. The mechanistic attribution — that a handful of active inhibitory neurons
holds the readout silent — is now qualified: those neurons are the best-reconstructed partners in
a circuit whose excitatory partners and sensory inputs are among the worst, and the observed
balance is consistent with that asymmetry rather than independent of it. Establishing the true
balance needs either a reconstruction-corrected estimate or a circuit whose partners are
uniformly well reconstructed.
