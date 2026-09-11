#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run one behaviour's control matrix, then apply its frozen contract.

    PYTHONPATH=src python scripts/run_demo02_behaviour.py --behaviour grooming
    PYTHONPATH=src python scripts/run_demo02_behaviour.py --behaviour escape --variants exact

The neural parameters come from DEMO-01's frozen operating point, unchanged. That point was
selected by a registered search on neural criteria alone, before any behaviour was attached,
and reusing it means no network parameter here was chosen by looking at a behavioural
outcome. It is the one thing in this pipeline that is already frozen, and it stays frozen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.behaviour_body import BehaviourBodyParameters  # noqa: E402
from flysim.config import load_json  # noqa: E402
from flysim.demo02 import BEHAVIOURS, DecoderParameters  # noqa: E402
from flysim.demo02_embodied import run_behaviour  # noqa: E402

TRAJECTORY = "derived/auxiliary/ozdil-2026-antennal-grooming/track-a-grooming-trajectory.npz"

#: Per behaviour: the scenario values that are not in the contract's fixed_parameters.
#: Every one is provenance E and every one is recorded in the run summary.
SCENARIOS: dict[str, dict[str, object]] = {
    "grooming": {
        "antennal_stimulus_side": "L",
        "antennal_stimulus_onset_us": 1_500_000,
        "antennal_stimulus_duration_us": 3_000_000,
        "sucrose_x_mm": 1e6,
    },
    "feeding": {
        # The patch sits under the fly, so a planted tarsus is inside it from the start
        # and the extension is not gated on the fly happening to walk somewhere.
        "sucrose_x_mm": 0.0,
        "sucrose_y_mm": 0.0,
        "sucrose_radius_mm": 3.0,
        "antennal_stimulus_side": "none",
    },
    "escape": {"antennal_stimulus_side": "none", "sucrose_x_mm": 1e6},
}

DECODERS: dict[str, dict[str, object]] = {
    "grooming": {
        "quiescent_us": 1_500_000,
        "threshold_hz": 0.6,
        "half_rate_hz": 6.0,
        "initiation_hold_us": 150_000,
        "action_us": 3_000_000,
    },
    "feeding": {
        "quiescent_us": 1_500_000,
        "threshold_hz": 0.6,
        "half_rate_hz": 6.0,
        "initiation_hold_us": 150_000,
        "action_us": 2_000_000,
    },
    "escape": {
        "quiescent_us": 1_500_000,
        "threshold_hz": 0.0,
        "spike_threshold": 1,
        "companion_threshold_hz": 0.5,
        "initiation_hold_us": 0,
        "action_us": 1_000_000,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behaviour", required=True, choices=BEHAVIOURS)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--duration-us", type=int, default=None)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    root: Path = args.root
    behaviour: str = args.behaviour
    contract_path = REPO / f"configs/experiments/demo02-{behaviour}-v1.json"
    contract = load_json(contract_path)
    variants = args.variants or list(contract["control_variants"])
    duration_us = args.duration_us or int(contract["fixed_parameters"]["duration_us"])
    seed = int(contract["fixed_parameters"]["seed"])

    # DEMO-01's frozen operating point, read and not varied.
    operating = load_json(root / "evidence/demo01/demo01-visual-operating-point-v1.json")
    selected = operating.get("search", {}).get("selected")
    if not selected:
        raise SystemExit(
            "The frozen DEMO-01 operating point has no selected point; refusing to invent one."
        )
    visual_contract = load_json(
        REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
    )
    parameters = {**visual_contract["fixed_parameters"], **selected}
    parameters["unresolved_sign_policy"] = visual_contract["unresolved_sign_policy"]

    body_parameters = BehaviourBodyParameters.from_mapping(
        {**SCENARIOS[behaviour], "station_keeping_settle_us": 2_000_000}
    )
    decoder = DecoderParameters.from_mapping(DECODERS[behaviour])

    results = {}
    for variant in variants:
        directory = root / f"runs/demo02-{behaviour}/{variant}"
        print(f"\n=== {behaviour} / {variant} ===", flush=True)
        result = run_behaviour(
            behaviour=behaviour,
            variant=variant,
            contract_path=contract_path,
            graph_path=root / "derived/male-cns-v1.0/graph",
            annotations_path=(
                root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
            ),
            transmitter_path=(
                root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
            ),
            build_root=root / f"build/demo02-{behaviour}",
            output_directory=directory,
            body_parameters=body_parameters,
            trajectory_path=root / TRAJECTORY if behaviour == "grooming" else None,
            decoder=decoder,
            parameters=parameters,
            duration_us=duration_us,
            seed=seed,
            allow_dirty_tree=args.allow_dirty_tree,
            progress=args.progress,
        )
        outcome = result.summary["outcome"]
        metrics = result.summary["takeoff"]
        print(
            f"  intervals {result.intervals}  displacement {result.displacement_mm:.3f} mm  "
            f"acting {outcome['reached_acting']}  onset {outcome['onset_us']}  "
            f"z rise {metrics['z_rise_mm']:.3f} mm  airborne {metrics['longest_airborne_us']} us"
        )
        results[variant] = {
            "directory": str(directory),
            "displacement_mm": result.displacement_mm,
            "onset_us": result.onset_us,
            "reached_acting": outcome["reached_acting"],
        }

    index = root / f"runs/demo02-{behaviour}/variants.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nindex: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
