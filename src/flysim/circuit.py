# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded open-loop circuit experiments for Stage 1 neural validation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

from flysim.connectome import SparseConnectome
from flysim.errors import ConfigurationError, DatasetError, ReadinessError

STAGE1_GENN_MODEL_VERSION = "9"


@dataclass(frozen=True, slots=True)
class CircuitSelection:
    graph: SparseConnectome
    input_body_ids: tuple[int, ...]
    readout_body_ids: tuple[int, ...]
    unavailable_input_body_ids: tuple[int, ...]
    unavailable_readout_body_ids: tuple[int, ...]
    no_path_input_body_ids: tuple[int, ...]
    no_path_readout_body_ids: tuple[int, ...]
    shortest_path_hops: int
    full_graph_dense_indices: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "neurons": self.graph.neuron_count,
            "edges": self.graph.edge_count,
            "input_body_ids": list(self.input_body_ids),
            "readout_body_ids": list(self.readout_body_ids),
            "unavailable_input_body_ids": list(self.unavailable_input_body_ids),
            "unavailable_readout_body_ids": list(self.unavailable_readout_body_ids),
            "no_path_input_body_ids": list(self.no_path_input_body_ids),
            "no_path_readout_body_ids": list(self.no_path_readout_body_ids),
            "shortest_path_hops": self.shortest_path_hops,
            "selection": "all nodes and induced edges on directed shortest input-readout paths",
        }


@dataclass(frozen=True, slots=True)
class TransferLIFParameters:
    dt_ms: float
    duration_ms: float
    resting_mv: float
    reset_mv: float
    threshold_mv: float
    membrane_tau_ms: float
    synapse_tau_ms: float
    refractory_ms: float
    synaptic_delay_ms: float
    synaptic_mv_per_contact: float
    tonic_drive_mv: float
    reset_synaptic_state_on_spike: bool
    state_updater: str
    genn_precision: str

    @property
    def steps(self) -> int:
        return round(self.duration_ms / self.dt_ms)

    @property
    def delay_steps(self) -> int:
        return round(self.synaptic_delay_ms / self.dt_ms)

    @property
    def axonal_delay_steps(self) -> int:
        """GeNN ``axonal_delay_steps`` that realises :attr:`delay_steps` of total delay.

        GeNN delivers a spike to the postsynaptic population on the step after it is
        emitted even with ``axonal_delay_steps = 0``, so the registered delay maps to one
        fewer axonal step. Assigning ``delay_steps`` directly is what produced the
        systematic one-step GeNN offset recorded in the Stage 1 parity reports.
        """
        return self.delay_steps - 1

    @property
    def refractory_steps(self) -> int:
        return round(self.refractory_ms / self.dt_ms)

    def validate(self) -> None:
        positive = (
            self.dt_ms,
            self.duration_ms,
            self.membrane_tau_ms,
            self.synapse_tau_ms,
            self.refractory_ms,
            self.synaptic_delay_ms,
            self.synaptic_mv_per_contact,
        )
        if any(value <= 0 for value in positive):
            raise ConfigurationError("Stage 1 LIF time and scale parameters must be positive")
        if self.steps <= 0 or self.delay_steps <= 0:
            raise ConfigurationError("Stage 1 LIF schedule has no integration or delay steps")
        if self.refractory_ms <= self.dt_ms:
            raise ConfigurationError("Stage 1 refractory period must exceed one integration step")
        if self.state_updater != "source-faithful-linear":
            raise ConfigurationError(
                f"Unsupported Stage 1 state updater: {self.state_updater!r}"
            )
        if self.genn_precision not in {"float32-production", "float64-reference"}:
            raise ConfigurationError(
                f"Unsupported Stage 1 GeNN precision: {self.genn_precision!r}"
            )

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
        """Compensate GeNN's countdown convention to match Brian2's tick boundary."""
        return self.refractory_ms - self.dt_ms


@dataclass(frozen=True, slots=True)
class StimulusSchedule:
    input_indices: np.ndarray
    forced_spikes: np.ndarray
    frequency_hz: float
    seed: int
    dt_ms: float

    def identity(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.input_indices.astype("<u4", copy=False).tobytes())
        digest.update(np.packbits(self.forced_spikes, axis=None).tobytes())
        digest.update(f"{self.frequency_hz}:{self.seed}:{self.dt_ms}".encode())
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CircuitRun:
    backend: str
    spike_times_ms: np.ndarray
    spike_indices: np.ndarray
    readout_rates_hz: tuple[float, ...]
    schedule_sha256: str
    readout_voltage_mv: np.ndarray | None = None
    readout_synaptic_state_mv: np.ndarray | None = None
    state_sample_dt_ms: float | None = None

    def trace_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.spike_times_ms.astype("<f8", copy=False).tobytes())
        digest.update(self.spike_indices.astype("<u4", copy=False).tobytes())
        return digest.hexdigest()

    def as_dict(
        self,
        graph: SparseConnectome,
        readout_indices: np.ndarray,
        *,
        include_trace: bool = False,
    ) -> dict[str, Any]:
        first_spikes = [
            (
                float(np.min(self.spike_times_ms[self.spike_indices == index]))
                if np.any(self.spike_indices == index)
                else None
            )
            for index in readout_indices
        ]
        payload: dict[str, Any] = {
            "backend": self.backend,
            "spike_count": int(self.spike_times_ms.size),
            "readout_body_ids": [graph.body_id(int(index)) for index in readout_indices],
            "readout_rates_hz": list(self.readout_rates_hz),
            "readout_first_spike_ms": first_spikes,
            "schedule_sha256": self.schedule_sha256,
            "spike_trace_sha256": self.trace_sha256(),
        }
        if include_trace:
            payload["spike_trace"] = {
                "times_ms": self.spike_times_ms.tolist(),
                "dense_indices": self.spike_indices.tolist(),
            }
            if self.readout_voltage_mv is not None:
                if self.state_sample_dt_ms is None:
                    raise ConfigurationError("Readout state trace is missing its sample interval")
                payload["readout_state_trace"] = {
                    "sample_times_ms": (
                        (np.arange(self.readout_voltage_mv.shape[0]) + 1)
                        * self.state_sample_dt_ms
                    ).tolist(),
                    "voltage_mv": self.readout_voltage_mv.tolist(),
                    "synaptic_state_mv": (
                        self.readout_synaptic_state_mv.tolist()
                        if self.readout_synaptic_state_mv is not None
                        else None
                    ),
                }
        return payload


