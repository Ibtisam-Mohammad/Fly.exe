"""Is the grooming readout starved of gain, or starved of sign?

30.2 per cent of the grooming readout's input contacts were active while it produced zero
spikes. Three candidate causes: the gain is too low, the excitation is cancelled by
inhibition, or a large share of its input carries no sign at all because ND-10's
transmitter-only regression left it unresolved and the frozen policy sets unresolved to
zero -- a contact that exists in the connectome and transmits nothing in the model.

This separates them structurally, with no simulation, by comparing the readout that stays
silent against the two that fire.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/mnt/i/AI/fly_brain/src")

from flysim.config import load_json
from flysim.connectome import SparseConnectome
from flysim.demo02 import Demo02Populations
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.sensory_atlas import SensoryAtlas

ROOT = Path("/srv/flybrain-data")
REPO = Path("/mnt/i/AI/fly_brain")

graph = SparseConnectome.load(ROOT / "derived/male-cns-v1.0/graph")
ann = ROOT / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
tx = ROOT / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
visual = load_json(REPO / "configs/experiments/demo01-visual-operating-point-v1.json")
policy = UnresolvedSignPolicy(visual["unresolved_sign_policy"])
print("unresolved sign policy:", policy)

signs = build_shiu_regression_signs(graph, tx, unresolved_policy=policy, seed=1).edge_signs
signs = np.asarray(signs)
src = np.asarray(graph.source_indices)
tgt = np.asarray(graph.target_indices)
con = np.asarray(graph.contact_counts, dtype=np.float64)
print(f"edges {len(signs):,}   signs: +1 {int((signs>0).sum()):,}  "
      f"-1 {int((signs<0).sum()):,}  0 {int((signs==0).sum()):,} "
      f"({100*float((signs==0).mean()):.1f}% of all edges carry no sign)")

atlas = SensoryAtlas.resolve(ann, graph)
dense = {int(b): graph.dense_index(int(b)) for b in graph.body_ids}

groups: dict[str, list[int]] = {}
for behaviour, names in (("grooming", ("groom-dn-left", "groom-dn-right")),
                         ("feeding", ("rostrum-mn9",)),
                         ("escape", ("giant-fibre-left", "giant-fibre-right"))):
    pops = Demo02Populations.resolve(
        ann, graph, behaviour=behaviour, entry_body_ids=atlas.entry_union
    )
    bodies: list[int] = []
    for name in names:
        bodies.extend(pops.readout[name])
    groups[f"{behaviour}: {'+'.join(names)}"] = [dense[b] for b in bodies]

# The DNp companion pool fired strongly, so it is the useful positive control here.
esc = Demo02Populations.resolve(
    ann, graph, behaviour="escape", entry_body_ids=atlas.entry_union
)
groups["escape: dn-loom pool (fired)"] = [
    dense[b] for name in ("dn-loom-left", "dn-loom-right") for b in esc.readout[name]
]

print(f"\n{'readout':44s}{'cells':>6s}{'in-contacts':>12s}"
      f"{'exc%':>7s}{'inh%':>7s}{'zero%':>7s}{'net exc-inh':>12s}")
for label, idx in groups.items():
    mask = np.isin(tgt, np.asarray(idx))
    c = con[mask]
    s = signs[mask]
    total = c.sum()
    exc = c[s > 0].sum()
    inh = c[s < 0].sum()
    zero = c[s == 0].sum()
    print(f"{label:44s}{len(idx):6d}{int(total):12,d}"
          f"{100*exc/total:7.1f}{100*inh/total:7.1f}{100*zero/total:7.1f}"
          f"{int(exc-inh):12,d}")

print("\nreading: a readout whose input is mostly zero-signed is starved of SIGN, not gain.")
print("         a readout with net excitation near or below zero is cancelled, not starved.")
