# SPDX-License-Identifier: GPL-2.0-or-later
"""Persistent direct-PyGeNN adapter for the full-graph Track A baseline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.connectome import SparseConnectome
from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError

TRACK_A_GENN_MODEL_VERSION = "3"
DEGREE_BUCKET_UPPER_BOUNDS = (64, 128, 256, 512, 1024, 2048, 4096, 8192)


@dataclass(frozen=True, slots=True)
class TrackAGeNNParameters:
    neural_dt_us: int
    resting_mv: float
    reset_mv: float
    threshold_mv: float
    membrane_tau_ms: float
    synapse_tau_ms: float
    refractory_ms: float
    synaptic_delay_ms: float
    synaptic_mv_per_contact: float
    central_entry_outgoing_gain: float
    tonic_drive_mv: float
    reset_synaptic_state_on_spike: bool

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> TrackAGeNNParameters:
        values = cls(**{name: raw[name] for name in cls.__dataclass_fields__})
        if min(
            values.neural_dt_us,
            values.membrane_tau_ms,
            values.synapse_tau_ms,
            values.refractory_ms,
            values.synaptic_delay_ms,
        ) <= 0:
            raise ConfigurationError("Track A GeNN time constants must be positive")
        if values.synaptic_mv_per_contact < 0:
            raise ConfigurationError("Track A synaptic scale cannot be negative")
        if values.central_entry_outgoing_gain < 1.0:
            raise ConfigurationError("Track A central-entry gain cannot be below one")
        if values.synaptic_delay_ms * 1000 % values.neural_dt_us != 0:
            raise ConfigurationError("Track A synaptic delay must align with the neural step")
        if values.delay_steps < 1:
            raise ConfigurationError(
                "Track A synaptic delay must be at least one neural step; GeNN cannot "
                "deliver a spike within the step that emitted it"
            )
        return values

    @property
    def dt_ms(self) -> float:
        return self.neural_dt_us / 1000.0

    @property
    def delay_steps(self) -> int:
        return round(self.synaptic_delay_ms / self.dt_ms)

    @property
    def axonal_delay_steps(self) -> int:
        """GeNN ``axonal_delay_steps`` that realises :attr:`delay_steps` of total delay.

        GeNN's generated code presents synaptic input to the postsynaptic neuron on the
        step after the presynaptic spike even with ``axonal_delay_steps = 0``. Assigning
        ``delay_steps`` therefore executed the registered 0.1 ms delay as 0.2 ms and put
        every GeNN backend one step behind NumPy and Brian2.
        """
        return self.delay_steps - 1

    @property
    def membrane_decay(self) -> float:
        return float(np.exp(-self.dt_ms / self.membrane_tau_ms))

    @property
    def synapse_decay(self) -> float:
        return float(np.exp(-self.dt_ms / self.synapse_tau_ms))

    @property
    def synaptic_voltage_coefficient(self) -> float:
        if np.isclose(self.synapse_tau_ms, self.membrane_tau_ms):
            return self.dt_ms * self.membrane_decay / self.membrane_tau_ms
        return float(
            self.synapse_tau_ms
            / (self.synapse_tau_ms - self.membrane_tau_ms)
            * (self.synapse_decay - self.membrane_decay)
        )

    @property
    def genn_refractory_ms(self) -> float:
        return self.refractory_ms - self.dt_ms


class TrackAGeNNEngine:
    """Keep one complete MaleCNS model loaded across every body exchange."""

    def __init__(self, build_path: Path, *, variant: str = "exact") -> None:
        self.build_path = build_path
        self.variant = variant
        self._t_us = 0
        self._graph: SparseConnectome | None = None
        self._parameters: TrackAGeNNParameters | None = None
        self._model: Any = None
        self._populations: tuple[Any, ...] = ()
        self._input_rates: tuple[Any, ...] = ()
        self._group_by_dense: np.ndarray | None = None
        self._local_by_dense: np.ndarray | None = None
        self._group_dense_indices: tuple[np.ndarray, ...] = ()
        self._sparse_layout: dict[str, Any] = {}
        self._last_counts: dict[int, float] = {}
        self._model_identity: str | None = None
        self._loaded = False

    @property
    def t_us(self) -> int:
        return self._t_us

    def initialize(self, graph: SparseConnectome, parameters: dict[str, Any], seed: int) -> None:
        from pygenn import GeNNModel, create_neuron_model, init_postsynaptic, init_weight_update

        graph.validate()
        values = TrackAGeNNParameters.from_mapping(parameters)
        signs = np.asarray(parameters.get("functional_edge_signs"), dtype=np.float32)
        if signs.shape != graph.contact_counts.shape:
            raise ConfigurationError("Track A edge signs do not align with the complete graph")
        if not np.all(np.isin(signs, (-1.0, 0.0, 1.0))):
            raise ConfigurationError("Track A functional signs must be -1, 0, or 1")
        entry_body_ids = tuple(int(value) for value in parameters.get("entry_body_ids", ()))
        if not entry_body_ids:
            raise ConfigurationError("Track A central-entry body IDs are required")
        entry_by_dense = np.zeros(graph.neuron_count, dtype=np.bool_)
        for body_id in entry_body_ids:
            entry_by_dense[graph.dense_index(body_id)] = True
        if self._loaded:
            raise ConfigurationError("Track A GeNN engine is already initialized")
        if "CUDA_PATH" not in os.environ:
            nvcc = shutil.which("nvcc")
            if nvcc is not None:
                os.environ["CUDA_PATH"] = str(Path(nvcc).resolve().parent.parent)

        reset_code = (
            "V = Vreset; SpikeCount += 1.0; "
            "RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac;"
        )
        if values.reset_synaptic_state_on_spike:
            reset_code = (
                "V = Vreset; G = 0.0; SpikeCount += 1.0; "
                "RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac;"
            )
        neuron_model = create_neuron_model(
            "MaleCNSTrackALIF",
            params=(
                "MembraneDecay",
                "SynapseDecay",
                "SynapticVoltageCoefficient",
                "Vrest",
                "Vreset",
                "Vthresh",
                "TauRefrac",
                "Tonic",
            ),
            vars=(
                ("V", "scalar"),
                ("G", "scalar"),
                ("RefracTime", "scalar"),
                ("SpikeCount", "scalar"),
                ("InputRateHz", "scalar"),
            ),
            sim_code="""
            if (RefracTime > 0.0) {
                RefracTime -= dt;
                V = Vreset;
            }
            else {
                const scalar oldG = G;
                const scalar baseline = Vrest + Tonic;
                V = baseline + ((V - baseline) * MembraneDecay)
                    + (oldG * SynapticVoltageCoefficient);
                G = oldG * SynapseDecay;
                G += Isyn;
            }
            """,
            threshold_condition_code=(
                "(InputRateHz > 0.0 && gennrand_uniform() < InputRateHz * dt / 1000.0) || "
                "(RefracTime <= 0.0 && V > Vthresh)"
            ),
            reset_code=reset_code,
        )
        identity = hashlib.sha256()
        identity.update(TRACK_A_GENN_MODEL_VERSION.encode())
        identity.update(graph.source_sha256.encode())
        identity.update(signs.astype("<f4", copy=False).tobytes())
        identity.update(np.asarray(sorted(entry_body_ids), dtype="<u8").tobytes())
        identity.update(
            json.dumps(
                {name: getattr(values, name) for name in values.__dataclass_fields__},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        # The random seed configures runtime RNG state but does not change the
        # generated CUDA model; all seeds of one graph/parameter variant share
        # the same compiled binary.
        identity.update(self.variant.encode())
        self._model_identity = identity.hexdigest()
        model = GeNNModel(
            "float",
            f"track_a_{self._model_identity[:12]}",
            backend="cuda",
            manual_device_id=0,
        )
        model.dt = values.dt_ms
        model.seed = seed
        # A single GeNN ragged projection would pad every source row to the
        # 11k-edge maximum out-degree. On MaleCNS this expands 25.6M logical
        # edges into about 1.85B slots. Disjoint degree buckets preserve the
        # exact graph while bounding the padding of every projection.
        out_degree = np.bincount(graph.source_indices, minlength=graph.neuron_count)
        group_by_dense = np.searchsorted(
            np.asarray(DEGREE_BUCKET_UPPER_BOUNDS), out_degree, side="right"
        ).astype(np.uint8)
        group_count = len(DEGREE_BUCKET_UPPER_BOUNDS) + 1
        group_dense_indices = tuple(
            np.flatnonzero(group_by_dense == group_index).astype(np.uint32)
            for group_index in range(group_count)
        )
        local_by_dense = np.empty(graph.neuron_count, dtype=np.uint32)
        populations: list[Any] = []
        neuron_params = {
            "MembraneDecay": values.membrane_decay,
            "SynapseDecay": values.synapse_decay,
            "SynapticVoltageCoefficient": values.synaptic_voltage_coefficient,
            "Vrest": values.resting_mv,
            "Vreset": values.reset_mv,
            "Vthresh": values.threshold_mv,
            "TauRefrac": values.genn_refractory_ms,
            "Tonic": values.tonic_drive_mv,
        }
        neuron_vars = {
            "V": values.resting_mv,
            "G": 0.0,
            "RefracTime": 0.0,
            "SpikeCount": 0.0,
            "InputRateHz": 0.0,
        }
        for group_index, dense_indices in enumerate(group_dense_indices):
            if dense_indices.size == 0:
                raise ConfigurationError(
                    f"Track A degree bucket {group_index} unexpectedly has no neurons"
                )
            local_by_dense[dense_indices] = np.arange(
                dense_indices.size, dtype=np.uint32
            )
            populations.append(
                model.add_neuron_population(
                    f"neurons_{group_index}",
                    int(dense_indices.size),
                    neuron_model,
                    neuron_params,
                    neuron_vars,
                )
            )

        logical_edges = 0
        padded_slots = 0
        projection_count = 0
        for source_group in range(group_count):
            source_selection = group_by_dense[graph.source_indices] == source_group
            source_dense = graph.source_indices[source_selection]
            target_dense = graph.target_indices[source_selection]
            source_signs = signs[source_selection]
            source_contacts = graph.contact_counts[source_selection]
            source_entry = entry_by_dense[graph.source_indices[source_selection]]
            for target_group in range(group_count):
                selection = group_by_dense[target_dense] == target_group
                edge_count = int(np.count_nonzero(selection))
                if edge_count == 0:
                    continue
                pre = local_by_dense[source_dense[selection]]
                post = local_by_dense[target_dense[selection]]
                weights = (
                    source_contacts[selection].astype(np.float32)
                    * source_signs[selection]
                    * np.float32(values.synaptic_mv_per_contact)
                    * np.where(
                        source_entry[selection],
                        np.float32(values.central_entry_outgoing_gain),
                        np.float32(1.0),
                    )
                )
                synapses = model.add_synapse_population(
                    f"edges_{source_group}_{target_group}",
                    "SPARSE",
                    populations[source_group],
                    populations[target_group],
                    init_weight_update("StaticPulse", {}, {"g": weights}),
                    init_postsynaptic("DeltaCurr"),
                )
                synapses.set_sparse_connections(pre, post)
                synapses.axonal_delay_steps = values.axonal_delay_steps
                logical_edges += edge_count
                padded_slots += (
                    int(synapses.max_connections)
                    * int(group_dense_indices[source_group].size)
                )
                projection_count += 1
        if logical_edges != graph.edge_count:
            raise ConfigurationError(
                f"Track A sparse layout retained {logical_edges} of {graph.edge_count} edges"
            )
        self.build_path.mkdir(parents=True, exist_ok=True)
        model.build(path_to_model=str(self.build_path), always_rebuild=False)
        model.load()
        self._graph = graph
        self._parameters = values
        self._model = model
        self._populations = tuple(populations)
        self._input_rates = tuple(pop.vars["InputRateHz"] for pop in populations)
        self._group_by_dense = group_by_dense
        self._local_by_dense = local_by_dense
        self._group_dense_indices = group_dense_indices
        self._sparse_layout = {
            "strategy": "out-degree-bucketed-disjoint-populations-v1",
            "degree_bucket_upper_bounds": list(DEGREE_BUCKET_UPPER_BOUNDS),
            "population_sizes": [int(indices.size) for indices in group_dense_indices],
            "projection_count": projection_count,
            "logical_edges": logical_edges,
            "padded_slots": padded_slots,
            "padding_factor": padded_slots / logical_edges,
            "central_entry_body_count": len(entry_body_ids),
            "central_entry_outgoing_gain": values.central_entry_outgoing_gain,
        }
        self._t_us = 0
        self._last_counts.clear()
        self._loaded = True

    def push_inputs(self, frame: NeuralInputFrame) -> None:
        graph, _ = self._require_ready()
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Track A input time {frame.t_us} does not match engine time {self._t_us}"
            )
        if frame.signal_type is not SignalType.FIRING_RATE or frame.units != "Hz":
            raise ConfigurationError("Track A GeNN inputs must be firing rates in Hz")
        assert self._group_by_dense is not None and self._local_by_dense is not None
        for variable in self._input_rates:
            variable.view.fill(0.0)
        for identifier, value in zip(frame.ids, frame.values, strict=True):
            if not isinstance(identifier, int):
                raise ConfigurationError("Track A GeNN input IDs must be numeric body IDs")
            if not np.isfinite(value) or value < 0.0:
                raise ConfigurationError("Track A input rates must be finite and nonnegative")
            dense_index = graph.dense_index(identifier)
            group_index = int(self._group_by_dense[dense_index])
            local_index = int(self._local_by_dense[dense_index])
            self._input_rates[group_index].view[local_index] = value
        for variable in self._input_rates:
            variable.push_to_device()

    def step_until(self, t_us: int) -> None:
        _, parameters = self._require_ready()
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step GeNN backward from {self._t_us} to {t_us}")
        delta_us = t_us - self._t_us
        if delta_us % parameters.neural_dt_us:
            raise CausalityError("Track A coupling boundary is not aligned to the neural step")
        for _ in range(delta_us // parameters.neural_dt_us):
            self._model.step_time()
        self._t_us = t_us

    def read_outputs(self, ids: tuple[str | int, ...], window_us: int) -> NeuralOutputFrame:
        graph, _ = self._require_ready()
        if window_us <= 0:
            raise ConfigurationError("Track A output window must be positive")
        if any(not isinstance(identifier, int) for identifier in ids):
            raise ConfigurationError("Track A GeNN output IDs must be numeric body IDs")
        assert self._group_by_dense is not None and self._local_by_dense is not None
        count_variables = tuple(pop.vars["SpikeCount"] for pop in self._populations)
        for variable in count_variables:
            variable.pull_from_device()
        values: list[float] = []
        for identifier in ids:
            assert isinstance(identifier, int)
            dense_index = graph.dense_index(identifier)
            group_index = int(self._group_by_dense[dense_index])
            local_index = int(self._local_by_dense[dense_index])
            cumulative = float(count_variables[group_index].view[local_index])
            previous = self._last_counts.get(identifier, 0.0)
            if cumulative < previous:
                raise CausalityError("Track A spike counter moved backward")
            values.append((cumulative - previous) / (window_us / 1_000_000.0))
            self._last_counts[identifier] = cumulative
        return NeuralOutputFrame(
            t_us=self._t_us,
            ids=ids,
            values=tuple(values),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="M/P/E",
            assumption_ids=("ND-01", "ND-02", "ND-03", "ND-04", "ND-05", "TRACKA-01"),
            metadata={
                "backend": "direct-pygenn-5.4",
                "model_identity": self._model_identity,
                "variant": self.variant,
                "window_us": window_us,
                "full_graph": True,
                "neurons": graph.neuron_count,
                "edges": graph.edge_count,
                "sparse_layout": self._sparse_layout,
                "physiological_default": False,
                "warning": "Shiu transmitter-only regression baseline; not fitted physiology",
            },
        )

    def checkpoint(self) -> dict[str, Any]:
        graph, _ = self._require_ready()
        return {
            "t_us": self._t_us,
            "backend": "direct-pygenn-5.4",
            "model_identity": self._model_identity,
            "variant": self.variant,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
            "sparse_layout": self._sparse_layout,
            "state_arrays_omitted": "optional Track A checkpoint is metadata-only",
        }

    def close(self) -> None:
        if self._loaded:
            self._model.unload()
            self._loaded = False

    def _require_ready(self) -> tuple[SparseConnectome, TrackAGeNNParameters]:
        if not self._loaded or self._graph is None or self._parameters is None:
            raise ConfigurationError("Track A GeNN engine is not initialized")
        return self._graph, self._parameters
