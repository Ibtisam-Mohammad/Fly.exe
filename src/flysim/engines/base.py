# SPDX-License-Identifier: GPL-2.0-or-later
"""Backend-neutral engine contracts."""

from __future__ import annotations

from typing import Any, Protocol

from flysim.contracts import (
    ActuatorCommandFrame,
    JointTorqueFrame,
    MotorNeuronFrame,
    MuscleActivationFrame,
    MuscleForceFrame,
    NeuralInputFrame,
    NeuralOutputFrame,
    SensorFrame,
)


class SensorTransducer(Protocol):
    """Causal world/body-signal to receptor-activity transformation."""

    def transduce(self, frame: SensorFrame) -> NeuralInputFrame: ...


class PopulationEncoder(Protocol):
    """Map registered receptor activity into stable MaleCNS population IDs."""

    def encode(self, frame: NeuralInputFrame) -> NeuralInputFrame: ...


class PopulationReadout(Protocol):
    """Interpret explicitly selected neural populations without changing them."""

    def read(self, frame: NeuralOutputFrame) -> NeuralOutputFrame: ...


class MotorPathway(Protocol):
    """Keep each provisional motor boundary explicit and independently replaceable."""

    def activate(self, frame: MotorNeuronFrame) -> MuscleActivationFrame: ...

    def force(self, frame: MuscleActivationFrame) -> MuscleForceFrame: ...

    def torque(self, frame: MuscleForceFrame) -> JointTorqueFrame: ...

    def command(self, frame: JointTorqueFrame) -> ActuatorCommandFrame: ...


class NeuralEngine(Protocol):
    @property
    def t_us(self) -> int: ...

    def initialize(self, graph: Any, parameters: dict[str, Any], seed: int) -> None: ...

    def push_inputs(self, frame: NeuralInputFrame) -> None: ...

    def step_until(self, t_us: int) -> None: ...

    def read_outputs(self, ids: tuple[str | int, ...], window_us: int) -> NeuralOutputFrame: ...

    def checkpoint(self) -> dict[str, Any]: ...


class BodyEngine(Protocol):
    @property
    def t_us(self) -> int: ...

    def sample_sensors(self) -> SensorFrame: ...

    def apply_actuators(self, frame: ActuatorCommandFrame) -> None: ...

    def step_until(self, t_us: int) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...
