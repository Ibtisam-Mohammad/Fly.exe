#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tune the E-provenance neural-to-locomotor decoder on development scenarios only.

    PYTHONPATH=src python scripts/tune_demo01_decoder.py --root /srv/flybrain-data

Two rules make this legitimate rather than circular.

The network is already frozen. This reads the operating point from the search artifact and
never varies it, so nothing here can compensate for a bad network by adjusting it; only the
decoder moves.

The scenarios are development scenarios, and they are not the one the demonstration is
evaluated on. The registered evaluation uses the cue at the position in
`configs/scenarios/demo01-visual-approach.json` with seed 1. Tuning here uses different cue
sides, different distances and different seeds, so the frozen decoder faces an unseen
configuration at evaluation time.

Behavioural objectives *are* admissible here, unlike in the operating-point search. This is
the behavioural decoder: tuning it on whether the turn tracks the cue is what tuning it
means. Tuning the *network* that way is what the search was built to prevent.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.demo01_acceptance import read_variant  # noqa: E402
from flysim.demo01_body import Demo01BodyParameters  # noqa: E402
from flysim.demo01_embodied import run_embodied  # noqa: E402
from flysim.demo01_visual import VisualDecoderParameters  # noqa: E402
from flysim.errors import ReadinessError  # noqa: E402

# Development scenarios: the cue on the other side, at other distances, other seeds. None
# of these is the registered evaluation configuration.
DEVELOPMENT = (
    {"name": "right-near", "cue_x_mm": 9.0, "cue_y_mm": -7.0, "seed": 2},
    {"name": "right-far", "cue_x_mm": 13.0, "cue_y_mm": -11.0, "seed": 3},
    {"name": "left-far", "cue_x_mm": 13.5, "cue_y_mm": 11.5, "seed": 4},
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
        default=REPO / "configs/scenarios/demo01-visual-approach.json",
    )
    parser.add_argument("--duration-s", type=float, default=8.0)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    args = parser.parse_args()

    root: Path = args.root
    artifact = root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    if not artifact.is_file():
        raise ReadinessError(f"The frozen operating point is missing: {artifact}")
    search = json.loads(artifact.read_text(encoding="utf-8"))
    operating_point = search.get("selected")
    if not operating_point:
        raise ReadinessError("The search selected no operating point")
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    coupling_us = int(json.loads(args.contract.read_text(encoding="utf-8"))["coupling_us"])
    duration_us = round(args.duration_s * 1_000_000 / coupling_us) * coupling_us
    base_decoder = VisualDecoderParameters.from_mapping(scenario["decoder"])

    print(f"frozen operating point: {operating_point}")
    print(f"development scenarios: {[row['name'] for row in DEVELOPMENT]}")
    print(f"{duration_us / 1e6:.2f} s each\n")

    grid = list(itertools.product((0.8, 1.6, 3.2), (0.6, 1.2), (1.0, -1.0)))
    print(
        f"{'yawgain':>8s} {'thresh':>7s} {'sign':>5s} | "
        f"{'walked':>7s} {'mean approach':>14s} {'cue-locked':>11s} {'|turn| deg':>11s}"
    )
    rows: list[dict] = []
    for yaw_gain, threshold, sign in grid:
        decoder = replace(
            base_decoder,
            yaw_gain_per_hz=yaw_gain,
            forward_threshold_hz=threshold,
            turn_sign=sign,
        )
        approaches: list[float] = []
        agreements: list[float] = []
        turns: list[float] = []
        walked = 0
        for development in DEVELOPMENT:
            body_parameters = Demo01BodyParameters.from_mapping(
                {
                    **scenario["body"],
                    "cue_x_mm": development["cue_x_mm"],
                    "cue_y_mm": development["cue_y_mm"],
                }
            )
            directory = (
                root
                / "runs/demo01-decoder-tuning"
                / f"y{yaw_gain:g}-t{threshold:g}-s{sign:+g}"
                / str(development["name"])
            )
            run_embodied(
                contract_path=args.contract,
                operating_point=operating_point,
                decoder=decoder,
                graph_path=root / "derived/male-cns-v1.0/graph",
                annotations_path=(
                    root
                    / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
                ),
                transmitter_path=(
                    root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
                ),
                build_root=root / "build/demo01-embodied",
                output_directory=directory,
                duration_us=duration_us,
                body_parameters=body_parameters,
                seed=int(development["seed"]),
                variant="exact",
                write_video=False,
                allow_dirty_tree=True,
            )
            summary = read_variant(directory, decoder.quiescent_us)
            approaches.append(summary.approach_mm)
            turns.append(abs(math.degrees(summary.net_heading_change_rad)))
            if summary.cue_locked_sign_agreement is not None:
                agreements.append(summary.cue_locked_sign_agreement)
            walked += int(summary.locomoted)
        mean_approach = sum(approaches) / len(approaches)
        mean_agreement = sum(agreements) / len(agreements) if agreements else float("nan")
        mean_turn = sum(turns) / len(turns)
        rows.append(
            {
                "yaw_gain_per_hz": yaw_gain,
                "forward_threshold_hz": threshold,
                "turn_sign": sign,
                "walked": walked,
                "mean_approach_mm": mean_approach,
                "mean_cue_locked_agreement": mean_agreement,
                "mean_abs_turn_deg": mean_turn,
            }
        )
        print(
            f"{yaw_gain:8.2f} {threshold:7.2f} {sign:+5.0f} | "
            f"{walked:5d}/{len(DEVELOPMENT)} {mean_approach:+14.2f} "
            f"{mean_agreement:11.3f} {mean_turn:11.1f}",
            flush=True,
        )

    # Selection rule, declared here rather than chosen after looking: among settings that
    # walked in every development scenario, the largest mean approach. Approach is the
    # behaviour the decoder exists to produce, and it is admissible for the decoder.
    usable = [row for row in rows if row["walked"] == len(DEVELOPMENT)]
    if not usable:
        print("\nNo decoder setting walked in every development scenario.")
        chosen = None
    else:
        chosen = max(usable, key=lambda row: row["mean_approach_mm"])
        print(f"\nchosen: {chosen}")

    output = root / "evidence/demo01/demo01-decoder-tuning.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "result_id": "demo01-decoder-tuning",
                "provenance": "E",
                "operating_point_frozen": operating_point,
                "development_scenarios": list(DEVELOPMENT),
                "duration_us": duration_us,
                "searched": rows,
                "selection_rule": (
                    "Among settings that walked in every development scenario, the largest "
                    "mean approach. Declared before the sweep."
                ),
                "chosen": chosen,
                "why_this_is_not_circular": (
                    "The network operating point is read from the frozen search artifact "
                    "and never varied, so only the decoder moves. The scenarios here are "
                    "development scenarios with different cue sides, distances and seeds "
                    "than the registered evaluation, so the frozen decoder meets an unseen "
                    "configuration at evaluation time."
                ),
                "why_a_behavioural_objective_is_admissible_here": (
                    "This is the behavioural decoder. Tuning it on whether the turn tracks "
                    "the cue is what tuning it means. Tuning the network that way is what "
                    "the operating-point search exists to prevent, and that search used no "
                    "behavioural quantity at all."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"recorded: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
