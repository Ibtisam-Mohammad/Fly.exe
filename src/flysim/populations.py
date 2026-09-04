# SPDX-License-Identifier: GPL-2.0-or-later
"""Versioned annotation queries for sensory, descending, and motor populations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

from flysim.config import load_json, sha256_json
from flysim.errors import DatasetError
from flysim.provenance import parse_provenance


@dataclass(frozen=True, slots=True)
class PopulationResult:
    id: str
    role: str
    status: str
    body_ids: tuple[int, ...]
    rows: tuple[dict[str, Any], ...]
    provenance: str
    fallback: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "status": self.status,
            "body_ids": list(self.body_ids),
            "rows": list(self.rows),
            "provenance": self.provenance,
            "fallback": self.fallback,
        }


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _query_mask(table: pa.Table, query: dict[str, Any]) -> pa.Array:
    field = str(query["field"])
    if field not in table.column_names:
        raise DatasetError(f"Population query field is absent: {field}")
    values = pc.fill_null(table[field], "")
    operator = str(query["operator"])
    pattern = str(query["value"])
    if operator == "exact":
        return pc.equal(values, pattern)
    if operator == "regex":
        return pc.match_substring_regex(values, pattern, ignore_case=True)
    raise DatasetError(f"Unsupported population query operator: {operator}")


def resolve_populations(
    annotations_path: Path,
    registry_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    registry = load_json(registry_path)
    table = feather.read_table(annotations_path, memory_map=True)
    required_columns = {
        "bodyId",
        "instance",
        "type",
        "class",
        "subclass",
        "entryNerve",
        "exitNerve",
        "receptorType",
        "status",
    }
    missing = sorted(required_columns - set(table.column_names))
    if missing:
        raise DatasetError(f"Annotation columns missing: {missing}")
    results: list[PopulationResult] = []
    for specification in registry["populations"]:
        provenance = str(specification["provenance"])
        parse_provenance(provenance)
        masks = [_query_mask(table, query) for query in specification["queries"]]
        if specification["combine"] == "all":
            mask = masks[0]
            for item in masks[1:]:
                mask = pc.and_(mask, item)
        elif specification["combine"] == "any":
            mask = masks[0]
            for item in masks[1:]:
                mask = pc.or_(mask, item)
        else:
            raise DatasetError(f"Invalid query combination: {specification['combine']}")
        selected = table.filter(mask).select(sorted(required_columns))
        rows = tuple(selected.to_pylist())
        body_ids = tuple(sorted({int(row["bodyId"]) for row in rows}))
        expected_min = int(specification["expected_min"])
        expected_max = int(specification["expected_max"])
        if not body_ids:
            status = "unresolved"
        elif expected_min <= len(body_ids) <= expected_max:
            status = "resolved"
        else:
            status = "ambiguous"
        results.append(
            PopulationResult(
                id=str(specification["id"]),
                role=str(specification["role"]),
                status=status,
                body_ids=body_ids,
                rows=rows,
                provenance=provenance,
                fallback=str(specification["fallback"]),
            )
        )

    payload = {
        "schema_version": "1.0",
        "registry_id": registry["registry_id"],
        "registry_sha256": sha256_json(registry),
        "dataset_id": registry["dataset_id"],
        "annotations_path": str(annotations_path.resolve()),
        "annotations_sha256": _source_sha256(annotations_path),
        "annotation_rows": table.num_rows,
        "populations": [item.as_dict() for item in results],
        "all_required_resolved": all(item.status == "resolved" for item in results),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload

