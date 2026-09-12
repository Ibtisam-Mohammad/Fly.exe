# SPDX-License-Identifier: GPL-2.0-or-later
"""The train scorer, on fixtures. Nothing here touches the Rozenfeld corpus.

What is tested is that when the real run opens the last unspent wild-type holdout it
refuses a drifted file, refuses a second pass, refuses a fit artifact that is not the one
the candidates were frozen from, refuses a frozen trajectory that no longer reproduces,
refuses an array that duplicates spent data, and computes both registered normalisations
and the R1/R2 arithmetic the way the committed contract says.
"""

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError
from flysim.stp_train import (
    R1_MARGIN,
    R2_MARGIN,
    _normalise,
    _weighted_error,
    run_stp_train_discrimination,
)

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "configs/experiments/stage2-stp-train-discrimination-v1.json"

_MI_INT8, _MI_INT32, _MI_UINT32, _MI_DOUBLE = 1, 5, 6, 9
_MI_MATRIX, _MI_COMPRESSED, _MX_DOUBLE = 14, 15, 6
TRAINS = {"1Hz": 32, "10Hz": 100, "20Hz": 100, "60Hz": 112}


def _element(element_type: int, data: bytes) -> bytes:
    return struct.pack("<II", element_type, len(data)) + data + b"\x00" * (-len(data) % 8)


def _matrix(name: str, block: np.ndarray) -> bytes:
    rows, columns = block.shape
    flat = np.asarray(block, dtype=np.float64).reshape(-1, order="F")
    body = (
        _element(_MI_UINT32, struct.pack("<II", _MX_DOUBLE, 0))
        + _element(_MI_INT32, struct.pack("<2i", rows, columns))
        + _element(_MI_INT8, name.encode("ascii"))
        + _element(_MI_DOUBLE, struct.pack(f"<{flat.size}d", *flat))
    )
    return _element(_MI_MATRIX, body)


def _mat_file(arrays: dict[str, np.ndarray]) -> bytes:
    header = b"MATLAB 5.0 MAT-file, hand-built fixture".ljust(124, b" ")
    header += struct.pack("<H", 0x0100) + b"IM"
    return header + b"".join(
        _element(_MI_COMPRESSED, zlib.compress(_matrix(name, block)))
        for name, block in arrays.items()
    )


def _cohort(trajectory: list[float], animals: int = 18, scale: float = -40.0) -> np.ndarray:
    """A cohort whose mean trajectory is the requested one, in negative picoamps."""
    block = np.empty((animals, len(trajectory)), dtype=np.float64)
    offsets = np.linspace(-0.02, 0.02, animals)
    for row in range(animals):
        block[row] = scale * (np.array(trajectory) + offsets[row])
    return block


