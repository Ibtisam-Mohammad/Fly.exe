# How sources were used

**The list of sources is in the [README](../README.md#sources)** — the connectome, the
software, the papers behind registered parameters, the behaviour and mapping sources, the
prior art, and the dataset cards. This file does not repeat that list. It answers what the
list cannot: how a published number becomes a parameter here, what each dataset's licence
permits, what may *not* be claimed from a reused work, and which sources were read and
rejected.

## 1. How a published number becomes a registered parameter

A value from a paper is not part of this project until it appears in a `configs/` registry
with an assumption ID. Reading a paper is not registration, and the gap between the two is
where most errors live.

1. The value is extracted with its **measurement conditions** into
   [`docs/evidence/LITERATURE_PARAMETER_CORPUS.md`](evidence/LITERATURE_PARAMETER_CORPUS.md).
   Conditions are not decoration: several apparent conflicts between papers dissolve once the
   stimulation frequency or the recording preparation is read, and one does not.
2. It is given a **provenance class** — `M` measured, `P` population prior, `F` fitted,
   `E` engineering scaffold, `I` irrecoverable.
3. It is registered with an **assumption ID** in
   [`configs/assumptions.json`](../configs/assumptions.json), which is what run manifests and
   evidence bundles cite.

Where the families live:

| family | registry |
|---|---|
| cell dynamics | [`configs/neural/cell-dynamics-v0.4.json`](../configs/neural/cell-dynamics-v0.4.json) |
| short-term plasticity | [`configs/neural/short-term-plasticity-v0.3.json`](../configs/neural/short-term-plasticity-v0.3.json) |
| populations and crosswalks | [`configs/populations/`](../configs/populations) |
| scenarios and operating points | [`configs/scenarios/`](../configs/scenarios) |
| acceptance contracts | [`configs/experiments/`](../configs/experiments) |

**A registered value can still be wrong, and one is known to be.** The registered depression
pair — utilisation 0.22 and recovery 893 ms, from Nagel, Hong & Wilson 2015 — predicts 56 to
58 % depression at 7 Hz. Kazama & Wilson 2008 independently measured about 40 % at that
frequency. The corpus records this as a partial failure of the registered rule rather than
smoothing it over, and also records why it is not a clean falsification: the 40 % is a
discussion-section round number with no error bar, from a different glomerulus and a different
protocol.

## 2. Licences and redistribution

**Nothing in the source list is redistributed by this repository.** Each dataset is fetched by
`flysim data sync`, hashed into an immutable lock, and a changed checksum for an
already-locked dataset is a hard validation failure. The primary PDFs were read locally and
are not republished.

| card | licence as recorded | redistribution |
|---|---|---|
| `malecns-v1.0` | CC-BY | attribution required; not redistributed here |
| `berg-malecns-2025-supplement` | paper CC-BY-4.0 | repository-file terms **require confirmation** before any redistribution |
| `morphology-canaries` | part of the MaleCNS release | not redistributed |
| `shiu-2024-brain-model` | MIT, repository and Edmond dataset v3.0 | permitted with attribution; not redistributed here |
| `ozdil-2026-antennal-grooming` | article CC-BY-NC-ND-4.0 | supplementary-file terms **require verification**; the trajectory card carries publisher data terms |
| `gugel-2023-elife-85443` | CC0 for the Dryad release | permitted; attribution preserved by choice |
| `nanami-2024-pn-current-clamp`, `-invivo-cellular-pack` | MIT repository licence | attribution to the paper, the repository **and the original recordings** |
| `gouwens-wilson-2009-dm1-modeldb` | ModelDB terms unverified | **redistribution disabled in code** |

The asymmetry is deliberate: where terms are unverified the project disables redistribution
rather than assuming permission.

## 3. Reserved and unopened data

[`configs/datasets/stage2-reservations-v1.json`](../configs/datasets/stage2-reservations-v1.json)
declares which staged files, and which variables and columns inside them, are **reserved**.
Reserved data is held out so that it can later serve as an independent test. Reading it spends
it, and a value fitted to it can never afterwards be validated by it. This is the mechanism
that makes a future held-out test possible at all, so it is enforced rather than encouraged.

## 4. Sources that were read and not used

A source that was looked for and rejected belongs in the audit trail, because its absence
explains a gap that would otherwise look like an oversight.

* **Croset, Treiber & Waddell 2018**, *eLife* 7:e34550 —
  [10.7554/eLife.34550](https://doi.org/10.7554/eLife.34550), GEO GSE95361 / SRA SRP128516.
  Located while searching for transmitter-identity evidence and unusable for it: a midbrain
  single-cell atlas is not a receptor-localisation measurement.
* **A unit-resolved multi-animal PN current-step source** — not found. No public repository
  hosts raw patch-clamp traces for *Drosophila* projection neurons or ORN→PN synapses, and
  neither Gouwens & Wilson 2009 nor Kazama & Wilson 2008 deposited raw data. The cellular tier
  therefore stays single-specimen, and says so.
* **An independent uEPSC holdout** — not found, which is why the refitted prior is labelled a
  prior and not a test.
* **Flybody** and **FlyMimic** — consulted as body baselines and not adopted; switching would
  require an un-checksummed mesh download, against the dataset-locking rule.

**One citation in the register is a correction.** An early record cited
[10.1016/j.neuron.2008.04.024](https://doi.org/10.1016/j.neuron.2008.04.024) as Kazama & Wilson
2008. That DOI is a different paper — Kruglikov & Rudy 2008, on neocortical GABA release. The
correct DOI is [10.1016/j.neuron.2008.02.030](https://doi.org/10.1016/j.neuron.2008.02.030).
The wrong one is kept in the register so the substitution stays visible instead of vanishing.

## 5. Reusing a work without inheriting its claims

Each of these is used for something specific, and the second column is the part that matters:
the claim the work does **not** license here. The full table is
[AGENTS.md section 11](../AGENTS.md).

| work | must not be claimed |
|---|---|
| MaleCNS | living dynamics, exact functional weights, or the body or state of the source fly |
| Shiu et al. 2024 | that its global LIF constants or transmitter-sign rules are MaleCNS physiology |
| Effectome | that anatomy alone determines state-dependent causal strength |
| FlyVis | that its learned visual parameters cover the rest of the CNS, or phototransduction |
| BrainTrace | that region-level calcium fitting recovers cell or synapse physiology |
| NeuroMechFly / FlyGym | that joint commands and ideal sensors are biological motor-neuron, muscle or receptor signals |
| Flybody | that female rigid-body geometry, learned control and phenomenological aerodynamics are an exact male |
| FlyMimic | that it is a complete six-leg or whole-body neuromuscular solution |

At the last evidence review, no peer-reviewed publication was known that combines MaleCNS
v1.0, fitted whole-CNS dynamics, peripheral sensory transduction, motor-neuron-to-muscle
dynamics, a physical body and closed-loop validation. This project does not claim to be that
publication either; see
[What is and is not claimed](../README.md#what-is-and-is-not-claimed).

## 6. Citing this work

Cite the software release **and** the exact MaleCNS release a run used — the graph is the
scientific object and the code only executes it. Machine-readable metadata is in
[`CITATION.cff`](../CITATION.cff). Every run manifest records the dataset lock, the graph hash,
the commit and the resolved validation tier, so a result can be tied to the exact inputs that
produced it.

One caveat about commit identifiers: the history was rewritten on 2026-09-12 and again on
2026-09-14, so any commit hash quoted in an older narrative document or run manifest is a
legacy identifier and needs mapping before it is used as a provenance claim.
`HISTORY_REWRITE_STATUS` in [AGENTS.md](../AGENTS.md) records both.
