# SPDX-License-Identifier: GPL-2.0-or-later
"""The scoring path that opens sealed data, checked entirely against fixtures.

Nothing in this file touches the Rozenfeld corpus. The point of the tests is that when
the real run does open it, it opens one named array at a time, refuses a file whose bytes
have drifted from the reserved checksum, and computes an interval from a t quantile that
matches published critical values rather than one this project invented.
"""

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flysim.depression_score import (
    ALL_INTERVALS_MS,
    HALF_WIDTH_LIMIT,
    PRIMARY_INTERVAL_MS,
    STAGES,
    run_depression_external_test,
    summarise,
    t_quantile,
    variable_for,
)
from flysim.errors import ConfigurationError
from flysim.reservations import read_mat_variable

_MI_INT8 = 1
_MI_INT32 = 5
_MI_UINT32 = 6
_MI_DOUBLE = 9
_MI_MATRIX = 14
_MI_COMPRESSED = 15
_MX_DOUBLE = 6


def _pad(blob: bytes) -> bytes:
    return blob + b"\x00" * (-len(blob) % 8)


def _element(element_type: int, data: bytes) -> bytes:
    return struct.pack("<II", element_type, len(data)) + _pad(data)


def _small_element(element_type: int, data: bytes) -> bytes:
    """The compact form MATLAB uses for a payload of four bytes or fewer."""
    assert len(data) <= 4
    return struct.pack("<I", (len(data) << 16) | element_type) + data.ljust(4, b"\x00")


def _matrix(name: str, dimensions: tuple[int, ...], values: list[float]) -> bytes:
    name_element = (
        _small_element(_MI_INT8, name.encode("ascii"))
        if len(name) <= 4
        else _element(_MI_INT8, name.encode("ascii"))
    )
    body = (
        _element(_MI_UINT32, struct.pack("<II", _MX_DOUBLE, 0))
        + _element(_MI_INT32, struct.pack(f"<{len(dimensions)}i", *dimensions))
        + name_element
        + _element(_MI_DOUBLE, struct.pack(f"<{len(values)}d", *values))
    )
    return _element(_MI_MATRIX, body)


def _mat_file(elements: list[bytes]) -> bytes:
    header = b"MATLAB 5.0 MAT-file, hand-built fixture".ljust(124, b" ")
    header += struct.pack("<H", 0x0100) + b"IM"
    return header + b"".join(elements)


@pytest.fixture
def paired_pulse_file(tmp_path: Path) -> Path:
    """A stand-in shaped like the real one: one ratio per animal, five intervals."""
    path = tmp_path / "Fig3D-fixture.mat"
    elements = []
    for index, interval in enumerate(ALL_INTERVALS_MS):
        values = [0.60 + 0.05 * index + 0.01 * animal for animal in range(6)]
        elements.append(
            _element(
                _MI_COMPRESSED,
                zlib.compress(_matrix(variable_for(interval), (6, 1), values)),
            )
        )
    # A neighbouring array the run must never touch, and a short name to exercise the
    # compact name-tag form.
    elements.append(_element(_MI_COMPRESSED, zlib.compress(_matrix("rnai", (6, 1), [9.9] * 6))))
    path.write_bytes(_mat_file(elements))
    return path


def test_one_named_variable_comes_back_and_the_others_do_not(paired_pulse_file: Path) -> None:
    opened = read_mat_variable(paired_pulse_file, variable_for(100.0))
    assert opened.shape == (6, 1)
    assert opened[0, 0] == pytest.approx(0.70)
    # Nothing about the neighbouring array is returned by that call.
    assert float(opened.max()) < 1.0


def test_a_short_variable_name_in_the_compact_tag_form_is_read(paired_pulse_file: Path) -> None:
    opened = read_mat_variable(paired_pulse_file, "rnai")
    assert opened.shape == (6, 1)
    assert opened[0, 0] == pytest.approx(9.9)


def test_a_misspelled_variable_raises_rather_than_reading_a_neighbour(
    paired_pulse_file: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="no variable named"):
        read_mat_variable(paired_pulse_file, "new_all_flies_PP_100ms_controls")


def test_an_empty_name_is_refused(paired_pulse_file: Path) -> None:
    with pytest.raises(ConfigurationError, match="needs the name"):
        read_mat_variable(paired_pulse_file, "")


def test_column_major_order_is_respected(tmp_path: Path) -> None:
    path = tmp_path / "order.mat"
    path.write_bytes(_mat_file([_matrix("m", (2, 3), [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])]))
    opened = read_mat_variable(path, "m")
    # MATLAB stores columns first, so the flat sequence 1..6 is [[1,3,5],[2,4,6]].
    assert opened.tolist() == [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0]]


def test_the_t_quantile_matches_published_critical_values() -> None:
    # Two-sided 95 percent critical values from a standard table.
    for degrees, expected in (
        (1, 12.7062),
        (2, 4.3027),
        (5, 2.5706),
        (10, 2.2281),
        (19, 2.0930),
        (21, 2.0796),
        (30, 2.0423),
        (100, 1.9840),
    ):
        assert t_quantile(degrees=degrees) == pytest.approx(expected, abs=5e-4)


def test_the_quantile_refuses_impossible_inputs() -> None:
    with pytest.raises(ConfigurationError, match="degree of freedom"):
        t_quantile(degrees=0)
    with pytest.raises(ConfigurationError, match="two-sided alpha"):
        t_quantile(degrees=10, two_sided_alpha=0.0)


