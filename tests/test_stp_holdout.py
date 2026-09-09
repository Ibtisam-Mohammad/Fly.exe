# SPDX-License-Identifier: GPL-2.0-or-later
"""The scorer that opens the sealed developmental cohorts, checked entirely on fixtures.

Nothing here touches the Rozenfeld corpus. What is tested is that when the real run does
open it, it refuses a drifted file, refuses a second pass, refuses a fit artifact that is
not the one the models were frozen from, refuses a frozen model whose recorded prediction
no longer reproduces, and computes A1, A2 and A3 the way the committed contract says.
"""

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError
from flysim.stp_families import paired_pulse
from flysim.stp_holdout import (
    A1_HALF_WIDTH_LIMIT,
    A1_MAX_MISSES,
    A1_MINIMUM_SCORABLE,
    A2_RESIDUAL_RATIO_LIMIT,
    A3_MINIMUM_AGREEMENTS,
    SEPARABILITY_LIMIT,
    run_stp_developmental_holdout,
)

REPO = Path(__file__).resolve().parents[1]
INTERVALS = (10.0, 30.0, 100.0, 300.0, 1000.0)
CONTRACT = REPO / "configs/experiments/stage2-stp-developmental-holdout-v1.json"

_MI_INT8, _MI_INT32, _MI_UINT32, _MI_DOUBLE = 1, 5, 6, 9
_MI_MATRIX, _MI_COMPRESSED, _MX_DOUBLE = 14, 15, 6


def _element(element_type: int, data: bytes) -> bytes:
    return struct.pack("<II", element_type, len(data)) + data + b"\x00" * (-len(data) % 8)


def _matrix(name: str, values: list[float]) -> bytes:
    body = (
        _element(_MI_UINT32, struct.pack("<II", _MX_DOUBLE, 0))
        + _element(_MI_INT32, struct.pack("<2i", len(values), 1))
        + _element(_MI_INT8, name.encode("ascii"))
        + _element(_MI_DOUBLE, struct.pack(f"<{len(values)}d", *values))
    )
    return _element(_MI_MATRIX, body)


def _mat_file(cohort: dict[float, list[float]]) -> bytes:
    header = b"MATLAB 5.0 MAT-file, hand-built fixture".ljust(124, b" ")
    header += struct.pack("<H", 0x0100) + b"IM"
    elements = [
        _element(
            _MI_COMPRESSED,
            zlib.compress(_matrix(f"new_all_flies_PP_{interval:g}ms_control", values)),
        )
        for interval, values in cohort.items()
    ]
    return header + b"".join(elements)


def _spread(mean: float, count: int, spread: float) -> list[float]:
    """A cohort with the requested mean and a controllable, symmetric spread."""
    step = spread / max(count - 1, 1)
    offsets = [(index - (count - 1) / 2.0) * step for index in range(count)]
    return [mean + offset for offset in offsets]


FROZEN = ("two-timescale-facilitation", (2.5655, 0.3701, 105.959, 0.1013))
OTHER = ("facilitation-depression", (0.00686, 0.07405, 31.0426, 20000.0))


def _model(family_id: str, theta: tuple[float, ...]) -> dict[str, Any]:
    from flysim.stp_families import family

    return {
        "family_id": family_id,
        "parameters": dict(zip(family(family_id).parameter_names, theta, strict=True)),
        "predicted": [
            {"interval_ms": interval, "predicted": paired_pulse(family_id, theta, interval)}
            for interval in INTERVALS
        ],
    }


