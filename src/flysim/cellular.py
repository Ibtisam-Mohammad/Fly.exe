# SPDX-License-Identifier: GPL-2.0-or-later
"""Cellular-tier (V1) observables measured from locked in vivo recordings.

`V1 Cellular` requires resting voltage, membrane time constant and firing/adaptation
distributions. None of those can be read off a fitted model, and none of them can be
recovered from a recording whose stimulus amplitudes were never published. This module
therefore separates two strictly different kinds of source.

*Unit-resolved* recordings publish the injected current in physical units alongside the
membrane voltage. They support resting potential, input resistance, membrane time
constant, rheobase, an F-I curve and adaptation.

*Stimulus-free* recordings publish only the membrane voltage. They support resting
potential, somatic spike amplitude and adaptation, and nothing that references current.

Mixing the two silently is what produces an unearned tier, so every measurement records
the stimulus resolution of the source it came from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from flysim.errors import ConfigurationError, DatasetError

STIMULUS_RESOLVED = "unit-resolved"
STIMULUS_IRRECOVERABLE = "irrecoverable"


@dataclass(frozen=True, slots=True)
class SpikeDetectionPolicy:
    """Preregistered somatic spike-detection rule.

    Drosophila central neurons attenuate axonal spikes on the way to the soma, so a fixed
    absolute voltage threshold silently discards real spikes in some classes and admits
    subthreshold depolarizations in others. The rule is therefore a prominence rule, and
    its parameters are preregistered rather than chosen per trace.
    """

    prominence_mv: float
    prominence_window_ms: float
    refractory_ms: float
    resting_mask_ms: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> SpikeDetectionPolicy:
        policy = cls(
            prominence_mv=float(raw["prominence_mv"]),
            prominence_window_ms=float(raw["prominence_window_ms"]),
            refractory_ms=float(raw["refractory_ms"]),
            resting_mask_ms=float(raw["resting_mask_ms"]),
        )
        values = (
            policy.prominence_mv,
            policy.prominence_window_ms,
            policy.refractory_ms,
            policy.resting_mask_ms,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ConfigurationError("Spike-detection policy values must be positive and finite")
        return policy

    def as_dict(self) -> dict[str, float]:
        return {
            "prominence_mv": self.prominence_mv,
            "prominence_window_ms": self.prominence_window_ms,
            "refractory_ms": self.refractory_ms,
            "resting_mask_ms": self.resting_mask_ms,
        }


def _sliding_minimum(values: np.ndarray, window: int) -> np.ndarray:
    """Minimum over the ``window`` samples ending at each index, in linear time."""
    source = np.asarray(values, dtype=np.float64)
    if window <= 1:
        return source.copy()
    padded = np.concatenate([np.full(window - 1, np.inf, dtype=np.float64), source])
    tail = (-len(padded)) % window
    if tail:
        padded = np.concatenate([padded, np.full(tail, np.inf, dtype=np.float64)])
    blocks = padded.reshape(-1, window)
    prefix = np.minimum.accumulate(blocks, axis=1).reshape(-1)
    suffix = np.minimum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].reshape(-1)
    ends = np.arange(window - 1, window - 1 + source.size)
    return np.minimum(suffix[ends - window + 1], prefix[ends])


def detect_spikes(
    voltage_mv: np.ndarray,
    *,
    sample_interval_us: int,
    policy: SpikeDetectionPolicy,
) -> np.ndarray:
    """Return sample indices of somatic spike peaks under the preregistered rule."""
    if sample_interval_us <= 0:
        raise ConfigurationError("Sample interval must be positive")
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    if voltage.ndim != 1 or voltage.size < 3:
        raise ConfigurationError("Spike detection needs a one-dimensional trace")
    if not np.all(np.isfinite(voltage)):
        raise DatasetError("Spike detection refuses a trace with nonfinite samples")
    dt_ms = sample_interval_us / 1_000.0
    window = max(1, round(policy.prominence_window_ms / dt_ms))
    refractory = max(1, round(policy.refractory_ms / dt_ms))
    # Trailing minimum strictly before each index: the sliding minimum shifted one sample.
    trailing = np.empty_like(voltage)
    trailing[0] = np.inf
    trailing[1:] = _sliding_minimum(voltage, window)[:-1]
    interior = np.arange(1, voltage.size - 1)
    peaks = (voltage[interior] >= voltage[interior - 1]) & (
        voltage[interior] > voltage[interior + 1]
    )
    prominent = voltage[interior] - trailing[interior] >= policy.prominence_mv
    accepted: list[int] = []
    last = -(10**9)
    for index in interior[peaks & prominent]:
        if int(index) - last > refractory:
            accepted.append(int(index))
            last = int(index)
    return np.asarray(accepted, dtype=np.int64)


def resting_potential_mv(
    voltage_mv: np.ndarray,
    spike_indices: np.ndarray,
    *,
    sample_interval_us: int,
    policy: SpikeDetectionPolicy,
) -> float:
    """Median membrane voltage away from spikes.

    The median rather than the mean, because a depolarizing stimulus epoch shifts a mean
    baseline while leaving the modal resting level intact.
    """
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    mask = np.ones(voltage.size, dtype=bool)
    half = max(1, round(policy.resting_mask_ms / (sample_interval_us / 1_000.0)))
    for index in np.asarray(spike_indices, dtype=np.int64):
        mask[max(0, int(index) - half) : int(index) + half + 1] = False
    if not mask.any():
        raise DatasetError("Every sample is masked as spike-adjacent; cannot measure rest")
    return float(np.median(voltage[mask]))


def somatic_spike_amplitude_mv(
    voltage_mv: np.ndarray,
    spike_indices: np.ndarray,
    *,
    sample_interval_us: int,
    policy: SpikeDetectionPolicy,
) -> float | None:
    """Median peak-minus-preceding-trough somatic spike height."""
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    indices = np.asarray(spike_indices, dtype=np.int64)
    if indices.size == 0:
        return None
    window = max(1, round(policy.prominence_window_ms / (sample_interval_us / 1_000.0)))
    amplitudes = [
        float(voltage[int(index)] - voltage[max(0, int(index) - window) : int(index) + 1].min())
        for index in indices
    ]
    return float(np.median(amplitudes))


def _interspike_intervals_ms(spike_indices: np.ndarray, sample_interval_us: int) -> np.ndarray:
    return np.diff(np.asarray(spike_indices, dtype=np.float64)) * sample_interval_us / 1_000.0


def adaptation_statistics(
    spike_indices: np.ndarray, *, sample_interval_us: int
) -> dict[str, Any]:
    """Current-independent spike-frequency adaptation.

    The ratio of the mean late interval to the mean early interval is used in preference
    to a last-minus-first index, because one long trailing interval at the end of a step
    dominates the latter and turns a non-adapting cell into an apparently adapting one.
    """
    intervals = _interspike_intervals_ms(spike_indices, sample_interval_us)
    if intervals.size < 4:
        return {
            "interval_count": int(intervals.size),
            "adaptation_ratio": None,
            "adaptation_index": None,
            "first_interval_ms": float(intervals[0]) if intervals.size else None,
            "last_interval_ms": float(intervals[-1]) if intervals.size else None,
        }
    third = max(1, intervals.size // 3)
    early = float(np.mean(intervals[:third]))
    late = float(np.mean(intervals[-third:]))
    return {
        "interval_count": int(intervals.size),
        "adaptation_ratio": late / early,
        "adaptation_index": (late - early) / (late + early),
        "first_interval_ms": float(intervals[0]),
        "last_interval_ms": float(intervals[-1]),
    }


@dataclass(frozen=True, slots=True)
class StepAnalysisPolicy:
    """Preregistered rule for reading a square current-step protocol."""

    baseline_settle_ms: float
    steady_window_ms: float
    charge_fit_low_fraction: float
    charge_fit_high_fraction: float
    minimum_subthreshold_span_mv: float
    minimum_fit_r_squared: float
    maximum_tau_to_window_ratio: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> StepAnalysisPolicy:
        policy = cls(
            baseline_settle_ms=float(raw["baseline_settle_ms"]),
            steady_window_ms=float(raw["steady_window_ms"]),
            charge_fit_low_fraction=float(raw["charge_fit_low_fraction"]),
            charge_fit_high_fraction=float(raw["charge_fit_high_fraction"]),
            minimum_subthreshold_span_mv=float(raw["minimum_subthreshold_span_mv"]),
            minimum_fit_r_squared=float(raw["minimum_fit_r_squared"]),
            maximum_tau_to_window_ratio=float(raw["maximum_tau_to_window_ratio"]),
        )
        if not 0.0 < policy.minimum_fit_r_squared < 1.0:
            raise ConfigurationError("Minimum fit R squared must lie strictly between 0 and 1")
        if policy.maximum_tau_to_window_ratio <= 0.0:
            raise ConfigurationError("Maximum tau-to-window ratio must be positive")
        if not 0.0 < policy.charge_fit_low_fraction < policy.charge_fit_high_fraction < 1.0:
            raise ConfigurationError("Charging-fit fractions must satisfy 0 < low < high < 1")
        positive = (
            policy.baseline_settle_ms,
            policy.steady_window_ms,
            policy.minimum_subthreshold_span_mv,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ConfigurationError("Step-analysis windows must be positive and finite")
        return policy

    def as_dict(self) -> dict[str, float]:
        return {
            "baseline_settle_ms": self.baseline_settle_ms,
            "steady_window_ms": self.steady_window_ms,
            "charge_fit_low_fraction": self.charge_fit_low_fraction,
            "charge_fit_high_fraction": self.charge_fit_high_fraction,
            "minimum_subthreshold_span_mv": self.minimum_subthreshold_span_mv,
            "minimum_fit_r_squared": self.minimum_fit_r_squared,
            "maximum_tau_to_window_ratio": self.maximum_tau_to_window_ratio,
        }


def _step_window(current_pa: np.ndarray) -> tuple[int, int, float]:
    """Locate one contiguous nonzero square pulse and return its bounds and amplitude."""
    active = np.flatnonzero(current_pa != 0.0)
    if active.size == 0:
        raise DatasetError("Current-step sweep carries no injected current")
    start, end = int(active[0]), int(active[-1])
    if active.size != end - start + 1:
        raise DatasetError("Injected current is not one contiguous pulse")
    levels = np.unique(current_pa[start : end + 1])
    if levels.size != 1:
        raise DatasetError("Injected pulse is not square; more than one level is present")
    return start, end, float(levels[0])


def _charging_time_constant_ms(
    elapsed_ms: np.ndarray,
    voltage_mv: np.ndarray,
    baseline_mv: float,
    steady_mv: float,
    policy: StepAnalysisPolicy,
) -> dict[str, Any]:
    """Single-exponential membrane time constant from the subthreshold charging phase."""
    span = steady_mv - baseline_mv
    if abs(span) < policy.minimum_subthreshold_span_mv:
        return {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": None,
            "charging_sample_count": 0,
            "charging_rejection": "subthreshold deflection below the registered minimum span",
            "charging_rejected_tau_ms": None,
        }
    remaining = (steady_mv - voltage_mv) / span
    usable = (remaining > policy.charge_fit_low_fraction) & (
        remaining < policy.charge_fit_high_fraction
    )
    # A passive transient approaches its asymptote monotonically and never crosses it.
    # An after-current or a drifting baseline does cross, and a log-linear fit to the
    # crossing region reports a time constant that describes the drift, not the membrane.
    overshoot = np.flatnonzero(remaining <= 0.0)
    if overshoot.size:
        usable = usable & (np.arange(remaining.size) < int(overshoot[0]))
    if int(np.count_nonzero(usable)) < 10:
        return {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": None,
            "charging_sample_count": int(np.count_nonzero(usable)),
            "charging_rejection": "fewer than ten samples inside the registered charging band",
            "charging_rejected_tau_ms": None,
        }
    x = elapsed_ms[usable]
    y = np.log(remaining[usable])
    slope, intercept = (float(value) for value in np.polyfit(x, y, 1))
    if slope >= 0.0:
        return {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": None,
            "charging_sample_count": int(x.size),
            "charging_rejection": "charging transient does not decay",
            "charging_rejected_tau_ms": None,
        }
    residual = y - (slope * x + intercept)
    total = y - float(np.mean(y))
    denominator = float(np.sum(total**2))
    r_squared = 1.0 - float(np.sum(residual**2)) / denominator if denominator > 0.0 else None
    tau_ms = -1.0 / slope
    observed_window_ms = float(x.max() - x.min())
    rejection: str | None = None
    if r_squared is None or r_squared < policy.minimum_fit_r_squared:
        rejection = "single-exponential fit below the registered R squared floor"
    elif tau_ms > policy.maximum_tau_to_window_ratio * observed_window_ms:
        rejection = "fitted time constant is longer than the transient actually observed"
    if rejection is not None:
        return {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": r_squared,
            "charging_sample_count": int(x.size),
            "charging_rejection": rejection,
            "charging_rejected_tau_ms": tau_ms,
        }
    return {
        "membrane_tau_ms": tau_ms,
        "charging_fit_r_squared": r_squared,
        "charging_sample_count": int(x.size),
        "charging_rejection": None,
        "charging_rejected_tau_ms": None,
    }


@dataclass(frozen=True, slots=True)
class StepDiagnosticsPolicy:
    """Preregistered sensitivity diagnostics that sit beside the primary step analysis.

    The primary analysis fixes an asymptote for the relaxation fit and a fixed upstroke
    velocity for the threshold. Both are assumptions whose effect on the reported value
    has to be visible, so these diagnostics report the same quantities under the
    alternative rule without replacing the primary values.
    """

    spike_threshold_slope_fraction: float
    relaxation_sensitivity_window_ms: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> StepDiagnosticsPolicy:
        policy = cls(
            spike_threshold_slope_fraction=float(raw["spike_threshold_slope_fraction"]),
            relaxation_sensitivity_window_ms=float(raw["relaxation_sensitivity_window_ms"]),
        )
        if not 0.0 < policy.spike_threshold_slope_fraction < 1.0:
            raise ConfigurationError("Threshold slope fraction must lie strictly between 0 and 1")
        if not math.isfinite(policy.relaxation_sensitivity_window_ms) or (
            policy.relaxation_sensitivity_window_ms <= 0.0
        ):
            raise ConfigurationError("Relaxation sensitivity window must be positive and finite")
        return policy

    def as_dict(self) -> dict[str, float]:
        return {
            "spike_threshold_slope_fraction": self.spike_threshold_slope_fraction,
            "relaxation_sensitivity_window_ms": self.relaxation_sensitivity_window_ms,
        }


def free_asymptote_exponential_fit(
    elapsed_ms: np.ndarray, voltage_mv: np.ndarray
) -> dict[str, Any]:
    """Fit ``V(t) = A exp(-t / tau) + C`` with the asymptote ``C`` left free.

    The primary relaxation fit pins the asymptote to the pre-step baseline. When the
    baseline has drifted during the step that pin biases the time constant, so this fit
    lets the data choose the asymptote and reports how far the two answers sit apart. It
    is a sensitivity diagnostic, not a replacement for the gated estimate.
    """
    elapsed = np.asarray(elapsed_ms, dtype=np.float64)
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    if elapsed.shape != voltage.shape or elapsed.ndim != 1:
        raise ConfigurationError("Free-asymptote fit needs matching one-dimensional inputs")
    if elapsed.size < 10:
        return {
            "tau_ms": None,
            "asymptote_mv": None,
            "amplitude_mv": None,
            "r_squared": None,
            "sample_count": int(elapsed.size),
        }
    total = float(np.sum((voltage - voltage.mean()) ** 2))
    best: tuple[float, float, np.ndarray] | None = None
    for candidate_tau in np.geomspace(0.5, 2_000.0, 600):
        design = np.column_stack([np.exp(-elapsed / candidate_tau), np.ones_like(elapsed)])
        coefficients, *_ = np.linalg.lstsq(design, voltage, rcond=None)
        residual = float(np.sum((voltage - design @ coefficients) ** 2))
        if best is None or residual < best[0]:
            best = (residual, float(candidate_tau), coefficients)
    assert best is not None
    best_residual, best_tau, best_coefficients = best
    return {
        "tau_ms": best_tau,
        "asymptote_mv": float(best_coefficients[1]),
        "amplitude_mv": float(best_coefficients[0]),
        "r_squared": 1.0 - best_residual / total if total > 0.0 else None,
        "sample_count": int(elapsed.size),
    }


def upstroke_diagnostics(
    voltage_mv: np.ndarray,
    spike_indices: np.ndarray,
    *,
    sample_interval_us: int,
    upstroke_criterion_mv_per_ms: float,
    search_window_ms: float,
    slope_fraction: float,
) -> dict[str, Any]:
    """How the fixed upstroke criterion relates to the spikes it is applied to.

    A criterion that sits at or above the peak upstroke velocity of the recorded spikes
    reports the voltage near the steepest point of the spike rather than a threshold, and
    silently drops the spikes that never reach it. The fraction-of-peak-slope rule scales
    with each spike and is reported alongside so the two can be compared.
    """
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    indices = np.asarray(spike_indices, dtype=np.int64)
    if indices.size == 0:
        return {
            "upstroke_peak_dv_dt_mv_per_ms": None,
            "spikes_reaching_upstroke_criterion": 0,
            "spike_threshold_at_slope_fraction_mv": None,
        }
    dt_ms = sample_interval_us / 1_000.0
    span = max(2, round(search_window_ms / dt_ms))
    derivative = np.gradient(voltage, dt_ms)
    peak_slopes: list[float] = []
    reaching = 0
    fractional: list[float] = []
    for index in indices:
        start = max(0, int(index) - span)
        segment = derivative[start : int(index) + 1]
        peak_slope = float(np.max(segment))
        peak_slopes.append(peak_slope)
        if peak_slope >= upstroke_criterion_mv_per_ms:
            reaching += 1
        if peak_slope > 0.0:
            crossing = np.flatnonzero(segment >= slope_fraction * peak_slope)
            fractional.append(float(voltage[start + int(crossing[0])]))
    return {
        "upstroke_peak_dv_dt_mv_per_ms": float(np.median(peak_slopes)),
        "spikes_reaching_upstroke_criterion": int(reaching),
        "spike_threshold_at_slope_fraction_mv": (
            float(np.median(fractional)) if fractional else None
        ),
    }


def current_step_features(
    current_pa: np.ndarray,
    voltage_mv: np.ndarray,
    *,
    sample_interval_us: int,
    spike_policy: SpikeDetectionPolicy,
    step_policy: StepAnalysisPolicy,
    upstroke_criterion_mv_per_ms: float = 10.0,
    threshold_search_window_ms: float = 5.0,
    diagnostics: StepDiagnosticsPolicy | None = None,
) -> list[dict[str, Any]]:
    """Per-sweep cellular features from a paired injected-current and voltage protocol.

    ``diagnostics`` is optional so that a contract written before the diagnostics existed
    reproduces its recorded output exactly; a contract that registers them gets the extra
    fields appended to every sweep record.
    """
    current = np.asarray(current_pa, dtype=np.float64)
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    if current.shape != voltage.shape or current.ndim != 2:
        raise ConfigurationError("Current and voltage sweeps must share a two-dimensional shape")
    if not (np.all(np.isfinite(current)) and np.all(np.isfinite(voltage))):
        raise DatasetError("Current-step protocol contains nonfinite samples")
    dt_ms = sample_interval_us / 1_000.0
    settle = max(1, round(step_policy.baseline_settle_ms / dt_ms))
    steady = max(1, round(step_policy.steady_window_ms / dt_ms))

    features: list[dict[str, Any]] = []
    for sweep_index in range(current.shape[0]):
        start, end, amplitude = _step_window(current[sweep_index])
        if start <= settle:
            raise DatasetError("Sweep has no pre-step baseline outside the settling window")
        trace = voltage[sweep_index]
        baseline = float(np.mean(trace[: start - settle]))
        spike_indices = detect_spikes(
            trace, sample_interval_us=sample_interval_us, policy=spike_policy
        )
        in_step = spike_indices[(spike_indices >= start) & (spike_indices <= end)]
        step_duration_ms = (end - start + 1) * dt_ms
        steady_start = max(start, end - steady + 1)
        steady_state = float(np.mean(trace[steady_start : end + 1]))
        subthreshold = in_step.size == 0
        charging: dict[str, Any] = {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": None,
            "charging_sample_count": 0,
            "charging_rejection": "sweep is suprathreshold; spikes forbid a passive fit",
            "charging_rejected_tau_ms": None,
        }
        input_resistance: float | None = None
        if subthreshold:
            elapsed = np.arange(end - start + 1, dtype=np.float64) * dt_ms
            charging = _charging_time_constant_ms(
                elapsed, trace[start : end + 1], baseline, steady_state, step_policy
            )
            if amplitude != 0.0:
                input_resistance = 1_000.0 * (steady_state - baseline) / amplitude
        # A protocol whose smallest step already fires gives no passive charging phase.
        # The relaxation after step offset is passive whenever no spike follows it, so it
        # recovers the same membrane time constant from an otherwise suprathreshold sweep.
        after_step = spike_indices[spike_indices > end]
        relaxation: dict[str, Any] = {
            "membrane_tau_ms": None,
            "charging_fit_r_squared": None,
            "charging_sample_count": 0,
            "charging_rejection": "a spike follows step offset; the relaxation is not passive",
            "charging_rejected_tau_ms": None,
        }
        if after_step.size == 0 and end + 2 < trace.size:
            tail = trace[end + 1 :]
            relaxation = _charging_time_constant_ms(
                np.arange(tail.size, dtype=np.float64) * dt_ms,
                tail,
                float(trace[end]),
                baseline,
                step_policy,
            )
        record: dict[str, Any] = {
            "sweep_index": sweep_index,
            "injected_current_pa": amplitude,
            "step_onset_us": int(start * sample_interval_us),
            "step_duration_ms": step_duration_ms,
            "baseline_potential_mv": baseline,
            "steady_state_potential_mv": steady_state,
            "subthreshold": subthreshold,
            "input_resistance_mohm": input_resistance,
            "spike_count": int(in_step.size),
            "firing_rate_hz": float(in_step.size) / (step_duration_ms / 1_000.0),
            "spike_times_ms": [float((int(index) - start) * dt_ms) for index in in_step],
            "post_step_spike_count": int(after_step.size),
            "spike_threshold_mv": spike_threshold_mv(
                trace,
                in_step,
                sample_interval_us=sample_interval_us,
                upstroke_criterion_mv_per_ms=upstroke_criterion_mv_per_ms,
                search_window_ms=threshold_search_window_ms,
            ),
            "minimum_interspike_interval_ms": minimum_interspike_interval_ms(
                in_step, sample_interval_us=sample_interval_us
            ),
        }
        record.update(charging)
        record.update({"relaxation_" + key: value for key, value in relaxation.items()})
        record.update(
            {
                "adaptation_" + key: value
                for key, value in adaptation_statistics(
                    in_step, sample_interval_us=sample_interval_us
                ).items()
            }
        )
        if diagnostics is not None:
            # The deflection is reported so that a sweep classified as subthreshold only
            # because the detector missed its spikes is visibly implausible.
            record["maximum_in_step_deflection_mv"] = float(
                np.max(trace[start : end + 1]) - baseline
            )
            record.update(
                upstroke_diagnostics(
                    trace,
                    in_step,
                    sample_interval_us=sample_interval_us,
                    upstroke_criterion_mv_per_ms=upstroke_criterion_mv_per_ms,
                    search_window_ms=threshold_search_window_ms,
                    slope_fraction=diagnostics.spike_threshold_slope_fraction,
                )
            )
            free_fit: dict[str, Any] | None = None
            if after_step.size == 0 and end + 2 < trace.size:
                window = max(1, round(diagnostics.relaxation_sensitivity_window_ms / dt_ms))
                tail = trace[end + 1 : end + 1 + window]
                free_fit = free_asymptote_exponential_fit(
                    np.arange(tail.size, dtype=np.float64) * dt_ms, tail
                )
                free_fit["assumed_asymptote_mv"] = baseline
                free_fit["window_ms"] = diagnostics.relaxation_sensitivity_window_ms
            record["relaxation_free_asymptote"] = free_fit
        features.append(record)
    return features


def summarise_current_step_protocol(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Cell-level V1 observables from the per-sweep features of one protocol."""
    if not features:
        raise ConfigurationError("Cannot summarise an empty current-step protocol")
    baselines = [float(item["baseline_potential_mv"]) for item in features]
    taus = [
        float(item["membrane_tau_ms"]) for item in features if item["membrane_tau_ms"] is not None
    ]
    relaxation_taus = [
        float(item["relaxation_membrane_tau_ms"])
        for item in features
        if item.get("relaxation_membrane_tau_ms") is not None
    ]
    resistances = [
        float(item["input_resistance_mohm"])
        for item in features
        if item["input_resistance_mohm"] is not None
    ]
    spiking = [item for item in features if int(item["spike_count"]) > 0]
    silent = [item for item in features if int(item["spike_count"]) == 0]
    ratios = [
        float(item["adaptation_adaptation_ratio"])
        for item in features
        if item.get("adaptation_adaptation_ratio") is not None
    ]
    rheobase_upper = (
        min(float(item["injected_current_pa"]) for item in spiking) if spiking else None
    )
    rheobase_lower = None
    if rheobase_upper is not None:
        below = [
            float(item["injected_current_pa"])
            for item in silent
            if float(item["injected_current_pa"]) < rheobase_upper
        ]
        rheobase_lower = max(below) if below else None
    thresholds = [
        float(item["spike_threshold_mv"])
        for item in features
        if item.get("spike_threshold_mv") is not None
    ]
    minima = [
        float(item["minimum_interspike_interval_ms"])
        for item in features
        if item.get("minimum_interspike_interval_ms") is not None
    ]
    currents = [float(item["injected_current_pa"]) for item in features]
    rates = [float(item["firing_rate_hz"]) for item in features]
    summary: dict[str, Any] = {
        "sweep_count": len(features),
        "resting_potential_mv": float(np.median(baselines)),
        "resting_potential_range_mv": [float(min(baselines)), float(max(baselines))],
        "membrane_tau_ms": float(np.median(taus)) if taus else None,
        "membrane_tau_sample_count": len(taus),
        "membrane_tau_from_charging_ms": float(np.median(taus)) if taus else None,
        "membrane_tau_from_relaxation_ms": (
            float(np.median(relaxation_taus)) if relaxation_taus else None
        ),
        "membrane_tau_relaxation_sample_count": len(relaxation_taus),
        "membrane_tau_relaxation_range_ms": (
            [float(min(relaxation_taus)), float(max(relaxation_taus))]
            if relaxation_taus
            else None
        ),
        "input_resistance_mohm": float(np.median(resistances)) if resistances else None,
        "input_resistance_sample_count": len(resistances),
        "rheobase_lower_bound_pa": rheobase_lower,
        "rheobase_upper_bound_pa": rheobase_upper,
        "fi_curve": [
            {"injected_current_pa": current, "firing_rate_hz": rate}
            for current, rate in zip(currents, rates, strict=True)
        ],
        "fi_monotonic": all(
            later >= earlier for earlier, later in pairwise(rates)
        ),
        "adaptation_ratio_median": float(np.median(ratios)) if ratios else None,
        "adaptation_ratio_sample_count": len(ratios),
        "spike_threshold_mv": float(np.median(thresholds)) if thresholds else None,
        "spike_threshold_sample_count": len(thresholds),
        "minimum_interspike_interval_ms": float(min(minima)) if minima else None,
        "stimulus_resolution": STIMULUS_RESOLVED,
    }
    if any("relaxation_free_asymptote" in item for item in features):
        summary.update(_summarise_step_diagnostics(features))
    return summary


