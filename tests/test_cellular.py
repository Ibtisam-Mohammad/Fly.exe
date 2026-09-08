# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np
import pytest

from flysim.cellular import (
    STIMULUS_IRRECOVERABLE,
    STIMULUS_RESOLVED,
    SpikeDetectionPolicy,
    StepAnalysisPolicy,
    _sliding_minimum,
    adaptation_statistics,
    current_step_features,
    detect_spikes,
    resting_potential_mv,
    stimulus_free_features,
    summarise_current_step_protocol,
)
from flysim.errors import ConfigurationError

SAMPLE_INTERVAL_US = 100

POLICY = SpikeDetectionPolicy(
    prominence_mv=10.0,
    prominence_window_ms=10.0,
    refractory_ms=2.0,
    resting_mask_ms=20.0,
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


def _spike_train(length: int, indices: tuple[int, ...], *, amplitude: float = 30.0) -> np.ndarray:
    """A resting trace with narrow triangular spikes at the requested samples."""
    trace = np.full(length, -60.0, dtype=np.float64)
    for index in indices:
        for offset, scale in ((-2, 0.25), (-1, 0.6), (0, 1.0), (1, 0.6), (2, 0.25)):
            trace[index + offset] = -60.0 + amplitude * scale
    return trace


def test_sliding_minimum_matches_a_brute_force_reference() -> None:
    generator = np.random.default_rng(11)
    values = generator.normal(size=257)
    for window in (1, 2, 7, 64, 300):
        observed = _sliding_minimum(values, window)
        expected = np.asarray(
            [values[max(0, index - window + 1) : index + 1].min() for index in range(values.size)]
        )
        assert observed == pytest.approx(expected)


def test_detect_spikes_finds_every_injected_spike() -> None:
    indices = (100, 400, 700, 1500)
    trace = _spike_train(2000, indices)

    detected = detect_spikes(trace, sample_interval_us=SAMPLE_INTERVAL_US, policy=POLICY)

    assert detected.tolist() == list(indices)


def test_detect_spikes_enforces_the_refractory_period() -> None:
    # Two peaks 1 ms apart; the refractory period is 2 ms, so only the first survives.
    trace = _spike_train(500, (100, 110))

    detected = detect_spikes(trace, sample_interval_us=SAMPLE_INTERVAL_US, policy=POLICY)

    assert detected.tolist() == [100]


def test_a_long_prominence_window_turns_a_slow_ramp_into_false_spikes() -> None:
    """Regression test for the defect the MBON protocol exposed.

    A trailing window longer than the depolarization it sits on absorbs the ramp into the
    prominence, so ordinary noise on the rising phase clears the threshold.
    """
    generator = np.random.default_rng(3)
    # 0.2 mV/ms, the depolarization rate the MBON-alpha1 steps actually produce, so a
    # 50 ms trailing window sees a 10 mV rise with no spike in it at all.
    ramp = np.linspace(-60.0, -35.0, 1_250) + generator.normal(scale=0.4, size=1_250)
    wide = SpikeDetectionPolicy(
        prominence_mv=10.0,
        prominence_window_ms=50.0,
        refractory_ms=2.0,
        resting_mask_ms=20.0,
    )

    false_positives = detect_spikes(
        ramp, sample_interval_us=SAMPLE_INTERVAL_US, policy=wide
    )
    calibrated = detect_spikes(ramp, sample_interval_us=SAMPLE_INTERVAL_US, policy=POLICY)

    assert false_positives.size > 0
    assert calibrated.size == 0


def test_resting_potential_ignores_a_depolarised_epoch() -> None:
    trace = np.full(10_000, -55.0)
    trace[6_000:] = -30.0

    rest = resting_potential_mv(
        trace,
        np.asarray([], dtype=np.int64),
        sample_interval_us=SAMPLE_INTERVAL_US,
        policy=POLICY,
    )

    assert rest == pytest.approx(-55.0)


def test_adaptation_ratio_separates_slowing_from_accelerating_trains() -> None:
    slowing = np.cumsum(np.asarray([0, 100, 150, 200, 300, 400, 600]))
    accelerating = np.cumsum(np.asarray([0, 600, 400, 300, 200, 150, 100]))

    slow = adaptation_statistics(slowing, sample_interval_us=SAMPLE_INTERVAL_US)
    fast = adaptation_statistics(accelerating, sample_interval_us=SAMPLE_INTERVAL_US)

    assert slow["adaptation_ratio"] > 1.0
    assert fast["adaptation_ratio"] < 1.0
    assert slow["adaptation_index"] > 0.0 > fast["adaptation_index"]


def test_adaptation_is_withheld_below_four_intervals() -> None:
    statistics = adaptation_statistics(
        np.asarray([0, 100, 250]), sample_interval_us=SAMPLE_INTERVAL_US
    )

    assert statistics["interval_count"] == 2
    assert statistics["adaptation_ratio"] is None
    assert statistics["adaptation_index"] is None


def _passive_step(
    *,
    tau_ms: float,
    resistance_mohm: float,
    current_pa: float,
    samples: int = 20_000,
    onset: int = 5_000,
    offset: int = 15_000,
) -> tuple[np.ndarray, np.ndarray]:
    dt_ms = SAMPLE_INTERVAL_US / 1_000.0
    current = np.zeros(samples)
    current[onset : offset + 1] = current_pa
    span = resistance_mohm * current_pa / 1_000.0
    voltage = np.full(samples, -60.0)
    charge = np.arange(offset + 1 - onset) * dt_ms
    voltage[onset : offset + 1] = -60.0 + span * (1.0 - np.exp(-charge / tau_ms))
    relax = np.arange(samples - offset - 1) * dt_ms
    voltage[offset + 1 :] = -60.0 + (voltage[offset] + 60.0) * np.exp(-relax / tau_ms)
    return current[None, :], voltage[None, :]


def test_current_step_features_recover_a_known_passive_cell() -> None:
    current, voltage = _passive_step(tau_ms=25.0, resistance_mohm=2_000.0, current_pa=2.0)

    features = current_step_features(
        current,
        voltage,
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        step_policy=STEP_POLICY,
    )
    summary = summarise_current_step_protocol(features)

    assert features[0]["subthreshold"] is True
    assert features[0]["membrane_tau_ms"] == pytest.approx(25.0, rel=1e-3)
    assert features[0]["input_resistance_mohm"] == pytest.approx(2_000.0, rel=1e-2)
    assert features[0]["relaxation_membrane_tau_ms"] == pytest.approx(25.0, rel=1e-3)
    assert summary["stimulus_resolution"] == STIMULUS_RESOLVED
    assert summary["rheobase_upper_bound_pa"] is None


def test_a_drifting_relaxation_is_rejected_rather_than_reported() -> None:
    """A baseline that never returns must not be reported as a membrane time constant."""
    current, voltage = _passive_step(tau_ms=25.0, resistance_mohm=2_000.0, current_pa=2.0)
    drift = np.linspace(0.0, 12.0, voltage.shape[1] - 15_001)
    voltage[0, 15_001:] += drift

    features = current_step_features(
        current,
        voltage,
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        step_policy=STEP_POLICY,
    )

    assert features[0]["relaxation_membrane_tau_ms"] is None
    assert features[0]["relaxation_charging_rejection"] is not None
    assert summarise_current_step_protocol(features)["membrane_tau_from_relaxation_ms"] is None


def test_rheobase_is_reported_as_a_bracket_across_sweeps() -> None:
    current, voltage = _passive_step(tau_ms=25.0, resistance_mohm=2_000.0, current_pa=2.0)
    spiking_voltage = voltage.copy()
    for index in (6_000, 7_000, 8_000, 9_000, 10_000):
        for offset, scale in ((-2, 0.25), (-1, 0.6), (0, 1.0), (1, 0.6), (2, 0.25)):
            spiking_voltage[0, index + offset] += 30.0 * scale
    features = current_step_features(
        np.concatenate([current, current * 2.0]),
        np.concatenate([voltage, spiking_voltage]),
        sample_interval_us=SAMPLE_INTERVAL_US,
        spike_policy=POLICY,
        step_policy=STEP_POLICY,
    )

    summary = summarise_current_step_protocol(features)

    assert summary["rheobase_lower_bound_pa"] == pytest.approx(2.0)
    assert summary["rheobase_upper_bound_pa"] == pytest.approx(4.0)
    assert features[1]["membrane_tau_ms"] is None


def test_stimulus_free_features_never_reference_current() -> None:
    trace = _spike_train(20_000, tuple(range(1_000, 11_000, 500)), amplitude=70.0)

    record = stimulus_free_features(
        trace, sample_interval_us=SAMPLE_INTERVAL_US, spike_policy=POLICY
    )

    assert record["stimulus_resolution"] == STIMULUS_IRRECOVERABLE
    assert record["overshoots_zero_mv"] is True
    assert record["spike_count"] == 20
    assert not any("current" in key or "resistance" in key for key in record)


def test_step_policy_rejects_an_inverted_charging_band() -> None:
    with pytest.raises(ConfigurationError):
        StepAnalysisPolicy.from_mapping(
            {
                "baseline_settle_ms": 10.0,
                "steady_window_ms": 100.0,
                "charge_fit_low_fraction": 0.9,
                "charge_fit_high_fraction": 0.1,
                "minimum_subthreshold_span_mv": 1.0,
                "minimum_fit_r_squared": 0.9,
                "maximum_tau_to_window_ratio": 1.0,
            }
        )
