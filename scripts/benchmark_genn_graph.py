# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure GeNN CUDA construction/loading for the imported structural graph.

All benchmark synapses have zero functional weight. This exercises sparse topology
allocation without claiming that MaleCNS contact counts determine conductance or sign.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from flysim.connectome import SparseConnectome


def _gpu_memory() -> dict[str, int]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    used, free, total = (int(value.strip()) for value in completed.stdout.split(","))
    return {"used_mib": used, "free_mib": free, "total_mib": total}


def _uniform_edge_sample(
    graph: SparseConnectome, scale: float
) -> tuple[np.ndarray, np.ndarray]:
    requested = max(1, round(graph.edge_count * scale))
    if requested == graph.edge_count:
        return graph.source_indices, graph.target_indices
    selection = np.floor(
        np.arange(requested, dtype=np.float64) * graph.edge_count / requested
    ).astype(np.int64)
    return graph.source_indices[selection], graph.target_indices[selection]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--scales", type=float, nargs="+", default=[0.01, 0.1, 1.0])
    parser.add_argument(
        "--build-root",
        type=Path,
        default=Path("/srv/flybrain-data/cache/genn-graph-benchmark"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if any(not 0.0 < scale <= 1.0 for scale in args.scales):
        raise ValueError("scales must be in (0, 1]")

    from pygenn import GeNNModel, init_postsynaptic, init_weight_update

    graph = SparseConnectome.load(args.graph)
    results: list[dict[str, object]] = []
    for scale in args.scales:
        source_indices, target_indices = _uniform_edge_sample(graph, scale)
        model_name = f"male_cns_load_{len(source_indices)}"
        build_path = args.build_root / model_name
        build_path.mkdir(parents=True, exist_ok=True)
        before = _gpu_memory()
        started = time.perf_counter()
        model = GeNNModel(
            "float",
            model_name,
            backend="cuda",
            manual_device_id=0,
        )
        model.seed = args.seed
        model.dt = 0.1
        population = model.add_neuron_population(
            "neurons",
            graph.neuron_count,
            "LIF",
            {
                "C": 1.0,
                "TauM": 20.0,
                "Vrest": -65.0,
                "Vreset": -65.0,
                "Vthresh": -50.0,
                "Ioffset": 0.0,
                "TauRefrac": 5.0,
            },
            {"V": -65.0, "RefracTime": 0.0},
        )
        synapses = model.add_synapse_population(
            "structural_edges",
            "SPARSE",
            population,
            population,
            init_weight_update("StaticPulseConstantWeight", {"g": 0.0}),
            init_postsynaptic("DeltaCurr"),
        )
        synapses.set_sparse_connections(source_indices, target_indices)
        configured_s = time.perf_counter() - started
        build_started = time.perf_counter()
        model.build(path_to_model=str(build_path), always_rebuild=True)
        build_s = time.perf_counter() - build_started
        load_started = time.perf_counter()
        model.load()
        load_s = time.perf_counter() - load_started
        loaded = _gpu_memory()
        step_started = time.perf_counter()
        model.step_time()
        step_s = time.perf_counter() - step_started
        model.unload()
        results.append(
            {
                "scale": scale,
                "neurons": graph.neuron_count,
                "edges": len(source_indices),
                "configured_s": configured_s,
                "build_s": build_s,
                "load_s": load_s,
                "one_timestep_s": step_s,
                "gpu_before": before,
                "gpu_loaded": loaded,
                "model_gpu_delta_mib": loaded["used_mib"] - before["used_mib"],
                "build_path": str(build_path.resolve()),
            }
        )
    payload = {
        "schema_version": "1.0",
        "backend": "GeNN 5.4 CUDA",
        "device_id": 0,
        "precision": "float32",
        "graph": str(args.graph.resolve()),
        "graph_source_sha256": graph.source_sha256,
        "topology_sampling": "uniform by aggregate-edge row for scales below 1.0",
        "functional_weight": 0.0,
        "functional_weight_provenance": "E; allocation-only, not neural dynamics",
        "results": results,
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