def _environment(
    tmp_path: Path, trajectories: dict[str, list[float]] | None = None
) -> dict[str, Path]:
    staging = tmp_path / "staging"
    (staging / "rozenfeld2023-repo" / "Figure 3").mkdir(parents=True)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    models = contract["frozen_predictions"]["models"]
    truth = models["candidate_A_two_timescale_facilitation_free"]["by_frequency"]
    arrays = {}
    for label, pulses in TRAINS.items():
        curve = (trajectories or {}).get(label) or truth[label]["trajectory"]
        arrays[f"all_flies_{label}_control"] = _cohort(list(curve[:pulses]))
        arrays[f"all_flies_{label}_RNAi"] = _cohort([0.5] * pulses)
    train_path = staging / "rozenfeld2023-repo" / "Figure 3" / "Fig3E_and_F.mat"
    train_path.write_bytes(_mat_file(arrays))

    spent: dict[str, Path] = {}
    for name, variables in (
        ("Fig3D.mat", [f"new_all_flies_PP_{i:g}ms_control" for i in (10, 30, 100, 300, 1000)]),
        ("Fig3H.mat", [f"new_all_flies_PP_{i:g}ms_control" for i in (10, 30, 100, 300, 1000)]),
        ("Fig3B.mat", ["all_flies_1Hz_control"]),
    ):
        path = staging / "rozenfeld2023-repo" / "Figure 3" / name
        path.write_bytes(
            _mat_file({key: _cohort([0.9] * 6, animals=7) for key in variables})
        )
        spent[name] = path

    manifest = {
        "datasets": [
            {
                "id": "fixture",
                "files": [
                    {
                        "path": "rozenfeld2023-repo/Figure 3/Fig3E_and_F.mat",
                        "sha256": sha256_file(train_path),
                        "reserved_names": list(arrays),
                    }
                ],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fit = tmp_path / "fit.json"
    fit.write_text(json.dumps({"fit_set": {}}), encoding="utf-8")
    contract["depends_on"] = {}
    # The real contract records its values as opened, having been executed and voided on
    # 2026-09-10. The fixture is a fresh copy of its rules, not a second look at it.
    contract["values_opened"] = False
    contract["frozen_predictions"]["fit_artifact_sha256"] = sha256_file(fit)
    local = tmp_path / "contract.json"
    local.write_text(json.dumps(contract), encoding="utf-8")
    return {
        "contract": local,
        "fit": fit,
        "manifest": manifest_path,
        "staging": staging,
        "output": tmp_path / "out.json",
        "train": train_path,
        "fig3d": spent["Fig3D.mat"],
    }


def _run(paths: dict[str, Path]) -> dict[str, Any]:
    return run_stp_train_discrimination(
        contract_path=paths["contract"],
        fit_artifact_path=paths["fit"],
        manifest_path=paths["manifest"],
        staging_root=paths["staging"],
        output_path=paths["output"],
        allow_dirty_tree=True,
    )


def test_the_real_contract_records_the_run_as_executed_and_void() -> None:
    """The arrays were latencies, so a model of amplitude was scored against the wrong thing."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["values_opened"] is True
    record = contract["execution_record"]
    assert record["verdict_in_the_artifact"] == "FAILED"
    assert record["corrected_verdict"] == "VOID"
    identification = record["identification"]
    assert "LATENCY" in identification["what_the_arrays_actually_hold"]
    assert "20.000000" in identification["what_the_arrays_actually_hold"]
    assert "5.000000" in identification["what_the_arrays_actually_hold"]
    # The check that was missing has to be named so the next contract carries one.
    missing = identification["the_check_that_would_have_caught_it_and_was_not_registered"]
    assert "frequency-independent" in missing
    assert "internal consistency check" in missing
    # And no candidate may be reported as refuted by it.
    assert record["no_refitting"].startswith("Nothing was refitted")
    void = record["consequence"]["the_verdict_is_void_not_a_refutation"]
    assert "not a refutation of the candidates" in void
    assert "scored against latency" in void


def test_the_corpus_is_recorded_as_holding_no_train_amplitude_series() -> None:
    """The position the void exposed: a different dataset is needed, not a different contract."""
    reservations = json.loads(
        (REPO / "configs/datasets/stage2-reservations-v1.json").read_text(encoding="utf-8")
    )
    statement = reservations["the_corpus_holds_no_orn_to_pn_train_amplitude_series"]
    assert "No train amplitude series exists anywhere in it" in statement
    assert "cannot be measured from this corpus" in statement
    entry = next(
        row
        for dataset in reservations["datasets"]
        for row in dataset.get("files", [])
        if row["path"].endswith("Fig3E_and_F.mat")
    )
    assert entry["role"].startswith("CORRECTED 2026-09-10")
    assert "LATENCY" in entry["role"]
    assert "superseded_role" in entry
    assert "amplitude" in entry["superseded_role"]
    assert entry["scoreable"].startswith("No.")


def test_the_registry_records_the_void_and_still_claims_no_tier() -> None:
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.2.json").read_text(encoding="utf-8")
    )
    assert registry["the_train_experiment_was_void"]["verdict"] == "VOID"
    assert registry["the_train_experiment_was_void"][
        "no_candidate_is_refuted_or_supported_by_it"
    ] is True
    assert "No validation tier is awarded" in registry["validation_status"]
    # The status has since moved from "no holdout left" to "refuted": the 7 Hz check
    # needed no new data, which withdrew the procurement claim.
    assert "REFUTED as of 2026-09-10" in registry["validation_status"]
    assert "needs no data the project does not already hold" in registry["validation_status"]


def test_the_margins_in_the_module_and_the_contract_agree() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in contract["hypotheses"]}
    assert str(R1_MARGIN) in by_id["R1"]["criterion"]
    assert str(R2_MARGIN) in by_id["R2"]["criterion"]
    assert by_id["R1"]["primary"] is True
    assert by_id["R2"]["primary"] is True
    assert by_id["R3"]["primary"] is False
    assert "PASS if and only if R1 identifies a winner and R2 is passed" in (
        contract["acceptance"]["verdict_rule"]
    )


def test_the_primary_normalisation_divides_the_cohort_mean_by_its_own_first_pulse() -> None:
    trajectory = [1.0, 0.8, 0.6, 0.5, 0.45]
    block = _cohort(trajectory, animals=9)
    summary = _normalise(block)
    assert summary["animals_supplied"] == 9
    assert summary["pulses"] == 5
    assert summary["primary_normalised_trajectory"][0] == pytest.approx(1.0)
    for index, value in enumerate(trajectory):
        assert summary["primary_normalised_trajectory"][index] == pytest.approx(
            value / trajectory[0], rel=1e-9
        )
    # Magnitudes are taken, so a negative-current array normalises positive.
    assert all(value > 0 for value in summary["primary_normalised_trajectory"])


def test_a_non_finite_entry_drops_that_animal_at_that_pulse_only() -> None:
    block = _cohort([1.0, 0.8, 0.6], animals=6)
    block[0, 1] = np.nan
    summary = _normalise(block)
    assert summary["finite_animals_per_pulse"] == [6, 5, 6]
    assert summary["all_nan_rows"] == 0
    block[2, :] = np.nan
    summary = _normalise(block)
    assert summary["all_nan_rows"] == 1
    assert summary["animals_excluded_from_the_secondary_normalisation"] == 1


def test_the_first_pulse_is_excluded_from_the_error_because_it_is_one_by_construction() -> None:
    observed = [1.0, 0.8, 0.6]
    errors = [0.0, 0.1, 0.1]
    total, scored = _weighted_error([1.0, 0.9, 0.5], observed, errors)
    assert scored == 2
    assert total == pytest.approx(1.0 + 1.0)
    # A model that is wrong at the first pulse cannot be penalised or rewarded for it.
    other, _ = _weighted_error([5.0, 0.9, 0.5], observed, errors)
    assert other == pytest.approx(total)


def test_a_cohort_matching_one_candidate_exactly_separates_the_two(tmp_path: Path) -> None:
    """The fixture cohort is candidate A's own trajectory, so A must win R1 and pass R2."""
    result = _run(_environment(tmp_path))
    r1 = result["hypotheses"]["R1"]
    assert r1["verdict"] == "SEPARATED"
    assert r1["winner"] == "candidate_A_two_timescale_facilitation_free"
    assert r1["ratio"] < R1_MARGIN
    assert result["hypotheses"]["R2"]["verdict"] == "PASSED"
    assert result["verdict"] == "PASSED"
    # And the refuted predecessor must be a strong null on this observable.
    check = result["hypotheses"]["degenerate_outcome_checks"]["D_R2_is_the_null_strong"]
    assert check["the_null_is_strong"] is True


def test_two_indistinguishable_curves_give_no_verdict(tmp_path: Path) -> None:
    """D-R1: if the frozen curves never exceed the cohort error, nothing is separable."""
    paths = _environment(tmp_path)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    models = contract["frozen_predictions"]["models"]
    # Make the second candidate identical to the first, parameters and trajectories alike.
    models["candidate_B_facilitation_depression"] = json.loads(
        json.dumps(models["candidate_A_two_timescale_facilitation_free"])
    )
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    result = _run(paths)
    assert result["hypotheses"]["R1"]["verdict"] == "NO VERDICT"
    assert result["hypotheses"]["R2"]["verdict"] == "NOT SCORED"
    assert result["verdict"] == "NO VERDICT"


def test_only_the_four_control_arrays_are_opened(tmp_path: Path) -> None:
    result = _run(_environment(tmp_path))
    opened = result["unsealing"]["variables_opened"]
    assert len(opened) == 4
    assert all(name.endswith("_control") for name in opened)
    assert not any("RNAi" in name for name in opened)
    assert set(result["cohorts"]) == set(TRAINS)


def test_the_unknown_overlap_classification_travels_into_the_artifact(tmp_path: Path) -> None:
    result = _run(_environment(tmp_path))
    assert result["subject_independence_classification"] == "UNKNOWN-OVERLAP"
    assert "FAILURE is stronger" in result["what_that_classification_means_for_this_result"]


def test_a_second_pass_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["values_opened"] = True
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="second look at the same holdout"):
        _run(paths)


def test_the_wrong_fit_artifact_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path)
    paths["fit"].write_text(json.dumps({"fit_set": {"changed": True}}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="not the one this contract froze from"):
        _run(paths)


def test_a_frozen_trajectory_that_no_longer_reproduces_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    trajectory = contract["frozen_predictions"]["models"][
        "candidate_A_two_timescale_facilitation_free"
    ]["by_frequency"]["10Hz"]["trajectory"]
    trajectory[7] += 0.01
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="no longer reproduces"):
        _run(paths)


def test_a_train_array_duplicating_spent_data_is_refused(tmp_path: Path) -> None:
    """The guard added after a holdout turned out to be bit-identical to the fit set."""
    paths = _environment(tmp_path)
    # Give Fig3D a byte-identical copy of one of the train arrays.
    train_bytes = paths["train"].read_bytes()
    paths["fig3d"].write_bytes(train_bytes)
    with pytest.raises(ConfigurationError, match="stores the same arrays as the spent"):
        _run(paths)


def test_a_file_whose_bytes_drifted_from_the_reservation_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path)
    arrays = {
        f"all_flies_{label}_control": _cohort([0.5] * pulses)
        for label, pulses in TRAINS.items()
    }
    paths["train"].write_bytes(_mat_file(arrays))
    with pytest.raises(ConfigurationError, match="has changed since it was reserved"):
        _run(paths)


