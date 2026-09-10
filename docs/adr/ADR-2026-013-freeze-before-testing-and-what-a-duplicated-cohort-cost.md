# ADR-2026-013 — Fit on spent data, freeze before testing, and what a duplicated cohort cost

Date: 2026-09-10
Status: accepted
Assumption set: `foundation-v0.7` → `foundation-v0.8`
Supersedes nothing. Amends ADR-2026-012 (third amendment, recorded there).

## Context

On 2026-09-09 the registered ND-06 v0.1 rule — a depression-only Tsodyks–Markram synapse
carrying Nagel, Hong and Wilson's published utilisation of 0.22 and recovery constant of
893 ms — was scored against Rozenfeld and colleagues' wild-type paired-pulse measurements
and failed structurally. `PPR = 1 − U·exp(−Δt/τ)` is bounded above by one and increases
with interval at every parameter setting; the measurements exceed one at three of five
intervals and decrease throughout. No refit could repair it.

That left the project in a position worth stating plainly. Every quantitative dynamical
claim it had ever made had failed: the cellular tier at 1.064 against a required value
below 1.0, the kinetics leg retired for want of unitary waveforms, the circuit readout
silent, and now the synaptic rule refuted on the one observable it had been tested
against. V0 Structural remained the only supported tier. And the reason was becoming
visible: the project had only ever *inherited* parameters from other laboratories' fits
and then tested them. It had never fitted anything itself and then tested the fit.

## Decision 1 — Fit on spent data, and only on spent data

The Fig3D wild-type arrays were opened and scored on 2026-09-09. That expenditure is
irreversible: they can never again function as a holdout for anything. Using them as
training data costs nothing that has not already been spent, and refusing to use them
would have left the failure undiagnosed while protecting nothing.

So `stage2-stp-family-selection-v1` fits on those five cohort means and nothing else. It
awards no tier and cannot: a fit to the only data it is scored against is the definition
of no test. What it produces is a frozen model, and the test is a separate contract
against cohorts that were still sealed.

This is a change of practice, not of standards. The rule that a fit awards no validation
is kept exactly. What changes is that a parameter may now be *earned* by fitting on spent
data and then surviving a holdout, rather than only inherited from someone else's fit.

## Decision 2 — Seven families, and what they refuted

Every candidate is a standard mechanism from the synaptic-physiology literature, and each
is implemented as a state machine over a spike train rather than a closed form — because
the recorded protocol is twenty pairs at 0.2 Hz and the ratio the authors report is the
mean second response over the mean first across those twenty. At 1000 ms that correction
is 0.028 in ratio units, larger than that cohort's own standard error. A closed form
would have had to assume it away.

