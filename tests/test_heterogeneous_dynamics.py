# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-type membrane parameters must reach the engines without being silently defaulted."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flysim.connectome import SparseConnectome
from flysim.dynamics import CELL_PARAMETER_KEYS, DynamicsRegistry, SignalRegime
from flysim.engines.genn import (
    HETEROGENEOUS_NEURON_PARAMETER_NAMES,
    derive_neuron_arrays,
)
from flysim.engines.lif import NumpyLIFEngine
from flysim.errors import ConfigurationError

REGISTRY_PATH = Path("configs/neural/cell-dynamics-v0.3.json")

FALLBACK = {
    "resting_mv": -52.0,
    "reset_mv": -52.0,
    "threshold_mv": -45.0,
    "membrane_tau_ms": 20.0,
    "synapse_tau_ms": 5.0,
    "refractory_ms": 2.2,
    "tonic_drive_mv": 0.0,
}


def _registry_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.1",
        "registry_id": "test-registry",
        "assumption_ids": ["ND-01", "ND-02", "ND-03", "ND-04", "ND-05"],
        "fallback_parameter_set_id": "fallback",
        "parameter_sets": [
            {
                "parameter_set_id": "fallback",
                "source": None,
                "evidence": "engineering fallback",
                "values": dict(FALLBACK),
                "value_provenance": dict.fromkeys(CELL_PARAMETER_KEYS, "E"),
            },
            {
                "parameter_set_id": "measured",
                "source": "https://example.invalid/paper",
                "evidence": "one measured cell",
                "values": {**FALLBACK, "resting_mv": -60.0, "membrane_tau_ms": 32.5},
                "value_provenance": {
                    **dict.fromkeys(CELL_PARAMETER_KEYS, "E"),
                    "resting_mv": "M",
                    "membrane_tau_ms": "M",
                },
            },
        ],
        "default_record": {
            "cell_type": "__unregistered__",
            "signal_regime": "unresolved",
            "model_family": "competing",
            "provenance": "E",
            "status": "proposed",
            "source": None,
            "evidence_scope": "none",
            "biological_mismatch": None,
            "alternatives": ["a", "b"],
        },
        "records": [
            {
                "cell_type": "TYPED",
                "signal_regime": "spiking",
                "model_family": "measured-single-cell-lif",
                "provenance": "M",
                "status": "accepted",
                "source": "https://example.invalid/paper",
                "evidence_scope": "one cell",
                "biological_mismatch": "one cell",
                "alternatives": [],
                "parameter_set_id": "measured",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_shipped_registry_binds_the_measured_mbon_parameter_set() -> None:
    registry = DynamicsRegistry.load(REGISTRY_PATH)

    resolution = registry.resolve_parameters(("MBON07", "MBON07", "DM1_lPN", ""))

    assert resolution.heterogeneous is True
    assert resolution.parameter_set_ids == (
        "mbon07-alpha1-measured-v1",
        "mbon07-alpha1-measured-v1",
        "shiu-2024-global-lif-fallback-v1",
        "shiu-2024-global-lif-fallback-v1",
    )
    assert resolution.parameter_arrays["membrane_tau_ms"].tolist() == [
        32.566,
        32.566,
        20.0,
        20.0,
    ]
    assert resolution.coverage["fallback_fraction"] == pytest.approx(0.5)
    assert resolution.coverage["measured_fraction"] == pytest.approx(0.5)
    measured = registry.parameter_sets["mbon07-alpha1-measured-v1"]
    # refractory_ms is M/E: a measured upper bound adopted as the value.
    assert set(measured.measured_keys) == {
        "resting_mv",
        "threshold_mv",
        "membrane_tau_ms",
        "refractory_ms",
    }


def test_every_unregistered_type_lands_on_the_declared_fallback(tmp_path: Path) -> None:
    registry = DynamicsRegistry.load(_write_registry(tmp_path, _registry_payload()))

    resolution = registry.resolve_parameters(("UNKNOWN_A", "UNKNOWN_B"))

    assert resolution.heterogeneous is False
    assert resolution.coverage["fallback_fraction"] == pytest.approx(1.0)
    assert resolution.coverage["measured_fraction"] == pytest.approx(0.0)
    assert resolution.unresolved_cell_types == ("UNKNOWN_A", "UNKNOWN_B")
    assert resolution.parameter_arrays["resting_mv"].tolist() == [-52.0, -52.0]


def test_a_cell_type_naming_an_unregistered_parameter_set_is_refused(tmp_path: Path) -> None:
    payload = _registry_payload()
    payload["records"][0]["parameter_set_id"] = "not-registered"

    with pytest.raises(ConfigurationError, match="unregistered parameter set"):
        DynamicsRegistry.load(_write_registry(tmp_path, payload))


def test_a_parameter_set_that_fires_without_input_is_refused(tmp_path: Path) -> None:
    payload = _registry_payload()
    payload["parameter_sets"][1]["values"]["threshold_mv"] = -70.0

    with pytest.raises(ConfigurationError, match="threshold_mv must sit above"):
        DynamicsRegistry.load(_write_registry(tmp_path, payload))


def test_graded_cell_types_are_reported_by_the_resolution(tmp_path: Path) -> None:
    payload = _registry_payload()
    payload["records"][0]["signal_regime"] = "graded"

    registry = DynamicsRegistry.load(_write_registry(tmp_path, payload))
    resolution = registry.resolve_parameters(("TYPED", "OTHER"))

    assert resolution.graded_cell_types == ("TYPED",)
    assert resolution.signal_regimes[0] is SignalRegime.GRADED


def test_derive_neuron_arrays_reproduces_the_scalar_coefficients() -> None:
    from flysim.engines.genn import TrackAGeNNParameters

    scalar = TrackAGeNNParameters(
        neural_dt_us=100,
        resting_mv=-52.0,
        reset_mv=-52.0,
        threshold_mv=-45.0,
        membrane_tau_ms=20.0,
        synapse_tau_ms=5.0,
        refractory_ms=2.2,
        synaptic_delay_ms=0.1,
        synaptic_mv_per_contact=0.2,
        central_entry_outgoing_gain=1.0,
        tonic_drive_mv=0.0,
        reset_synaptic_state_on_spike=False,
    )
    arrays = derive_neuron_arrays(
        {key: np.full(3, FALLBACK[key]) for key in CELL_PARAMETER_KEYS},
        dt_ms=scalar.dt_ms,
        neuron_count=3,
    )

    assert set(arrays) == set(HETEROGENEOUS_NEURON_PARAMETER_NAMES)
    assert arrays["MembraneDecay"].tolist() == pytest.approx([scalar.membrane_decay] * 3)
    assert arrays["SynapseDecay"].tolist() == pytest.approx([scalar.synapse_decay] * 3)
    assert arrays["SynapticVoltageCoefficient"].tolist() == pytest.approx(
        [scalar.synaptic_voltage_coefficient] * 3
    )
    assert arrays["TauRefrac"].tolist() == pytest.approx([scalar.genn_refractory_ms] * 3)


def test_derive_neuron_arrays_refuses_a_refractory_below_one_step() -> None:
    values = {key: np.full(2, FALLBACK[key]) for key in CELL_PARAMETER_KEYS}
    values["refractory_ms"] = np.asarray([0.05, 2.2])

    with pytest.raises(ConfigurationError, match="at least one neural step"):
        derive_neuron_arrays(values, dt_ms=0.1, neuron_count=2)


def test_derive_neuron_arrays_refuses_a_misaligned_array() -> None:
    values = {key: np.full(2, FALLBACK[key]) for key in CELL_PARAMETER_KEYS}

    with pytest.raises(ConfigurationError, match="expected \\(3,\\)"):
        derive_neuron_arrays(values, dt_ms=0.1, neuron_count=3)


def _three_neuron_graph() -> SparseConnectome:
    return SparseConnectome(
        body_ids=np.asarray([10, 20, 30], dtype=np.uint64),
        source_indices=np.asarray([0, 1], dtype=np.uint32),
        target_indices=np.asarray([1, 2], dtype=np.uint32),
        contact_counts=np.asarray([5, 5], dtype=np.uint32),
        source_release="test",
        source_sha256="0" * 64,
    )


def _lif_parameters() -> dict[str, Any]:
    return {
        "neural_dt_us": 100,
        "membrane_tau_us": 20_000,
        "resting_mv": -52.0,
        "reset_mv": -52.0,
        "threshold_mv": -45.0,
        "refractory_us": 2_200,
        "tonic_drive_mv": 0.0,
        "input_gain_mv": 20.0,
        "synaptic_mv_per_contact": 0.2,
        "functional_edge_signs": np.asarray([1.0, 1.0], dtype=np.float32),
    }


def test_the_numpy_oracle_refuses_a_graded_neuron() -> None:
    engine = NumpyLIFEngine()

    with pytest.raises(ConfigurationError, match="graded signal regime"):
        engine.initialize(
            _three_neuron_graph(),
            {**_lif_parameters(), "signal_regimes": ("spiking", "graded", "spiking")},
            seed=0,
        )


def test_the_numpy_oracle_applies_a_per_neuron_threshold() -> None:
    graph = _three_neuron_graph()
    thresholds = np.asarray([-45.0, -20.0, -45.0])
    parameters = {
        **_lif_parameters(),
        "per_neuron_parameters": {
            "resting_mv": np.full(3, -52.0),
            "threshold_mv": thresholds,
        },
    }
    baseline = NumpyLIFEngine()
    baseline.initialize(graph, _lif_parameters(), seed=0)
    heterogeneous = NumpyLIFEngine()
    heterogeneous.initialize(graph, parameters, seed=0)

    frame_ids = (10, 20, 30)
    for engine in (baseline, heterogeneous):
        from flysim.contracts import NeuralInputFrame, SignalType

        engine.push_inputs(
            NeuralInputFrame(
                t_us=0,
                ids=frame_ids,
                values=(1.0, 1.0, 1.0),
                units="normalized",
                signal_type=SignalType.RECEPTOR_ACTIVITY,
                provenance="E",
                assumption_ids=("ND-LIF-01",),
            )
        )
        engine.step_until(20_000)

    homogeneous_rates = baseline.read_outputs(frame_ids, 20_000).values
    raised_rates = heterogeneous.read_outputs(frame_ids, 20_000).values

    # The neuron whose threshold was raised to -20 mV must stop firing; its neighbours,
    # which kept the shared threshold, must be unaffected.
    assert homogeneous_rates[1] > 0.0
    assert raised_rates[1] == 0.0
    assert raised_rates[0] == homogeneous_rates[0]


def test_broadcasting_the_shared_parameters_leaves_the_scalar_path_identical() -> None:
    graph = _three_neuron_graph()
    scalar = NumpyLIFEngine()
    scalar.initialize(graph, _lif_parameters(), seed=0)
    broadcast = NumpyLIFEngine()
    broadcast.initialize(
        graph,
        {
            **_lif_parameters(),
            "per_neuron_parameters": {
                key: np.full(3, value)
                for key, value in (
                    ("resting_mv", -52.0),
                    ("reset_mv", -52.0),
                    ("threshold_mv", -45.0),
                    ("membrane_tau_ms", 20.0),
                    ("refractory_ms", 2.2),
                    ("tonic_drive_mv", 0.0),
                )
            },
        },
        seed=0,
    )

    from flysim.contracts import NeuralInputFrame, SignalType

    for engine in (scalar, broadcast):
        engine.push_inputs(
            NeuralInputFrame(
                t_us=0,
                ids=(10, 20, 30),
                values=(1.0, 0.5, 0.0),
                units="normalized",
                signal_type=SignalType.RECEPTOR_ACTIVITY,
                provenance="E",
                assumption_ids=("ND-LIF-01",),
            )
        )
        engine.step_until(50_000)

    assert scalar.checkpoint()["voltage_mv"] == broadcast.checkpoint()["voltage_mv"]
