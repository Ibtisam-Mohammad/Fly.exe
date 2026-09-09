# SPDX-License-Identifier: GPL-2.0-or-later
"""The evidence gate, and the two ways git will tell you a dirty tree is clean.

On 2026-09-09 an edit that changed ``foundation-v0.6`` to ``foundation-v0.7`` in two
config files — the same byte length — was invisible to ``git status``, ``git diff``,
``git diff-files`` and ``git add``, while ``git hash-object`` disagreed with the index.
An evidence-grade artifact gated on that answer would have recorded a commit that did
not describe the code that produced it, which is the exact defect the gate was added to
prevent.

These tests hold the repaired gate to the standard that failure implies: it must catch a
same-length edit, and it must refuse outright when an index bit has told git to stop
looking at a file, because in that state a clean report carries no information.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

import flysim.runs as runs
from flysim.errors import ValidationError
from flysim.runs import audit_worktree, require_clean_worktree

CONFIG = "configs/thing.json"
ORIGINAL = '{\n  "assumption_set": "foundation-v0.6"\n}\n'
SAME_LENGTH = '{\n  "assumption_set": "foundation-v0.7"\n}\n'


def _run(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _run(tmp_path, "init", "--quiet")
    (tmp_path / "configs").mkdir()
    (tmp_path / CONFIG).write_text(ORIGINAL, encoding="utf-8")
    _run(tmp_path, "add", CONFIG)
    _run(
        tmp_path,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    return tmp_path


@pytest.fixture
def rooted(repository: Path) -> Iterator[Path]:
    """Point the gate at the fixture repository for the duration of a test."""
    original = runs.project_root
    runs.project_root = lambda: repository  # type: ignore[assignment]
    try:
        yield repository
    finally:
        runs.project_root = original  # type: ignore[assignment]


def _edit_preserving_length_and_timestamps(repository: Path) -> None:
    """Make the edit that git missed, and put the timestamps back afterwards."""
    path = repository / CONFIG
    before = path.stat()
    assert len(SAME_LENGTH) == len(ORIGINAL), "the fixture must preserve byte length"
    path.write_text(SAME_LENGTH, encoding="utf-8")
    os.utime(path, (before.st_atime, before.st_mtime))


def test_a_clean_tree_is_clean(rooted: Path) -> None:
    audit = audit_worktree(rooted)
    assert audit.clean
    assert audit.commit is not None
    assert audit.tracked_files == 1
    assert audit.findings() == []
    assert not audit.status_disagrees


def test_a_same_length_edit_is_caught_by_re_hashing_the_bytes(rooted: Path) -> None:
    _edit_preserving_length_and_timestamps(rooted)
    audit = audit_worktree(rooted)
    assert audit.modified_paths == (CONFIG,)
    assert not audit.clean
    # Whether git status happens to notice depends on the version, the filesystem and
    # git's racily-clean logic, so the test does not require it to be fooled. What it
    # does require is that when status is fooled, the audit says so out loud.
    if audit.status_reported_clean:
        assert audit.status_disagrees
    with pytest.raises(ValidationError, match="clean git worktree"):
        require_clean_worktree("An evidence-grade run")


def test_an_assume_unchanged_bit_is_refused_even_though_status_is_clean(rooted: Path) -> None:
    # This is the deterministic form of the same trap: the bit tells git to trust the
    # index, so status reports clean over a file whose contents have changed.
    _run(rooted, "update-index", "--assume-unchanged", CONFIG)
    (rooted / CONFIG).write_text(SAME_LENGTH, encoding="utf-8")
    audit = audit_worktree(rooted)
    assert audit.status_reported_clean is True
    assert audit.status_disagrees is True
    assert audit.flagged_paths == ((CONFIG, "assume-unchanged"),)
    with pytest.raises(ValidationError) as failure:
        require_clean_worktree("An evidence-grade run")
    message = str(failure.value)
    assert "assume-unchanged" in message
    assert "reported this tree CLEAN" in message
    assert "force-remove" in message


def test_a_skip_worktree_bit_is_refused_on_its_own(rooted: Path) -> None:
    # No edit at all. The bit alone makes every later git report unreliable, so the gate
    # refuses rather than reporting a cleanliness it cannot establish.
    _run(rooted, "update-index", "--skip-worktree", CONFIG)
    audit = audit_worktree(rooted)
    assert audit.flagged_paths == ((CONFIG, "skip-worktree"),)
    assert not audit.clean
    with pytest.raises(ValidationError, match="skip-worktree"):
        require_clean_worktree("An evidence-grade run")


def test_a_staged_but_uncommitted_change_is_refused(rooted: Path) -> None:
    (rooted / CONFIG).write_text(SAME_LENGTH, encoding="utf-8")
    _run(rooted, "add", CONFIG)
    audit = audit_worktree(rooted)
    assert audit.staged_paths == (CONFIG,)
    assert audit.modified_paths == ()
    with pytest.raises(ValidationError, match="staged but uncommitted"):
        require_clean_worktree("An evidence-grade run")


def test_a_deleted_tracked_file_is_refused(rooted: Path) -> None:
    (rooted / CONFIG).unlink()
    audit = audit_worktree(rooted)
    assert audit.missing_paths == (CONFIG,)
    with pytest.raises(ValidationError, match="tracked but absent"):
        require_clean_worktree("An evidence-grade run")


def test_an_untracked_file_is_refused(rooted: Path) -> None:
    (rooted / "scratch.json").write_text("{}\n", encoding="utf-8")
    audit = audit_worktree(rooted)
    assert audit.untracked_paths == ("scratch.json",)
    with pytest.raises(ValidationError, match="untracked"):
        require_clean_worktree("An evidence-grade run")


def test_an_unreadable_repository_is_never_clean(tmp_path: Path) -> None:
    audit = audit_worktree(tmp_path / "not-a-repository")
    assert audit.commit is None
    assert not audit.clean


def test_the_evidence_gate_records_which_check_established_cleanliness(rooted: Path) -> None:
    state = require_clean_worktree("An evidence-grade run")
    assert state["dirty"] is False
    verification = state["verification"]
    assert verification["byte_audit_performed"] is True
    assert "re-hashed" in verification["method"]
    assert verification["tracked_files"] == 1


def test_the_cheap_check_says_it_is_the_cheap_check(rooted: Path) -> None:
    # A development run must not be able to pass itself off as byte-verified.
    state = runs.git_metadata()
    verification = state["verification"]
    assert verification["byte_audit_performed"] is False
    assert "NOT re-hashed" in verification["method"]
    assert "same-length" in verification["why_this_is_weaker"]


def test_the_cheap_check_still_refuses_to_call_a_flagged_tree_clean(rooted: Path) -> None:
    _run(rooted, "update-index", "--assume-unchanged", CONFIG)
    (rooted / CONFIG).write_text(SAME_LENGTH, encoding="utf-8")
    state = runs.git_metadata()
    # git status reports clean here; the index-bit audit is cheap enough to run anyway.
    assert state["dirty"] is True
    assert state["verification"]["status_reported_clean"] is True
    assert state["verification"]["index_bits_set"] == [f"{CONFIG} (assume-unchanged)"]


def test_a_detached_worktree_is_created_recognised_and_removed(rooted: Path) -> None:
    target = rooted.parent / "evidence-worktree"
    created = runs.create_evidence_worktree(path=target, commit="HEAD", root=rooted)
    assert created["detached"] is True
    assert (target / CONFIG).read_text(encoding="utf-8") == ORIGINAL
    audit = audit_worktree(target)
    assert audit.clean
    assert audit.detached_head is True
    assert audit.linked_worktree is True
    assert audit.as_dict()["ran_from_detached_worktree"] is True
    runs.remove_evidence_worktree(path=target, root=rooted)
    assert not target.exists()


def test_a_worktree_will_not_be_created_over_an_existing_path(rooted: Path) -> None:
    target = rooted.parent / "occupied"
    target.mkdir()
    with pytest.raises(ValidationError, match="Refusing to reuse"):
        runs.create_evidence_worktree(path=target, root=rooted)


def test_an_edit_inside_a_detached_worktree_is_still_caught(rooted: Path) -> None:
    # The worktree is immutable in practice, not by force. If someone edits it anyway,
    # the audit must catch that too rather than trusting the detached state.
    target = rooted.parent / "editable-worktree"
    runs.create_evidence_worktree(path=target, commit="HEAD", root=rooted)
    try:
        _edit_preserving_length_and_timestamps(target)
        audit = audit_worktree(target)
        assert audit.modified_paths == (CONFIG,)
        assert not audit.clean
    finally:
        runs.remove_evidence_worktree(path=target, root=rooted)
