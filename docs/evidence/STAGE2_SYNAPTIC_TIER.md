# Stage 2 synaptic tier and the exit gate

Status: two V2 legs evaluated, one passing; Stage 2 does not exit
Date: 2026-09-08
Highest project validation tier: V0 Structural

Immutable results:

| Artifact | Logical SHA-256 |
|---|---|
| `synaptic-structure-v1.json` | `545b8b34a6b17cacda076d09f725f18768eed5d64c667bbb323291117e79627a` |
| `uepsc-kinetics-holdout-v1.json` | `e5a68e2cf17b37cfd3048252cccf15a44e3be321da9b5f2347b9102cdd12b2ed` |
| `exit-gate-v1.json` | `e2a559476c70962ef31555e16a528820cfbe6b20b14fbe853e2fe92d7be6caf9` |

See [ADR-2026-008](../adr/ADR-2026-008-synaptic-tier-and-stage2-exit-gate.md).

## A second one-step GeNN defect

ADR-2026-006 predicted that rerunning Stage 1 after the axonal-delay repair would move GeNN one
step earlier and remove the offset. The shift happened — readout first spikes went from 59.0 and
26.1 ms to 58.9 and 26.0 ms — but the parity error stayed at exactly 0.1 ms.

GeNN labels a spike with the **start** of the integration interval that produced it; the NumPy
oracle and the Brian2 adapter both label it with the **end**. `neural_parity.run_genn` corrected
for this and documented it; the Stage 1 adapter in `circuit.py` did not. The two off-by-one
errors cancelled at the readout, so the original report recorded parity as passing when two
defects were in place.

With both fixed the 41-neuron transfer agrees across all three backends to **1.1e-13 ms with
zero timing outliers**. The small three-neuron parity fixture used the already-corrected adapter
and its numbers are unchanged.

## Can contact number carry the ND-04 type-pair scale?

Tested across **50 glomeruli and 265 projection neurons** against the published claim that
ORN-to-PN connections are homeostatically matched.

| Hypothesis | Observed | Supports structural matching |
|---|---|---|
| H1 total contacts per PN vary less than converging ORN count | CV 0.695 vs 0.603 | no |
| H2 contacts per connection fall as ORN count rises | Spearman rho −0.232 | weakly yes |
| H3 contacts per connection are "several dozen" (24–100) | median of medians 43 | consistent |

The extremes show the partial compensation directly:

```
glomerulus   converging ORNs   median contacts/connection   total contacts/PN
VA5                     12.7                         46.0                 811
DL2d                    13.3                         52.0                 752
VA7m                    18.3                         21.8                 438
...
VA2                     74.5                         87.8                6546
VA1v                    86.0                         12.0                1345
VA1d                    92.0                         12.5                1410
DA1                    150.5                         11.0                2134
```

The direction is right — the high-convergence pheromone glomeruli DA1, VA1d and VA1v have the
fewest contacts per connection — but total drive per PN still varies more across glomeruli than
ORN number does. **Contact number alone does not implement the matching.** If the published
matching is real it must be carried by release probability or receptor density, which is exactly
what `ND-04` already asserts. The assertion now has evidence behind it rather than none.

H3 is the first quantitative agreement between MaleCNS structure and an independent
physiological measurement anywhere in this project.

## The first physically grounded per-contact scale

Dividing the published 5–7 mV unitary EPSP by the measured contacts per connection:

| | at 5 mV | at 7 mV |
|---|---:|---:|
| minimum across glomeruli | 0.042 mV | 0.059 mV |
| median across glomeruli | 0.117 mV | 0.164 mV |
| maximum across glomeruli | 0.800 mV | 1.120 mV |

The registered engineering fallback of **0.2 mV per contact lies inside this range**, near the
top of the median band. That is the first physiological justification the value has had — it was
previously carried over from a whole-brain model of a different connectome with no cross-check.

