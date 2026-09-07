# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
import json
import pickle
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.errors import DatasetError
from flysim.feeding_stage1 import evaluate_feeding_screen
from flysim.shiu_feeding import (
    load_primitive_population_pickle,
    prepare_shiu_feeding_screen,
    read_xlsx_sheet,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_workbook(path: Path) -> None:
    strings = ["type", "extension", "left", "right", "unused", "alpha", "beta"]
    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    workbook = (
        '<?xml version="1.0"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="screen" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    worksheet = (
        '<?xml version="1.0"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="M1" t="s"><v>2</v></c><c r="N1" t="s"><v>3</v></c>'
        '<c r="T1" t="s"><v>4</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>5</v></c><c r="B2"><v>1</v></c>'
        '<c r="M2"><v>3</v></c><c r="N2"><v>2</v></c></row>'
        '<row r="3"><c r="A3" t="s"><v>6</v></c><c r="B3"><v>0</v></c>'
        '<c r="M3"><v>0</v></c><c r="N3"><v>0</v></c></row>'
        '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{shared}</sst>",
        )
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def test_xlsx_reader_and_primitive_pickle_guard(tmp_path: Path) -> None:
    workbook = tmp_path / "screen.xlsx"
    _write_workbook(workbook)
    rows = read_xlsx_sheet(workbook, "screen")
    assert rows[1][0] == "alpha"
    assert rows[1][12:14] == ["3", "2"]

    population_path = tmp_path / "populations.pickle"
    population_path.write_bytes(pickle.dumps({"alpha": [100], "beta": [200]}))
    assert load_primitive_population_pickle(population_path) == {
        "alpha": (100,),
        "beta": (200,),
    }

    population_path.write_bytes(pickle.dumps(Path("unsafe")))
    with pytest.raises(DatasetError, match="global is forbidden"):
        load_primitive_population_pickle(population_path)


def test_feeding_screen_preparation_preserves_partial_mapping(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "auxiliary" / "shiu-2024-brain-model"
    supplement = tmp_path / "raw" / "auxiliary" / "berg-malecns-2025-supplement"
    source.mkdir(parents=True)
    supplement.mkdir(parents=True)
    populations = source / "populations.pickle"
    populations.write_bytes(pickle.dumps({"alpha": [100, 101], "beta": [200]}))
    workbook = source / "screen.xlsx"
    _write_workbook(workbook)
    mapping = supplement / "mapping.json"
    mapping.write_text(json.dumps({"100": "A"}), encoding="utf-8")
    annotations = tmp_path / "annotations.feather"
    feather.write_feather(
        pa.table(
            {
                "bodyId": pa.array([10], type=pa.uint64()),
                "type": ["A"],
                "flywireType": ["A"],
                "instance": ["A_L"],
                "status": ["Traced"],
            }
        ),
        annotations,
    )
    experiment = tmp_path / "experiment.json"
    experiment.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "experiment_id": "test-feeding-screen",
                "source_artifacts": {
                    "screen_populations": {
                        "filename": populations.name,
                        "sha256": _sha256(populations),
                    },
                    "supplementary_workbook": {
                        "filename": workbook.name,
                        "sha256": _sha256(workbook),
                        "sheet": "screen",
                    },
                    "crosswalk": {
                        "filename": mapping.name,
                        "sha256": _sha256(mapping),
                    },
                },
                "reference_rule": {
                    "expected_confusion_matrix": {
                        "true_positive": 1,
                        "false_positive": 0,
                        "true_negative": 1,
                        "false_negative": 0,
                    }
                },
                "assumption_ids": ["DATA-03", "ND-01", "VAL-01"],
                "provenance": "M/P/E",
                "claim_boundary": "test only",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "evidence" / "feeding.json"

    result = prepare_shiu_feeding_screen(
        root=tmp_path,
        annotations_path=annotations,
        experiment_path=experiment,
        output_path=output,
    )

    assert result["source_screen"]["confusion_matrix"]["true_positive"] == 1
    assert result["male_cns_transfer_readiness"]["mapping_status_counts"] == {
        "resolved": 0,
        "partial": 1,
        "unresolved": 1,
    }
    assert result["transfer_records"][0]["male_cns_body_ids"] == [10]
    assert result["validation_tier_awarded"] is None


def test_stage1_baseline_can_pass_when_stronger_v3_margin_fails(tmp_path: Path) -> None:
    preparation = tmp_path / "preparation.json"
    preparation.write_text(
        json.dumps(
            {
                "transfer_records": [
                    {
                        "source_type": "positive",
                        "male_cns_body_ids": [1],
                        "observed_positive": True,
                    },
                    {
                        "source_type": "negative",
                        "male_cns_body_ids": [2],
                        "observed_positive": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    preregistration = tmp_path / "preregistration.json"
    preregistration.write_text(
        json.dumps(
            {
                "experiment_id": "test",
                "input_populations": [
                    {"source_type": "positive"},
                    {"source_type": "negative"},
                ],
                "transfer_protocol": {
                    "timestep_sensitivity_ms": 0.05,
                    "stage1_pass_rule": {
                        "minimum_exact_balanced_accuracy": 0.75,
                        "minimum_exact_auroc": 0.75,
                        "minimum_auroc_margin_over_required_controls": 0.05,
                        "required_controls": ["shuffled-connectivity", "cell-type-only"],
                        "minimum_dt_prediction_agreement": 0.95,
                        "maximum_dt_auroc_delta": 0.05,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def run(variant: str, scores: list[float]) -> dict[str, object]:
        rates = [[[score, score]] for score in scores]
        return {
            "variant": variant,
            "population_names": ["positive", "negative"],
            "readout_rates_hz": rates,
            "finite_state": True,
            "runtime_seconds": 1.0,
        }

    predictions = tmp_path / "predictions.json"
    predictions.write_text(
        json.dumps(
            {
                "status": "predictions-frozen-before-outcome-evaluation",
                "preregistration_sha256": _sha256(preregistration),
                "all_states_finite": True,
                "runs": [
                    run("exact", [1.0, 0.0]),
                    run("shuffled-connectivity", [0.0, 0.0]),
                    run("cell-type-only", [1.0, 0.0]),
                    run("uniform-weights", [0.0, 0.0]),
                    run("randomized-weights", [0.0, 0.0]),
                    run("weak-edge-dropout", [1.0, 0.0]),
                    run("excitatory-control", [1.0, 0.0]),
                    run("inhibitory-control", [1.0, 0.0]),
                    run("seeded-balanced-control", [1.0, 0.0]),
                    run("zero-weight", [0.0, 0.0]),
                    run("dt-0.05-ms", [1.0, 0.0]),
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_feeding_screen(
        preparation_path=preparation,
        preregistration_path=preregistration,
        predictions_path=predictions,
        output_path=tmp_path / "review.json",
    )

    assert result["stage1_exit_gate_passed"] is True
    assert result["selected_v3_review_passed"] is False
    assert result["selected_v3_blocking_reasons"] == ["required_control_margins"]
    assert result["validation_tier_awarded"] is None
