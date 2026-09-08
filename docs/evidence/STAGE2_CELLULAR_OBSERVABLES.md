# Stage 2 cellular observables and heterogeneous-cell execution

Status: first measured cellular observables recorded; V1 remains blocked; two registered
values shown to depend on their measurement rule (ADR-2026-009)
Date: 2026-09-08
Immutable results: `cellular-observables-v1.json` logical SHA-256 `4796191ebd8c1ecd…`;
`cellular-observables-v2.json` logical SHA-256 `d6dc1c03331c814f…` (file
`7cbacca867818a39…`); `projection-neuron-ensemble-v1.json` logical SHA-256 `8759a6dd9f991255…`
Highest project validation tier: V0 Structural

## Corrections from the 2026-09-08 review

The independent review (ADR-2026-009) reissued the measurement contract as
`stage2-cellular-observables-v2`. It reproduces every v1 value exactly and adds three
diagnostics that expose what the primary values assume. The v1 table below is left as written;
read it with these corrections.

| Value | v1 (primary rule) | Under the alternative rule | What the difference is |
|---|---|---|---|
| Membrane time constant | 32.566 ms, asymptote pinned to the pre-step baseline −57.58 mV | **47.6 ms**, free asymptote settles at −60.16 mV, R² 0.881 | the pre-step baselines span 5.7 mV across sweeps, so the pin is an assumption; honest value is a 33 to 48 ms bracket |
| Spike threshold | −38.402 mV at a 10 mV/ms upstroke criterion | **−41.838 mV** at 10% of each spike's peak slope | median peak upstroke is 10.03 mV/ms, so only 51% of spikes reach the criterion and those that do reach it near their steepest point |
| Spike counts 2 to 10 pA | 1, 10, 17, 21, 24 (10 mV prominence) | 0, 10, 15, 23, 30 (−35 mV crossing); 1, 21, 26, 29, 40 (5 mV) | spikes are 8.9 to 13.8 mV high, so the detector is marginal; v1 called the first two "agreeing" |
| Shortest interspike interval | 15.8 ms | 14.4 ms | detector-dependent; and it is an upper bound on refractoriness, registered as a value |
| LN resting potential, four animals | −50.789 mV median, whole-trace masked median | **−49.02 mV** median before the first spike (−47.55, −48.38, −50.59, −49.67) | every trial carries an unpublished stimulus from about 1 to 4 s and ten seconds of after-hyperpolarization, and the whole-trace median is that post-stimulus level |

The 20 mV sensitivity block reports a 28.1 ms charging constant and a 2360 MΩ input resistance.
Those are artifacts: at 20 mV prominence the detector misses every spike and the code then fits
sweeps with 24 to 33 mV deflections as passive. v2 reports the deflection beside them. Neither
number may be quoted.

None of this changes `cell-dynamics-v0.3`; what a v0.4 should carry is listed in ADR-2026-009
and AGENTS section 15.

## What changed

Two things. The project now has measured cellular observables in physical units rather than
only fitted model parameters, and the engines can carry per-type membrane parameters instead of
one global value. Neither awards a tier. See
[ADR-2026-007](../adr/ADR-2026-007-cellular-tier-sources.md).

## The Nanami stimulus question is closed, and the answer removes a planned evaluation

The manifest for the reserved PN trace recorded `step_levels: [3 … 10]` as the in vivo protocol
with unresolved units. Those integers are the list `I4` in `02_plot_figs/analyze_PQNtest.ipynb`,
which sets the stimulus of the **in-silico PQN model** plotted in the row above the recording.
The paper says of that model: *"All variables and parameters are purely abstract with no physical
units."* The in vivo protocol is described only as *"Multiple levels of depolarizing currents
were injected into the soma of individual PNs."*

The amplitudes are therefore **irrecoverable**, not unresolved. Two further reconstruction errors
are withdrawn with them: the extraction offset is 303.5 ms before the first threshold crossing,
not 306.5 ms, and the notebook plots three one-second windows at four-second spacing, not eight at
two-second spacing.

The superseded manifest stays on disk unchanged, because the frozen dynamic-revision contract
pins its SHA-256 and the frozen fit has to stay reproducible.

**The reserved trace is retired as a scoring source.** Two independent blockers: without stimulus
amplitudes no current-referenced observable can be compared at all, and the somatic spikes do not
reach the primary 10 mV detection prominence, so across the three tested prominences the whole
20 s trace yields between 0 and 25 spikes. Both the spike count and any adaptation statistic
would be properties of the detector rather than of the recording.

