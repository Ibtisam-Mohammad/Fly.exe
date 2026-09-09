# SPDX-License-Identifier: GPL-2.0-or-later
"""Fit the candidate ORN-to-PN plasticity families on spent data and screen them.

This run reads the Fig3D wild-type paired-pulse arrays. Those arrays were opened and
scored on 2026-09-09 under ``stage2-depression-external-test-v1``, which means they are
**spent**: they can never again function as a test of anything, and the only remaining
honest use for them is as training data. Every number this run produces is therefore a
fit, not a validation, and the artifact says so in as many places as it takes.

What the run decides is which families get frozen and sent to holdout cohorts that are
still sealed. Three screens gate that, all fixed in the committed contract:

* **E1, consistent with its own training data.** The fitted curve must lie inside the
  fit set's 95 percent interval at every one of the five intervals.
* **E2, sharp enough to be falsified.** The bootstrap 95 percent band on the frozen
  prediction must be no wider at any interval than the fit set's own 95 percent interval
  there. A curve blurrier than the data cannot be refuted by more data, and freezing one
  would be a way of never being wrong. This screen carries no threshold of its own: it
  scales itself to the data.
* **E3, no smuggled constants.** Any constant a family pins rather than fits must be
  refitted across a declared sweep, and the five scored predictions must move by no more
  than 0.01 in ratio units. A pinning that changes the predictions is an assumption doing
  work, and it has to be fitted or abandoned.

Parameter-level identifiability is measured for every family and gates nothing. It
answers a different question -- which fitted numbers may be reported as measurements of
anything -- and the artifact keeps the two apart.

A flat constant is fitted alongside as the degeneracy guard. If a frozen model cannot
beat a horizontal line on the holdout, the holdout did not test anything.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from flysim import stp_families
from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.depression_score import ALL_INTERVALS_MS, summarise, variable_for
from flysim.errors import ConfigurationError
from flysim.reservations import read_mat_variable
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot
from flysim.stp_families import (
    KAZAMA_WILSON_RELEASE_PROBABILITY,
    PARALLEL_SHARE,
    PINNED_FAST_TAU_MS,
    PINNED_RECOVERY_TAU_MS,
    SELECTION_ORDER,
    Observation,
    bootstrap_predictions,
    discrimination,
    effective_first_pulse_utilisation,
    family,
    fit_family,
    leave_one_out,
    paired_pulse,
    predict,
    synthetic_recovery,
)

FIT_SOURCE = "rozenfeld2023-repo/Figure 3/Fig3D.mat"
FIT_COHORT = "wild-type controls, 2 to 4 days post eclosion"

# E1 and E3, as fixed in stage2-stp-family-selection-v1.json. E2 has no constant of its
# own: the band is compared against the fit set's own interval. A test asserts agreement.
REQUIRED_INTERVALS_INSIDE = 5
PINNED_SHIFT_LIMIT = 0.01

# Reported, not gating: the thresholds under which a fitted parameter may be described as
# a measurement rather than as a nuisance value the fit carries along.
IDENTIFIABILITY_BIAS_LIMIT = 0.25
IDENTIFIABILITY_WIDTH_LIMIT = 2.0

# The declared sweeps for E3. Each entry is (module attribute, values to pin it at), and
# each sweep must contain the value the module actually pins.
PINNED_CONSTANTS: dict[str, tuple[tuple[str, tuple[float, ...]], ...]] = {
    "parallel-release-components": (("PARALLEL_SHARE", (0.25, 0.5, 0.75)),),
    "two-timescale-facilitation": (
        ("PINNED_FAST_TAU_MS", (1.0, 2.0, 5.0, 10.0)),
        ("PINNED_RECOVERY_TAU_MS", (5000.0, 10000.0, 20000.0, 50000.0)),
    ),
    "two-timescale-facilitation-free": (
        ("PINNED_RECOVERY_TAU_MS", (5000.0, 10000.0, 20000.0, 50000.0)),
    ),
}
_CONSTANT_LABELS = {
    "PARALLEL_SHARE": "resting share of the facilitating component",
    "PINNED_FAST_TAU_MS": "fast facilitation time constant",
    "PINNED_RECOVERY_TAU_MS": "resource recovery time constant",
}


def _observations(
    path: Path,
) -> tuple[list[Observation], dict[float, np.ndarray], list[dict[str, Any]]]:
    """Cohort summaries and the per-animal values, for the fit and for the bootstrap."""
    observations: list[Observation] = []
    samples: dict[float, np.ndarray] = {}
    described: list[dict[str, Any]] = []
    for interval in ALL_INTERVALS_MS:
        values = read_mat_variable(path, variable_for(interval))
        flat = np.asarray(values, dtype=np.float64).reshape(-1)
        summary = summarise(values)
        samples[interval] = flat[np.isfinite(flat)]
        observations.append(
            Observation(
                interval_ms=interval,
                mean=summary["mean"],
                standard_error=summary["standard_error"],
                animals=summary["animals_scored"],
            )
        )
        described.append({"interval_ms": interval, "variable": variable_for(interval), **summary})
    return observations, samples, described


def _inside_count(
    predicted: tuple[float, ...] | np.ndarray, described: list[dict[str, Any]]
) -> tuple[int, list[bool]]:
    flags = [
        bool(row["ci95_low"] <= float(value) <= row["ci95_high"])
        for value, row in zip(predicted, described, strict=True)
    ]
    return sum(flags), flags


def _sweep_pinned_constant(
    family_id: str,
    observations: list[Observation],
    *,
    attribute: str,
    values: tuple[float, ...],
    restarts: int,
) -> dict[str, Any]:
    """Refit at each pinned value and report how far the scored predictions move.

    The module constant is swapped for the duration and restored in a finally block.
    This is the only way to ask the question honestly: a pinning that is really harmless
    must give the same predictions when it is pinned somewhere else.
    """
    original = float(getattr(stp_families, attribute))
    if not any(math.isclose(value, original) for value in values):
        raise ConfigurationError(f"The {attribute} sweep must include the pinned {original}")
    rows: list[dict[str, Any]] = []
    baseline: np.ndarray | None = None
    try:
        for value in values:
            setattr(stp_families, attribute, value)
            fitted = fit_family(family_id, observations, restarts=restarts)
            curve = predict(family_id, fitted.theta, ALL_INTERVALS_MS)
            if math.isclose(value, original):
                baseline = curve
            rows.append(
                {
                    "pinned_at": value,
                    "weighted_sse": fitted.weighted_sse,
                    "parameters": dict(
                        zip(family(family_id).parameter_names, fitted.theta, strict=True)
                    ),
                    "predicted": [float(entry) for entry in curve],
                }
            )
    finally:
        setattr(stp_families, attribute, original)
    assert baseline is not None
    worst = 0.0
    for row in rows:
        shift = float(np.max(np.abs(np.array(row["predicted"]) - baseline)))
        row["largest_prediction_shift"] = shift
        worst = max(worst, shift)
    return {
        "constant": attribute,
        "what_it_is": _CONSTANT_LABELS[attribute],
        "pinned_value": original,
        "values_swept": list(values),
        "by_value": rows,
        "largest_prediction_shift_over_the_sweep": worst,
        "pinning_is_harmless": worst <= PINNED_SHIFT_LIMIT,
        "limit": PINNED_SHIFT_LIMIT,
    }


def _band_is_sharp_enough(
    band: dict[str, Any], described: list[dict[str, Any]]
) -> tuple[bool, list[dict[str, Any]]]:
    """E2: the frozen prediction must be no blurrier than the data it was fitted to."""
    rows: list[dict[str, Any]] = []
    for row, observed in zip(band["by_interval"], described, strict=True):
        half_width = 0.5 * (row["percentile_97_5"] - row["percentile_2_5"])
        rows.append(
            {
                "interval_ms": row["interval_ms"],
                "prediction_band_half_width": half_width,
                "fit_set_ci95_half_width": observed["ci95_half_width"],
                "sharp_enough": bool(half_width <= observed["ci95_half_width"]),
            }
        )
    return all(entry["sharp_enough"] for entry in rows), rows


def _identifiability(
    family_id: str,
    theta: tuple[float, ...],
    observations: list[Observation],
    *,
    replicates: int,
) -> list[dict[str, Any]]:
    """Which fitted numbers may be reported as measurements. Gates nothing."""
    spec = family(family_id)
    recovery = synthetic_recovery(
        family_id, theta, observations, replicates=replicates, restarts=10
    )
    rows: list[dict[str, Any]] = []
    for index, parameter in enumerate(spec.parameters):
        row = recovery["parameters"][parameter.name]
        bias, width = row["median_relative_bias"], row["interval_width_over_true"]
        identified = (
            bias is not None
            and width is not None
            and abs(bias) <= IDENTIFIABILITY_BIAS_LIMIT
            and width <= IDENTIFIABILITY_WIDTH_LIMIT
        )
        rows.append(
            {
                "name": parameter.name,
                "fitted": theta[index],
                "recovery": row,
                "may_be_reported_as_a_measurement": bool(identified),
                "otherwise": (
                    "carried as a fitted nuisance value: this observable does not "
                    "determine it, and the frozen registry must not report it as measured"
                ),
            }
        )
    return rows


def _screen(
    family_id: str,
    observations: list[Observation],
    samples: dict[float, np.ndarray],
    described: list[dict[str, Any]],
    *,
    replicates: int,
    restarts: int,
    bootstrap_replicates: int,
) -> dict[str, Any]:
    """Fit one family, apply E1 to E3, and report every intermediate number."""
    spec = family(family_id)
    fitted = fit_family(family_id, observations, restarts=restarts)
    inside, flags = _inside_count(fitted.predicted, described)
    band = bootstrap_predictions(
        family_id, samples, ALL_INTERVALS_MS, replicates=bootstrap_replicates, restarts=10
    )
    sharp, sharpness = _band_is_sharp_enough(band, described)
    pinned = [
        _sweep_pinned_constant(
            family_id,
            observations,
            attribute=attribute,
            values=values,
            restarts=max(8, restarts // 4),
        )
        for attribute, values in PINNED_CONSTANTS.get(family_id, ())
    ]
    pinned_ok = all(row["pinning_is_harmless"] for row in pinned)
    utilisation = effective_first_pulse_utilisation(family_id, fitted.theta)
    return {
        "family": spec.as_dict(),
        "fit": fitted.as_dict(),
        "residuals_in_standard_errors": [
            (float(value) - row["mean"]) / row["standard_error"]
            for value, row in zip(fitted.predicted, described, strict=True)
        ],
        "e1_consistent_with_its_training_data": {
            "intervals_inside_the_fit_set_ci95": inside,
            "inside_by_interval": flags,
            "required": REQUIRED_INTERVALS_INSIDE,
            "passes": inside >= REQUIRED_INTERVALS_INSIDE,
        },
        "e2_sharp_enough_to_be_falsified": {
            "by_interval": sharpness,
            "passes": sharp,
            "rule": (
                "the bootstrap 95 percent band on the prediction must be no wider than "
                "the fit set's own 95 percent interval at the same interval"
            ),
        },
        "e3_pinned_constants_are_harmless": {
            "constants_pinned": [
                attribute for attribute, _ in PINNED_CONSTANTS.get(family_id, ())
            ],
            "sweeps": pinned,
            "passes": pinned_ok,
        },
        "eligible_to_be_frozen": bool(
            inside >= REQUIRED_INTERVALS_INSIDE and sharp and pinned_ok
        ),
        "prediction_band": band,
        "parameter_identifiability_reported_not_gating": _identifiability(
            family_id, fitted.theta, observations, replicates=replicates
        ),
        "leave_one_out": leave_one_out(family_id, observations, restarts=12),
        "effective_first_pulse_utilisation": utilisation,
        "against_the_measured_release_probability": {
            "measured": KAZAMA_WILSON_RELEASE_PROBABILITY,
            "source": (
                "Kazama and Wilson 2008, multiple-probability fluctuation analysis: 0.79 "
                "plus or minus 0.02, uniform across glomeruli"
            ),
            "ratio_measured_over_fitted": KAZAMA_WILSON_RELEASE_PROBABILITY / utilisation,
            "gates_nothing": (
                "Mapping a fitted utilisation onto a measured per-site release "
                "probability needs one vesicle per site and no within-pair recovery, "
                "which the ND-06 registry already records as the reason the "
                "variance-derived value was not adopted. It is reported because a family "
                "that reproduces this curve only by putting the release probability far "
                "below the measured one has told us something about itself."
            ),
        },
        "protocol_correction": [
            {
                "interval_ms": interval,
                "from_rest": paired_pulse(family_id, fitted.theta, interval, from_rest=True),
                "twenty_pairs_at_0_2_hz": paired_pulse(family_id, fitted.theta, interval),
            }
            for interval in ALL_INTERVALS_MS
        ],
    }


def flat_null(observations: list[Observation]) -> dict[str, Any]:
    """The degeneracy guard: one horizontal line, fitted the same way as everything else."""
    weights = np.array([1.0 / row.standard_error**2 for row in observations])
    means = np.array([row.mean for row in observations])
    level = float(np.sum(weights * means) / np.sum(weights))
    return {
        "family_id": "flat-null",
        "level": level,
        "weighted_sse_on_the_fit_set": float(np.sum(weights * (level - means) ** 2)),
        "parameter_count": 1,
        "why_it_is_here": (
            "A model that cannot beat a horizontal line on the holdout has not been "
            "tested by the holdout. This level is frozen with everything else so the "
            "comparison on unseen cohorts is between two predictions made in advance."
        ),
    }


def _select(eligible: list[str], screened: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Apply the committed tie-break and say what it chose and why."""
    if not eligible:
        return {
            "primary": None,
            "secondary": None,
            "why": (
                "No family passed all three screens, so nothing is frozen and the sealed "
                "cohorts stay sealed. That is a result, not a failure of the run."
            ),
        }
    by_residual = sorted(eligible, key=lambda name: (screened[name]["fit"]["weighted_sse"], name))
    by_size = sorted(
        eligible,
        key=lambda name: (
            screened[name]["family"]["parameter_count"],
            screened[name]["fit"]["weighted_sse"],
            name,
        ),
    )
    primary = by_residual[0]
    secondary = next((name for name in by_size if name != primary), None)
    return {
        "primary": primary,
        "secondary": secondary,
        "primary_rule": "lowest weighted residual among eligible families",
        "secondary_rule": "fewest parameters among the rest, ties by weighted residual",
        "eligible_by_residual": by_residual,
        "eligible_by_parameter_count": by_size,
        "why": (
            f"{primary} carries the lowest weighted residual of the eligible families and "
            "is frozen as the primary. "
            + (
                f"{secondary} is frozen alongside it as the secondary so an unseen cohort "
                "can adjudicate between them, which the fit set cannot."
                if secondary
                else "No second eligible family exists, so the holdout scores one model "
                "against the flat null only."
            )
        ),
    }


