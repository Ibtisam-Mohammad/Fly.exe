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