| family | k | weighted SSE | df | p | inside all 5 | eligible |
|---|---|---|---|---|---|---|
| depletion alone (v0.1's form) | 2 | 123.6 | 3 | 3e-27 | 1 of 5 | no |
| textbook Tsodyks–Markram | 3 | 16.8 | 2 | 0.0002 | 4 of 5 | no |
| published depression + facilitation | 2 | 17.6 | 3 | 0.0005 | 4 of 5 | no |
| release-probability facilitation over depletion | 4 | 6.24 | 1 | 0.013 | 5 of 5 | **yes** |
| two parallel release components | 4 | 6.27 | 1 | 0.012 | 5 of 5 | no (E2) |
| two-timescale facilitation, fast τ pinned | 4 | **0.017** | 1 | **0.90** | 5 of 5 | no (E3) |
| two-timescale facilitation, fast τ fitted | 5 | 0.000 | 0 | — | 5 of 5 | **yes** |

Three things were refuted along the way, and the second is the one that matters.

**The textbook form cannot facilitate enough.** Tying the facilitation step to the resting
release probability — the standard `u ← u + U(1−u)` — caps the paired-pulse ratio at 1.5.
The measured 10 ms cohort mean is 1.5139. The ceiling is real, it is proved in the test
suite over random parameters, and it is what excludes the family.

**The minimal repair fails, so yesterday's diagnosis was half right.** Keeping Nagel's
0.22 and 893 ms exactly as v0.1 registers them and adding only the missing facilitation
caps the ratio at 1.388, again below the measured 1.5139, and misses the 10 ms interval by
3.1 standard errors. The 2026-09-09 record said the diagnosis was "a missing facilitation
mechanism, not a wrong depression mechanism". The mechanism was indeed missing — and the
published parameters are also wrong for this synapse as these recordings measure it. That
correction is now in the v0.2 registry's `supersedes` block.

**One facilitation timescale is not enough.** Subtracting the plateau from the cohort
means leaves an excess whose implied decay constant is 21 ms between the 10 and 30 ms
intervals and 83 ms between the 30 and 100 ms intervals. A single exponential forced
through the 10 and 100 ms points misses the 30 ms point by 3.3 standard errors. That is a
statement about the data, not about any model, and it is asserted in a test rather than in
prose.

## Decision 3 — Eligibility is about falsifiability, not about parameters

The first draft of the fit contract gated eligibility on parameter-level identifiability:
each free parameter had to be recovered when the family refitted data it generated itself.
That was a design error and the contract preserves it verbatim together with what it would
have decided, because replacing it silently would have been indistinguishable from moving
a threshold to suit an outcome.

The error is that parameter identifiability answers whether a fitted number may be
*reported as a measurement*. Eligibility for freezing has to answer whether the frozen
*prediction* can be refuted. Those are different questions, and a model can have
thoroughly unidentifiable parameters and a perfectly sharp predicted curve — which is the
ordinary condition of a mechanistic model fitted to a few summary statistics. Under the
superseded screen exactly one family was eligible, by a margin of 0.005 on a single
statistic, and the family that fits the curve with p = 0.90 was excluded.

The three screens that replaced it:

- **E1** — the fitted curve must lie inside the fit set's own 95 % interval at all five
  intervals. Not four of five: two candidates fail precisely by missing 10 ms by more than
  three standard errors while sitting comfortably inside the other four.
- **E2** — the bootstrap 95 % band on the frozen prediction must be no wider at any
  interval than the fit set's own interval there. A curve blurrier than the data cannot be
  refuted by more data of the same kind, and freezing one is a way of arranging never to
  be wrong. This screen has no threshold of its own; it scales to the data. It is the only
  screen a family can fail while fitting perfectly, and the parallel two-component family
  did fail it, at 10 ms (band 0.124 against data 0.116) and 30 ms (0.123 against 0.105).
- **E3** — any constant a family pins rather than fits must be refitted across a declared
  sweep and leave the five predictions within 0.01. This excluded the best-fitting family
  in the table: pinning its fast facilitation constant at 5 ms gives p = 0.90, but pinning
  it at 1 ms instead moves the predictions by 0.078. The constant was doing work, so it
  had to be fitted. Its five-parameter variant, where it is, became the primary.

Parameter identifiability is still measured for every family and still reported. It now
decides which numbers may be called measurements. Of the primary rule's five parameters,
**none** survives recovery; of the secondary's four, two do. The registry carries the two
lists separately so nothing here can be quoted as a measured synaptic property.

## Decision 4 — Freeze two, and let an unseen cohort choose

The fit set cannot choose between a four-parameter and a five-parameter account of five
cohort means. On data the five-parameter family generates it wins 99 times in 100; on data
the four-parameter family generates the five-parameter one still wins, because it nests
it. That asymmetry is exactly what nesting predicts and it means the fit set is not an
arbiter. Both were frozen, with their parameters and their five predictions written into
the holdout contract numerically, pinned to the fit artifact by checksum, and the scorer
re-derives each curve from its parameters and refuses to run if the two disagree.

A one-parameter flat constant was frozen alongside them. A model that cannot beat a
horizontal line on unseen animals has not been tested by them.

## Decision 5 — An independent tension worth recording: the release probability

Every family that could reproduce this paired-pulse curve needed an effective first-pulse
utilisation between 0.07 and 0.13. Kazama and Wilson measured a release probability of
0.79 ± 0.02 at this synapse by multiple-probability fluctuation analysis, uniform across
glomeruli. That is a factor of six to eleven.

It is not a clean contradiction: mapping a fitted utilisation onto a per-site release
probability needs one vesicle per site and no within-pair recovery, which the v0.1
registry already records as the reason the variance-derived value was not adopted. But it
is a large unexplained gap and it is now recorded in the registry rather than left out. A
synapse releasing with probability 0.79 should barely facilitate at all, and these
recordings facilitate by fifty per cent at 10 ms. Something in that pair of statements is
wrong and this project has not established which.

## Decision 6 — The holdout is void, and the verdict is NO VERDICT

The holdout ran clean at `c7f45bf` from a detached worktree, byte-verified, and returned
PASSED. **The verdict does not stand.**

Fig3J's five wild-type arrays are element-wise identical to Fig3D's: same values, same
order, same animal counts of 20, 21, 22, 22, 22, maximum absolute difference exactly zero
at every interval, matching digests of the stored element bytes. The authors compared
their 1-day-old `cac^RNAi` cohort against the same wild-type reference they used for the
2-to-4-day comparison, and the repository ships that reference in both figure files.
Nothing improper on their side — the RNAi cohorts do differ, 28 animals against 22. Only
the wild-type control is shared.

It was discoverable before the run and from the published legends alone. Figure 3D gives
wild-type n = 20 (10 ms), 21 (30 ms), 22 (100, 300, 1000 ms). Figure 3J gives wild-type
n = 20 (10 ms), 21 (30 ms), 22 (100, 300, 1000 ms). Identical at every interval. Both
lines are recorded side by side in the fit contract's own independence audit. The
coincidence was noticed and not acted on, because Fig3H differs at three of five intervals
and the pattern looked like ordinary cohort variation. Identical counts at five
independent intervals is not cohort variation; it is the same cohort.

**So the experiment returns NO VERDICT — not PASSED and not FAILED.** It was not run. A
void cohort produces no evidence either way. The immutable artifact is left exactly as
written, with its PASSED field intact, and the contract's execution record supersedes it;
any citation of one must cite the other.

**Promoting the secondary cohort is forbidden.** Fig3H was registered as secondary and
declared in advance not to enter the verdict. Promoting it now because the primary turned
out void would be exactly the criterion restatement the contract forbids in its own
acceptance section, and the project has a standing rule against restating a failed
criterion.

### What survives, stated at its real weight

Fig3H, day 0, is a genuine unseen cohort. Its registered results stand where they were
registered:

| criterion | verdict | detail |
|---|---|---|
| A1 — prediction inside the measurement error | **NO VERDICT** | the frozen curve does land inside all five intervals, but the 10 and 30 ms half-widths are 0.19 and 0.17 against a registered 0.15 power limit, leaving three scorable against a registered minimum of four |
| A2 — better than a frozen constant | **PASSED** | weighted residual 1.493 against the constant's 38.612 on 21 unseen animals, a factor of 26 against a registered requirement of 2 |
| A3 — shape | PASSED | 4 of 4 adjacent directions, and the constant passes it too |

A2 is the one substantive registered result the whole exercise produced, and it is real:
a model frozen with its numbers written down beat a frozen null on animals it had not
seen, under a criterion fixed in advance. It is also the first time anything in this
project has done that. It is not a validation tier and the registry says so.

The two frozen rules are **not** separated. The four-parameter one does marginally better
on the genuine cohort, 1.279 against 1.493 — the opposite direction from the fit set,
where the two-timescale family won by a factor of hundreds. The curves differ by up to
0.075 at 100 ms, above the registered 0.02 separability limit, but that cohort's 100 ms
half-width is 0.12. One cohort this size cannot tell them apart and neither may be
preferred.

## Decision 7 — The structural fix, and the pattern it does not fix

`flysim.reservations.duplicate_arrays` compares digests of the stored element bytes of
named arrays across two MAT files, decoding nothing, and `flysim.stp_holdout` now refuses
to open any cohort that duplicates a spent one before a byte of payload is read. Run
against this case it flags all five Fig3J arrays and clears all five Fig3H arrays; both
assertions are in the test suite against the real files.

Equal stored bytes prove equal data, which is the direction a guard needs: a match
refuses. The converse does not hold, so a clean result is a screen and not a certificate
of independence. The other half of the protection is reading the published animal counts
and acting on them, and that half is not automatable.

**The pattern this does not fix.** This is the third instance in two days of inferring
something that was cheap to check:

1. the preparation inferred from a plotting label instead of read from the methods;
2. a join size inferred from a file's row count instead of measured on its column;
3. a cohort's independence inferred from a legend's prose instead of checked against its
   own numbers.

All three were cheap. None was checked. All three unchecked readings favoured the project.
Two automated guards have been added since — the byte-level worktree audit and this
duplicate-array check — and they address the mechanisms, one each. They do not address the
habit, and recording the habit is the only thing available here that might.

## What is not decided here

- **No tier.** V0 Structural remains the only supported tier. The Stage 2 gate stays at v4
  and 0 of 3; the retired synaptic leg stays retired, because it needs unitary waveforms
  this repository does not ship.
- **Edge sign.** ND-10 is untouched and stays unresolved wherever receptor evidence is
  absent.
- **Which of the two frozen rules is right.** Unresolved, and not resolvable on the
  evidence now in hand.
- **Whether either rule predicts anything but a paired-pulse ratio.** Neither has been
  wired into a circuit runner, and that work should wait.

## Consequences

The trains in `Figure 3/Fig3E_and_F.mat` — 1, 10, 20 and 60 Hz over 32 to 112 pulses in 18
animals — are now the **only** unspent wild-type ORN-to-PN holdout in the corpus. That
raises rather than lowers the standard for the contract that opens them, and it makes them
the decisive next experiment on every count that matters:

- they measure the resource recovery constant, which the paired-pulse protocol cannot
  identify at all — every family drove it to its bound, and the 300 and 1000 ms cohort
  means differ by 0.0003 against a pooled standard error of 0.0277;
- the two candidates make sharply different and bounded train predictions — a
  second-to-first ratio of 1.026 against 0.951 at 10 Hz, with the peak at a different
  pulse — so the trains discriminate between them (an earlier version of this line claimed
  they would diverge in a long train, which is false; see the fourth amendment);
- the additive and multiplicative accounts differ by a term invisible on a paired-pulse
  curve that compounds across a train;
- and the fast facilitation component, which the paired-pulse curve sees only at its 10 ms
  point, is sampled repeatedly by a 60 Hz train whose interval is 16.7 ms.

Before that contract is written, the duplicate-array guard must be run against those
arrays and Fig3B's, and the published animal counts compared. Eighteen animals appear in
every train array in the file, at every frequency, which is itself a pattern worth
checking rather than assuming.

## Addendum, 2026-09-10 — the audit that should have come first, run across all of Figure 3

Decision 7 said the guard must be run against the train arrays before the contract that
opens them is written. Deferring that would have been the fourth instance of the pattern
this ADR records, so it was run immediately. It is in
`configs/datasets/stage2-reservations-v1.json` under `known_duplications_audited_2026_09_10`.

**A second identical pair, in a different observable.** `Fig3B.mat`'s
`all_flies_1Hz_control` is bit-identical to `Fig3I.mat`'s. Figure 3B is the 2-to-4-day
wild-type absolute amplitude and Figure 3I is the 1-day one, and the legends give both
n = 17. Same reuse, different quantity.

So the pattern is systematic and it can be stated in one line: **the day-1 wild-type
controls in this repository are reused copies of the 2-to-4-day wild-type controls, and
the day-0 wild-type controls are genuinely separate recordings.** That holds in both
places it can be checked — the paired-pulse arrays (3D/3J against 3D/3H) and the amplitude
arrays (3B/3I against 3B/3G). It is not misconduct; the authors compared each perturbation
cohort against a wild-type reference and reused that reference for the day-1 comparison.
It does mean the repository ships fewer independent wild-type cohorts than its figure count
suggests, and that is now recorded where the next contract will read it.

**The trains are clean.** All 24 arrays in `Fig3E_and_F.mat` are stored distinctly: no
train duplicates another, no latency or jitter array duplicates a train, and the 1 Hz
arrays there are distinct from `Fig3B.mat`'s despite sharing both variable names — so
opening the trains does not spend the amplitude file or the reverse. The wild-type trains
at 1, 10, 20 and 60 Hz survive as a genuine unspent holdout, and they are the only one
left for this synapse.

**What the digest audit still cannot do.** It catches reuse of the same stored bytes. It
cannot catch two files holding the same animals recorded twice, and it cannot catch a
legend that misdescribes a cohort. Every train array reports 18 animals at every frequency;
the digests confirm 24 distinct arrays, and the counts should still be reconciled against
the paper's stated n before those arrays are scored. That part is not automatable and
saying so is the point of this addendum.

## Fourth amendment, 2026-09-10 — a false structural claim, and the bound that replaces it

This ADR asserted, in Decision 2's table commentary and again in Consequences, that both
frozen candidates "carry additive, unbounded facilitation, so they diverge in a long
train", and used that to argue a 60 Hz train "would show it immediately". **It is false.**
Computed rather than asserted:

```
model            Hz pulses   A2/A1   A3/A1  peak@  peak   last/A1
primary  M4f      1     32   0.903   0.819      1  1.000    0.339
primary  M4f     10    100   1.026   0.970      2  1.026    0.058
primary  M4f     20    100   1.097   1.099      3  1.099    0.039
primary  M4f     60    112   1.303   1.389      4  1.407    0.027
secondary M1      1     32   0.924   0.857      1  1.000    0.399
secondary M1     10    100   0.951   0.874      1  1.000    0.059
secondary M1     20    100   1.075   1.001      2  1.075    0.030
secondary M1     60    112   1.375   1.427      3  1.427    0.010
```

The facilitation has no ceiling of its own, but it *multiplies* a depleting resource that
falls to one to three per cent by the end of a long train, so the product peaks near 1.4
within the first few pulses and collapses. The claim was made by reasoning about the
facilitation term in isolation. That is the fourth instance of the pattern this ADR
records, and the correction is now asserted in the test suite rather than in prose.

**It improves the case for the train experiment rather than weakening it.** The two
candidates make finite, well-behaved and sharply different predictions: the second-to-first
ratio at 10 Hz is 1.026 against 0.951, the peak sits at pulse 2 for one and pulse 1 for the
other, and the 1 Hz steady states are 0.339 against 0.399 — that last pair being the direct
test of the recovery constant the paired-pulse protocol cannot measure. The trains are a
discrimination experiment, not an expected refutation.

## Fifth amendment, 2026-09-10 — the measured release probability is incompatible with the measured facilitation

Decision 5 recorded a "factor of six to eleven" tension between the fitted first-pulse
utilisations and Kazama and Wilson's measured release probability, and called it "a large
unexplained gap". That undersells it. The relation is structural and it can be stated as a
bound.

Take one homogeneous pool of release sites, each holding at most one vesicle, each
releasing with probability `p` at rest. Let the second pulse release with any probability
up to one — that is, grant facilitation everything it could possibly ask for — and let a
site that released be unavailable until it recovers. Then

```
R1 = N p1 q,   R2 = N p2 (1 − p1 e^{−Δt/τ}) q
PPR = (p2/p1)(1 − p1 e^{−Δt/τ})  ≤  (1 − p e^{−Δt/τ}) / p
```

| | at p = 0.79 | required by the data |
|---|---|---|
| ceiling on PPR at 10 ms | **0.277** | measured **1.5139** |
| largest p compatible with the measured ratio | | **0.400** (0.419 at the CI's generous end) |
| same, at a 20000 ms recovery constant | 0.266 | 0.398 |

So a single homogeneous pool at the measured release probability cannot produce a
paired-pulse ratio above about 0.28 at 10 ms, against a measured 1.51 — short by a factor
of five and a half — and **no facilitation mechanism closes the gap**, because the bound
already allows facilitation to certainty. Read the other way, the measured ratio caps the
resting release probability below 0.40 whatever else is assumed. Neither statement depends
on the pinned recovery constant.

**At least one of three things is false:** that the resting release probability at this
synapse is near 0.79; that the Rozenfeld paired-pulse ratios measure the same quantity at
the same synapse; or that a single homogeneous pool describes it.

**The third was offered here as the leading candidate, on the argument that a
heterogeneous population facilitates because the first pulse preferentially depletes the
high-probability sites. That argument is wrong and is withdrawn by the seventh amendment
below: heterogeneity makes paired-pulse depression worse, and the bound holds over any
distribution of per-site probabilities with the mean alone.** What survives is set out
there.

**The escape hatch, named so it cannot be produced later.** Postsynaptic saturation raises
a measured paired-pulse ratio, so if these recordings saturate, the true presynaptic ratio
is below 1.5139 and the bound is less badly violated. `VAL-02` records that mechanism. It
is weak here because minimal stimulation is designed to stay off the saturating part of the
curve, established on 2026-09-09, but it is not zero, and it is the only route by which a
release probability near 0.79 survives.

The bound and its inverse are `flysim.stp_families.single_pool_paired_pulse_ceiling` and
`maximum_single_pool_release_probability`, both asserted in the test suite.

## Sixth amendment, 2026-09-10 — three pieces of language that overstated their evidence

**The goodness-of-fit statistic.** Decision 2's table prints p = 0.90 for the pinned
two-timescale family and the prose called it "the best-fitting family". With one residual
degree of freedom a p that large says the residual is *smaller* than chance would give,
which is the signature of over-parameterisation, not of a validated model; and the primary
candidate has no p at all, having zero residual degrees of freedom. Neither a saturated nor
a near-saturated fit validates a mechanism. The p-values are reported so the fit can be
audited and for nothing else, and the registry now says so at every place one appears.

**The A2 margin.** Decision 6's table gives the frozen model's weighted residual as 1.493
against the frozen constant's 38.612 and calls the factor of 26 "the one substantive
registered result". The result stands; the margin should never be quoted without its null.
That constant sits at 0.9785 while the day-0 cohort means span 0.92 to 1.46, so any curve
with roughly the right shape beats it comfortably. The factor of 26 measures how much
structure the data have, not how good the model is. What the result establishes is narrower
and still worth having: a model frozen beforehand outperformed a null frozen beforehand on
unseen animals, under a criterion fixed in advance.

**The file name.** `short-term-plasticity-v0.2` implied a successor registry that had
replaced v0.1. It has not; v0.1 is refuted and its candidates are unvalidated, so the
project's honest position is an empty slot rather than a succession. The registry id is now
`male-cns-orn-pn-stp-candidates-v0.2` and the file states in its first field that nothing
in it may be used as the ORN-to-PN plasticity rule in a simulation.

## Seventh amendment, 2026-09-10 — the heterogeneity resolution is wrong, and the bound is more general than it was stated to be

The fifth amendment, committed an hour before this one, offered site heterogeneity as the
leading resolution of the incompatibility and said "a heterogeneous population facilitates
on a paired pulse with no change in per-site probability, because the first pulse
preferentially depletes the high-probability sites and the survivors are the
low-probability ones."

**That is backwards, and it is the fifth instance of the pattern — written into the very
commit that documented the fourth.**

The survivors do carry the second response, and they carry *less* of it, because the sites
removed were the ones contributing most. With no facilitation, a pool with any distribution
of release probabilities gives

```
PPR = 1 − c·E[p²]/E[p] = 1 − c·(E[p] + Var[p]/E[p])
```

which is strictly *below* the homogeneous `1 − c·E[p]` whenever the variance is positive.
Simulated site by site rather than argued:

| pool, all with E[p] = 0.79 | PPR, no facilitation | PPR, facilitation to certainty |
|---|---|---|
| homogeneous 0.79 | 0.2188 | 0.2770 |
| bimodal 0.95 / 0.63 | 0.1868 | 0.2770 |
| extreme 1.0 / 0.58 | 0.1636 | 0.2770 |

**And the bound is more general than the fifth amendment claimed.** It does not need the
sites to be identical: `R1 = N·E[p]·q` and `R2 ≤ N·(1 − E[p]·c)·q`, so the ceiling is
`(1 − E[p]·c)/E[p]` with the mean alone — the spread cancels exactly, which the right-hand
column above shows. Heterogeneity is therefore *eliminated* as a resolution rather than
being the leading one. That makes the incompatibility stronger, not weaker.

**What actually survives**, now that a whole class of explanations is closed:

1. **The mean release probability is not 0.79 here.** MPFA assumes a uniform release
   probability and heterogeneity is a known source of bias in it — so heterogeneity stays
   relevant, as a reason to distrust the number rather than as a mechanism. The direction
   of that bias must be checked against the method literature and not assumed; this ADR has
   already been burned twice this session by assuming a direction.
2. **The two measurements are of different things.** Kazama and Wilson stimulated the
   antennal nerve at 0.033 Hz; Rozenfeld and colleagues used minimal stimulation of ORN
   axons at 0.2 Hz through `GH146-QF`, which labels about 60 % of projection neurons across
   an unstated mixture of glomeruli.
3. **One vesicle per site fails** — multivesicular release, or recruitment of sites not
   available on the first pulse. This is the only surviving presynaptic *mechanism*,
   because it is the assumption the bound actually needs, and it is the one to design an
   experiment against.
4. **Postsynaptic saturation**, already recorded in `VAL-02` and weak under minimal
   stimulation.

**What this withdraws.** The fifth amendment's closing claim that the excluded
parallel-release-components family was "the mechanistically indicated one" because it
encodes heterogeneity. It is withdrawn. That family's facilitating component works because
it facilitates, not because the pool is mixed. Its standing is exactly what E2 said: a band
wider than the data at 10 and 30 ms, which is a statement about the power of five summary
statistics and nothing more.

**On the pattern.** Four of the five instances were about data — a plotting label, a row
count, a figure legend. The fourth and fifth are about mathematics: reasoning about one
term of an expression while forgetting what multiplies it, and then reasoning about which
sites survive while forgetting which sites mattered. Both were one simulation away from
being caught, and in both cases the wrong version was the one that made the project's
position look better — here, by offering a tidy resolution to an inconvenient
incompatibility. The rule has to extend past data checks to any claim about a model's
behaviour: simulate it before writing it down.

## Eighth amendment, 2026-09-10 — the trains are latencies, and the corpus has no amplitude holdout

The train discrimination experiment was preregistered, frozen, committed and run. It
returned FAILED, with all three mechanistic models scoring about a quarter of a million in
summed weighted error against a flat line's 8,218. **That verdict is void, and no candidate
is refuted by it.**

`all_flies_<f>_control` in `Fig3E_and_F.mat` holds **per-pulse evoked-EPSC latency in
sample units**, not amplitude. The row mean of each array is exactly the matching
`mean_rise_time_<f>_control`:

| frequency | row mean ÷ mean_rise_time | spread across 17 animals |
|---|---|---|
| 1 Hz | **20.000000** | 0 |
| 10 Hz | **20.000000** | 0 |
| 20 Hz | **20.000000** | 0 |
| 60 Hz | **5.000000** | 0 |

Those are the sampling rates in samples per millisecond. Converted, the first animal's
latencies are 3.92, 4.08, 4.31 and 4.30 ms across the four frequencies — the right
magnitude for a synaptic latency, and increasing with stimulation frequency exactly as the
paper reports for Figure 3E. The file is named for Figures 3E and 3F, which are latency and
jitter, and all 24 of its arrays are latency quantities.

**It was visible in the opened data before any score was read.**

1. The values are **positive**. Genuine evoked currents in this repository are negative —
   `Fig3B`'s wild-type array has a mean of −36 pA.
2. The first column is **frequency-dependent**: 68.7, 68.0, 71.9, 18.1. A pulse delivered
   from rest cannot depend on the frequency of the train that follows it.
3. There is **no depression anywhere** — 1.02 at pulse 112 of a 60 Hz train. No chemical
   synapse does that, and this paper's own paired-pulse data show 0.93 by 300 ms.
4. The non-finite entries are scattered and non-monotone, which is what undetected
   responses look like and not what a decaying amplitude series looks like.

**The check that would have caught it was not registered.** The first column must be
frequency-independent. One line, no external information, and it falsifies the amplitude
reading outright. The contract registered an animal-count reconciliation and did not
register this. Every future observation model must state at least one internal consistency
check the data can fail on their own terms.

**Where it originated.** The intake and reservation manifest of 2026-09-09, which called
the file "per-animal evoked-EPSC amplitude across trains at 1, 10, 20 and 60 Hz". Inferred
from the variable names, never checked against the values or against the figure the file is
named for. This is the **sixth** instance of the session's pattern and chronologically the
**first** — it was written before all the others and propagated into this ADR, STATUS, the
Stage 2 tier document, both holdout contracts and the train contract, every one of which
called the trains the decisive next experiment.

**Every guard built after the previous failure ran and was clean.** The duplicate-array
check passed correctly, the manifest checksum matched, the frozen trajectories re-derived
from their parameters. None of them could have caught this, because they all check
provenance and identity rather than whether the quantity is the quantity. That is a gap in
the guard set and it is now named.

**What it cost: nothing spendable.** Four per-pulse latency arrays were opened. The
reservation contract already recorded the latency arrays as reserved but never scoreable,
because no registered model generates a latency. They could not have been a holdout for
anything. That is luck rather than design and it is recorded as luck.

### The real position this exposes

**There is no unspent wild-type ORN→PN amplitude holdout in this corpus, and there never
was one.** What Rozenfeld and colleagues' repository actually offers for this synapse:

| observable | files | status |
|---|---|---|
| per-animal mean evoked amplitude at 1 Hz | Fig3B, Fig3G, Fig3I | Fig3B ≡ Fig3I bit-identical; ND-04 carries no absolute conductance scale to score any of them |
| paired-pulse ratios | Fig3D, Fig3H, Fig3J | Fig3D ≡ Fig3J bit-identical; D and H both spent |
| per-pulse latency and jitter | Fig3E_and_F | no registered model generates a latency |
| miniature EPSCs | Fig5B | no quantal amplitude or spontaneous rate registered |
| Bruchpilot puncta | Fig5D | needs its own contract; puncta and contacts are not the same unit |

**No train amplitude series exists anywhere in it.** So the resource recovery constant
cannot be measured from this corpus by anyone. The candidates' pinned constant is
*unmeasurable* from the available data rather than merely unmeasured, and the plan to
settle it with the trains — stated in this ADR's Consequences, in STATUS, in the tier
document and in two contracts — was built on a mis-read header.

**Advancing the ORN→PN synaptic tier now requires a different dataset, not a different
contract.** That is the honest deliverable of this session's second half, and it is worth
more than a fourth negative result would have been: it says where the work is, and it says
it is not here.

## Ninth amendment, 2026-09-10 — the corpus claim, checked across the whole repository and then qualified

The eighth amendment asserted that "no train amplitude series exists anywhere in it" after
examining one figure directory. That is the same shape as the six errors this ADR already
records, so it was checked: `read_mat_structure` over every MAT file in the repository,
variable names and shapes only, no payload decoded, nothing spent.

**The claim survives, for 61 of 66 files.** Across every readable file the only per-pulse
arrays over a stimulation train are `Fig3E_and_F`'s latencies and the 32-column arrays of
`Fig3B`, `Fig3G` and `Fig3I` — the 32 eEPSCs evoked at 1 Hz that the methods say were
averaged to give one amplitude per animal. Everything else wide is odour-evoked calcium or
spiking population data, raw whole-cell traces, or behaviour.

**Five files could not be read**, and the claim is therefore about 61 of 66 files and not
about the repository:

| file | why |
|---|---|
| `Figure 1/Fig1D.mat` | MATLAB v7.3, an HDF5 container the header-only reader declines to parse |
| `Figure S4/FigS4A.mat` | MATLAB v7.3 |
| `Figure S8/FigS8E.mat` | MATLAB v7.3 |
| `Figure 8/Fig8B.mat` | **v5 container the project's own reader cannot parse** |
| `Figure S13/FigS13.mat` | same |

Four of the five belong to odour-response or behaviour figures, where an evoked-amplitude
train series would be out of place. "Would be out of place" is an inference of exactly the
kind that produced the six recorded errors, so it is recorded as an open question rather
than as a conclusion.

**The last two are a defect in this project's reader, not in the data.** `Fig8B` and
`FigS13` are version 5 containers that `read_mat_structure` fails on at the dimensions
subelement — most likely a variable class it does not handle, such as a cell array or a
struct. It is recorded rather than fixed, because no current contract needs it and because
an unrecorded reader limitation is precisely how a corpus comes to be described from the
files that happened to open.

The audit also confirmed that `Fig3G`'s wild-type 1 Hz array carries 20 animals against
`Fig3B`'s and `Fig3I`'s 17, matching the published legends and consistent with the recorded
finding that `Fig3B` and `Fig3I` are bit-identical while `Fig3G` is a separate day-0
recording.

## Tenth amendment, 2026-09-10 - both candidates are refuted, and no new data was needed

The ninth amendment closed with the position that advancing this synapse required a
different dataset. **That was wrong**, and the check that shows it was available the whole
time, in this project's own registry.

`ND-06 v0.1` records Kazama and Wilson's measurement as the external test the
depression-only rule failed: *"At frequencies mimicking the basal firing rate of a typical
ORN (7 Hz), synaptic responses depress by about 40% but remain relatively strong"* - a
steady state of about **0.60**. The v0.2 candidates were fitted to Rozenfeld paired-pulse
ratios and were never fitted to that number. Their predictions for it follow
deterministically from parameters frozen and committed at `c7f45bf`, before this check was
conceived, which is checkable in git.

| model | 7 Hz | 10 Hz | 20 Hz | 60 Hz |
|---|---|---|---|---|
| candidate A, two-timescale facilitation | **0.074** | 0.058 | 0.039 | 0.027 |
| candidate B, facilitation + depression | **0.082** | 0.059 | 0.030 | 0.010 |
| ND-06 v0.1, the refuted predecessor | **0.441** | 0.350 | 0.208 | 0.079 |
| **measured (Kazama & Wilson, 7 Hz)** | **~0.60** | | | |

**Both candidates are refuted.** They predict about eight times too much depression, and
the rule they were built to replace is six times closer to the measurement.

**Why, and what it demonstrates.** The paired-pulse curve cannot constrain the resource
recovery constant - the 300 ms and 1000 ms cohort means differ by 0.0003 against a pooled
standard error of 0.0277 - so every family drove that constant to the top of its box. A
constant of 20000 ms means essentially no recovery between pulses. Across a single 1000 ms
pair that is harmless and invisible; across a sustained train the resource never refills
and the response collapses to a few per cent.

So the demonstration this session was asked for is precise, and it is about the
**observable** rather than the mechanism: *a short-term-plasticity rule fitted to
paired-pulse ratios alone cannot be a usable rule, because the parameter that dominates its
behaviour in any sustained train is exactly the parameter that observable cannot see.* That
is why the fit looked excellent, why the identifiability check flagged every parameter as
unrecoverable, and why the candidates nonetheless fail by a factor of eight the moment a
train is asked of them. The three findings are one finding.

**What it does not show.** It does not restore v0.1, which stays refuted on paired pulses
for reasons no parameter can repair: its ratios cannot exceed one and cannot decrease with
interval. The honest position is that v0.1 is refuted on paired pulses, both successors are
refuted on sustained trains, and **no registered rule survives both observables**. It also
identifies no correct mechanism; it rules two out.

**This is not a preregistered holdout test and is not presented as one.** The target was
known when the check was conceived. Its value rests entirely on the parameters having been
frozen and committed first, with the predictions following deterministically - and that
much is verifiable rather than asserted.

**The concrete next experiment, corrected.** Not procurement. A successor must be
constrained by a sustained-train observable *at fit time*, not merely tested against one
afterwards. Kazama and Wilson's 7 Hz value and Nagel, Hong and Wilson's 10 Hz trajectory
are both published, both already in the corpus, and neither is a holdout this project could
otherwise spend. Fitting a family jointly to the Rozenfeld paired-pulse curve and to at
least one train constraint is the next contract, and it needs no data the project does not
already hold. The release-probability incompatibility remains open and is untouched by any
of this.

## Eleventh amendment, 2026-09-10 - the first passed dynamical validation

Everything above is prologue to this. The joint fit was run, two families survived, one
was frozen as primary under a rule committed beforehand, and it was scored once against a
day-0 1 Hz train cohort that had never been decoded. **It passed both registered
criteria.**

| | result |
|---|---|
| **J1** prediction inside the measurement error | **PASSED** - 31 of 31 scorable pulses inside 1.96 standard errors, a fraction of 1.000 against the registered 0.80 |
| **J2** beats the refuted predecessor | **PASSED** - weighted error 13.41 against ND-06 v0.1's 139.32, a ratio of 0.096 against a limit of 0.5 |
| J3 steady state | observed 0.555; primary predicts 0.643, secondary 0.650, v0.1 0.904 |
| J4 the two frozen models | 13.41 against 14.60 on 31 pulses - separates nothing |

**Why this one worked when the others did not.** Every earlier candidate was fitted to a
paired-pulse curve alone, and that observable cannot constrain the resource recovery
constant: the 300 ms and 1000 ms cohort means differ by 0.0003 against a pooled standard
error of 0.0277. Every family duly drove the constant to its bound, which is invisible
across a single pair and catastrophic across a train. Adding a 32-pulse 1 Hz trajectory to
the objective fixes it: the constant comes out at 7096 ms, interior to its box, and the
fits gain 32 residual degrees of freedom with goodness-of-fit p values near 0.78. The
previous primary had zero residual degrees of freedom and no p at all.

**The guards, each answering a failure this session actually had.**

| guard | what it established | which failure it answers |
|---|---|---|
| manifest checksum | the bytes scored are the bytes reserved | the dirty-tree artifacts of 2026-09-08 |
| duplicate-array digest | Fig3G duplicates none of Fig3D, Fig3B, Fig3H | the bit-identical holdout of this morning |
| trajectory re-derivation | every pulse recomputed from frozen parameters to 1e-6 | a simulator moving under a freeze |
| **internal consistency check** | first pulse 49.72 pA against the fit set's 50.43, ratio 0.986 | **the latency arrays scored as amplitudes** |
| degeneracy check on J1 | v0.1 lands inside at only 0.581, below 0.80 | a criterion that passes everything |

The fourth is the one that matters most, and it is the first contract in this project to
carry a check the data can fail on their own terms. The fifth is what makes J1 mean
something: had the null also passed it, the registered fallback would have put the verdict
on J2 alone.

**What it establishes.** That a short-term-plasticity model for the ORN-to-PN synapse,
fitted to a paired-pulse curve and a 1 Hz train in one cohort and frozen with every
predicted number written down and checksum-pinned beforehand, predicts an unseen cohort's
32-pulse train trajectory inside its measurement error at every scorable pulse, ten times
better than the rule it replaces. **V1-limited**, scoped to the ORN-to-uniglomerular-PN
paired-pulse and 1 Hz train observables, in one laboratory, across an unstated glomerular
mixture labelled by `GH146-QF`.

**What it does not establish, stated in the same place.**

- Nothing above 1 Hz. The primary predicts a 7 Hz steady state of 0.195 against Kazama and
  Wilson's measured 0.60. The secondary gives 0.532. That is a live problem for the
  primary and this pass does not touch it.
- Nothing about another laboratory, glomerulus or synapse class; nothing about latency,
  jitter, absolute amplitude, minis or any perturbation; nothing about edge sign, which
  stays unresolved under `ND-10`.
- Not the release-probability incompatibility. The primary's effective first-pulse
  utilisation is 0.084 against a measured 0.79, and the bound derived in the fifth and
  seventh amendments holds for any distribution of per-site probabilities.
- Not which of the two models is right. The holdout separates them by 1.2 on 31 points.
- **Not developmental invariance**, and this is the sharpest caveat. The day-0 cohort's
  steady state is 0.555 and the day-2-to-4 fit set's is 0.703. The frozen models predict
  0.643 and 0.650 - *between* the two. So the curve is not tracking a cohort identical to
  the one it was fitted to; it lands inside the day-0 error bars at every pulse while
  sitting above the day-0 mean and below the day-2-to-4 mean. That the day-0 intervals are
  wide enough to contain it is part of why J1 passes, and the degeneracy check is what
  establishes they are not so wide that the refuted null also passes.

**The Stage 2 gate is unchanged at v4, 0 of 3.** Its three legs are cellular, synaptic
kinetics and circuit, and this is none of them: it is a plasticity module, and the gate's
synaptic leg requires unitary waveforms this repository does not ship. V0 Structural
remains the only supported *stage* tier; what changes is that one registered dynamics
module now carries a V1-limited validation of its own, which is the first in this project.

## Twelfth amendment, 2026-09-10 - the audit of the pass, and the corpus running out

The eleventh amendment recorded a pass. This one records an independent audit of that
pass, requested with the standing instruction to change no model, threshold, artifact or
verdict while answering. Nothing was changed. The audit is attached verbatim to both
`stage2-stp-joint-holdout-v1.json` and `short-term-plasticity-v0.3.json` under
`independent_audit`, and its verdict is **VALIDATED WITH NARROWER CLAIM**.

**The arithmetic held.** J1 at 31 of 31 and J2 at a ratio of 0.0962 re-derive exactly from
the raw arrays. The freeze predates the unsealing, gated by the contract's own
`values_opened` flag and by the fit-artifact checksum the runner requires. No parameter
moved on the outcome. Five findings narrow what the pass means, and three of them are
corrections to my own reporting.

**Finding 1, and it is the one that matters.** The registered criteria are also passed by
a predictor with no mechanism in it. Fig3B's own normalised mean trajectory - the
*training* cohort's curve, zero parameters, available before Fig3G was opened - scores J1
at 29 of 31 and J2 at a ratio of 0.2446. Both clear the registered bars.

| predictor on the 31 Fig3G pulses | weighted SSE | ratio vs v0.1 | inside | RMSE |
|---|---|---|---|---|
| v0.3 primary | 13.41 | 0.096 | 31/31 | 0.0873 |
| v0.3 secondary | 14.60 | 0.105 | 31/31 | 0.0913 |
| ND-06 v0.1, the registered null | 139.32 | 1.000 | 18/31 | 0.2357 |
| constant 1.0 | 254.96 | 1.830 | 10/31 | 0.3226 |
| best constant 0.6714, oracle | 23.87 | 0.171 | 31/31 | 0.1236 |
| **Fig3B training mean, zero parameters** | **34.08** | **0.245** | **29/31** | 0.1318 |

The mean standard error across those pulses is 0.127, so the primary's RMSE of 0.0873 is
inside the noise floor - and so is every predictor in the bottom three rows. The
registered degeneracy check was not wrong: it asked whether the *refuted predecessor*
passes J1 and correctly found it does not, at 0.581. What was missing is a strong baseline
drawn from the training data, and **no criterion in this project has ever carried one**.
That is the design lesson and it is now a requirement on every successor contract.

So J1 and J2 establish that the frozen curve is not contradicted at 1 Hz and that it beats
the refuted rule by a factor of ten. They do not establish that the mechanism is
identified. The model does beat the training mean, 13.41 against 34.08, but that margin
was never registered and may not be claimed as a passed test.

**Finding 2, a correction.** The reported `p = 0.7871 on 32 degrees of freedom` is invalid
as stated. It treats 36 correlated repeated measures as 36 independent observations: the
31 train points come from repeated stimulation of the same cells, every one is divided by
the same estimated first-pulse mean, and the methods say several protocols ran in one
cell, so the 5 paired-pulse points are probably not independent of the train either.
Bootstrapping over animals gives a mean lag-1 correlation of 0.656, a participation ratio
of 4.91 and a Kish effective count of 3.28. Scored properly as a Mahalanobis distance on
the leading principal components, the primary gives 2.70 on 5 df (p = 0.75) and 9.19 on 10
(p = 0.51), while v0.1 gives 27.77 on 5 (p = 4.0e-05) and 62.93 on 10 (p = 1.0e-09). The
*conclusions* survive - the model is consistent, the null is decisively rejected - but
four parameters constrained by roughly five to ten effective degrees of freedom is a far
weaker constraint than "36 points, 32 df" implies. The frozen numbers are left in place
because they are what the run computed and rewriting them would falsify the record; the
correction travels with them.

**Finding 3, a correction.** The registered standard error divides each pulse's raw error
by the *point estimate* of the first-pulse mean, treating that denominator as exact.
Because an animal with a large first response has large later responses, the ratio is
steadier than its numerator, and the correct bootstrap error is 0.44 to 0.85 times the
registered one. The J1 intervals were therefore 1.2 to 2.3 times too wide. Recomputed
properly the primary still passes at 31 of 31 and the secondary at 30 of 31, so the defect
flattered the test without changing its outcome - but it is a defect and the fix belongs
in the next scorer.

**Finding 4, a correction, and the one I should have caught before freezing.** The contract
called Fig3G "a genuine unseen cohort". Subject identity cannot be determined from this
corpus at all: the MAT files hold bare double matrices with no animal, cell or date
identifier, and `Figure_3.m` - the authors' own script - titles both the 3B and 3G sections
simply `1Hz`, carrying no age label. The day-0 assignment rests entirely on the published
legend. The authors *do* use that vocabulary in their code elsewhere, `Figure_6.m` titling
panels `day 0` and `day 2-4`, so the labels are theirs and not my inference - but they are
not attached to the Figure 3 arrays, and **this paper has already broken legend-implied
distinctness once**, which is why the earlier developmental holdout was voided.

Worse, and undisclosed: `Fig3H` is the day-0 *paired-pulse* cohort with n = 20 at 10 ms,
matching Fig3G's n = 20 exactly, and it was opened on 2026-09-10 as the surviving arm of
that voided holdout - **before this freeze**. The methods say "Ten seconds of rest were
afforded to the cell in between recordings", which describes several protocols run in one
cell. So Fig3G's twenty cells are probably Fig3H's twenty cells. The *array* had never
been decoded, which is what the contract claimed and is true; the *animals* had been, under
a different protocol, and their day-0 paired-pulse behaviour was known to me before the
freeze. The fit used only Fig3D and Fig3B and the selection rule was committed in advance,
so the leak into the numbers is nil and the leak into the analyst is small - but it existed
and the contract should have said so. The audit's classification: independent of the
*fitting* cohorts is **probable, not established**; against everything opened before the
freeze, **same subjects, different protocol** cannot be excluded.

One red flag was checked and discarded. Sixty exact float values are shared between Fig3B
and Fig3G, one of them a first-pulse magnitude matching to 7e-15 pA. That is digitisation:
Fig3B alone holds 60 internal exact repeats among 544 entries and Fig3G 46 among 640, the
same rate, and the two rows carrying the shared value differ by up to 17.7 pA and share
none of their 32 pulses. Exact-value coincidence carries no identity information here,
which also means the stored-byte duplicate guard is informative only for whole arrays -
which is how it is used.

**Finding 5.** The 7 Hz miss is a protocol mismatch *and* a failure, and the first does not
excuse the second. Kazama and Wilson's 0.60 is a discussion-section round number with no
error bar, from minimal single-axon stimulation in VM2, against Rozenfeld's compound
antennal-nerve stimulation across a `GH146-QF` mixture. But **this project refuted ND-06
v0.2 on precisely this number.** By the same standard the primary's 0.195 is a failure on
the only external check available - a factor of three, in the same direction that killed
its predecessor. `short-term-plasticity-v0.3.json` now carries
`neither_rule_is_promoted`, saying in terms that no consumer may treat
`facilitation-depression` as preferred and that any use above 1 Hz should prefer the
secondary or carry both.

### The corpus is now closed, and it has run out

The whole-repository audit could read 61 of 66 files and honestly recorded the other five
as an open question rather than concluding from "an amplitude series would be out of place
in a behaviour figure". That question is now answered by measurement. The repository ships
the MATLAB script that generates each figure, and reading the authors' code is reading
provenance, not a reserved value:

| file | what it actually holds |
|---|---|
| `Fig8B.mat` | `IAAvs`, a table of behavioural **learning indices**. The table object is also why the v5 reader fails - it handles numeric matrices |
| `FigS13.mat` | the same for Syn-RNAi, plus Y-maze `% correct choice` |
| `Fig1D.mat` | spike-train **correlation against bin size**, per odour |
| `FigS4A.mat` | the same, per odour, Cac-RNAi |
| `FigS8E.mat` | the same, Syn-RNAi |

**The claim is now about 66 of 66 files.** No unread file holds an ORN-to-PN
evoked-amplitude train series, and the reason is measured rather than plausible.

With that, Figure 3 resolves completely: three ages, each with a train panel and a
paired-pulse panel - day 0 in `Fig3G`/`Fig3H`, day 1 in `Fig3I`/`Fig3J`, day 2 to 4 in
`Fig3B`/`Fig3D`. The wild-type control was recorded **twice, not three times**: the day-1
panels reuse the day-2-to-4 wild-type arrays verbatim, which is exactly the recorded
`Fig3B ≡ Fig3I` and `Fig3D ≡ Fig3J` duplication. Each age has its own cacophony-RNAi
cohort, and those three RNAi train arrays - 18, 19 and 22 animals - are stored distinctly.

**So there is no unspent wild-type ORN-to-PN train left, and no train-amplitude array at
any frequency but 1 Hz.** The only higher-frequency per-pulse data are Fig3E_and_F's 10,
20 and 60 Hz *latency* and jitter arrays, which no registered model generates. The 7 Hz
question that divides the two frozen models **cannot be settled with Rozenfeld data**, and
the next wild-type train holdout does not exist to be preregistered. That is a hard
boundary and it is better to have it measured than assumed.

### Why the remaining perturbation data is asymmetric, not discriminating

Three cacophony-RNAi train cohorts and three RNAi paired-pulse cohorts are still sealed.
Cacophony is the presynaptic Cav2 alpha-1 subunit, so knockdown reads naturally as a
reduction in release probability, which would be a one-parameter prediction from a frozen
model. Before proposing that as the next contract it was simulated, because asserting a
divergence from a term in isolation is the error recorded in the fourth amendment. It does
not do what it looks like it does.

Scaling each frozen model's release parameter by `f` from 1.0 down to 0.1:

```
                 PPR at 10 ms          1 Hz steady state
  f          primary  secondary       primary  secondary
1.00          1.4808     1.4937        0.6429     0.6503
0.60          1.5072     1.4838        0.6509     0.7097
0.25          1.5317     1.4703        0.6580     0.8212
0.10          1.5426     1.4627        0.6611     0.9116
```

Two things follow. **The paired-pulse curve is nearly blind to release probability in both
families** - a tenfold reduction moves the 10 ms ratio by 0.06 against a measured standard
error of 0.055 - so `f` cannot be fitted from an RNAi paired-pulse curve. That is the same
non-identifiability that caused four consecutive failures, in a new place. And **the
primary has no usable release knob at all**: its resting utilisation is 0.0078, at its box
bound, contributing about nine per cent of the effective first-pulse utilisation of 0.0842,
the rest coming from the facilitation increment. Scaling it changes almost nothing.

That asymmetry is itself testable and worth stating now, from an exact sweep of `f` over
the whole reduction range [0, 1]:

```
                       1 Hz steady state        7 Hz steady state
  primary                [0.6429, 0.6632]        [0.1949, 0.2093]
  secondary              [0.6503, 1.0000]        [0.5316, 1.0036]
```

So a measured cacophony-RNAi day-2-to-4 1 Hz steady state outside roughly [0.60, 0.70]
would refute the primary **for any release-probability reduction whatever**, and would not
embarrass the secondary, whose reachable set covers almost everything. The 7 Hz row says
the same thing more sharply and belongs beside the fifth finding: no reduction in release
probability brings the primary within 0.39 of Kazama and Wilson's 0.60, so that miss cannot
be explained away as a difference in release probability between preparations. A test that can kill one model and cannot kill the other is worth
running, but it must be registered as what it is - a one-sided refutation attempt on the
primary under a declared perturbation assumption - and not as a discrimination experiment.
A failure would also not be cleanly attributable, since "cacophony knockdown scales release
probability and nothing else" is an assumption ND-06 does not currently carry.

**The Stage 2 gate is unchanged at v4, 0 of 3, and V0 Structural remains the only supported
stage tier.** The audit confirms both. What the audit changed is the size of the claim, not
the tier: `V1-limited` still stands, and now says explicitly that its criteria are cleared
by a model-free baseline.
