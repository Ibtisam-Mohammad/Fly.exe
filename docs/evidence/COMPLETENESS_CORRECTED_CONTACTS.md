# Completeness-corrected contacts: a correction that fails, and what falsifies it

Status: complete. **The correction fails its own preregistered gate and is not adopted.**
No validation tier is awarded, and no previously recorded contact statistic is corrected
by it.

Artifact: `evidence/male-cns-v1.0/completeness-corrected-contacts-v1.json`
SHA-256 `cb2c078c7d4d73058a516804a0794919907f9d84bf63688073a322df2d910a9f`
Contract: [`completeness-corrected-contacts-v1.json`](../../configs/experiments/completeness-corrected-contacts-v1.json)
Code commit `d9722b3`, clean worktree, evidence-grade. 50 glomeruli.

## What was attempted

Median contacts per realised ORN-to-PN connection is the statistic three of this
project's results rest on, and it is measured over realised pairs only. The
[convergence test](ORN_PN_CONVERGENCE.md) showed that weak connections are specifically
what goes missing, so the statistic is inflated exactly where reconstruction is worst,
and the [glomerular volume test](GLOMERULAR_VOLUME_SCALING.md) was declared inconclusive
for that reason. Its closing section named this correction as the indicated next step.

The model: a true connection carrying `k_true` synapses appears in the graph with
`k_obs ~ Binomial(k_true, p)` at the released `p = 0.42` postsynaptic completion rate,
and is absent entirely when `k_obs = 0`. The observed contact distribution is then a
zero-truncated binomial thinning of the truth at a known rate.

Two independent legs. **The exact leg needs no distributional assumption at all:** an
absent pair contributes no observed contacts, so the observed total over realised pairs
is also the total over *all* true pairs, and Kazama and Wilson 2009 supply the true pair
count because ORN-to-PN connectivity is complete bipartite. So

```
E[k_true] = total_contacts / (p * n_ORN * n_PN)   =   naive mean * completeness / p
```

That correction factor is above 1 for well-reconstructed glomeruli and below 1 for badly
reconstructed ones, because losing synapses inside recovered pairs and losing whole weak
pairs bias in opposite directions. **The model leg** is analytic, because a negative
binomial is closed under binomial thinning: zero-truncating the truth leaves the observed
counts exactly zero-truncated negative binomial in the thinned parameter. So fitting the
observed counts identifies the thinned shape, and the completeness becomes a prediction
the fit never saw.

## Every hypothesis fails except the boundary guard

| | criterion | observed | verdict |
|---|---|---|---|
| **H1** gate | predicted-vs-measured completeness ρ ≥ 0.7, median abs error ≤ 0.10 | ρ = **0.635**, error **0.131** | **fails** |
| **H2** | ≥ 35 glomeruli yield a solvable p, median in [0.30, 0.55] | **1 of 50**, p = 0.096 | **fails** |
| **H3** | corrected-vs-ORN-count \|ρ\| < 0.30 and p ≥ 0.05 | ρ = **−0.554**, p = 3.0e-5 | **fails** |
| **H4** | corrected-vs-volume p < 0.05, ρ > 0 | ρ = +0.209, p = 0.146 | not supported |
| **H5** | fewer than 5 fits at a search boundary | **0** | passes |
| **H6** | corrected mean in [35.8, 67.0] for the recorded glomeruli | 58.2 to 192.2, **2.06×** | **fails** |

H1 was registered as the gate, in these words: *"If it fails, the loss process is not
independent per-synapse thinning at the released rate, the correction is not trustworthy,
and H3 and H4 must not be read as results."* It failed. So H3 and H4 are reported and are
not results.

**H3 is worth stating plainly because it is the opposite of the intended effect.** The
correction was built to remove an incompleteness confound, and it *strengthened* it: the
naive median correlates with converging ORN count at ρ = −0.475 and the corrected mean at
ρ = −0.554. A correction that makes the confound it targets worse is wrong.

## What falsifies the model, and it is not a marginal miss

H2's inversion returning nothing for 49 of 50 glomeruli demanded an explanation rather
than a null, and the explanation is a hard bound the model cannot cross.

As `p` falls towards zero the inferred true distribution grows without bound, but the
predicted completeness falls only to the untruncated non-zero mass of the *observed*
distribution. That value is a **floor**: the lowest completeness the thinning model can
produce at any survival rate whatsoever. A measured completeness below it is not evidence
of a small `p` — it falsifies the model.

**45 of 50 glomeruli sit below the floor, with a median gap of −0.124.** The worst:

```
glomerulus   measured   model floor      gap
DM3            0.5238        0.9947   -0.4708
VL2p           0.4852        0.9203   -0.4351
DL3            0.6108        0.9907   -0.3799
DL4            0.6694        1.0000   -0.3306
VA1v           0.6615        0.9669   -0.3053
```

The gap is largest exactly where completeness is worst, and the four glomeruli the
convergence test found perfectly complete sit exactly *at* the floor, gap 0.0000.

