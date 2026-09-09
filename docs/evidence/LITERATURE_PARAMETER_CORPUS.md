# Literature parameter corpus

One place for every quantitative value extracted from the primary literature, with its source,
its measurement conditions, and its provenance class. Compiled 2026-09-09 from 14 full-text
papers supplied by the project owner.

**How to use this.** A value here is not registered until it appears in a `configs/` registry
with an assumption ID. This document is the audit trail behind those registrations and the
place to check before adding a parameter. Provenance follows the project classes: `M` measured,
`P` population prior, `F` fitted, `E` engineering scaffold, `I` irrecoverable.

**The most important thing in this document** is not a parameter. It is the connectome
completion rates in section 5, which the repository does not currently disclose anywhere, and
which qualify every structural and functional claim the project makes.

## 1. Paper index

| key | citation | what it supplies |
|---|---|---|
| `KW2008` | Kazama & Wilson 2008, *Neuron* 58:401–413, [10.1016/j.neuron.2008.02.030](https://doi.org/10.1016/j.neuron.2008.02.030) | uEPSC amplitudes per glomerulus, quantal parameters, release-site counts, 7 Hz depression |
| `KW2009` | Kazama & Wilson 2009, *Nat Neurosci*, "Origins of correlated activity in an olfactory circuit" | complete ORN→PN convergence, ORN counts per glomerulus |
| `Nagel2015` | Nagel, Hong & Wilson 2015, *Nat Neurosci* 18:56–65, [10.1038/nn.3895](https://doi.org/10.1038/nn.3895) | two-component EPSC kinetics and conductances, depression fits, presynaptic inhibition |
| `Gouwens2009` | Gouwens & Wilson 2009, *J Neurosci*, "Signal Propagation in Drosophila Central Neurons" | measured PN input resistance, seal-conductance correction to resting potential |
| `Gaudry2012` | Gaudry, Hong, Kain, de Bivort & Wilson 2012, *Nature*, [10.1038/nature11747](https://doi.org/10.1038/nature11747) | ipsi/contra release asymmetry and odour lateralisation |
| `Gugel2023` | Gugel et al. 2023, *eLife* 12:e85443 | the 12 uEPSC recordings already in the corpus (DL5) |
| `MaleCNS` | "Sexual dimorphism in the complete Drosophila male central nervous system connectome" (`mmc6.pdf`) | the connectome this project runs on: counts, completion rates |
| `GainControl` | "Interactions between specialized gain control mechanisms in olfactory processing" (`mmc3.pdf`) | LN classes performing local vs global gain control |
| `NRmap` | "Mapping of multiple neurotransmitter receptor subtypes and distinct protein complexes to the connectome" | receptor subunit localisation; the definitive answer on `ND-03` |
| `Davis2020` | Davis et al. 2020, *eLife* 50901 | cell-type-resolved transcriptomes — visual system only |
| `Lappalainen2024` | Lappalainen et al. 2024, *Nature* 634:1132 | connectome-constrained network prior art; the methodological benchmark |
| `Rozenfeld2023` | Rozenfeld, Ehmann, Manoim, Kittel & Parnas 2023, *Nat Commun*, [10.1038/s41467-023-38575-6](https://doi.org/10.1038/s41467-023-38575-6) | independent release-site estimate, homeostatic AZ plasticity |
| `Pooryasin2021` | Pooryasin et al. 2021, *Nat Commun*, "Unc13A and Unc13B..." | two release-machinery populations with distinct STP |
| `OlfSNN2024` | *Front Neurosci* 18:1384336, data-driven olfactory SNN | comparison model, unfitted LIF |

Extracted plain text is in the session scratchpad under `papers_txt/`; the PDFs are in
`C:\Users\ibtis\Downloads\papers`. Neither is checksum-locked into `/srv/flybrain-data`, so
nothing here is evidence-grade until a value is registered with its own dataset card.

## 2. ORN→PN synapse

The best-characterised synapse in the fly brain, and the only one where the project can compare
independent measurements. Note the measurement condition column: several apparent conflicts
dissolve once it is read, and one does not.

| quantity | value | conditions | source | prov |
|---|---|---|---|---|
| uEPSC amplitude | **29.0 ± 2.6 pA** (n = 45) | minimal antennal-nerve stimulation at 0.033 Hz, pooled glomeruli | `KW2008` | M |
| uEPSC amplitude | ~13.5 pA | first pulse of a 10 Hz train, set in model | `Nagel2015` | F |
| uEPSP amplitude | **6.19 ± 0.45 mV** (n = 23) | as above | `KW2008` | M |
| uEPSP amplitude | ~7 mV | model, given its passive properties | `Nagel2015` | F |
| uEPSC across glomeruli | differs, p < 10⁻⁶ ANOVA, n = 9, 10, 9, 10 | DM6, VM2, DL5, DM4; DL5 and DM4 larger | `KW2008` | M |
| uEPSP across glomeruli | **constant**, p > 0.43 ANOVA, n = 7, 5, 5, 6 | same four glomeruli | `KW2008` | M |
| quantal size `q` | **1.05 ± 0.11 pA**; 1.12 pA in the worked example | multiple-probability fluctuation analysis | `KW2008` | M |
| mEPSC amplitude CV | 0.24 | averaged across PNs | `KW2008` | M |
| release probability `p` | **0.79 ± 0.02**; "near 0.75" in discussion; 0.77 in the worked example | MPFA; uniform across glomeruli, p > 0.36 | `KW2008` | M |
| release sites `N` per ORN axon per PN | **51.4 ± 7.8**; 47.4 in the worked example; ">25 per PN" for large glomeruli | MPFA | `KW2008` | M |
| release sites per ORN–PN pair | **~10–30** | independent estimate | `Rozenfeld2023` | M |
| `N` across glomeruli | differs, p < 0.01; scales with glomerular volume | | `KW2008` | M |
| peak conductance | **0.28 nS** total: 0.22 nS fast + 0.06 nS slow | model, per ORN input | `Nagel2015` | F |
| EPSC decay | fast τ**g = 9.3 ms**, slow τ**g = 80 ms** | model | `Nagel2015` | F |
| ipsi vs contra uEPSC | equal, p > 0.54, n = 20 / 24 | | `KW2008` | M |
| ORN→PN convergence | **complete**: every ORN synapses onto every PN of its cognate glomerulus | dual whole-cell, synchronous spontaneous EPSCs | `KW2009` | M |
| ORNs per glomerulus (DM4) | **17.4 ± 0.9 per antenna** (n = 5 antennae) | Or59b-GFP cell counts | `KW2009` | M |
| ORN spontaneous rate (DM4) | 3.44 ± 0.16 Hz (n = 11) | | `KW2009` | M |
| PN spontaneous EPSC rate (DM4) | 74.9 ± 8.6 Hz (n = 8, one antenna removed) | consistent with 3.44 × 17.4 | `KW2009` | M |

### 2.1 Short-term depression, and the one real conflict

All three `Nagel2015` fits use the same equation the project's plasticity registry implements —
`A ← f·A` on a spike, `A ← A + (1−A)dt/τ` between spikes, with the paper stating its `r` "is
equivalent to (1 − f)". So `utilisation = 1 − f` and `recovery_tau_ms = τ` transfer directly.

| fit | `f` | `U = 1−f` | `τ` (ms) | conditions |
|---|---|---|---|---|
| whole EPSC | 0.78 | **0.22** | **893** | control saline, 10 Hz, Fig 1c — **registered default** |
| fast component (IMI-resistant) | 0.77 | 0.23 | 1006 | curare blocks the fast component, so IMI-resistant = fast |
| slow component (curare-resistant) | 0.91 | 0.09 | 629 | IMI occludes the slow component |

Recording basis: n = 19 PNs from 19 flies, glomerulus DM6 or VM2, electrical stimulation.

**Both components are monosynaptic.** `Nagel2015` measured them in *spontaneous* EPSCs, each of
which "arises from a single ORN spike, and any dynamics present in these EPSCs must therefore
arise from unitary ORN-to-PN connections", and separated them pharmacologically at the same
synapse — concluding "ORN-to-PN synapses contain two types of nicotinic receptor with distinct
kinetics. Alternatively, the two components might represent different states of the same
receptor." `KW2008` had inferred from evoked-stimulation failure modes that the two decay
components "originate from different synapses", the slow one polysynaptic via interneurons that
interconnect glomeruli. **`Nagel2015`'s evidence is the stronger of the two** because spontaneous
single-ORN EPSCs are monosynaptic by construction, so the registry's whole-EPSC choice is
sound. `Pooryasin2021` adds independent mechanistic support that a single fly central synapse
can carry two STP components: Unc13A clusters closer to Ca²⁺ channels than Unc13B and
"coupling distance defines release components with distinct STP characteristics" — though that
was measured at ePN *output* synapses, not ORN→PN.

**The real conflict is a failed prediction.** `KW2008` independently measured depression at a
different frequency: *"At frequencies mimicking the basal firing rate of a typical ORN (7 Hz),
synaptic responses depress by about 40% but remain relatively strong."* That is depression **to**
about 60% of rest. The registered pair predicts otherwise:

```
registered U = 0.22, tau = 893 ms, 7 Hz (ISI 142.86 ms)
  exact discrete steady state  x* = (1-c)/(1-(1-U)c),  c = exp(-142.86/893) = 0.85216
                               x* = 0.4409   ->  56% depression
  mean-field approximation     x* = 1/(1 + 0.22*7*0.893) = 0.4210  ->  58% depression
  KW2008 measurement                                                   ~40% depression
```

The registered rule **over-predicts depression at 7 Hz by roughly 16 percentage points against
an independent measurement from a different paper.** This is the first genuine external test the
ND-06 rule has faced and it does not pass cleanly. Values that would reproduce `KW2008`:
`U ≈ 0.107` at τ = 893 ms — which *is* inside the registered utilisation range [0.09, 0.23] — or
τ ≈ 433 ms at U = 0.22, which is *outside* the registered τ range [629, 1006].

This must be recorded as a partial failure of the registered rule, not smoothed over. It is
also not a clean falsification: `KW2008`'s "about 40%" is a discussion-section round number with
no error bar, measured in VM2 with 4 s trains, against `Nagel2015`'s DM6/VM2 fit at 10 Hz.

**The depression is presynaptic.** `KW2008` Fig 8G: 7 Hz stimulation decreases 1/CV², and the
decrease correlates with the uEPSC amplitude decrease (Pearson r = 0.79, p < 10⁻⁴). That
validates the *form* of the Tsodyks–Markram resource model, independently of its parameters.

### 2.2 Homeostatic matching, stated precisely

`KW2008`'s claim, which the project's `ND-04` synaptic-structure test attributes to it, is:
uEPSC amplitude scales with glomerular volume because **`N`, the number of release sites per ORN
axon per PN, scales** — while `p` and `q` stay constant across glomeruli — so that uEPSP is
constant across glomeruli despite the current differing. Large glomeruli give PNs large dendritic
arbors, hence lower input resistance, hence more current is needed for the same depolarisation.
Verified causally: overexpressing Kir2.1 to lower input resistance *increased* uEPSC amplitude
(p < 0.005, n = 26 / 7).

The structural corollary testable on the connectome: **contacts per ORN→PN connection should
scale with glomerular volume**, and `p`/`q` invariance means contact count is the only structural
degree of freedom carrying the effect.

## 3. PN membrane properties

| quantity | value | conditions | source | prov |
|---|---|---|---|---|
| **input resistance** | **598.0 ± 69.3 MΩ** (n = 14) | whole-cell, antennae removed | `Gouwens2009` | **M** |
| membrane resistance | 800 MΩ | *"The constant R_m was set at 800 MΩ"* — a model constant, **not** a measurement | `Nagel2015` | E |
| membrane time constant | 5 ms | *"adjusted so that a unitary EPSP decayed with a half-width of about 50 ms"* | `Nagel2015` | F |
| compartmental specifics | Ri ≈ 80 Ω·cm, Rm ≈ 10⁴ Ω·cm², Cm ≈ 1 µF/cm² ⇒ τ_m ≈ 10 ms | fitted compartmental model | `Gouwens2009` | F |
| somatic resting potential, whole-cell | −47.8 ± 1.6 mV | measured at soma | `Gouwens2009` | M |
| **true resting potential** | **−57.8 ± 1.5 mV** (n = 12) | hyperpolarisation needed to match the cell-attached firing rate | `Gouwens2009` | **M** |
| leak reversal | −70 mV, *"close to the resting potential of PNs in tetrodotoxin"* | model | `Nagel2015` | E |
| spike threshold | **not reported** in any of these papers | | — | I |
| unitary synapse structure | must be modelled as dozens of release sites across many dendritic branches to match real uEPSC size | | `Gouwens2009` | F |

### 3.1 Two consequences for the project's cellular tier

**The v0.4 input-resistance defect is confirmed with a measured number.** ADR-2026-010 recorded
that every self-consistent MBON07 LIF candidate implies 4.4–6.4 GΩ, that the observed 2 pA
rheobase requires ≥ 9.26 GΩ, and called the implied resistance "a fitting artifact of the
single-compartment LIF form", citing only `Nagel2015`'s 800 MΩ *model constant*. The measured
value is now available: **598 ± 69 MΩ**, which is **7 to 15 times lower** than the LIF fit
implies. The artifact conclusion stands and is now backed by a measurement rather than by
another model's constant.

**Every whole-cell somatic resting potential in the corpus carries a systematic bias.**
`Gouwens2009` shows the electrode seal conductance depolarises the measured somatic resting
potential by about 10 mV, because *Drosophila* neurons have input resistances approaching the
seal resistance. This affects absolute voltages throughout the cell-dynamics registries. It does
**not** simply cancel in `threshold_mv − resting_mv`: the seal acts as a divider toward the seal
reversal potential near 0 mV, so the error is larger at more hyperpolarised potentials, which
means the true threshold-to-rest distance is **larger** than whole-cell recordings show. For
v0.4's MBON07 that widens the 18.5 mV gap and therefore makes the rheobase inconsistency in
section 3.1 *worse*, not better. No registry value is changed on this basis yet — Nanami's
recording conditions have to be checked first — but it is a live correction candidate for every
`resting_mv` in `configs/neural/`.

## 4. Inhibition and gain control

`GainControl` identifies functionally distinct antennal-lobe inhibitory interneuron classes:
non-spiking LNs with compartmentalised calcium signals that "specialize in intra-glomerular gain
control", and LNs with broad dense arbors that "specialize in global presynaptic gain control".
`Nagel2015` adds that presynaptic inhibition "dynamically updates synaptic properties to promote
accurate transmission of signals across a wide range of frequencies", with GABA_B blockade
(CGP54626, n = 17 PNs) and GABA_A blockade markedly altering PN responses, and reports LN
recordings at n = 45 LNs and synaptic currents in n = 22 LNs.

This matters for the widened-circuit result in
[STAGE2_WIDENED_GROOMING_CIRCUIT.md](STAGE2_WIDENED_GROOMING_CIRCUIT.md). That sweep found the
one-hop circuit has *zero* inhibitory input to the readout and over-responds, while the
bounded-path circuit is held silent by 14–22 active inhibitory neurons. The literature says the
real thing is neither: inhibition here is **specialised, divisive and partly presynaptic**, with
separate local and global mechanisms. A signed-sum LIF model with no presynaptic inhibition and
no divisive normalisation has no way to reproduce it, which is a mechanistic reason the sweep's
two failure modes bracket the reference rather than containing it. Note this is the *olfactory*
antennal lobe; the widened circuit is the JON-F→aBN1 mechanosensory grooming pathway, so the
principle transfers but the specific cell classes do not.

## 5. The connectome, and what the repository does not disclose about it

From `MaleCNS`, the paper describing the dataset this entire project runs on:

| quantity | paper value | repository value | status |
|---|---|---|---|
| neurons identified, proofread, annotated | **166,700** (incl. sensory axons) | — | not recorded |
| neurons in the connectivity graph | **166,483** (217 disconnected) | 165,122 `Traced` bodies | **Δ 1,361 unreconciled** |
| directed edges | **25.6 M** | 25,563,197 | agrees |
| synaptic connections | **124.2 M** | — | not recorded |
| unique cell types | **11,710** | 11,752 | **Δ 42, repo has more** |
| presynaptic completion rate | **94%** | — | **undisclosed** |
| postsynaptic completion rate | **42%** | — | **undisclosed** |
| connections with both partners proofread | **40.1%** | — | **undisclosed** |
| proofreading effort | 44 person-years | — | not recorded |

**The three completion rates appear nowhere in the repository** — not in `V0_STRUCTURAL.md`, not
in `STATUS.md`, not in `configs/datasets/malecns-v1.0.json`. They are a first-order caveat on
every claim the project makes, and their absence is the same class of undisclosed limitation the
independent audits have twice found. Specifically:

- **42% postsynaptic completion means more than half of all postsynaptic sites are not assigned
  to a proofread neuron.** Every statement about the inputs a neuron receives — including the
  excitation/inhibition balance that drives the entire widened-circuit result — is computed from
  a minority sample of that neuron's actual inputs. The direction of that bias is unknown.
- **40.1% both-sides-proofread** is the fraction of synaptic connections usable for connectivity
  analysis at all.
- **94% presynaptic completion** is high, so out-degree is far better sampled than in-degree.
  Any asymmetry between the project's forward and backward reachability results may partly be
  this rather than biology.

The 1,361-neuron and 42-cell-type discrepancies are probably explained by the repository's
`Traced`-status filter and by type labels present in the annotation artifact but not in the
paper's final count. Both need an explicit reconciliation rather than an assumption.

## 6. Structural predictions testable on the locked graph, with no physiology

These are the highest-value experiments this corpus makes available, because they need no
biophysical parameters, no fitting and no simulation — only the checksum-locked connectome.

**P1 — Complete ORN→PN convergence (`KW2009`).** Every ORN of a glomerulus synapses onto every
uniglomerular PN of that glomerulus, and vice versa. On the connectome this is a
complete-bipartite prediction: for each glomerulus, the fraction of possible ORN×PN pairs that
carry an edge should be 1.0. It is binary, unambiguous, has no free parameter, and it directly
tests `DATA-03` edge recovery and the postsynaptic completion problem in section 5 at the same
time — a measured fraction well below 1.0 in a well-proofread glomerulus is evidence about the
connectome, not about the fly. **This is the single best new test available.**

**P2 — Release-site count against contact count (`KW2008`, `Rozenfeld2023`).** `N` per ORN axon
per PN is 51.4 ± 7.8 by MPFA, ">25 per PN" for large glomeruli, and ~10–30 by
`Rozenfeld2023`'s independent estimate. The repository already measures a median 43 contacts per
connection. Those are the same physical quantity measured two ways, so the comparison is direct
and it is currently favourable — 43 sits inside the MPFA estimate's spread and above
`Rozenfeld2023`'s range.

**P3 — Homeostatic matching (`KW2008`). Done and inconclusive; see
[GLOMERULAR_VOLUME_SCALING.md](GLOMERULAR_VOLUME_SCALING.md). Volume was measured blind, both preregistered hypotheses failed, and the earlier proxy-failure explanation is withdrawn: volume does track ORN count. The contact statistic turns out to be contaminated by reconstruction incompleteness, so the question is not settleable on this connectome without a completeness-corrected contact estimate.** The superseded reasoning follows.

**Superseded:** A post-hoc ordinal check found that contacts per connection reproduce
`KW2008`'s stated uEPSC ordering on their four recorded glomeruli with clean separation
(DL5 81 > DM4 63 > VM2 40 > DM6 28), and that the project's earlier negative result came from
substituting ORN count for glomerular volume — a proxy that anti-correlates with contacts across
all 50 glomeruli. The proper test needs **glomerular volumes**, and here is the practical route,
because it is not immediately available: the `syn-partners` contacts derivative carries
`x_post, y_post, z_post, body_post`, so a volume proxy can be computed from the spatial extent of
each glomerulus's ORN→PN synapse cloud by streaming its 298 parquet shards. Region labels would
be better than a proxy, and `syn-points` carries `primary_label` and `subprimary_label` with 12
and 100 distinct values respectively — 100 being suggestively close to 50 glomeruli on two sides
— but the derivative stores them as **integer codes with no name mapping**, and the manifest does
not carry one. The strings would have to be recovered from the raw
`syn-points-male-cns-v1.0-minconf-0.5.feather` dictionary first. Note that reading that raw
artifact whole is not viable — 357 M points saturated the WSL instance — so any such work must
stream shards.

**P3 original statement.** Contacts per ORN→PN connection
should scale with glomerular volume across DM6, VM2, DL5 and DM4, with the ordering
DL5 ≈ DM4 > DM6 ≈ VM2. The repository's existing test found contact number "does not implement
the published homeostatic matching"; section 2.2 gives the precise form of the claim to retest
against, including that `p` and `q` invariance makes contact count the only structural carrier.

**P4 — Bilateral symmetry of ORN→PN strength (`KW2008`).** Ipsilateral and contralateral
projections produce equal uEPSCs (p > 0.54), so contact counts from each antenna onto a shared
PN should be statistically indistinguishable. A left/right contact-count comparison is directly
available and doubles as an internal consistency check on the connectome itself.

## 7. `ND-03` functional edge polarity: the definitive answer

`NRmap` settles what the project can and cannot do here, and the answer is not "the dataset is
missing".

The good news for the registered policy: *"The stereotyped patterns of each class of receptor
matched the pattern of the neurotransmitters used by their respective presynaptic inputs."*
Transmitter-based sign assignment is broadly correct, which is what `ND-03` currently does.

The bad news for refining it: *"**Unexpectedly, different NRs to the same neurotransmitter are
also localized to different domains, receiving input from different presynaptic partners.** This
was seen for both cholinergic (excitatory) and GABAergic (inhibitory) synapses."*

So the postsynaptic receptor identity for a given edge is **partner-specific and
dendritic-domain-specific**. It is not a property of the postsynaptic cell that any bulk
expression atlas can report. `ND-03`'s "transmitter-plus-postsynaptic-receptor" policy therefore
cannot be advanced beyond the transmitter term with any resource that exists or is likely to,
because the required measurement is domain-resolved and partner-resolved localisation, currently
available for a handful of visual-system neurons via conditional epitope tagging and
expansion light-sheet microscopy.

`Davis2020` is the closest thing to the resource `ND-03` would need — cell-type-resolved
transcriptomes for 67 named types via TAPIN-seq, with a probabilistic interpretation layer — but
it covers the **visual system only**. `Croset2018` (checked previously) is a midbrain Drop-Seq
atlas whose PN-level receptor statements are inferential and which has no published mapping to
MaleCNS body IDs. Neither closes the gap.

**Recommended disposition:** change `ND-03`'s status from "receptor evidence is incomplete,
pending" to "transmitter term is supported; the receptor refinement is not obtainable at
connectome scale, and the reason is that the quantity is partner-specific rather than
cell-specific." That converts an open action item into a stated boundary, which is honest and
which stops the project from waiting on a dataset that will not arrive in this form.

**Disposition taken, 2026-09-09 (ADR-2026-012).** The recommendation above was adopted and then
went one step further: the record was **split**, because one identifier carrying both terms let
every contract that cited it for an edge's sign lean on the term that cannot be measured.
`ND-03` is now presynaptic transmitter identity alone, `M/P`, and it has a reserved validation
set. `ND-10` carries postsynaptic receptor identity and functional edge polarity, `P/F`, as a
stated boundary. The section above is the evidence for `ND-10`, not for `ND-03`.

One consequence is worth stating plainly, because the intake of the flyconnectome ground truth
got it wrong. Verified transmitter assignments validate `ND-03` — but for **169** MaleCNS
cell types, none of them in the antennal lobe, not the 6,107 rows of the parent table,
which carries no MaleCNS column at all and includes 804 larval rows. See ADR-2026-012
third amendment. They do
**not** validate edge sign: a correct transmitter label still leaves the sign unresolved wherever
the postsynaptic receptor is unknown, which the paragraphs above establish is the normal case
rather than the exception. An agreement rate on transmitter identity is an upper bound on sign
correctness, not a measurement of it.


## 8. Methodological prior art: what "the mark" actually looks like

`Lappalainen2024` is the most directly comparable published work and it is worth being precise
about what it did, because it is a different strategy from the one this repository pursues.

They built a deep mechanistic network whose connectivity came from the optic-lobe connectome,
then optimised it on a **task** (motion detection) rather than fitting it to recordings, and then
validated it by predicting neural activity for cell types whose measurements were **held out of
the optimisation entirely**. Their framing: *"with only the connectome and task constraints... we
can predict the neural activity underlying a specified neural computation"*, and they note the
strategy "is more likely to be successful when" specific conditions hold. They report an ensemble
of models rather than one, and correlations between measured and predicted activity per cell type.

The contrast with this project matters strategically. This repository is attempting to measure or
source every biophysical parameter before it will claim a tier, and sections 3 and 7 above show
that route is blocked in several places by data that does not exist. `Lappalainen2024` shows a
route that does not need those parameters: connectome topology plus a task objective, validated
against held-out recordings. It does not award biophysical realism, and it would not satisfy the
project's cellular tier — but it does produce a falsifiable, validated model, which the project
currently does not have at any tier above V0.

This is a strategic option to put to the owner, not a change to make unilaterally.

## 9. What remains missing after reading all 14 papers

- **Raw traces.** None of these papers deposited raw electrophysiology. Confirmed absent for
  `KW2008`, `KW2009`, `Gouwens2009` and `Nagel2015`. The cellular tier stays single-specimen and
  the uEPSC holdout stays empty on that account.
- **Per-cell depression fits.** `Nagel2015` publishes population fits only; the SI in hand does
  not break `f` and `τ` down by cell, so the ND-06 spread remains a spread across pharmacological
  conditions rather than across animals.
- **Spike threshold for any PN.** Not reported in any of the 14.
- **Antennal-lobe or MaleCNS-linked receptor expression by cell type.** Section 7 — not missing
  so much as not the right kind of quantity.
- **Anything at all about the Eon demo.** No data source exists to compare Track A against.

## 10. Corrections and additions this corpus forces

Recorded here so they are not lost; each needs its own change with tests.

1. **Disclose the connectome completion rates** (94% / 42% / 40.1%) in `V0_STRUCTURAL.md`, the
   MaleCNS dataset card and `STATUS.md`, and add the postsynaptic-completion caveat to the
   widened-circuit report, whose central E/I result depends on it. **Highest priority.**
2. **Reconcile 165,122 against the paper's 166,483**, and 11,752 cell types against 11,710.
3. **Record the failed 7 Hz depression prediction** in the plasticity registry and in
   ADR-2026-010: the registered pair over-predicts depression by ~16 points against `KW2008`.
4. **Replace the 800 MΩ model constant with Gouwens' measured 598 ± 69 MΩ** in ADR-2026-010's
   input-resistance argument, strengthening a conclusion that currently leans on another model.
5. **Open the seal-conductance question** for every `resting_mv` in `configs/neural/`.
6. **Restate `ND-03`** as a boundary rather than a pending action.
7. **Add `KW2008`, `KW2009`, `Gouwens2009` and `MaleCNS` as literature sources** with the values
   in sections 2 and 3, so the uEPSC amplitude comparison below becomes registrable.

### The uEPSC amplitude coincidence was spurious, and chasing it found a real defect

**Withdrawn.** An earlier draft of this document noted that the project's refitted uEPSC prior
gives a population amplitude of **30.25 pA** from the 12 `Gugel2023` DL5 cells while `KW2008`
measures **29.0 ± 2.6 pA** (n = 45), and flagged the agreement as a promising independent check.
Both conditions that draft said had to be settled first were then settled, and the coincidence
does not survive either.

**The protocols are comparable — that part holds.** `Gugel2023` state that they "adapted a
previously established minimal stimulation protocol (Kazama and Wilson, 2008)", substituting
488 nm optogenetic stimulation of ORN terminals for electrical antennal-nerve stimulation with
the nerve severed, and they report their DL5 values were "similar to previous measurements made
using conventional electrical stimulation of the antennal nerve (Kazama and Wilson, 2008),
confirming this method". So a DL5-to-DL5 comparison is legitimate.

**But the comparison was against the wrong numbers on both sides.** `KW2008`'s 29.0 pA is pooled
across four glomeruli whose amplitudes differ at p < 10⁻⁶, and DL5 is one of the two *large* ones.
`Gugel2023` state their own DL5 control amplitude as **~40 pA**, not 29. And the project's
30.25 pA is not a measurement of those cells but the output of a kernel fit. Measuring the
traces directly — per-cell peak deflection against a pre-stimulus baseline — gives:

```
  12 cells, peak amplitude:  mean 36.61 pA, median 36.13, SEM 2.92, range 24.0 to 55.8
  control (solvent) only, n=7:  mean 34.92 pA
  Gugel2023 stated value for the control condition:  ~40 pA
```

So the repository's **data is faithful** and agrees with the source paper; the repository's
**kernel fit underestimates the amplitude by 17%** (30.25 against 36.61 pA), and the frozen fit
by 33% (24.47 pA). The apparent agreement with `KW2008` was a biased fit amplitude landing near a
pooled cross-glomerular mean by coincidence.

**Why the fit is biased, tested and mostly answered.** Three candidates were tested:

| candidate | result |
|---|---|
| decay overestimate pulling the amplitude down | pinning decay to the published τ = 10.1 ms moves amplitude 30.25 → 31.59 pA, only 4% of the gap |
| per-cell onset jitter smeared by one shared onset | ruled out — all 12 traces peak at exactly 49.90 ms, already peak-aligned as `Gugel2023` describe doing |
| Huber δ = 1.0 pA against a 36 pA signal | 3% effect; pure least squares gives 31.47 pA |

The answer is **model-family misspecification, and both source papers say so explicitly.**
`KW2008`: *"The decay phase of these evoked EPSCs typically had two components, fast and slow."*
`Nagel2015` fits exactly that, at τ = 9.3 ms and τ = 80 ms with conductances of 0.22 and 0.06 nS.
The project's kernel has **one** decay. Fitting a single exponential decay to a fast-plus-slow
waveform necessarily returns an intermediate decay and a depressed peak. Adding a second decay
term to the same fitting machinery, over a comparable grid:

```
  one decay  (repo family): decay 15.0 ms      | amp 32.93 pA (-10.0%) | SSE 50199 | t_half 11.20 ms
  two decays              : 11.0 / 50.0 ms     | amp 33.95 pA ( -7.2%) | SSE 38568 | t_half  9.80 ms
                                                                          SSE improvement 23.2%
  published targets                                    ~40 pA                        t_half ~7 ms
```

**This reframes a recorded result.** ADR-2026-008 recorded the frozen uEPSC kernel's decay as
*failing* its preregistered holdout at 0.463 median fractional error against a 0.30 limit, and
ADR-2026-009 examined the criteria but not the kernel family. That failure is substantially a
misspecification the literature predicted rather than an open empirical question: the fitted
family cannot represent the waveform the source papers describe. A two-component kernel is the
indicated fix and its parameters are published.

**What it does not do is unblock the synaptic tier.** A better kernel is still fitted to all
twelve cells, so it is a better prior and not a test. And even two decays leave the amplitude 7%
low and the half-decay 40% above the published 7 ms, so the family is improved rather than
correct.
