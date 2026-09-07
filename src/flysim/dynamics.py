# SPDX-License-Identifier: GPL-2.0-or-later
"""Versioned neuron-regime and type-pair parameter registries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.errors import ConfigurationError
from flysim.provenance import parse_provenance


class SignalRegime(StrEnum):
    SPIKING = "spiking"
    GRADED = "graded"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CellDynamicsRecord:
    cell_type: str
    signal_regime: SignalRegime
    model_family: str
    provenance: str
    status: str
    source: str | None
    evidence_scope: str
    biological_mismatch: str | None
    alternatives: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_type": self.cell_type,
            "signal_regime": self.signal_regime.value,
            "model_family": self.model_family,
            "provenance": self.provenance,
            "status": self.status,
            "source": self.source,
            "evidence_scope": self.evidence_scope,
            "biological_mismatch": self.biological_mismatch,
            "alternatives": list(self.alternatives),
        }


@dataclass(frozen=True, slots=True)
class DynamicsResolution:
    registry_id: str
    registry_sha256: str
    records: tuple[CellDynamicsRecord, ...]
    body_signal_regimes: tuple[SignalRegime, ...]
    body_model_families: tuple[str, ...]
    unresolved_cell_types: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        counts = {
            regime.value: self.body_signal_regimes.count(regime) for regime in SignalRegime
        }
        return {
            "registry_id": self.registry_id,
            "registry_sha256": self.registry_sha256,
            "records": [record.as_dict() for record in self.records],
            "body_signal_regime_counts": counts,
            "unresolved_cell_types": list(self.unresolved_cell_types),
            "all_cell_types_resolved": not self.unresolved_cell_types,
        }


@dataclass(frozen=True, slots=True)
class DynamicsRegistry:
    registry_id: str
    registry_sha256: str
    assumption_ids: tuple[str, ...]
    default_record: CellDynamicsRecord
    records: tuple[CellDynamicsRecord, ...]

    @classmethod
    def load(cls, path: Path) -> DynamicsRegistry:
        payload = load_json(path)
        if payload.get("schema_version") != "1.0":
            raise ConfigurationError("Unsupported dynamics registry schema")
        assumption_ids = tuple(str(value) for value in payload["assumption_ids"])
        required_assumptions = {"ND-01", "ND-02", "ND-03", "ND-04", "ND-05"}
        if not required_assumptions <= set(assumption_ids):
            raise ConfigurationError("Dynamics registry omits one or more ND-01 through ND-05")

        def parse_record(record: dict[str, Any]) -> CellDynamicsRecord:
            provenance = str(record["provenance"])
            parse_provenance(provenance)
            status = str(record["status"])
            if status not in {"accepted", "proposed"}:
                raise ConfigurationError(f"Unsupported dynamics record status: {status!r}")
            alternatives = tuple(str(value) for value in record.get("alternatives", []))
            regime = SignalRegime(str(record["signal_regime"]))
            if regime is SignalRegime.UNRESOLVED and len(alternatives) < 2:
                raise ConfigurationError(
                    f"Unresolved type {record['cell_type']!r} needs competing alternatives"
                )
            return CellDynamicsRecord(
                cell_type=str(record["cell_type"]),
                signal_regime=regime,
                model_family=str(record["model_family"]),
                provenance=provenance,
                status=status,
                source=str(record["source"]) if record.get("source") is not None else None,
                evidence_scope=str(record["evidence_scope"]),
                biological_mismatch=(
                    str(record["biological_mismatch"])
                    if record.get("biological_mismatch") is not None
                    else None
                ),
                alternatives=alternatives,
            )

        default_record = parse_record(payload["default_record"])
        records = tuple(parse_record(record) for record in payload["records"])
        cell_types = [record.cell_type for record in records]
        if len(cell_types) != len(set(cell_types)):
            raise ConfigurationError("Dynamics registry contains duplicate cell types")
        return cls(
            registry_id=str(payload["registry_id"]),
            registry_sha256=sha256_json(payload),
            assumption_ids=assumption_ids,
            default_record=default_record,
            records=records,
        )

    def resolve(self, cell_types: tuple[str, ...]) -> DynamicsResolution:
        by_type = {record.cell_type: record for record in self.records}
        selected_records: dict[str, CellDynamicsRecord] = {}
        regimes = []
        families = []
        unresolved = set()
        for cell_type in cell_types:
            record = by_type.get(cell_type, self.default_record)
            if record is self.default_record:
                record = replace(record, cell_type=cell_type)
            selected_records[cell_type] = record
            regimes.append(record.signal_regime)
            families.append(record.model_family)
            if record.signal_regime is SignalRegime.UNRESOLVED:
                unresolved.add(cell_type)
        return DynamicsResolution(
            registry_id=self.registry_id,
            registry_sha256=self.registry_sha256,
            records=tuple(selected_records[key] for key in sorted(selected_records)),
            body_signal_regimes=tuple(regimes),
            body_model_families=tuple(families),
            unresolved_cell_types=tuple(sorted(unresolved)),
        )


def edge_type_pair_keys(
    graph: SparseConnectome, cell_types: tuple[str, ...]
) -> tuple[str, ...]:
    graph.validate()
    if len(cell_types) != graph.neuron_count:
        raise ConfigurationError("Cell-type labels do not align with graph bodies")
    return tuple(
        f"{cell_types[int(source)]}->{cell_types[int(target)]}"
        for source, target in zip(graph.source_indices, graph.target_indices, strict=True)
    )


def edge_scale_multipliers(
    graph: SparseConnectome,
    cell_types: tuple[str, ...],
    *,
    absolute_scale_mv_per_contact: dict[str, float],
    fallback_scale_mv_per_contact: float,
) -> np.ndarray:
    """Map reversible type-pair scales onto edges relative to the runtime fallback."""
    if fallback_scale_mv_per_contact <= 0.0:
        raise ConfigurationError("Fallback contact scale must be positive")
    keys = edge_type_pair_keys(graph, cell_types)
    values = np.asarray(
        [absolute_scale_mv_per_contact.get(key, fallback_scale_mv_per_contact) for key in keys],
        dtype=np.float64,
    )
    if np.any(~np.isfinite(values)) or np.any(values < 0.0):
        raise ConfigurationError("Type-pair contact scales must be finite and nonnegative")
    return values / fallback_scale_mv_per_contact
