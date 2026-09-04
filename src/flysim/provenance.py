# SPDX-License-Identifier: GPL-2.0-or-later
"""Machine-readable evidence and assumption provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


class ProvenanceClass(StrEnum):
    MEASURED = "M"
    POPULATION_PRIOR = "P"
    FITTED = "F"
    ENGINEERING = "E"
    IRRECOVERABLE = "I"


def parse_provenance(value: str) -> tuple[ProvenanceClass, ...]:
    """Parse one provenance class or a slash-delimited combination."""
    try:
        parsed = tuple(ProvenanceClass(part) for part in value.split("/"))
    except ValueError as exc:
        raise ConfigurationError(f"Invalid provenance class: {value!r}") from exc
    if not parsed:
        raise ConfigurationError("Provenance cannot be empty")
    return parsed


@dataclass(frozen=True, slots=True)
class AssumptionRecord:
    id: str
    name: str
    value: Any
    units: str
    provenance: tuple[ProvenanceClass, ...]
    applies_to: str
    source: str
    biological_mismatch: str | None
    uncertainty: Any
    status: str
    validation: str
    owner: str
    last_reviewed: str

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> AssumptionRecord:
        required = {
            "id",
            "name",
            "value",
            "units",
            "provenance",
            "applies_to",
            "source",
            "biological_mismatch",
            "uncertainty",
            "status",
            "validation",
            "owner",
            "last_reviewed",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise ConfigurationError(f"Assumption is missing fields: {', '.join(missing)}")
        if raw["status"] not in {"proposed", "accepted", "deprecated"}:
            raise ConfigurationError(f"Invalid status for {raw['id']}: {raw['status']}")
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            value=raw["value"],
            units=str(raw["units"]),
            provenance=parse_provenance(str(raw["provenance"])),
            applies_to=str(raw["applies_to"]),
            source=str(raw["source"]),
            biological_mismatch=raw["biological_mismatch"],
            uncertainty=raw["uncertainty"],
            status=str(raw["status"]),
            validation=str(raw["validation"]),
            owner=str(raw["owner"]),
            last_reviewed=str(raw["last_reviewed"]),
        )

    def provenance_text(self) -> str:
        return "/".join(item.value for item in self.provenance)


@dataclass(frozen=True, slots=True)
class AssumptionRegistry:
    schema_version: str
    assumption_set_id: str
    records: dict[str, AssumptionRecord]
    source_path: Path
    sha256: str

    @classmethod
    def load(cls, path: Path) -> AssumptionRegistry:
        payload = path.read_bytes()
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Invalid assumption JSON at {path}: {exc}") from exc
        items = [AssumptionRecord.from_mapping(item) for item in raw.get("records", [])]
        records = {item.id: item for item in items}
        if len(records) != len(items):
            raise ConfigurationError("Assumption IDs must be unique")
        if not records:
            raise ConfigurationError("Assumption registry is empty")
        return cls(
            schema_version=str(raw["schema_version"]),
            assumption_set_id=str(raw["assumption_set_id"]),
            records=records,
            source_path=path.resolve(),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def require(self, *ids: str) -> None:
        missing = sorted(set(ids) - self.records.keys())
        if missing:
            raise ConfigurationError(f"Missing required assumptions: {', '.join(missing)}")
        deprecated = sorted(item for item in ids if self.records[item].status == "deprecated")
        if deprecated:
            raise ConfigurationError(
                f"Required assumptions are deprecated: {', '.join(deprecated)}"
            )

    def value_map(self, assumption_id: str) -> dict[str, Any]:
        self.require(assumption_id)
        value = self.records[assumption_id].value
        if not isinstance(value, dict):
            raise ConfigurationError(f"{assumption_id} value must be an object")
        return value
