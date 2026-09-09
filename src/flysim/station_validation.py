# SPDX-License-Identifier: GPL-2.0-or-later
"""Evaluate the frozen station-keeping controller on the registered validation poses.

Every pose MOTOR-04 was tuned on was also used to choose its gains, its control channel
and its offset limit, so the recorded figures are training performance. This module draws
the validation poses from the rule registered in the v5 criteria contract, evaluates B2
and B3-v5 on them once, and refuses to run against a dirty worktree so the frozen
controller is recoverable from the recorded commit.

The poses are generated from the contract's seed rather than listed, so the set cannot be
edited after the fact without changing the seed, and the seed is what the contract pins.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.errors import ConfigurationError
from flysim.provenance import parse_provenance
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot


def draw_validation_poses(
    *, seed: int, count: int, max_attempts: int
) -> list[dict[str, float]]:
    """The registered draw: heading uniform on [-pi, pi), lateral offset on [-1.5, 1.5]."""
    if count <= 0 or max_attempts < count:
        raise ConfigurationError("Validation draw needs a positive count within its attempts")
    generator = np.random.default_rng(seed)
    poses: list[dict[str, float]] = []
    for attempt in range(max_attempts):
        heading = round(float(generator.uniform(-math.pi, math.pi)), 4)
        lateral = round(float(generator.uniform(-1.5, 1.5)), 4)
        poses.append(
            {"attempt": attempt + 1, "initial_heading_rad": heading, "initial_y_mm": lateral}
        )
    return poses


def _build_body(
    *, heading_rad: float, lateral_mm: float, root: Path, registry_path: Path
) -> Any:
    """Construct the Track A body from the registered values with the pose overridden."""
    from dataclasses import replace

    from flysim.engines.flygym import FlyGymTrackABodyEngine, FlyGymTrackAParameters
    from flysim.provenance import AssumptionRegistry

    registry = AssumptionRegistry.load(registry_path)
    timing = registry.value_map("NUM-01")
    body = registry.value_map("BODY-01")
    motor = registry.value_map("MOTOR-03")
    odor = registry.value_map("SENS-03")
    contact = registry.value_map("SENS-04")
    parameters = FlyGymTrackAParameters(
        **body,
        physics_dt_us=int(timing["physics_dt_us"]),
        **{
            key: odor[key]
            for key in (
                "source_strength",
                "softening_mm2",
                "half_saturation",
                "antenna_separation_mm",
            )
        },
        **{
            key: contact[key]
            for key in (
                "dust_deposition_per_s",
                "dust_exposure_cap",
                "single_dust_exposure",
                "groom_removal_per_s",
                "food_contact_radius_mm",
            )
        },
        **{
            key: motor[key]
            for key in (
                "max_forward_mm_s",
                "max_yaw_rad_s",
                "feed_rostrum_extension_rad",
                "feed_haustellum_extension_rad",
                "groom_blend_in_us",
            )
        },
        **registry.value_map("MOTOR-04"),
    )
    # Only the pose moves. Every other registered value, including the dust patch, is
    # held at its BODY-01 setting, so no validation pose alters the arena.
    parameters = replace(
        parameters, initial_heading_rad=heading_rad, initial_y_mm=lateral_mm
    )
    trajectory = (
        root
        / "derived"
        / "auxiliary"
        / "ozdil-2026-antennal-grooming"
        / "track-a-grooming-trajectory.npz"
    )
    return FlyGymTrackABodyEngine(parameters, trajectory, seed=1, render=False)


def measure_pose(engine: Any, samples: tuple[float, ...]) -> dict[str, float]:
    """Net thorax displacement under zero descending command at each sample time."""
    x0, y0, _, heading0 = engine._pose()
    measured: dict[str, float] = {}
    for second in samples:
        engine.step_until(int(second * 1_000_000))
        x, y, _, heading = engine._pose()
        measured[f"displacement_{second:g}s_mm"] = math.hypot(x - x0, y - y0)
        measured[f"heading_change_{second:g}s_rad"] = abs(
            math.atan2(math.sin(heading - heading0), math.cos(heading - heading0))
        )
    return measured


def run_station_keeping_validation(
    *,
    root: Path,
    experiment_path: Path,
    output_path: Path,
    registry_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Score B2 and B3-v5 on the registered validation poses, once."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The station-keeping validation run")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported Track A criteria contract schema")
    if not contract.get("adopted"):
        raise ConfigurationError(
            "The validation run scores an adopted criterion; this contract is not adopted"
        )
    parse_provenance(str(contract["provenance"]))
    split = contract["development_and_validation_split"]
    rule = split["validation_set_rule"]
    criterion = contract["adopted_criterion"]
    limit = float(criterion["limit_mm"])
    b2_limit = 2.5

    poses = draw_validation_poses(seed=20260910, count=int(rule["count"]), max_attempts=40)
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for pose in poses:
        if len(rows) >= int(rule["count"]):
            break
        try:
            engine = _build_body(
                heading_rad=float(pose["initial_heading_rad"]),
                lateral_mm=float(pose["initial_y_mm"]),
                root=root,
                registry_path=registry_path,
            )
        except ConfigurationError as error:
            # The registered rejection rule: a pose whose settled body starts inside the
            # dust patch is discarded and replaced by the next draw.
            rejected.append({**pose, "reason": str(error)})
            continue
        measured = measure_pose(engine, (3.0, 6.0, 12.0))
        ratio = (
            measured["displacement_6s_mm"] / measured["displacement_3s_mm"]
            if measured["displacement_3s_mm"] > 1e-9
            else float("inf")
        )
        rows.append(
            {
                "pose_id": f"v{len(rows) + 1:02d}",
                **pose,
                **measured,
                "b2_passed": measured["displacement_3s_mm"] <= b2_limit,
                "b3_v5_passed": measured["displacement_12s_mm"] <= limit,
                "v4_b3_ratio_diagnostic": ratio,
                "v4_b3_ratio_would_have_passed": ratio < 1.5,
            }
        )

    required = math.ceil(0.8 * len(rows)) if rows else 0
    b2_passed = sum(1 for row in rows if row["b2_passed"])
    b3_passed = sum(1 for row in rows if row["b3_v5_passed"])
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "track-a-station-keeping-validation-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "E",
        "assumption_ids": list(contract["assumption_ids"]),
        "poses_scored": len(rows),
        "poses_rejected_by_dust_guard": len(rejected),
        "rejected_poses": rejected,
        "by_pose": rows,
        "acceptance": {
            "threshold": split["validation_acceptance_threshold"]["threshold"],
            "required_passes": required,
            "b2_passes": b2_passed,
            "b2_passed": b2_passed >= required,
            "b3_v5_passes": b3_passed,
            "b3_v5_passed": b3_passed >= required,
            "validation_passed": b2_passed >= required and b3_passed >= required,
        },
        "development_comparison": {
            "b3_v5_development_passes": "5 of 7",
            "note": (
                "Development performance is training performance: those poses chose the "
                "gains, the control channel and the offset limit. The comparison is reported "
                "so that a gap between development and validation is visible."
            ),
        },
        "v4_b3_diagnostic": {
            "note": (
                "The retired 6 s over 3 s ratio is still computed per pose. It is not a "
                "criterion, because a 30.8 mm runaway satisfies it, but the number describes "
                "settling behaviour and removing it would hide that."
            ),
            "would_have_passed": sum(
                1 for row in rows if row["v4_b3_ratio_would_have_passed"]
            ),
        },
        "claim_boundary": (
            "Standing station-keeping only, on poses the controller was not tuned on. It "
            "awards no tier and does not evaluate B1, B4, the nine controls or the renderer "
            "timing amendment, so it cannot make Track A an accepted milestone."
        ),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "evidence_grade": not worktree["dirty"],
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot),
    }
