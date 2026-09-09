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


_RECORDED_PATH_LIMIT = 20


def _git(root: Path, *arguments: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
    ).stdout


def _nul_records(blob: str) -> list[str]:
    return [record for record in blob.split("\0") if record]


def _index_blobs(root: Path) -> dict[str, str]:
    """Path to index blob hash for every tracked file."""
    entries: dict[str, str] = {}
    for record in _nul_records(_git(root, "ls-files", "-s", "-z")):
        metadata, path = record.split("\t", 1)
        _mode, blob, _stage = metadata.split()
        entries[path] = blob
    return entries


def _index_flags(root: Path) -> tuple[tuple[str, str], ...]:
    """Paths carrying an index bit that makes git stop looking at the file.

    ``git ls-files -v`` lower-cases the tag of an assume-unchanged path and tags a
    skip-worktree path ``S``. Either bit tells git to trust the index over the disk,
    which is precisely the state in which a clean report means nothing.
    """
    flagged: list[tuple[str, str]] = []
    for record in _nul_records(_git(root, "ls-files", "-v", "-z")):
        tag, path = record[0], record[2:]
        if tag.islower():
            flagged.append((path, "assume-unchanged"))
        elif tag == "S":
            flagged.append((path, "skip-worktree"))
    return tuple(flagged)


@dataclass(frozen=True, slots=True)
class WorktreeAudit:
    """What the working tree actually contains, established without the stat cache.

    ``git status`` and ``git diff-files`` decide whether to open a file by comparing its
    recorded size and timestamps. On 2026-09-09 that comparison was wrong here: an edit
    that changed ``foundation-v0.6`` to ``foundation-v0.7``, preserving byte length, was
    invisible to ``git status``, ``git diff``, ``git diff-files`` and ``git add``, while
    ``git hash-object`` disagreed with the index. An evidence-grade run gated on that
    answer would have recorded a commit that did not describe the code it ran.

    So this audit re-hashes every tracked file through git's own clean filters and
    compares the result with the index, compares the index with HEAD, and refuses to
    interpret a repository that carries assume-unchanged or skip-worktree bits at all.
    """

    commit: str | None
    detached_head: bool
    linked_worktree: bool
    status_reported_clean: bool
    tracked_files: int
    flagged_paths: tuple[tuple[str, str], ...]
    staged_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]
    unverifiable_paths: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return (
            self.commit is not None
            and not self.flagged_paths
            and not self.staged_paths
            and not self.modified_paths
            and not self.missing_paths
            and not self.untracked_paths
            and not self.unverifiable_paths
        )

    @property
    def status_disagrees(self) -> bool:
        """The failure this audit exists for: a clean report over an unclean tree."""
        return self.status_reported_clean and not self.clean

    def findings(self) -> list[str]:
        report: list[str] = []
        for label, paths in (
            ("index bit set", tuple(f"{path} ({flag})" for path, flag in self.flagged_paths)),
            ("staged but uncommitted", self.staged_paths),
            ("bytes differ from the index", self.modified_paths),
            ("tracked but absent", self.missing_paths),
            ("untracked", self.untracked_paths),
            ("could not be verified", self.unverifiable_paths),
        ):
            if paths:
                shown = ", ".join(paths[:_RECORDED_PATH_LIMIT])
                hidden = len(paths) - _RECORDED_PATH_LIMIT
                more = f" and {hidden} more" if hidden > 0 else ""
                report.append(f"{label}: {shown}{more}")
        return report

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": (
                "tracked files re-hashed through git's clean filters and compared with the "
                "index; index compared with HEAD; index bits audited"
            ),
            "detached_head": self.detached_head,
            "linked_worktree": self.linked_worktree,
            "ran_from_detached_worktree": self.detached_head and self.linked_worktree,
            "status_reported_clean": self.status_reported_clean,
            "byte_audit_agrees_with_status": not self.status_disagrees,
            "tracked_files": self.tracked_files,
            "counts": {
                "flagged": len(self.flagged_paths),
                "staged": len(self.staged_paths),
                "modified": len(self.modified_paths),
                "missing": len(self.missing_paths),
                "untracked": len(self.untracked_paths),
                "unverifiable": len(self.unverifiable_paths),
            },
            "findings": self.findings(),
        }


