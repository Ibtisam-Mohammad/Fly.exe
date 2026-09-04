# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile and execute the smallest useful CUDA-backed GeNN model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path("/srv/flybrain-data/cache/genn-smoke"),
    )
    args = parser.parse_args()

    from pygenn import GeNNModel

    args.build_dir.mkdir(parents=True, exist_ok=True)
    model = GeNNModel(
        "float",
        "flybrain_smoke",
        backend="cuda",
        manual_device_id=0,
    )
    model.dt = 0.1
    population = model.add_neuron_population(
        "neurons",
        1,
        "LIF",
        {
            "C": 1.0,
            "TauM": 20.0,
            "Vrest": -65.0,
            "Vreset": -65.0,
            "Vthresh": -50.0,
            "Ioffset": 1.0,
            "TauRefrac": 5.0,
        },
        {"V": -65.0, "RefracTime": 0.0},
    )
    model.build(path_to_model=str(args.build_dir), always_rebuild=True)
    model.load()
    model.step_time()
    population.vars["V"].pull_from_device()
    print(
        json.dumps(
            {
                "backend": model.backend_name,
                "device_id": 0,
                "precision": "float32",
                "t_ms": model.t,
                "voltage_mv": float(population.vars["V"].values[0]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
