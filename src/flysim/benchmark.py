# SPDX-License-Identifier: GPL-2.0-or-later
"""Honest dry-run sizing before native GPU backends are installed."""

from __future__ import annotations

from dataclasses import dataclass

from flysim.connectome import SparseConnectome


@dataclass(frozen=True, slots=True)
class MemoryEstimate:
    scale: float
    neurons: int
    edges: int
    estimated_bytes: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "scale": self.scale,
            "neurons": self.neurons,
            "edges": self.edges,
            "estimated_bytes": self.estimated_bytes,
            "estimated_gib": self.estimated_bytes / (1024**3),
        }


def estimate_sparse_memory(
    scales: tuple[float, ...],
    parameters: dict[str, float | int],
    graph: SparseConnectome | None = None,
) -> tuple[MemoryEstimate, ...]:
    neurons = graph.neuron_count if graph else int(parameters["estimated_full_neurons"])
    edges = graph.edge_count if graph else int(parameters["estimated_aggregate_edges"])
    neuron_bytes = int(parameters["float_state_fields_per_neuron"]) * 4
    edge_bytes = (
        int(parameters["uint_index_fields_per_edge"]) * 4
        + int(parameters["float_state_fields_per_edge"]) * 4
    )
    safety = float(parameters["allocation_safety_factor"])
    output: list[MemoryEstimate] = []
    for scale in scales:
        if not 0.0 < scale <= 1.0:
            raise ValueError(f"Scale must be in (0,1], got {scale}")
        scaled_neurons = max(1, round(neurons * scale))
        scaled_edges = max(1, round(edges * scale))
        estimated = round((scaled_neurons * neuron_bytes + scaled_edges * edge_bytes) * safety)
        output.append(MemoryEstimate(scale, scaled_neurons, scaled_edges, estimated))
    return tuple(output)