@dataclass(frozen=True, slots=True)
class PopulationScreenRun:
    """Readout rates from one batched, label-blind population screen."""

    population_names: tuple[str, ...]
    seed_labels: tuple[int, ...]
    readout_body_ids: tuple[int, ...]
    readout_rates_hz: np.ndarray
    total_spike_counts: np.ndarray
    finite_state: bool
    master_seed: int
    runtime_seconds: float
    model_identity: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "population_names": list(self.population_names),
            "seed_labels": list(self.seed_labels),
            "readout_body_ids": list(self.readout_body_ids),
            "readout_rates_hz": self.readout_rates_hz.tolist(),
            "total_spike_counts": self.total_spike_counts.tolist(),
            "finite_state": self.finite_state,
            "master_seed": self.master_seed,
            "runtime_seconds": self.runtime_seconds,
            "model_identity": self.model_identity,
        }


def _available_dense_indices(
    graph: SparseConnectome, body_ids: tuple[int, ...]
) -> tuple[np.ndarray, tuple[int, ...]]:
    available: list[int] = []
    unavailable: list[int] = []
    for body_id in body_ids:
        try:
            available.append(graph.dense_index(body_id))
        except KeyError:
            unavailable.append(body_id)
    return np.asarray(sorted(set(available)), dtype=np.uint32), tuple(sorted(unavailable))


def select_shortest_path_circuit(
    graph: SparseConnectome,
    input_body_ids: tuple[int, ...],
    readout_body_ids: tuple[int, ...],
    *,
    maximum_hops: int,
) -> CircuitSelection:
    """Retain all neurons and edges on the shortest directed input-to-readout paths."""
    graph.validate()
    if maximum_hops <= 0:
        raise ConfigurationError("maximum_hops must be positive")
    inputs, unavailable_inputs = _available_dense_indices(graph, input_body_ids)
    readouts, unavailable_readouts = _available_dense_indices(graph, readout_body_ids)
    if inputs.size == 0:
        raise ReadinessError("No requested input neurons are present in the production graph")
    if readouts.size == 0:
        raise ReadinessError("No requested readout neurons are present in the production graph")

    order = np.argsort(graph.source_indices, kind="stable")
    sources = graph.source_indices[order]
    targets = graph.target_indices[order]
    edge_starts = np.searchsorted(sources, np.arange(graph.neuron_count), side="left")
    edge_ends = np.searchsorted(sources, np.arange(graph.neuron_count), side="right")
    visited = np.zeros(graph.neuron_count, dtype=np.bool_)
    visited[inputs] = True
    layers: list[np.ndarray] = [inputs]
    reached = np.empty(0, dtype=np.uint32)

    for _ in range(maximum_hops):
        neighbours = [
            targets[edge_starts[int(source)] : edge_ends[int(source)]] for source in layers[-1]
        ]
        nonempty = [item for item in neighbours if item.size]
        if not nonempty:
            break
        next_layer = np.unique(np.concatenate(nonempty)).astype(np.uint32, copy=False)
        next_layer = next_layer[~visited[next_layer]]
        if next_layer.size == 0:
            break
        visited[next_layer] = True
        layers.append(next_layer)
        reached = np.intersect1d(next_layer, readouts, assume_unique=True).astype(np.uint32)
        if reached.size:
            break
    if reached.size == 0:
        raise ReadinessError(
            f"No directed input-to-readout path was found within {maximum_hops} hops"
        )

    relevant = reached
    selected_layers: list[np.ndarray] = [reached]
    for layer in reversed(layers[:-1]):
        keep: list[int] = []
        relevant_set = set(int(value) for value in relevant)
        for source in layer:
            outgoing = targets[edge_starts[int(source)] : edge_ends[int(source)]]
            if any(int(target) in relevant_set for target in outgoing):
                keep.append(int(source))
        kept = np.asarray(keep, dtype=np.uint32)
        if kept.size == 0:
            raise DatasetError("Shortest-path backtracking produced an empty predecessor layer")
        selected_layers.append(kept)
        relevant = kept

    full_dense = np.unique(np.concatenate(selected_layers)).astype(np.uint32, copy=False)
    selected_mask = np.zeros(graph.neuron_count, dtype=np.bool_)
    selected_mask[full_dense] = True
    edge_mask = selected_mask[graph.source_indices] & selected_mask[graph.target_indices]
    old_sources = graph.source_indices[edge_mask]
    old_targets = graph.target_indices[edge_mask]
    old_counts = graph.contact_counts[edge_mask]
    selected_body_ids = graph.body_ids[full_dense]
    body_order = np.argsort(selected_body_ids)
    sorted_full_dense = full_dense[body_order]
    sorted_body_ids = selected_body_ids[body_order].astype(np.uint64, copy=False)
    old_to_new = np.full(graph.neuron_count, np.iinfo(np.uint32).max, dtype=np.uint32)
    old_to_new[sorted_full_dense] = np.arange(sorted_full_dense.size, dtype=np.uint32)
    new_sources = old_to_new[old_sources]
    new_targets = old_to_new[old_targets]
    edge_order = np.lexsort((new_targets, new_sources))
    identity = hashlib.sha256()
    identity.update(graph.source_sha256.encode())
    identity.update(sorted_body_ids.astype("<u8", copy=False).tobytes())
    identity.update(str(len(layers) - 1).encode())
    circuit = SparseConnectome(
        body_ids=sorted_body_ids,
        source_indices=new_sources[edge_order].astype(np.uint32, copy=False),
        target_indices=new_targets[edge_order].astype(np.uint32, copy=False),
        contact_counts=old_counts[edge_order].astype(np.uint32, copy=False),
        source_release=f"{graph.source_release}:shortest-path-circuit",
        source_sha256=identity.hexdigest(),
    )
    circuit.validate()
    selected_dense_set = set(int(value) for value in sorted_full_dense)
    present_input_ids = tuple(
        body_id for body_id in input_body_ids if body_id not in unavailable_inputs
    )
    present_readout_ids = tuple(
        body_id for body_id in readout_body_ids if body_id not in unavailable_readouts
    )
    available_input_ids = tuple(
        body_id for body_id in present_input_ids if graph.dense_index(body_id) in selected_dense_set
    )
    available_readout_ids = tuple(
        body_id
        for body_id in present_readout_ids
        if graph.dense_index(body_id) in selected_dense_set
    )
    return CircuitSelection(
        graph=circuit,
        input_body_ids=available_input_ids,
        readout_body_ids=available_readout_ids,
        unavailable_input_body_ids=unavailable_inputs,
        unavailable_readout_body_ids=unavailable_readouts,
        no_path_input_body_ids=tuple(
            body_id for body_id in present_input_ids if body_id not in available_input_ids
        ),
        no_path_readout_body_ids=tuple(
            body_id for body_id in present_readout_ids if body_id not in available_readout_ids
        ),
        shortest_path_hops=len(layers) - 1,
        full_graph_dense_indices=tuple(int(value) for value in sorted_full_dense),
    )


