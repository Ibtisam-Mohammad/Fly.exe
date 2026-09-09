# Bilateral ORN→PN symmetry: the connectome makes a prediction the source experiment could not test

Status: complete. **The preregistered prediction is rejected, decisively and reproducibly.**
No validation tier is awarded — this is a structural test, not a model test.

Artifact: `evidence/male-cns-v1.0/stage2-bilateral-symmetry-v1.json`
SHA-256 `c74a4c55fd9c3a19404628c4346093aa2c331a5b8fdc3d5c2b772cd15859d11c`
Contract: [`stage2-bilateral-symmetry-v1.json`](../../configs/experiments/stage2-bilateral-symmetry-v1.json)
Code commit `564bdb9`, clean worktree, evidence-grade. 50 glomeruli, 265 projection neurons.

## The prediction

Kazama and Wilson 2008 report that ipsilateral and contralateral ORN projections produce
uEPSCs of equal amplitude, at p > 0.54. They also found release probability and quantal
size constant across glomeruli, so under the identification of one anatomical contact with
one release site, equal amplitude implies an equal number of contacts per connection from
each antenna onto the same PN.

That is parameter-free and needs no physiology. It is also **better conditioned than any
previous contact-based test in this project**, because it is paired within a projection
neuron, so the glomerulus-to-glomerulus variation that confounded the
[volume test](GLOMERULAR_VOLUME_SCALING.md) and the homeostatic-matching test cancels
exactly.

## The result

| | criterion | observed | verdict |
|---|---|---|---|
| **H1** | median \|log2(ipsi/contra)\| ≤ 0.3 and sign test p ≥ 0.05 | median **+0.643**, ratio **1.561**, 220/40, **p = 2.7e-31** | **rejected** |
| **H2** | same sign for left-side and right-side PNs | **both positive** | passes; the effect is ipsi-vs-contra |
| **H3** | median ipsi−contra completeness difference within ±0.05 | **+0.0496** | passes, by 0.0004 |

**Ipsilateral ORN→PN connections carry about 1.56 times the contacts of contralateral
ones**, and 220 of 260 projection neurons show the bias individually.

## H2 rules out the deflationary explanation, and a tighter control rules out another

The obvious worry is that this is reconstruction, not biology. The graph has 1343 right-side
against 883 left-side ORNs, a 1.52-to-1 recovery asymmetry that no fly has. Two controls
address it.

**H2, preregistered.** If the effect were a left/right asymmetry of the reconstruction, it
would reverse sign between left-side and right-side PNs — what is "ipsilateral" for a left
PN is "contralateral" for a right one. It does not reverse:

| PN side | n | median log2(ipsi/contra) | ratio | sign test |
|---|---|---|---|---|
| left | 131 | +0.430 | 1.35 | 99 / 32, p = 3.7e-9 |
| right | 129 | +0.783 | 1.72 | 121 / 8, p = 4.8e-27 |

Both positive, so it is genuinely an ipsilateral-versus-contralateral effect. The
*magnitudes* differ, 1.35 against 1.72, so a left/right component is superimposed on it —
consistent with the recovery asymmetry — but it does not generate the effect.

**A within-ORN control, post-hoc.** Each ORN projects to *both* antennal lobes, so the same
axon makes ipsilateral and contralateral connections. Comparing them inside one ORN holds
the soma, the axon and that neuron's entire reconstruction quality fixed:

```
ORNs with realised pairs in both lobes   1799
median log2(ipsi/contra)               +0.634   ratio 1.552
sign test                        1409 / 378     p = 2.0e-139
```

**1.552 against 1.561** — the same number from a completely different pairing. So the bias
is not an ORN-level reconstruction-quality effect, because within-ORN comparison eliminates
that by construction. This control is labelled post-hoc: it was run after seeing H1's
result, and it is reported as an explanation of what the effect is not, rather than as a
preregistered finding.

**What remains unexcluded** is reconstruction bias *within* an axon: the contralateral
branch crosses the midline through the antennal commissure, a longer and thinner path whose
distal arbor is the hardest part to trace. The within-ORN control cannot see that, because
it is the same axon. H3 argues against it being severe — pair-level completeness differs by
only 0.05 — but a contralateral arbor could lose contacts without losing whole pairs, which
is precisely the regime H3 does not probe.

## What this means, and the reading matters

**Kazama and Wilson's p > 0.54 is a failure to reject, not a demonstration of equality.**
That distinction carries the interpretation. A patch-clamp comparison at their sample sizes
would not reliably detect a 1.56-fold difference, so the connectome is not necessarily
contradicting their data. It is making a **quantitative prediction their experiment did not
have the power to test**: ipsilateral unitary EPSCs should be roughly 1.5 times
contralateral ones onto the same PN.

That is the useful output. It is a falsifiable, targeted, single-experiment prediction
derived from structure alone, and it is the kind of thing a connectome model ought to
produce. It can be checked by anyone with the preparation Kazama and Wilson used.

**The alternative reading is that one contact is not one release site**, which two
independent results now support. The
[completeness correction](COMPLETENESS_CORRECTED_CONTACTS.md) found corrected contact counts
about 2.06 times their release-site estimate, and this test finds a contact asymmetry where
they measured no amplitude asymmetry. Both point the same way, from different directions,
and neither depends on the other. The contact-to-release-site identification is now the
most load-bearing untested assumption in every contact-based claim this project makes, and
it should be treated as such rather than as a convention.

## H3 passed, and should not be leaned on

H3 was registered **expecting to fail**, because the ORN side counts were known in advance.
It passed at +0.0496 against a ±0.05 limit — by four ten-thousandths. That is a pass by the
letter and it should not be read as evidence of balanced reconstruction. Its direction is
also the same as H1's, ipsi-favouring, so what it shows is that the pair-level asymmetry is
small while the contact-level asymmetry is large — which is the observation that makes the
within-axon reconstruction worry hard to dismiss.

## A defect this test found in its own instrument

The first sign-test implementation computed an exact binomial coefficient divided by
`2.0 ** n`, which overflows above about a thousand observations. It raised `OverflowError`
on the within-ORN control's 1799 pairs. The tail is now summed in log space, and two
regression tests cover it: one at 2300 observations, and one against a published two-sided
critical value (15 of 18 → p = 0.007538).

The artifact is unaffected: its 260 observations are below the overflow threshold, and the
recorded p-values were computed correctly.

## What this does not do

It awards no tier, fits nothing and simulates nothing. **It tests the connectome and the
published anatomy, not this project's simulator** — no membrane parameter, synaptic kernel
or integration step is touched. A pass would have been agreement between MaleCNS v1.0 and
an independent physiological measurement; the rejection is a disagreement between them,
with two candidate causes named and one of them, ORN-level reconstruction quality,
eliminated.

This test is the structural leg of [`stage2-exit-gate-v4`](../adr/ADR-2026-011-retire-the-blocked-physiology-gates.md),
where it **fails**, and it is the only leg in that gate whose criterion was registered
before the run that scores it.
