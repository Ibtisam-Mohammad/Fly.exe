# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail-closed assessment for the corrected Eon-class showcase.

The v2 presentation is an edit of three independently executed experiments.  This module
does not run them and cannot tune them.  It verifies their immutable verdicts, controls,
target coverage, body gate and video manifest before allowing a public-release claim.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from flysim.config import load_json, sha256_json
from flysim.errors import ValidationError


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _artifact(root: Path, specification: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    relative = Path(str(specification["path"]))
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValidationError(f"Artifact escapes the v2 bundle: {relative}")
    if not path.is_file():
        raise ValidationError(f"Required v2 artifact is missing: {relative}")
    observed = _sha256_file(path)
    expected = str(specification["sha256"])
    if observed != expected:
        raise ValidationError(
            f"Artifact checksum mismatch for {relative}: {observed} != {expected}"
        )
    return load_json(path), observed


def _criterion(verdict: Mapping[str, Any], prefix: str) -> bool:
    matches = [
        value
        for name, value in verdict.get("criteria", {}).items()
        if str(name).startswith(prefix)
    ]
    if len(matches) != 1:
        return False
    value = matches[0]
    if not isinstance(value, Mapping):
        return False
    return value.get("passed") is True or value.get("status") == "pass"


def _control_passed(
    component: Mapping[str, Any], name: str, failures: list[str], label: str
) -> None:
    controls = component.get("controls", {})
    control = controls.get(name) if isinstance(controls, Mapping) else None
    if not isinstance(control, Mapping) or control.get("passed") is not True:
        failures.append(f"{label}: required control {name} is missing or did not pass")


def evaluate_showcase_v2(
    *, contract: Mapping[str, Any], bundle_path: Path, require_video: bool = True
) -> dict[str, Any]:
    """Evaluate a v2 bundle without executing or rendering any experiment."""
    bundle = load_json(bundle_path)
    root = bundle_path.parent.resolve()
    failures: list[str] = []
    if bundle.get("experiment_id") != contract.get("experiment_id"):
        failures.append("bundle experiment_id does not match the v2 contract")
    if bundle.get("scientific_validation_tier_awarded") is not None:
        failures.append("the engineering bundle claims a scientific validation tier")

    components = bundle.get("components", {})
    if not isinstance(components, Mapping):
        raise ValidationError("v2 bundle components must be an object")
    required_controls = contract["required_controls_per_component"]
    control_names = tuple(required_controls["causal"]) + tuple(required_controls["body"])
    artifact_hashes: dict[str, str] = {}
    commits: set[str] = set()

    navigation_spec = contract["components"]["navigation"]
    navigation = components.get("navigation", [])
    if not isinstance(navigation, Sequence) or isinstance(navigation, (str, bytes)):
        navigation = []
    expected_targets = {str(item["id"]): item for item in navigation_spec["targets"]}
    seen_targets: set[str] = set()
    passed_targets = 0
    navigation_results: dict[str, Any] = {}
    for raw in navigation:
        if not isinstance(raw, Mapping):
            failures.append("navigation component entry is not an object")
            continue
        target_id = str(raw.get("target_id", ""))
        if target_id not in expected_targets or target_id in seen_targets:
            failures.append(f"navigation: unexpected or repeated target {target_id!r}")
            continue
        seen_targets.add(target_id)
        verdict, digest = _artifact(root, raw["verdict"])
        artifact_hashes[f"navigation:{target_id}"] = digest
        commit = str(raw.get("code_commit", ""))
        if not commit:
            failures.append(f"navigation:{target_id}: code_commit is missing")
        else:
            commits.add(commit)
        expected = expected_targets[target_id]
        if int(raw.get("seed", -1)) != int(expected["seed"]):
            failures.append(f"navigation:{target_id}: seed does not match the contract")
        coordinates = raw.get("cue_position_mm")
        if coordinates != [expected["cue_x_mm"], expected["cue_y_mm"]]:
            failures.append(f"navigation:{target_id}: cue position does not match the contract")
        criteria_ok = all(
            _criterion(verdict, str(prefix))
            for prefix in navigation_spec["required_criteria"]
        )
        exact = verdict.get("measured", {}).get("exact", {})
        final_distance = exact.get("final_cue_distance_mm")
        reaches = (
            isinstance(final_distance, (int, float))
            and float(final_distance)
            <= float(navigation_spec["max_final_target_distance_mm"])
        )
        for name in control_names:
            _control_passed(raw, str(name), failures, f"navigation:{target_id}")
        passed = bool(criteria_ok and reaches)
        passed_targets += int(passed)
        navigation_results[target_id] = {
            "criteria_passed": criteria_ok,
            "final_target_distance_mm": final_distance,
            "reached_target": reaches,
            "passed": passed,
        }
    if seen_targets != set(expected_targets):
        failures.append(
            "navigation: target coverage is incomplete; missing "
            + ", ".join(sorted(set(expected_targets) - seen_targets))
        )
    if passed_targets < int(navigation_spec["minimum_targets_passed"]):
        failures.append(
            f"navigation: {passed_targets} targets passed; "
            f"{navigation_spec['minimum_targets_passed']} required"
        )

    component_results: dict[str, Any] = {"navigation": navigation_results}
    for name in ("grooming", "feeding"):
        requirement = contract["components"][name]
        raw = components.get(name)
        if not isinstance(raw, Mapping):
            failures.append(f"{name}: component is missing")
            continue
        verdict, digest = _artifact(root, raw["verdict"])
        artifact_hashes[name] = digest
        commit = str(raw.get("code_commit", ""))
        if not commit:
            failures.append(f"{name}: code_commit is missing")
        else:
            commits.add(commit)
        experiment_matches = verdict.get("experiment_id") == requirement["experiment_id"]
        verdict_matches = str(verdict.get("verdict", "")).startswith(
            str(requirement["required_verdict_prefix"])
        )
        criteria_ok = all(
            _criterion(verdict, str(prefix)) for prefix in requirement["required_criteria"]
        )
        for control_name in control_names:
            _control_passed(raw, str(control_name), failures, name)
        passed = bool(experiment_matches and verdict_matches and criteria_ok)
        component_results[name] = {
            "experiment_matches": experiment_matches,
            "verdict": verdict.get("verdict"),
            "criteria_passed": criteria_ok,
            "passed": passed,
        }
        if not passed:
            failures.append(f"{name}: independent behaviour contract did not pass")

    if len(commits) != 1:
        failures.append(
            "component artifacts do not share exactly one recorded code commit: "
            + ", ".join(sorted(commits))
        )

    components_ready = not failures
    video_raw = bundle.get("video")
    video_result: dict[str, Any] = {"passed": False}
    if not require_video:
        video_result = {"passed": False, "status": "not evaluated"}
    elif not isinstance(video_raw, Mapping):
        failures.append("video: manifest is missing")
    else:
        manifest, manifest_digest = _artifact(root, video_raw["manifest"])
        video_path = (root / Path(str(video_raw["path"]))).resolve()
        if not video_path.is_relative_to(root) or not video_path.is_file():
            failures.append("video: MP4 is missing or outside the bundle")
        else:
            observed_video_hash = _sha256_file(video_path)
            if observed_video_hash != str(video_raw["sha256"]):
                failures.append("video: MP4 checksum does not match the bundle")
            artifact_hashes["video"] = observed_video_hash
        artifact_hashes["video-manifest"] = manifest_digest
        video_contract = contract["video"]
        duration = float(manifest.get("duration_s", 0.0))
        resolution = manifest.get("resolution")
        fps = float(manifest.get("fps", 0.0))
        chapters = set(str(value) for value in manifest.get("chapters", ()))
        labels = set(str(value) for value in manifest.get("labels", ()))
        video_ok = all(
            (
                float(video_contract["duration_s_min"]) <= duration
                <= float(video_contract["duration_s_max"]),
                resolution == video_contract["resolution"],
                fps >= float(video_contract["minimum_fps"]),
                manifest.get("layout") == video_contract["required_layout"],
                chapters.issuperset(video_contract["required_chapters"]),
                labels.issuperset(video_contract["required_labels"]),
            )
        )
        if not video_ok:
            failures.append("video: duration, format, comparison layout, chapters or labels fail")
        video_result = {
            "duration_s": duration,
            "resolution": resolution,
            "fps": fps,
            "layout": manifest.get("layout"),
            "passed": video_ok,
        }

    return {
        "schema_version": "2.0",
        "experiment_id": contract["experiment_id"],
        "experiment_sha256": sha256_json(dict(contract)),
        "bundle_sha256": _sha256_file(bundle_path),
        "ready_for_cinematic": components_ready,
        "accepted_as_engineering_showcase": require_video and not failures,
        "scientific_validation_tier_awarded": None,
        "components": component_results,
        "video": video_result,
        "code_commits": sorted(commits),
        "artifact_hashes": artifact_hashes,
        "failures": failures,
        "claim": contract["claim_if_every_gate_passes"] if not failures else None,
        "claim_boundary": contract["claim_boundary"],
    }


__all__ = ["evaluate_showcase_v2"]