def select_population_path_circuit(
    graph: SparseConnectome,
    input_populations: Mapping[str, tuple[int, ...]],
    readout_body_ids: tuple[int, ...],
    *,
    maximum_hops: int,
) -> CircuitSelection:
    """Select the union of each input body's shortest paths to either readout.

    Unlike :func:`select_shortest_path_circuit`, this does not stop when the first
    source reaches a readout. That distinction is required for a population screen
    whose source types sit at different graph distances.
    """
    graph.validate()
    if maximum_hops <= 0:
        raise ConfigurationError("maximum_hops must be positive")
    requested_inputs = tuple(
        sorted({body_id for values in input_populations.values() for body_id in values})
    )
    inputs, unavailable_inputs = _available_dense_indices(graph, requested_inputs)
    readouts, unavailable_readouts = _available_dense_indices(graph, readout_body_ids)
    if inputs.size == 0 or readouts.size == 0:
        raise ReadinessError("Population screen inputs or readouts are absent from the graph")

    reverse_distance = np.full(graph.neuron_count, maximum_hops + 1, dtype=np.int16)
    reverse_distance[readouts] = 0
    frontier = np.zeros(graph.neuron_count, dtype=np.bool_)
    frontier[readouts] = True
    for hop in range(1, maximum_hops + 1):
        edge_mask = frontier[graph.target_indices] & (
            reverse_distance[graph.source_indices] == maximum_hops + 1
        )
        sources = np.unique(graph.source_indices[edge_mask])
        if sources.size == 0:
            break
        reverse_distance[sources] = hop
        frontier.fill(False)
        frontier[sources] = True

    reachable_inputs = inputs[reverse_distance[inputs] <= maximum_hops]
    if reachable_inputs.size == 0:
        raise ReadinessError(
            f"No population-screen input reaches a readout within {maximum_hops} hops"
        )
    selected = np.zeros(graph.neuron_count, dtype=np.bool_)
    selected[readouts] = True
    selected[reachable_inputs] = True
    frontier.fill(False)
    frontier[reachable_inputs] = True
    maximum_distance = int(reverse_distance[reachable_inputs].max())
    for distance in range(maximum_distance, 0, -1):
        layer_sources = np.flatnonzero(
            frontier & (reverse_distance == distance)
        ).astype(np.uint32)
        if layer_sources.size == 0:
            continue
        edge_mask = np.isin(graph.source_indices, layer_sources) & (
            reverse_distance[graph.target_indices] == distance - 1
        )
        targets = np.unique(graph.target_indices[edge_mask])
        selected[targets] = True
        frontier[targets] = True

    full_dense = np.flatnonzero(selected).astype(np.uint32)
    induced_edges = selected[graph.source_indices] & selected[graph.target_indices]
    old_sources = graph.source_indices[induced_edges]
    old_targets = graph.target_indices[induced_edges]
    old_counts = graph.contact_counts[induced_edges]
    selected_body_ids = graph.body_ids[full_dense]
    body_order = np.argsort(selected_body_ids)
    sorted_full_dense = full_dense[body_order]
    sorted_body_ids = selected_body_ids[body_order].astype(np.uint64, copy=False)
    old_to_new = np.full(graph.neuron_count, np.iinfo(np.uint32).max, dtype=np.uint32)
    old_to_new[sorted_full_dense] = np.arange(sorted_full_dense.size, dtype=np.uint32)
    new_sources = old_to_new[old_sources]
    new_targets = old_to_new[old_targets]
    edge_order = np.lexsort((new_targets, new_sources))
    identity = hashlib.sha256()
    identity.update(graph.source_sha256.encode())
    identity.update(sorted_body_ids.astype("<u8", copy=False).tobytes())
    identity.update(str(maximum_hops).encode())
    circuit = SparseConnectome(
        body_ids=sorted_body_ids,
        source_indices=new_sources[edge_order].astype(np.uint32, copy=False),
        target_indices=new_targets[edge_order].astype(np.uint32, copy=False),
        contact_counts=old_counts[edge_order].astype(np.uint32, copy=False),
        source_release=f"{graph.source_release}:population-shortest-path-union",
        source_sha256=identity.hexdigest(),
    )
    circuit.validate()
    reachable_set = set(int(value) for value in reachable_inputs)
    present_inputs = tuple(
        body_id for body_id in requested_inputs if body_id not in unavailable_inputs
    )
    return CircuitSelection(
        graph=circuit,
        input_body_ids=tuple(
            body_id
            for body_id in present_inputs
            if graph.dense_index(body_id) in reachable_set
        ),
        readout_body_ids=tuple(
            body_id for body_id in readout_body_ids if body_id not in unavailable_readouts
        ),
        unavailable_input_body_ids=unavailable_inputs,
        unavailable_readout_body_ids=unavailable_readouts,
        no_path_input_body_ids=tuple(
            body_id
            for body_id in present_inputs
            if graph.dense_index(body_id) not in reachable_set
        ),
        no_path_readout_body_ids=(),
        shortest_path_hops=maximum_distance,
        full_graph_dense_indices=tuple(int(value) for value in sorted_full_dense),
    )


def load_cell_types(annotations_path: Path, body_ids: np.ndarray) -> tuple[str, ...]:
    table = feather.read_table(annotations_path, columns=("bodyId", "type"), memory_map=True)
    selected = table.filter(
        pc.is_in(
            pc.cast(table["bodyId"], pa.uint64()),
            value_set=pa.array(body_ids, type=pa.uint64()),
        )
    )
    by_body = {int(row["bodyId"]): str(row["type"] or "") for row in selected.to_pylist()}
    return tuple(by_body.get(int(body_id), "") for body_id in body_ids)


