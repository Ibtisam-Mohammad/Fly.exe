# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute and evaluate the preregistered Track A controls.

Every control carries a falsifiable criterion drawn from the experiment specification.
The previous revision registered the shuffled-connectome control with no blocked
transition, which made its ``passed`` field unconditionally true and meant the control
could never falsify the acceptance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


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


def _require_clean_worktree() -> str:
    """Refuse to produce control evidence whose code state cannot be recovered."""
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise RuntimeError(
            "Track A controls require a clean git worktree so that the recorded commit "
            f"{commit[:8]} reproduces the executed code. Uncommitted changes:\n{dirty}"
        )
    return commit


def _latest_result(output_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for manifest in sorted(output_root.glob("*/manifest.json")):
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        candidates.append((manifest, raw))
    if not candidates:
        raise RuntimeError(f"No run manifest was written under {output_root}")
    manifest, raw = candidates[-1]
    validation_path = manifest.parent / "validation-report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    return manifest, raw, validation


def _run(
    command: list[str], output_root: Path, *, expected_commit: str
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if list(output_root.glob("*/manifest.json")):
        try:
            manifest, raw, validation = _latest_result(output_root)
        except RuntimeError:
            pass
        else:
            _require_reusable(raw, expected_commit, output_root)
            return manifest, raw, validation
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        manifest, raw, validation = _latest_result(output_root)
    except RuntimeError as exc:
        raise RuntimeError(
            f"Control run produced no manifest under {output_root}; "
            f"return={completed.returncode}; stderr={completed.stderr[-2000:]}"
        ) from exc
    if not validation["valid"]:
        raise RuntimeError(f"Control run is structurally invalid: {validation['failures']}")
    _require_reusable(raw, expected_commit, output_root)
    return manifest, raw, validation


def _require_reusable(raw: dict[str, Any], expected_commit: str, output_root: Path) -> None:
    """Reject a resumed run that a different or uncommitted code state produced."""
    git = raw.get("git", {})
    if git.get("dirty"):
        raise RuntimeError(f"Refusing a control run produced from a dirty tree: {output_root}")
    if git.get("commit") != expected_commit:
        raise RuntimeError(
            f"Refusing a control run from commit {git.get('commit')}; "
            f"the current worktree is {expected_commit} ({output_root})"
        )


def _event_targets(manifest: dict[str, Any]) -> list[str]:
    return [event["to_state"] for event in manifest["result"]["events"]]


def _peak_readout(run_directory: Path, readout_id: str) -> float:
    """Peak per-coupling readout rate for one population across a run trace."""
    peak = 0.0
    trace_path = run_directory / "trace.jsonl"
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        neural = record.get("neural", {})
        ids = list(neural.get("ids", []))
        if readout_id not in ids:
            continue
        peak = max(peak, float(neural["values"][ids.index(readout_id)]))
    return peak


def _exact_reference_peak(primary: dict[str, Any], readout_id: str) -> dict[str, Any]:
    """Median peak readout across the exact-graph primary matrix."""
    peaks = [
        _peak_readout(Path(row["run_directory"]), readout_id)
        for row in primary["conditions"].values()
    ]
    return {
        "readout": readout_id,
        "runs": len(peaks),
        "median_peak_hz": statistics.median(peaks),
        "minimum_peak_hz": min(peaks),
        "maximum_peak_hz": max(peaks),
        "source": "exact-graph primary acceptance matrix",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--primary-progress", type=Path)
    parser.add_argument(
        "--experiment",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "configs"
        / "experiments"
        / "track-a-acceptance.json",
    )
    args = parser.parse_args()
    experiment_bytes = args.experiment.read_bytes()
    experiment = json.loads(experiment_bytes)
    criteria = experiment["control_criteria"]
    commit = _require_clean_worktree()
    graph = args.graph or args.root / "derived" / "male-cns-v1.0" / "graph"
    output = args.output or args.root / "evidence" / "male-cns-v1.0" / "track-a-controls.json"
    output_root = args.run_root or args.root / "runs" / "track-a-controls"
    primary_path = (
        args.primary_progress
        or args.root / "runs" / "track-a-acceptance" / "primary-progress.json"
    )
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
    if primary.get("experiment_sha256") != hashlib.sha256(experiment_bytes).hexdigest():
        raise RuntimeError(
            "The primary matrix was produced from a different experiment specification"
        )
    reference_position = experiment["held_out_food_positions_mm"][1]
    base = [
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
        "1",
        "--food-x-mm",
        str(reference_position["x"]),
        "--food-y-mm",
        str(reference_position["y"]),
    ]
    definitions = (
        (
            "contamination-input-ablation",
            ["--ablate-input", "sensory:antenna-contamination", "--headless"],
        ),
        (
            "groom-readout-ablation",
            ["--ablate-output", "readout:antennal-grooming-DN", "--headless"],
        ),
        ("sucrose-input-ablation", ["--ablate-input", "sensory:sucrose-contact", "--headless"]),
        ("mn9-readout-ablation", ["--ablate-output", "readout:MN9", "--headless"]),
        ("zero-weight", ["--control", "zero-weight", "--headless"]),
        ("shuffled-connectome", ["--control", "shuffled-connectome", "--headless"]),
    )
    results: dict[str, Any] = {}
    degradation_reference: dict[str, Any] | None = None
    for control_id, extra in definitions:
        destination = output_root / control_id
        criterion = criteria[control_id]
        print(json.dumps({"event": "control_started", "control": control_id}), flush=True)
        manifest_path, manifest, validation = _run(
            [*base, *extra, "--output-root", str(destination)],
            destination,
            expected_commit=commit,
        )
        targets = _event_targets(manifest)
        record: dict[str, Any] = {
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": _sha256(manifest_path),
            "completed": manifest["result"]["completed"],
            "event_targets": targets,
            "criterion": criterion,
            "validation": validation,
        }
        if criterion["type"] == "blocked-transition":
            record["blocked_transition"] = criterion["transition"]
            record["passed"] = criterion["transition"] not in targets
        elif criterion["type"] == "readout-degradation":
            if degradation_reference is None:
                degradation_reference = _exact_reference_peak(primary, criterion["readout"])
            allowed = float(criterion["max_fraction_of_exact_peak"]) * float(
                degradation_reference["median_peak_hz"]
            )
            observed = _peak_readout(manifest_path.parent, criterion["readout"])
            record["exact_reference"] = degradation_reference
            record["observed_peak_hz"] = observed
            record["allowed_peak_hz"] = allowed
            record["completed_requirement_met"] = not (
                criterion["must_not_complete"] and manifest["result"]["completed"]
            )
            record["degradation_requirement_met"] = observed <= allowed
            record["passed"] = bool(
                record["completed_requirement_met"] and record["degradation_requirement_met"]
            )
        else:
            raise RuntimeError(f"Unsupported control criterion: {criterion['type']}")
        results[control_id] = record
        print(
            json.dumps(
                {
                    "event": "control_finished",
                    "control": control_id,
                    "passed": record["passed"],
                }
            ),
            flush=True,
        )

    viewer_root = output_root / "viewer"
    viewer_manifest_path, viewer_manifest, viewer_validation = _run(
        [*base, "--render", "--output-root", str(viewer_root)],
        viewer_root,
        expected_commit=commit,
    )
    headless_key = f"{reference_position['id']}:seed-1"
    headless_manifest_path = Path(primary["conditions"][headless_key]["manifest"])
    headless_manifest = json.loads(headless_manifest_path.read_text(encoding="utf-8"))
    viewer_events = viewer_manifest["result"]["events"]
    headless_events = headless_manifest["result"]["events"]
    video = viewer_manifest_path.parent / "flygym.mp4"
    viewer_signature = [
        (event["from_state"], event["to_state"], event["reason"]) for event in viewer_events
    ]
    headless_signature = [
        (event["from_state"], event["to_state"], event["reason"]) for event in headless_events
    ]
    timing_differences_us = [
        int(viewer["t_us"]) - int(headless["t_us"])
        for viewer, headless in zip(viewer_events, headless_events, strict=True)
    ]
    equivalence_passed = viewer_signature == headless_signature
    results["headless-viewer-equivalence"] = {
        "headless_manifest": str(headless_manifest_path.resolve()),
        "headless_manifest_sha256": _sha256(headless_manifest_path),
        "viewer_manifest": str(viewer_manifest_path.resolve()),
        "viewer_manifest_sha256": _sha256(viewer_manifest_path),
        "criterion": criteria["headless-viewer-equivalence"],
        "transition_signatures_identical": equivalence_passed,
        "transition_timing_differences_us": timing_differences_us,
        "video": str(video.resolve()),
        "video_sha256": _sha256(video),
        "validation": viewer_validation,
        "passed": equivalence_passed,
    }

    controller_manifest = Path("artifacts/controller-only/body-preview.json").resolve()
    controller_present = controller_manifest.is_file()
    results["controller-only"] = {
        "manifest": str(controller_manifest),
        "manifest_sha256": _sha256(controller_manifest) if controller_present else None,
        "criterion": criteria["controller-only"],
        "passed": controller_present,
    }
    bypass_root = output_root / "neural-bypass"
    bypass_command = [
        sys.executable,
        "-u",
        "-m",
        "flysim.cli",
        "run",
        "eon-demo",
        "--seed",
        "1",
        "--headless",
        "--output-root",
        str(bypass_root),
    ]
    bypass_manifest_path, bypass_manifest, bypass_validation = _run(
        bypass_command, bypass_root, expected_commit=commit
    )
    if not bypass_validation["valid"]:
        raise RuntimeError("The neural-bypass control run is structurally invalid")
    results["neural-bypass"] = {
        "manifest": str(bypass_manifest_path.resolve()),
        "manifest_sha256": _sha256(bypass_manifest_path),
        "connectome_graph_used": bypass_manifest["connectome"]["graph_used"],
        "criterion": criteria["neural-bypass"],
        "passed": bypass_manifest["connectome"]["graph_used"] is False,
    }

    speed_threshold = float(experiment["minimum_biological_seconds_per_wall_second"])
    speeds = [
        float(row["biological_seconds_per_wall_second"]) for row in primary["conditions"].values()
    ]
    cold_start_speeds = [
        float(row["biological_seconds_per_wall_second_cold_start"])
        for row in primary["conditions"].values()
        if row.get("biological_seconds_per_wall_second_cold_start") is not None
    ]
    speed_passed = min(speeds) >= speed_threshold
    payload = {
        "schema_version": "2.0",
        "experiment_id": experiment["experiment_id"],
        "experiment_sha256": hashlib.sha256(experiment_bytes).hexdigest(),
        "code_commit": commit,
        "primary_progress": str(primary_path.resolve()),
        "primary_progress_sha256": _sha256(primary_path),
        "primary_matrix_passed": primary["primary_matrix_passed"],
        "controls": results,
        "all_required_controls_passed": all(
            bool(results[name]["passed"]) for name in experiment["required_controls"]
        ),
        "performance": {
            "metric": experiment["throughput_metric"],
            "minimum_biological_seconds_per_wall_second": min(speeds),
            "median_biological_seconds_per_wall_second": statistics.median(speeds),
            "minimum_cold_start_biological_seconds_per_wall_second": (
                min(cold_start_speeds) if cold_start_speeds else None
            ),
            "required_minimum": speed_threshold,
            "passed": speed_passed,
            "classification": "offline-prototype" if not speed_passed else "interactive",
        },
        "tier_awarded": None,
        "claim_boundary": experiment["claim_boundary"],
    }
    _write_atomic(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["all_required_controls_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
