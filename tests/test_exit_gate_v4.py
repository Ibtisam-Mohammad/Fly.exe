# SPDX-License-Identifier: GPL-2.0-or-later
"""The restructured Stage 2 gate, and the guard rails that stop it becoming a free pass.

Retiring two of four legs from a failing gate is the shape of the gate redefinition an
independent audit found in this repository in September 2026. These tests are the
constraints ADR-2026-011 imposes on itself, made executable, so a later edit that quietly
widens the gate breaks the suite.
"""

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "configs" / "experiments" / "stage2-exit-gate-v3.json"
V4 = REPO / "configs" / "experiments" / "stage2-exit-gate-v4.json"
ADR = REPO / "docs" / "adr" / "ADR-2026-011-retire-the-blocked-physiology-gates.md"


@pytest.fixture
def v4() -> dict[str, Any]:
    return json.loads(V4.read_text(encoding="utf-8"))


def test_the_retired_legs_are_the_two_that_need_unavailable_data(v4: dict[str, Any]) -> None:
    retired = {leg["id"] for leg in v4["retired_legs"]}

    assert retired == {"cellular", "synaptic"}
    availability = ("No public repository", "None are public", "not public")
    for leg in v4["retired_legs"]:
        # The justification has to be about the data being unavailable, which would hold
        # whether or not the leg passed. A justification that appealed to the failure
        # would be the gate redefinition ADR-2026-011 has to distinguish itself from.
        because = leg["retired_because"]
        assert any(marker in because for marker in availability), leg["id"]
        assert "fails" not in because and "failing" not in because, leg["id"]
        assert leg["reinstate_when"].strip()
        assert "at least as strict" in leg["reinstate_when"]


def test_a_retired_leg_carries_no_criterion(v4: dict[str, Any]) -> None:
    """An unscored leg with an expectation still attached invites being scored again."""
    for leg in v4["retired_legs"]:
        for key in ("expect", "expect_at_least", "expect_below"):
            assert key not in leg, f"{leg['id']} still declares {key}"


def test_the_retired_legs_keep_their_artifact_pins(v4: dict[str, Any]) -> None:
    """Retiring must narrow what is scored, not what is verified."""
    v3 = json.loads(V3.read_text(encoding="utf-8"))
    v3_legs = {leg["id"]: leg for leg in v3["legs"]}

    for leg in v4["retired_legs"]:
        assert leg["artifact"] == v3_legs[leg["id"]]["artifact"]
        assert leg["sufficiency_caveats"] == v3_legs[leg["id"]]["sufficiency_caveats"]


def test_the_surviving_legs_are_unchanged_from_v3(v4: dict[str, Any]) -> None:
    v3 = json.loads(V3.read_text(encoding="utf-8"))
    v3_legs = {leg["id"]: leg for leg in v3["legs"]}
    v4_legs = {leg["id"]: leg for leg in v4["legs"]}

    for identifier in ("circuit", "ensemble"):
        assert v4_legs[identifier] == v3_legs[identifier]


def test_the_gate_did_not_get_easier(v4: dict[str, Any]) -> None:
    """The whole point: nothing is gained. Every scored leg must currently fail."""
    v4_legs = {leg["id"]: leg for leg in v4["legs"]}

    assert set(v4_legs) == {"circuit", "ensemble", "structural"}
    # The circuit leg observes 0.0 against a 0.8 floor and the ensemble leg observes false;
    # the structural leg reads a hypothesis that is rejected. Assert the criteria, since the
    # observed values live in the artifacts.
    assert v4_legs["circuit"]["expect_at_least"] == 0.8
    assert v4_legs["ensemble"]["expect"] is True
    assert v4_legs["structural"]["expect"] is True
    assert "0 of 3" in v4["purpose"]


def test_the_structural_leg_was_registered_before_the_run_that_scores_it(
    v4: dict[str, Any],
) -> None:
    """The composition rule is what separates this from criterion-shopping."""
    rule = v4["composition_rule"]
    structural = next(leg for leg in v4["legs"] if leg["id"] == "structural")

    assert "registered before the test that scores it was run" in rule
    assert "criterion-shopping" in rule
    assert "564bdb9" in structural["registered_before_the_run"]
    assert "could not be chosen to fit the outcome" in structural["registered_before_the_run"]


def test_the_known_outcome_structural_results_are_not_scored(v4: dict[str, Any]) -> None:
    """Scoring a test whose result was already known would breach the composition rule."""
    not_scored = {item["id"] for item in v4["structural_results_deliberately_not_scored"]}
    scored = {leg["id"] for leg in v4["legs"]}

    assert not_scored == {
        "orn_pn_convergence",
        "glomerular_volume_scaling",
        "completeness_corrected_contacts",
    }
    assert not (not_scored & scored)
    for item in v4["structural_results_deliberately_not_scored"]:
        assert item["why_not_scored"].strip()


def test_retiring_a_leg_is_not_recorded_as_passing_it(v4: dict[str, Any]) -> None:
    acceptance = v4["acceptance"]

    assert "not passed, waived or satisfied" in acceptance["retiring_a_leg_is_not_passing_it"]
    assert "which legs were scored" in acceptance["retiring_a_leg_is_not_passing_it"]
    # And the gate must admit it is weaker than the statement it descends from.
    assert "weaker than the statement" in acceptance["narrower_than_the_gate_statement"]
    assert "AGENTS.md" in acceptance["narrower_than_the_gate_statement"]


def test_no_verdict_is_withdrawn(v4: dict[str, Any]) -> None:
    supersedes = v4["supersedes"]

    assert supersedes["experiment_id"] == "stage2-exit-gate-v3"
    assert "0 of 4 stands" in supersedes["what_does_not_change"]
    assert "no verdict is withdrawn" in supersedes["what_does_not_change"].lower()


def test_the_gate_awards_no_tier(v4: dict[str, Any]) -> None:
    assert "awards no validation tier" in v4["tier_policy"]
    assert "awards no tier" in v4["claim_boundary"]


def test_the_adr_states_what_is_lost(
) -> None:
    """A restructure that only listed its benefits would be advocacy, not a decision record."""
    adr = ADR.read_text(encoding="utf-8")

    assert "## What is lost" in adr
    # It must name the audit finding it resembles rather than hope nobody notices.
    assert "gate redefinition" in adr
    assert "stronger scientific object" in adr
    assert "reinstated if the data appears" in adr
    # And it must say the structural legs do not test the simulator.
    assert "test the connectome, not the model" in adr