**The reading.** The contact distribution of recovered pairs is far too heavy to account
for the number of missing pairs. If the missing pairs were the weak tail of the same
distribution, the recovered pairs would show substantial mass at one to three contacts.
Mostly they do not — per-glomerulus naive medians run from 9 to 117.5. So the pairs are
missing for a reason the contact distribution does not encode.

The convergence test already measured the candidate, and it is per-neuron rather than
per-synapse: an ORN's reached-target fraction correlates with its total out-contact budget
at r = +0.836 in VL2p and +0.847 in DA1. **An axon that was not followed loses whole
connections, not a random 58 percent of each connection's synapses.** Per-synapse thinning
and per-axon truncation are different processes and only the second can produce these
numbers.

## The volume question is now bounded, and stays unsettled

This is the one thing the exercise does settle. The two candidate correction models
bracket the volume correlation, and neither reaches significance:

| statistic | ρ vs rarefied volume | p |
|---|---|---|
| naive median (what the volume report used) | +0.070 | 0.629 |
| naive mean | +0.262 | 0.066 |
| corrected mean, thinning model | +0.209 | 0.146 |

Under per-axon truncation the recovered pairs are an unbiased sample of pairs rather than
a strength-biased one, so the appropriate estimator is `naive mean / p` — which is the
naive mean rescaled by a constant, and therefore has *exactly* the naive mean's rank
correlations. So the two models bracket the answer at ρ = +0.209 to +0.262, p = 0.066 to
0.146.

**Kazama and Wilson's release-site scaling is not supported on this connectome under
either correction model, and the reason is power rather than contamination.** The earlier
report could not say that: it left open the possibility that a correction would reveal the
effect. It will not. Fifty glomeruli, of which eleven are well reconstructed, is what
exists, and the correlation sits just outside significance under the most favourable of
the three statistics.

## And separately, one contact is not one release site

H6 was registered **expecting to fail**, with the arithmetic for glomerulus D stated in
advance, so that the discrepancy would be reported rather than absorbed. The corrected
means for the four glomeruli Kazama and Wilson recorded:

```
DL5   192.2      DM4    90.1      VM2    81.9      DM6    58.2
```

against their 51.4 ± 7.8 release sites per ORN axon per PN — a mean ratio of **2.06**.
Three of the four are outside twice their stated standard deviation.

This holds regardless of the completion rate: the estimator scales as `1/p`, so pushing
`p` to 0.50 still leaves a median corrected mean of 88.3 across the 50 glomeruli. It also
holds under the per-axon estimator, which is larger still by a factor of `1/completeness`.

So either one anatomical contact is not one vesicular release site, at a ratio of roughly
two, or the fluctuation analysis underestimates. Both sides are indirect estimates of the
same quantity and the convergence contract already recorded the identification as an
assumption. This is the first quantitative pressure on it.

## What this does not do

It corrects nothing. No previously recorded contact statistic is revised, the widened
grooming circuit's excitation/inhibition balance is not rescaled, and the volume report's
verdict of "not settleable with this measurement" stands — now with the addition that the
correction it named as the way forward does not work, and why.

**The indicated next step is a per-axon reconstruction-quality model**, not a per-synapse
one: estimate each ORN's truncation from its out-contact budget, which the convergence
test showed is predictive, and model pair presence as an axon property. That model would
predict the completeness deficits the thinning model cannot. Whether it can also correct
the contact statistic is a separate question, and the bracketing above suggests it would
not change the volume verdict.

## Sensitivity, and why it is short

The exact estimator is `total / (p * possible_pairs)`, so `p` rescales every corrected
mean by a common factor and cannot change a rank correlation at all. H3 and H4 are exactly
`p`-invariant — verified rather than asserted, and the run fails closed if a rank
correlation moves when `p` does. Only the H6 magnitude comparison depends on `p`, and it
fails across the whole registered range [0.35, 0.50].

## Caveats

1. **The negative binomial is a choice.** A different family for `k_true` would give a
   different floor. But the floor is `1 − q_Y^r` where both parameters are fitted to the
   observed counts, and the argument behind it is family-independent: the observed counts
   carry little mass at one to three contacts, so independent per-synapse thinning cannot
   have removed many whole pairs. The family sharpens the argument rather than creating it.
2. **`p = 0.42` is a whole-dataset figure.** The olfactory system may not be sampled at the
   dataset average. H2 was the test of that and it could not run, because the inversion is
   undefined below the floor. So the completion rate remains undisclosed-by-the-source and
   unchecked internally.
3. **Complete convergence is assumed for the denominator.** It is the Kazama and Wilson
   result the convergence test confirmed exactly in every glomerulus well enough
   reconstructed to test it, but it is an assumption in the glomeruli that are not.
4. **H4 and H6 were not blind** and both say so in the artifact. H4 was informed by the
   volume report's stratified analysis; H6 was informed by glomerulus D, computed while
   writing the contract, which is why it was registered as an expected failure.
