# ADR-2026-004 — First Stage 2 projection-neuron physiology pack

Status: accepted  
Date: 2026-09-07  
Changes assumptions: `ND-01`, `ND-02`, `ND-05`, `ND-09`

## Decision

Use two complementary, cross-specimen sources for the first fitted projection-neuron family:

- Gouwens and Wilson 2009 DM1 electrophysiology/model source as a passive, morphology-aware
  parameter prior. Preserve the three published fits rather than averaging them into one cell.
- Gugel, Maurais, and Hong 2023 Figure 7 solvent-control DL5 recordings as the first cellular and
  unitary-EPSC fit/held-out data. Split by recorded cell before fitting: six fit recordings and
  five held-out recordings across the two assays. Retain chronic-odor recordings, but exclude them
  from the baseline-state fit.

The fitted object is initially a shared uniglomerular projection-neuron family. DL5 response values
must not be relabelled as DM1 measurements. No V1 or V2 tier is awarded by acquisition, normalization,
readiness, or fitting alone; an immutable held-out evidence bundle is required.

## Reason

The Gouwens source provides DM1-specific passive cable fits but not an independent raw-trace
validation set. The Gugel source provides individual-cell F-I curves and unitary-EPSC waveforms with
a specimen-level split, but for DL5 in younger females. Together they permit an honest first fit while
keeping type, sex, age, and preparation mismatches visible.

## Sources

- <https://doi.org/10.1523/JNEUROSCI.0764-09.2009>
- <https://modeldb.science/118662>
- <https://doi.org/10.7554/eLife.85443>
- <https://datadryad.org/dataset/doi:10.5061/dryad.v15dv420q>

## Alternatives considered

- Literature summary statistics alone: rejected as the primary fitting source because they do not
  support a recorded-cell held-out split.
- Treat the three published DM1 model fits as V1 validation: rejected because they are exposed fitted
  model parameters, not independent held-out recordings.
- Pool chronic odor exposure with solvent controls: rejected because it changes neural state and would
  confound the fixed baseline condition.
- Transfer DL5 values directly to DM1/DM4: rejected; the first model is a family distribution with an
  explicit type mismatch.

## Validation effect

This decision makes the first Stage 2 fit data-ready and fixes its losses and split. It awards no
validation tier. V1 and V2 remain prospective until parameters are frozen and evaluated on the
registered held-out cells.