def _new_graph(
    graph: SparseConnectome,
    sources: np.ndarray,
    targets: np.ndarray,
    counts: np.ndarray,
    variant: str,
) -> SparseConnectome:
    order = np.lexsort((targets, sources))
    identity = hashlib.sha256()
    identity.update(graph.source_sha256.encode())
    identity.update(variant.encode())
    identity.update(sources[order].astype("<u4", copy=False).tobytes())
    identity.update(targets[order].astype("<u4", copy=False).tobytes())
    identity.update(counts[order].astype("<u4", copy=False).tobytes())
    result = SparseConnectome(
        body_ids=graph.body_ids.copy(),
        source_indices=sources[order].astype(np.uint32, copy=False),
        target_indices=targets[order].astype(np.uint32, copy=False),
        contact_counts=counts[order].astype(np.uint32, copy=False),
        source_release=f"{graph.source_release}:{variant}",
        source_sha256=identity.hexdigest(),
    )
    result.validate()
    return result


def build_control_graph(
    graph: SparseConnectome,
    variant: str,
    *,
    cell_types: tuple[str, ...],
    seed: int,
    weak_edge_max_contacts: int,
    silenced_body_ids: tuple[int, ...] = (),
) -> SparseConnectome:
    """Build reversible controls without changing the canonical graph."""
    graph.validate()
    if len(cell_types) != graph.neuron_count:
        raise ConfigurationError("cell_types must align one-to-one with circuit neurons")
    rng = np.random.default_rng(seed)
    sources = np.asarray(graph.source_indices)
    targets = np.asarray(graph.target_indices)
    counts = np.asarray(graph.contact_counts)
    if variant == "exact":
        return graph
    if variant == "shuffled-connectivity":
        return _new_graph(graph, sources, rng.permutation(targets), counts, variant)
    if variant == "uniform-weights":
        uniform = max(1, round(float(np.median(counts))))
        return _new_graph(
            graph, sources, targets, np.full_like(counts, uniform), variant
        )
    if variant == "randomized-weights":
        return _new_graph(graph, sources, targets, rng.permutation(counts), variant)
    if variant == "weak-edge-dropout":
        keep = counts > weak_edge_max_contacts
        if not np.any(keep):
            raise ConfigurationError("Weak-edge dropout removed every circuit edge")
        return _new_graph(graph, sources[keep], targets[keep], counts[keep], variant)
    if variant == "silenced-cb0496":
        available, unavailable = _available_dense_indices(graph, silenced_body_ids)
        if unavailable or available.size == 0:
            raise ReadinessError("The CB0496 silencing population is unavailable in MaleCNS")
        keep = ~np.isin(sources, available)
        return _new_graph(graph, sources[keep], targets[keep], counts[keep], variant)
    if variant != "cell-type-only":
        raise ConfigurationError(f"Unsupported circuit control: {variant}")

    labels = tuple(
        value if value else f"untyped-body-{graph.body_id(index)}"
        for index, value in enumerate(cell_types)
    )
    pair_counts: dict[tuple[str, str], list[int]] = {}
    for source, target, count in zip(sources, targets, counts, strict=True):
        pair_counts.setdefault((labels[int(source)], labels[int(target)]), []).append(int(count))
    type_members: dict[str, np.ndarray] = {
        label: np.flatnonzero(np.asarray(labels) == label).astype(np.uint32)
        for label in set(labels)
    }
    generated_sources: list[np.ndarray] = []
    generated_targets: list[np.ndarray] = []
    generated_counts: list[np.ndarray] = []
    for (source_type, target_type), values in pair_counts.items():
        source_members = type_members[source_type]
        target_members = type_members[target_type]
        pair_sources = np.repeat(source_members, target_members.size)
        pair_targets = np.tile(target_members, source_members.size)
        if source_type == target_type:
            keep = pair_sources != pair_targets
            pair_sources = pair_sources[keep]
            pair_targets = pair_targets[keep]
        if pair_sources.size == 0:
            continue
        mean_count = max(1, round(float(np.mean(values))))
        generated_sources.append(pair_sources)
        generated_targets.append(pair_targets)
        generated_counts.append(np.full(pair_sources.size, mean_count, dtype=np.uint32))
    if not generated_sources:
        raise ConfigurationError("Cell-type-only control generated no edges")
    return _new_graph(
        graph,
        np.concatenate(generated_sources),
        np.concatenate(generated_targets),
        np.concatenate(generated_counts),
        variant,
    )


def make_stimulus_schedule(
    graph: SparseConnectome,
    input_body_ids: tuple[int, ...],
    *,
    frequency_hz: float,
    parameters: TransferLIFParameters,
    seed: int,
) -> StimulusSchedule:
    parameters.validate()
    if not 0 < frequency_hz <= 1000.0 / parameters.dt_ms:
        raise ConfigurationError("Stimulus frequency is outside the discrete schedule range")
    input_indices = np.asarray(
        [graph.dense_index(body_id) for body_id in input_body_ids], dtype=np.uint32
    )
    rng = np.random.default_rng(seed)
    probability = frequency_hz * parameters.dt_ms / 1000.0
    forced = rng.random((parameters.steps, input_indices.size)) < probability
    return StimulusSchedule(
        input_indices=input_indices,
        forced_spikes=forced,
        frequency_hz=frequency_hz,
        seed=seed,
        dt_ms=parameters.dt_ms,
    )


def _readout_rates(
    spike_indices: np.ndarray, readout_indices: np.ndarray, duration_ms: float
) -> tuple[float, ...]:
    return tuple(
        float(np.count_nonzero(spike_indices == index) * 1000.0 / duration_ms)
        for index in readout_indices
    )


def _functional_edge_weights(
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    parameters: TransferLIFParameters,
    edge_scale_multipliers: np.ndarray | None,
    *,
    dtype: np.dtype[Any],
) -> np.ndarray:
    if edge_signs.shape != graph.contact_counts.shape:
        raise ConfigurationError("edge_signs must align with circuit edges")
    multipliers = (
        np.ones(graph.edge_count, dtype=np.float64)
        if edge_scale_multipliers is None
        else np.asarray(edge_scale_multipliers, dtype=np.float64)
    )
    if multipliers.shape != graph.contact_counts.shape:
        raise ConfigurationError("edge_scale_multipliers must align with circuit edges")
    if np.any(~np.isfinite(multipliers)) or np.any(multipliers < 0.0):
        raise ConfigurationError("edge_scale_multipliers must be finite and nonnegative")
    return np.asarray(
        graph.contact_counts.astype(dtype)
        * edge_signs.astype(dtype)
        * multipliers.astype(dtype)
        * parameters.synaptic_mv_per_contact,
        dtype=dtype,
    )


