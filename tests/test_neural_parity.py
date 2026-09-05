# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np

from flysim.neural_parity import ParityCircuit, compare_spikes, run_numpy


def test_numpy_parity_fixture_is_deterministic_and_recruits_chain() -> None:
    circuit = ParityCircuit()
    first_times, first_ids = run_numpy(circuit)
    second_times, second_ids = run_numpy(circuit)
    assert np.array_equal(first_times, second_times)
    assert np.array_equal(first_ids, second_ids)
    assert set(first_ids) == {0, 1, 2}


def test_spike_comparison_rejects_identity_mismatch() -> None:
    report = compare_spikes(
        np.array([1.0]),
        np.array([0], dtype=np.uint32),
        np.array([1.0]),
        np.array([1], dtype=np.uint32),
        tolerance_ms=0.1,
    )
    assert not report["passed"]
