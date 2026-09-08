# SPDX-License-Identifier: GPL-2.0-or-later
"""ADR-2026-010 and the review follow-ups: registry v0.4 with value ranges, the strict cellular
exit criterion, bounded-path circuits, vectorised delivery, registered short-term depression,
and the labelled uEPSC prior."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flysim.circuit import (
    StimulusSchedule,
    TransferLIFParameters,
    _deliver_spikes,
    make_stimulus_schedule,
    run_numpy_circuit,
    select_bounded_path_circuit,
    select_shortest_path_circuit,
)
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.dynamics import CELL_PARAMETER_KEYS, CellParameterSet, DynamicsRegistry
from flysim.errors import ConfigurationError
from flysim.plasticity import (
    EdgeDepression,
    ShortTermPlasticityRegistry,
    build_edge_depression,
    steady_state_resource,
)
from flysim.synaptic import (
    difference_of_exponentials_kernel,
    evaluate_stage2_exit_gate,
    fit_difference_of_exponentials_kernel,
    fit_uepsc_prior,
)

REPO = Path(__file__).resolve().parents[1]
DT_MS = 0.1


def _parameters(**overrides: Any) -> TransferLIFParameters:
    values: dict[str, Any] = {
        "dt_ms": DT_MS,
        "duration_ms": 20.0,
        "resting_mv": -52.0,
        "reset_mv": -52.0,
        "threshold_mv": -45.0,
        "membrane_tau_ms": 20.0,
        "synapse_tau_ms": 5.0,
        "refractory_ms": 2.2,
        "synaptic_delay_ms": 1.8,
        "synaptic_mv_per_contact": 0.275,
        "tonic_drive_mv": 0.0,
        "reset_synaptic_state_on_spike": True,
        "state_updater": "source-faithful-linear",
        "genn_precision": "float64-reference",
    }
    values.update(overrides)
    return TransferLIFParameters(**values)


def _graph(
    sources: list[int], targets: list[int], contacts: list[int], count: int
) -> SparseConnectome:
    order = np.lexsort((np.asarray(targets), np.asarray(sources)))
    return SparseConnectome(
        body_ids=np.asarray([10 * (index + 1) for index in range(count)], dtype=np.uint64),
        source_indices=np.asarray(sources, dtype=np.uint32)[order],
        target_indices=np.asarray(targets, dtype=np.uint32)[order],
        contact_counts=np.asarray(contacts, dtype=np.uint32)[order],
        source_release="test:v1",
        source_sha256="b" * 64,
    )


# ----------------------------------------------------------------- registry v0.4


def test_registry_v04_carries_the_decided_mbon07_values_and_their_ranges() -> None:
    registry = DynamicsRegistry.load(REPO / "configs" / "neural" / "cell-dynamics-v0.4.json")
    parameter_set = registry.parameter_sets["mbon07-alpha1-measured-v2"]

    assert parameter_set.values["membrane_tau_ms"] == pytest.approx(47.577)
    assert parameter_set.values["threshold_mv"] == pytest.approx(-41.838)
    assert parameter_set.values["refractory_ms"] == pytest.approx(15.8)
    assert parameter_set.value_ranges is not None
    assert parameter_set.value_ranges["membrane_tau_ms"] == (32.566, 47.577)
    assert parameter_set.as_dict()["value_ranges"]["threshold_mv"] == [-41.838, -38.402]

    resolution = registry.resolve_parameters(("MBON07", "SomethingElse"))
    assert resolution.heterogeneous is True
    assert resolution.parameter_arrays["membrane_tau_ms"][0] == pytest.approx(47.577)
    assert resolution.parameter_arrays["membrane_tau_ms"][1] == pytest.approx(20.0)


def _parameter_set_payload(**extra: Any) -> dict[str, Any]:
    return {
        "parameter_set_id": "candidate",
        "source": None,
        "evidence": "test",
        "values": {
            "resting_mv": -60.0,
            "reset_mv": -60.0,
            "threshold_mv": -40.0,
            "membrane_tau_ms": 40.0,
            "synapse_tau_ms": 5.0,
            "refractory_ms": 2.2,
            "tonic_drive_mv": 0.0,
        },
        "value_provenance": dict.fromkeys(CELL_PARAMETER_KEYS, "E"),
        **extra,
    }


def test_a_value_range_must_contain_the_registered_value() -> None:
    accepted = CellParameterSet.from_mapping(
        _parameter_set_payload(value_ranges={"membrane_tau_ms": [30.0, 50.0]})
    )
    assert accepted.value_ranges == {"membrane_tau_ms": (30.0, 50.0)}

    with pytest.raises(ConfigurationError, match="do not contain"):
        CellParameterSet.from_mapping(
            _parameter_set_payload(value_ranges={"membrane_tau_ms": [50.0, 60.0]})
        )
    with pytest.raises(ConfigurationError, match="unknown parameter"):
        CellParameterSet.from_mapping(_parameter_set_payload(value_ranges={"bogus": [0, 1]}))


# --------------------------------------------------------------- exit gate v3


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _gate_contract(tmp_path: Path, artifact: Path, ratio_limit: float) -> Path:
    return _write_json(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "stage2-exit-gate-test",
            "provenance": "E",
            "gate_statement": {"source": "test", "text": "t"},
            "legs": [
                {
                    "id": "cellular",
                    "requirement": "r",
                    "artifact": {"path": "holdout.json", "sha256": sha256_file(artifact)},
                    "read": ["metrics", "normalized_error_ratio"],
                    "expect_below": ratio_limit,
                    "sufficiency_caveats": [],
                }
            ],
            "acceptance": {"partial_pass_is_not_a_pass": "no"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )


def test_expect_below_is_strict_so_tying_the_cohort_mean_does_not_pass(tmp_path: Path) -> None:
    root = tmp_path / "root"
    tie = _write_json(root / "holdout.json", {"metrics": {"normalized_error_ratio": 1.0}})
    result = evaluate_stage2_exit_gate(_gate_contract(tmp_path, tie, 1.0), root, tmp_path / "a")
    assert result["legs"][0]["passed"] is False
    assert result["legs"][0]["criterion"] == "< 1.0"

    better = _write_json(root / "holdout.json", {"metrics": {"normalized_error_ratio": 0.93}})
    result = evaluate_stage2_exit_gate(
        _gate_contract(tmp_path, better, 1.0), root, tmp_path / "b"
    )
    assert result["legs"][0]["passed"] is True


# ---------------------------------------------------------- bounded-path circuit


def test_bounded_path_selection_admits_the_lateral_partner_the_shortest_path_drops() -> None:
    # 10 -> 40 directly; 10 -> 20 -> 40 in two hops; 30 -> 40 is unreachable from the input.
    graph = _graph([0, 0, 1, 2], [3, 1, 3, 3], [5, 2, 3, 4], 4)

    shortest = select_shortest_path_circuit(graph, (10,), (40,), maximum_hops=3)
    one_hop = select_bounded_path_circuit(graph, (10,), (40,), maximum_path_length=1)
    two_hop = select_bounded_path_circuit(graph, (10,), (40,), maximum_path_length=2)

    assert shortest.graph.body_ids.tolist() == [10, 40]
    assert one_hop.graph.body_ids.tolist() == [10, 40]
    assert two_hop.graph.body_ids.tolist() == [10, 20, 40]
    assert two_hop.graph.edge_count == 3
    assert two_hop.shortest_path_hops == 2
    assert "at most 2" in two_hop.selection_rule
    assert two_hop.input_body_ids == (10,)
    assert two_hop.readout_body_ids == (40,)


# ------------------------------------------------------------ vectorised delivery


def test_vectorised_delivery_matches_the_per_source_loop_bit_for_bit() -> None:
    generator = np.random.default_rng(5)
    count = 60
    pairs = np.unique(generator.integers(0, count, size=(900, 2)), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    order = np.lexsort((pairs[:, 1], pairs[:, 0]))
    sources = pairs[order, 0]
    targets = pairs[order, 1]
    weights = generator.normal(size=sources.size)
    starts = np.searchsorted(sources, np.arange(count), side="left")
    ends = np.searchsorted(sources, np.arange(count), side="right")
    current = np.flatnonzero(generator.random(count) < 0.4).astype(np.uint32)

    looped = np.zeros(count)
    vectorised = np.zeros(count)
    _deliver_spikes(looped, current, starts, ends, targets, weights, vectorized=False)
    _deliver_spikes(vectorised, current, starts, ends, targets, weights)

    assert np.array_equal(looped, vectorised)


# ------------------------------------------------------------- short-term depression


def _pair_graph() -> SparseConnectome:
    return _graph([0], [1], [4], 2)


def test_a_depression_object_with_no_depressing_edge_leaves_the_run_bit_identical() -> None:
    graph = _graph([0, 0, 1, 2, 2, 3], [1, 4, 3, 3, 4, 4], [2, 1, 3, 4, 1, 5], 5)
    parameters = _parameters()
    schedule = make_stimulus_schedule(
        graph, (10,), frequency_hz=200.0, parameters=parameters, seed=3
    )
    signs = np.ones(graph.edge_count, dtype=np.float32)
    inert = EdgeDepression(
        utilisation=np.zeros(graph.edge_count),
        recovery_tau_ms=25.0,
        depressing_edge_indices=np.empty(0, dtype=np.int64),
        summary={},
    )

    static = run_numpy_circuit(graph, signs, schedule, parameters, (50,))
    with_object = run_numpy_circuit(graph, signs, schedule, parameters, (50,), depression=inert)

    assert np.array_equal(static.spike_times_ms, with_object.spike_times_ms)
    assert np.array_equal(static.readout_synaptic_state_mv, with_object.readout_synaptic_state_mv)


def _regular_train_schedule(steps: int, period_steps: int) -> StimulusSchedule:
    forced = np.zeros((steps, 1), dtype=np.bool_)
    forced[::period_steps, 0] = True
    return StimulusSchedule(
        input_indices=np.asarray([0], dtype=np.uint32),
        forced_spikes=forced,
        frequency_hz=1_000.0 / (period_steps * DT_MS),
        seed=0,
        dt_ms=DT_MS,
    )


def _delivered_amplitudes(run: Any, parameters: TransferLIFParameters) -> np.ndarray:
    state = run.readout_synaptic_state_mv[:, 0]
    previous = np.concatenate(([0.0], state[:-1])) * parameters.synapse_decay
    jumps = state - previous
    return jumps[jumps > 1e-12]


def test_depression_follows_the_regular_train_recursion() -> None:
    graph = _pair_graph()
    # A weight far below threshold keeps the postsynaptic cell silent, so the synaptic state
    # of the readout records exactly what each presynaptic spike delivered.
    # The registered recovery constant is 893 ms, so the train needs several seconds to
    # settle onto the closed-form plateau; 500 ms leaves it 6e-5 short.
    parameters = _parameters(duration_ms=4000.0, synaptic_mv_per_contact=0.001)
    period_steps = 100  # 10 ms, a 100 Hz train
    schedule = _regular_train_schedule(parameters.steps, period_steps)
    signs = np.ones(1, dtype=np.float32)
    utilisation, recovery_tau_ms = 0.22, 893.0
    depression = EdgeDepression(
        utilisation=np.asarray([utilisation]),
        recovery_tau_ms=recovery_tau_ms,
        depressing_edge_indices=np.asarray([0], dtype=np.int64),
        summary={},
    )

    run = run_numpy_circuit(graph, signs, schedule, parameters, (20,), depression=depression)
    amplitudes = _delivered_amplitudes(run, parameters)

    assert amplitudes.size >= 45
    assert amplitudes[0] == pytest.approx(4 * 0.001)  # first spike after rest is undepressed
    recovery = np.exp(-period_steps * DT_MS / recovery_tau_ms)
    expected = 1.0
    for observed in amplitudes[1:10]:
        expected = 1.0 - (1.0 - expected * (1.0 - utilisation)) * recovery
        assert observed / amplitudes[0] == pytest.approx(expected, rel=1e-9)
    closed_form = (1.0 - recovery) / (1.0 - (1.0 - utilisation) * recovery)
    assert amplitudes[-1] / amplitudes[0] == pytest.approx(closed_form, rel=1e-6)
    assert steady_state_resource(0.22, 50.0, 893.0) == pytest.approx(1.0 / (1.0 + 9.823))


def test_the_registry_binds_only_same_glomerulus_orn_to_pn_edges() -> None:
    registry = ShortTermPlasticityRegistry.load(
        REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json"
    )
    graph = _graph([0, 0, 0], [1, 2, 3], [10, 10, 10], 4)
    cell_types = ("ORN_DM1", "DM1_lPN", "DL5_adPN", "LN1")

    depression = build_edge_depression(graph, cell_types, registry, recovery_tau_ms=893.0)

    assert depression.utilisation.tolist() == [0.22, 0.0, 0.0]
    assert depression.depressing_edge_indices.tolist() == [0]
    assert depression.summary["matched_edges_by_rule"] == {"orn-to-uniglomerular-pn": 1}
    with pytest.raises(ConfigurationError, match="outside the registered range"):
        build_edge_depression(graph, cell_types, registry, recovery_tau_ms=25.0)


def test_the_registry_carries_the_nagel_2015_fit_and_its_published_spread() -> None:
    """ADR-2026-010: both parameters come from the fit of this registry's own equation to
    measured EPSC amplitude versus stimulus number, not from a separate quantity."""
    registry = ShortTermPlasticityRegistry.load(
        REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json"
    )
    (rule,) = registry.rules

    assert rule.utilisation == 0.22
    assert rule.utilisation_range == (0.09, 0.23)
    assert rule.registered_recovery_tau_ms == 893.0
    assert rule.recovery_tau_range_ms == (629.0, 1006.0)
    # The superseded reading of Kazama and Wilson's release probability is outside the
    # published spread of the fitted utilisation, which is why it is recorded and not run.
    low, high = rule.utilisation_range
    assert not low <= 0.79 <= high


def test_the_registered_pair_reproduces_the_published_paired_pulse_ratio() -> None:
    """The discriminator in ADR-2026-010: 0.22 lands on the measured 10 Hz trajectory and
    0.79 mispredicts it by a factor of 2.7, so the choice is settled by the data."""
    registry = ShortTermPlasticityRegistry.load(
        REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json"
    )
    (rule,) = registry.rules
    tau = rule.registered_recovery_tau_ms
    assert tau is not None

    def paired_pulse(utilisation: float) -> float:
        return float(1.0 - utilisation * np.exp(-100.0 / tau))

    assert paired_pulse(rule.utilisation) == pytest.approx(0.8033, abs=5e-5)
    assert paired_pulse(0.79) == pytest.approx(0.2937, abs=5e-5)
    assert paired_pulse(rule.utilisation) / paired_pulse(0.79) == pytest.approx(2.735, abs=5e-4)


def test_the_registry_records_its_failed_external_test_at_7_hz() -> None:
    """The one external check the ND-06 rule has faced, and it did not pass cleanly.

    Kazama and Wilson 2008 measure about 40% depression at 7 Hz; the registered pair predicts
    56%. This is recorded rather than refit, because refitting to the failing test would remove
    the only independent check the rule has.
    """
    payload = json.loads(
        (REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json").read_text()
    )
    test = payload["rules"][0]["external_test"]

    assert test["verdict"].startswith("FAILED")
    assert test["published_depression_fraction"] == 0.40
    assert test["predicted_depression_fraction"] == pytest.approx(0.559, abs=5e-4)

    # The prediction must follow from the registered parameters, not be a stored number.
    registry = ShortTermPlasticityRegistry.load(
        REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json"
    )
    (rule,) = registry.rules
    tau = rule.registered_recovery_tau_ms
    assert tau is not None
    isi = 1000.0 / 7.0
    decay = float(np.exp(-isi / tau))
    steady = (1.0 - decay) / (1.0 - (1.0 - rule.utilisation) * decay)
    assert steady == pytest.approx(test["predicted_steady_state_resource"], abs=5e-4)
    assert 1.0 - steady == pytest.approx(test["predicted_depression_fraction"], abs=5e-4)
    # The discrepancy is the reportable quantity: about 16 percentage points.
    assert (1.0 - steady) - test["published_depression_fraction"] == pytest.approx(0.159, abs=2e-3)


def test_the_loader_refuses_a_utilisation_outside_its_registered_spread(tmp_path: Path) -> None:
    payload = json.loads(
        (REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json").read_text()
    )
    payload["rules"][0]["utilisation"] = 0.5
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ConfigurationError, match="utilisation_range does not contain"):
        ShortTermPlasticityRegistry.load(path)


def test_the_loader_refuses_a_registered_tau_outside_its_own_range(tmp_path: Path) -> None:
    payload = json.loads(
        (REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json").read_text()
    )
    payload["rules"][0]["recovery_tau_ms"]["value"] = 2000.0
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ConfigurationError, match="lies outside"):
        ShortTermPlasticityRegistry.load(path)


# ------------------------------------------------------------------ uEPSC prior


def test_the_kernel_fit_recovers_a_synthetic_population() -> None:
    time_ms = np.arange(0.0, 200.0, DT_MS)
    kernel = difference_of_exponentials_kernel(
        time_ms, onset_ms=47.25, rise_tau_ms=0.75, decay_tau_ms=10.5
    )
    curves = np.stack([-amplitude * kernel for amplitude in (30.0, 40.0, 50.0)])

    fit = fit_difference_of_exponentials_kernel(time_ms, curves)

    assert fit["onset_ms"] == pytest.approx(47.25)
    assert fit["rise_tau_ms"] == pytest.approx(0.75)
    assert fit["decay_tau_ms"] == pytest.approx(10.5)
    assert fit["population_amplitude_pa"] == pytest.approx(40.0, rel=1e-6)
    assert fit["continuous_parameter_at_search_boundary"] is False


def test_the_prior_refit_is_labelled_unvalidated_and_reports_the_published_comparison(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    time_ms = np.arange(0.0, 200.0, DT_MS)
    kernel = difference_of_exponentials_kernel(
        time_ms, onset_ms=47.25, rise_tau_ms=0.75, decay_tau_ms=10.5
    )
    traces = {"cell-a": -30.0 * kernel, "cell-b": -50.0 * kernel}
    table = pa.table(
        {
            "specimen_id": pa.array([name for name in traces for _ in time_ms]),
            "time_ms": pa.array(np.concatenate([time_ms for _ in traces])),
            "current_pa": pa.array(np.concatenate(list(traces.values()))),
        }
    )
    artifact = root / "traces.parquet"
    pq.write_table(table, artifact)
    frozen = _write_json(
        root / "frozen.json",
        {"uepsc_model": {"parameters": {"decay_tau_ms": 15.0, "population_amplitude_pa": 24.0}}},
    )
    contract = _write_json(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "stage2-uepsc-prior-test",
            "provenance": "P/F",
            "required_artifact": {"path": "traces.parquet", "sha256": sha256_file(artifact)},
            "fit_specimen_ids": list(traces),
            "pooling_justification": "test",
            "held_out_specimen_ids": [],
            "baseline_window_ms": {"start": 0.0, "end": 40.0},
            "kernel": {
                "family": "test",
                "onset_grid_ms": {"start": 45.0, "stop": 51.0, "count": 25},
                "rise_grid_ms": [0.5, 0.75, 1.0],
                "decay_grid_ms": {"start": 3.0, "stop": 30.0, "count": 55},
            },
            "comparison_values": {
                "frozen_fit": {"path": "frozen.json", "sha256": sha256_file(frozen)},
                "published_half_decay_ms": 7.0,
            },
            "acceptance": {"validated": False, "why_not": "nothing held out"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )

    result = fit_uepsc_prior(contract, root, tmp_path / "out.json")

    assert result["result_id"] == "stage2-uepsc-prior-test"
    assert result["acceptance"]["validated"] is False
    assert result["kernel"]["decay_tau_ms"] == pytest.approx(10.5)
    assert result["kernel"]["population_amplitude_pa"] == pytest.approx(40.0, rel=1e-6)
    assert result["against_published_half_decay"]["implied_single_exponential_tau_ms"] == (
        pytest.approx(7.0 / np.log(2.0))
    )
    assert result["against_frozen_fit"]["frozen_decay_tau_ms"] == 15.0
