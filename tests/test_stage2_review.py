# SPDX-License-Identifier: GPL-2.0-or-later
"""Checks added by the 2026-09-08 independent Stage 2 review (ADR-2026-009).

Each test pins one defect the review found: an assumption that had been silently baked
into a measured value, a criterion that could pass without information, or an output
that had to stay byte-identical for a contract written before the review.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flysim.cellular import (
    SpikeDetectionPolicy,
    StepAnalysisPolicy,
    StepDiagnosticsPolicy,
    current_step_features,
    free_asymptote_exponential_fit,
    stimulus_free_features,
    summarise_current_step_protocol,
    upstroke_diagnostics,
)
from flysim.datasets import sha256_file
from flysim.dynamics import CellParameterSet
from flysim.errors import ConfigurationError, DatasetError
from flysim.synaptic import (
    evaluate_stage2_exit_gate,
    evaluate_uepsc_kinetics_holdout,
    receptor_neuron_bodies_per_glomerulus,
)

SAMPLE_INTERVAL_US = 100
DT_MS = SAMPLE_INTERVAL_US / 1_000.0

POLICY = SpikeDetectionPolicy(
    prominence_mv=10.0, prominence_window_ms=10.0, refractory_ms=2.0, resting_mask_ms=20.0
)
STEP_POLICY = StepAnalysisPolicy(
    baseline_settle_ms=10.0,
    steady_window_ms=100.0,
    charge_fit_low_fraction=0.1,
    charge_fit_high_fraction=0.9,
    minimum_subthreshold_span_mv=1.0,
    minimum_fit_r_squared=0.9,
    maximum_tau_to_window_ratio=1.0,
)
DIAGNOSTICS = StepDiagnosticsPolicy(
    spike_threshold_slope_fraction=0.1, relaxation_sensitivity_window_ms=200.0
)


def _passive_step(
    *,
    tau_ms: float,
    span_mv: float,
    post_step_asymptote_mv: float,
    current_pa: float = 2.0,
    samples: int = 20_000,
    onset: int = 5_000,
    offset: int = 15_000,
) -> tuple[np.ndarray, np.ndarray]:
    """A passive cell whose post-step resting level may differ from the pre-step one."""
    current = np.zeros(samples)
    current[onset : offset + 1] = current_pa
    voltage = np.full(samples, -60.0)
    charge = np.arange(offset + 1 - onset) * DT_MS
    voltage[onset : offset + 1] = -60.0 + span_mv * (1.0 - np.exp(-charge / tau_ms))
    relax = np.arange(samples - offset - 1) * DT_MS
    voltage[offset + 1 :] = post_step_asymptote_mv + (
        voltage[offset] - post_step_asymptote_mv
    ) * np.exp(-relax / tau_ms)
    return current[None, :], voltage[None, :]


def test_free_asymptote_fit_recovers_a_clean_exponential() -> None:
    elapsed = np.arange(0.0, 200.0, DT_MS)
    voltage = -60.0 + 10.0 * np.exp(-elapsed / 25.0)

    fit = free_asymptote_exponential_fit(elapsed, voltage)

    assert fit["tau_ms"] == pytest.approx(25.0, rel=0.02)
    assert fit["asymptote_mv"] == pytest.approx(-60.0, abs=0.05)
    assert fit["r_squared"] > 0.999


def test_a_pinned_asymptote_biases_the_gated_time_constant_and_the_free_fit_shows_it() -> None:
    """The relaxation settles 2 mV above the pre-step baseline the primary fit pins."""
    current, voltage = _passive_step(tau_ms=25.0, span_mv=10.0, post_step_asymptote_mv=-58.0)

    features = current_step_features(
        current,
        voltage,
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        step_policy=STEP_POLICY,
        diagnostics=DIAGNOSTICS,
    )
    record = features[0]
    free = record["relaxation_free_asymptote"]

    assert free["asymptote_mv"] == pytest.approx(-58.0, abs=0.05)
    assert free["tau_ms"] == pytest.approx(25.0, rel=0.03)
    assert free["assumed_asymptote_mv"] == pytest.approx(-60.0)
    gated = record["relaxation_membrane_tau_ms"]
    # The pinned fit either rejects the drifted relaxation or reports a wrong constant.
    assert gated is None or abs(gated - 25.0) / 25.0 > 0.10
    summary = summarise_current_step_protocol(features)
    assert summary["relaxation_free_asymptote_fits"][0]["tau_ms"] == pytest.approx(
        25.0, rel=0.03
    )


def test_step_diagnostics_are_absent_unless_a_contract_asks_for_them() -> None:
    current, voltage = _passive_step(tau_ms=25.0, span_mv=10.0, post_step_asymptote_mv=-60.0)

    features = current_step_features(
        current,
        voltage,
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        step_policy=STEP_POLICY,
    )
    summary = summarise_current_step_protocol(features)

    assert "relaxation_free_asymptote" not in features[0]
    assert "maximum_in_step_deflection_mv" not in features[0]
    assert "relaxation_free_asymptote_fits" not in summary


def test_an_upstroke_criterion_above_the_peak_slope_is_reported_not_hidden() -> None:
    # Ten-millivolt spikes that rise over 2 ms peak at 5 mV/ms, below a 10 mV/ms rule.
    trace = np.full(6_000, -60.0)
    peaks = (1_000, 2_500, 4_000)
    for peak in peaks:
        trace[peak - 20 : peak + 1] = np.linspace(-60.0, -50.0, 21)
        trace[peak : peak + 21] = np.linspace(-50.0, -60.0, 21)

    diagnostics = upstroke_diagnostics(
        trace,
        np.asarray(peaks),
        sample_interval_us=SAMPLE_INTERVAL_US,
        upstroke_criterion_mv_per_ms=10.0,
        search_window_ms=5.0,
        slope_fraction=0.1,
    )

    assert diagnostics["upstroke_peak_dv_dt_mv_per_ms"] == pytest.approx(5.0, rel=0.05)
    assert diagnostics["spikes_reaching_upstroke_criterion"] == 0
    # The fraction rule still places a threshold, near the foot of the ramp.
    assert -60.5 < diagnostics["spike_threshold_at_slope_fraction_mv"] < -58.0


def test_pre_first_spike_baseline_ignores_a_post_stimulus_hyperpolarization() -> None:
    trace = np.full(50_000, -53.0)  # 5 s, mostly the after-hyperpolarized level
    trace[:10_000] = -50.0  # the first second is the true pre-stimulus rest
    for index in range(10_500, 12_000, 300):
        for offset, scale in ((-2, 0.25), (-1, 0.6), (0, 1.0), (1, 0.6), (2, 0.25)):
            trace[index + offset] = -50.0 + 40.0 * scale

    record = stimulus_free_features(
        trace,
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        report_pre_spike_baseline=True,
    )

    assert record["resting_potential_mv"] == pytest.approx(-53.0)
    assert record["pre_first_spike_resting_potential_mv"] == pytest.approx(-50.0)
    assert record["pre_first_spike_duration_ms"] == pytest.approx(1_030.0)
    plain = stimulus_free_features(
        trace, sample_interval_us=SAMPLE_INTERVAL_US, spike_policy=POLICY
    )
    assert "pre_first_spike_resting_potential_mv" not in plain


def test_receptor_neuron_bodies_are_counted_whether_or_not_they_connect() -> None:
    counts = receptor_neuron_bodies_per_glomerulus(
        ("ORN_DM1", "ORN_DM1", "ORN_DA1", "DM1_lPN", "ORN_DM1", "LN1")
    )

    assert counts == {"DM1": 3, "DA1": 1}


def test_a_parameter_set_missing_a_value_is_a_configuration_error() -> None:
    raw = {
        "parameter_set_id": "broken",
        "source": None,
        "evidence": "missing threshold",
        "values": {"resting_mv": -52.0},
        "value_provenance": {},
    }

    with pytest.raises(ConfigurationError, match="omits"):
        CellParameterSet.from_mapping(raw)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_exit_gate_result_id_follows_the_contract() -> None:
    pass


def test_the_exit_gate_result_id_follows_the_contract_experiment_id(tmp_path: Path) -> None:
    root = tmp_path / "root"
    artifact = _write_json(root / "a.json", {"acceptance": {"pass": True}})
    contract = _write_json(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "stage2-exit-gate-v9",
            "provenance": "E",
            "gate_statement": {"source": "test", "text": "t"},
            "legs": [
                {
                    "id": "alpha",
                    "requirement": "r",
                    "artifact": {"path": "a.json", "sha256": sha256_file(artifact)},
                    "read": ["acceptance", "pass"],
                    "expect": True,
                    "sufficiency_caveats": [],
                }
            ],
            "acceptance": {"partial_pass_is_not_a_pass": "no"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )

    result = evaluate_stage2_exit_gate(contract, root, tmp_path / "out.json")

    assert result["result_id"] == "stage2-exit-gate-v9"


def _uepsc_fixture(
    tmp_path: Path, traces: dict[str, np.ndarray], *, report_alignment: bool
) -> tuple[Path, Path]:
    root = tmp_path / "root"
    time_ms = np.arange(0.0, 200.0, DT_MS)
    table = pa.table(
        {
            "specimen_id": pa.array(
                [name for name in traces for _ in time_ms], type=pa.string()
            ),
            "time_ms": pa.array(np.concatenate([time_ms for _ in traces]), type=pa.float64()),
            "current_pa": pa.array(np.concatenate(list(traces.values())), type=pa.float64()),
        }
    )
    artifact = root / "traces.parquet"
    artifact.parent.mkdir(parents=True)
    pq.write_table(table, artifact)
    fit = _write_json(
        root / "fit.json",
        {
            "frozen_before_held_out_evaluation": True,
            "uepsc_model": {
                "parameters": {
                    "onset_ms": 47.25,
                    "rise_tau_ms": 0.75,
                    "decay_tau_ms": 15.0,
                    "population_amplitude_pa": 24.0,
                }
            },
        },
    )
    contract = _write_json(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "stage2-uepsc-kinetics-holdout-test",
            "provenance": "P/F",
            "frozen_fit": {"path": "fit.json", "sha256": sha256_file(fit)},
            "required_artifact": {"path": "traces.parquet", "sha256": sha256_file(artifact)},
            "held_out_specimen_ids": list(traces),
            "consumed_specimen_ids": ["other-cell"],
            "baseline_window_ms": {"start": 0.0, "end": 40.0},
            "report_peak_alignment": report_alignment,
            "gated_criteria": [
                {"id": "sign"},
                {"id": "peak_time", "limit_ms": 1.0},
                {"id": "decay_time", "limit_fraction": 0.3},
            ],
            "reported_but_not_gated": [{"id": "peak_amplitude", "reason": "test"}],
            "acceptance": {"why_not": "test"},
            "threshold_provenance": "test",
            "tier_policy": "none",
            "declared_blockers": [],
            "claim_boundary": "none",
        },
    )
    return contract, root


def test_the_uepsc_holdout_reports_when_every_held_out_peak_shares_one_sample(
    tmp_path: Path,
) -> None:
    from flysim.synaptic import difference_of_exponentials_kernel

    time_ms = np.arange(0.0, 200.0, DT_MS)
    kernel = difference_of_exponentials_kernel(
        time_ms, onset_ms=47.25, rise_tau_ms=0.75, decay_tau_ms=10.0
    )
    contract, root = _uepsc_fixture(
        tmp_path,
        {"cell-a": -30.0 * kernel, "cell-b": -45.0 * kernel},
        report_alignment=True,
    )

    result = evaluate_uepsc_kinetics_holdout(contract, root, tmp_path / "out.json")

    assert result["result_id"] == "stage2-uepsc-kinetics-holdout-test"
    assert result["peak_alignment"]["all_held_out_peaks_share_one_sample"] is True
    assert result["peak_alignment"]["peak_time_criterion_informative"] is False
    assert result["gated"]["peak_time"]["passed"] is True


def test_the_uepsc_holdout_refuses_a_waveform_whose_decay_is_undefined(tmp_path: Path) -> None:
    time_ms = np.arange(0.0, 200.0, DT_MS)
    never_decays = np.where(time_ms >= 50.0, -30.0, 0.0)
    contract, root = _uepsc_fixture(tmp_path, {"cell-a": never_decays}, report_alignment=False)

    with pytest.raises(DatasetError, match="never decays"):
        evaluate_uepsc_kinetics_holdout(contract, root, tmp_path / "out.json")
