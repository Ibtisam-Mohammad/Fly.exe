# SPDX-License-Identifier: GPL-2.0-or-later
"""Sparse LIF numerical oracle for small circuits, not whole-CNS production."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import numpy as np

from flysim.connectome import SparseConnectome
from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError


@dataclass(frozen=True, slots=True)
class LIFParameters:
    neural_dt_us: int
    membrane_tau_us: int
    resting_mv: float
    reset_mv: float
    threshold_mv: float
    refractory_us: int
    tonic_drive_mv: float
    input_gain_mv: float
    synaptic_mv_per_contact: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> LIFParameters:
        return cls(**{name: raw[name] for name in cls.__dataclass_fields__})


class NumpyLIFEngine:
    """Transparent oracle whose edge signs must be supplied by the caller."""

    def __init__(self) -> None:
        self._t_us = 0
        self._graph: SparseConnectome | None = None
        self._parameters: LIFParameters | None = None
        self._voltage = np.empty(0, dtype=np.float32)
        self._external_drive = np.empty(0, dtype=np.float32)
        self._refractory_until = np.empty(0, dtype=np.int64)
        self._edge_weights = np.empty(0, dtype=np.float32)
        self._spikes = np.empty(0, dtype=np.bool_)
        self._spike_history: list[tuple[int, np.ndarray]] = []
        self._queue: list[tuple[int, int, NeuralInputFrame]] = []
        self._queue_counter = 0

    @property
    def t_us(self) -> int:
        return self._t_us

    def initialize(self, graph: SparseConnectome, parameters: dict[str, Any], seed: int) -> None:
        del seed  # This deterministic baseline currently has no registered noise process.
        graph.validate()
        if graph.neuron_count > 100_000:
            raise ConfigurationError(
                "The NumPy LIF engine is a small-circuit oracle, not a whole-CNS backend"
            )
        signs = np.asarray(parameters.get("functional_edge_signs"), dtype=np.float32)
        if signs.shape != graph.contact_counts.shape:
            raise ConfigurationError(
                "functional_edge_signs must provide one explicit sign per aggregate edge"
            )
        if not np.all(np.isin(signs, (-1.0, 0.0, 1.0))):
            raise ConfigurationError("Functional edge signs must be -1, 0, or 1")
        self._parameters = LIFParameters.from_mapping(parameters)
        if self._parameters.neural_dt_us <= 0 or self._parameters.membrane_tau_us <= 0:
            raise ConfigurationError("LIF timesteps must be positive")
        self._graph = graph
        self._t_us = 0
        self._voltage = np.full(
            graph.neuron_count, self._parameters.resting_mv, dtype=np.float32
        )
        self._external_drive = np.zeros(graph.neuron_count, dtype=np.float32)
        self._refractory_until = np.zeros(graph.neuron_count, dtype=np.int64)
        self._edge_weights = (
            graph.contact_counts.astype(np.float32)
            * signs
            * self._parameters.synaptic_mv_per_contact
        )
        self._spikes = np.zeros(graph.neuron_count, dtype=np.bool_)
        self._spike_history.clear()
        self._queue.clear()

    def push_inputs(self, frame: NeuralInputFrame) -> None:
        self._require_ready()
        if frame.t_us < self._t_us:
            raise CausalityError(
                f"Neural input at {frame.t_us} us is older than engine time {self._t_us} us"
            )
        delay_us = int(frame.metadata.get("delay_us", 0))
        if delay_us < 0:
            raise CausalityError("Input delay cannot be negative")
        heapq.heappush(self._queue, (frame.t_us + delay_us, self._queue_counter, frame))
        self._queue_counter += 1

    def _apply_inputs(self, until_us: int) -> None:
        graph, _ = self._require_ready()
        while self._queue and self._queue[0][0] <= until_us:
            _, _, frame = heapq.heappop(self._queue)
            for body_id, value in zip(frame.ids, frame.values, strict=True):
                if not isinstance(body_id, int):
                    raise ConfigurationError("LIF input IDs must be numeric MaleCNS body IDs")
                self._external_drive[graph.dense_index(body_id)] = value

    def step_until(self, t_us: int) -> None:
        graph, parameters = self._require_ready()
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step LIF engine backward from {self._t_us} to {t_us}")
        while self._t_us < t_us:
            next_t = min(t_us, self._t_us + parameters.neural_dt_us)
            self._apply_inputs(next_t)
            dt_fraction = (next_t - self._t_us) / parameters.membrane_tau_us
            synaptic = np.zeros(graph.neuron_count, dtype=np.float32)
            active_edges = self._spikes[graph.source_indices]
            np.add.at(
                synaptic,
                graph.target_indices[active_edges],
                self._edge_weights[active_edges],
            )
            active = self._refractory_until <= self._t_us
            drive = (
                parameters.tonic_drive_mv
                + parameters.input_gain_mv * self._external_drive
                + synaptic
            )
            self._voltage[active] += dt_fraction * (
                parameters.resting_mv - self._voltage[active] + drive[active]
            )
            self._voltage[~active] = parameters.reset_mv
            self._spikes = active & (self._voltage >= parameters.threshold_mv)
            if np.any(self._spikes):
                spike_indices = np.flatnonzero(self._spikes).astype(np.uint32)
                self._spike_history.append((next_t, spike_indices))
                self._voltage[self._spikes] = parameters.reset_mv
                self._refractory_until[self._spikes] = next_t + parameters.refractory_us
            self._t_us = next_t

    def read_outputs(self, ids: tuple[str | int, ...], window_us: int) -> NeuralOutputFrame:
        graph, _ = self._require_ready()
        if window_us <= 0:
            raise ConfigurationError("Output window must be positive")
        cutoff = self._t_us - window_us
        counts = np.zeros(len(ids), dtype=np.uint32)
        requested = {
            graph.dense_index(identifier): index
            for index, identifier in enumerate(ids)
            if isinstance(identifier, int)
        }
        for spike_t, spike_indices in self._spike_history:
            if spike_t > cutoff:
                for dense_index in spike_indices:
                    output_index = requested.get(int(dense_index))
                    if output_index is not None:
                        counts[output_index] += 1
        rates = counts.astype(np.float64) / (window_us / 1_000_000.0)
        return NeuralOutputFrame(
            t_us=self._t_us,
            ids=ids,
            values=tuple(float(value) for value in rates),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="P/E",
            assumption_ids=("ND-LIF-01", "ND-03", "ND-04"),
            metadata={"backend": "numpy-lif-oracle", "window_us": window_us},
        )

    def checkpoint(self) -> dict[str, Any]:
        return {
            "t_us": self._t_us,
            "voltage_mv": self._voltage.tolist(),
            "refractory_until_us": self._refractory_until.tolist(),
            "backend": "numpy-lif-oracle",
        }

    def _require_ready(self) -> tuple[SparseConnectome, LIFParameters]:
        if self._graph is None or self._parameters is None:
            raise ConfigurationError("LIF engine is not initialized")
        return self._graph, self._parameters

