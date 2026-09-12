#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the frozen grooming operating-point search and write the artifact.

    PYTHONPATH=src python scripts/search_demo02_grooming_operating_point.py

Every candidate is recorded, passing or failing.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.config import load_json, sha256_json  # noqa: E402
from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.demo02 import Demo02Populations  # noqa: E402
from flysim.demo02_grooming_probe import (  # noqa: E402
    GroomCriteria,
    epochs_from_contract,
    probe_grooming_operating_point,
    score_grooming_candidate,
    select_operating_point,
)
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs  # noqa: E402
from flysim.runs import git_metadata, require_clean_worktree  # noqa: E402
from flysim.sensory_atlas import SensoryAtlas  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    args = parser.parse_args()

    root: Path = args.root
    verification = (
        git_metadata()
        if args.allow_dirty_tree
        else require_clean_worktree("A DEMO-02 grooming operating-point search")
    )
    contract = load_json(
        REPO / "configs/experiments/demo02-grooming-operating-point-v1.json"
    )
    visual = load_json(
        REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
    )
    demo01 = load_json(root / "evidence/demo01/demo01-visual-operating-point-v1.json")
    selected = demo01.get("selected")
    if not selected:
        raise SystemExit("The frozen DEMO-01 operating point has no selected point.")

    fixed = contract["what_is_searched_and_what_is_fixed"]["fixed"]
    base = {**visual["fixed_parameters"], **selected}
    base["lamina_on_off_balance"] = fixed["lamina_on_off_balance"]
    base["adaptation_increment_mv"] = fixed["adaptation_increment_mv"]
    base["readout_filter_tau_ms"] = visual["readout"]["readout_filter_tau_ms"]
    policy = UnresolvedSignPolicy(visual["unresolved_sign_policy"])
    criteria = GroomCriteria.from_mapping(contract["neural_criteria"])
    epochs = epochs_from_contract(contract)
    coupling_us = int(contract["coupling_us"])
    settle_fraction = float(contract["epochs"]["settle_fraction"])

    graph = SparseConnectome.load(root / "derived/male-cns-v1.0/graph")
    graph.validate()
    annotations = (
        root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    transmitters = (
        root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
    )
    atlas = SensoryAtlas.resolve(annotations, graph)
    populations = Demo02Populations.resolve(
        annotations, graph, behaviour="grooming", entry_body_ids=atlas.entry_union
    )
    signs = build_shiu_regression_signs(
        graph, transmitters, unresolved_policy=policy, seed=args.seed
    ).edge_signs
    print(
        f"entry union {len(atlas.entry_union)} bodies, readout "
        f"{ {k: len(v) for k, v in populations.readout.items()} }",
        flush=True,
    )

    grid = contract["searched_grid"]
    names = list(grid)
    candidates = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(grid[name] for name in names))
    ]
    if len(candidates) != int(contract["grid_size"]):
        raise SystemExit(
            f"Grid expands to {len(candidates)} and the contract declares "
            f"{contract['grid_size']}."
        )
    print(f"{len(candidates)} candidates\n", flush=True)
    print(
        f"{'ant_hz':>7s}{'syn':>6s}{'inh':>6s} | {'base':>5s}{'L(l,r)':>9s}{'R(l,r)':>9s}"
        f" | {'swing':>7s}{'rec':>6s}{'act':>6s} | N12345",
        flush=True,
    )

    results = []
    started = time.perf_counter()
    for index, candidate in enumerate(candidates, 1):
        measured = probe_grooming_operating_point(
            graph=graph,
            atlas=atlas,
            populations=populations,
            signs=signs,
            base_parameters=base,
            candidate=candidate,
            epochs=epochs,
            deflection_rad=float(fixed["deflection_rad"]),
            transducer_half_saturation=float(fixed["transducer_half_saturation"]),
            transducer_threshold=float(fixed["transducer_threshold"]),
            coupling_us=coupling_us,
            build_root=root / "build/demo02-groom-search",
            seed=args.seed,
            settle_fraction=settle_fraction,
        )
        score = score_grooming_candidate(measured, criteria)
        results.append({"candidate": candidate, "measured": measured, "score": score})
        v = score["values"]
        flags = "".join(
            "1" if score[k] else "."
            for k in (
                "N1_silent_and_stable_at_rest",
                "N2_responds_to_the_stimulus",
                "N3_side_selectivity_reverses",
                "N4_recovers_to_silence",
                "N5_the_network_is_alive_and_not_saturated",
            )
        )
        left = "{},{}".format(
            v["left_spikes"]["groom-dn-left"], v["left_spikes"]["groom-dn-right"]
        )
        right = "{},{}".format(
            v["right_spikes"]["groom-dn-left"], v["right_spikes"]["groom-dn-right"]
        )
        print(
            f"{candidate['antennal_max_rate_hz']:7.0f}"
            f"{candidate['synaptic_mv_per_contact']:6.2f}"
            f"{candidate['inhibitory_weight_gain']:6.2f} | "
            f"{v['baseline_readout_spikes']:5d}{left:>9s}{right:>9s} | "
            f"{v['selectivity_swing']:7.3f}{v['recovery_hz']:6.2f}"
            f"{v['driven_active_fraction']:6.3f} | {flags}"
            f"  {'PASS' if score['passes'] else ''}  [{index}/{len(candidates)}]",
            flush=True,
        )

    winner = select_operating_point(results)
    elapsed = time.perf_counter() - started
    passing = sum(1 for r in results if r["score"]["passes"])
    print(f"\n{passing} of {len(results)} candidates passed all five criteria "
          f"({elapsed / 60:.1f} min)")
    if winner:
        print(f"SELECTED: {json.dumps(winner['candidate'])}")
        print(f"  swing {winner['score']['values']['selectivity_swing']:+.3f}, "
              f"best side {winner['score']['values']['best_side_spikes']} spikes")
    else:
        print("SELECTED: none. That is the result and it is reported as one.")

    artifact = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "experiment_sha256": sha256_json(contract),
        "provenance": "E",
        "code_commit": verification["commit"],
        "worktree_dirty": verification["dirty"],
        "worktree_verification": verification.get("verification", {}),
        "seed": args.seed,
        "graph": {
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "populations": populations.as_dict(),
        "searched_grid": grid,
        "candidates_searched": len(results),
        "candidates_passing": passing,
        "selection_rule": contract["selection_rule"],
        "selected": winner["candidate"] if winner else None,
        "selected_score": winner["score"] if winner else None,
        "results": results,
        "elapsed_seconds": elapsed,
        "evidence_grade": "engineering calibration; no tier awarded",
        "claim_boundary": contract["claim_boundary"],
        "the_entry_rate_is_not_biological": contract[
            "a_biologically_indefensible_number_declared_as_one"
        ],
        "this_search_did_not_see": (
            "demo02-grooming-v1 or any of its criteria G1 to G7, and no body, decoder, "
            "excursion or displacement quantity exists anywhere in this pipeline."
        ),
    }
    out = root / "evidence/demo02/grooming-operating-point-v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"artifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
