# SPDX-License-Identifier: GPL-2.0-or-later
"""Numeric MaleCNS population adapters for the Eon-like Track A demonstration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.engines.reference import (
    OUTPUT_DNA_L,
    OUTPUT_DNA_R,
    OUTPUT_FEED,
    OUTPUT_FORWARD,
    OUTPUT_GROOM,
    SENSOR_CONTAMINATION,
    SENSOR_ODOR_L,
    SENSOR_ODOR_R,
    SENSOR_SUCROSE,
)
from flysim.errors import ConfigurationError, DatasetError

REQUIRED_TRACK_A_POPULATIONS = (
    "steering-dn-left",
    "steering-dn-right",
    "forward-odn1",
    "feeding-mn9",
    "grooming-jo-f",
    "grooming-descending-readout",
    "ethyl-acetate-receptor-entry",
    "sucrose-receptor-entry",
)


@dataclass(frozen=True, slots=True)
class TrackAPopulationMap:
    registry_id: str
    resolution_sha256: str
    body_ids: dict[str, tuple[int, ...]]
    rows: dict[str, tuple[dict[str, Any], ...]]

    @classmethod
    def load(cls, path: Path) -> TrackAPopulationMap:
        if not path.is_file():
            raise DatasetError(f"Track A population resolution is missing: {path}")
        import hashlib

        encoded = path.read_bytes()
        raw = json.loads(encoded)
        by_id = {str(item["id"]): item for item in raw.get("populations", [])}
        missing = sorted(set(REQUIRED_TRACK_A_POPULATIONS) - by_id.keys())
        if missing:
            raise DatasetError(f"Track A population resolution lacks: {missing}")
        unresolved = [
            identifier
            for identifier in REQUIRED_TRACK_A_POPULATIONS
            if by_id[identifier].get("status") != "resolved"
        ]
        if unresolved:
            raise DatasetError(f"Track A populations are not resolved: {unresolved}")
        body_ids = {
            identifier: tuple(int(value) for value in by_id[identifier]["body_ids"])
            for identifier in REQUIRED_TRACK_A_POPULATIONS
        }
        if any(not values for values in body_ids.values()):
            raise DatasetError("A resolved Track A population is empty")
        return cls(
            registry_id=str(raw["registry_id"]),
            resolution_sha256=hashlib.sha256(encoded).hexdigest(),
            body_ids=body_ids,
            rows={
                identifier: tuple(dict(row) for row in by_id[identifier].get("rows", []))
                for identifier in REQUIRED_TRACK_A_POPULATIONS
            },
        )

    def side(self, population_id: str, side: str) -> tuple[int, ...]:
        suffix = f"_{side.upper()}"
        values = tuple(
            int(row["bodyId"])
            for row in self.rows[population_id]
            if str(row.get("instance") or "").endswith(suffix)
        )
        if not values:
            raise DatasetError(f"Population {population_id} has no {side} members")
        return tuple(sorted(values))

    @property
    def output_body_ids(self) -> tuple[int, ...]:
        ordered = (
            "steering-dn-left",
            "steering-dn-right",
            "forward-odn1",
            "grooming-descending-readout",
            "feeding-mn9",
        )
        return tuple(dict.fromkeys(body for name in ordered for body in self.body_ids[name]))


@dataclass(frozen=True, slots=True)
class TrackAEncodingParameters:
    odor_max_rate_hz: float
    contamination_max_rate_hz: float
    sucrose_rate_hz: float
    forward_intent_rate_hz: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> TrackAEncodingParameters:
        values = cls(
            odor_max_rate_hz=float(raw["odor_max_rate_hz"]),
            contamination_max_rate_hz=float(raw["contamination_max_rate_hz"]),
            sucrose_rate_hz=float(raw["sucrose_rate_hz"]),
            forward_intent_rate_hz=float(raw["forward_intent_rate_hz"]),
        )
        if min(
            values.odor_max_rate_hz,
            values.contamination_max_rate_hz,
            values.sucrose_rate_hz,
            values.forward_intent_rate_hz,
        ) <= 0:
            raise ConfigurationError("Track A population-encoding rates must be positive")
        return values


class TrackAPopulationEncoder:
    """Map procedural sensor values to numeric MaleCNS central-entry populations."""

    def __init__(
        self,
        populations: TrackAPopulationMap,
        parameters: TrackAEncodingParameters,
        ablated_sensor_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.populations = populations
        self.parameters = parameters
        self.ablated_sensor_ids = ablated_sensor_ids

    def _value(self, frame: NeuralInputFrame, identifier: str) -> float:
        if identifier in self.ablated_sensor_ids:
            return 0.0
        return min(1.0, max(0.0, frame.value_for(identifier, 0.0)))

    def encode(self, frame: NeuralInputFrame) -> NeuralInputFrame:
        rates: dict[int, float] = {}

        def assign(body_ids: tuple[int, ...], rate_hz: float) -> None:
            for body_id in body_ids:
                if body_id in rates:
                    raise ConfigurationError(f"Track A input populations overlap at {body_id}")
                rates[body_id] = rate_hz

        odor_left = self._value(frame, SENSOR_ODOR_L) * self.parameters.odor_max_rate_hz
        odor_right = self._value(frame, SENSOR_ODOR_R) * self.parameters.odor_max_rate_hz
        contamination = (
            self._value(frame, SENSOR_CONTAMINATION)
            * self.parameters.contamination_max_rate_hz
        )
        sucrose = self._value(frame, SENSOR_SUCROSE) * self.parameters.sucrose_rate_hz
        assign(self.populations.side("ethyl-acetate-receptor-entry", "L"), odor_left)
        assign(self.populations.side("ethyl-acetate-receptor-entry", "R"), odor_right)
        assign(self.populations.body_ids["grooming-jo-f"], contamination)
        assign(self.populations.body_ids["sucrose-receptor-entry"], sucrose)
        forward_intent = (
            max(self._value(frame, SENSOR_ODOR_L), self._value(frame, SENSOR_ODOR_R))
            * self.parameters.forward_intent_rate_hz
        )
        assign(self.populations.body_ids["forward-odn1"], forward_intent)
        ids = tuple(sorted(rates))
        return NeuralInputFrame(
            t_us=frame.t_us,
            ids=ids,
            values=tuple(rates[body_id] for body_id in ids),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="M/P/E",
            assumption_ids=("DATA-03", "SENS-03", "SENS-04", "TRACKA-01"),
            metadata={
                "population_registry_id": self.populations.registry_id,
                "population_resolution_sha256": self.populations.resolution_sha256,
                "peripheral_bypasses": {
                    "ethyl_acetate": (
                        "world-to-DM1/DM4 PNs; receptors and AL local circuit bypassed"
                    ),
                    "sucrose": "contact-to-GNG588/Fdg; Gr5a/Gr64f and upstream layers bypassed",
                },
                "intent_bias": "odor-gated DNg97/oDN1 direct drive; engineering scaffold",
            },
        )


class TrackAPopulationReadout:
    """Aggregate numeric body rates into the five semantic Eon-style readouts."""

    _OUTPUT_GROUPS = (
        (OUTPUT_DNA_L, "steering-dn-left"),
        (OUTPUT_DNA_R, "steering-dn-right"),
        (OUTPUT_FORWARD, "forward-odn1"),
        (OUTPUT_GROOM, "grooming-descending-readout"),
        (OUTPUT_FEED, "feeding-mn9"),
    )

    def __init__(
        self,
        populations: TrackAPopulationMap,
        ablated_output_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.populations = populations
        self.ablated_output_ids = ablated_output_ids

    def read(self, frame: NeuralOutputFrame) -> NeuralOutputFrame:
        values: list[float] = []
        members: dict[str, list[int]] = {}
        for output_id, population_id in self._OUTPUT_GROUPS:
            body_ids = self.populations.body_ids[population_id]
            members[output_id] = list(body_ids)
            value = sum(frame.value_for(body_id) for body_id in body_ids) / len(body_ids)
            values.append(0.0 if output_id in self.ablated_output_ids else value)
        return NeuralOutputFrame(
            t_us=frame.t_us,
            ids=tuple(output_id for output_id, _ in self._OUTPUT_GROUPS),
            values=tuple(values),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="M/P/E",
            assumption_ids=("DATA-03", "ND-01", "ND-03", "ND-04", "TRACKA-01"),
            metadata={
                **frame.metadata,
                "aggregation": "arithmetic mean across registered population members",
                "population_members": members,
                "population_resolution_sha256": self.populations.resolution_sha256,
            },
        )
