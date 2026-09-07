# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare the independent Shiu Figure 2 feeding-screen transfer."""

from __future__ import annotations

import io
import json
import os
import pickle
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.feather as feather

from flysim.config import load_json, project_root, sha256_json
from flysim.datasets import sha256_file
from flysim.errors import DatasetError

_MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DOCUMENT_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_REFERENCE = re.compile(r"([A-Z]+)[0-9]+")


class _PrimitiveUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        raise DatasetError(f"Executable pickle global is forbidden: {module}.{name}")


def load_primitive_population_pickle(path: Path) -> dict[str, tuple[int, ...]]:
    """Load the pinned primitive dictionary without permitting global imports."""
    try:
        value = _PrimitiveUnpickler(io.BytesIO(path.read_bytes())).load()
    except (pickle.UnpicklingError, EOFError) as exc:
        raise DatasetError(f"Invalid primitive population pickle: {path}") from exc
    if not isinstance(value, dict):
        raise DatasetError("SEZ population artifact must contain a dictionary")
    result: dict[str, tuple[int, ...]] = {}
    for raw_name, raw_ids in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_ids, list):
            raise DatasetError("SEZ population entries must be string-to-list mappings")
        if not raw_ids or any(not isinstance(body_id, int) for body_id in raw_ids):
            raise DatasetError(f"SEZ population {raw_name!r} has invalid body IDs")
        result[raw_name] = tuple(int(body_id) for body_id in raw_ids)
    if len(result) != len(value):
        raise DatasetError("SEZ population names must be unique")
    return result


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise DatasetError(f"Invalid XLSX cell reference: {reference!r}")
    index = 0
    for character in match.group(1):
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iter(f"{_MAIN_NS}t"))
        for item in root
    ]


def _sheet_target(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_id: str | None = None
    sheets = workbook.find(f"{_MAIN_NS}sheets")
    if sheets is None:
        raise DatasetError("Supplementary workbook contains no worksheets")
    for sheet in sheets:
        if sheet.attrib.get("name") == sheet_name:
            relationship_id = sheet.attrib.get(f"{_DOCUMENT_REL_NS}id")
            break
    if relationship_id is None:
        raise DatasetError(f"Supplementary worksheet is absent: {sheet_name!r}")
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.findall(f"{_PACKAGE_REL_NS}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise DatasetError(f"Worksheet relationship is absent: {relationship_id}")


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[list[str]]:
    """Read plain string/numeric cells from one checksum-locked XLSX worksheet."""
    try:
        with zipfile.ZipFile(path) as archive:
            strings = _shared_strings(archive)
            worksheet = ET.fromstring(archive.read(_sheet_target(archive, sheet_name)))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise DatasetError(f"Invalid supplementary workbook: {path}") from exc
    rows: list[list[str]] = []
    for row in worksheet.iter(f"{_MAIN_NS}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{_MAIN_NS}c"):
            index = _column_index(cell.attrib["r"])
            value_node = cell.find(f"{_MAIN_NS}v")
            value = "" if value_node is None or value_node.text is None else value_node.text
            if cell.attrib.get("t") == "s" and value:
                try:
                    value = strings[int(value)]
                except (IndexError, ValueError) as exc:
                    raise DatasetError("Invalid XLSX shared-string reference") from exc
            values[index] = value
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def _as_nonnegative_float(value: str, field: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise DatasetError(f"Feeding-screen {field} is not numeric: {value!r}") from exc
    if not 0.0 <= parsed < float("inf"):
        raise DatasetError(f"Feeding-screen {field} must be finite and nonnegative")
    return parsed


def _confusion(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "true_positive": sum(
            bool(item["predicted_positive"] and item["observed_positive"])
            for item in records
        ),
        "false_positive": sum(
            bool(item["predicted_positive"] and not item["observed_positive"])
            for item in records
        ),
        "true_negative": sum(
            bool(not item["predicted_positive"] and not item["observed_positive"])
            for item in records
        ),
        "false_negative": sum(
            bool(not item["predicted_positive"] and item["observed_positive"])
            for item in records
        ),
    }


def _code_commit() -> str:
    repository = project_root()
    return subprocess.run(
        ["git", "-c", f"safe.directory={repository}", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repository,
    ).stdout.strip()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def prepare_shiu_feeding_screen(
    *,
    root: Path,
    annotations_path: Path,
    experiment_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Lock the biological screen and quantify the exact MaleCNS mapping boundary."""
    experiment = load_json(experiment_path)
    source_root = root / "raw" / "auxiliary" / "shiu-2024-brain-model"
    supplement_root = root / "raw" / "auxiliary" / "berg-malecns-2025-supplement"
    artifacts = experiment["source_artifacts"]
    populations_path = source_root / str(artifacts["screen_populations"]["filename"])
    workbook_path = source_root / str(artifacts["supplementary_workbook"]["filename"])
    mapping_path = supplement_root / str(artifacts["crosswalk"]["filename"])
    for path, expected in (
        (populations_path, artifacts["screen_populations"]["sha256"]),
        (workbook_path, artifacts["supplementary_workbook"]["sha256"]),
        (mapping_path, artifacts["crosswalk"]["sha256"]),
    ):
        observed = sha256_file(path)
        if observed != expected:
            raise DatasetError(f"Stage 1 feeding source hash mismatch: {path}")

    source_populations = load_primitive_population_pickle(populations_path)
    rows = read_xlsx_sheet(workbook_path, artifacts["supplementary_workbook"]["sheet"])
    if not rows or len(rows[0]) < 20:
        raise DatasetError("Supplementary Table 3 has an unexpected schema")
    population_names_by_fold = {name.casefold(): name for name in source_populations}
    if len(population_names_by_fold) != len(source_populations):
        raise DatasetError("SEZ population names collide under case-insensitive matching")
    screen_records: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        if len(row) < 14:
            raise DatasetError(f"Supplementary Table 3 row is truncated: {row[0]!r}")
        observed_rate = _as_nonnegative_float(row[1], "opto extension rate")
        if observed_rate > 1.0:
            raise DatasetError("Optogenetic extension fraction exceeds one")
        left_rate = _as_nonnegative_float(row[12], "50 Hz left MN9 rate")
        right_rate = _as_nonnegative_float(row[13], "50 Hz right MN9 rate")
        workbook_name = row[0]
        source_type = population_names_by_fold.get(workbook_name.casefold())
        if source_type is None:
            raise DatasetError(f"Supplementary Table 3 type is absent from source: {workbook_name}")
        screen_records.append(
            {
                "source_type": source_type,
                "workbook_type_label": workbook_name,
                "observed_extension_fraction": observed_rate,
                "predicted_left_mn9_rate_hz": left_rate,
                "predicted_right_mn9_rate_hz": right_rate,
                "predicted_positive": left_rate > 0.0 and right_rate > 0.0,
                "observed_positive": observed_rate > 0.0,
            }
        )
    screen_names = {str(item["source_type"]).casefold() for item in screen_records}
    if screen_names != set(population_names_by_fold):
        raise DatasetError("Supplementary Table 3 and SEZ population names do not match")
    confusion = _confusion(screen_records)
    if confusion != experiment["reference_rule"]["expected_confusion_matrix"]:
        raise DatasetError(f"Source Figure 2 confusion matrix changed: {confusion}")

    crosswalk = load_json(mapping_path)
    annotations = feather.read_table(
        annotations_path,
        columns=["bodyId", "type", "flywireType", "instance", "status"],
        memory_map=True,
    ).to_pylist()
    bodies_by_label: dict[str, set[int]] = {}
    for annotation in annotations:
        if annotation["status"] != "Traced":
            continue
        for field in ("type", "flywireType"):
            label = annotation[field]
            if label:
                bodies_by_label.setdefault(str(label), set()).add(int(annotation["bodyId"]))

    transfer_records: list[dict[str, Any]] = []
    for screen_record in screen_records:
        source_type = str(screen_record["source_type"])
        source_ids = source_populations[source_type]
        labels = sorted(
            {
                str(crosswalk[str(body_id)])
                for body_id in source_ids
                if str(body_id) in crosswalk
            }
        )
        mapped_source_ids = sum(str(body_id) in crosswalk for body_id in source_ids)
        target_body_ids = sorted(
            set().union(*(bodies_by_label.get(label, set()) for label in labels))
            if labels
            else set()
        )
        if not target_body_ids:
            mapping_status = "unresolved"
        elif mapped_source_ids < len(source_ids):
            mapping_status = "partial"
        else:
            mapping_status = "resolved"
        transfer_records.append(
            {
                **screen_record,
                "source_flywire_ids": list(source_ids),
                "mapped_source_identity_count": mapped_source_ids,
                "crosswalk_labels": labels,
                "male_cns_body_ids": target_body_ids,
                "mapping_status": mapping_status,
            }
        )

    mapped_records = [item for item in transfer_records if item["male_cns_body_ids"]]
    status_counts = {
        status: sum(item["mapping_status"] == status for item in transfer_records)
        for status in ("resolved", "partial", "unresolved")
    }
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment["experiment_id"],
        "status": "prepared",
        "code_commit": _code_commit(),
        "experiment_path": str(experiment_path.resolve()),
        "experiment_sha256": sha256_file(experiment_path),
        "experiment_logical_sha256": sha256_json(experiment),
        "source_artifacts": {
            "screen_populations": str(populations_path.resolve()),
            "screen_populations_sha256": sha256_file(populations_path),
            "supplementary_workbook": str(workbook_path.resolve()),
            "supplementary_workbook_sha256": sha256_file(workbook_path),
            "crosswalk": str(mapping_path.resolve()),
            "crosswalk_sha256": sha256_file(mapping_path),
            "annotations": str(annotations_path.resolve()),
            "annotations_sha256": sha256_file(annotations_path),
        },
        "source_screen": {
            "cell_type_count": len(screen_records),
            "confusion_matrix": confusion,
            "rule": experiment["reference_rule"],
        },
        "male_cns_transfer_readiness": {
            "mapping_status_counts": status_counts,
            "types_with_any_male_cns_mapping": len(mapped_records),
            "mapped_subset_source_confusion_matrix": _confusion(mapped_records),
            "simulation_status": "not-run",
            "next_action": (
                "Preregister the mapped subset and held-out readout rule, then execute exact, "
                "shuffled-connectivity, cell-type-only, and sign alternatives without fitting "
                "to the optogenetic labels."
            ),
        },
        "transfer_records": transfer_records,
        "assumption_ids": experiment["assumption_ids"],
        "provenance": experiment["provenance"],
        "claim_boundary": experiment["claim_boundary"],
        "stage1_exit_gate_passed": False,
        "validation_tier_awarded": None,
    }
    _atomic_json(output_path, payload)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": sha256_file(output_path),
    }
