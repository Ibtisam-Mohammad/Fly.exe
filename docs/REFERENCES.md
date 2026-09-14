# References, datasets and prior art

Everything this project reads, reuses or takes a number from, in one place.

**What a citation here means.** Three different relationships are collapsed by the word
"reference", and they are kept apart below:

1. **The connectome itself** — the anatomy the simulation *is*. One dataset, section 1.
2. **Sources of registered numbers** — a value extracted from a paper and written into a
   `configs/` registry. Sections 4 and 5. Every such value carries an assumption ID in
   [`configs/assumptions.json`](../configs/assumptions.json), and the audit trail with its
   measurement conditions is
   [`docs/evidence/LITERATURE_PARAMETER_CORPUS.md`](evidence/LITERATURE_PARAMETER_CORPUS.md).
   A paper appearing here does **not** mean its value is registered: the corpus records
   several that were read and rejected, and one registered value that an independent
   measurement contradicts.
3. **Prior art reused as method or code** — an approach, an implementation or a body model.
   Sections 2, 3 and 6. Reusing the work does not inherit its claims;
   [`AGENTS.md` section 11](../AGENTS.md) lists, for each one, what it may *not* be used to
   claim.

No dataset in this list is redistributed by this repository. Each is downloaded by
`flysim data sync`, checksummed, and recorded in an immutable dataset lock. The primary PDFs
were read locally and are not republished here.

---

## 1. The connectome

