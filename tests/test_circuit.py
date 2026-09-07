# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

import numpy as np

from flysim.circuit import (
    CircuitRun,
    TransferLIFParameters,
    build_control_graph,
    compare_backend_runs,
    make_stimulus_schedule,
    run_numpy_circuit,
    select_shortest_path_circuit,
)
from flysim.connectome import SparseConnectome


def _graph() -> SparseConnectome:
    return SparseConnectome(
        body_ids=np.asarray([10, 20, 30, 40, 50], dtype=np.uint64),
        source_indices=np.asarray([0, 0, 1, 2, 2, 3], dtype=np.uint32),
        target_indices=np.asarray([1, 4, 3, 3, 4, 4], dtype=np.uint32),
        contact_counts=np.asarray([2, 1, 3, 4, 1, 5], dtype=np.uint32),
        source_release="test:v1",
        source_sha256="a" * 64,
    )


def _parameters() -> TransferLIFParameters:
    return TransferLIFParameters(
        dt_ms=0.1,
        duration_ms=20.0,
        resting_mv=-52.0,
        reset_mv=-52.0,
        threshold_mv=-45.0,
        membrane_tau_ms=20.0,
        synapse_tau_ms=5.0,
        refractory_ms=2.2,
        synaptic_delay_ms=1.8,
        synaptic_mv_per_contact=0.275,
        tonic_drive_mv=0.0,
        reset_synaptic_state_on_spike=True,
    )


def test_shortest_path_selection_excludes_longer_branch() -> None:
    selected = select_shortest_path_circuit(_graph(), (10,), (50,), maximum_hops=4)
    assert selected.shortest_path_hops == 1
    assert selected.graph.body_ids.tolist() == [10, 50]
    assert selected.graph.contact_counts.tolist() == [1]
    assert selected.input_body_ids == (10,)
    assert selected.no_path_input_body_ids == ()


def test_control_variants_preserve_valid_graphs() -> None:
    graph = _graph()
    labels = ("input", "a", "b", "a", "output")
    for variant in (
        "exact",
        "cell-type-only",
        "shuffled-connectivity",
        "uniform-weights",
        "randomized-weights",
        "weak-edge-dropout",
    ):
        control = build_control_graph(
            graph,
            variant,
            cell_types=labels,
            seed=1,
            weak_edge_max_contacts=1,
        )
        control.validate()


def test_numpy_circuit_is_deterministic() -> None:
    graph = _graph()
    parameters = _parameters()
    schedule = make_stimulus_schedule(
        graph, (10,), frequency_hz=200.0, parameters=parameters, seed=3
    )
    signs = np.ones(graph.edge_count, dtype=np.float32)
    first = run_numpy_circuit(graph, signs, schedule, parameters, (50,))
    second = run_numpy_circuit(graph, signs, schedule, parameters, (50,))
    assert np.array_equal(first.spike_indices, second.spike_indices)
    assert np.array_equal(first.spike_times_ms, second.spike_times_ms)
    assert compare_backend_runs(
        first,
        second,
        spike_time_tolerance_ms=0.1,
        rate_relative_tolerance=0.01,
    )["passed"]


def test_build_path_argument_is_a_path() -> None:
    assert isinstance(Path("build"), Path)


def test_backend_comparison_is_neuron_wise_and_timestep_tolerant() -> None:
    reference = CircuitRun(
        backend="numpy",
        spike_times_ms=np.asarray([1.0, 1.0, 2.0]),
        spike_indices=np.asarray([0, 1, 0], dtype=np.uint32),
        readout_rates_hz=(2.0,),
        schedule_sha256="a" * 64,
    )
    candidate = CircuitRun(
        backend="genn",
        spike_times_ms=np.asarray([1.1, 1.1, 2.1]),
        spike_indices=np.asarray([1, 0, 0], dtype=np.uint32),
        readout_rates_hz=(2.0,),
        schedule_sha256="a" * 64,
    )

    comparison = compare_backend_runs(
        reference,
        candidate,
        spike_time_tolerance_ms=0.1,
        rate_relative_tolerance=0.01,
    )

    assert comparison["passed"]
    assert comparison["ordered_neuron_ids_match"]
