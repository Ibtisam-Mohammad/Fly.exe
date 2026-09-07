# Stage 2 projection-neuron physiology foundation

Status: first frozen fit evaluated; cellular gate failed, synaptic aggregate gate passed  
Date: 2026-09-08  
Highest project validation tier: V0 Structural

## What is locked

The pinned ModelDB source for Gouwens and Wilson 2009 is checked out at commit
`cf5a57dee863cea502e78ef5bc481369253900d9`. The normalizer extracts three published DM1 passive
model fits with their original units and source-file hashes:

| Published model | Rm (ohm cm2) | Cm (uF/cm2) | Ri (ohm cm) | Derived Rm x Cm (ms) |
|---|---:|---:|---:|---:|
| cell 1 | 8,300 | 2.57 | 163.9 | 21.331 |
| cell 2 | 20,400 | 1.50 | 102.5 | 30.600 |
| cell 3 | 20,800 | 0.79 | 266.1 | 16.432 |

These are `P/F` priors: published fits from other flies, not measurements from the MaleCNS specimen
and not independent validation traces.

All six official eLife source workbooks for Gugel et al. 2023 are locally checksum-locked. The Figure
7 workbook is normalized without Excel-specific runtime state into:

- 7,280 DL5 current/firing-rate rows across eight recorded cells;
- 24,012 DL5 unitary-EPSC waveform rows across twelve recorded cells;
- an immutable manifest preserving source identity, units, condition, and recorded-cell IDs.

Only solvent controls enter the baseline fit. Chronic E2-hexenal recordings remain available as a
separate state perturbation. The preregistered split uses six fit recordings and five held-out
recordings; no recorded cell occurs in both sets.

## Locked losses

The F-I objective is a per-cell Huber loss over the registered current ramp. Held-out reporting adds
RMSE, rheobase error, and gain error. The unitary-EPSC objective is a baseline-corrected waveform
Huber loss over 0–200 ms. Held-out reporting adds waveform RMSE, peak amplitude, peak time, and decay
time errors.

`flysim stage2 readiness --root /srv/flybrain-data` verifies four artifact hashes, units, a nonempty
recorded-cell split, positive loss weights, and the claim boundary. The current report is fit-ready
with zero blockers.

## Scientific boundary

The source flies are two-day-old females, and the response cells are DL5 projection neurons. The
project target is a five-day-old male and Track A uses DM1/DM4 relays. The first fitted object is
therefore a cross-specimen uniglomerular-PN family distribution. It must not be reported as direct
DM1, DM4, MaleCNS-donor, or brain-wide physiology.

## First frozen result

The first bounded fit was frozen before held-out evaluation. The selected steady-state LIF family
has a 31 pA rheobase, 30.6 ms membrane time constant, and 24 ms refractory period. Its held-out F-I
RMSE is 19.062 Hz versus a 15.523 Hz fit-cohort biological baseline: normalized ratio 1.228, which
fails the preregistered 1.2 limit.

The selected causal difference-of-exponentials uEPSC kernel has a 47.25 ms onset, 0.75 ms rise time
constant, 15 ms decay time constant, and 24.467 pA population amplitude. Its held-out RMSE is 4.517
pA versus a 4.087 pA biological baseline after applying the same baseline subtraction to both:
normalized ratio 1.105, which passes the aggregate limit.
No continuous fitted parameter is on a search boundary.

The immutable result is `projection-neuron-fit-v3.json`, SHA-256
`5ee63453c3c12d7ada3754245b93c172567e1ecaf6b0c4a4a51fec958a336780`. The earlier v1 exploratory
run used a truncated refractory search range, and v2 used an asymmetric baseline comparison. Both
are superseded and are not evidence.

No V1 or V2 evidence has been awarded. The F-I failure blocks V1. The uEPSC aggregate result still
needs preregistered peak/timing/decay feature review before a selected V2 decision. Because the
held-out cells have now been inspected, any revised active-cell family must be tested on a new
independent holdout rather than retuned against these recordings.
