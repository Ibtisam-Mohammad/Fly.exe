# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproducible experiment records and artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flysim import __version__
from flysim.config import ScenarioConfig, project_root
from flysim.errors import ValidationError
from flysim.provenance import AssumptionRegistry
from flysim.scheduler import SchedulerResult


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata() -> dict[str, Any]:
    root = project_root()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        commit = None
        dirty = True
    return {"commit": commit, "dirty": dirty}


def require_clean_worktree(purpose: str) -> dict[str, Any]:
    """Refuse to produce evidence whose code state cannot be recovered from git.

    Every Track A acceptance and control artifact in the first release was written from
    an uncommitted tree, so the exact implementation behind the recorded commit could
    not be reconstructed. Evidence-grade runs now fail closed instead.
    """
    state = git_metadata()
    if state["commit"] is None:
        raise ValidationError(
            f"{purpose} requires a resolvable git commit; no repository state was readable"
        )
    if state["dirty"]:
        raise ValidationError(
            f"{purpose} requires a clean git worktree so that the recorded commit "
            f"{state['commit'][:8]} reproduces the executed code. Commit or stash the "
            "changes, or pass --allow-dirty-tree to produce an explicitly "
            "non-evidence-grade run."
        )
    return state


@dataclass(frozen=True, slots=True)
class WrittenRun:
    run_id: str
    directory: Path
    manifest_path: Path
    trace_path: Path


def write_run(
    result: SchedulerResult,
    scenario: ScenarioConfig,
    registry: AssumptionRegistry,
    seed: int,
    output_root: Path,
    ablated_inputs: tuple[str, ...],
    ablated_outputs: tuple[str, ...],
    connectome_metadata: dict[str, Any] | None = None,
    run_metadata: dict[str, Any] | None = None,
    evidence_grade: bool = False,
) -> WrittenRun:
    """Write a run record. ``evidence_grade`` refuses to write from a dirty worktree.

    The command-line surface, which is what produces released evidence, passes
    ``evidence_grade=True`` unless the operator explicitly opts out. Library callers and
    tests default to ``False`` so that development runs stay possible, and the manifest
    always records which contract applied.
    """
    git_state = (
        require_clean_worktree("An evidence-grade run")
        if evidence_grade
        else {**git_metadata(), "clean_worktree_check_waived": True}
    )
    timestamp = datetime.now(UTC)
    run_id = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{scenario.scenario_id}_seed-{seed}"
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    trace_path = directory / "trace.jsonl"
    with trace_path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in result.trace:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": timestamp.isoformat(),
        "flysim_version": __version__,
        "scenario": {
            "id": scenario.scenario_id,
            "track": scenario.track,
            "sha256": scenario.sha256,
            "claim_boundary": scenario.claim_boundary,
        },
        "assumption_set": {
            "id": registry.assumption_set_id,
            "sha256": registry.sha256,
            "required_ids": list(scenario.required_assumptions),
        },
        "random_seed": seed,
        "initial_physiological_state": registry.records["STATE-01"].value,
        "backends": {"neural": scenario.neural_backend, "body": scenario.body_backend},
        "connectome": connectome_metadata or {
            "canonical_release": registry.records["DATA-01"].value,
            "graph_used": False,
            "resolved_body_ids": False,
        },
        "scaffolds": list(scenario.scaffolds),
        "omissions": list(scenario.omissions),
        "interventions": {
            "ablated_input_ids": list(ablated_inputs),
            "ablated_output_ids": list(ablated_outputs),
        },
        "result": {
            "completed": result.completed,
            "final_t_us": result.final_t_us,
            "final_state": result.final_state.value,
            "events": list(result.events),
            "highest_validation_tier": None,
            "scientific_validation_passed": False,
        },
        "git": {**git_state, "evidence_grade": evidence_grade},
        "timing": dict(result.timing),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "artifacts": {"trace": trace_path.name, "trace_sha256": _sha256_file(trace_path)},
        "credentials": {
            "neuprint_used": False,
            "secret_values_recorded": False,
        },
        "run_metadata": run_metadata or {},
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return WrittenRun(
        run_id=run_id,
        directory=directory.resolve(),
        manifest_path=manifest_path.resolve(),
        trace_path=trace_path.resolve(),
    )


def attach_run_artifact(written: WrittenRun, artifact_id: str, path: Path) -> dict[str, str]:
    """Finalize a generated artifact into an existing run manifest.

    Some backends, notably FlyGym's renderer, can only emit their artifact after the
    simulation trace and run directory exist. This function records the final relative
    path and checksum before the run is presented to the caller.
    """
    if not artifact_id or not artifact_id.replace("_", "").isalnum():
        raise ValueError("artifact_id must contain only letters, numbers, and underscores")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(written.directory)
    except ValueError as exc:
        raise ValueError("run artifacts must be inside the run directory") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    manifest = json.loads(written.manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.setdefault("artifacts", {})
    artifacts[artifact_id] = relative.as_posix()
    artifacts[f"{artifact_id}_sha256"] = _sha256_file(resolved)
    written.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "path": str(resolved),
        "sha256": str(artifacts[f"{artifact_id}_sha256"]),
    }


def read_trace(run_directory: Path) -> list[dict[str, Any]]:
    path = run_directory / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
