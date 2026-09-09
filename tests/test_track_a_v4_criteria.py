# SPDX-License-Identifier: GPL-2.0-or-later
"""The v4 Track A criteria, and the checks that stop the split from hiding a defect.

Splitting a failed criterion is criterion-shopping unless the replacement is genuinely
failable and currently failing. These tests are the contract's own reviewer instruction made
executable, so a later edit that quietly weakens it breaks the suite.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "configs" / "experiments" / "track-a-acceptance.json"
V4 = REPO / "configs" / "experiments" / "track-a-acceptance-v4-criteria.json"


@pytest.fixture
def v4() -> dict:
    return json.loads(V4.read_text())


@pytest.fixture
def criteria(v4: dict) -> dict:
    return {item["id"]: item for item in v4["criteria"]}


def test_the_body_length_limit_is_unchanged_from_v3(v4: dict, criteria: dict) -> None:
    """The split must not smuggle in a looser limit; only what it measures may change."""
    v3 = json.loads(V3.read_text())

    assert v3["behavioral_criteria"]["max_groom_net_displacement_mm"] == 2.5
    assert criteria["B1"]["limit_mm"] == 2.5
    assert criteria["B2"]["limit_mm"] == 2.5
    assert criteria["B4"]["minimum_mm"] == v3["behavioral_criteria"][
        "min_pre_groom_seek_displacement_mm"
    ]


def test_the_replacement_criterion_currently_fails(criteria: dict) -> None:
    """B3 is the point of the split. If it passed, the split would hide the defect."""
    b3 = criteria["B3"]

    assert b3["fails_now"] is True
    observed = b3["currently_observed"]
    assert observed["passes"] is False
    # And the recorded numbers must actually fail the stated limit, not merely say so.
    ratio = observed["displacement_6s_mm"] / observed["displacement_3s_mm"]
    assert ratio == pytest.approx(observed["ratio"], abs=5e-3)
    assert ratio > observed["limit"]


def test_the_absolute_displacement_is_still_reported(v4: dict) -> None:
    """Dropping it would remove the measurement the v3 criterion capped."""
    reporting = v4["reporting_requirements"]

    assert "groom_net_displacement_mm" in reporting["absolute_displacement_still_recorded"]
    assert "not withdrawn" in reporting["v3_verdict_stands"]
    assert "0 of 30" in reporting["v3_verdict_stands"]


def test_acceptance_requires_every_criterion_not_just_the_new_one(v4: dict) -> None:
    requirement = v4["reporting_requirements"]["acceptance_requires_all"]

    for identifier in ("B1", "B2", "B3", "B4"):
        assert identifier in requirement
    assert "Passing B1 alone changes nothing" in requirement


def test_the_physics_escape_routes_are_named_and_forbidden(criteria: dict) -> None:
    """The ADR-2026-006 constraint, written into the criterion that would be tempted by it."""
    forbidden = criteria["B3"]["must_not_be_cleared_by"]

    for route in ("adhesion", "contact", "actuator force", "damping", "weld", "shorten"):
        assert any(route in entry for entry in forbidden), route
    assert "controller addition rather than a physics change" in criteria["B3"]["may_be_cleared_by"]


def test_the_contract_discloses_that_it_is_not_blind(v4: dict) -> None:
    """It was written after the failure, in the direction that makes B1 pass."""
    disclosure = v4["disclosure"]

    assert "not_blind" in disclosure
    assert "1.34 mm" in disclosure["not_blind"]
    assert "which passes" in disclosure["not_blind"]
    # It must name the prior repairs of the same kind rather than presenting itself as novel.
    assert "third such correction" in disclosure["prior_repairs_of_this_kind"]
    assert "criterion-shopping" in disclosure["reviewer_instruction"]


def test_the_decomposition_sums_to_the_observed_displacement(v4: dict) -> None:
    """The whole argument rests on this arithmetic, so it is checked rather than trusted."""
    parts = v4["problem"]["decomposition"]

    assert parts["baseline_creep_contribution_mm"] == pytest.approx(
        parts["standing_no_command_all_six_legs_adhered_mm"]
    )
    assert parts["adhesion_pattern_contribution_mm"] == pytest.approx(
        parts["grooming_adhesion_pattern_no_replay_mm"]
        - parts["standing_no_command_all_six_legs_adhered_mm"],
        abs=1e-3,
    )
    assert parts["replay_own_contribution_mm"] == pytest.approx(
        parts["full_grooming_bout_with_replay_v3_median_mm"]
        - parts["grooming_adhesion_pattern_no_replay_mm"],
        abs=1e-2,
    )
    total = (
        parts["baseline_creep_contribution_mm"]
        + parts["adhesion_pattern_contribution_mm"]
        + parts["replay_own_contribution_mm"]
    )
    assert total == pytest.approx(parts["full_grooming_bout_with_replay_v3_median_mm"], abs=1e-2)
    # The replay must be the smallest term, which is the claim the split rests on.
    assert parts["replay_own_contribution_mm"] < parts["adhesion_pattern_contribution_mm"]
    assert parts["replay_own_contribution_mm"] < parts["baseline_creep_contribution_mm"]


def test_the_renderer_amendment_only_adds_and_currently_fails(v4: dict) -> None:
    amendment = v4["renderer_control_amendment"]

    assert amendment["currently_passes"] is False
    assert amendment["currently_observed_ms"] > amendment["limit_ms"]
    assert "strictly added" in amendment["note"]
    # The tolerance must be justified against the simulation's own timescales.
    assert "coupling cycle" in amendment["limit_rationale"]


def test_nothing_is_accepted_by_registering_criteria(v4: dict) -> None:
    assert v4["status"] == "preregistered, not executed"
    assert "No run is executed" in v4["claim_boundary"]
    assert "remains not an accepted milestone" in v4["claim_boundary"]
    # The criterion must be fixed before a controller exists, or it could be chosen to fit one.
    assert "written first" in v4["registered_before"]
    assert "controller" in v4["registered_before"]