def audit_worktree(root: Path | None = None) -> WorktreeAudit:
    """Establish the working-tree state from file bytes rather than from git's cache."""
    root = root or project_root()
    unreadable = WorktreeAudit(
        commit=None,
        detached_head=False,
        linked_worktree=False,
        status_reported_clean=False,
        tracked_files=0,
        flagged_paths=(),
        staged_paths=(),
        modified_paths=(),
        missing_paths=(),
        untracked_paths=(),
        unverifiable_paths=(),
    )
    try:
        commit = _git(root, "rev-parse", "HEAD").strip()
        status_clean = not _git(root, "status", "--porcelain").strip()
        index = _index_blobs(root)
        flagged = _index_flags(root)
        staged = tuple(
            sorted(_nul_records(_git(root, "diff-index", "--cached", "--name-only", "-z", "HEAD")))
        )
        untracked = tuple(
            sorted(_nul_records(_git(root, "ls-files", "--others", "--exclude-standard", "-z")))
        )
        git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").strip()).resolve()
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        common_dir = Path(common.strip()).resolve()
        detached = (
            subprocess.run(
                ["git", "symbolic-ref", "-q", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
            ).returncode
            != 0
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return unreadable

    missing: list[str] = []
    verifiable: list[str] = []
    unverifiable: list[str] = []
    for path in sorted(index):
        if "\n" in path:
            # --stdin-paths is newline-delimited, so such a path cannot be checked this
            # way. Refusing is the only safe answer; silently skipping it would put an
            # unexamined file inside an evidence-grade claim.
            unverifiable.append(path)
        elif (root / path).is_file():
            verifiable.append(path)
        else:
            missing.append(path)

    modified: list[str] = []
    if verifiable:
        try:
            recomputed = _git(
                root, "hash-object", "--stdin-paths", stdin="\n".join(verifiable) + "\n"
            ).split()
        except (OSError, subprocess.CalledProcessError):
            unverifiable.extend(verifiable)
            recomputed = []
        if recomputed and len(recomputed) == len(verifiable):
            modified = [
                path
                for path, digest in zip(verifiable, recomputed, strict=True)
                if digest != index[path]
            ]
        elif recomputed:
            unverifiable.extend(verifiable)

    return WorktreeAudit(
        commit=commit,
        detached_head=detached,
        linked_worktree=git_dir != common_dir,
        status_reported_clean=status_clean,
        tracked_files=len(index),
        flagged_paths=flagged,
        staged_paths=staged,
        modified_paths=tuple(modified),
        missing_paths=tuple(missing),
        untracked_paths=untracked,
        unverifiable_paths=tuple(sorted(set(unverifiable))),
    )


def git_metadata() -> dict[str, Any]:
    """Cheap state for a run that is not claiming evidence grade.

    The byte-level audit costs a few seconds on this repository's filesystem, which is
    the right price for an evidence gate and the wrong one for every development run and
    test. So this reports what ``git status`` says, plus the index-bit audit, which is one
    command and catches the case where a clean report is meaningless. What it never does
    is let the result be mistaken for the strong check: the recorded method says which
    check ran, and ``byte_audit_performed`` is false here.
    """
    root = project_root()
    try:
        commit: str | None = _git(root, "rev-parse", "HEAD").strip()
        dirty = bool(_git(root, "status", "--porcelain").strip())
        flagged = _index_flags(root)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {
            "commit": None,
            "dirty": True,
            "verification": {
                "method": "unreadable repository",
                "byte_audit_performed": False,
            },
        }
    return {
        "commit": commit,
        "dirty": dirty or bool(flagged),
        "verification": {
            "method": "git status plus an index-bit audit; file bytes were NOT re-hashed",
            "byte_audit_performed": False,
            "status_reported_clean": not dirty,
            "index_bits_set": [f"{path} ({flag})" for path, flag in flagged],
            "why_this_is_weaker": (
                "git status decides whether to open a file from its recorded size and "
                "timestamps, and that comparison was observed to miss a real same-length "
                "edit here on 2026-09-09. Only require_clean_worktree re-hashes the bytes, "
                "so only an evidence-grade artifact carries that guarantee."
            ),
        },
    }


def require_clean_worktree(purpose: str) -> dict[str, Any]:
    """Refuse to produce evidence whose code state cannot be recovered from git.

    Every Track A acceptance and control artifact in the first release was written from
    an uncommitted tree, so the exact implementation behind the recorded commit could
    not be reconstructed. Evidence-grade runs now fail closed instead, and since
    2026-09-09 they fail closed on the file bytes rather than on ``git status``, because
    that report was observed to miss a real modification.
    """
    audit = audit_worktree()
    if audit.commit is None:
        raise ValidationError(
            f"{purpose} requires a resolvable git commit; no repository state was readable"
        )
    if not audit.clean:
        detail = "; ".join(audit.findings()) or "the repository state could not be verified"
        warning = (
            " NOTE: git status reported this tree CLEAN and the byte-level audit disagrees, "
            "which is the stale-stat-cache failure this check exists for. Run "
            "'git update-index --force-remove <path>' then 'git add <path>' on the paths "
            "below before trusting any git report about them."
            if audit.status_disagrees
            else ""
        )
        raise ValidationError(
            f"{purpose} requires a clean git worktree so that the recorded commit "
            f"{audit.commit[:8]} reproduces the executed code. Found {detail}. Commit or "
            "stash the changes, or pass --allow-dirty-tree to produce an explicitly "
            f"non-evidence-grade run.{warning}"
        )
    return {
        "commit": audit.commit,
        "dirty": False,
        "verification": {**audit.as_dict(), "byte_audit_performed": True},
    }


def create_evidence_worktree(
    *, path: Path, commit: str = "HEAD", root: Path | None = None
) -> dict[str, Any]:
    """Add a detached worktree at ``commit`` so an evidence run cannot see later edits.

    Running from the checkout one is editing is the reason a stale cache mattered at all:
    the tree can change under a long run. A detached worktree at a named commit is
    immutable in practice, and the audit records that the run came from one.
    """
    root = root or project_root()
    resolved = path.resolve()
    if resolved.exists():
        raise ValidationError(f"Refusing to reuse an existing path for a worktree: {resolved}")
    revision = _git(root, "rev-parse", commit).strip()
    _git(root, "worktree", "add", "--detach", str(resolved), revision)
    return {
        "worktree": str(resolved),
        "commit": revision,
        "detached": True,
        "how_to_use": (
            "Run the evidence command with this directory as the working directory and its "
            "src on PYTHONPATH, so the executed code is the recorded commit and nothing else."
        ),
        "remove_with": f"git worktree remove --force {resolved}",
    }


def remove_evidence_worktree(*, path: Path, root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    resolved = path.resolve()
    _git(root, "worktree", "remove", "--force", str(resolved))
    return {"removed": str(resolved)}


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
