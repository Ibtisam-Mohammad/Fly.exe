# SPDX-License-Identifier: GPL-2.0-or-later
"""Backend-neutral engine contracts."""

from __future__ import annotations

from typing import Any, Protocol

from flysim.contracts import ActuatorCommandFrame, NeuralInputFrame, NeuralOutputFrame, SensorFrame


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

