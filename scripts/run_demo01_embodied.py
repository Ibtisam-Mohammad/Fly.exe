#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the DEMO-01 closed loop and its identical-seed controls, then render the video.

    PYTHONPATH=src python scripts/run_demo01_embodied.py \
        --root /srv/flybrain-data --duration-s 20 --render

The operating point comes from the frozen artifact of the registered search, never from
the command line, so the network the demonstration runs cannot drift from the network the
search selected. Pass --operating-point only to reproduce a historical run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.demo01_acceptance import (  # noqa: E402
    evaluate,
    read_variant,
    summarise_for_console,
)
from flysim.demo01_body import Demo01BodyParameters  # noqa: E402
from flysim.demo01_embodied import CONTROL_VARIANTS, run_embodied  # noqa: E402
from flysim.demo01_render import (  # noqa: E402
    build_soma_positions,
    render_comparison,
    render_recording,
)
from flysim.demo01_visual import VisualDecoderParameters  # noqa: E402
from flysim.errors import ReadinessError  # noqa: E402


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
    parser.add_argument("--duration-s", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--variant",
        action="append",
        default=None,
        choices=list(CONTROL_VARIANTS),
        help="Run only these variants. Default: every one, which is the point of controls.",
    )
    parser.add_argument("--operating-point", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--acceptance",
        type=Path,
        default=REPO / "configs/experiments/demo01-acceptance-v1.json",
    )
    args = parser.parse_args()

    root: Path = args.root
    search_artifact = (
        args.operating_point
        or root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    )
    if not search_artifact.is_file():
        raise ReadinessError(
            f"The frozen operating point is missing: {search_artifact}. Run "
            "scripts/run_demo01_visual_search.py first; the demonstration may not invent "
            "its own network parameters."
        )
    search = json.loads(search_artifact.read_text(encoding="utf-8"))
    operating_point = search.get("selected")
    if not operating_point:
        raise ReadinessError(
            f"{search_artifact} selected no operating point ("
            f"{search['candidates_passing']} of {search['candidates_searched']} passed), "
            "so there is nothing frozen to run."
        )
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    body_parameters = Demo01BodyParameters.from_mapping(scenario["body"])
    decoder = VisualDecoderParameters.from_mapping(scenario["decoder"])

    positions = root / "derived/male-cns-v1.0/soma-positions.npz"
    if args.render and not positions.is_file():
        graph = SparseConnectome.load(root / "derived/male-cns-v1.0/graph")
        report = build_soma_positions(
            root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather",
            graph,
            positions,
        )
        print(f"built brain-view geometry: {report['drawn']} drawn, "
              f"{report['missing']} without a released position")

    output_root = args.output_root or root / "runs/demo01-visual"
    coupling_us = int(json.loads(args.contract.read_text(encoding="utf-8"))["coupling_us"])
    duration_us = round(args.duration_s * 1_000_000 / coupling_us) * coupling_us
    variants = args.variant or list(CONTROL_VARIANTS)

    print(f"operating point (frozen): {operating_point}")
    print(f"decoder (E): {decoder.as_dict()}")
    print(f"duration {duration_us / 1e6:.2f} s   variants {variants}")

    results = []
    for variant in variants:
        directory = output_root / variant
        print(f"\n=== {variant} ===", flush=True)
        result = run_embodied(
            contract_path=args.contract,
            operating_point=operating_point,
            decoder=decoder,
            graph_path=root / "derived/male-cns-v1.0/graph",
            annotations_path=(
                root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
            ),
            transmitter_path=(
                root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
            ),
            build_root=root / "build/demo01-embodied",
            output_directory=directory,
            duration_us=duration_us,
            body_parameters=body_parameters,
            seed=args.seed,
            variant=variant,
            allow_dirty_tree=args.allow_dirty_tree,
            progress=args.progress,
        )
        results.append(result)
        print(
            f"  displacement {result.displacement_mm:7.2f} mm   "
            f"heading change {result.net_heading_change_rad:+6.3f} rad   "
            f"cue distance {result.initial_distance_mm:6.2f} -> "
            f"{result.final_distance_mm:6.2f} mm   "
            f"onset {result.locomotion_onset_us}"
        )

    print("\n" + "=" * 96)
    print(
        f"{'variant':22s} {'displ mm':>9s} {'d heading':>10s} "
        f"{'cue start':>10s} {'cue end':>9s} {'onset s':>8s}"
    )
    for result in results:
        onset = (
            f"{result.locomotion_onset_us / 1e6:8.2f}"
            if result.locomotion_onset_us is not None
            else "    none"
        )
        print(
            f"{result.variant:22s} {result.displacement_mm:9.2f} "
            f"{result.net_heading_change_rad:+10.3f} "
            f"{result.initial_distance_mm:10.2f} {result.final_distance_mm:9.2f} {onset}"
        )
    print("=" * 96)

    # The verdict is computed by code that cannot run a simulation and cannot alter a
    # threshold, from a contract committed before these runs.
    verdict = None
    if {"exact", "readout-ablated", "stimulus-absent"} <= set(variants):
        summaries = {
            result.variant: read_variant(result.directory, decoder.quiescent_us)
            for result in results
        }
        verdict = evaluate(
            contract_path=args.acceptance,
            variants=summaries,
            quiescent_us=decoder.quiescent_us,
        )
        print(summarise_for_console(verdict))
        (output_root / "acceptance.json").write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nverdict: {output_root / 'acceptance.json'}")
    else:
        print(
            "Acceptance not evaluated: it needs the exact, readout-ablated and "
            "stimulus-absent variants, and this invocation ran only "
            f"{sorted(variants)}."
        )
    # Rendering happens only now. The closing card carries the verdict, and the verdict
    # does not exist until every variant has run, so rendering inside the variant loop
    # would have stamped "no verdict has been computed" onto all four videos.
    if args.render:
        for result in results:
            video = render_recording(
                result.directory,
                positions_path=positions,
                fps=args.fps,
                title=f"MaleCNS full-graph closed loop - {result.variant}",
            )
            print(f"  video {video} ({video.stat().st_size / 1e6:.1f} MB)")

    comparison: dict[str, Any] = {
        "schema_version": "1.0",
        "operating_point": operating_point,
        "decoder": decoder.as_dict(),
        "duration_us": duration_us,
        "seed": args.seed,
        "variants": {
            result.variant: {
                "displacement_mm": result.displacement_mm,
                "net_heading_change_rad": result.net_heading_change_rad,
                "initial_cue_distance_mm": result.initial_distance_mm,
                "final_cue_distance_mm": result.final_distance_mm,
                "locomotion_onset_us": result.locomotion_onset_us,
            }
            for result in results
        },
    }
    if args.render and len(results) > 1:
        panel = render_comparison(
            output_root,
            positions_path=positions,
            fps=args.fps,
            variants=[result.variant for result in results],
        )
        print(f"comparison video: {panel} ({panel.stat().st_size / 1e6:.1f} MB)")

    comparison["acceptance"] = verdict
    (output_root / "control-comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"comparison: {output_root / 'control-comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
