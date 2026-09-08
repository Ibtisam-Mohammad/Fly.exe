# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only check of the heterogeneous Track A GeNN kernel on the full traced graph.

Three kernels are built and driven identically (grooming JO-F population at a fixed rate for
a fixed interval, seed 1) and their per-neuron spike counts compared:

* ``homogeneous``  shared parameters compiled as constants, the recorded Track A path;
* ``fallback``     every neuron carries the fallback parameter set as per-neuron variables,
                   which must reproduce the homogeneous counts exactly or the promoted kernel
                   is not the same model;
* ``v03``          the ``cell-dynamics-v0.3`` resolution, in which only the MBON07 bodies differ.

Each stage is one invocation so it fits a bounded session; ``compare`` reads the saved counts.
This is an engineering verification of the execution path (ADR-2026-009). It is not an
evidence artifact and awards nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


def _log(*parts: Any) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def compare(workdir: Path) -> dict[str, Any]:
    homogeneous = np.load(workdir / "hetero_homogeneous.npz")
    fallback = np.load(workdir / "hetero_fallback.npz")
    heterogeneous = np.load(workdir / "hetero_v03.npz")
    c_hom = homogeneous["counts"]
    c_fb = fallback["counts"]
    c_het = heterogeneous["counts"]
    mbon = homogeneous["mbon_dense"]
    differ = c_het != c_hom
    result = {
        "fallback_only_vs_homogeneous": {
            "spike_counts_identical": bool(np.array_equal(c_hom, c_fb)),
            "neurons_with_different_counts": int(np.count_nonzero(c_hom != c_fb)),
            "total_spikes_homogeneous": float(c_hom.sum()),
            "total_spikes_fallback_only": float(c_fb.sum()),
        },
        "v0_3_vs_homogeneous": {
            "neurons_with_different_counts": int(np.count_nonzero(differ)),
            "differing_non_mbon07_neurons": int(
                np.count_nonzero(differ) - sum(1 for index in mbon if differ[index])
            ),
            "mbon07_counts_homogeneous": [float(c_hom[index]) for index in mbon],
            "mbon07_counts_heterogeneous": [float(c_het[index]) for index in mbon],
            "total_spikes_heterogeneous": float(c_het.sum()),
        },
        "stages": {
            name: json.loads((workdir / f"hetero_{name}.json").read_text(encoding="utf-8"))
            for name in ("homogeneous", "fallback", "v03")
        },
    }
    (workdir / "hetero_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_stage(
    stage: str,
    *,
    root: Path,
    repo: Path,
    workdir: Path,
    registry_path: Path,
    drive_hz: float,
    duration_us: int,
) -> dict[str, Any]:
    from flysim.circuit import load_cell_types
    from flysim.connectome import SparseConnectome
    from flysim.contracts import NeuralInputFrame, SignalType
    from flysim.dynamics import CELL_PARAMETER_KEYS, DynamicsRegistry
    from flysim.engines.genn import TrackAGeNNEngine
    from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs

    graph = SparseConnectome.load(root / "derived/male-cns-v1.0/graph")
    graph.validate()
    _log("graph", graph.neuron_count, graph.edge_count)
    assumptions = json.loads((repo / "configs/assumptions.json").read_text(encoding="utf-8"))
    track_a = next(record for record in assumptions["records"] if record["id"] == "TRACKA-01")
    values = dict(track_a["value"])
    populations = json.loads(
        (root / "derived/male-cns-v1.0/population-resolution.json").read_text(encoding="utf-8")
    )
    by_id = {
        item["id"]: [int(body) for body in item["body_ids"]]
        for item in populations["populations"]
    }
    signs = build_shiu_regression_signs(
        graph,
        root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather",
        unresolved_policy=UnresolvedSignPolicy(str(values["unresolved_sign_policy"])),
        seed=1,
    ).edge_signs
    entry = tuple(
        dict.fromkeys(
            body
            for population in (
                "ethyl-acetate-receptor-entry",
                "grooming-jo-f",
                "sucrose-receptor-entry",
            )
            for body in by_id[population]
        )
    )
    cell_types = load_cell_types(
        root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather",
        graph.body_ids,
    )
    registry = DynamicsRegistry.load(registry_path)
    resolution = registry.resolve_parameters(cell_types)
    fallback = registry.parameter_sets[registry.fallback_parameter_set_id].values
    mbon_dense = np.asarray([index for index, label in enumerate(cell_types) if label == "MBON07"])
    mbon_ids = [int(graph.body_ids[index]) for index in mbon_dense]
    regimes = tuple(regime.value for regime in resolution.signal_regimes)
    if stage == "homogeneous":
        extra: dict[str, Any] = {}
    elif stage == "fallback":
        extra = {
            "per_neuron_parameters": {
                key: np.full(graph.neuron_count, fallback[key], dtype=np.float64)
                for key in CELL_PARAMETER_KEYS
            },
            "signal_regimes": regimes,
        }
    elif stage == "v03":
        extra = {
            "per_neuron_parameters": resolution.parameter_arrays,
            "signal_regimes": regimes,
            "cell_parameter_report": resolution.as_dict(),
        }
    else:
        raise SystemExit(f"unknown stage {stage!r}")

    engine = TrackAGeNNEngine(root / "cache/genn/review-hetero" / stage, variant="exact")
    started = time.perf_counter()
    engine.initialize(
        graph,
        {**values, **extra, "functional_edge_signs": signs, "entry_body_ids": entry},
        1,
    )
    build_seconds = time.perf_counter() - started
    inputs = tuple(by_id["grooming-jo-f"])
    engine.push_inputs(
        NeuralInputFrame(
            t_us=0,
            ids=inputs,
            values=tuple([drive_hz] * len(inputs)),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="E",
            assumption_ids=("TRACKA-01",),
            metadata={},
        )
    )
    started = time.perf_counter()
    engine.step_until(duration_us)
    simulation_seconds = time.perf_counter() - started
    readout_ids = tuple(by_id["grooming-descending-readout"]) + tuple(mbon_ids)
    output = engine.read_outputs(readout_ids, duration_us)
    counts = np.zeros(graph.neuron_count, dtype=np.float64)
    for population, dense in zip(engine._populations, engine._group_dense_indices, strict=True):
        variable = population.vars["SpikeCount"]
        variable.pull_from_device()
        counts[dense] = np.asarray(variable.view, dtype=np.float64)
    cell_parameters = output.metadata["cell_parameters"]
    engine.close()
    record = {
        "stage": stage,
        "drive_hz": drive_hz,
        "duration_us": duration_us,
        "build_seconds": build_seconds,
        "simulation_seconds": simulation_seconds,
        "total_spikes": float(counts.sum()),
        "active_neurons": int(np.count_nonzero(counts)),
        "readout_rates_hz": dict(zip([str(i) for i in readout_ids], output.values, strict=True)),
        "mbon07_body_ids": mbon_ids,
        "mbon07_spikes": [float(counts[index]) for index in mbon_dense],
        "heterogeneous": cell_parameters["heterogeneous"],
        "promoted": cell_parameters["promoted_to_per_neuron_vars"],
        "model_identity": output.metadata["model_identity"],
    }
    workdir.mkdir(parents=True, exist_ok=True)
    np.savez(workdir / f"hetero_{stage}.npz", counts=counts, mbon_dense=mbon_dense)
    (workdir / f"hetero_{stage}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["homogeneous", "fallback", "v03", "compare"])
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/neural/cell-dynamics-v0.3.json",
    )
    parser.add_argument("--drive-hz", type=float, default=200.0)
    parser.add_argument("--duration-us", type=int, default=300_000)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo / "src"))
    if args.stage == "compare":
        result = compare(args.workdir)
    else:
        result = run_stage(
            args.stage,
            root=args.root,
            repo=args.repo,
            workdir=args.workdir,
            registry_path=args.registry,
            drive_hz=args.drive_hz,
            duration_us=args.duration_us,
        )
    _log(json.dumps({k: v for k, v in result.items() if k not in {"readout_rates_hz", "stages"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
