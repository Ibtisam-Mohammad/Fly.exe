# ORN→PN convergence: the connectome tested against independent physiology

Status: complete. No validation tier is awarded — this is a structural test, not a model test.

Artifact: `evidence/male-cns-v1.0/orn-pn-convergence-v1.json`
SHA-256 `eba6ab95af9a6a60bfd15716e0833eb751a9f7aaa1aa3755eda309cd6c435a9e`
Contract: [`orn-pn-convergence-v1.json`](../../configs/experiments/orn-pn-convergence-v1.json)
Code commit `ee79bb4`, clean worktree, evidence-grade. Runtime 43 s.

## The prediction

Kazama and Wilson 2009 found that spontaneous EPSCs occur synchronously in homotypic PN pairs
and concluded: *"ORN-PN connections are completely convergent, with each PN receiving input from
all ORNs. This is equivalent to the statement that this circuit is completely divergent, meaning
that each ORN synapses onto all PNs."*

That is binary, parameter-free and complete-bipartite. It needs no biophysics, no fit and no
simulation, so it tests the connectome rather than any model this project has built. Scope: the
50 glomeruli carrying both an `ORN_` type and a uniglomerular PN type, 2,562 ORN and 265 PN
bodies in the graph, 16,384 possible ordered pairs, all four glomeruli Kazama and Wilson
recorded included.

## The headline

**Both preregistered hypotheses fail globally, and the prediction is nevertheless confirmed
exactly where the connectome is well reconstructed.**

| | result |
|---|---|
| H1: minimum completeness = 1.0 | **fails** — minimum 0.485 (VL2p) |
| H2: median completeness ≥ 0.95 | **fails** — median 0.865, pooled 0.756 |
| glomeruli at exactly 1.0 | **4** — V, VC5, VM5v, VM7d |
| glomeruli below the 0.95 floor | 39 of 50 |
| PNs reached by no cognate ORN | **0** |

Four glomeruli are perfectly complete bipartite graphs:

```
  V      55 ORN x  2 PN =  110 pairs, all present, median 49 contacts
  VC5    31 ORN x  6 PN =  186 pairs, all present, median 44 contacts
  VM5v   34 ORN x  5 PN =  170 pairs, all present, median 46 contacts
  VM7d   36 ORN x  7 PN =  252 pairs, all present, median 39 contacts
  ----------------------------------------------------------------
  TOTAL   4 glomeruli,      718 ordered pairs, zero missing
```

If edges were recovered independently at the observed median rate of 0.865, the probability that
all 718 of those pairs would be present is 0.865⁷¹⁸ = **7.3 × 10⁻⁴⁶**; for VM7d's 252 pairs alone
it is 1.4 × 10⁻¹⁶. These are not near-misses that happened to round up. Where the reconstruction
supports the question, the answer is exactly the one Kazama and Wilson predicted.

## Why the other 46 fall short

The contract required the artifact to distinguish four candidate causes rather than assert one.
Three are ruled out and the fourth is confirmed with a quantitative signal.

**Not PN mislabelling.** Zero projection neurons are reached by no cognate ORN, across all 50
glomeruli. If uniglomerular PN labels were being applied to cells not postsynaptic to that
glomerulus, those cells would appear as orphans. None do.

**Not a failure of the biological claim.** The four glomeruli Kazama and Wilson actually recorded
span 0.680 (DM4) to 0.988 (DL5), with a median of 0.881 against 0.855 for the other 46. Their
origin glomeruli are not systematically better than the rest, so "the claim does not generalise
beyond where it was measured" predicts the opposite of what is observed. And the four perfect
glomeruli are ones they never recorded, which is the claim generalising rather than failing.

**Not per-synapse incompleteness alone — my H2 argument was wrong.** H2 reasoned that at 42%
postsynaptic completion and at least 10 release sites per pair, edge-level recovery could not
fall below about 0.99. The flaw is the premise: the contact count per pair is *not* uniformly ≥10.
Measured median contacts per realised pair range from 9 to 117.5 across glomeruli, and in the
worst glomeruli many pairs carry 1 to 4 contacts, where a 42% per-synapse recovery rate leaves a
real chance of losing the pair entirely. The argument was sound arithmetic on a false premise.

**It is reconstruction quality, and it is measurable per neuron.** Two independent signals:

- **Per ORN.** The fraction of its cognate PNs that an ORN reaches correlates strongly with that
  ORN's total out-contact budget: r = **+0.836** in VL2p, **+0.847** in DA1, +0.597 in DL5,
  +0.501 in DM4. An ORN that reaches few of its targets is an ORN whose axon carries few
  reconstructed contacts anywhere. The distributions are smooth rather than bimodal, so
  reconstruction completeness varies continuously across axons instead of splitting them into
  intact and broken.