## What is locked instead

`nanami-2024-invivo-cellular-pack-v1`, 47 files checksum-locked at the same pinned commit
`c064f47da7a1f8c4e9137c09b5e327d1a38ab9f4`:

| Class | Animals | Stimulus | Origin |
|---|---:|---|---|
| MBON-alpha1 | 1 | **unit-resolved**, 1 s pulses at 2, 4, 6, 8, 10 pA | Nanami et al. 2024 |
| Antennal-lobe LN | 4 | irrecoverable | Seki et al. 2010 |
| Kenyon cell | 1 | irrecoverable | Inada et al. 2017 |
| Olfactory PN | 1 | irrecoverable | Nanami et al. 2024 |

The MBON-alpha1 protocol is the only unit-resolved current-step protocol in any registered
source. The paper states *"1-s square pulses with incrementing amplitudes (0–10 pA, 2 pA steps)"*
and the published injected-current file reproduces exactly that: five sweeps at 2, 4, 6, 8 and
10 pA, each 1000.0 ms long. That agreement was derived from the data, not assumed.

## Two analysis rules that had to be fixed first

A **50 ms spike-prominence window** absorbed the slow step depolarization into the prominence, so
noise on the rising phase cleared a 10 mV threshold. In-step counts were 1, 28, 19, 27, 44 and
non-monotonic in injected current. At 10 ms they are 1, 10, 17, 21, 24, monotonic, and agree with
an independent fixed −35 mV threshold count of 0, 10, 15, 23, 30 on the same sweeps.

An **ungated single-exponential fit** reported a 268 ms membrane time constant from the post-step
relaxation. The relaxations overshoot the pre-step baseline and drift, so the fit was describing
an after-current, not the membrane. With an R² floor of 0.9 and a requirement that the fitted
time constant not exceed the transient actually observed, four of five sweeps are rejected — two
because a spike follows offset, two that would have reported 239.6 ms and 102.6 ms.

Both calibrations happened before any model was scored, and the contract sets no pass/fail
threshold on any measured value, so neither can bias a comparison. Both are recorded in
`configs/experiments/stage2-cellular-observables.json` rather than presented as blind choices.

## Measured values

MBON-alpha1, one cell, contract `stage2-cellular-observables-v1`:

| Observable | Value | Provenance |
|---|---|---|
| Resting potential | −60.354 mV (range −63.174 to −57.506 across sweeps) | measured |
| Membrane time constant | **32.566 ms**, R² 0.911, one surviving sweep | measured |
| Spike threshold | −38.402 mV at a 10 mV/ms upstroke criterion | measured |
| Shortest interspike interval | 15.8 ms | measured upper bound on refractoriness |
| Rheobase | at or below 2 pA | bracketed, not resolved |
| F-I | 1, 10, 17, 21, 24 Hz at 2, 4, 6, 8, 10 pA | measured, monotonic |
| Adaptation ratio | 0.749 median | measured; below 1, so this cell facilitates |
| Input resistance | not measurable | every sweep is suprathreshold |

The 32.566 ms sits just above the 16.4 to 30.6 ms range of the three pinned Gouwens and Wilson
DM1 passive fits, which is the only independent cross-check available.

Antennal-lobe local neurons, four animals: resting potential −48.203, −50.672, −51.062 and
−50.906 mV, median −50.789 mV. This is the only multi-animal cellular distribution in the
project.

## Somatic spike amplitude by class, and what it does not show

| Class | Median somatic amplitude | Median peak | Overshoots 0 mV |
|---|---:|---:|---|
| Antennal-lobe LN | 33.4 mV | +29 mV | yes, 29 of 40 trials |
| Kenyon cell | 7.0 mV | −44.3 mV | no |
| Olfactory PN | 5.6 mV | −51.1 mV | no |

A six-fold spread, so **no single absolute spike threshold serves all four classes**. This does
not classify any of them as graded. Axonal spike initiation followed by passive attenuation to
the soma produces exactly the same measurement, and that is the published conclusion for
Drosophila projection neurons in the source already pinned as the project passive prior. The
`AGENTS.md` section 15 spiking/graded registry choice stays open.

## Heterogeneous-cell execution

