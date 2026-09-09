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


def test_the_criterion_is_adopted_prospectively_and_withdraws_nothing(
    v5: dict[str, Any],
) -> None:
    assert v5["adopted"] is True
    assert v5["adopted_on"] == "2026-09-09"
    terms = v5["adoption_terms"]
    assert "re-scores nothing" in terms["prospective_only"]
    preserved = " ".join(terms["earlier_verdicts_preserved_unchanged"])
    # The three verdicts that must survive adoption, named explicitly.
    assert "0 of 30" in preserved
    assert "2 of 7 development poses" in preserved
    assert "0 of 3" in preserved
    assert "remains not an accepted milestone" in v5["claim_boundary"]


def test_the_superseded_wording_is_preserved_rather_than_deleted(
    v5: dict[str, Any],
) -> None:
    """Before adoption this contract said it superseded nothing. That line is now false of
    the criterion and still true of every verdict, so it is kept and annotated."""
    supersedes = v5["supersedes"]

    assert supersedes["experiment_id"] == "track-a-acceptance-v4-criteria"
    assert "supersedes nothing" in supersedes["superseded_text_before_adoption"]
    assert "No verdict is withdrawn" in supersedes["what_does_not_change"]


def test_the_validation_threshold_is_one_the_development_set_fails(
    v5: dict[str, Any],
) -> None:
    """The only property that matters: it cannot have been chosen to be passable."""
    threshold = v5["development_and_validation_split"]["validation_acceptance_threshold"]

    assert "10 of the 12" in threshold["threshold"]
    assert "8 successes of 10" in threshold["where_it_comes_from"]
    assert "FAILS" in threshold["disclosure_that_it_is_informed"]
    assert "5 of 7" in threshold["disclosure_that_it_is_informed"]
    assert "below 80" in threshold["disclosure_that_it_is_informed"]


def test_the_split_is_registered_with_a_seed_and_a_freeze(v5: dict[str, Any]) -> None:
    split = v5["development_and_validation_split"]

    assert len(split["development_poses"]) == 7
    rule = split["validation_set_rule"]
    assert "20260910" in rule["generator"]
    assert rule["count"] == 12
    freeze = split["freeze_and_evaluate_once"]
    assert "clean worktree" in freeze["freeze"]
    assert "exactly once" in freeze["evaluate_once"]
    assert "new validation set" in freeze["no_retuning_after_seeing_it"]


def test_the_rejected_secondary_channel_is_recorded(v5: dict[str, Any]) -> None:
    """A tuning attempt that failed on development is part of the record, not deleted."""
    note = v5["development_and_validation_split"]["secondary_channel_attempt"]

    assert "weight 0.0" in note
    assert "3 of 7 passing against 5 of 7" in note
    assert "No validation pose was involved" in note or "no validation pose" in note.lower()


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
    proposed = v5["adopted_criterion"]

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
    rejects = v5["adopted_criterion"]["would_reject_all_three_degenerate_cases"]
    limit = v5["adopted_criterion"]["limit_mm"]

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


def test_the_validation_outcome_is_recorded_exactly_as_evaluated(v5: dict[str, Any]) -> None:
    outcome = v5["validation_outcome"]
    assert outcome["evaluated_once"] is True
    assert outcome["poses_scored"] == 12
    assert outcome["b2_passes"] == 12
    assert outcome["b3_v5_passes"] == 8
    assert outcome["required_passes"] == 10
    assert "validation FAILS" in outcome["verdict"]
    assert outcome["observed"] == 8
    assert outcome["frozen_commit"] == "4c4a53f"
    # The prediction written before the run, kept alongside the result it predicted.
    assert "8 or 9" in outcome["predicted_before_the_run"]


def test_the_outcome_is_not_reinterpreted_as_an_overfitting_gap(v5: dict[str, Any]) -> None:
    comparison = v5["validation_outcome"]["development_versus_validation"]
    assert "same rate" in comparison
    assert "capability limit" in comparison
    assert "rather than an overfitting gap" in comparison


def test_the_validation_set_is_declared_spent_and_the_code_agrees(v5: dict[str, Any]) -> None:
    from flysim.station_validation import SPENT_VALIDATION_SEEDS

    seed = v5["development_and_validation_split"]["validation_set_rule"]["seed"]
    assert seed == 20260910
    assert seed in SPENT_VALIDATION_SEEDS
    recorded = SPENT_VALIDATION_SEEDS[seed]
    outcome = v5["validation_outcome"]
    # The pinned record and the contract must not drift apart.
    assert recorded["b3_v5_passes"] == outcome["b3_v5_passes"]
    assert recorded["b2_passes"] == outcome["b2_passes"]
    assert recorded["required_passes"] == outcome["required_passes"]
    assert recorded["poses_scored"] == outcome["poses_scored"]
    assert recorded["frozen_commit"] == outcome["frozen_commit"]


def test_a_spent_seed_cannot_be_redrawn_for_development_or_for_scoring() -> None:
    import pytest as _pytest

    from flysim.errors import ConfigurationError
    from flysim.station_validation import draw_validation_poses

    for purpose in ("validation", "development"):
        with _pytest.raises(ConfigurationError, match="is spent"):
            draw_validation_poses(
                seed=20260910, count=12, max_attempts=40, purpose=purpose
            )


def test_a_spent_seed_may_still_be_reproduced_for_inspection() -> None:
    from flysim.station_validation import draw_validation_poses

    poses = draw_validation_poses(
        seed=20260910, count=12, max_attempts=12, purpose="reproduce"
    )
    assert len(poses) == 12
    # The recorded first pose of the evaluated set, so a reader can check the artifact.
    assert poses[0]["initial_heading_rad"] == pytest.approx(-3.0990, abs=1e-4)
    assert poses[0]["initial_y_mm"] == pytest.approx(1.217, abs=1e-3)


def test_an_unspent_seed_is_still_drawable() -> None:
    from flysim.station_validation import draw_validation_poses

    poses = draw_validation_poses(seed=20260911, count=4, max_attempts=4)
    assert len(poses) == 4


def test_an_unknown_draw_purpose_fails_closed() -> None:
    import pytest as _pytest

    from flysim.errors import ConfigurationError
    from flysim.station_validation import draw_validation_poses

    with _pytest.raises(ConfigurationError, match="Unknown draw purpose"):
        draw_validation_poses(seed=20260911, count=4, max_attempts=4, purpose="tuning")


def test_the_successor_controller_needs_two_fresh_registered_seeds(v5: dict[str, Any]) -> None:
    rule = v5["future_development_rule"]
    assert rule["successor_id"] == "MOTOR-05"
    requirements = " ".join(rule["requirements"])
    assert "new development set" in requirements
    assert "separately frozen validation set" in requirements
    assert "before tuning" in requirements
    assert "20260910 stays permanently retired" in requirements
    assert "does not withdraw an earlier failure" in rule["what_stays_on_the_record"]
