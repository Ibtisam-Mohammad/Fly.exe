# SPDX-License-Identifier: GPL-2.0-or-later
from flysim.benchmark import estimate_sparse_memory


def test_memory_estimate_scales_monotonically() -> None:
    parameters = {
        "estimated_full_neurons": 100,
        "estimated_aggregate_edges": 1000,
        "float_state_fields_per_neuron": 8,
        "uint_index_fields_per_edge": 2,
        "float_state_fields_per_edge": 1,
        "allocation_safety_factor": 1.5,
    }
    estimates = estimate_sparse_memory((0.01, 0.1, 1.0), parameters)
    assert [item.neurons for item in estimates] == [1, 10, 100]
    assert (
        estimates[0].estimated_bytes
        < estimates[1].estimated_bytes
        < estimates[2].estimated_bytes
    )
