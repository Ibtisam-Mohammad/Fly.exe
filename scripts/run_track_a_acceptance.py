# SPDX-License-Identifier: GPL-2.0-or-later
"""Run and resume the preregistered Track A seed/location matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(part, path)


def _progress(event: str, **values: Any) -> None:
    print(json.dumps({"event": event, **values}, sort_keys=True), file=sys.stderr, flush=True)


def _load_existing(path: Path, experiment_sha256: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": "1.0",
            "experiment_sha256": experiment_sha256,
            "conditions": {},
        }
    result = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if result.get("experiment_sha256") != experiment_sha256:
        raise ValueError("Refusing to resume with a different Track A experiment specification")
    return result


def _recover_result(
    output_root: Path, *, seed: int, position: dict[str, Any]
) -> dict[str, Any] | None:
    """Recover a fully written run if CUDA teardown ended before stdout flushed."""
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    for manifest in output_root.glob("*/manifest.json"):
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if raw.get("random_seed") != seed:
            continue
        if raw.get("run_metadata", {}).get("food_position_mm") != [
            position["x"],
            position["y"],
        ]:
            continue
        validation_path = manifest.parent / "validation-report.json"
        if not validation_path.is_file():
            continue
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        candidates.append((str(raw.get("created_at", "")), manifest, validation))
    if not candidates:
        return None
    _, manifest, validation = max(candidates, key=lambda value: value[0])
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        "run_directory": str(manifest.parent),
        "completed": bool(raw["result"]["completed"]),
        "final_state": raw["result"]["final_state"],
        "biological_seconds_per_wall_second": raw["run_metadata"][
            "biological_seconds_per_wall_second"
        ],
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment",
        type=Path,
        default=Path("configs/experiments/track-a-acceptance.json"),
    )
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--seed", type=int, action="append", dest="selected_seeds")
    parser.add_argument("--position", action="append", dest="selected_positions")
    args = parser.parse_args()

    experiment_bytes = args.experiment.read_bytes()
    experiment_sha256 = hashlib.sha256(experiment_bytes).hexdigest()
    experiment = json.loads(experiment_bytes)
    graph = args.graph or args.root / "derived" / "male-cns-v1.0" / "graph"
    output_root = args.output_root or args.root / "runs" / "track-a-acceptance"
    progress_path = args.progress or output_root / "primary-progress.json"
    progress = _load_existing(progress_path, experiment_sha256)
    positions = [
        value
        for value in experiment["held_out_food_positions_mm"]
        if args.selected_positions is None or value["id"] in args.selected_positions
    ]
    seeds = [
        int(value)
        for value in experiment["seeds"]
        if args.selected_seeds is None or int(value) in args.selected_seeds
    ]
    if not positions or not seeds:
        raise ValueError("The selected Track A acceptance matrix is empty")

    for position in positions:
        for seed in seeds:
            key = f"{position['id']}:seed-{seed}"
            existing = progress["conditions"].get(key)
            if isinstance(existing, dict):
                manifest = Path(str(existing.get("manifest", "")))
                if manifest.is_file() and _sha256(manifest) == existing.get("manifest_sha256"):
                    _progress("condition_skipped", condition=key)
                    continue
            recovered = _recover_result(output_root, seed=seed, position=position)
            if recovered is not None:
                run_directory = Path(recovered["run_directory"])
                manifest = run_directory / "manifest.json"
                progress["conditions"][key] = {
                    "position_id": position["id"],
                    "position_mm": [position["x"], position["y"]],
                    "seed": seed,
                    "completed": bool(recovered["completed"]),
                    "valid": bool(recovered["validation"]["valid"]),
                    "final_state": recovered["final_state"],
                    "biological_seconds_per_wall_second": recovered[
                        "biological_seconds_per_wall_second"
                    ],
                    "run_directory": str(run_directory.resolve()),
                    "manifest": str(manifest.resolve()),
                    "manifest_sha256": _sha256(manifest),
                    "return_code": None,
                }
                _write_atomic(progress_path, progress)
                _progress("condition_recovered", condition=key)
                continue
            command = [
                sys.executable,
                "-u",
                "-m",
                "flysim.cli",
                "run",
                "eon-malecns",
                "--graph",
                str(graph),
                "--root",
                str(args.root),
                "--duration-us",
                str(experiment["duration_us"]),
                "--seed",
                str(seed),
                "--food-x-mm",
                str(position["x"]),
                "--food-y-mm",
                str(position["y"]),
                "--headless",
                "--output-root",
                str(output_root),
            ]
            _progress("condition_started", condition=key)
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError:
                result = _recover_result(output_root, seed=seed, position=position)
                if result is None:
                    raise RuntimeError(
                        "Track A subprocess emitted invalid JSON and no valid run could be "
                        f"recovered for {key}; return={completed.returncode}; "
                        f"stderr={completed.stderr}"
                    ) from None
            run_directory = Path(result["run_directory"])
            manifest = run_directory / "manifest.json"
            progress["conditions"][key] = {
                "position_id": position["id"],
                "position_mm": [position["x"], position["y"]],
                "seed": seed,
                "completed": bool(result["completed"]),
                "valid": bool(result["validation"]["valid"]),
                "final_state": result["final_state"],
                "biological_seconds_per_wall_second": result[
                    "biological_seconds_per_wall_second"
                ],
                "run_directory": str(run_directory.resolve()),
                "manifest": str(manifest.resolve()),
                "manifest_sha256": _sha256(manifest),
                "return_code": completed.returncode,
            }
            _write_atomic(progress_path, progress)
            _progress(
                "condition_finished",
                condition=key,
                completed=result["completed"],
                final_state=result["final_state"],
            )

    minimum = int(experiment["minimum_successes_per_position"])
    summaries: dict[str, dict[str, Any]] = {}
    all_passed = True
    for position in positions:
        rows = [
            value
            for value in progress["conditions"].values()
            if value["position_id"] == position["id"] and value["seed"] in seeds
        ]
        successes = sum(bool(row["completed"] and row["valid"]) for row in rows)
        passed = len(rows) == len(seeds) and successes >= minimum
        all_passed &= passed
        summaries[position["id"]] = {
            "runs": len(rows),
            "successes": successes,
            "minimum_successes": minimum,
            "passed": passed,
        }
    progress["position_summaries"] = summaries
    progress["primary_matrix_passed"] = all_passed
    progress["claim_boundary"] = experiment["claim_boundary"]
    _write_atomic(progress_path, progress)
    print(json.dumps(progress, indent=2, sort_keys=True))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
