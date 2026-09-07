# SPDX-License-Identifier: GPL-2.0-or-later
"""Causal multi-rate orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from flysim.contracts import ActuatorCommandFrame, NeuralInputFrame, SignalType
from flysim.engines.base import (
    BodyEngine,
    NeuralEngine,
    PopulationEncoder,
    PopulationReadout,
)
from flysim.engines.body import COMMAND_IDS
from flysim.engines.reference import REFERENCE_OUTPUT_IDS
from flysim.errors import CausalityError, ConfigurationError
from flysim.scenario import DemoState, EonDemoController
from flysim.timing import CausalDelayQueue


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    completed: bool
    final_t_us: int
    final_state: DemoState
    trace: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]


class CausalScheduler:
    def __init__(
        self,
        neural: NeuralEngine,
        body: BodyEngine,
        controller: EonDemoController,
        coupling_us: int,
        sensory_delay_us: int = 0,
        motor_delay_us: int = 0,
        population_encoder: PopulationEncoder | None = None,
        population_readout: PopulationReadout | None = None,
        output_ids: tuple[str | int, ...] = REFERENCE_OUTPUT_IDS,
    ) -> None:
        if coupling_us <= 0:
            raise ConfigurationError("Coupling interval must be positive")
        if neural.t_us != body.t_us:
            raise CausalityError("Neural and body engines must start at the same time")
        self.neural = neural
        self.body = body
        self.controller = controller
        self.coupling_us = coupling_us
        self.population_encoder = population_encoder
        self.population_readout = population_readout
        self.output_ids = output_ids
        self.sensory_queue: CausalDelayQueue[NeuralInputFrame] = CausalDelayQueue(
            sensory_delay_us
        )
        self.motor_queue: CausalDelayQueue[ActuatorCommandFrame] = CausalDelayQueue(
            motor_delay_us
        )

    def run_until(self, duration_us: int) -> SchedulerResult:
        if duration_us <= self.body.t_us:
            raise ConfigurationError("Run duration must exceed current simulation time")
        initial = ActuatorCommandFrame(
            t_us=self.body.t_us,
            ids=COMMAND_IDS,
            values=tuple(0.0 for _ in COMMAND_IDS),
            units="mm/s, rad/s, normalized, normalized",
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-03",),
            metadata={"controller_state": "INITIAL_DELAY", "vnc_bypass": True},
        )
        self.body.apply_actuators(initial)
        applied_command = initial
        trace: list[dict[str, Any]] = []

        while self.body.t_us < duration_us and self.controller.state != DemoState.COMPLETE:
            current_t = self.body.t_us
            if current_t != self.neural.t_us:
                raise CausalityError(
                    f"Engine clocks diverged: body={current_t}, neural={self.neural.t_us}"
                )
            sensors_before = self.body.sample_sensors()
            neural_inputs = NeuralInputFrame(
                t_us=current_t,
                ids=sensors_before.ids,
                values=sensors_before.values,
                units=sensors_before.units,
                signal_type=SignalType.RECEPTOR_ACTIVITY,
                provenance="E",
                assumption_ids=sensors_before.assumption_ids,
                metadata={"transduction": "identity-reference-scaffold"},
            )
            if self.population_encoder is not None:
                neural_inputs = self.population_encoder.encode(neural_inputs)
            self.sensory_queue.push(current_t, neural_inputs)
            for delayed_input in self.sensory_queue.pop_ready(current_t):
                delivered_input = replace(
                    delayed_input,
                    t_us=current_t,
                    metadata={**delayed_input.metadata, "source_t_us": delayed_input.t_us},
                )
                self.neural.push_inputs(delivered_input)
            next_t = min(duration_us, current_t + self.coupling_us)

            # The body advances on the previously committed command while the neural engine
            # processes current sensors. The newly decoded command starts only at next_t.
            self.neural.step_until(next_t)
            self.body.step_until(next_t)
            if self.body.t_us != self.neural.t_us:
                raise CausalityError("Engine clocks diverged after stepping")

            neural_outputs = self.neural.read_outputs(self.output_ids, self.coupling_us)
            if self.population_readout is not None:
                neural_outputs = self.population_readout.read(neural_outputs)
            sensors_after = self.body.sample_sensors()
            command = self.controller.decode(neural_outputs, sensors_after)
            self.motor_queue.push(next_t, command)
            ready_commands = self.motor_queue.pop_ready(next_t)
            if ready_commands:
                decoded = ready_commands[-1]
                applied_command = replace(
                    decoded,
                    t_us=next_t,
                    metadata={**decoded.metadata, "source_t_us": decoded.t_us},
                )
                self.body.apply_actuators(applied_command)
            traced_command = replace(
                applied_command,
                t_us=next_t,
                metadata={
                    **applied_command.metadata,
                    "active_since_t_us": applied_command.t_us,
                },
            )
            trace.append(
                {
                    "t_us": next_t,
                    "state": self.controller.state.value,
                    "body": self.body.snapshot(),
                    "sensors": sensors_after.as_dict(),
                    "neural": neural_outputs.as_dict(),
                    "actuators": traced_command.as_dict(),
                }
            )

        return SchedulerResult(
            completed=self.controller.state == DemoState.COMPLETE,
            final_t_us=self.body.t_us,
            final_state=self.controller.state,
            trace=tuple(trace),
            events=tuple(event.as_dict() for event in self.controller.events),
        )
