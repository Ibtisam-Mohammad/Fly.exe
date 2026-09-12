# SPDX-License-Identifier: GPL-2.0-or-later
"""Run, evaluate, and package the explicitly engineered Eon-class showcase.

This module does not create a new biological model. It puts a release boundary around the
existing full-graph Track A scenario: three exact runs, four causal ablations, two diagnostic
graph controls, and an offline render of the declared hero run. The result may be accepted as
an engineering showcase and can never award a scientific validation tier.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from flysim.config import load_json, project_root, sha256_json
from flysim.errors import FlySimError, ReadinessError, ValidationError
from flysim.render import render_run
from flysim.runs import require_clean_worktree


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _event_targets(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(event["to_state"]) for event in manifest["result"]["events"])


def _contains_in_order(observed: Sequence[str], required: Sequence[str]) -> bool:
    cursor = 0
    for value in observed:
        if cursor < len(required) and value == required[cursor]:
            cursor += 1
    return cursor == len(required)


def _load_run(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    validation_path = directory / "validation-report.json"
    if not manifest_path.is_file() or not validation_path.is_file():
        raise ValidationError(f"Showcase run is incomplete: {directory}")
    manifest = load_json(manifest_path)
    validation = load_json(validation_path)
    return {
        "directory": str(directory.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha256_file(manifest_path),
        "validation_path": str(validation_path.resolve()),
        "validation_sha256": _sha256_file(validation_path),
        "manifest": manifest,
        "validation": validation,
        "event_targets": _event_targets(manifest),
    }


def evaluate_showcase(
    *,
    contract: Mapping[str, Any],
    exact_directories: Mapping[int, Path],
    control_directories: Mapping[str, Path],
    diagnostic_directories: Mapping[str, Path],
) -> dict[str, Any]:
    """Apply the frozen engineering contract without running a simulation."""
    exact = {seed: _load_run(path) for seed, path in sorted(exact_directories.items())}
    controls = {name: _load_run(path) for name, path in sorted(control_directories.items())}
    diagnostics = {
        name: _load_run(path) for name, path in sorted(diagnostic_directories.items())
    }
    all_runs = [*exact.values(), *controls.values(), *diagnostics.values()]
    failures: list[str] = []

    expected_scenario = str(contract["scenario_id"])
    expected_graph = contract["required_graph"]
    commits: set[str] = set()
    for run in all_runs:
        manifest = run["manifest"]
        if manifest["scenario"]["id"] != expected_scenario:
            failures.append(
                f"{run['directory']}: scenario {manifest['scenario']['id']} is not "
                f"{expected_scenario}"
            )
        if run["validation"].get("valid") is not True:
            failures.append(f"{run['directory']}: run-artifact validation did not pass")
        git = manifest.get("git", {})
        if git.get("dirty") is not False or git.get("evidence_grade") is not True:
            failures.append(f"{run['directory']}: run was not produced from a clean tree")
        if git.get("commit"):
            commits.add(str(git["commit"]))
        graph = manifest.get("connectome", {})
        for key, expected in expected_graph.items():
            if graph.get(key) != expected:
                failures.append(
                    f"{run['directory']}: connectome {key}={graph.get(key)!r}, "
                    f"expected {expected!r}"
                )
        if manifest.get("result", {}).get("highest_validation_tier") is not None:
            failures.append(f"{run['directory']}: an engineering showcase claimed a tier")
    if len(commits) != 1:
        failures.append(
            "showcase runs do not share exactly one clean code commit: "
            + ", ".join(sorted(commits))
        )

    required_sequence = tuple(str(value) for value in contract["required_sequence"])
    exact_results: dict[str, Any] = {}
    for seed in (int(value) for value in contract["seeds"]):
        exact_run = exact.get(seed)
        if exact_run is None:
            failures.append(f"exact seed {seed} is missing")
            continue
        sequence_passed = _contains_in_order(exact_run["event_targets"], required_sequence)
        completed = exact_run["manifest"]["result"].get("completed") is True
        exact_results[str(seed)] = {
            "completed": completed,
            "required_sequence_observed": sequence_passed,
            "event_targets": list(exact_run["event_targets"]),
            "run": {
                key: value
                for key, value in exact_run.items()
                if key not in {"manifest", "validation"}
            },
        }
    completed_seeds = sum(
        bool(value["completed"] and value["required_sequence_observed"])
        for value in exact_results.values()
    )
    if completed_seeds < int(contract["minimum_completed_seeds"]):
        failures.append(
            f"only {completed_seeds} exact seeds completed the required sequence; "
            f"{contract['minimum_completed_seeds']} required"
        )
    hero_seed = int(contract["hero_seed"])
    hero = exact_results.get(str(hero_seed))
    if not hero or not hero["completed"] or not hero["required_sequence_observed"]:
        failures.append(f"hero seed {hero_seed} did not complete the required sequence")

    control_results: dict[str, Any] = {}
    for name, specification in contract["required_controls"].items():
        control_run = controls.get(name)
        if control_run is None:
            failures.append(f"required control {name} is missing")
            continue
        blocked = str(specification["must_block_state"])
        passed = blocked not in control_run["event_targets"]
        control_results[name] = {
            "passed": passed,
            "blocked_state": blocked,
            "event_targets": list(control_run["event_targets"]),
            "meaning": specification["meaning"],
            "run": {
                key: value
                for key, value in control_run.items()
                if key not in {"manifest", "validation"}
            },
        }
        if not passed:
            failures.append(f"control {name} did not block {blocked}")

    diagnostic_results = {
        name: {
            "gates_acceptance": False,
            "event_targets": list(run["event_targets"]),
            "meaning": contract["diagnostic_controls"][name]["meaning"],
            "run": {
                key: value
                for key, value in run.items()
                if key not in {"manifest", "validation"}
            },
        }
        for name, run in diagnostics.items()
    }
    return {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "experiment_sha256": sha256_json(dict(contract)),
        "accepted_as_engineering_showcase": not failures,
        "scientific_validation_tier_awarded": None,
        "claim": contract["claim"],
        "code_commits": sorted(commits),
        "exact": exact_results,
        "completed_exact_seeds": completed_seeds,
        "required_controls": control_results,
        "diagnostic_controls": diagnostic_results,
        "failures": failures,
        "limitations": list(contract["what_this_is_not"]),
    }


def _latest_reusable_run(
    directory: Path,
    *,
    commit: str,
    seed: int,
    scenario_id: str,
    duration_us: int,
    food_position: Sequence[float],
    ablated_inputs: Sequence[str],
    ablated_outputs: Sequence[str],
    control_variant: str,
) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    for manifest_path in directory.glob("*/manifest.json"):
        try:
            manifest = load_json(manifest_path)
        except (OSError, FlySimError):
            continue
        if manifest.get("random_seed") != seed:
            continue
        if manifest.get("scenario", {}).get("id") != scenario_id:
            continue
        git = manifest.get("git", {})
        if git.get("dirty") or git.get("commit") != commit:
            continue
        interventions = manifest.get("interventions", {})
        if sorted(interventions.get("ablated_input_ids", ())) != sorted(ablated_inputs):
            continue
        if sorted(interventions.get("ablated_output_ids", ())) != sorted(ablated_outputs):
            continue
        connectome = manifest.get("connectome", {})
        if connectome.get("control_variant") != control_variant:
            continue
        metadata = manifest.get("run_metadata", {})
        if metadata.get("requested_duration_us") != duration_us:
            continue
        if metadata.get("food_position_mm") != list(food_position):
            continue
        validation_path = manifest_path.parent / "validation-report.json"
        if not validation_path.is_file() or not load_json(validation_path).get("valid"):
            continue
        candidates.append((str(manifest.get("created_at", "")), manifest_path.parent))
    if not candidates:
        return None
    latest = max(candidates, key=lambda value: value[0])
    return latest[1]


def _run_condition(
    *,
    root: Path,
    graph: Path,
    output_root: Path,
    commit: str,
    scenario_id: str,
    seed: int,
    duration_us: int,
    food_position: Sequence[float],
    ablated_inputs: Sequence[str] = (),
    ablated_outputs: Sequence[str] = (),
    control_variant: str = "exact",
) -> Path:
    reused = _latest_reusable_run(
        output_root,
        commit=commit,
        seed=seed,
        scenario_id=scenario_id,
        duration_us=duration_us,
        food_position=food_position,
        ablated_inputs=ablated_inputs,
        ablated_outputs=ablated_outputs,
        control_variant=control_variant,
    )
    if reused is not None:
        return reused
    command = [
        sys.executable,
        "-u",
        "-m",
        "flysim.cli",
        "run",
        "eon-malecns",
        "--root",
        str(root),
        "--graph",
        str(graph),
        "--output-root",
        str(output_root),
        "--duration-us",
        str(duration_us),
        "--seed",
        str(seed),
        "--food-x-mm",
        str(food_position[0]),
        "--food-y-mm",
        str(food_position[1]),
        "--headless",
    ]
    for identifier in ablated_inputs:
        command.extend(("--ablate-input", identifier))
    for identifier in ablated_outputs:
        command.extend(("--ablate-output", identifier))
    if control_variant != "exact":
        command.extend(("--control", control_variant))
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    written = _latest_reusable_run(
        output_root,
        commit=commit,
        seed=seed,
        scenario_id=scenario_id,
        duration_us=duration_us,
        food_position=food_position,
        ablated_inputs=ablated_inputs,
        ablated_outputs=ablated_outputs,
        control_variant=control_variant,
    )
    if written is None:
        raise ReadinessError(
            f"Showcase condition produced no reusable run (exit {completed.returncode}): "
            f"{completed.stderr[-2000:]}"
        )
    return written


def build_showcase(
    *,
    root: Path,
    graph: Path | None = None,
    output_root: Path | None = None,
    contract_path: Path | None = None,
    render: bool = True,
    include_diagnostics: bool = True,
) -> dict[str, Any]:
    """Execute the frozen matrix, evaluate it, render the hero, and write the package."""
    repository = project_root()
    contract_file = contract_path or (
        repository / "configs" / "experiments" / "eon-showcase-v1.json"
    )
    contract = load_json(contract_file)
    clean = require_clean_worktree("The Eon showcase release")
    commit = str(clean["commit"])
    graph_path = graph or root / "derived" / "male-cns-v1.0" / "graph"
    if not graph_path.exists():
        raise ReadinessError(f"The imported MaleCNS graph is missing: {graph_path}")
    destination = output_root or root / "runs" / str(contract["experiment_id"])
    duration_us = int(contract["duration_us"])
    food_position = tuple(float(value) for value in contract["food_position_mm"])
    scenario_id = str(contract["scenario_id"])

    exact: dict[int, Path] = {}
    for seed in (int(value) for value in contract["seeds"]):
        exact[seed] = _run_condition(
            root=root,
            graph=graph_path,
            output_root=destination / f"exact-seed-{seed}",
            commit=commit,
            scenario_id=scenario_id,
            seed=seed,
            duration_us=duration_us,
            food_position=food_position,
        )

    hero_seed = int(contract["hero_seed"])
    controls: dict[str, Path] = {}
    for name, specification in contract["required_controls"].items():
        arguments = tuple(str(value) for value in specification["arguments"])
        if len(arguments) != 2 or arguments[0] not in {
            "--ablate-input",
            "--ablate-output",
        }:
            raise ValidationError(f"Unsupported causal-control arguments for {name}")
        controls[name] = _run_condition(
            root=root,
            graph=graph_path,
            output_root=destination / "controls" / name,
            commit=commit,
            scenario_id=scenario_id,
            seed=hero_seed,
            duration_us=duration_us,
            food_position=food_position,
            ablated_inputs=(arguments[1],) if arguments[0] == "--ablate-input" else (),
            ablated_outputs=(arguments[1],) if arguments[0] == "--ablate-output" else (),
        )

    diagnostics: dict[str, Path] = {}
    if include_diagnostics:
        for name, specification in contract["diagnostic_controls"].items():
            arguments = tuple(str(value) for value in specification["arguments"])
            if len(arguments) != 2 or arguments[0] != "--control":
                raise ValidationError(f"Unsupported diagnostic arguments for {name}")
            diagnostics[name] = _run_condition(
                root=root,
                graph=graph_path,
                output_root=destination / "diagnostics" / name,
                commit=commit,
                scenario_id=scenario_id,
                seed=hero_seed,
                duration_us=duration_us,
                food_position=food_position,
                control_variant=arguments[1],
            )

    acceptance = evaluate_showcase(
        contract=contract,
        exact_directories=exact,
        control_directories=controls,
        diagnostic_directories=diagnostics,
    )
    acceptance_path = destination / "acceptance.json"
    _write_json_atomic(acceptance_path, acceptance)

    hero_directory = exact[hero_seed]
    video_path: Path | None = None
    render_manifest_path: Path | None = None
    if render:
        video_path = render_run(hero_directory)
        render_manifest_path = hero_directory / "render-manifest.json"

    artifacts: dict[str, dict[str, str]] = {
        "contract": {
            "path": str(contract_file.resolve()),
            "sha256": _sha256_file(contract_file),
        },
        "acceptance": {
            "path": str(acceptance_path.resolve()),
            "sha256": _sha256_file(acceptance_path),
        },
    }
    if video_path is not None and render_manifest_path is not None:
        artifacts["hero_video"] = {
            "path": str(video_path),
            "sha256": _sha256_file(video_path),
        }
        artifacts["hero_render_manifest"] = {
            "path": str(render_manifest_path.resolve()),
            "sha256": _sha256_file(render_manifest_path),
        }
    package = {
        "schema_version": "1.0",
        "package_id": contract["experiment_id"],
        "accepted_as_engineering_showcase": acceptance["accepted_as_engineering_showcase"],
        "scientific_validation_tier_awarded": None,
        "code_commit": commit,
        "claim": contract["claim"],
        "hero_seed": hero_seed,
        "hero_run": str(hero_directory.resolve()),
        "exact_runs": {str(seed): str(path.resolve()) for seed, path in exact.items()},
        "control_runs": {name: str(path.resolve()) for name, path in controls.items()},
        "diagnostic_runs": {name: str(path.resolve()) for name, path in diagnostics.items()},
        "artifacts": artifacts,
        "declared_bridges": list(contract["declared_bridges"]),
        "required_video_labels": list(contract["required_video_labels"]),
        "limitations": list(contract["what_this_is_not"]),
    }
    package_path = destination / "showcase-manifest.json"
    _write_json_atomic(package_path, package)
    return {**package, "showcase_manifest": str(package_path.resolve())}


__all__ = ["build_showcase", "evaluate_showcase"]