- **Per glomerulus.** Completeness correlates with connection strength across the 50 glomeruli,
  r = +0.575 (Pearson) and +0.611 (rank). Stratified:

  | stratum | n | median completeness | at 1.0 |
  |---|---|---|---|
  | median contacts ≥ 40 | 28 | 0.912 | 3 |
  | median contacts < 20 | 9 | 0.729 | 0 |

**Weak connections are specifically what goes missing.** In VM7d, complete at 1.000, *zero* of
252 realised pairs carry fewer than 5 contacts. In DL5, at 0.988, zero of 85 pairs carry fewer
than 10. In VL2p, at 0.485, twenty of 131 realised pairs carry fewer than 5 and ten carry exactly
one. A glomerulus is complete when it has no weak connections to lose.

## What this establishes, and what it does not

**It establishes** the first quantitative agreement between the MaleCNS connectome and an
independent physiological measurement in this project. Complete ORN→PN convergence holds exactly
in every glomerulus whose reconstruction is strong enough to test it, and the deviations
elsewhere are explained by a measurable property of the reconstruction rather than left as
unexplained disagreement.

**It also yields a reusable instrument.** An ORN's out-contact budget predicts whether its known
connections are recovered. The same statistic can be computed for any neuron in any circuit this
project models, which turns "is this subgraph well reconstructed?" from a worry into a
measurement. That is directly relevant to
[the widened grooming circuit](STAGE2_WIDENED_GROOMING_CIRCUIT.md), whose entire result rests on
an excitation/inhibition balance computed from recovered edges, and which currently carries no
reconstruction-quality statistic at all. Computing one for the JON-F→aBN1 populations is the
obvious follow-up.

**It does not** award any tier, validate any parameter, or say anything about dynamics. It is
also a test of the annotation as much as the segmentation: the populations come from the `type`
column, and a systematic typing error would show up here as reconstruction failure. The zero
orphan count argues against gross typing error but does not exclude subtler ones.

## Secondary observations

**Contacts per connection against release sites per connection.** Median contacts over realised
pairs is 14.0 pooled, with per-glomerulus medians from 9 to 117.5. Kazama and Wilson's
fluctuation analysis gives 51.4 ± 7.8 release sites per ORN axon per PN and ">25 per PN" for
large glomeruli; Rozenfeld and colleagues independently estimate 10–30. The pooled figure sits
inside the Rozenfeld range and below the fluctuation estimate, but the pooled figure is close to
meaningless given the eleven-fold spread across glomeruli, and it is biased upward because pairs
with more contacts are more likely to be recovered at all. Identifying one anatomical contact
with one vesicular release site is an assumption the contract records as one; both sides of this
comparison are indirect estimates of the same quantity.

**Presynaptic feedback is present.** 3,315 PN→ORN ordered pairs exist across the 50 glomeruli,
measured as a control and not part of any hypothesis. Feedback onto ORN terminals is expected —
Nagel and colleagues show presynaptic inhibition dynamically updates ORN→PN synaptic properties,
and blocking GABA_B with CGP54626 markedly alters PN responses — so its presence is a sanity
check passed rather than a surprise. It is also a reminder that the ORN→PN pathway is not
feedforward, which bears on any model that treats it as such.

**DM4 ORN count, recorded and explicitly not a passed prediction.** MaleCNS carries 32 Traced DM4
ORN bodies against the 34.8 implied by Kazama and Wilson's 17.4 ± 0.9 per antenna counted from
Or59b-GFP labelling, an 8% shortfall consistent with a small number of unrecovered axons. This
count was observed while scoping the contract, before it was written, and the contract says so.
It is a comparison, not a test.

**DA1 is large, as expected in a male.** 204 ORNs and 15 PNs, the largest of the 50 by both
measures, consistent with the pheromone glomerulus in a male nervous system. Its completeness is
0.738, in line with its low median contact count of 12 rather than anything anatomically
peculiar.

## Corrections this run forces

1. **H2's derivation is wrong and must be marked so, not quietly dropped.** Its arithmetic is
   right and its premise is false: it assumed ≥10 contacts per pair when the measured
   distribution reaches down to 1. A v2 contract should replace the flat release-site assumption
   with the measured per-glomerulus contact distribution. The v1 contract and artifact stay
   unedited.
2. **The 0.9999988 figure in H2 was itself corrected before the run**, from an initial
   0.99998 that was simply miscalculated. Caught by a test that checks the contract's own
   arithmetic, which is why that test exists.
3. **Report reconstruction quality alongside every modelled circuit.** See above.