def _verify(*, manifest_path: Path, staging_root: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    entries = [
        entry
        for dataset in manifest["datasets"]
        for entry in dataset["files"]
        if entry["path"] == FIT_SOURCE
    ]
    if len(entries) != 1:
        raise ConfigurationError(f"{FIT_SOURCE} is not pinned exactly once by the manifest")
    observed = sha256_file(staging_root / FIT_SOURCE)
    if observed != entries[0]["sha256"]:
        raise ConfigurationError(
            f"{FIT_SOURCE} has changed since it was reserved: manifest recorded "
            f"{entries[0]['sha256'][:16]}..., file is {observed[:16]}..."
        )
    return {
        "path": FIT_SOURCE,
        "sha256": observed,
        "matches_sealed_manifest": True,
        "manifest_sha256": sha256_file(manifest_path),
        "already_spent_on": "2026-09-09, by stage2-depression-external-test-v1",
    }


def run_stp_family_selection(
    *,
    contract_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    replicates: int = 100,
    restarts: int = 48,
    bootstrap_replicates: int = 200,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Fit every family on the spent fit set, screen them, and name what gets frozen."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The ORN-to-PN plasticity family selection")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported family-selection contract schema")
    declared = tuple(contract["families_considered"])
    if declared != SELECTION_ORDER:
        raise ConfigurationError(
            "The contract's family list and the module's selection order disagree: "
            f"{declared} against {SELECTION_ORDER}"
        )
    verification = _verify(manifest_path=manifest_path, staging_root=staging_root)
    observations, samples, described = _observations(staging_root / FIT_SOURCE)

    screened = {
        family_id: _screen(
            family_id,
            observations,
            samples,
            described,
            replicates=replicates,
            restarts=restarts,
            bootstrap_replicates=bootstrap_replicates,
        )
        for family_id in SELECTION_ORDER
    }
    eligible = [
        family_id for family_id in SELECTION_ORDER if screened[family_id]["eligible_to_be_frozen"]
    ]
    selection = _select(eligible, screened)

    separability: list[dict[str, Any]] = []
    if selection.get("primary") and selection.get("secondary"):
        first, second = str(selection["primary"]), str(selection["secondary"])
        for generating, competitor in ((first, second), (second, first)):
            separability.append(
                discrimination(
                    generating,
                    tuple(screened[generating]["fit"]["parameters"].values()),
                    competitor,
                    observations,
                    replicates=replicates,
                    restarts=10,
                )
            )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-stp-family-selection-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "F",
        "assumption_ids": list(contract["assumption_ids"]),
        "this_is_a_fit_and_not_a_validation": (
            "The Fig3D wild-type arrays were opened and scored on 2026-09-09. They are "
            "spent, so nothing here is a test and no tier is awarded by this run. The "
            "frozen models' only test is the sealed developmental cohorts, scored once."
        ),
        "fit_set": {
            "file": FIT_SOURCE,
            "cohort": FIT_COHORT,
            "verification": verification,
            "by_interval": described,
            "weights": "one over the squared cohort standard error",
            "unit_of_observation": "one paired-pulse ratio per animal",
        },
        "protocol": {
            "pair_repetition_hz": 0.2,
            "pairs_averaged": 20,
            "source": (
                "Methods: 'Paired-pulse recordings were made at 0.2 Hz with "
                "inter-stimulus intervals of (in ms): 10, 30, 100, 300, and 1000. For "
                "each interval 20 traces were averaged.'"
            ),
            "why_it_is_simulated_rather_than_assumed_away": (
                "The ratio the authors report is the mean second response over the mean "
                "first response across twenty pairs, and the earlier pairs leave the "
                "resource partly depleted. Every prediction here is computed that way; "
                "the from-rest value sits beside it in protocol_correction, and at "
                "1000 ms the two differ by more than that cohort's standard error."
            ),
        },
        "screens": {
            "e1": (
                "the fitted curve must lie inside the fit set's 95 percent interval at "
                f"{REQUIRED_INTERVALS_INSIDE} of {len(ALL_INTERVALS_MS)} intervals"
            ),
            "e2": (
                "the bootstrap 95 percent band on the frozen prediction must be no wider "
                "at any interval than the fit set's own 95 percent interval there. This "
                "screen carries no threshold of its own: it scales to the data."
            ),
            "e3": (
                "every constant a family pins rather than fits must be refitted across "
                f"its declared sweep and move the five predictions by at most "
                f"{PINNED_SHIFT_LIMIT}"
            ),
            "selection": (
                "among eligible families the lowest weighted residual is the primary and "
                "the fewest parameters is the secondary"
            ),
            "reported_not_gating": (
                "parameter-level identifiability, the chi-square goodness of fit, the "
                "leave-one-interval-out error, and the comparison against Kazama and "
                "Wilson's measured release probability"
            ),
            "pinned_constants": {
                "parallel-release-components/share": PARALLEL_SHARE,
                "two-timescale-facilitation/fast_tau_ms": PINNED_FAST_TAU_MS,
                "recovery_tau_ms": PINNED_RECOVERY_TAU_MS,
            },
        },
        "families": screened,
        "eligible": eligible,
        "selection": selection,
        "flat_null": flat_null(observations),
        "separability_of_the_two_frozen_families": separability,
        "nothing_sealed_was_opened": (
            "Only Fig3D's five wild-type arrays were read. Fig3H, Fig3J, Fig3E_and_F, "
            "Fig6D, the RNAi arrays and every other reserved file stay sealed, and so "
            "does the whole Takagi corpus."
        ),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "worktree_verification": worktree.get("verification"),
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


def frozen_predictions(family_id: str, theta: tuple[float, ...]) -> list[dict[str, Any]]:
    """The curve a frozen family predicts, for writing into the successor registry."""
    return [
        {
            "interval_ms": interval,
            "predicted": paired_pulse(family_id, theta, interval),
            "from_rest": paired_pulse(family_id, theta, interval, from_rest=True),
        }
        for interval in ALL_INTERVALS_MS
    ]
