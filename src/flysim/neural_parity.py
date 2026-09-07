# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic small-circuit runners used to compare neural backends."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class ParityCircuit:
    """A dimensionless LIF circuit with explicit engineering parameters."""

    dt_ms: float = 0.1
    duration_ms: float = 200.0
    tau_m_ms: float = 20.0
    rest: float = -65.0
    reset: float = -65.0
    threshold: float = -50.0
    refractory_ms: float = 5.0
    drive: tuple[float, ...] = (30.0, 14.0, 14.0)
    sources: tuple[int, ...] = (0, 1)
    targets: tuple[int, ...] = (1, 2)
    synaptic_weight: float = 300.0

    @property
    def neuron_count(self) -> int:
        return len(self.drive)

    @property
    def steps(self) -> int:
        return round(self.duration_ms / self.dt_ms)

    def identity(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def run_numpy(circuit: ParityCircuit) -> tuple[np.ndarray, np.ndarray]:
    """Run the canonical forward-Euler schedule used by the parity fixture."""
    voltage = np.full(circuit.neuron_count, circuit.rest, dtype=np.float64)
    refractory_until = np.zeros(circuit.neuron_count, dtype=np.float64)
    previous_spikes = np.zeros(circuit.neuron_count, dtype=np.bool_)
    spike_times: list[float] = []
    spike_ids: list[int] = []
    for step in range(circuit.steps):
        start_ms = step * circuit.dt_ms
        end_ms = (step + 1) * circuit.dt_ms
        synaptic = np.zeros(circuit.neuron_count, dtype=np.float64)
        for source, target in zip(circuit.sources, circuit.targets, strict=True):
            if previous_spikes[source]:
                synaptic[target] += circuit.synaptic_weight
        active = refractory_until <= start_ms + 1e-12
        voltage[active] += (circuit.dt_ms / circuit.tau_m_ms) * (
            circuit.rest - voltage[active]
            + np.asarray(circuit.drive)[active]
            + synaptic[active]
        )
        voltage[~active] = circuit.reset
        current_spikes = active & (voltage >= circuit.threshold)
        for neuron_id in np.flatnonzero(current_spikes):
            spike_times.append(end_ms)
            spike_ids.append(int(neuron_id))
        voltage[current_spikes] = circuit.reset
        refractory_until[current_spikes] = end_ms + circuit.refractory_ms
        previous_spikes = current_spikes
    return np.asarray(spike_times), np.asarray(spike_ids, dtype=np.uint32)


def run_brian2(circuit: ParityCircuit) -> tuple[np.ndarray, np.ndarray]:
    """Run the same fixture in Brian2's NumPy runtime."""
    import brian2 as b2

    b2.start_scope()
    b2.prefs.codegen.target = "numpy"
    b2.defaultclock.dt = circuit.dt_ms * b2.ms
    neurons = b2.NeuronGroup(
        circuit.neuron_count,
        """
        dv/dt = (rest - v + drive) / tau : 1 (unless refractory)
        drive : 1
        rest : 1 (constant)
        tau : second (constant)
        """,
        threshold=f"v >= {circuit.threshold}",
        reset=f"v = {circuit.reset}",
        # Brian2's threshold timestamp precedes the completed Euler interval;
        # add one dt to match the explicit interval-end schedule above.
        refractory=(circuit.refractory_ms + circuit.dt_ms) * b2.ms,
        method="euler",
    )
    neurons.v = circuit.rest
    neurons.drive = circuit.drive
    neurons.rest = circuit.rest
    neurons.tau = circuit.tau_m_ms * b2.ms
    synapses = b2.Synapses(
        neurons,
        neurons,
        model="w : 1 (constant)",
        on_pre="v_post += w * dt / tau_post",
    )
    synapses.connect(i=circuit.sources, j=circuit.targets)
    synapses.w = circuit.synaptic_weight
    monitor = b2.SpikeMonitor(neurons)
    b2.run(circuit.duration_ms * b2.ms)
    # Brian2 labels threshold crossings at the beginning of the completed interval.
    return np.asarray(monitor.t / b2.ms) + circuit.dt_ms, np.asarray(monitor.i, dtype=np.uint32)


def run_genn(circuit: ParityCircuit, build_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Run the fixture with a direct custom PyGeNN model on CUDA."""
    from pygenn import (
        GeNNModel,
        create_neuron_model,
        init_postsynaptic,
        init_weight_update,
    )

    neuron_model = create_neuron_model(
        "MaleCNSParityLIF",
        params=("TauM", "Vrest", "Vreset", "Vthresh", "TauRefrac"),
        vars=(
            ("V", "scalar"),
            ("RefracTime", "scalar"),
            ("Drive", "scalar"),
        ),
        sim_code="""
        if (RefracTime > 0.0) {
            RefracTime -= dt;
            V = Vreset;
        }
        else {
            V += (dt / TauM) * (Vrest - V + Drive + Isyn);
        }
        """,
        threshold_condition_code="RefracTime <= 0.0 && V >= Vthresh",
        reset_code="V = Vreset; RefracTime = TauRefrac;",
    )
    if "CUDA_PATH" not in os.environ:
        nvcc = shutil.which("nvcc")
        if nvcc is not None:
            os.environ["CUDA_PATH"] = str(Path(nvcc).resolve().parent.parent)
    model = GeNNModel("float", f"parity_f32_{circuit.identity()[:12]}", backend="cuda")
    model.dt = circuit.dt_ms
    population = model.add_neuron_population(
        "neurons",
        circuit.neuron_count,
        neuron_model,
        {
            "TauM": circuit.tau_m_ms,
            "Vrest": circuit.rest,
            "Vreset": circuit.reset,
            "Vthresh": circuit.threshold,
            "TauRefrac": circuit.refractory_ms - circuit.dt_ms,
        },
        {"V": circuit.rest, "RefracTime": 0.0, "Drive": np.asarray(circuit.drive)},
    )
    population.spike_recording_enabled = True
    synapses = model.add_synapse_population(
        "edges",
        "SPARSE",
        population,
        population,
        init_weight_update("StaticPulseConstantWeight", {"g": circuit.synaptic_weight}),
        init_postsynaptic("DeltaCurr"),
    )
    synapses.set_sparse_connections(
        np.asarray(circuit.sources, dtype=np.uint32),
        np.asarray(circuit.targets, dtype=np.uint32),
    )
    build_path.mkdir(parents=True, exist_ok=True)
    model.build(path_to_model=str(build_path), always_rebuild=False)
    model.load(num_recording_timesteps=circuit.steps)
    for _ in range(circuit.steps):
        model.step_time()
    model.pull_recording_buffers_from_device()
    recorded_batches = population.spike_recording_data
    if len(recorded_batches) != 1:
        raise RuntimeError(f"Expected one GeNN recording batch, got {len(recorded_batches)}")
    times, ids = recorded_batches[0]
    model.unload()
    # GeNN labels spikes with the start of the completed integration interval.
    return np.asarray(times) + circuit.dt_ms, np.asarray(ids, dtype=np.uint32)


def compare_spikes(
    expected_times: np.ndarray,
    expected_ids: np.ndarray,
    actual_times: np.ndarray,
    actual_ids: np.ndarray,
    *,
    tolerance_ms: float,
) -> dict[str, Any]:
    """Compare ordered spike identities and times without hiding count errors."""
    same_count = len(expected_times) == len(actual_times)
    same_ids = same_count and bool(np.array_equal(expected_ids, actual_ids))
    maximum_error = None
    if same_count:
        maximum_error = (
            float(np.max(np.abs(expected_times - actual_times))) if len(expected_times) else 0.0
        )
    passed = same_ids and maximum_error is not None and maximum_error <= tolerance_ms
    return {
        "passed": passed,
        "expected_spike_count": len(expected_times),
        "actual_spike_count": len(actual_times),
        "ordered_neuron_ids_match": same_ids,
        "maximum_spike_time_error_ms": maximum_error,
        "tolerance_ms": tolerance_ms,
    }