It stays an engineering fallback. A scale derived from a cross-specimen unitary amplitude and
applied to all 50 glomeruli is a prior, and the 27-fold spread across glomeruli is precisely why
a single global number is wrong. The assumption register is not bumped: `ND-04`'s decision is
unchanged, and a derived prior is a result that belongs in an evidence artifact.

## The unitary-EPSC kernel fails its preregistered kinetics limit

The post-freeze feature review had recorded "no preregistered feature-level acceptance
thresholds" as a V2 blocker. Those thresholds were fixed and committed before the five
unconsumed chronic-exposure cells were opened.

| Criterion | Limit | Observed | Result |
|---|---|---|---|
| Sign: every held-out waveform inward | > 0 | minimum peak 27.689 pA | pass |
| Peak time, median absolute error | ≤ 1.0 ms | 0.300 ms | pass |
| Decay time, median absolute fractional error | ≤ 0.30 | **0.463** | **fail** |

Per-cell decay errors: 0.463, 0.881, 0.519, 0.350, 0.282 — four of five over the limit. The
kernel gets polarity and timing right and the decay wrong by about half again.

Peak amplitude was preregistered as reported-but-not-gated: the source paper's whole subject is
that chronic exposure changes this synapse, so an amplitude mismatch on exposure-state cells
cannot separate model error from a real state difference. For the record the kernel underpredicts
all five cells, by 3.2 to 25.8 pA, median 13.6 pA.

Both limits came from the 0.1 ms measurement grid and the 15 ms fitted decay constant, not from
the model errors already observed on the consumed solvent cells.

## Two V2 requirements have no registered source

**Receptor-aware polarity, `ND-03`.** The MaleCNS `receptorType` annotation is *gustatory
receptor identity* — 752 of 211,577 bodies, three values (`putative_ppk23`, `putative_ppk25`,
`putative_IR52b`). It is not postsynaptic neurotransmitter receptor expression and must not be
read as such. No connectome-mapped receptor resource exists either; the FlyWire whole-brain
literature states that the available predictions "lack neuropeptide predictions and receptor
expression data, an important gap given that neurotransmitters such as glutamate can be
excitatory or inhibitory." Polarity therefore stays transmitter-only, labelled as a regression.

**Release failure and short-term plasticity, `ND-06`.** The published description of this synapse
gives high release probability and strong short-term depression qualitatively. No paired-pulse
ratio, failure distribution or recovery time constant is published in a checksum-lockable form,
and no dataset is deposited.

## The Stage 2 exit gate

`stage2-exit-gate-v1` reads each leg from a checksum-pinned artifact instead of restating it, so
it cannot drift from the evidence and flips on its own when the evidence arrives.

| Leg | Evidence | Observed | Criterion | Passes |
|---|---|---|---|---|
| cellular | chronic-condition F-I sub-gate | true | equals true | **yes** |
| synaptic | uEPSC kinetics holdout | false | equals true | no |
| circuit | grooming transfer held-out coverage | 0.0 | ≥ 0.8 | no |
| ensemble | VAL-01 ensemble held-out evaluation | false | equals true | no |

**One leg of four. Stage 2 does not exit.** A partial pass is recorded so the remaining work
stays visible, not so the stage can be declared complete. The one passing leg carries its own
caveat: it scores firing rate only, on state-shifted cells from the same paper, using a model
that predicts no resting voltage, time constant or adaptation at all.

## What now blocks Stage 2

1. **No unconsumed recording of any kind remains.** Every registered F-I cell was consumed by the
   first frozen evaluation or the chronic-condition holdout; the last five uEPSC cells were
   consumed by the test above. Both the synaptic and ensemble legs need new data, not new code.
2. **The circuit leg's reference is not biological.** Held-out coverage is 0.0, and even a pass
   would be against archived FlyWire simulation output rather than a recording.
3. **`ND-03` and `ND-06` have no source.** Receptor-aware polarity and release/STP evidence do
   not exist in any acquirable, lockable form found so far.
4. **The decay kinetics are wrong.** A revised kernel must be fitted and then tested on a new
   independent holdout, because these five cells are now consumed too.
