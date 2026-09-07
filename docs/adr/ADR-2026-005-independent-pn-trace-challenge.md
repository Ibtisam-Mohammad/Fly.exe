# ADR-2026-005 — Independent PN trace challenge

Status: accepted

Date: 2026-09-08

Changes assumptions: `ND-01`, `ND-02`, `ND-05`

## Decision

Lock the raw projection-neuron current-clamp trace published with Nanami et al. 2024 as a
strictly external challenge. It may not be used for parameter fitting, model-family selection, or
post-hoc threshold changes. The revised PN model will continue to use only the originally
registered Gugel fit cells and the Gouwens passive priors.

The trace is normalized before response analysis, but the eight stimulus windows are not silently
treated as fully measured protocol metadata. The repository notebook reconstructs their alignment
from the first voltage threshold crossing and lists step levels 3 through 10 without an explicit
physical unit. Both limitations remain attached to every derivative.

This single cell cannot award V1. A separate multi-animal, type-resolved holdout remains required
for cellular-tier evidence.

## Reason

The first Gugel held-out set has already been consumed by the frozen steady-state LIF evaluation.
Reusing those cells to choose and validate a replacement would leak validation evidence. The
Nanami trace was produced by a different group and protocol and was not used in the first fit, so
it can expose time-domain failure after the replacement is frozen.

The Gugel Figure 7 F-I source is a slow triangular ramp at 4.5 pA/s, reported in overlapping 50 ms
rate windows. A ramp-aware dynamic model is therefore the next justified replacement for the
failed pointwise steady-state transfer.

## Sources

- <https://doi.org/10.3389/fnins.2024.1384336>
- <https://github.com/tnanami/fly-olfactory-network-fpga>
- <https://doi.org/10.7554/eLife.85443>

## Validation effect

This decision locks one independent challenge cell and prevents held-out reuse. It awards no
validation tier. The next implementation gate is a preregistered ramp-aware adaptive model fitted
only to the original training cells, followed by one sealed evaluation of the Nanami trace.