def run_numpy_circuit(
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    schedule: StimulusSchedule,
    parameters: TransferLIFParameters,
    readout_body_ids: tuple[int, ...],
    edge_scale_multipliers: np.ndarray | None = None,
) -> CircuitRun:
    """Run the source-faithful linear update with an explicit causal schedule."""
    graph.validate()
    parameters.validate()
    if schedule.forced_spikes.shape != (parameters.steps, schedule.input_indices.size):
        raise ConfigurationError("Stimulus schedule shape does not match the experiment")
    voltage = np.full(graph.neuron_count, parameters.resting_mv, dtype=np.float64)
    synaptic_state = np.zeros(graph.neuron_count, dtype=np.float64)
    refractory_until = np.zeros(graph.neuron_count, dtype=np.int64)
    queue = np.zeros((parameters.delay_steps + 1, graph.neuron_count), dtype=np.float64)
    weights = _functional_edge_weights(
        graph,
        edge_signs,
        parameters,
        edge_scale_multipliers,
        dtype=np.dtype(np.float64),
    )
    sources = np.asarray(graph.source_indices)
    targets = np.asarray(graph.target_indices)
    edge_starts = np.searchsorted(sources, np.arange(graph.neuron_count), side="left")
    edge_ends = np.searchsorted(sources, np.arange(graph.neuron_count), side="right")
    spike_times: list[float] = []
    spike_indices: list[int] = []
    readouts = np.asarray(
        [graph.dense_index(body_id) for body_id in readout_body_ids], dtype=np.uint32
    )
    readout_voltage = np.empty((parameters.steps, readouts.size), dtype=np.float64)
    readout_synaptic_state = np.empty_like(readout_voltage)
    for step in range(parameters.steps):
        queue_slot = step % queue.shape[0]
        arrivals = queue[queue_slot].copy()
        queue[queue_slot].fill(0.0)
        active = refractory_until <= step
        active_synaptic_state = synaptic_state[active].copy()
        baseline_mv = parameters.resting_mv + parameters.tonic_drive_mv
        voltage[active] = (
            baseline_mv
            + (voltage[active] - baseline_mv) * parameters.membrane_decay
            + active_synaptic_state * parameters.synaptic_voltage_coefficient
        )
        synaptic_state[active] = active_synaptic_state * parameters.synapse_decay
        voltage[~active] = parameters.reset_mv
        spikes = active & (voltage > parameters.threshold_mv)
        forced_indices = schedule.input_indices[schedule.forced_spikes[step]]
        spikes[forced_indices] = True
        # Brian2's default schedule applies delayed on_pre events after the
        # state and threshold updates, but before reset processing.
        # Brian2's ``unless refractory`` flag also guards synaptic writes to
        # the marked state variable, so arrivals to refractory cells are lost.
        synaptic_state[active] += arrivals[active]
        current = np.flatnonzero(spikes).astype(np.uint32)
        if current.size:
            end_time = (step + 1) * parameters.dt_ms
            spike_times.extend([end_time] * current.size)
            spike_indices.extend(int(value) for value in current)
            delivery_slot = (step + parameters.delay_steps) % queue.shape[0]
            for source in current:
                start = edge_starts[int(source)]
                end = edge_ends[int(source)]
                if start != end:
                    np.add.at(queue[delivery_slot], targets[start:end], weights[start:end])
            voltage[current] = parameters.reset_mv
            if parameters.reset_synaptic_state_on_spike:
                synaptic_state[current] = 0.0
            refractory_until[current] = step + parameters.refractory_steps
            refractory_until[forced_indices] = step
        readout_voltage[step] = voltage[readouts]
        readout_synaptic_state[step] = synaptic_state[readouts]
    times = np.asarray(spike_times, dtype=np.float64)
    indices = np.asarray(spike_indices, dtype=np.uint32)
    return CircuitRun(
        backend="numpy",
        spike_times_ms=times,
        spike_indices=indices,
        readout_rates_hz=_readout_rates(indices, readouts, parameters.duration_ms),
        schedule_sha256=schedule.identity(),
        readout_voltage_mv=readout_voltage,
        readout_synaptic_state_mv=readout_synaptic_state,
        state_sample_dt_ms=parameters.dt_ms,
    )


def run_brian2_circuit(
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    schedule: StimulusSchedule,
    parameters: TransferLIFParameters,
    readout_body_ids: tuple[int, ...],
    edge_scale_multipliers: np.ndarray | None = None,
) -> CircuitRun:
    """Run the transferred circuit with Brian2 using the same forced-spike schedule."""
    import brian2 as b2

    graph.validate()
    parameters.validate()
    brian_input_indices = schedule.input_indices.astype(np.int64, copy=False)
    forced = np.zeros((parameters.steps, graph.neuron_count), dtype=np.float64)
    forced[:, brian_input_indices] = schedule.forced_spikes
    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = parameters.dt_ms * b2.ms
    stimulus = b2.TimedArray(forced, dt=parameters.dt_ms * b2.ms)
    reset_rule = "v = reset; g = 0 * volt"
    if not parameters.reset_synaptic_state_on_spike:
        reset_rule = "v = reset"
    neurons = b2.NeuronGroup(
        graph.neuron_count,
        """
        dv/dt = (rest - v + g + tonic) / tau_m : volt (unless refractory)
        dg/dt = -g / tau_syn : volt (unless refractory)
        rfc : second
        """,
        threshold="(v > threshold) or (stimulus(t, i) > 0.5)",
        reset=reset_rule,
        refractory="rfc",
        method="linear",
        namespace={
            "rest": parameters.resting_mv * b2.mV,
            "reset": parameters.reset_mv * b2.mV,
            "threshold": parameters.threshold_mv * b2.mV,
            "tau_m": parameters.membrane_tau_ms * b2.ms,
            "tau_syn": parameters.synapse_tau_ms * b2.ms,
            "tonic": parameters.tonic_drive_mv * b2.mV,
            "stimulus": stimulus,
        },
    )
    neurons.v = parameters.resting_mv * b2.mV
    neurons.g = 0.0 * b2.mV
    neurons.rfc = parameters.refractory_ms * b2.ms
    neurons.rfc[brian_input_indices] = 0.0 * b2.ms
    synapses = b2.Synapses(neurons, neurons, model="w : volt", on_pre="g_post += w")
    synapses.connect(
        i=graph.source_indices.astype(np.int64, copy=False),
        j=graph.target_indices.astype(np.int64, copy=False),
    )
    synapses.w = (
        _functional_edge_weights(
            graph,
            edge_signs,
            parameters,
            edge_scale_multipliers,
            dtype=np.dtype(np.float64),
        )
        * b2.mV
    )
    synapses.delay = parameters.synaptic_delay_ms * b2.ms
    monitor = b2.SpikeMonitor(neurons)
    readouts = np.asarray(
        [graph.dense_index(body_id) for body_id in readout_body_ids], dtype=np.uint32
    )
    state_monitor = b2.StateMonitor(
        neurons,
        ("v", "g"),
        record=readouts.astype(np.int64, copy=False),
        when="end",
    )
    b2.run(parameters.duration_ms * b2.ms)
    times = np.asarray(monitor.t / b2.ms, dtype=np.float64) + parameters.dt_ms
    indices = np.asarray(monitor.i, dtype=np.uint32)
    return CircuitRun(
        backend="brian2",
        spike_times_ms=times,
        spike_indices=indices,
        readout_rates_hz=_readout_rates(indices, readouts, parameters.duration_ms),
        schedule_sha256=schedule.identity(),
        readout_voltage_mv=np.asarray(state_monitor.v / b2.mV, dtype=np.float64).T,
        readout_synaptic_state_mv=np.asarray(
            state_monitor.g / b2.mV, dtype=np.float64
        ).T,
        state_sample_dt_ms=parameters.dt_ms,
    )