def test_a_pulse_count_that_disagrees_with_the_freeze_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    row = contract["frozen_predictions"]["models"][
        "candidate_A_two_timescale_facilitation_free"
    ]["by_frequency"]["1Hz"]
    row["pulses"] = 31
    row["trajectory"] = row["trajectory"][:31]
    for other in ("candidate_B_facilitation_depression", "null_1_nd06_v0_1_depression_only"):
        entry = contract["frozen_predictions"]["models"][other]["by_frequency"]["1Hz"]
        entry["pulses"] = 31
        entry["trajectory"] = entry["trajectory"][:31]
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="the contract froze"):
        _run(paths)


def test_the_corpus_claim_carries_its_own_qualification() -> None:
    """The strongest closing claim of the session, checked and then qualified.

    "No train amplitude series exists anywhere in this corpus" was asserted from one
    figure directory. A whole-repository structure audit confirmed it for the 61 files
    that could be read and found five that could not, so the claim covers 61 of 66 files.
    The qualification has to travel with the claim or the next reader inherits the
    unqualified version.
    """
    reservations = json.loads(
        (REPO / "configs/datasets/stage2-reservations-v1.json").read_text(encoding="utf-8")
    )
    audit = reservations["whole_repository_structure_audit_2026_09_10"]
    assert audit["files_examined"] == 66
    assert audit["files_read_successfully"] == 61
    assert len(audit["the_five_unreadable_files"]) == 5
    assert "61 of 66 files and not about the repository" in (
        audit["the_qualification_that_must_travel_with_it"]
    )
    # The reader defect must be recorded as ours rather than blamed on the data.
    defect = audit["a_defect_in_the_project_reader_not_in_the_data"]
    assert "limitation of" in defect
    assert "not a property of the files" in defect
    # And the registry must not repeat the unqualified version.
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.2.json").read_text(encoding="utf-8")
    )
    qualified = registry["the_train_experiment_was_void"][
        "the_corpus_claim_and_its_qualification"
    ]
    assert "61 of 66 files" in qualified
    assert "open question rather than as a conclusion" in qualified


