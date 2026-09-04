# SPDX-License-Identifier: GPL-2.0-or-later
"""Typed signal frames used at biological and simulator boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import ConfigurationError
from .provenance import parse_provenance

Identifier = int | str


class SignalType(StrEnum):
    WORLD_QUANTITY = "world_quantity"
    RECEPTOR_ACTIVITY = "receptor_activity"
    SPIKE_EVENT = "spike_event"
    GRADED_VOLTAGE = "graded_voltage"
    FIRING_RATE = "firing_rate"
    TRANSMITTER_RELEASE = "transmitter_release"
    MOTOR_NEURON_ACTIVITY = "motor_neuron_activity"
    MUSCLE_ACTIVATION = "muscle_activation"
    MUSCLE_FORCE = "muscle_force"
    JOINT_TORQUE = "joint_torque"
    ACTUATOR_COMMAND = "actuator_command"
    CALCIUM_OBSERVATION = "calcium_observation"


@dataclass(frozen=True, slots=True)
class SignalFrame:
    t_us: int
    ids: tuple[Identifier, ...]
    values: tuple[float, ...]
    units: str
    signal_type: SignalType
    provenance: str
    assumption_ids: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.t_us < 0:
            raise ConfigurationError("Frame timestamp cannot be negative")
        if len(self.ids) != len(self.values):
            raise ConfigurationError("Frame IDs and values must have equal length")
        if len(set(self.ids)) != len(self.ids):
            raise ConfigurationError("Frame IDs must be unique")
        if not self.units.strip():
            raise ConfigurationError("Frame units are required")
        if not self.assumption_ids:
            raise ConfigurationError("Every signal frame must cite at least one assumption")
        parse_provenance(self.provenance)

    def value_for(self, identifier: Identifier, default: float | None = None) -> float:
        try:
            return self.values[self.ids.index(identifier)]
        except ValueError:
            if default is None:
                raise KeyError(identifier) from None
            return default

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_us": self.t_us,
            "ids": list(self.ids),
            "values": list(self.values),
            "units": self.units,
            "signal_type": self.signal_type.value,
            "provenance": self.provenance,
            "assumption_ids": list(self.assumption_ids),
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class SensorFrame(SignalFrame):
    """World or transduced quantities sampled from the embodied fly."""


@dataclass(frozen=True, slots=True)
class NeuralInputFrame(SignalFrame):
    """Values delivered to resolved sensory-entry neurons."""


@dataclass(frozen=True, slots=True)
class NeuralOutputFrame(SignalFrame):
    """Neural activity read from the simulator without motor interpretation."""


@dataclass(frozen=True, slots=True)
class MotorNeuronFrame(SignalFrame):
    """Activity of resolved motor neurons, before NMJ transformation."""


@dataclass(frozen=True, slots=True)
class MuscleActivationFrame(SignalFrame):
    """Muscle activation after an explicit NMJ/activation model."""


@dataclass(frozen=True, slots=True)
class ActuatorCommandFrame(SignalFrame):
    """Engineering commands accepted by the current body backend."""


def frame_from_dict[FrameT: SignalFrame](frame_type: type[FrameT], raw: dict[str, Any]) -> FrameT:
    return frame_type(
        t_us=int(raw["t_us"]),
        ids=tuple(raw["ids"]),
        values=tuple(float(item) for item in raw["values"]),
        units=str(raw["units"]),
        signal_type=SignalType(raw["signal_type"]),
        provenance=str(raw["provenance"]),
        assumption_ids=tuple(str(item) for item in raw["assumption_ids"]),
        metadata=dict(raw.get("metadata", {})),
    )