def run_genn_circuit(
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    schedule: StimulusSchedule,
    parameters: TransferLIFParameters,
    readout_body_ids: tuple[int, ...],
    build_path: Path,
    edge_scale_multipliers: np.ndarray | None = None,
) -> CircuitRun:
    """Run the transferred circuit with direct PyGeNN on CUDA."""
    from pygenn import (
        GeNNModel,
        create_neuron_model,
        init_postsynaptic,
        init_weight_update,
    )

    graph.validate()
    parameters.validate()
    reset_code = "V = Vreset; RefracTime = InputCell > 0.5 ? 0.0 : TauRefrac;"
    if parameters.reset_synaptic_state_on_spike:
        reset_code = (
            "V = Vreset; G = 0.0; "
            "RefracTime = InputCell > 0.5 ? 0.0 : TauRefrac;"
        )
    neuron_model = create_neuron_model(
        "MaleCNSStage1LIF",
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
            ("Forced", "scalar"),
            ("InputCell", "scalar"),
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
        threshold_condition_code="Forced > 0.5 || (RefracTime <= 0.0 && V > Vthresh)",
        reset_code=reset_code,
    )
    if "CUDA_PATH" not in os.environ:
        nvcc = shutil.which("nvcc")
        if nvcc is not None:
            os.environ["CUDA_PATH"] = str(Path(nvcc).resolve().parent.parent)
    identity = hashlib.sha256()
    identity.update(STAGE1_GENN_MODEL_VERSION.encode())
    identity.update(graph.source_sha256.encode())
    identity.update(schedule.identity().encode())
    identity.update(
        json.dumps(asdict(parameters), sort_keys=True, separators=(",", ":")).encode()
    )
    if edge_scale_multipliers is not None:
        identity.update(np.asarray(edge_scale_multipliers, dtype="<f8").tobytes())
    scalar_type = "double" if parameters.genn_precision == "float64-reference" else "float"
    numpy_dtype = np.float64 if scalar_type == "double" else np.float32
    model = GeNNModel(scalar_type, f"stage1_{identity.hexdigest()[:12]}", backend="cuda")
    model.dt = parameters.dt_ms
    input_cells = np.zeros(graph.neuron_count, dtype=numpy_dtype)
    input_cells[schedule.input_indices] = 1.0
    population = model.add_neuron_population(
        "neurons",
        graph.neuron_count,
        neuron_model,
        {
            "MembraneDecay": parameters.membrane_decay,
            "SynapseDecay": parameters.synapse_decay,
            "SynapticVoltageCoefficient": parameters.synaptic_voltage_coefficient,
            "Vrest": parameters.resting_mv,
            "Vreset": parameters.reset_mv,
            "Vthresh": parameters.threshold_mv,
            "TauRefrac": parameters.genn_refractory_ms,
            "Tonic": parameters.tonic_drive_mv,
        },
        {
            "V": parameters.resting_mv,
            "G": 0.0,
            "RefracTime": 0.0,
            "Forced": 0.0,
            "InputCell": input_cells,
        },
    )
    population.spike_recording_enabled = True
    weights = _functional_edge_weights(
        graph,
        edge_signs,
        parameters,
        edge_scale_multipliers,
        dtype=np.dtype(numpy_dtype),
    )
    synapses = model.add_synapse_population(
        "edges",
        "SPARSE",
        population,
        population,
        init_weight_update("StaticPulse", {}, {"g": weights}),
        init_postsynaptic("DeltaCurr"),
    )
    synapses.set_sparse_connections(graph.source_indices, graph.target_indices)
    synapses.axonal_delay_steps = parameters.axonal_delay_steps
    build_path.mkdir(parents=True, exist_ok=True)
    model.build(path_to_model=str(build_path), always_rebuild=False)
    model.load(num_recording_timesteps=parameters.steps)
    forced_view = population.vars["Forced"]
    for step in range(parameters.steps):
        forced_view.view.fill(0.0)
        forced_view.view[schedule.input_indices] = schedule.forced_spikes[step]
        forced_view.push_to_device()
        model.step_time()
    model.pull_recording_buffers_from_device()
    recorded = population.spike_recording_data
    if len(recorded) != 1:
        raise RuntimeError(f"Expected one GeNN recording batch, got {len(recorded)}")
    times, indices = recorded[0]
    model.unload()
    # GeNN labels a spike with the start of the integration interval that produced it,
    # while the NumPy oracle and the Brian2 adapter both label it with the end of that
    # interval. `neural_parity.run_genn` already corrects for this; this adapter did not,
    # and the resulting one-step offset was masked in the Stage 1 reports by the separate
    # axonal-delay defect pushing GeNN one step the other way. Fixing the delay alone
    # would have left a real one-step disagreement in place.
    spike_times = np.asarray(times, dtype=np.float64) + parameters.dt_ms
    spike_indices = np.asarray(indices, dtype=np.uint32)
    readouts = np.asarray(
        [graph.dense_index(body_id) for body_id in readout_body_ids], dtype=np.uint32
    )
    return CircuitRun(
        backend="genn",
        spike_times_ms=spike_times,
        spike_indices=spike_indices,
        readout_rates_hz=_readout_rates(spike_indices, readouts, parameters.duration_ms),
        schedule_sha256=schedule.identity(),
    )


