# SPDX-License-Identifier: GPL-2.0-or-later
"""Fit the ORN-to-PN plasticity families jointly to a paired-pulse curve and a train.

The whole reason the previous attempt failed is here in one sentence. A paired-pulse
curve cannot constrain the resource recovery constant -- the 300 ms and 1000 ms cohort
means differ by 0.0003 against a pooled standard error of 0.0277 -- so every family drove
that constant to its bound, which is invisible across a single pair and catastrophic
across a sustained train. Both frozen candidates then predicted a 7 Hz steady state near
0.08 against a published 0.60.

A 1 Hz train of 32 pulses constrains it directly, and the corpus turned out to hold one
in Fig3B all along. So this module fits both observables at once:

* the five Fig3D wild-type paired-pulse cohort means, spent on 2026-09-09;
* the thirty-one scorable pulses of the Fig3B wild-type 1 Hz trajectory, spent on
  2026-09-10 while characterising the mis-described latency arrays.

Both are spent. Neither can test anything again, and fitting to them costs nothing that
has not already been paid. The test is Fig3G, a day-0 1 Hz train in twenty animals that
has never been decoded.

Kazama and Wilson's 7 Hz steady state is deliberately **not** in the objective. It comes
from a different laboratory and a different preparation, and keeping it out leaves one
independent published number to check the joint fit against afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.depression_score import ALL_INTERVALS_MS, summarise, variable_for
from flysim.errors import ConfigurationError
from flysim.reservations import read_mat_variable
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot
from flysim.stp_families import (
    KAZAMA_WILSON_RELEASE_PROBABILITY,
    SELECTION_ORDER,
    Observation,
    _from_box,
    _latin_hypercube,
    _to_box,
    amplitudes,
    chi_square_upper_tail,
    effective_first_pulse_utilisation,
    family,
    nelder_mead,
    paired_pulse,
)

PAIRED_SOURCE = "rozenfeld2023-repo/Figure 3/Fig3D.mat"
TRAIN_SOURCE = "rozenfeld2023-repo/Figure 3/Fig3B.mat"
TRAIN_VARIABLE = "all_flies_1Hz_control"
TRAIN_HERTZ = 1.0
KAZAMA_WILSON_7HZ_STEADY_STATE = 0.60

# The screens, mirrored from the committed contract. E1 and E2 are unchanged in spirit
# from the paired-pulse-only selection; E3 has no work to do because the joint fit leaves
# no constant pinned -- the train constrains the one that used to be.
REQUIRED_PAIRED_INSIDE = 5
REQUIRED_TRAIN_FRACTION_INSIDE = 0.80
BOUND_FRACTION = 0.01


@dataclass(frozen=True, slots=True)
class TrainObservation:
    """One cohort-mean train trajectory, normalised to its own first pulse."""

    hertz: float
    normalised: tuple[float, ...]
    standard_error: tuple[float, ...]
    animals: tuple[int, ...]

    @property
    def pulses(self) -> int:
        return len(self.normalised)


def normalise_train(values: np.ndarray) -> dict[str, Any]:
    """Cohort-mean trajectory over its own first pulse, with per-pulse standard errors.

    Magnitudes are taken because the arrays hold evoked currents and are negative. The
    cohort mean is formed at each pulse and the whole mean trajectory divided by its own
    first element, which avoids dividing each animal by a single noisy measurement.
    """
    magnitudes = np.abs(np.asarray(values, dtype=np.float64))
    if magnitudes.ndim != 2:
        raise ConfigurationError("A train array must be animals by pulses")
    finite = np.isfinite(magnitudes)
    counts = finite.sum(axis=0)
    if counts[0] < 2:
        raise ConfigurationError("The first pulse needs at least two finite values")
    means = np.array(
        [
            float(np.mean(magnitudes[finite[:, i], i])) if counts[i] >= 1 else np.nan
            for i in range(magnitudes.shape[1])
        ]
    )
    deviations = np.array(
        [
            float(np.std(magnitudes[finite[:, i], i], ddof=1)) if counts[i] >= 2 else np.nan
            for i in range(magnitudes.shape[1])
        ]
    )
    errors = deviations / np.sqrt(np.maximum(counts, 1))
    return {
        "pulses": int(magnitudes.shape[1]),
        "animals_per_pulse": [int(value) for value in counts],
        "first_pulse_magnitude": float(means[0]),
        "normalised": [float(value) for value in means / means[0]],
        "standard_error": [float(value) for value in errors / means[0]],
    }


def joint_residuals(
    family_id: str,
    theta: tuple[float, ...],
    paired: list[Observation],
    train: TrainObservation,
) -> dict[str, float]:
    """Weighted squared error on each observable, and their sum.

    The train's first pulse is excluded: the normalisation makes it exactly one for the
    data and for every model alike, so it carries no information and has no error.
    """
    paired_error = 0.0
    for row in paired:
        predicted = paired_pulse(family_id, theta, row.interval_ms)
        paired_error += ((predicted - row.mean) / row.standard_error) ** 2

    interval = 1000.0 / train.hertz
    values = amplitudes(family_id, theta, [i * interval for i in range(train.pulses)])
    curve = values / values[0]
    train_error = 0.0
    scored = 0
    for index in range(1, train.pulses):
        observed, error = train.normalised[index], train.standard_error[index]
        if not np.isfinite(observed) or not np.isfinite(error) or error <= 0.0:
            continue
        train_error += ((curve[index] - observed) / error) ** 2
        scored += 1
    return {
        "paired_pulse": paired_error,
        "train": train_error,
        "train_pulses_scored": float(scored),
        "total": paired_error + train_error,
    }


def fit_jointly(
    family_id: str,
    paired: list[Observation],
    train: TrainObservation,
    *,
    restarts: int = 48,
    seed: int = 20260910,
) -> dict[str, Any]:
    """Weighted least squares over both observables at once."""
    spec = family(family_id)
    rng = np.random.default_rng(seed)
    starts = _latin_hypercube(spec, restarts, rng)

    def objective(unbounded: np.ndarray) -> float:
        theta = tuple(float(v) for v in _to_box(unbounded, spec))
        return joint_residuals(family_id, theta, paired, train)["total"]

    best: np.ndarray | None = None
    best_value = float("inf")
    for start in starts:
        candidate, value = nelder_mead(objective, _from_box(start, spec))
        if value < best_value:
            best, best_value = candidate, value
    assert best is not None
    theta = tuple(float(v) for v in _to_box(best, spec))
    parts = joint_residuals(family_id, theta, paired, train)
    points = len(paired) + int(parts["train_pulses_scored"])
    degrees = points - spec.parameter_count
    at_bound = tuple(
        parameter.name
        for parameter, value in zip(spec.parameters, theta, strict=True)
        if (value - parameter.low) < BOUND_FRACTION * (parameter.high - parameter.low)
        or (parameter.high - value) < BOUND_FRACTION * (parameter.high - parameter.low)
    )
    return {
        "family_id": family_id,
        "parameters": dict(zip(spec.parameter_names, theta, strict=True)),
        "theta": theta,
        "weighted_sse": parts["total"],
        "weighted_sse_paired_pulse": parts["paired_pulse"],
        "weighted_sse_train": parts["train"],
        "points_scored": points,
        "degrees_of_freedom": degrees,
        "goodness_of_fit_p": (
            chi_square_upper_tail(parts["total"], degrees) if degrees >= 1 else None
        ),
        "parameters_at_a_bound": list(at_bound),
        "effective_first_pulse_utilisation": effective_first_pulse_utilisation(
            family_id, theta
        ),
    }


def steady_state(family_id: str, theta: tuple[float, ...], hertz: float) -> float:
    interval = 1000.0 / hertz
    pulses = min(int(60.0 * hertz), 4000)
    values = amplitudes(family_id, theta, [i * interval for i in range(pulses)])
    return float(np.mean(values[-5:] / values[0]))


def _verify(*, manifest_path: Path, relative_path: str, staging_root: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    entries = [
        entry
        for dataset in manifest["datasets"]
        for entry in dataset["files"]
        if entry["path"] == relative_path
    ]
    if len(entries) != 1:
        raise ConfigurationError(f"{relative_path} is not reserved exactly once")
    observed = sha256_file(staging_root / relative_path)
    if observed != entries[0]["sha256"]:
        raise ConfigurationError(
            f"{relative_path} has changed since it was reserved: manifest recorded "
            f"{entries[0]['sha256'][:16]}..., file is {observed[:16]}..."
        )
    return {"path": relative_path, "sha256": observed, "matches_sealed_manifest": True}


def run_joint_fit(
    *,
    contract_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    restarts: int = 48,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Fit every family to both spent observables and screen them."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The joint paired-pulse and train fit")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported joint-fit contract schema")
    if tuple(contract["families_considered"]) != SELECTION_ORDER:
        raise ConfigurationError("The contract's family list and the module disagree")

    paired_check = _verify(
        manifest_path=manifest_path, relative_path=PAIRED_SOURCE, staging_root=staging_root
    )
    train_check = _verify(
        manifest_path=manifest_path, relative_path=TRAIN_SOURCE, staging_root=staging_root
    )

    described: list[dict[str, Any]] = []
    paired: list[Observation] = []
    for interval in ALL_INTERVALS_MS:
        summary = summarise(read_mat_variable(staging_root / PAIRED_SOURCE, variable_for(interval)))
        paired.append(
            Observation(
                interval_ms=interval,
                mean=summary["mean"],
                standard_error=summary["standard_error"],
                animals=summary["animals_scored"],
            )
        )
        described.append({"interval_ms": interval, **summary})

    raw = read_mat_variable(staging_root / TRAIN_SOURCE, TRAIN_VARIABLE)
    train_summary = normalise_train(raw)
    train = TrainObservation(
        hertz=TRAIN_HERTZ,
        normalised=tuple(train_summary["normalised"]),
        standard_error=tuple(train_summary["standard_error"]),
        animals=tuple(train_summary["animals_per_pulse"]),
    )

    fits = {
        family_id: fit_jointly(family_id, paired, train, restarts=restarts)
        for family_id in SELECTION_ORDER
    }
    screened = {
        family_id: _screen(family_id, fit, paired, train, described)
        for family_id, fit in fits.items()
    }
    eligible = [name for name in SELECTION_ORDER if screened[name]["eligible"]]
    selection = _select(eligible, screened)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-stp-joint-fit-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "F",
        "assumption_ids": list(contract["assumption_ids"]),
        "this_is_a_fit_and_not_a_validation": (
            "Both observables are spent: the paired-pulse arrays on 2026-09-09 and the "
            "Fig3B train on 2026-09-10. No tier is awarded by this run. The test is "
            "Fig3G, which has never been decoded."
        ),
        "fit_set": {
            "paired_pulse": {**paired_check, "by_interval": described},
            "train": {**train_check, "variable": TRAIN_VARIABLE, "hertz": TRAIN_HERTZ,
                      **train_summary},
            "why_the_train_changes_everything": (
                "The paired-pulse curve cannot constrain the resource recovery constant: "
                "its 300 ms and 1000 ms means differ by 0.0003 against a pooled standard "
                "error of 0.0277. A 32-pulse train at 1 Hz constrains it directly, and "
                "that is the parameter whose bound-valued fit made both previous "
                "candidates predict a 7 Hz steady state near 0.08 against a published 0.60."
            ),
        },
        "families": screened,
        "eligible": eligible,
        "selection": selection,
        "independent_check_not_in_the_objective": {
            "source": "Kazama and Wilson 2008, 7 Hz steady state about 0.60",
            "why_it_is_kept_out_of_the_fit": (
                "A different laboratory and preparation, and keeping it out leaves one "
                "independent published number to check the joint fit against afterwards."
            ),
            "by_family": {
                name: steady_state(name, fits[name]["theta"], 7.0) for name in SELECTION_ORDER
            },
            "measured": KAZAMA_WILSON_7HZ_STEADY_STATE,
        },
        "release_probability_tension": {
            "measured": KAZAMA_WILSON_RELEASE_PROBABILITY,
            "by_family": {
                name: fits[name]["effective_first_pulse_utilisation"]
                for name in SELECTION_ORDER
            },
        },
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "worktree_verification": worktree.get("verification"),
        "evidence_grade": not worktree["dirty"],
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {**payload, "output": str(output_path.resolve()), "sha256": digest,
            "immutable_snapshot": str(snapshot)}


def _screen(
    family_id: str,
    fit: dict[str, Any],
    paired: list[Observation],
    train: TrainObservation,
    described: list[dict[str, Any]],
) -> dict[str, Any]:
    """E1 on both observables; a family at a bound is reported and not excluded for it."""
    theta = fit["theta"]
    paired_inside = []
    for row in described:
        predicted = paired_pulse(family_id, theta, row["interval_ms"])
        paired_inside.append(bool(row["ci95_low"] <= predicted <= row["ci95_high"]))
    interval = 1000.0 / train.hertz
    values = amplitudes(family_id, theta, [i * interval for i in range(train.pulses)])
    curve = values / values[0]
    inside, scored = 0, 0
    for index in range(1, train.pulses):
        observed, error = train.normalised[index], train.standard_error[index]
        if not np.isfinite(observed) or not np.isfinite(error) or error <= 0.0:
            continue
        scored += 1
        if abs(curve[index] - observed) <= 1.96 * error:
            inside += 1
    fraction = inside / scored if scored else 0.0
    return {
        "fit": fit,
        "e1_paired_pulse_inside": sum(paired_inside),
        "e1_paired_pulse_required": REQUIRED_PAIRED_INSIDE,
        "e1_train_fraction_inside": fraction,
        "e1_train_required": REQUIRED_TRAIN_FRACTION_INSIDE,
        "eligible": bool(
            sum(paired_inside) >= REQUIRED_PAIRED_INSIDE
            and fraction >= REQUIRED_TRAIN_FRACTION_INSIDE
        ),
        "predicted_paired_pulse": [
            paired_pulse(family_id, theta, row.interval_ms) for row in paired
        ],
        "predicted_train": [float(v) for v in curve],
        "steady_state_1hz": float(np.mean(curve[-5:])),
    }


def _select(eligible: list[str], screened: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not eligible:
        return {"primary": None, "why": "No family satisfied both observables."}
    ordered = sorted(eligible, key=lambda name: screened[name]["fit"]["weighted_sse"])
    return {
        "primary": ordered[0],
        "eligible_by_residual": ordered,
        "why": (
            f"{ordered[0]} carries the lowest joint weighted residual of the families that "
            "are consistent with both observables."
        ),
    }