def test_the_joint_holdout_passed_and_the_guards_that_make_it_mean_something() -> None:
    """The project's first passed dynamical validation, and why it is not an artefact."""
    contract = json.loads(
        (REPO / "configs/experiments/stage2-stp-joint-holdout-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["values_opened"] is True
    record = contract["execution_record"]
    assert record["verdict"] == "PASSED"
    assert "31 of 31" in record["results"]["J1_prediction_inside_the_measurement_error"]
    assert "factor of ten" in record["results"]["J2_beats_the_refuted_predecessor"]
    guards = record["the_guards_that_ran_and_what_each_established"]
    # Four guards, each answering a failure this session actually had.
    assert "duplicates none of" in guards["duplicate_array_digest"]
    assert "1e-6" in guards["frozen_trajectory_rederivation"]
    assert "latency arrays were scored as amplitudes" in guards["internal_consistency_check"]
    # And the null must not pass J1, or J1 discriminates nothing.
    assert "0.581" in guards["degeneracy_check_on_J1"]
    assert "J1 discriminates" in guards["degeneracy_check_on_J1"]


def test_the_pass_carries_its_limits_and_does_not_overclaim() -> None:
    """A pass is worth what it is worth. The record has to say so in the same place."""
    contract = json.loads(
        (REPO / "configs/experiments/stage2-stp-joint-holdout-v1.json").read_text(
            encoding="utf-8"
        )
    )
    record = contract["execution_record"]
    # No tier. V1-limited was never a member of flysim.evidence.ValidationTier,
    # and the block that claimed it also argued "it is not V2" from circuit
    # scale, when AGENTS.md defines V2 Synaptic by observable class and names
    # short-term plasticity in it.
    assert record["the_tier_it_earns"]["tier"] is None
    assert "V2 Synaptic" in record["the_tier_it_earns"]["which_tier_this_would_fall_under"]
    assert "it_is_not_V2" not in record["the_tier_it_earns"]
    limits = " ".join(record["what_it_does_not_establish"])
    for phrase in (
        "another laboratory",
        "7 Hz",
        "edge sign",
        "release-probability incompatibility",
        "Developmental invariance",
    ):
        assert phrase in limits, phrase
    # The day-0 cohort genuinely differs from the fit set, and that must be disclosed
    # in the same record rather than left for a reader to notice.
    caveat = record["the_honest_caveat_on_the_day_0_difference"]
    assert "0.555" in caveat and "0.703" in caveat
    assert "between the two" in caveat
    # The two models are not separated and neither may be preferred.
    assert "separates nothing" in record["results"]["J4_the_two_frozen_models_are_not_separated"]


def test_the_v0_3_registry_records_the_tier_and_the_open_problems() -> None:
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.3.json").read_text(encoding="utf-8")
    )
    assert registry["tier"] is None
    assert registry["tier_record"]["tier"] is None
    assert registry["validation"]["verdict"] == "PASSED"
    # What changed from the refuted predecessors has to be stated mechanistically.
    assert "7096 ms" in registry["supersedes"]["what_changed"]
    assert "cannot constrain" in registry["supersedes"]["what_changed"]
    # And the open problems must survive the pass rather than be quietly dropped.
    problems = " ".join(registry["open_problems_this_does_not_touch"])
    assert "release-probability incompatibility" in problems
    assert "0.195" in problems
    assert "edge sign" in problems
    separation = registry["the_two_are_not_separated"]
    assert "Neither the fit set nor the holdout can choose between them" in separation
    assert "prefer the secondary" in separation
    # Nothing is wired into a runner yet and the file must say so.
    assert "not implemented" in registry["engine_coverage"]["numpy_circuit_runner"]


def test_the_audit_is_attached_to_both_the_contract_and_the_registry() -> None:
    """A pass carries its audit in the same files, or the audit is decoration."""
    for name in (
        "configs/experiments/stage2-stp-joint-holdout-v1.json",
        "configs/neural/short-term-plasticity-v0.3.json",
    ):
        record = json.loads((REPO / name).read_text(encoding="utf-8"))["independent_audit"]
        assert record["verdict"] == "VALIDATED WITH NARROWER CLAIM"
        # The arithmetic was not what the audit disputed, and that must stay on record.
        assert "reproduce exactly" in record["the_verdict_stands_as_computed"]


def test_the_audit_records_that_a_model_free_baseline_clears_the_criteria() -> None:
    """The single finding that caps what the pass is worth."""
    record = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.3.json").read_text(encoding="utf-8")
    )["independent_audit"]
    finding = record["finding_1_the_criteria_do_not_separate_the_model_from_a_model_free_baseline"]
    table = finding["the_table"]
    # Fig3B's own mean trajectory carries no mechanism and clears both bars.
    weighted_sse, ratio, inside = table["fig3b_training_cohort_empirical_mean"][:3]
    assert inside / 31 >= 0.80, "the baseline passes J1"
    assert ratio <= 0.5, "the baseline passes J2"
    # And it must be beaten by the model, which is a margin and not a passed test.
    assert table["v0_3_primary"][0] < weighted_sse
    assert "may not be claimed" in finding["what_it_costs_the_claim"]
    # The noise floor has to be stated: passing J1 means sitting inside the error bars.
    assert table["mean_standard_error_across_the_31_pulses"] > table["v0_3_primary"][3]