| | |
|---|---|
| Dataset | **MaleCNS v1.0**, HHMI Janelia FlyEM |
| Download | <https://male-cns.janelia.org/download/> |
| License | CC-BY |
| Paper | Sexual dimorphism in the complete *Drosophila* male central nervous system connectome, [10.1016/j.cell.2026.08.015](https://doi.org/10.1016/j.cell.2026.08.015) |
| Companion | Male gustatory connectome, [10.1016/j.cell.2026.08.016](https://doi.org/10.1016/j.cell.2026.08.016) |
| Registry | [`configs/datasets/malecns-v1.0.json`](../configs/datasets/malecns-v1.0.json) — seven checksum-locked flat-connectome tables |
| Supplement | [`configs/datasets/berg-malecns-2025-supplement.json`](../configs/datasets/berg-malecns-2025-supplement.json), <https://github.com/flyconnectome/2025malecns> |

The executed graph is **165,122 neurons and 25,563,197 edges**. What that graph does *not*
say about itself — reconstruction completion rates, and why they qualify every structural
and functional claim made anywhere in this repository — is section 5 of the literature
corpus. Read it before quoting any number from a run.

Morphology canaries (skeleton SWCs used to detect a silently changed release) are
[`configs/datasets/morphology-canaries.json`](../configs/datasets/morphology-canaries.json).

## 2. Body, physics and neural simulators

| Component | Used for | Source and license |
|---|---|---|
| **NeuroMechFly v2 / FlyGym** 2.1.0 | The body: 133 DOF, legs, contact, adhesion, the published `HybridTurningController` gait | [10.1038/s41592-024-02497-y](https://doi.org/10.1038/s41592-024-02497-y), Apache-2.0, <https://github.com/NeLy-EPFL/flygym> |
| **MuJoCo** 3.9 | Rigid-body physics, contacts, rendering | Apache-2.0 |
| **GeNN / PyGeNN** | The production sparse CUDA engine that executes the full graph | <https://github.com/genn-team/genn> |
| **Brian2** | Small-circuit numerical oracle used to check the engine | CeCILL-2.1, <https://github.com/brian-team/brian2> |
| **Flybody** | Consulted as a later whole-body and flight-physics baseline. **Not used** — its mesh pack is not checksum-lockable here, and its fluid model is not NeuroMechFly's | [10.1038/s41586-025-09029-4](https://doi.org/10.1038/s41586-025-09029-4) |
| **FlyMimic** | Consulted for muscle-level foreleg priors. Not used | <https://openreview.net/forum?id=6lEjX1getx> |

The distinction between Flybody and NeuroMechFly matters and is recorded in
[ADR-2026-017](adr/ADR-2026-017-a-wing-command-in-a-body-with-no-air.md): this project's body
sets no air density and no viscosity and has no fluid geoms, so **wing flapping produces
exactly zero lift here**, and any takeoff is leg extension against the floor.

## 3. Reference implementations

| Work | How it is used |
|---|---|
| **Shiu et al. 2024**, whole-brain leaky integrate-and-fire model of FlyWire — [10.1038/s41586-024-07763-9](https://doi.org/10.1038/s41586-024-07763-9), MIT, <https://github.com/philshiu/Drosophila_brain_model>, archived outputs [10.17617/3.CZODIW](https://doi.org/10.17617/3.CZODIW) | Stage 1 regression reference. Selected circuit tests are reproduced against its archived outputs. Its global LIF constants are **not** treated as MaleCNS physiology |
| **Eon fly-brain** — GPL-2.0-or-later, <https://github.com/eonsystemspbc/fly-brain> | Reproduction reference and attributed implementation ideas for the engineering demonstration lane |

## 4. Physiology parameters: the literature corpus

Fourteen full-text papers were read and every quantitative value extracted, with its
measurement conditions and provenance class, into
[`docs/evidence/LITERATURE_PARAMETER_CORPUS.md`](evidence/LITERATURE_PARAMETER_CORPUS.md).
That document is the audit trail; this table is its index.

| key | citation | what it supplies |
|---|---|---|
| `KW2008` | Kazama & Wilson 2008, *Neuron* 58:401–413, [10.1016/j.neuron.2008.02.030](https://doi.org/10.1016/j.neuron.2008.02.030) | uEPSC/uEPSP amplitudes per glomerulus, quantal parameters, release-site counts, 7 Hz depression |
| `KW2009` | Kazama & Wilson 2009, *Nat Neurosci*, "Origins of correlated activity in an olfactory circuit" | complete ORN→PN convergence, ORN counts per glomerulus |
| `Nagel2015` | Nagel, Hong & Wilson 2015, *Nat Neurosci* 18:56–65, [10.1038/nn.3895](https://doi.org/10.1038/nn.3895) | two-component EPSC kinetics and conductances, the registered depression fit, presynaptic inhibition |
| `Gouwens2009` | Gouwens & Wilson 2009, *J Neurosci*, [10.1523/JNEUROSCI.0764-09.2009](https://doi.org/10.1523/JNEUROSCI.0764-09.2009) | measured PN input resistance, seal-conductance correction to resting potential |
| `Gaudry2012` | Gaudry, Hong, Kain, de Bivort & Wilson 2012, *Nature*, [10.1038/nature11747](https://doi.org/10.1038/nature11747) | ipsi/contra release asymmetry and odour lateralisation |
| `Gugel2023` | Gugel et al. 2023, *eLife* 12:e85443, [10.7554/eLife.85443](https://doi.org/10.7554/eLife.85443) | the DL5 uEPSC recordings in the corpus |
| `MaleCNS` | the connectome paper, section 1 | counts and reconstruction completion rates |
| `GainControl` | Interactions between specialized gain control mechanisms in olfactory processing | LN classes performing local versus global gain control |
| `NRmap` | Mapping of multiple neurotransmitter receptor subtypes and distinct protein complexes to the connectome | receptor subunit localisation; the definitive answer on functional edge polarity (`ND-03`) |
| `Davis2020` | Davis et al. 2020, *eLife* 50901, [10.7554/eLife.50901](https://doi.org/10.7554/eLife.50901) | cell-type-resolved transcriptomes, visual system only |
| `Lappalainen2024` | Lappalainen et al. 2024, *Nature* 634:1132, [10.1038/s41586-024-07939-3](https://doi.org/10.1038/s41586-024-07939-3) | connectome-constrained network prior art; the methodological benchmark |
| `Rozenfeld2023` | Rozenfeld, Ehmann, Manoim, Kittel & Parnas 2023, *Nat Commun*, [10.1038/s41467-023-38575-6](https://doi.org/10.1038/s41467-023-38575-6) | independent release-site estimate, homeostatic active-zone plasticity |
| `Pooryasin2021` | Pooryasin et al. 2021, *Nat Commun*, "Unc13A and Unc13B…" | two release-machinery populations with distinct short-term plasticity |
| `OlfSNN2024` | Nanami et al. 2024, *Front Neurosci* 18:1384336, [10.3389/fnins.2024.1384336](https://doi.org/10.3389/fnins.2024.1384336) | comparison model; PN current-clamp recordings |

Two further sources are cited in the registries without a full corpus entry:

* Liu et al. 2022, connectomic features underlying synaptic strength — [PMC8825683](https://pmc.ncbi.nlm.nih.gov/articles/PMC8825683/) — the contact-to-release-site question; obtained only in part.
* Takagi et al. 2024, ORN population expansions and PN adaptation — [10.1038/s41467-024-50808-w](https://doi.org/10.1038/s41467-024-50808-w).

Where the registered numbers live: [`configs/neural/cell-dynamics-v0.4.json`](../configs/neural/cell-dynamics-v0.4.json)
and [`configs/neural/short-term-plasticity-v0.3.json`](../configs/neural/short-term-plasticity-v0.3.json).

## 5. Behaviour-specific sources

| Source | Supplies |
|---|---|
| Özdil et al. 2026, centralized brain networks controlling antennal grooming — [10.1038/s41467-026-72152-x](https://doi.org/10.1038/s41467-026-72152-x), collection [10.7910/DVN/N8ITTG](https://doi.org/10.7910/DVN/N8ITTG) | The checksum-locked antennal-grooming joint trajectory replayed by Track A ([card](../configs/datasets/ozdil-2026-antennal-grooming-trajectory.json)) |
| Johnston's-organ receptor spiking — [10.1016/j.cub.2013.10.006](https://doi.org/10.1016/j.cub.2013.10.006) | Class-level evidence that JO neurons spike, behind the LIF fallback registered for JO-F/JO-FD types |
| [10.1038/srep21841](https://doi.org/10.1038/srep21841) and [10.1038/s41467-019-09069-1](https://doi.org/10.1038/s41467-019-09069-1) | Odorant→receptor→glomerulus mapping used by the `eon-demo` storyboard, declared an engineering bypass |
| [10.1038/s41586-025-09554-2](https://doi.org/10.1038/s41586-025-09554-2) | The DNg97/oDN1 identity behind the Track A descending crosswalk |
| Seki et al. 2010 [10.1152/jn.00249.2010](https://doi.org/10.1152/jn.00249.2010); Inada et al. 2017 [10.1016/j.celrep.2017.05.049](https://doi.org/10.1016/j.celrep.2017.05.049) | Cell-type physiology for antennal-lobe local neurons and Kenyon cells |
| Gouwens & Wilson DM1 passive model, [ModelDB 118662](https://github.com/ModelDBRepository/118662) | Published passive-model source; redistribution from this project is disabled ([card](../configs/datasets/gouwens-wilson-2009-dm1-modeldb.json)) |

## 6. Methodological prior art

Used as method or as a boundary marker, never as a source of numbers.

| Work | Appropriate use here |
|---|---|
| [Effectome framework](https://doi.org/10.1038/s41586-024-07982-0) | Connectome weights as priors for fitted causal effects |
| [FlyVis](https://doi.org/10.1038/s41586-024-07939-3) | Visual type sharing, graded dynamics, task and physiology fitting precedent |
| [BrainTrace](https://doi.org/10.1038/s41467-026-68453-w) | Scalable fitting; evidence that background drive matters |
| [Inter-individual connectome variability](https://doi.org/10.1038/s41586-024-07686-5) | What one donor graph can and cannot represent |
| [BANC, female brain-and-cord comparison](https://doi.org/10.1038/s41586-026-10735-w) | Cross-dataset comparison boundary |
| [Adult mushroom-body connectome](https://doi.org/10.7554/eLife.62576) | Subsystem anchor |
| [Adult muscle motor-unit physiology](https://pmc.ncbi.nlm.nih.gov/articles/PMC7347388/) | Motor-neuron-to-muscle boundary |
| [Femoral chordotonal biomechanics](https://pmc.ncbi.nlm.nih.gov/articles/PMC10644877/) | Proprioceptive transduction boundary |
| [DoOR olfactory response database](https://pmc.ncbi.nlm.nih.gov/articles/PMC4766438/) | Odour response reference |

At the last evidence review, no peer-reviewed publication was known that combines MaleCNS
v1.0, fitted whole-CNS dynamics, peripheral sensory transduction, motor-neuron-to-muscle
dynamics, a physical body and closed-loop validation. This project does not claim to be that
publication either; see [What is claimed](../README.md#what-is-and-is-not-claimed).

## 7. Datasets, licences and redistribution status

Every card is in [`configs/datasets/`](../configs/datasets). None of these files is
redistributed by this repository.

| Card | Supplies | Licence as recorded |
|---|---|---|
| `malecns-v1.0` | The connectome | CC-BY |
| `berg-malecns-2025-supplement` | Structural and male–female comparison tables | Paper CC-BY-4.0; repository-file redistribution terms require confirmation |
| `morphology-canaries` | Skeleton SWCs used to detect a changed release | Part of the MaleCNS release |
| `shiu-2024-brain-model` | Stage 1 regression reference and archived outputs | MIT for repository and Edmond dataset v3.0 |
| `ozdil-2026-antennal-grooming` / `-trajectory` | Grooming supplementary data and the replayed trajectory | CC-BY-NC-ND-4.0 article terms; publisher data terms — verify before any redistribution |
| `gugel-2023-elife-85443` | uEPSC source data | CC0 for the Dryad release; preserve attribution |
| `nanami-2024-pn-current-clamp` / `-invivo-cellular-pack` | PN current-clamp recordings | MIT repository licence; preserve paper and original-recording attribution |
| `gouwens-wilson-2009-dm1-modeldb` | Published DM1 passive model | ModelDB terms require verification; redistribution disabled |
| `stage2-2026-09-09-intake` | Classification of a staged dataset drop | — |
| `stage2-reservations-v1` | Declares which staged files, variables and columns are **reserved and unopened** so they can serve as held-out data | — |

That last card is load-bearing for the project's validation discipline: data declared
reserved must stay unread until a preregistered test opens it.

## 8. Software dependencies

Runtime and development dependencies with their version bounds are in
[`pyproject.toml`](../pyproject.toml) and pinned exactly in `uv.lock`. Licence boundaries
for the components above are restated in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## 9. Citing this work

Cite the software release **and** the exact MaleCNS release a run used — the graph is the
scientific object, the code only executes it. Machine-readable metadata is in
[`CITATION.cff`](../CITATION.cff). Every run manifest records the dataset lock, the graph
hash, the commit and the resolved validation tier, so a result can be tied to the exact
inputs that produced it.