def run_genn_population_screen(
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    input_populations: Mapping[str, tuple[int, ...]],
    parameters: TransferLIFParameters,
    readout_body_ids: tuple[int, ...],
    *,
    frequency_hz: float,
    seed_labels: tuple[int, ...],
    master_seed: int,
    build_path: Path,
) -> PopulationScreenRun:
    """Execute all source populations and trials in one direct-PyGeNN batch.

    Source labels and biological outcomes are deliberately absent from this
    interface. GeNN gives every batch/neuron pair an independent RNG stream rooted
    in ``master_seed``; ``seed_labels`` are stable trial identifiers and ordering.
    """
    from pygenn import (
        GeNNModel,
        VarAccess,
        create_neuron_model,
        init_postsynaptic,
        init_weight_update,
    )

    graph.validate()
    parameters.validate()
    if not input_populations or not seed_labels:
        raise ConfigurationError("Population screen requires populations and seed labels")
    if not 0.0 < frequency_hz <= 1000.0 / parameters.dt_ms:
        raise ConfigurationError("Population-screen input frequency is invalid")
    if edge_signs.shape != (graph.edge_count,):
        raise ConfigurationError("Population-screen edge signs do not align with the graph")

    population_names = tuple(input_populations)
    batch_size = len(population_names) * len(seed_labels)
    input_mask = np.zeros((batch_size, graph.neuron_count), dtype=np.float32)
    for population_index, name in enumerate(population_names):
        indices = np.asarray(
            [graph.dense_index(body_id) for body_id in input_populations[name]],
            dtype=np.uint32,
        )
        for seed_index in range(len(seed_labels)):
            batch = population_index * len(seed_labels) + seed_index
            input_mask[batch, indices] = 1.0

    reset_code = (
        "V = Vreset; SpikeCount += 1.0; "
        "RefracTime = InputCell > 0.5 ? 0.0 : TauRefrac;"
    )
    if parameters.reset_synaptic_state_on_spike:
        reset_code = (
            "V = Vreset; G = 0.0; SpikeCount += 1.0; "
            "RefracTime = InputCell > 0.5 ? 0.0 : TauRefrac;"
        )
    neuron_model = create_neuron_model(
        "MaleCNSStage1BatchedLIF",
        params=(
            "MembraneDecay",
            "SynapseDecay",
            "SynapticVoltageCoefficient",
            "Vrest",
            "Vreset",
            "Vthresh",
            "TauRefrac",
            "Tonic",
            "InputProbability",
        ),
        vars=(
            ("V", "scalar"),
            ("G", "scalar"),
            ("RefracTime", "scalar"),
            ("SpikeCount", "scalar"),
            ("InputCell", "scalar", VarAccess.READ_ONLY_DUPLICATE),
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
            "(InputCell > 0.5 && gennrand_uniform() < InputProbability) || "
            "(RefracTime <= 0.0 && V > Vthresh)"
        ),
        reset_code=reset_code,
    )
    if "CUDA_PATH" not in os.environ:
        nvcc = shutil.which("nvcc")
        if nvcc is not None:
            os.environ["CUDA_PATH"] = str(Path(nvcc).resolve().parent.parent)
    build_identity = hashlib.sha256()
    build_identity.update((STAGE1_GENN_MODEL_VERSION + ":population-screen-v1").encode())
    build_identity.update(graph.source_sha256.encode())
    build_identity.update(np.asarray(edge_signs, dtype="<f4").tobytes())
    build_identity.update(str(batch_size).encode())
    build_identity.update(
        json.dumps(asdict(parameters), sort_keys=True, separators=(",", ":")).encode()
    )
    identity = hashlib.sha256()
    identity.update(build_identity.digest())
    identity.update(json.dumps(population_names, separators=(",", ":")).encode())
    identity.update(np.packbits(input_mask > 0.5, axis=None).tobytes())
    identity.update(json.dumps(seed_labels, separators=(",", ":")).encode())
    identity.update(f"{frequency_hz}:{master_seed}".encode())
    model_identity = identity.hexdigest()
    scalar_type = "double" if parameters.genn_precision == "float64-reference" else "float"
    numpy_dtype = np.float64 if scalar_type == "double" else np.float32
    model = GeNNModel(
        scalar_type,
        f"stage1_screen_{build_identity.hexdigest()[:12]}",
        backend="cuda",
    )
    model.dt = parameters.dt_ms
    model.batch_size = batch_size
    model.seed = master_seed
    population = model.add_neuron_population(
        "neurons",
        graph.neuron_count,
        neuron_model,
        {
            "MembraneDecay": parameters.membrane_decay,
            "SynapseDecay": parameters.synapse_decay,
            "SynapticVoltageCoefficient": parameters.synaptic_voltage_coefficient,
            "Vrest": parameters.resting_mv,
            "Vreset": parameters.reset_mv,
            "Vthresh": parameters.threshold_mv,
            "TauRefrac": parameters.genn_refractory_ms,
            "Tonic": parameters.tonic_drive_mv,
            "InputProbability": frequency_hz * parameters.dt_ms / 1000.0,
        },
        {
            "V": parameters.resting_mv,
            "G": 0.0,
            "RefracTime": 0.0,
            "SpikeCount": 0.0,
            "InputCell": input_mask.astype(numpy_dtype, copy=False),
        },
    )
    weights = _functional_edge_weights(
        graph, edge_signs, parameters, None, dtype=np.dtype(numpy_dtype)
    )
    synapses = model.add_synapse_population(
        "edges",
        "SPARSE",
        population,
        population,
        init_weight_update("StaticPulse", {}, {"g": weights}),
        init_postsynaptic("DeltaCurr"),
    )
    synapses.set_sparse_connections(graph.source_indices, graph.target_indices)
    synapses.axonal_delay_steps = parameters.axonal_delay_steps
    build_path.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model.build(path_to_model=str(build_path), always_rebuild=False)
    model.load()
    try:
        for _ in range(parameters.steps):
            model.step_time()
        for name in ("SpikeCount", "V", "G"):
            population.vars[name].pull_from_device()
        # GeNN owns these host views; detach every array before ``unload`` frees
        # the backing allocation. Counts already change dtype, but keep the copy
        # explicit so a future precision change cannot reintroduce a dangling view.
        counts = np.array(population.vars["SpikeCount"].view, dtype=np.float64, copy=True)
        voltage = np.array(population.vars["V"].view, copy=True)
        synaptic_state = np.array(population.vars["G"].view, copy=True)
    finally:
        model.unload()
    runtime_seconds = time.perf_counter() - started
    readout_indices = np.asarray(
        [graph.dense_index(body_id) for body_id in readout_body_ids], dtype=np.uint32
    )
    readout_counts = counts[:, readout_indices]
    rates = readout_counts / (parameters.duration_ms / 1000.0)
    rates = rates.reshape(len(population_names), len(seed_labels), len(readout_body_ids))
    total_counts = counts.sum(axis=1).reshape(len(population_names), len(seed_labels))
    return PopulationScreenRun(
        population_names=population_names,
        seed_labels=seed_labels,
        readout_body_ids=readout_body_ids,
        readout_rates_hz=rates,
        total_spike_counts=total_counts,
        finite_state=bool(
            np.all(np.isfinite(counts))
            and np.all(np.isfinite(voltage))
            and np.all(np.isfinite(synaptic_state))
        ),
        master_seed=master_seed,
        runtime_seconds=runtime_seconds,
        model_identity=model_identity,
    )