def _summarise_step_diagnostics(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Cell-level view of the sensitivity diagnostics, kept apart from the primary values."""
    fractional = [
        float(item["spike_threshold_at_slope_fraction_mv"])
        for item in features
        if item.get("spike_threshold_at_slope_fraction_mv") is not None
    ]
    peak_slopes = [
        float(item["upstroke_peak_dv_dt_mv_per_ms"])
        for item in features
        if item.get("upstroke_peak_dv_dt_mv_per_ms") is not None
    ]
    spikes = sum(int(item["spike_count"]) for item in features)
    reaching = sum(int(item.get("spikes_reaching_upstroke_criterion", 0)) for item in features)
    free_fits = [
        {
            "sweep_index": int(item["sweep_index"]),
            "tau_ms": item["relaxation_free_asymptote"]["tau_ms"],
            "asymptote_mv": item["relaxation_free_asymptote"]["asymptote_mv"],
            "assumed_asymptote_mv": item["relaxation_free_asymptote"]["assumed_asymptote_mv"],
            "r_squared": item["relaxation_free_asymptote"]["r_squared"],
            "gated_tau_ms": item.get("relaxation_membrane_tau_ms"),
        }
        for item in features
        if item.get("relaxation_free_asymptote") is not None
    ]
    accepted = [
        entry for entry in free_fits if entry["gated_tau_ms"] is not None and entry["tau_ms"]
    ]
    return {
        "spike_threshold_at_slope_fraction_mv": (
            float(np.median(fractional)) if fractional else None
        ),
        "upstroke_peak_dv_dt_mv_per_ms": float(np.median(peak_slopes)) if peak_slopes else None,
        "spikes_reaching_upstroke_criterion_fraction": (
            reaching / spikes if spikes else None
        ),
        "maximum_in_step_deflection_mv": [
            item.get("maximum_in_step_deflection_mv") for item in features
        ],
        "relaxation_free_asymptote_fits": free_fits,
        "membrane_tau_free_asymptote_on_accepted_sweeps_ms": (
            [float(entry["tau_ms"]) for entry in accepted] if accepted else None
        ),
    }


def stimulus_free_features(
    voltage_mv: np.ndarray,
    *,
    sample_interval_us: int,
    spike_policy: SpikeDetectionPolicy,
    report_pre_spike_baseline: bool = False,
) -> dict[str, Any]:
    """Current-independent observables from a trace whose stimulus was never published.

    ``report_pre_spike_baseline`` adds the median voltage before the first detected spike.
    For a trace that carries an unpublished stimulus epoch followed by a long
    after-hyperpolarization, the whole-trace masked median is pulled toward the
    post-stimulus level, and the pre-spike segment is the only part that is certainly
    free of both.
    """
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    spike_indices = detect_spikes(
        voltage, sample_interval_us=sample_interval_us, policy=spike_policy
    )
    duration_s = voltage.size * sample_interval_us / 1_000_000.0
    record: dict[str, Any] = {
        "sample_count": int(voltage.size),
        "duration_s": duration_s,
        "resting_potential_mv": resting_potential_mv(
            voltage, spike_indices, sample_interval_us=sample_interval_us, policy=spike_policy
        ),
        "minimum_potential_mv": float(np.min(voltage)),
        "peak_potential_mv": float(np.max(voltage)),
        "spike_count": int(spike_indices.size),
        "mean_rate_hz": float(spike_indices.size) / duration_s if duration_s > 0.0 else None,
        "somatic_spike_amplitude_mv": somatic_spike_amplitude_mv(
            voltage, spike_indices, sample_interval_us=sample_interval_us, policy=spike_policy
        ),
        "median_spike_peak_mv": (
            float(np.median(voltage[spike_indices])) if spike_indices.size else None
        ),
        "overshoots_zero_mv": (
            bool(np.median(voltage[spike_indices]) > 0.0) if spike_indices.size else None
        ),
        "stimulus_resolution": STIMULUS_IRRECOVERABLE,
    }
    record.update(
        {
            "adaptation_" + key: value
            for key, value in adaptation_statistics(
                spike_indices, sample_interval_us=sample_interval_us
            ).items()
        }
    )
    if report_pre_spike_baseline:
        half = max(1, round(spike_policy.resting_mask_ms / (sample_interval_us / 1_000.0)))
        cutoff = int(spike_indices[0]) - half if spike_indices.size else voltage.size
        segment = voltage[: max(0, cutoff)]
        record["pre_first_spike_resting_potential_mv"] = (
            float(np.median(segment)) if segment.size else None
        )
        record["pre_first_spike_duration_ms"] = segment.size * sample_interval_us / 1_000.0
    return record


def spike_threshold_mv(
    voltage_mv: np.ndarray,
    spike_indices: np.ndarray,
    *,
    sample_interval_us: int,
    upstroke_criterion_mv_per_ms: float,
    search_window_ms: float,
) -> float | None:
    """Median voltage at which the upstroke first exceeds the registered rate criterion.

    A fixed absolute threshold cannot be read off a somatic recording whose spikes are
    attenuated, so the rate criterion is applied to the upstroke and the crossing voltage
    is reported. Cells whose spikes never reach the criterion return None rather than a
    number derived from a slower depolarization.
    """
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    indices = np.asarray(spike_indices, dtype=np.int64)
    if indices.size == 0:
        return None
    dt_ms = sample_interval_us / 1_000.0
    span = max(2, round(search_window_ms / dt_ms))
    derivative = np.gradient(voltage, dt_ms)
    crossings: list[float] = []
    for index in indices:
        start = max(0, int(index) - span)
        segment = derivative[start : int(index) + 1]
        fast = np.flatnonzero(segment >= upstroke_criterion_mv_per_ms)
        if fast.size:
            crossings.append(float(voltage[start + int(fast[0])]))
    return float(np.median(crossings)) if crossings else None


def minimum_interspike_interval_ms(
    spike_indices: np.ndarray, *, sample_interval_us: int
) -> float | None:
    """Shortest observed interval, an upper bound on the absolute refractory period."""
    intervals = _interspike_intervals_ms(spike_indices, sample_interval_us)
    return float(np.min(intervals)) if intervals.size else None
