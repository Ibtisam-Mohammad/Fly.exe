# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate deterministic NumPy, Brian2, and direct PyGeNN LIF fixtures."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from flysim.neural_parity import (
    ParityCircuit,
    compare_spikes,
    run_brian2,
    run_genn,
    run_numpy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-path",
        type=Path,
        default=Path("/srv/flybrain-data/cache/genn-parity"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-genn", action="store_true")
    args = parser.parse_args()
    circuit = ParityCircuit()
    numpy_times, numpy_ids = run_numpy(circuit)
    brian_times, brian_ids = run_brian2(circuit)
    comparisons = {
        "brian2_vs_numpy": compare_spikes(
            numpy_times,
            numpy_ids,
            brian_times,
            brian_ids,
            tolerance_ms=circuit.dt_ms,
        )
    }
    if not args.skip_genn:
        genn_times, genn_ids = run_genn(circuit, args.build_path)
        comparisons["genn_vs_numpy"] = compare_spikes(
            numpy_times,
            numpy_ids,
            genn_times,
            genn_ids,
            tolerance_ms=circuit.dt_ms,
        )
    payload = {
        "schema_version": "1.0",
        "evidence_kind": "deterministic-small-circuit-backend-parity",
        "validation_tier": "none; numerical implementation evidence only",
        "assumption_ids": ["ND-LIF-01", "ND-01", "ND-04", "NUM-01"],
        "circuit_sha256": circuit.identity(),
        "circuit": asdict(circuit),
        "backends": {
            "numpy": importlib.metadata.version("numpy"),
            "brian2": importlib.metadata.version("brian2"),
            "pygenn": None if args.skip_genn else importlib.metadata.version("pygenn"),
            "genn_precision": None if args.skip_genn else "float32",
        },
        "code_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        ).stdout.strip(),
        "comparisons": comparisons,
        "passed": all(item["passed"] for item in comparisons.values()),
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
