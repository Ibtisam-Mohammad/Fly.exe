#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the frozen neural-only tarsal-taste to MN9 operating-point search."""

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
from flysim.demo02_feeding_probe import (  # noqa: E402
    epochs_from_contract,
    probe_feeding_operating_point,
    score_feeding_candidate,
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
        else require_clean_worktree("The DEMO-02 feeding operating-point search")
    )
    contract = load_json(
        REPO / "configs/experiments/demo02-feeding-operating-point-v1.json"
    )
    visual = load_json(
        REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
    )
    source = load_json(root / "evidence/demo01/demo01-visual-operating-point-v1.json")
    selected = source.get("selected")
    if not selected:
        raise SystemExit("The frozen DEMO-01 operating point has no selected point.")

    fixed = contract["fixed_parameters"]
    base = {**visual["fixed_parameters"], **selected}
    base.update(
        {
            "adaptation_increment_mv": fixed["adaptation_increment_mv"],
            "lamina_on_off_balance": fixed["lamina_on_off_balance"],
            "synaptic_delay_ms": fixed["synaptic_delay_ms"],
            "readout_filter_tau_ms": fixed["readout_filter_tau_ms"],
        }
    )
    coupling_us = int(fixed["coupling_us"])
    epochs = epochs_from_contract(contract)
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
        annotations, graph, behaviour="feeding", entry_body_ids=atlas.entry_union
    )
    signs = build_shiu_regression_signs(
        graph,
        transmitters,
        unresolved_policy=UnresolvedSignPolicy(visual["unresolved_sign_policy"]),
        seed=args.seed,
    ).edge_signs
    grid = contract["searched_grid"]
    names = list(grid)
    candidates = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(grid[name] for name in names))
    ]
    if len(candidates) != int(contract["grid_size"]):
        raise SystemExit("Expanded feeding grid does not match the preregistered size")

    results: list[dict[str, object]] = []
    started = time.perf_counter()
    for index, candidate in enumerate(candidates, 1):
        measured = probe_feeding_operating_point(
            graph=graph,
            atlas=atlas,
            populations=populations,
            signs=signs,
            base_parameters=base,
            candidate=candidate,
            epochs=epochs,
            transducer_half_saturation=float(fixed["transducer_half_saturation"]),
            transducer_threshold=float(fixed["transducer_threshold"]),
            coupling_us=coupling_us,
            build_root=root / "build/demo02-feed-search",
            seed=args.seed,
            settle_fraction=float(contract["epochs"]["settle_fraction"]),
        )
        score = score_feeding_candidate(measured, contract)
        results.append({"candidate": candidate, "measured": measured, "score": score})
        flags = "".join(
            "1" if score[name] else "."
            for name in (
                "N1_baseline_is_silent",
                "N2_the_route_responds",
                "N3_the_response_tracks_concentration",
                "N4_the_route_recovers",
                "N5_the_network_is_alive_and_not_saturated",
            )
        )
        values = score["values"]
        print(
            f"[{index:02d}/{len(candidates)}] {candidate} spikes="
            f"{values['spike_counts_by_concentration']} rho={values['spearman']:.3f} "
            f"N={flags} {'PASS' if score['passes'] else ''}",
            flush=True,
        )
    winner = select_operating_point(results)
    passing = sum(bool(row["score"]["passes"]) for row in results)  # type: ignore[index]
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
        "elapsed_seconds": time.perf_counter() - started,
        "scientific_validation_tier_awarded": None,
        "this_search_did_not_see": (
            "demo02-feeding-v2, F1 through F7, a body, a joint, a contact outcome, "
            "or a video"
        ),
        "claim_boundary": contract["claim_boundary"],
    }
    output = root / "evidence/demo02/feeding-operating-point-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"{passing} of {len(results)} candidates passed; artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
