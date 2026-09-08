# ADR-2026-007 — Cellular-tier sources and the Nanami stimulus resolution

Status: accepted

Date: 2026-09-08

Changes assumptions: `ND-01`, `ND-02`

```yaml
decision_id: ADR-2026-007
date: 2026-09-08
changes_assumptions: [ND-01, ND-02]
old_decision: >-
  The Nanami PN manifest recorded stimulus levels 3 through 10 as the in vivo protocol with
  "unresolved source-code units", and the project planned one sealed external evaluation of
  that trace once the units were resolved. No cellular observable had been measured from any
  source; V1 was tracked as a fitting problem.
new_decision: >-
  The stimulus levels are withdrawn: they are the dimensionless amplitudes of the in-silico
  PQN model, not of any recording, and the in vivo amplitudes are irrecoverable. The reserved
  PN trace is retired as a scoring source. The remaining in vivo recordings redistributed with
  the same pinned commit are locked as a cellular pack, and cellular observables are measured
  under a preregistered contract that refuses every unit-bearing observable for a source whose
  stimulus was never published.
reason: >-
  V1 requires measured resting voltage, membrane time constant and adaptation. The project had
  none, and the one external challenge it was holding could not be scored for two independent
  reasons that only became visible on reading the source code and the paper Methods together.
primary_sources:
  - https://doi.org/10.3389/fnins.2024.1384336
  - https://github.com/tnanami/fly-olfactory-network-fpga
  - https://doi.org/10.1152/jn.00249.2010
  - https://doi.org/10.1016/j.celrep.2017.05.049
alternatives_tested:
  - completing the Gugel Dryad acquisition to reach its unimported Figure 5 to 7 source data
  - treating the PQN model levels as pA and scoring the PN trace against them
  - reporting the post-step relaxation time constant without a fit-quality gate
validation_effect: >-
  One membrane time constant, one input-resistance bracket and one F-I curve are now measured
  in physical units, for one MBON-alpha1 cell. A four-animal resting-potential distribution is
  measured for antennal-lobe local neurons. No projection-neuron type has any of the three V1
  observables. No tier is awarded and V1 remains blocked.
approved_by: project-owner
```

## What the stimulus levels actually are

The Nanami PN manifest recorded `step_levels: [3, 4, 5, 6, 7, 8, 9, 10]` for the in vivo
recording. Those integers are the list `I4` in `02_plot_figs/analyze_PQNtest.ipynb`, which sets
the stimulus amplitudes of the **in-silico PQN model** in the row above the in vivo trace in the
same figure. The paper states of that model: *"All variables and parameters are purely abstract
with no physical units."*

The in vivo PN protocol is described in the Methods only as *"Multiple levels of depolarizing
currents were injected into the soma of individual PNs."* No amplitude is published anywhere in
the paper or the repository. The units are therefore not unresolved pending further work; they
are **irrecoverable**, provenance class `I`.

Two further reconstruction errors are withdrawn at the same time. The extraction offset is
303.5 ms before the first threshold crossing, not 306.5 ms: `plot_wave_PN` sets
`t0 = t_cross - 0.03 - w + 0.25` with `w = 0.0235` and keeps samples after `t0 - 0.5`. And the
notebook plots three one-second display windows at four-second spacing, not eight windows at
two-second spacing; the eight came from the eight in-silico levels.

The superseded manifest is left on disk unchanged, because the frozen dynamic-revision contract
pins its SHA-256 and the frozen fit must stay reproducible. The correction is carried in the new
pack manifest, which names each withdrawn field and the evidence against it.

## Why the reserved trace is retired

Two independent blockers, either of which is sufficient:

1. With no stimulus amplitudes, no current-referenced observable can be compared at all.
2. The somatic spikes in that trace do not reach the primary 10 mV detection prominence. Across
   the three tested prominences the whole 20 s trace yields between 0 and 25 spikes, so both the
   spike count and any adaptation statistic are properties of the detector rather than of the
   recording.

The trace stays locked as a resting-potential and somatic-amplitude reference.

## What is locked instead

The same pinned commit redistributes three more in vivo sources, now checksum-locked as
`nanami-2024-invivo-cellular-pack-v1` across 47 files:

- **MBON-alpha1**, the only unit-resolved protocol in any registered source. The Methods state
  *"1-s square pulses with incrementing amplitudes (0–10 pA, 2 pA steps)"*, and the published
  injected-current file reproduces exactly that: five sweeps at 2, 4, 6, 8 and 10 pA, each
  1000.0 ms long. Newly reported in Nanami et al. 2024.
- **Antennal-lobe local neurons**, forty traces across four animals, from Seki et al. 2010. The
  only multi-animal source in the pack. Stimulus amplitudes are not published.
- **One Kenyon cell**, from Inada et al. 2017. Stimulus amplitudes are not published.

## Why the measurement contract separates stimulus resolution

Every unit-bearing observable — membrane time constant, input resistance, rheobase, F-I — is
refused for a source whose stimulus amplitudes were never published. That refusal is the point:
it is what stops an irrecoverable protocol from being laundered into a membrane time constant by
a later query that joins the tables.

## Two analysis rules that had to be fixed before any number was believable

A **50 ms prominence window** absorbed the slow step depolarization into the spike prominence, so
noise on the rising phase cleared a 10 mV threshold. In-step counts were 1, 28, 19, 27, 44 and
non-monotonic in injected current. At 10 ms they are 1, 10, 17, 21, 24 and monotonic, agreeing
with an independent fixed −35 mV threshold count of 0, 10, 15, 23, 30 on the same sweeps.

A **single-exponential fit with no quality gate** reported a 268 ms membrane time constant from
the post-step relaxation. The relaxations overshoot the pre-step baseline and drift, so the fit
was describing an after-current and a drifting baseline. With an R² floor of 0.9 and a
requirement that the fitted time constant not exceed the transient actually observed, three of
the five sweeps are rejected — they would have reported 239.6 ms and 102.6 ms — and one clean
fit survives at **32.57 ms with R² = 0.911**, which sits just above the 16.4 to 30.6 ms range of
the pinned Gouwens and Wilson DM1 passive fits.

Both calibrations happened before any model was scored against these traces, and the contract
sets no pass/fail threshold on any measured value, so neither can bias a comparison. Both are
recorded in the contract rather than presented as blind choices.

## Somatic spike amplitude is not a signal-regime classifier

Median somatic spike amplitude differs six-fold across the pack: antennal-lobe LNs 33.4 mV with
overshoot past 0 mV in 29 of 40 trials; MBON-alpha1 detected at 10 mV prominence; the Kenyon
cell 7.0 mV peaking at −44.3 mV; the projection neuron 5.6 mV peaking at −51.1 mV.

This constrains the observation model and shows that no single absolute spike threshold serves
all four classes. It does **not** classify any of them as graded. Axonal spike initiation
followed by passive attenuation to the soma produces exactly the same measurement, and that is
the published conclusion for Drosophila projection neurons in Gouwens and Wilson 2009 — the
source already pinned as the project passive prior. The `AGENTS.md` section 15 spiking/graded
registry choice therefore stays open, and no cell type moves out of the unresolved regime on
this evidence.

## Alternatives considered

- **Complete the Gugel Dryad acquisition.** The deposit at `doi:10.5061/dryad.v15dv420q` holds
  four source-data files the eLife CDN does not carry, including two more Figure 7 files.
  Dryad now serves downloads behind a proof-of-work bot wall, so scripted acquisition under the
  project checksum-locking rule is not currently possible. Recorded as a blocker, not abandoned.
- **Treat the PQN levels as pA.** Rejected: the authors state the model is dimensionless, and the
  numbers belong to a different row of the figure.
- **Report the 268 ms relaxation with a caveat.** Rejected: a caveat on a number that is
  measuring baseline drift is worse than no number, because downstream code reads the number.

## Validation effect

This decision produces the project's first measured cellular observables in physical units and
records precisely which V1 requirements remain unmet. It awards no tier. V1 additionally
requires a fitted model to predict these distributions on cells it never saw, for the cell types
the model actually claims, and no projection-neuron type currently has a multi-animal,
type-resolved measurement of any of the three required observables.