`cell-dynamics-v0.3` adds numeric parameter sets with **per-value** provenance, because a set that
measures resting voltage and time constant but falls back to an engineering reset voltage is
neither measured nor a scaffold. `MBON07` binds the measured set; its MaleCNS identity is
confirmed from the annotation table itself, where `MBON07` carries instance `MBON07(a1)`.

Both engines now accept per-neuron membrane parameter arrays:

- The **GeNN** engine promotes the eight kernel coefficients from shared parameters to per-neuron
  variables only when the resolution is heterogeneous, so a homogeneous graph keeps the cheaper
  compiled kernel and every recorded Track A run is bit-for-bit unchanged. The model identity
  hash covers the per-neuron values, so a parameter change cannot reuse a stale build.
- The **NumPy oracle** broadcasts the shared parameters first and then overwrites with supplied
  arrays, which is why the Brian2 and GeNN parity comparisons are unaffected.
- Both engines **refuse** a graph containing neurons resolved to the graded regime. Substituting
  the spiking model for them would be an undeclared modelling decision.

Resolved against the full traced graph:

```
neurons                          165,122
distinct cell types               11,752
mbon07-alpha1-measured-v1              4 neurons
shiu-2024-global-lif-fallback-v1 165,118 neurons
fallback fraction                 99.998%
measured fraction                  0.0024%
```

That 0.0024% is the honest state of type-resolved physiology in this project. Engines report it
in run metadata so no run can appear to be executing fitted physiology.

Stage 1 records the same resolution but keeps execution on the source-faithful LIF baseline.
Enabling type-resolved execution there would change every frozen Stage 1 number with no new
validation evidence to justify it.

## VAL-01 uncertainty ensemble, and what it exposes

`VAL-01` requires five parameter samples by four seeds. The frozen projection-neuron family had
two per-cell draws and a deterministic integrator, so it met neither half. Contract
`stage2-pn-uncertainty-ensemble-v1` widens it using only the two originally registered training
cells: parameter samples come from rejection sampling over candidates whose training loss is
within 25% of the best on the same cell, and each seed varies the unobserved membrane and
adaptation state at protocol onset rather than injecting a noise process the data cannot
constrain.

130 of the 768 candidates are accepted, and the ranges they span are the finding:

| Parameter | Minimum | Median | Maximum | Max/min |
|---|---:|---:|---:|---:|
| Rheobase (pA) | 21.205 | 62.013 | 79.194 | 3.7 |
| Membrane tau (ms) | 16.432 | 21.331 | 30.600 | 1.9 |
| Refractory (ms) | 1.124 | 17.050 | 29.942 | 26.6 |
| Adaptation tau (ms) | 50.676 | 170.498 | 1945.076 | 38.4 |
| Adaptation increment | 0.000 | 0.068 | 0.197 | — |

**The two training cells do not constrain this family.** A 25% loss tolerance admits a 27-fold
range of refractory periods and a 38-fold range of adaptation time constants, and the accepted
set includes `adaptation_increment = 0.0` — a model with no adaptation at all is within 25% of
the best fit. The ensemble mean scores 18.847 Hz training RMSE against the 7.630 Hz previously
reported for the two-draw family, which makes plain that the 7.630 Hz figure was a property of
scoring each per-cell best fit on the cell that selected it, not of a well-determined family.

Reading a consumed cell is guarded at the point of the read, not merely by contract text: every
recorded-cell identifier handed to the reader is checked against the consumed list and a match
raises.

The ensemble is deliberately **unscored**. Every registered F-I recording has already been
consumed, by the first frozen evaluation or by the chronic-condition holdout, so evaluating the
widened family on any of them would leak validation evidence.

## Claim boundary

No tier is awarded. V1 requires that a fitted model predict resting voltage, membrane time
constant and adaptation distributions on cells it never saw, for the cell types the model
actually claims. No projection-neuron type has a multi-animal, type-resolved measurement of any
of the three, and the one unit-resolved protocol in the whole registered corpus is a single cell
of a class Track A does not drive.

## Open blockers

1. No unit-resolved current-step protocol exists for any projection-neuron type.
2. The Gugel Dryad deposit holds four source-data files the eLife CDN does not carry, including
   two more Figure 7 files. Dryad now serves downloads behind a proof-of-work bot wall, so
   scripted acquisition under the project checksum-locking rule is currently blocked.
3. Input resistance is unmeasurable from the MBON protocol because every sweep is suprathreshold.
4. The VAL-01 ensemble now has the required shape, but it cannot be scored: no unconsumed F-I
   recording exists in any registered source.