def compare_backend_runs(
    reference: CircuitRun,
    candidate: CircuitRun,
    *,
    spike_time_tolerance_ms: float,
    rate_relative_tolerance: float,
) -> dict[str, Any]:
    reference_counts = np.bincount(reference.spike_indices.astype(np.int64))
    candidate_counts = np.bincount(candidate.spike_indices.astype(np.int64))
    count_size = max(reference_counts.size, candidate_counts.size)
    reference_counts = np.pad(reference_counts, (0, count_size - reference_counts.size))
    candidate_counts = np.pad(candidate_counts, (0, count_size - candidate_counts.size))
    count_differences = [
        {
            "dense_index": int(index),
            "reference_spikes": int(reference_counts[index]),
            "candidate_spikes": int(candidate_counts[index]),
            "delta": int(candidate_counts[index] - reference_counts[index]),
        }
        for index in np.flatnonzero(reference_counts != candidate_counts)
    ]
    same_count = reference.spike_indices.size == candidate.spike_indices.size
    reference_order = np.lexsort((reference.spike_times_ms, reference.spike_indices))
    candidate_order = np.lexsort((candidate.spike_times_ms, candidate.spike_indices))
    same_ids = same_count and bool(
        np.array_equal(
            reference.spike_indices[reference_order],
            candidate.spike_indices[candidate_order],
        )
    )
    maximum_time_error_ms: float | None = None
    maximum_signed_time_delta_ms: float | None = None
    timing_outliers: list[dict[str, Any]] = []
    if same_ids:
        time_deltas = (
            candidate.spike_times_ms[candidate_order]
            - reference.spike_times_ms[reference_order]
        )
        maximum_time_error_ms = (
            float(np.max(np.abs(time_deltas)))
            if reference.spike_times_ms.size
            else 0.0
        )
        maximum_signed_time_delta_ms = (
            float(time_deltas[np.argmax(np.abs(time_deltas))]) if time_deltas.size else 0.0
        )
        for neuron_index in np.unique(reference.spike_indices[reference_order]):
            neuron_deltas = time_deltas[
                reference.spike_indices[reference_order] == neuron_index
            ]
            neuron_maximum = float(np.max(np.abs(neuron_deltas)))
            if neuron_maximum > spike_time_tolerance_ms + 1e-9:
                timing_outliers.append(
                    {
                        "dense_index": int(neuron_index),
                        "maximum_spike_time_error_ms": neuron_maximum,
                    }
                )
    ref_rates = np.asarray(reference.readout_rates_hz)
    candidate_rates = np.asarray(candidate.readout_rates_hz)
    denominator = np.maximum(np.abs(ref_rates), 1.0)
    maximum_rate_relative_error = float(
        np.max(np.abs(ref_rates - candidate_rates) / denominator)
    )
    passed = bool(
        same_ids
        and maximum_time_error_ms is not None
        and maximum_time_error_ms <= spike_time_tolerance_ms + 1e-9
        and maximum_rate_relative_error <= rate_relative_tolerance
    )
    return {
        "reference_backend": reference.backend,
        "candidate_backend": candidate.backend,
        "same_spike_count": same_count,
        "per_neuron_count_differences": count_differences,
        "ordered_neuron_ids_match": same_ids,
        "maximum_spike_time_error_ms": maximum_time_error_ms,
        "maximum_signed_spike_time_delta_ms": maximum_signed_time_delta_ms,
        "timing_outliers": timing_outliers,
        "spike_time_tolerance_ms": spike_time_tolerance_ms,
        "maximum_readout_rate_relative_error": maximum_rate_relative_error,
        "rate_relative_tolerance": rate_relative_tolerance,
        "passed": passed,
    }


def parameters_from_experiment(experiment: dict[str, Any]) -> TransferLIFParameters:
    published = experiment["published_parameters"]
    transfer = experiment["transfer_protocol"]
    result = TransferLIFParameters(
        dt_ms=float(transfer["neural_dt_ms"]),
        duration_ms=float(experiment["reference"]["duration_ms"]),
        resting_mv=float(published["resting_mv"]),
        reset_mv=float(published["reset_mv"]),
        threshold_mv=float(published["threshold_mv"]),
        membrane_tau_ms=float(published["membrane_tau_ms"]),
        synapse_tau_ms=float(published["synapse_tau_ms"]),
        refractory_ms=float(published["refractory_ms"]),
        synaptic_delay_ms=float(published["synaptic_delay_ms"]),
        synaptic_mv_per_contact=float(published["synaptic_mv_per_contact"]),
        tonic_drive_mv=float(published["tonic_drive_mv"]),
        reset_synaptic_state_on_spike=bool(published["reset_synaptic_state_on_spike"]),
        state_updater=str(published["transfer_state_updater"]),
        genn_precision=str(published["transfer_genn_precision"]),
    )
    result.validate()
    return result


def load_population_ids(path: Path) -> dict[str, tuple[int, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item["id"]): tuple(int(value) for value in item["body_ids"])
        for item in payload["populations"]
    }


def dataclass_payload(value: TransferLIFParameters) -> dict[str, Any]:
    return asdict(value)
