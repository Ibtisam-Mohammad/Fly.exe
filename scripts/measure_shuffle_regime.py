"""Can the degree-preserving shuffle be made into a usable topology control?

The shuffle is supposed to remove structure and keep statistics. It does not: escape/shuffled
runs at 14,025 active neurons per interval against the intact 2,948, and fires the giant
fibre 242 times where the real connectome fires it zero. DEMO-01 saw the same thing and
hedged for it, and its surviving claim -- "the exact connectivity rather than a network of
its size is responsible AT THIS OPERATING POINT" -- leans entirely on that qualifier.

A control that moves the network to a different excitability regime cannot separate topology
from gain. There are only two honest responses: make the regimes match, or withdraw the
claim. This measures whether the first is even possible.

The method is the one the qualifier implies. Hold the stimulus and everything else fixed,
sweep synaptic gain on the SHUFFLED graph alone, and find the value whose descending-pool
activity matches the intact network's. If such a value exists, the comparison can be redone
at matched activity and the topology question actually asked. If the shuffled network cannot
be brought to the intact network's activity at any gain, that is a stronger statement: the
shuffle does not preserve the statistics it claims to.

Neural-only. No body, no decoder, no outcome.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, "/mnt/i/AI/fly_brain/src")

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.demo01 import Demo01Populations
from flysim.demo01_visual import (
    VISUAL_ENTRY_SPECS,
    VISUAL_MONITOR_POOLS,
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualEncodingParameters,
)
from flysim.demo01_visual_probe import KERNEL_KEYS
from flysim.demo02_escape_probe import ESCAPE_READOUT_SPECS
from flysim.engines.genn import TrackAGeNNEngine
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs

ROOT = Path("/srv/flybrain-data")
REPO = Path("/mnt/i/AI/fly_brain")
COUPLING = 15_000
POOL = "descending-all"
GEOM = {"cue_radius_mm": 2.5, "cue_distance_mm": 4.0, "cue_bearing_deg": 35.0}

visual = load_json(REPO / "configs/experiments/demo01-visual-operating-point-v1.json")
search = load_json(ROOT / "evidence/demo02/escape-operating-point-v1.json")
demo01 = load_json(ROOT / "evidence/demo01/demo01-visual-operating-point-v1.json")
base = {**visual["fixed_parameters"], **demo01["selected"]}
base.update(search["selected"])
base["readout_filter_tau_ms"] = visual["readout"]["readout_filter_tau_ms"]
retina = RetinaMap.from_mapping(visual["retina_map"])
policy = UnresolvedSignPolicy(visual["unresolved_sign_policy"])

graph = SparseConnectome.load(ROOT / "derived/male-cns-v1.0/graph")
graph.validate()
ann = ROOT / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
tx = ROOT / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
pops = Demo01Populations.resolve(
    ann, graph, entry_specs=VISUAL_ENTRY_SPECS, readout_specs=ESCAPE_READOUT_SPECS,
    monitor_pools=VISUAL_MONITOR_POOLS, require_hex=True,
)
signs = build_shiu_regression_signs(graph, tx, unresolved_policy=policy, seed=1).edge_signs


def shuffled(seed: int) -> SparseConnectome:
    rng = np.random.default_rng(seed)
    targets = np.asarray(graph.target_indices).copy()
    rng.shuffle(targets)
    return replace(graph, target_indices=targets)


def measure(g: SparseConnectome, gain: float, side: str = "left",
            seconds: float = 1.5) -> dict:
    """Descending-pool activity and per-side giant-fibre spikes, object held present."""
    params = {**base, "synaptic_mv_per_contact": gain}
    kernel = {k: params[k] for k in KERNEL_KEYS if k in params}
    # A real hash of the whole target array. A cheap summary could collide between the
    # intact and shuffled graphs, and this project has already had one run load another's
    # compiled kernel because a build key was too coarse.
    wiring = hashlib.sha256(
        np.asarray(g.target_indices, dtype=np.int64).tobytes()
    ).hexdigest()[:12]
    engine = TrackAGeNNEngine(
        ROOT / f"build/demo02-shuffle-regime/{sha256_json({**kernel, 'w': wiring})[:12]}",
        variant="exact")
    engine.initialize(
        g, {**params, "functional_edge_signs": signs,
            "entry_body_ids": pops.entry_body_ids}, 1)
    enc = RetinotopicVisualEncoder(
        pops, VisualEncodingParameters.from_mapping(params), retina)
    bearing = np.radians(GEOM["cue_bearing_deg"] * (1.0 if side == "left" else -1.0))
    d = GEOM["cue_distance_mm"]
    cue = VisualCue(x_mm=d * np.cos(bearing), y_mm=d * np.sin(bearing),
                    radius_mm=GEOM["cue_radius_mm"])
    ids = pops.readout_body_ids
    per = {"giant-fibre-left": 0, "giant-fibre-right": 0}
    hz, act, gf, t = [], [], 0, 0
    try:
        for step in range(int(seconds * 1e6) // COUPLING):
            engine.push_inputs(enc.encode(t, cue, x_mm=0.0, y_mm=0.0, heading_rad=0.0))
            t += COUPLING
            engine.step_until(t)
            raw = engine.read_outputs(ids, COUPLING)
            a = engine.population_activity(dict(pops.monitors), COUPLING)[POOL]
            if step >= 20:                      # discard the transient
                hz.append(float(a["mean_rate_hz"]))
                act.append(float(a["active_fraction"]))
                counts = raw.metadata.get("spike_counts", {})
                gf += sum(int(v) for v in counts.values())
                for nm in ("giant-fibre-left", "giant-fibre-right"):
                    for b in pops.readout[nm]:
                        per[nm] += int(counts.get(b, 0))
    finally:
        engine.close()
    return {"descending_hz": float(np.mean(hz)), "active": float(np.mean(act)),
            "gf_spikes": gf, "per_side": per}


def sel(a: float, b: float) -> float:
    t = a + b
    return 0.0 if t <= 0 else (a - b) / t


def both_sides(g, gain, label):
    left = measure(g, gain, "left")
    right = measure(g, gain, "right")
    lp, rp = left["per_side"], right["per_side"]
    il = sel(lp["giant-fibre-left"], lp["giant-fibre-right"])
    ir = sel(rp["giant-fibre-left"], rp["giant-fibre-right"])
    swing = il - ir
    reverses = (il > 0 > ir) or (il < 0 < ir)
    enough = min(left["gf_spikes"], right["gf_spikes"]) >= 20
    lstr = "{},{}".format(lp["giant-fibre-left"], lp["giant-fibre-right"])
    rstr = "{},{}".format(rp["giant-fibre-left"], rp["giant-fibre-right"])
    print("{:32s} L {:>9s}  R {:>9s}  swing {:+7.3f}  reverses {:5s}  "
          "20+both {:5s}  desc {:6.2f} Hz".format(
              label, lstr, rstr, swing, str(reverses), str(enough),
              left["descending_hz"]), flush=True)
    return {"swing": swing, "reverses": reverses, "enough": enough}


print("=== is the RESPONSE lateralised, not merely present? ===")
print("    A topology gate compares a real network against a rewired one. A random")
print("    network that merely fires the readout says little; one that reproduces its")
print("    SELECTIVITY says the topology was not doing the work.")
print()
intact = both_sides(graph, base["synaptic_mv_per_contact"], "intact @ gain 0.40")
matched = both_sides(shuffled(1), 0.15, "shuffled @ matched gain 0.15")
naive = both_sides(shuffled(1), base["synaptic_mv_per_contact"], "shuffled @ gain 0.40")

print()
if not matched["enough"]:
    print("VERDICT: the matched shuffle does not reach 20 spikes in both epochs, so its")
    print("         selectivity index is not interpretable. No topology claim either way.")
elif matched["reverses"] and abs(matched["swing"]) >= 0.2:
    print("VERDICT: a regime-matched shuffle REPRODUCES the lateralised response.")
    print("         Topology is not doing the work and the claim must be withdrawn.")
else:
    print("VERDICT: the matched shuffle drives the readout but does NOT reproduce its")
    print("         lateralisation. Topology survives as a claim about SELECTIVITY only,")
    print("         not about whether the readout can be driven at all.")
