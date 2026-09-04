# SPDX-License-Identifier: GPL-2.0-or-later
"""Small causal engineering circuit for contract tests and Track A storyboard."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError

SENSOR_ODOR_L = "sensory:ethyl-acetate:left"
SENSOR_ODOR_R = "sensory:ethyl-acetate:right"
SENSOR_CONTAMINATION = "sensory:antenna-contamination"
SENSOR_SUCROSE = "sensory:sucrose-contact"
SENSOR_TOUCH = "sensory:ground-touch"

OUTPUT_DNA_L = "readout:DNa01-02:left"
OUTPUT_DNA_R = "readout:DNa01-02:right"
OUTPUT_FORWARD = "readout:oDN1"
OUTPUT_GROOM = "readout:antennal-grooming-DN"
OUTPUT_FEED = "readout:MN9"

REFERENCE_OUTPUT_IDS = (
    OUTPUT_DNA_L,
    OUTPUT_DNA_R,
    OUTPUT_FORWARD,
    OUTPUT_GROOM,
    OUTPUT_FEED,
)


@dataclass(frozen=True, slots=True)
class ReferenceDynamics:
    neural_dt_us: int
    sensory_delay_us: int
    time_constant_us: int
    baseline_rate_hz: float
    observation_noise_hz_sd: float
    odor_output_gain_hz: float
    groom_output_gain_hz: float
    sweet_output_gain_hz: float

    @classmethod
    def from_parameters(cls, parameters: dict[str, Any]) -> ReferenceDynamics:
        return cls(**{key: parameters[key] for key in cls.__dataclass_fields__})


class ReferenceNeuralEngine:
    """Explicit `E` scaffold; it is not a MaleCNS physiological model."""

    def __init__(
        self,
        ablated_input_ids: frozenset[str] = frozenset(),
        ablated_output_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._t_us = 0
        self._parameters: ReferenceDynamics | None = None
        self._rng = np.random.default_rng(0)
        self._input_values: dict[str, float] = {}
        self._rates = {identifier: 0.0 for identifier in REFERENCE_OUTPUT_IDS}
        self._queue: list[tuple[int, int, NeuralInputFrame]] = []
        self._queue_counter = 0
        self._ablated_inputs = ablated_input_ids
        self._ablated_outputs = ablated_output_ids

    @property
    def t_us(self) -> int:
        return self._t_us

    def initialize(self, graph: Any, parameters: dict[str, Any], seed: int) -> None:
        if graph is not None:
            raise ConfigurationError(
                "The reference engineering circuit cannot consume a MaleCNS graph; "
                "use the production GeNN adapter after its readiness gate passes"
            )
        self._parameters = ReferenceDynamics.from_parameters(parameters)
        if self._parameters.neural_dt_us <= 0 or self._parameters.sensory_delay_us <= 0:
            raise ConfigurationError("Reference neural timesteps and delays must be positive")
        self._rng = np.random.default_rng(seed)
        self._t_us = 0
        self._queue.clear()
        self._input_values.clear()
        self._rates = {
            identifier: self._parameters.baseline_rate_hz for identifier in REFERENCE_OUTPUT_IDS
        }

    def push_inputs(self, frame: NeuralInputFrame) -> None:
        parameters = self._require_parameters()
        if frame.t_us < self._t_us:
            raise CausalityError(
                f"Neural input at {frame.t_us} us is older than neural time {self._t_us} us"
            )
        arrival = frame.t_us + parameters.sensory_delay_us
        heapq.heappush(self._queue, (arrival, self._queue_counter, frame))
        self._queue_counter += 1

    def _apply_arrived_inputs(self, until_us: int) -> None:
        while self._queue and self._queue[0][0] <= until_us:
            _, _, frame = heapq.heappop(self._queue)
            for identifier, value in zip(frame.ids, frame.values, strict=True):
                key = str(identifier)
                self._input_values[key] = 0.0 if key in self._ablated_inputs else float(value)

    def _target_rates(self) -> dict[str, float]:
        parameters = self._require_parameters()
        odor_l = max(0.0, self._input_values.get(SENSOR_ODOR_L, 0.0))
        odor_r = max(0.0, self._input_values.get(SENSOR_ODOR_R, 0.0))
        contamination = max(0.0, self._input_values.get(SENSOR_CONTAMINATION, 0.0))
        sucrose = max(0.0, self._input_values.get(SENSOR_SUCROSE, 0.0))
        baseline = parameters.baseline_rate_hz
        return {
            OUTPUT_DNA_L: baseline + parameters.odor_output_gain_hz * odor_l,
            OUTPUT_DNA_R: baseline + parameters.odor_output_gain_hz * odor_r,
            OUTPUT_FORWARD: baseline
            + parameters.odor_output_gain_hz * math.sqrt(max(0.0, odor_l * odor_r)),
            OUTPUT_GROOM: baseline + parameters.groom_output_gain_hz * contamination,
            OUTPUT_FEED: baseline + parameters.sweet_output_gain_hz * sucrose,
        }

    def step_until(self, t_us: int) -> None:
        parameters = self._require_parameters()
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step neural engine backward from {self._t_us} to {t_us}")
        while self._t_us < t_us:
            next_t = min(t_us, self._t_us + parameters.neural_dt_us)
            self._apply_arrived_inputs(next_t)
            dt_us = next_t - self._t_us
            alpha = 1.0 - math.exp(-dt_us / parameters.time_constant_us)
            targets = self._target_rates()
            # Ornstein-Uhlenbeck scaling keeps the registered noise parameter as
            # the stationary standard deviation instead of accumulating it each step.
            noise_scale = parameters.observation_noise_hz_sd * math.sqrt(
                1.0 - math.exp(-2.0 * dt_us / parameters.time_constant_us)
            )
            for identifier, target in targets.items():
                noise = float(self._rng.normal(0.0, noise_scale))
                updated = (
                    self._rates[identifier]
                    + alpha * (target - self._rates[identifier])
                    + noise
                )
                self._rates[identifier] = max(0.0, updated)
            self._t_us = next_t

    def read_outputs(self, ids: tuple[str | int, ...], window_us: int) -> NeuralOutputFrame:
        if window_us <= 0:
            raise ConfigurationError("Neural output window must be positive")
        values = tuple(
            0.0 if str(identifier) in self._ablated_outputs else self._rates[str(identifier)]
            for identifier in ids
        )
        return NeuralOutputFrame(
            t_us=self._t_us,
            ids=ids,
            values=values,
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="E",
            assumption_ids=("ND-08",),
            metadata={
                "backend": "reference-engineering-circuit",
                "male_cns_graph_used": False,
                "window_us": window_us,
            },
        )

    def checkpoint(self) -> dict[str, Any]:
        return {
            "t_us": self._t_us,
            "rates_hz": dict(self._rates),
            "inputs": dict(self._input_values),
            "pending_input_count": len(self._queue),
            "backend": "reference-engineering-circuit",
        }

    def _require_parameters(self) -> ReferenceDynamics:
        if self._parameters is None:
            raise ConfigurationError("Reference neural engine is not initialized")
        return self._parameters
