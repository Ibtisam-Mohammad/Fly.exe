# SPDX-License-Identifier: GPL-2.0-or-later
"""ND-03 and ND-10, and the claim the split exists to stop.

The old ND-03 bundled a testable quantity with an untestable one. Every place that cited
it for an edge's sign was leaning on the untestable half, which made a bounded claim look
like a tested one. These tests hold the two apart: transmitter identity has a validation
set, polarity does not, and neither record may quietly reacquire the other's properties.
"""

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "configs" / "assumptions.json"
RESERVATIONS = REPO / "configs" / "datasets" / "stage2-reservations-v1.json"
INTAKE = REPO / "configs" / "datasets" / "stage2-2026-09-09-intake.json"


@pytest.fixture
def records() -> dict[str, dict[str, Any]]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {record["id"]: record for record in payload["records"]}


def test_the_set_identifier_moved_with_the_split() -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert payload["assumption_set_id"] == "foundation-v0.7"


def test_nd03_is_transmitter_identity_and_disclaims_edge_sign(
    records: dict[str, dict[str, Any]],
) -> None:
    record = records["ND-03"]
    assert record["name"] == "presynaptic transmitter identity"
    assert record["value"]["resolves_edge_sign"] is False
    assert "presynaptic neuron" in record["applies_to"]
    assert "cannot measure whether an edge excites or inhibits" in record["uncertainty"]


def test_nd10_carries_polarity_and_leaves_the_sign_unresolved(
    records: dict[str, dict[str, Any]],
) -> None:
    record = records["ND-10"]
    assert record["name"] == "postsynaptic receptor identity and functional edge polarity"
    assert record["value"]["unresolved_sign_default"] == "unresolved"
    assert "partner-specific" in record["biological_mismatch"]
    # The transmitter ground truth must not be claimed as validation for this record.
    assert "does not validate this record" in record["uncertainty"]
    assert "upper bound on sign correctness" in record["uncertainty"]


def test_only_the_transmitter_record_claims_a_validation_set(
    records: dict[str, dict[str, Any]],
) -> None:
    assert "Reserved and unopened" in records["ND-03"]["validation"]
    assert "6,107" in records["ND-03"]["uncertainty"]
    polarity = records["ND-10"]
    assert "Not available at scale" in polarity["validation"]
    assert "6,107" not in polarity["uncertainty"]


def test_the_transmitter_only_sign_rule_stays_a_named_control(
    records: dict[str, dict[str, Any]],
) -> None:
    value = records["ND-10"]["value"]
    assert "regression control" in value["transmitter_only_sign_rule"]
    assert "not the physiological default" in value["transmitter_only_sign_rule"]


def test_the_live_scenario_requires_both_halves() -> None:
    scenario = json.loads(
        (REPO / "configs" / "scenarios" / "eon-malecns.json").read_text(encoding="utf-8")
    )
    assert scenario["assumption_set"] == "foundation-v0.7"
    required = scenario["required_assumptions"]
    assert "ND-03" in required
    assert "ND-10" in required
    # A run that asserts edge signs must record the boundary it is asserting them under.
    assert required.index("ND-10") == required.index("ND-03") + 1


def test_val02_declares_the_observation_model_as_an_assumption(
    records: dict[str, dict[str, Any]],
) -> None:
    record = records["VAL-02"]
    assert record["provenance"] == "E"
    assert record["status"] == "proposed"
    assert "Every clause is false in detail" in record["biological_mismatch"]
    # The direction of the bias is what makes the assumption usable, so it must be stated.
    assert "bias a measured paired-pulse ratio downward" in record["uncertainty"]


def test_motor04_records_the_failed_validation_and_the_successor_rule(
    records: dict[str, dict[str, Any]],
) -> None:
    validation = records["MOTOR-04"]["validation"]
    assert "8 of 12 against the 10 required" in validation
    assert "validation FAILS" in validation
    assert "MOTOR-05" in validation
    assert "spent" in validation


def test_the_intake_correction_names_what_it_got_wrong() -> None:
    intake = json.loads(INTAKE.read_text(encoding="utf-8"))
    reserved = {item["id"]: item for item in intake["reserved_as_validation_genuinely_unseen"]}
    transmitter = reserved["drosophila-neurotransmitter-ground-truth"]
    correction = transmitter["correction_to_this_entry"]
    assert "overstates" in correction
    assert "ND-10" in correction
    assert "upper bound on sign correctness" in correction
    # And the corrected claim must no longer say the dataset tests sign assignment.
    claim = transmitter["why_it_matters"]
    assert "sign assignment" not in claim
    assert "excites or inhibits" not in claim
    assert "transmitter label is right" in claim
    changes = " ".join(intake["what_this_intake_changes"])
    assert "not as edge sign" in changes
    assert "synaptic leg is NOT reinstated" in changes


def test_the_malecns_join_question_is_recorded_as_resolved() -> None:
    intake = json.loads(INTAKE.read_text(encoding="utf-8"))
    reserved = {item["id"]: item for item in intake["reserved_as_validation_genuinely_unseen"]}
    transmitter = reserved["drosophila-neurotransmitter-ground-truth"]
    assert transmitter["open_question"].startswith("RESOLVED")
    assert "cell_type_mcns" in transmitter["open_question"]
    reservations = json.loads(RESERVATIONS.read_text(encoding="utf-8"))
    paths = {
        entry["path"]
        for dataset in reservations["datasets"]
        for entry in dataset["files"]
    }
    assert (
        "drosophila-neurotransmitters/gt_sources/male_cns/202509-male_cns_gt_data.csv" in paths
    )
