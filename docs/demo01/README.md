# DEMO-01: where everything is

A closed loop through the whole released MaleCNS graph, built as an engineering
demonstration. **Tier V0 Structural. Nothing here is validated physiology and nothing here
changes the project's scientific status.**

Read in this order.

| document | what it is for |
|---|---|
| [`docs/evidence/DEMO01_FULL_GRAPH_EMBODIMENT.md`](../evidence/DEMO01_FULL_GRAPH_EMBODIMENT.md) | the record: every route measurement, the search result, what may and may not be claimed |
| [`docs/adr/ADR-2026-014-*.md`](../adr/) | the decisions and the alternatives that were rejected |
| [`PROGRESS.md`](PROGRESS.md) | the working ledger, kept so nothing regresses and no decision is silently revisited |
| [`PILOT.md`](PILOT.md) | the exploratory pilot that shaped the registered grid, published because it did |

## Contracts, all committed before the runs they govern

| contract | governs |
|---|---|
| `configs/experiments/demo01-operating-point-v1.json` | the **olfactory** search, which failed 0 of 24. Kept unchanged as a record of a failed experiment. |
| `configs/experiments/demo01-visual-operating-point-v1.json` | the visual search, which passed 31 of 108 |
| `configs/experiments/demo01-acceptance-v1.json` | what the demonstration may claim, gated on the identical-seed controls |
| `configs/scenarios/demo01-visual-approach.json` | the body, the cue and the frozen decoder |

## Code

| module | role |
|---|---|
| `src/flysim/demo01.py` | declared populations, the causal readout filter, the odour route's scorer |
| `src/flysim/demo01_visual.py` | the visual route: retinal map, retinotopic encoder, five-criterion scorer, decoder |
| `src/flysim/demo01_visual_probe.py` | the neural-only operating-point search |
| `src/flysim/demo01_body.py` | the FlyGym body, the cue and the ported station-keeping controller |
| `src/flysim/demo01_embodied.py` | the closed loop, the control variants and the synchronised recording |
| `src/flysim/demo01_acceptance.py` | applies the frozen contract. Cannot run a simulation or alter a threshold. |
| `src/flysim/demo01_render.py` | reads a finished recording and composites video. Cannot touch a simulation. |

## How to reproduce, in order

The order is not a convenience. Each step freezes something the next step is not allowed to
vary.

```
# 1. the network, scored on neural criteria with no behavioural quantity anywhere
PYTHONPATH=src python scripts/run_demo01_visual_search.py --root /srv/flybrain-data --progress

# 2. the decoder, on development scenarios only, with the network frozen
PYTHONPATH=src python scripts/tune_demo01_decoder.py --root /srv/flybrain-data

# 3. the evaluation: four identical-seed variants, then the verdict and the video
PYTHONPATH=src python scripts/run_demo01_embodied.py --root /srv/flybrain-data \
    --duration-s 20 --render --progress
```

Step 3 reads the operating point from step 1's artifact rather than the command line, so
the demonstration cannot drift from the network the search selected.

## The three things worth knowing before watching the video

**The retina is not executed.** All 66,533 photoreceptor output edges are zeroed by the
frozen sign policy, because fly photoreceptors are histaminergic and histamine is absent
from the transmitter model. Entry is one synapse downstream at the lamina.

**The turn direction is an engineering choice, not a result.** The decoder carries a sign
that may be -1 or +1, and the sweep measured one flip turning a +12.07 mm approach into a
-5.86 mm retreat while the cue-locked agreement barely moved. What the network determines is
which descending side is stronger for a given cue side.

**A single run proves nothing.** The predecessor demonstration walked 100.2 mm with every
synaptic weight zeroed. What licenses a causal claim here is that the readout-ablated and
stimulus-absent variants fail, from an identical seed, with the same body and decoder.