def test_the_audit_corrects_the_goodness_of_fit_and_the_error_bars() -> None:
    record = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.3.json").read_text(encoding="utf-8")
    )["independent_audit"]
    gof = record["finding_2_the_goodness_of_fit_p_is_invalid_as_reported"]
    structure = gof["measured_correlation_structure_bootstrap_over_animals_b_20000"]
    assert structure["participation_ratio"] < 31, "31 pulses are not 31 independent checks"
    assert structure["kish_effective_points"] < 10
    assert "does not survive" in gof["the_corrected_statement"]
    # The frozen numbers stay put; the correction travels beside them.
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.3.json").read_text(encoding="utf-8")
    )
    assert registry["primary_rule"]["degrees_of_freedom"] == 32
    assert "left in place" in gof["where_the_wrong_number_appears"]
    bars = record["finding_3_the_registered_error_bars_are_too_wide"]
    assert bars["does_the_verdict_survive"].startswith("Yes")


def test_the_audit_downgrades_the_independence_claim_and_discloses_fig3h() -> None:
    record = json.loads(
        (REPO / "configs/experiments/stage2-stp-joint-holdout-v1.json").read_text(
            encoding="utf-8"
        )
    )["independent_audit"]
    finding = record["finding_4_the_independence_claim_overstates_what_is_established"]
    classification = finding["the_classification_the_audit_returns"]
    against_fit = classification["against_the_fitting_cohorts_fig3b_and_fig3d"]
    assert "PROBABLE, NOT ESTABLISHED" in against_fit
    assert "SAME SUBJECTS, DIFFERENT PROTOCOL" in classification[
        "against_everything_opened_before_the_freeze"
    ]
    # The undisclosed pre-freeze opening has to be named, not softened.
    disclosure = finding["the_disclosure_the_contract_should_have_carried"]
    assert "Fig3H" in disclosure and "before this contract" in disclosure
    assert "should have been" in disclosure
    # And the coincidence that looked alarming must be recorded as discarded, with why.
    assert "digitisation" in finding["one_red_flag_checked_and_discarded"]


