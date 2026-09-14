#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the embodied 3D swarm and its identical-seed controls.

    PYTHONPATH=src python scripts/run_swarm3d_showcase.py \
        --root /srv/flybrain-data --duration-s 60 --variant exact \
        --variant stimulus-absent --progress

The operating point comes from the frozen artifact of the registered DEMO-01 visual search,
never from the command line, so the network this video runs cannot drift from the network
that search selected. Everything else -- the arena, the objects, the twelve starting poses
-- lives in the scenario file and is hashed into the summary.

Rendering is a separate step (`scripts/render_swarm3d_showcase.py`) reading the recording
this one writes, so no camera is ever baked into a simulation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.errors import ReadinessError  # noqa: E402
from flysim.swarm3d_run import (  # noqa: E402
    CONTROL_VARIANTS,
    SwarmScenario,
    run_swarm3d,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO / "configs/experiments/demo01-visual-operating-point-v1.json",
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=REPO / "configs/scenarios/swarm3d-showcase.json",
    )
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--variant", action="append", default=None, choices=list(CONTROL_VARIANTS)
    )
    parser.add_argument(
        "--flies",
        type=int,
        default=0,
        help="Run only the first N flies of the scenario. For smoke tests only; the "
        "showcase run uses every fly the scenario declares.",
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    root: Path = args.root
    search_artifact = root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    if not search_artifact.is_file():
        raise ReadinessError(
            f"The frozen operating point is missing: {search_artifact}. The showcase may "
            "not invent its own network parameters."
        )
    search = json.loads(search_artifact.read_text(encoding="utf-8"))
    operating_point = search.get("selected")
    if not operating_point:
        raise ReadinessError(
            f"{search_artifact} selected no operating point, so there is nothing frozen "
            "to run."
        )

    scenario = SwarmScenario.load(args.scenario)
    if args.flies:
        scenario = SwarmScenario(
            scenario_id=f"{scenario.scenario_id}+first-{args.flies}",
            arena=scenario.arena,
            flies=scenario.flies[: args.flies],
            objects=scenario.objects,
            decoder=scenario.decoder,
            include_other_flies=scenario.include_other_flies,
        )

    coupling_us = int(json.loads(args.contract.read_text(encoding="utf-8"))["coupling_us"])
    duration_us = round(args.duration_s * 1_000_000 / coupling_us) * coupling_us
    variants = args.variant or ["exact"]
    output_root = args.output_root or root / "runs/swarm3d-showcase"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    print(f"scenario     {scenario.scenario_id}")
    print(f"flies        {len(scenario.flies)}   objects {len(scenario.objects)}")
    print(f"operating pt {operating_point}   (frozen)")
    print(f"duration     {duration_us / 1e6:.2f} s   variants {variants}   seed {args.seed}")

    for variant in variants:
        directory = output_root / f"{stamp}_seed-{args.seed}" / variant
        print(f"\n=== {variant} -> {directory}")
        result = run_swarm3d(
            contract_path=args.contract,
            scenario=scenario,
            operating_point=operating_point,
            graph_path=root / "derived/male-cns-v1.0/graph",
            annotations_path=(
                root
                / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
            ),
            transmitter_path=(
                root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
            ),
            build_root=root / "build/swarm3d",
            output_directory=directory,
            duration_us=duration_us,
            seed=args.seed,
            variant=variant,
            allow_dirty_tree=args.allow_dirty_tree,
            progress=args.progress,
        )
        outcome = result.summary["outcome"]
        print(
            f"  {result.intervals} intervals in "
            f"{result.summary['simulation_seconds']:.0f} s "
            f"({result.summary['biological_per_wall']:.3f} x real time)"
        )
        print(
            f"  closed on a food object: "
            f"{outcome['flies_that_closed_on_a_food_object']}/{len(scenario.flies)}   "
            f"median {outcome['median_closed_mm']:+.2f} mm"
        )
        for entry in outcome["per_fly"]:
            print(
                f"    {entry['fly_id']:>8}  "
                f"{entry['initial_nearest_food_mm']:6.2f} -> "
                f"{entry['final_nearest_food_mm']:6.2f} mm  "
                f"({entry['closed_mm']:+6.2f})  "
                f"walked {entry['displacement_mm']:6.2f} mm  "
                f"-> {entry['final_nearest_food']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
