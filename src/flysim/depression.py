# SPDX-License-Identifier: GPL-2.0-or-later
"""What the frozen ND-06 depression rule predicts about paired-pulse and train recordings.

The registered rule is a depression-only Tsodyks-Markram resource with one utilisation and
one recovery time constant. From rest it makes closed-form predictions for two observables
and no others: the ratio of a second response to a first at a given interval, and the
amplitude of the nth response in a regular train. This module computes them, and it exists
so that a prediction can be committed before an external recording is opened rather than
derived afterwards.

Everything the rule cannot generate is left out on purpose. It has no latency term, no
quantal amplitude, no spontaneous release rate and no absolute conductance, so response
latency, latency jitter, miniature EPSC amplitude and frequency, and evoked amplitude in
picoamps are not predicted here even where a dataset supplies them. Adding an observable a
model cannot produce turns a test into an exercise in choosing what to report.

The three published fits travel as pairs. A utilisation from one pharmacological component
and a recovery constant from another describe no measurement, so the prediction band is the
envelope over three points in parameter space rather than a rectangle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flysim.config import load_json, sha256_json
from flysim.errors import ConfigurationError
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot


@dataclass(frozen=True, slots=True)
class PublishedFit:
    """One published (utilisation, recovery) pair, never split across fits."""

    fit_id: str
    utilisation: float
    recovery_tau_ms: float
    primary: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.fit_id,
            "utilisation": self.utilisation,
            "recovery_tau_ms": self.recovery_tau_ms,
            "primary": self.primary,
        }


def paired_pulse_ratio(*, utilisation: float, recovery_tau_ms: float, interval_ms: float) -> float:
    """Second-to-first response ratio from rest.

    The resource is one before the first spike and ``1 - utilisation`` after it, and it
    recovers exponentially, so the ratio is ``1 - U exp(-dt/tau)``. This has a consequence
    worth stating: the ratio cannot fall below ``1 - utilisation`` at any interval, which
    is the sharpest refutable claim the rule makes about a paired-pulse experiment.
    """
    _check(utilisation, recovery_tau_ms)
    if interval_ms <= 0.0:
        raise ConfigurationError("A paired-pulse interval must be positive")
    return 1.0 - utilisation * math.exp(-interval_ms / recovery_tau_ms)


def train_resource(
    *, utilisation: float, recovery_tau_ms: float, interval_ms: float, pulses: int
) -> tuple[float, ...]:
    """Resource available to each pulse of a regular train started from rest."""
    _check(utilisation, recovery_tau_ms)
    if interval_ms <= 0.0:
        raise ConfigurationError("A train interval must be positive")
    if pulses < 1:
        raise ConfigurationError("A train needs at least one pulse")
    recovery = math.exp(-interval_ms / recovery_tau_ms)
    resource = 1.0
    trajectory = [resource]
    for _ in range(pulses - 1):
        resource = 1.0 - (1.0 - resource * (1.0 - utilisation)) * recovery
        trajectory.append(resource)
    return tuple(trajectory)


def train_steady_state(
    *, utilisation: float, recovery_tau_ms: float, interval_ms: float
) -> float:
    """Fixed point of the train recursion, ``(1 - c) / (1 - (1 - U) c)``.

    This is the exact discrete value, not the mean-field approximation the registry also
    records; the two diverge most at low rates, where a 1 Hz train is nearly full recovery
    between pulses and the mean-field form still predicts appreciable depression.
    """
    _check(utilisation, recovery_tau_ms)
    if interval_ms <= 0.0:
        raise ConfigurationError("A train interval must be positive")
    recovery = math.exp(-interval_ms / recovery_tau_ms)
    return (1.0 - recovery) / (1.0 - (1.0 - utilisation) * recovery)


def _check(utilisation: float, recovery_tau_ms: float) -> None:
    if not 0.0 < utilisation <= 1.0:
        raise ConfigurationError("Utilisation must lie in (0, 1]")
    if not recovery_tau_ms > 0.0 or not math.isfinite(recovery_tau_ms):
        raise ConfigurationError("Recovery time constant must be positive and finite")


def load_published_fits(registry_path: Path, *, rule_id: str) -> tuple[PublishedFit, ...]:
    """Read the paired fits for one rule and check them against the registered ranges."""
    payload = load_json(registry_path)
    rules = {str(rule["rule_id"]): rule for rule in payload["rules"]}
    if rule_id not in rules:
        raise ConfigurationError(f"Rule {rule_id!r} is not in the plasticity registry")
    rule = rules[rule_id]
    raw = rule.get("published_fits")
    if not raw:
        raise ConfigurationError(f"Rule {rule_id!r} carries no published fits to predict from")
    low, high = (float(rule["utilisation_range"][0]), float(rule["utilisation_range"][1]))
    tau_low, tau_high = (
        float(rule["recovery_tau_ms"]["range"][0]),
        float(rule["recovery_tau_ms"]["range"][1]),
    )
    fits: list[PublishedFit] = []
    for entry in raw:
        utilisation = float(entry["utilisation"])
        recovery = float(entry["recovery_tau_ms"])
        if not low <= utilisation <= high:
            raise ConfigurationError(
                f"Published fit {entry['id']!r} has a utilisation outside the registered range"
            )
        if not tau_low <= recovery <= tau_high:
            raise ConfigurationError(
                f"Published fit {entry['id']!r} has a recovery constant outside its range"
            )
        fits.append(
            PublishedFit(
                fit_id=str(entry["id"]),
                utilisation=utilisation,
                recovery_tau_ms=recovery,
                primary=bool(entry.get("primary", False)),
            )
        )
    primaries = [fit for fit in fits if fit.primary]
    if len(primaries) != 1:
        raise ConfigurationError("Exactly one published fit must be marked primary")
    primary = primaries[0]
    if primary.utilisation != float(rule["utilisation"]):
        raise ConfigurationError("The primary fit does not match the registered utilisation")
    if primary.recovery_tau_ms != float(rule["recovery_tau_ms"]["value"]):
        raise ConfigurationError(
            "The primary fit does not match the registered recovery time constant"
        )
    return tuple(fits)


def _band(values: dict[str, float]) -> dict[str, float]:
    return {"lowest": min(values.values()), "highest": max(values.values())}


def predict(
    *,
    fits: tuple[PublishedFit, ...],
    paired_pulse_intervals_ms: tuple[float, ...],
    train_frequencies_hz: tuple[float, ...],
    train_pulses: dict[str, int],
) -> dict[str, Any]:
    """Every prediction the rule makes for the named intervals and frequencies."""
    primary = next(fit for fit in fits if fit.primary)
    paired: list[dict[str, Any]] = []
    for interval in paired_pulse_intervals_ms:
        by_fit = {
            fit.fit_id: paired_pulse_ratio(
                utilisation=fit.utilisation,
                recovery_tau_ms=fit.recovery_tau_ms,
                interval_ms=interval,
            )
            for fit in fits
        }
        paired.append(
            {
                "interval_ms": interval,
                "primary_prediction": by_fit[primary.fit_id],
                "by_published_fit": by_fit,
                "registered_family_band": _band(by_fit),
            }
        )
    trains: list[dict[str, Any]] = []
    for frequency in train_frequencies_hz:
        interval = 1000.0 / frequency
        pulses = int(train_pulses[f"{frequency:g}"])
        by_fit = {
            fit.fit_id: train_steady_state(
                utilisation=fit.utilisation,
                recovery_tau_ms=fit.recovery_tau_ms,
                interval_ms=interval,
            )
            for fit in fits
        }
        final = {
            fit.fit_id: train_resource(
                utilisation=fit.utilisation,
                recovery_tau_ms=fit.recovery_tau_ms,
                interval_ms=interval,
                pulses=pulses,
            )[-1]
            for fit in fits
        }
        trains.append(
            {
                "frequency_hz": frequency,
                "interstimulus_interval_ms": interval,
                "pulses_in_the_recording": pulses,
                "primary_steady_state": by_fit[primary.fit_id],
                "primary_final_pulse": final[primary.fit_id],
                "by_published_fit_steady_state": by_fit,
                "by_published_fit_final_pulse": final,
                "registered_family_band_steady_state": _band(by_fit),
            }
        )
    floor = min(1.0 - fit.utilisation for fit in fits)
    return {
        "published_fits": [fit.as_dict() for fit in fits],
        "paired_pulse": paired,
        "trains": trains,
        "hard_bounds": {
            "paired_pulse_ratio_floor": floor,
            "why": (
                "The ratio is 1 - U exp(-dt/tau), which approaches 1 - U as the interval "
                "shrinks and 1 as it grows. No interval, and no member of the registered "
                f"family, can produce a ratio below {floor:.4f}. A measured mean below that "
                "refutes the rule as registered without any threshold being chosen."
            ),
            "monotone_in_interval": True,
        },
        "not_predicted": {
            "response_latency_ms": (
                "ND-06 has no latency term. ND-05 carries conduction and release latency "
                "as a policy with no fitted value for this preparation, and the "
                "stimulating-electrode distance is unknown, so no number can be generated."
            ),
            "latency_jitter_ms": (
                "Requires the stochastic-release class. The registered baseline is "
                "static-deterministic, so the model produces exactly zero jitter, which is "
                "a degenerate prediction rather than a testable one."
            ),
            "miniature_epsc_amplitude_pa": "No quantal amplitude is registered.",
            "miniature_epsc_frequency_hz": "No spontaneous release rate is registered.",
            "evoked_amplitude_pa": (
                "ND-04 is contact_count times a type-pair scale with "
                "contact_count_is_strength false, so there is no absolute conductance to "
                "convert into picoamps."
            ),
            "bruchpilot_puncta": (
                "A light-microscopy release-site count is not the same unit as an "
                "electron-microscopy contact count; the identification of the two is itself "
                "under test and cannot be assumed in order to score it."
            ),
        },
    }


def run_depression_prediction(
    *,
    experiment_path: Path,
    registry_path: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Write the predictions named by a preregistration, before any value is opened."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The depression prediction run")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported depression external-test contract schema")
    if contract.get("values_opened"):
        raise ConfigurationError(
            "This contract records that the reserved values are already open; a prediction "
            "written afterwards is not a prediction"
        )
    design = contract["prediction_grid"]
    fits = load_published_fits(registry_path, rule_id=str(design["rule_id"]))
    predictions = predict(
        fits=fits,
        paired_pulse_intervals_ms=tuple(
            float(value) for value in design["paired_pulse_intervals_ms"]
        ),
        train_frequencies_hz=tuple(float(value) for value in design["train_frequencies_hz"]),
        train_pulses={str(key): int(value) for key, value in design["train_pulses"].items()},
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-depression-prediction-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "F",
        "assumption_ids": list(contract["assumption_ids"]),
        "registry_id": str(load_json(registry_path)["registry_id"]),
        "registry_sha256": sha256_json(load_json(registry_path)),
        "predictions": predictions,
        "measured_values_read": False,
        "claim_boundary": (
            "Predictions only. No reserved observation is read, nothing is scored, and no "
            "tier is awarded. Its purpose is to exist, checksummed and committed, before "
            "the recording it predicts is opened."
        ),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "evidence_grade": not worktree["dirty"],
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot),
    }
