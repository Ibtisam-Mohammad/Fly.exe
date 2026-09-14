# SPDX-License-Identifier: GPL-2.0-or-later
"""Measured two/four-state capacity benchmark for the shared full-graph engine."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flysim.errors import ConfigurationError
from flysim.multifly_live import build_full_cns_runtime
from flysim.runs import git_metadata


def _gpu_memory() -> dict[str, int] | None:
    try:
        process = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    first = process.stdout.strip().splitlines()[0].split(",")
    if len(first) != 2:
        return None
    try:
        return {"used_mb": int(first[0].strip()), "total_mb": int(first[1].strip())}
    except ValueError:
        return None


def benchmark_multifly_full_graph(
    *,
    data_root: Path,
    agent_counts: Sequence[int],
    duration_us: int,
    seed: int,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if duration_us <= 0:
        raise ConfigurationError("Multi-fly benchmark duration must be positive")
    counts = tuple(int(value) for value in agent_counts)
    if not counts or any(not 1 <= value <= 16 for value in counts):
        raise ConfigurationError("Multi-fly benchmark counts must lie in [1, 16]")
    if len(set(counts)) != len(counts):
        raise ConfigurationError("Multi-fly benchmark counts must be unique")

    rows: list[dict[str, Any]] = []
    for count in counts:
        before = _gpu_memory()
        started = time.perf_counter()
        runtime = None
        try:
            runtime = build_full_cns_runtime(
                data_root=data_root,
                seed=seed,
                neural_copies=count,
            )
            build_seconds = time.perf_counter() - started
            after_build = _gpu_memory()
            initial_snapshot = runtime.snapshot()
            coupling_us = runtime.coordinator.coupling_us
            steps = -(-duration_us // coupling_us)
            simulation_started = time.perf_counter()
            for _ in range(steps):
                runtime.step()
            simulation_seconds = time.perf_counter() - simulation_started
            snapshot = runtime.snapshot()
            after_run = _gpu_memory()
            targets = [
                item
                for item in initial_snapshot["arena"]["stimuli"]
                if item["kind"] in {"food", "visual-target"}
            ]
            if not targets:
                raise ConfigurationError("Multi-fly capacity scenario has no target")
            target = targets[0]
            initial_flies = {
                item["id"]: item for item in initial_snapshot["arena"]["flies"]
            }
            motion = []
            for final in snapshot["arena"]["flies"]:
                initial = initial_flies[final["id"]]
                initial_distance = math.hypot(
                    initial["x_mm"] - target["x_mm"],
                    initial["y_mm"] - target["y_mm"],
                )
                final_distance = math.hypot(
                    final["x_mm"] - target["x_mm"],
                    final["y_mm"] - target["y_mm"],
                )
                motion.append(
                    {
                        "agent_id": final["id"],
                        "initial_target_distance_mm": initial_distance,
                        "final_target_distance_mm": final_distance,
                        "target_distance_change_mm": initial_distance - final_distance,
                        "path_length_mm": final["path_length_mm"],
                        "approached_target": final_distance < initial_distance,
                    }
                )
            rows.append(
                {
                    "agent_count": count,
                    "status": "completed",
                    "build_seconds": build_seconds,
                    "simulation_wall_seconds": simulation_seconds,
                    "biological_seconds": steps * coupling_us / 1_000_000.0,
                    "biological_per_wall": (
                        steps * coupling_us / 1_000_000.0 / simulation_seconds
                    ),
                    "gpu_before": before,
                    "gpu_after_build": after_build,
                    "gpu_after_run": after_run,
                    "connectivity_allocations": sum(
                        int(
                            cohort["checkpoint"].get("connectivity_allocations", 1)
                        )
                        for cohort in snapshot["neural"]["cohorts"]
                    ),
                    "target": {
                        "id": target["id"],
                        "kind": target["kind"],
                        "x_mm": target["x_mm"],
                        "y_mm": target["y_mm"],
                        "radius_mm": target["radius_mm"],
                    },
                    "posthoc_motion_metrics": motion,
                    "agents_approaching_target": sum(
                        bool(item["approached_target"]) for item in motion
                    ),
                    "runtime": snapshot["runtime"],
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "agent_count": count,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "gpu_before": before,
                    "gpu_at_failure": _gpu_memory(),
                }
            )
        finally:
            if runtime is not None:
                runtime.close()
        rows[-1]["gpu_after_close"] = _gpu_memory()

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "benchmark": "multifly-full-graph-capacity-v1",
        "evidence_grade": False,
        "validation_tier_awarded": None,
        "code": git_metadata(),
        "seed": seed,
        "duration_us_requested": duration_us,
        "runs": rows,
        "interpretation": (
            "Agents share one exact connectivity allocation within a batch and have "
            "separate neuron state. Passing is an engineering capacity result only; the "
            "agents are parameterised copies of one specimen."
        ),
        "assumption_ids": ["MULTI-01", "WEB-01"],
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".part")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output_path)
    return payload


__all__ = ["benchmark_multifly_full_graph"]
