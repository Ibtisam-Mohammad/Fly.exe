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
from flysim.demo02_acceptance import evaluate, read_variant  # noqa: E402
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


def _run_dir(root, behaviour: str, suffix: str, version: str, seed: int, variant: str):
    """Where one variant's recording lives. v2 keeps seeds apart so none can overwrite."""
    base = root / f"runs/demo02-{behaviour}{suffix}"
    return base / (variant if version == "v1" else f"seed{seed}/{variant}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behaviour", required=True, choices=BEHAVIOURS)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--duration-us", type=int, default=None)
    parser.add_argument("--allow-dirty-tree", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--contract-version", default="v1", choices=("v1", "v2", "legs-v1"),
        help="v2 runs the contract's registered seed set into per-seed run directories "
             "and requires every seed to pass.",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="One seed from the contract's registered set. The set is frozen; a seed "
             "outside it is refused.",
    )
    parser.add_argument(
        "--score-only", action="store_true",
        help="Skip running and apply the frozen contract to whatever is already recorded. "
             "Variants run in separate processes because CUDA does not release device "
             "memory between engines in one process, and the third build in a process "
             "fails with out of memory.",
    )
    args = parser.parse_args()

    root: Path = args.root
    behaviour: str = args.behaviour
    version = args.contract_version
    contract_path = REPO / f"configs/experiments/demo02-{behaviour}-{version}.json"
    contract = load_json(contract_path)
    variants = args.variants or list(contract["control_variants"])
    duration_us = args.duration_us or int(contract["fixed_parameters"]["duration_us"])
    # v1 carries one seed in fixed_parameters; v2 carries a seed set and every seed
    # must pass. Runs go into per-seed directories so a seed can never overwrite another.
    seeds = contract.get("seeds") or [int(contract["fixed_parameters"]["seed"])]
    if args.seed is not None:
        if args.seed not in seeds:
            raise SystemExit(
                f"Seed {args.seed} is not in the contract's registered set {seeds}. "
                "The seed set is frozen."
            )
        seeds = [args.seed]
    seed = int(seeds[0])
    suffix = "" if version == "v1" else f"-{version}"

    # DEMO-01's frozen operating point, read and not varied.
    operating = load_json(root / "evidence/demo01/demo01-visual-operating-point-v1.json")
    selected = operating.get("selected")
    if not selected:
        raise SystemExit(
            "The frozen DEMO-01 operating point has no selected point; refusing to invent one."
        )
    visual_contract = load_json(
        REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
    )
    parameters = {**visual_contract["fixed_parameters"], **selected}
    parameters["unresolved_sign_policy"] = visual_contract["unresolved_sign_policy"]
    # The readout filter lives in its own block in the visual contract, and its value and
    # its reasoning are reused unchanged: at a 15 ms interval one spike is 66.7 Hz, so an
    # unfiltered count is a 0-1-2 counter.
    parameters["readout_filter_tau_ms"] = visual_contract["readout"][
        "readout_filter_tau_ms"
    ]
    # Escape reuses DEMO-01's frozen retinotopic encoder unchanged, so it needs that
    # contract's frozen retina map too. Note what comes with it: lamina_baseline_rate_hz
    # is 1.0 there, so the 5342 lamina cells carry a baseline even in the stimulus-absent
    # control. That is DEMO-01's own registered behaviour ("everything identical,
    # including the lamina baseline drive") and it is inherited rather than quietly
    # changed -- but it means the bus's zero-baseline property does not hold for escape,
    # and those cells run without a refractory period throughout.
    parameters["retina_map"] = visual_contract["retina_map"]

    # Escape, and escape only, uses the operating point its own registered search selected.
    # That search scored neural criteria alone -- silent at rest, responds to the object,
    # side-selectivity reverses, recovers, network alive and unsaturated -- and could not
    # see demo02-escape-v1 or any body quantity. DEMO-01's point is kept for every other
    # behaviour, unchanged, because nothing has been searched for them.
    if behaviour == "escape":
        search = load_json(
            root / "evidence/demo02/escape-operating-point-v1.json"
        )
        chosen = search.get("selected")
        if not chosen:
            raise SystemExit(
                "The escape operating-point search selected nothing; refusing to invent "
                "a point. Run scripts/search_demo02_escape_operating_point.py first."
            )
        parameters.update(chosen)
        parameters["operating_point_source"] = search["experiment_id"]
        parameters["operating_point_result_id"] = search["result_id"]
        print(f"escape operating point (frozen by search): {json.dumps(chosen)}",
              flush=True)

    body_parameters = BehaviourBodyParameters.from_mapping(
        {**SCENARIOS[behaviour], "station_keeping_settle_us": 2_000_000}
    )
    decoder_spec = dict(DECODERS[behaviour])
    if contract.get("adr") == "ADR-2026-017":
        # The contract, not the code, decides whether the wing command is emitted.
        decoder_spec["command_wings"] = False
    decoder = DecoderParameters.from_mapping(decoder_spec)

    results = {}
    for variant in [] if args.score_only else variants:
        directory = (
            root / f"runs/demo02-{behaviour}{suffix}"
            / (variant if version == "v1" else f"seed{seed}/{variant}")
        )
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

    if results:
        index = root / f"runs/demo02-{behaviour}{suffix}/variants-seed{seed}.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nindex: {index}")

    # Apply the frozen contract in the same clean-tree window that produced the runs, so
    # the verdict cannot be computed against a tree that has moved since.
    recorded = {
        name: read_variant(_run_dir(root, behaviour, suffix, version, seed, name))
        for name in variants
        if _run_dir(root, behaviour, suffix, version, seed, name).joinpath(
            "summary.json").exists()
    }
    verdict = evaluate(behaviour=behaviour, contract=contract, variants=recorded)
    print(f"\n--- {contract['experiment_id']} ---")
    for name, outcome in verdict["criteria"].items():
        print(f"  [{outcome['status'].upper():10s}] {name}")
        print(f"               {outcome['detail']}")
    print(f"\nVERDICT: {verdict['verdict']}")
    print(f"tier:    {verdict['tier']}")
    # The filename carries the experiment id and, for multi-seed contracts, the seed. It
    # used to be f"{behaviour}-acceptance.json" for every contract, so scoring v2 and then
    # legs-v1 silently overwrote the recorded v1 verdict -- twice -- with a different
    # experiment's result under v1's name.
    stem = str(contract["experiment_id"])
    out = root / "evidence/demo02" / (
        f"{stem}-acceptance.json" if len(seeds) == 1
        else f"{stem}-acceptance-seed{seed}.json"
    )
    if out.exists():
        held = json.loads(out.read_text(encoding="utf-8")).get("experiment_id")
        if held and held != stem:
            raise SystemExit(
                f"{out} holds a verdict for {held!r} and this run is {stem!r}. Refusing "
                "to overwrite one experiment's recorded verdict with another's."
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(verdict, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"acceptance: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