def test_neither_frozen_rule_is_promoted() -> None:
    """The one independent observable favours the secondary; the file must not hide that."""
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.3.json").read_text(encoding="utf-8")
    )
    note = registry["neither_rule_is_promoted"]
    assert "No consumer of this file may treat the primary as preferred" in note
    assert "0.532" in note and "0.195" in note
    assert registry["tier"] is None, "there was never a tier for the audit to narrow"
    assert "model-free baseline" in registry["tier_after_audit"]


def test_the_corpus_inventory_is_closed_and_says_what_ran_out() -> None:
    """66 of 66 files, and the consequence stated rather than left for a reader."""
    manifest = json.loads(
        (REPO / "configs/datasets/stage2-reservations-v1.json").read_text(encoding="utf-8")
    )
    closed = manifest["the_five_unreadable_files_closed_2026_09_10"]
    assert len(closed["what_each_of_the_five_actually_holds"]) == 5
    assert "66 of 66" in closed["the_qualification_is_withdrawn"]
    # The reader defect is explained now, not merely recorded.
    assert "table" in closed["the_reader_defect_is_now_explained_not_merely_recorded"]
    inventory = manifest["orn_to_pn_train_amplitude_inventory_2026_09_10"]
    arrays = inventory["every_orn_to_pn_1hz_train_amplitude_array_in_the_corpus"]
    spent = [k for k, v in arrays.items() if v["status"].startswith("SPENT")]
    sealed = [k for k, v in arrays.items() if v["status"].startswith("SEALED")]
    assert len(spent) == 2 and all("wild type" in k for k in spent)
    assert len(sealed) == 3 and all("RNAi" in k for k in sealed)
    # The hard boundary has to be explicit: no wild-type train left, nothing above 1 Hz.
    consequence = inventory["the_consequence_that_matters"]
    assert "no unspent wild-type" in consequence
    assert "other than 1 Hz" in consequence
    assert "cannot be settled with Rozenfeld data" in consequence
