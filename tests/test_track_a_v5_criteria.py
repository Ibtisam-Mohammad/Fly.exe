# SPDX-License-Identifier: GPL-2.0-or-later
"""The v5 proposal, and the checks that stop it from becoming a quiet criterion swap.

A replacement written by the author of the controller that failed the original is exactly
the move this project has had to repair three times. These tests are the guard rails:
the proposal must stay unadopted, must not withdraw the v4 failure, must actually reject
the degenerate cases that motivate it, and must not be merely easier than what it
replaces.
"""

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
V4 = REPO / "configs" / "experiments" / "track-a-acceptance-v4-criteria.json"
V5 = REPO / "configs" / "experiments" / "track-a-acceptance-v5-criteria.json"


@pytest.fixture
def v5() -> dict[str, Any]:
    return json.loads(V5.read_text(encoding="utf-8"))


@pytest.fixture
def demonstrations(v5: dict[str, Any]) -> dict[str, dict[str, Any]]:
    listed = v5["why_this_exists"]["demonstrations_that_b3_is_degenerate"]
    return {item["id"]: item for item in listed}


def test_the_proposal_is_not_adopted_and_changes_no_verdict(v5: dict[str, Any]) -> None:
    assert v5["adopted"] is False
    assert "NOT ADOPTED" in v5["status"]
    assert "supersedes nothing" in v5["supersedes_nothing"].lower()
    assert "remains failed" in v5["claim_boundary"]
    assert "remains not an accepted milestone" in v5["claim_boundary"]


def test_the_v4_criterion_is_untouched(v5: dict[str, Any]) -> None:
    """The proposal may not edit what it proposes to replace."""
    v4 = json.loads(V4.read_text(encoding="utf-8"))
    b3 = next(item for item in v4["criteria"] if item["id"] == "B3")

    assert b3["fails_now"] is True
    assert b3["currently_observed"]["limit"] == 1.5
    assert b3["currently_observed"]["passes"] is False


def test_the_limit_is_still_one_body_length(v5: dict[str, Any]) -> None:
    """Only the statistic may change. A looser limit would be the smuggled relaxation."""
    v4 = json.loads(V4.read_text(encoding="utf-8"))
    proposed = v5["proposed_criterion"]

    assert proposed["limit_mm"] == 2.5
    for identifier in ("B1", "B2"):
        criterion = next(item for item in v4["criteria"] if item["id"] == identifier)
        assert criterion["limit_mm"] == proposed["limit_mm"]


def test_the_decisive_demonstration_really_is_decisive(demonstrations: dict[str, Any]) -> None:
    """D3 is the case that settles it: a runaway body satisfying the ratio criterion."""
    observed = demonstrations["D3"]["observed"]

    # The recorded ratio must actually follow from the recorded displacements.
    ratio = observed["displacement_6s_mm"] / observed["displacement_3s_mm"]
    assert ratio == pytest.approx(observed["ratio"], abs=5e-3)
    # And it must pass the v4 limit while the body is plainly lost.
    assert ratio < 1.5
    assert observed["passes"] is True
    assert observed["displacement_3s_mm"] > 4.0 * 2.5
    assert observed["heading_change_rad"] > 2.0


def test_the_short_window_demonstration_is_arithmetically_sound(
    demonstrations: dict[str, Any],
) -> None:
    observed = demonstrations["D2"]["observed"]

    assert observed["displacement_6s_mm"] / observed["displacement_3s_mm"] == pytest.approx(
        observed["ratio"], abs=5e-3
    )
    assert observed["displacement_12s_mm"] / observed["displacement_3s_mm"] == pytest.approx(
        observed["ratio_12s_over_3s"], abs=5e-2
    )
    # It passes at 6 s and is far past a body length at 12 s. That is the whole point.
    assert observed["passes"] is True
    assert observed["displacement_12s_mm"] > 2.5


def test_the_better_controller_really_is_the_one_that_fails(
    demonstrations: dict[str, Any],
) -> None:
    first = demonstrations["D1"]
    worse, better = first["worse_controller"], first["better_controller"]

    assert better["displacement_3s_mm"] < worse["displacement_3s_mm"]
    assert better["passes"] is False and worse["passes"] is True
    assert better["ratio"] > worse["ratio"]


def test_the_proposal_rejects_the_cases_that_motivate_it(v5: dict[str, Any]) -> None:
    """A replacement that accepted the degenerate cases would be no improvement."""
    rejects = v5["proposed_criterion"]["would_reject_all_three_degenerate_cases"]
    limit = v5["proposed_criterion"]["limit_mm"]

    for key in ("D2_leaking_case", "D3_diverged_case", "uncontrolled_baseline"):
        case = rejects[key]
        assert case["passes"] is False, key
        assert case["displacement_12s_mm"] > limit, key


def test_the_proposal_is_not_merely_easier(v5: dict[str, Any]) -> None:
    """It must fail something the current controller produces, or it is criterion-shopping."""
    disclosure = v5["disclosure"]

    assert "not one the current controller passes" in disclosure["not_blind"]
    assert "would not close Track A" in disclosure["not_blind"]
    assert "criterion-shopping" in disclosure["reviewer_instruction"]
    assert "Not the author of the controller" in disclosure["who_decides"]


def test_everything_else_stays_in_place(v5: dict[str, Any]) -> None:
    unchanged = " ".join(v5["what_stays_unchanged"])

    for item in ("B1", "B2", "B4", "nine existing controls", "100 ms"):
        assert item in unchanged
