#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the registered DEMO-01 visual operating-point search.

    PYTHONPATH=src python scripts/run_demo01_visual_search.py \
        --root /srv/flybrain-data --progress

Every searched candidate is recorded, passing or not. The search refuses to run from a
dirty worktree unless --allow-dirty-tree is passed, in which case the artifact is marked
non-evidence-grade.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.demo01_visual_probe import (  # noqa: E402
    run_visual_operating_point_search,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO / "configs/experiments/demo01-visual-operating-point-v1.json",
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--keep-timeline",
        action="store_true",
        help=(
            "Retain the per-interval timeline for every candidate. Off by default because "
            "108 candidates times 350 intervals times seven monitor pools is a large "
            "artifact; the epoch means, the pool summary and the criterion values are "
            "always recorded."
        ),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    root: Path = args.root
    output = args.output or root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    artifact = run_visual_operating_point_search(
        contract_path=args.contract,
        graph_path=root / "derived/male-cns-v1.0/graph",
        annotations_path=(
            root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
        ),
        transmitter_path=(
            root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
        ),
        build_root=root / "build/demo01-visual-search",
        output_path=output,
        seed=args.seed,
        allow_dirty_tree=args.allow_dirty_tree,
        max_candidates=args.max_candidates,
        keep_timeline=args.keep_timeline,
        progress=args.progress,
    )

    print("=" * 110)
    print(
        f"searched {artifact['candidates_searched']}   "
        f"passing {artifact['candidates_passing']}"
    )
    populations = artifact["populations"]
    print(f"entry   {populations['entry_sizes']}")
    print(f"readout {populations['readout_sizes']}")
    print(f"monitor {populations['monitor_sizes']}")
    print(
        f"entry bodies with released column coordinates: "
        f"{populations['entry_bodies_with_column_coordinates']}"
    )
    print("=" * 110)
    header = (
        f"{'mv':>5s} {'inh':>5s} {'adapt':>6s} {'lamHz':>6s} {'on/off':>6s} | "
        f"{'base':>6s} {'cueL':>6s} {'cueR':>6s} {'recov':>6s} {'resid':>7s} | "
        f"{'selL':>7s} {'selR':>7s} {'swing':>6s} {'rev':>3s} | "
        f"{'poolHz':>7s} {'act':>7s} {'spikes':>7s} | C1 C2 C3 C4 C5"
    )
    print(header)
    flag_keys = (
        "C1_stable_nonsaturated",
        "C2_cue_responsive",
        "C3_bilateral_selectivity_reverses",
        "C4_recovers_to_baseline",
        "C5_enough_spikes_to_be_meaningful",
    )
    for row in artifact["results"]:
        candidate, score = row["candidate"], row["score"]
        flags = "".join(" P" if score[key] else " ." for key in flag_keys)
        descending = row["pool_summary"]["descending-all"]
        print(
            f"{candidate['synaptic_mv_per_contact']:5.2f} "
            f"{candidate['inhibitory_weight_gain']:5.1f} "
            f"{candidate['adaptation_increment_mv']:6.1f} "
            f"{candidate['lamina_max_rate_hz']:6.0f} "
            f"{candidate['lamina_on_off_balance']:6.1f} | "
            f"{score['baseline_drive_hz']:6.2f} {score['cue_left_drive_hz']:6.2f} "
            f"{score['cue_right_drive_hz']:6.2f} {score['recovery_drive_hz']:6.2f} "
            f"{score['recovery_residual_fraction']:7.2f} | "
            f"{score['left_cue_selectivity_index']:+7.3f} "
            f"{score['right_cue_selectivity_index']:+7.3f} "
            f"{score['selectivity_swing']:6.3f} "
            f"{'Y' if score['selectivity_reverses_with_cue_side'] else 'n':>3s} | "
            f"{descending['mean_rate_hz']:7.2f} {descending['active_fraction']:7.4f} "
            f"{min(score['cue_epoch_readout_spike_counts'].values()):7d} |"
            f"{flags}" + ("  <== PASS" if score["all_criteria_met"] else "")
        )
    print("=" * 110)
    print(f"selected: {artifact['selected']}")
    print(
        f"artifact: {output}  sha256={artifact['artifact_sha256']}\n"
        f"snapshot: {artifact['immutable_snapshot']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
