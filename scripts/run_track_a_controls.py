# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute and evaluate the preregistered Track A controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _run(command: list[str], output_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if list(output_root.glob("*/manifest.json")):
        try:
            return _latest_result(output_root)
        except RuntimeError:
            pass
    subprocess.run(command, capture_output=True, text=True, check=False)
    manifest, raw, validation = _latest_result(output_root)
    if not validation["valid"]:
        raise RuntimeError(f"Control run is structurally invalid: {validation['failures']}")
    return manifest, raw, validation


def _event_targets(manifest: dict[str, Any]) -> list[str]:
    return [event["to_state"] for event in manifest["result"]["events"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--primary-progress", type=Path)
    args = parser.parse_args()
    graph = args.graph or args.root / "derived" / "male-cns-v1.0" / "graph"
    output = args.output or args.root / "evidence" / "male-cns-v1.0" / "track-a-controls.json"
    output_root = args.run_root or args.root / "runs" / "track-a-controls"
    primary_path = (
        args.primary_progress
        or args.root / "runs" / "track-a-acceptance" / "primary-progress.json"
    )
    primary = json.loads(primary_path.read_text(encoding="utf-8"))
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
        "12000000",
        "--seed",
        "1",
        "--food-x-mm",
        "8.0",
        "--food-y-mm",
        "0.0",
    ]
    definitions = (
        (
            "contamination-input-ablation",
            ["--ablate-input", "sensory:antenna-contamination", "--headless"],
            "GROOM",
        ),
        (
            "groom-readout-ablation",
            ["--ablate-output", "readout:antennal-grooming-DN", "--headless"],
            "GROOM",
        ),
        (
            "sucrose-input-ablation",
            ["--ablate-input", "sensory:sucrose-contact", "--headless"],
            "FEED_INITIATION",
        ),
        (
            "mn9-readout-ablation",
            ["--ablate-output", "readout:MN9", "--headless"],
            "FEED_INITIATION",
        ),
        ("zero-weight", ["--control", "zero-weight", "--headless"], "GROOM"),
        ("shuffled-connectome", ["--control", "shuffled-connectome", "--headless"], None),
    )
    results: dict[str, Any] = {}
    for control_id, extra, blocked_transition in definitions:
        destination = output_root / control_id
        print(json.dumps({"event": "control_started", "control": control_id}), flush=True)
        manifest_path, manifest, validation = _run(
            [*base, *extra, "--output-root", str(destination)], destination
        )
        targets = _event_targets(manifest)
        passed = blocked_transition is None or blocked_transition not in targets
        results[control_id] = {
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": _sha256(manifest_path),
            "completed": manifest["result"]["completed"],
            "event_targets": targets,
            "blocked_transition": blocked_transition,
            "passed": passed,
            "validation": validation,
        }
        print(
            json.dumps(
                {"event": "control_finished", "control": control_id, "passed": passed}
            ),
            flush=True,
        )

    viewer_root = output_root / "viewer"
    viewer_manifest_path, viewer_manifest, viewer_validation = _run(
        [*base, "--render", "--output-root", str(viewer_root)], viewer_root
    )
    headless_manifest_path = Path(primary["conditions"]["center:seed-1"]["manifest"])
    headless_manifest = json.loads(headless_manifest_path.read_text(encoding="utf-8"))
    viewer_events = viewer_manifest["result"]["events"]
    headless_events = headless_manifest["result"]["events"]
    video = viewer_manifest_path.parent / "flygym.mp4"
    viewer_signature = [
        (event["from_state"], event["to_state"], event["reason"])
        for event in viewer_events
    ]
    headless_signature = [
        (event["from_state"], event["to_state"], event["reason"])
        for event in headless_events
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
        "transition_signatures_identical": equivalence_passed,
        "transition_timing_differences_us": timing_differences_us,
        "video": str(video.resolve()),
        "video_sha256": _sha256(video),
        "validation": viewer_validation,
        "passed": equivalence_passed,
    }

    controller_manifest = Path("artifacts/controller-only/body-preview.json").resolve()
    results["controller-only"] = {
        "manifest": str(controller_manifest),
        "manifest_sha256": _sha256(controller_manifest),
        "passed": controller_manifest.is_file(),
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
        bypass_command, bypass_root
    )
    results["neural-bypass"] = {
        "manifest": str(bypass_manifest_path.resolve()),
        "manifest_sha256": _sha256(bypass_manifest_path),
        "connectome_graph_used": bypass_manifest["connectome"]["graph_used"],
        "validation": bypass_validation,
        "passed": bypass_manifest["connectome"]["graph_used"] is False,
    }

    speed_threshold = 0.5
    speeds = [
        float(row["biological_seconds_per_wall_second"])
        for row in primary["conditions"].values()
    ]
    speed_passed = min(speeds) >= speed_threshold
    payload = {
        "schema_version": "1.0",
        "experiment_id": "track-a-eon-malecns-controls-v1",
        "primary_progress": str(primary_path.resolve()),
        "primary_progress_sha256": _sha256(primary_path),
        "primary_matrix_passed": primary["primary_matrix_passed"],
        "controls": results,
        "all_required_controls_passed": all(
            bool(value["passed"]) for value in results.values()
        ),
        "performance": {
            "minimum_biological_seconds_per_wall_second": min(speeds),
            "median_biological_seconds_per_wall_second": sorted(speeds)[len(speeds) // 2],
            "required_minimum": speed_threshold,
            "passed": speed_passed,
            "classification": "offline-prototype" if not speed_passed else "interactive",
        },
        "highest_validation_tier": "V0 Structural (project foundation only)",
        "tier_awarded": None,
        "claim_boundary": "Engineering integration controls only; awards no validation tier.",
    }
    _write_atomic(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["all_required_controls_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
