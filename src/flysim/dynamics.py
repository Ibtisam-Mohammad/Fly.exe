# SPDX-License-Identifier: GPL-2.0-or-later
"""Versioned neuron-regime and type-pair parameter registries."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.errors import ConfigurationError
from flysim.provenance import ProvenanceClass, parse_provenance


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
    parameter_prior_id: str | None = None
    parameter_set_id: str | None = None

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
            "parameter_prior_id": self.parameter_prior_id,
            "parameter_set_id": self.parameter_set_id,
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


CELL_PARAMETER_KEYS = (
    "resting_mv",
    "reset_mv",
    "threshold_mv",
    "membrane_tau_ms",
    "synapse_tau_ms",
    "refractory_ms",
    "tonic_drive_mv",
)


@dataclass(frozen=True, slots=True)
class CellParameterSet:
    """One named numeric membrane parameter set with per-value provenance.

    Per-value provenance matters more here than one label for the set. A set that measures
    resting voltage and time constant but falls back to an engineering reset voltage is
    neither measured nor an engineering scaffold, and reporting it as either is misleading.
    """

    parameter_set_id: str
    source: str | None
    evidence: str
    values: dict[str, float]
    value_provenance: dict[str, str]

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> CellParameterSet:
        values = {key: float(raw["values"][key]) for key in CELL_PARAMETER_KEYS}
        missing = set(CELL_PARAMETER_KEYS) - set(raw["values"])
        if missing:
            raise ConfigurationError(f"Cell parameter set omits {sorted(missing)}")
        if any(not math.isfinite(value) for value in values.values()):
            raise ConfigurationError("Cell parameter values must be finite")
        for key in ("membrane_tau_ms", "synapse_tau_ms"):
            if values[key] <= 0.0:
                raise ConfigurationError(f"{key} must be positive")
        if values["refractory_ms"] < 0.0:
            raise ConfigurationError("refractory_ms cannot be negative")
        if values["threshold_mv"] <= values["resting_mv"]:
            raise ConfigurationError(
                "threshold_mv must sit above resting_mv or the cell fires without input"
            )
        provenance = {key: str(raw["value_provenance"][key]) for key in CELL_PARAMETER_KEYS}
        for value in provenance.values():
            parse_provenance(value)
        return cls(
            parameter_set_id=str(raw["parameter_set_id"]),
            source=str(raw["source"]) if raw.get("source") is not None else None,
            evidence=str(raw["evidence"]),
            values=values,
            value_provenance=provenance,
        )

    @property
    def measured_keys(self) -> tuple[str, ...]:
        return tuple(
            key
            for key in CELL_PARAMETER_KEYS
            if ProvenanceClass.MEASURED in parse_provenance(self.value_provenance[key])
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "parameter_set_id": self.parameter_set_id,
            "source": self.source,
            "evidence": self.evidence,
            "values": dict(self.values),
            "value_provenance": dict(self.value_provenance),
            "measured_keys": list(self.measured_keys),
        }


@dataclass(frozen=True, slots=True)
class CellParameterResolution:
    """Per-neuron membrane parameters plus an honest account of where they came from."""

    registry_id: str
    registry_sha256: str
    fallback_parameter_set_id: str
    parameter_arrays: dict[str, np.ndarray]
    parameter_set_ids: tuple[str, ...]
    signal_regimes: tuple[SignalRegime, ...]
    heterogeneous: bool
    graded_cell_types: tuple[str, ...]
    unresolved_cell_types: tuple[str, ...]
    coverage: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "registry_sha256": self.registry_sha256,
            "fallback_parameter_set_id": self.fallback_parameter_set_id,
            "heterogeneous": self.heterogeneous,
            "graded_cell_types": list(self.graded_cell_types),
            "unresolved_cell_types": list(self.unresolved_cell_types),
            "coverage": self.coverage,
        }


@dataclass(frozen=True, slots=True)
class DynamicsRegistry:
    registry_id: str
    registry_sha256: str
    assumption_ids: tuple[str, ...]
    default_record: CellDynamicsRecord
    records: tuple[CellDynamicsRecord, ...]
    parameter_sets: dict[str, CellParameterSet]
    fallback_parameter_set_id: str

    @classmethod
    def load(cls, path: Path) -> DynamicsRegistry:
        payload = load_json(path)
        if payload.get("schema_version") not in {"1.0", "1.1"}:
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
                parameter_prior_id=(
                    str(record["parameter_prior_id"])
                    if record.get("parameter_prior_id") is not None
                    else None
                ),
                parameter_set_id=(
                    str(record["parameter_set_id"])
                    if record.get("parameter_set_id") is not None
                    else None
                ),
            )

        default_record = parse_record(payload["default_record"])
        records = tuple(parse_record(record) for record in payload["records"])
        cell_types = [record.cell_type for record in records]
        if len(cell_types) != len(set(cell_types)):
            raise ConfigurationError("Dynamics registry contains duplicate cell types")
        parameter_sets = {
            str(item["parameter_set_id"]): CellParameterSet.from_mapping(item)
            for item in payload.get("parameter_sets", [])
        }
        if len(parameter_sets) != len(payload.get("parameter_sets", [])):
            raise ConfigurationError("Dynamics registry contains duplicate parameter set IDs")
        fallback_id = str(
            payload.get("fallback_parameter_set_id", "engineering-fallback-not-registered")
        )
        # `parameter_prior_id` points at a source document; `parameter_set_id` binds the
        # numeric values the engine will actually run. Only the latter must resolve.
        for record in (default_record, *records):
            identifier = record.parameter_set_id
            if identifier is not None and identifier not in parameter_sets:
                raise ConfigurationError(
                    f"Cell type {record.cell_type!r} names unregistered parameter set "
                    f"{identifier!r}"
                )
        return cls(
            registry_id=str(payload["registry_id"]),
            registry_sha256=sha256_json(payload),
            assumption_ids=assumption_ids,
            default_record=default_record,
            records=records,
            parameter_sets=parameter_sets,
            fallback_parameter_set_id=fallback_id,
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

    def resolve_parameters(self, cell_types: tuple[str, ...]) -> CellParameterResolution:
        """Bind each neuron to a registered parameter set, or to the declared fallback.

        Nothing is silently defaulted: the coverage report names how many neurons each set
        covers, and how much of the graph is running on the engineering fallback.
        """
        if self.fallback_parameter_set_id not in self.parameter_sets:
            raise ConfigurationError(
                f"Fallback parameter set {self.fallback_parameter_set_id!r} is not registered"
            )
        fallback = self.parameter_sets[self.fallback_parameter_set_id]
        by_type = {record.cell_type: record for record in self.records}
        assigned: list[str] = []
        regimes: list[SignalRegime] = []
        graded: set[str] = set()
        unresolved: set[str] = set()
        for cell_type in cell_types:
            record = by_type.get(cell_type, self.default_record)
            regimes.append(record.signal_regime)
            if record.signal_regime is SignalRegime.GRADED:
                graded.add(cell_type)
            elif record.signal_regime is SignalRegime.UNRESOLVED:
                unresolved.add(cell_type)
            identifier = record.parameter_set_id
            assigned.append(identifier if identifier is not None else fallback.parameter_set_id)

        arrays = {
            key: np.asarray(
                [self.parameter_sets[identifier].values[key] for identifier in assigned],
                dtype=np.float64,
            )
            for key in CELL_PARAMETER_KEYS
        }
        counts: dict[str, int] = {}
        for identifier in assigned:
            counts[identifier] = counts.get(identifier, 0) + 1
        total = len(assigned)
        measured_neurons = sum(
            count
            for identifier, count in counts.items()
            if self.parameter_sets[identifier].measured_keys
        )
        coverage = {
            "neuron_count": total,
            "distinct_cell_types": len(set(cell_types)),
            "parameter_set_neuron_counts": dict(sorted(counts.items())),
            "fallback_neuron_count": counts.get(fallback.parameter_set_id, 0),
            "fallback_fraction": (
                counts.get(fallback.parameter_set_id, 0) / total if total else 0.0
            ),
            "neurons_with_any_measured_parameter": measured_neurons,
            "measured_fraction": measured_neurons / total if total else 0.0,
            "parameter_sets": {
                identifier: self.parameter_sets[identifier].as_dict()
                for identifier in sorted(counts)
            },
        }
        return CellParameterResolution(
            registry_id=self.registry_id,
            registry_sha256=self.registry_sha256,
            fallback_parameter_set_id=fallback.parameter_set_id,
            parameter_arrays=arrays,
            parameter_set_ids=tuple(assigned),
            signal_regimes=tuple(regimes),
            heterogeneous=len(counts) > 1,
            graded_cell_types=tuple(sorted(graded)),
            unresolved_cell_types=tuple(sorted(unresolved)),
            coverage=coverage,
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