def test_the_summary_reports_what_it_dropped_and_a_checkable_interval() -> None:
    values = np.array([[0.8], [0.9], [np.nan], [1.0], [1.1]])
    summary = summarise(values)
    assert summary["animals_supplied"] == 5
    assert summary["animals_scored"] == 4
    assert summary["animals_excluded_non_finite"] == 1
    assert summary["mean"] == pytest.approx(0.95)
    assert summary["standard_deviation"] == pytest.approx(0.1290994, abs=1e-6)
    # mean +/- t(3) * sd / sqrt(4)
    assert summary["ci95_half_width"] == pytest.approx(
        t_quantile(degrees=3) * summary["standard_deviation"] / 2.0, rel=1e-9
    )
    assert summary["ci95_low"] < summary["mean"] < summary["ci95_high"]


def test_a_cohort_of_one_cannot_be_summarised() -> None:
    with pytest.raises(ConfigurationError, match="at least two finite"):
        summarise(np.array([[0.8], [np.nan]]))


def test_the_stages_open_one_interval_and_then_five() -> None:
    assert STAGES["primary"] == (PRIMARY_INTERVAL_MS,)
    assert STAGES["intervals"] == ALL_INTERVALS_MS
    assert len(STAGES["primary"]) == 1
    assert PRIMARY_INTERVAL_MS in STAGES["intervals"]


def test_the_variable_names_are_the_ones_the_contract_names() -> None:
    contract = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "experiments"
            / "stage2-depression-external-test-v1.json"
        ).read_text(encoding="utf-8")
    )
    declared = set(contract["data"]["primary_source"]["variables"])
    assert {variable_for(interval) for interval in ALL_INTERVALS_MS} == declared
    assert variable_for(1000.0) == "new_all_flies_PP_1000ms_control"
    with pytest.raises(ConfigurationError, match="not a preregistered interval"):
        variable_for(50.0)


def _fixture_environment(tmp_path: Path, source: Path) -> dict[str, Path]:
    from flysim.datasets import sha256_file

    relative = source.name
    manifest = {
        "datasets": [
            {
                "id": "fixture",
                "files": [
                    {
                        "path": relative,
                        "sha256": sha256_file(source),
                        "reserved_names": [variable_for(i) for i in ALL_INTERVALS_MS],
                    }
                ],
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    contract: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": "fixture-contract",
        "values_opened": False,
        "assumption_ids": ["ND-06"],
        "prediction_grid": {"rule_id": "orn-to-uniglomerular-pn"},
        "data": {
            "primary_source": {
                "file": relative,
                "variables": [variable_for(i) for i in ALL_INTERVALS_MS],
            }
        },
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return {"manifest": manifest_path, "contract": contract_path}


def test_an_unknown_stage_is_refused(tmp_path: Path, paired_pulse_file: Path) -> None:
    paths = _fixture_environment(tmp_path, paired_pulse_file)
    with pytest.raises(ConfigurationError, match="Unknown stage"):
        run_depression_external_test(
            stage="everything",
            contract_path=paths["contract"],
            registry_path=Path("unused"),
            manifest_path=paths["manifest"],
            staging_root=paired_pulse_file.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_a_file_whose_bytes_drifted_from_the_reservation_is_refused(
    tmp_path: Path, paired_pulse_file: Path
) -> None:
    paths = _fixture_environment(tmp_path, paired_pulse_file)
    # Same shape, different values: exactly the case a checksum catches and a shape check
    # would not.
    paired_pulse_file.write_bytes(
        _mat_file(
            [
                _element(
                    _MI_COMPRESSED,
                    zlib.compress(_matrix(variable_for(i), (6, 1), [0.5] * 6)),
                )
                for i in ALL_INTERVALS_MS
            ]
        )
    )
    with pytest.raises(ConfigurationError, match="has changed since it was reserved"):
        run_depression_external_test(
            stage="primary",
            contract_path=paths["contract"],
            registry_path=Path("unused"),
            manifest_path=paths["manifest"],
            staging_root=paired_pulse_file.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_a_contract_that_records_its_values_as_open_refuses_a_second_pass(
    tmp_path: Path, paired_pulse_file: Path
) -> None:
    paths = _fixture_environment(tmp_path, paired_pulse_file)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["values_opened"] = True
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="second look at the same holdout"):
        run_depression_external_test(
            stage="primary",
            contract_path=paths["contract"],
            registry_path=Path("unused"),
            manifest_path=paths["manifest"],
            staging_root=paired_pulse_file.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_a_stage_cannot_open_a_variable_the_contract_does_not_name(
    tmp_path: Path, paired_pulse_file: Path
) -> None:
    paths = _fixture_environment(tmp_path, paired_pulse_file)
    contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
    contract["data"]["primary_source"]["variables"] = [variable_for(10.0)]
    paths["contract"].write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="does not name"):
        run_depression_external_test(
            stage="primary",
            contract_path=paths["contract"],
            registry_path=Path("unused"),
            manifest_path=paths["manifest"],
            staging_root=paired_pulse_file.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_the_half_width_rule_is_the_registered_one() -> None:
    contract = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "experiments"
            / "stage2-depression-external-test-v1.json"
        ).read_text(encoding="utf-8")
    )
    primary = next(item for item in contract["hypotheses"] if item["id"] == "H1")
    assert str(HALF_WIDTH_LIMIT) in primary["degenerate_outcome_check"]
    assert "NO VERDICT" in primary["degenerate_outcome_check"]