def _environment(
    tmp_path: Path,
    *,
    primary_means: dict[float, float],
    secondary_means: dict[float, float] | None = None,
    spread: float = 0.30,
    count: int = 22,
    with_secondary_model: bool = True,
    flat_level: float = 1.0,
    primary_duplicates_the_spent_file: bool = False,
) -> dict[str, Path]:
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    # The spent file the guard checks candidates against. Its numbers are deliberately
    # unlike any cohort's unless a test asks for the duplicate case.
    spent_path = staging / "spent.mat"
    spent_body = _mat_file(
        {interval: _spread(0.123, 19, 0.05) for interval in INTERVALS}
    )
    spent_path.write_bytes(spent_body)
    files: dict[str, Path] = {}
    for role, means in (
        ("primary", primary_means),
        ("secondary", secondary_means or primary_means),
    ):
        path = staging / f"{role}.mat"
        if role == "primary" and primary_duplicates_the_spent_file:
            path.write_bytes(spent_body)
        else:
            path.write_bytes(
                _mat_file(
                    {
                        interval: _spread(mean, count, spread)
                        for interval, mean in means.items()
                    }
                )
            )
        files[role] = path
    files["spent"] = spent_path
    variables = [f"new_all_flies_PP_{interval:g}ms_control" for interval in INTERVALS]
    manifest = {
        "datasets": [
            {
                "id": "fixture",
                "files": [
                    {"path": path.name, "sha256": sha256_file(path), "reserved_names": variables}
                    for path in files.values()
                ],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fit_artifact = tmp_path / "fit.json"
    fit_artifact.write_text(
        json.dumps(
            {
                "fit_set": {
                    "by_interval": [
                        {
                            "interval_ms": interval,
                            "mean": 1.0,
                            "standard_error": 0.05,
                            "ci95_half_width": 0.10,
                        }
                        for interval in INTERVALS
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    contract = {
        "schema_version": "1.0",
        "experiment_id": "fixture-holdout",
        "values_opened": False,
        "assumption_ids": ["ND-06"],
        "depends_on": {
            "fit_artifact_sha256": sha256_file(fit_artifact),
            "spent_arrays": [
                {
                    "file": files["spent"].name,
                    "variables": variables,
                    "why_it_is_spent": "the fixture's stand-in for the fit set",
                }
            ],
        },
        "the_cohorts": {
            "primary": {
                "file": files["primary"].name,
                "variables": variables,
                "cohort": "fixture day 1",
            },
            "secondary": {
                "file": files["secondary"].name,
                "variables": variables,
                "cohort": "fixture day 0",
            },
        },
        "frozen_models": {
            "primary": _model(*FROZEN),
            "secondary": _model(*OTHER) if with_secondary_model else None,
            "flat_null": {"family_id": "flat-null", "level": flat_level},
        },
        "acceptance": {
            "verdict_rule": "A1 and A2",
            "what_a_pass_would_establish": "x",
            "what_a_pass_would_not_establish": "y",
            "no_refitting": "z",
        },
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return {
        "contract": contract_path,
        "fit": fit_artifact,
        "manifest": manifest_path,
        "staging": staging,
        "output": tmp_path / "out.json",
        "primary_file": files["primary"],
    }


def _run(paths: dict[str, Path]) -> dict[str, Any]:
    return run_stp_developmental_holdout(
        contract_path=paths["contract"],
        fit_artifact_path=paths["fit"],
        manifest_path=paths["manifest"],
        staging_root=paths["staging"],
        output_path=paths["output"],
        allow_dirty_tree=True,
    )


def test_the_thresholds_in_the_module_and_the_contract_agree() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in contract["hypotheses"]}
    assert str(A1_MAX_MISSES) in by_id["A1"]["criterion"] or "one miss" in by_id["A1"]["criterion"]
    assert str(A1_HALF_WIDTH_LIMIT) in by_id["A1"]["degenerate_outcome_check"]
    assert str(A1_MINIMUM_SCORABLE) in by_id["A1"]["degenerate_outcome_check"].replace(
        "four", "4"
    )
    assert str(A2_RESIDUAL_RATIO_LIMIT) in by_id["A2"]["criterion"].replace("half", "0.5")
    assert str(A3_MINIMUM_AGREEMENTS) in by_id["A3"]["criterion"].replace("three", "3")
    assert str(SEPARABILITY_LIMIT) in contract["the_secondary_model_is_scored_and_awards_nothing"][
        "degenerate_outcome_check"
    ]


def test_the_contract_names_only_control_arrays_and_records_being_opened_once() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    # Opened on 2026-09-10. The flag is what stops a second scoring pass.
    assert contract["values_opened"] is True
    for role in ("primary", "secondary"):
        variables = contract["the_cohorts"][role]["variables"]
        assert len(variables) == len(INTERVALS)
        assert all(name.endswith("_control") for name in variables)
        assert not any("RNAi" in name for name in variables)
    assert "Fig6D" in contract["the_cohorts"]["excluded"]
    assert "Fig3E_and_F" in contract["the_cohorts"]["excluded"]


def test_a_model_that_lands_on_the_cohort_passes_both_primary_criteria(tmp_path: Path) -> None:
    """The frozen curve reproduced exactly by the cohort: A1 and A2 must both pass."""
    means = {
        interval: paired_pulse(FROZEN[0], FROZEN[1], interval) for interval in INTERVALS
    }
    paths = _environment(tmp_path, primary_means=means, spread=0.20)
    result = _run(paths)
    scores = result["scores"]["primary"]["primary_model"]
    assert scores["A1"]["verdict"] == "PASSED"
    assert scores["A1"]["misses"] == []
    assert scores["A2"]["verdict"] == "PASSED"
    assert scores["A2"]["ratio_model_over_null"] < A2_RESIDUAL_RATIO_LIMIT
    assert result["verdict"] == "PASSED"


def test_a_model_that_misses_every_interval_fails(tmp_path: Path) -> None:
    means = dict.fromkeys(INTERVALS, 0.40)
    paths = _environment(tmp_path, primary_means=means, spread=0.10, flat_level=0.40)
    result = _run(paths)
    scores = result["scores"]["primary"]["primary_model"]
    assert scores["A1"]["verdict"] == "FAILED"
    assert len(scores["A1"]["misses"]) == len(INTERVALS)
    assert result["verdict"] == "FAILED"


def test_one_miss_is_tolerated_and_two_are_not(tmp_path: Path) -> None:
    exact = {interval: paired_pulse(FROZEN[0], FROZEN[1], interval) for interval in INTERVALS}
    one_off = dict(exact)
    one_off[300.0] = exact[300.0] + 0.40
    paths = _environment(tmp_path, primary_means=one_off, spread=0.15)
    assert _run(paths)["scores"]["primary"]["primary_model"]["A1"]["verdict"] == "PASSED"

    two_off = dict(one_off)
    two_off[1000.0] = exact[1000.0] + 0.40
    other = _environment(tmp_path / "second", primary_means=two_off, spread=0.15)
    assert _run(other)["scores"]["primary"]["primary_model"]["A1"]["verdict"] == "FAILED"


def test_a_wide_cohort_is_no_verdict_rather_than_a_pass(tmp_path: Path) -> None:
    """The degenerate outcome A1 exists to catch: an interval wide enough to contain anything."""
    means = dict.fromkeys(INTERVALS, 1.0)
    paths = _environment(tmp_path, primary_means=means, spread=4.0, count=6)
    result = _run(paths)
    scores = result["scores"]["primary"]["primary_model"]
    assert scores["A1"]["verdict"] == "NO VERDICT"
    assert scores["A1"]["intervals_scorable"] < A1_MINIMUM_SCORABLE
    dropped = result["degenerate_outcome_checks"]["D1_underpowered_intervals"]["intervals_dropped"]
    assert len(dropped) == len(INTERVALS)


def test_when_the_flat_null_also_passes_A1_the_verdict_falls_back_to_A2(tmp_path: Path) -> None:
    """D2: a cohort so flat that a constant lands inside every interval."""
    means = dict.fromkeys(INTERVALS, 1.0)
    paths = _environment(tmp_path, primary_means=means, spread=1.0, count=22, flat_level=1.0)
    result = _run(paths)
    check = result["degenerate_outcome_checks"]["D2_the_flat_null_against_A1"]
    assert check["flat_null_A1"] == "PASSED"
    assert check["A1_is_uninformative"] is True
    assert "A2" in result["verdict_note"]
    # The flat null scores zero residual against itself, so nothing can be half of it.
    assert result["scores"]["primary"]["primary_model"]["A2"]["verdict"] == "FAILED"
    assert result["verdict"] == "FAILED"


def test_the_replication_check_fires_when_the_holdout_matches_the_fit_set(tmp_path: Path) -> None:
    """D3: the fixture fit set has mean 1.0 and standard error 0.05 at every interval."""
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0), spread=0.2)
    check = _run(paths)["degenerate_outcome_checks"]["D3_is_this_a_replication_rather_than_a_test"]
    assert check["all_five_within_one_fit_set_standard_error"] is True

    other = _environment(tmp_path / "far", primary_means=dict.fromkeys(INTERVALS, 1.5), spread=0.2)
    far = _run(other)["degenerate_outcome_checks"][
        "D3_is_this_a_replication_rather_than_a_test"
    ]
    assert far["all_five_within_one_fit_set_standard_error"] is False


def test_the_separability_check_reports_whether_the_two_curves_differ(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0), spread=0.2)
    check = _run(paths)["degenerate_outcome_checks"][
        "D4_can_the_holdout_separate_the_two_frozen_models"
    ]
    assert check is not None
    assert check["limit"] == SEPARABILITY_LIMIT
    assert isinstance(check["this_holdout_can_separate_them"], bool)


def test_a_single_frozen_model_leaves_the_separability_check_empty(tmp_path: Path) -> None:
    paths = _environment(
        tmp_path,
        primary_means=dict.fromkeys(INTERVALS, 1.0),
        spread=0.2,
        with_secondary_model=False,
    )
    result = _run(paths)
    assert (
        result["degenerate_outcome_checks"]["D4_can_the_holdout_separate_the_two_frozen_models"]
        is None
    )
    assert "secondary_model" not in result["scores"]["primary"]
    assert result["frozen_models"]["secondary"] is None


def test_both_cohorts_are_opened_and_only_the_named_arrays(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    result = _run(paths)
    for role in ("primary", "secondary"):
        unsealing = result["cohorts"][role]["unsealing"]
        assert unsealing["matches_sealed_manifest"] is True
        assert len(unsealing["variables_opened"]) == len(INTERVALS)
        assert all(name.endswith("_control") for name in unsealing["variables_opened"])


def test_a_contract_that_records_its_values_as_open_refuses_a_second_pass(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["values_opened"] = True
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="second look at the same holdout"):
        _run(paths)


def test_a_contract_with_nothing_frozen_leaves_the_cohorts_sealed(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["frozen_models"]["primary"] = None
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cohorts must stay sealed"):
        _run(paths)


def test_the_wrong_fit_artifact_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    paths["fit"].write_text(json.dumps({"fit_set": {"by_interval": []}}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="not the one this contract froze from"):
        _run(paths)


def test_a_frozen_prediction_that_no_longer_reproduces_is_refused(tmp_path: Path) -> None:
    """The check that catches a simulator that moved between the freeze and the score."""
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["frozen_models"]["primary"]["predicted"][2]["predicted"] += 0.01
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="no longer reproduces"):
        _run(paths)


def test_a_frozen_model_missing_a_parameter_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["frozen_models"]["primary"]["parameters"].pop("utilisation")
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="frozen without"):
        _run(paths)


def test_a_file_whose_bytes_drifted_from_the_reservation_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    paths["primary_file"].write_bytes(
        _mat_file({interval: _spread(0.5, 22, 0.2) for interval in INTERVALS})
    )
    with pytest.raises(ConfigurationError, match="has changed since it was reserved"):
        _run(paths)


def test_a_cohort_that_would_open_an_undeclared_variable_is_refused(tmp_path: Path) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["the_cohorts"]["primary"]["variables"] = ["new_all_flies_PP_10ms_control"]
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="does not name"):
        _run(paths)


def test_the_shape_criterion_counts_adjacent_directions(tmp_path: Path) -> None:
    """A3 with a cohort that rises where the frozen curve falls, and tight intervals."""
    rising = {interval: 0.8 + 0.1 * index for index, interval in enumerate(INTERVALS)}
    paths = _environment(tmp_path, primary_means=rising, spread=0.02, count=22)
    scores = _run(paths)["scores"]["primary"]["primary_model"]
    assert scores["A3"]["verdict"] == "FAILED"
    assert scores["A3"]["agreements"] < A3_MINIMUM_AGREEMENTS
    assert all(row["cohort_intervals_overlap"] is False for row in scores["A3"]["by_comparison"])

def test_a_cohort_that_duplicates_a_spent_one_is_refused_before_it_is_opened(
    tmp_path: Path,
) -> None:
    """The guard added after 2026-09-10, when a holdout turned out to be the fit set.

    Fig3J's five wild-type arrays are bit-identical to Fig3D's, the arrays the models
    were fitted to, and the published legends give both the same animal counts. The
    holdout was preregistered, committed, opened and scored before that was noticed. The
    refusal has to happen before any payload is decoded, which is why the check works on
    the stored element bytes.
    """
    paths = _environment(
        tmp_path,
        primary_means=dict.fromkeys(INTERVALS, 1.0),
        primary_duplicates_the_spent_file=True,
    )
    with pytest.raises(ConfigurationError, match="stores the same arrays as the already-spent"):
        _run(paths)


def test_a_clean_cohort_records_what_the_guard_checked_and_what_it_cannot_prove(
    tmp_path: Path,
) -> None:
    paths = _environment(tmp_path, primary_means=dict.fromkeys(INTERVALS, 1.0))
    result = _run(paths)
    for role in ("primary", "secondary"):
        entry = result["cohorts"][role]["not_a_duplicate_of_a_spent_cohort"]
        assert entry["no_duplicate_found"] is True
        assert entry["checked_against"][0]["duplicate_arrays"] == []
        assert "do not prove unequal data" in entry["what_a_clean_result_does_not_prove"]


def test_the_guard_finds_the_real_duplication_and_clears_the_real_cohort() -> None:
    """Against the actual Rozenfeld files, if they are staged; skipped otherwise.

    This is the one test in the suite that touches the corpus, and it decodes nothing:
    it compares digests of stored element bytes. It is here because the assertion that
    matters is about those specific files.
    """
    import os

    from flysim.reservations import duplicate_arrays

    root = (
        Path(os.environ.get("FLYSIM_DATA_ROOT", "/srv/flybrain-data"))
        / "incoming"
        / "stage2-2026-09-09"
        / "rozenfeld2023-repo"
    )
    figure = root / "Figure 3"
    if not (figure / "Fig3D.mat").is_file():
        pytest.skip("the Rozenfeld corpus is not staged in this environment")
    names = [f"new_all_flies_PP_{interval:g}ms_control" for interval in INTERVALS]
    assert duplicate_arrays(
        candidate=figure / "Fig3J.mat", spent=figure / "Fig3D.mat", names=names
    ) == tuple(names)
    assert (
        duplicate_arrays(
            candidate=figure / "Fig3H.mat", spent=figure / "Fig3D.mat", names=names
        )
        == ()
    )


def test_the_executed_contract_records_the_voiding_rather_than_the_pass() -> None:
    """The artifact says PASSED. The record must say why that does not stand."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["values_opened"] is True
    record = contract["execution_record"]
    superseded = record["the_artifact_records_a_verdict_that_does_not_stand"]
    assert superseded["what_it_says"] == "PASSED"
    assert superseded["the_corrected_verdict"] == "NO VERDICT"
    assert "training set" in superseded["why_it_does_not_stand"]
    # The duplication, how it was discoverable, and the fix must all be on the record.
    duplication = record["the_duplication"]
    assert "bit-identical" in duplication["finding"] or "identical" in duplication["finding"]
    assert "Identical at every interval" in duplication["how_it_was_discoverable_in_advance"]
    assert "duplicate_arrays" in duplication["the_structural_fix"]
    # And the one genuine cohort's registered results, unpromoted.
    genuine = record["what_the_genuine_cohort_returned"]
    assert genuine["A1"]["verdict"] == "NO VERDICT"
    assert genuine["A2"]["verdict"] == "PASSED"
    assert "enter the verdict" in genuine["registered_role"]
    assert "criterion-restatement" in genuine["what_this_cohort_cannot_support"]


def test_the_registry_records_no_verdict_and_claims_no_tier() -> None:
    registry = json.loads(
        (REPO / "configs/neural/short-term-plasticity-v0.2.json").read_text(encoding="utf-8")
    )
    assert registry["holdout"]["verdict"] == "NO VERDICT"
    assert "NO VERDICT" in registry["validation_status"]
    assert "awards no validation tier" in registry["validation_status"]
    forbidden = registry["holdout"]["what_it_may_not_claim"]
    assert any("passed holdout" in entry.lower() for entry in forbidden)
    assert any("validation tier" in entry.lower() for entry in forbidden)
