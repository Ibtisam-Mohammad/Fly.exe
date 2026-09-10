# SPDX-License-Identifier: GPL-2.0-or-later
"""Score the frozen ORN-to-PN candidates against the sealed wild-type train arrays.

The last unspent wild-type holdout for this synapse, opened once. Four arrays: the
control trains at 1, 10, 20 and 60 Hz. Not the RNAi trains, not the sixteen latency and
jitter arrays, nothing from any other file.

Two guards run before a byte of payload is decoded. The file is re-checked against the
checksum in the sealed reservation manifest, and every array is compared against every
array already spent — Fig3D's five, Fig3H's five and Fig3B's 1 Hz control — by the digest
of its stored bytes. That second guard exists because a preregistered holdout was opened
and scored on 2026-09-10 before anyone noticed it was bit-identical to the training set.

Nothing here fits anything. The trajectories come out of the committed contract pulse by
pulse, the run re-derives them from the frozen parameters, and it refuses to proceed if
the two disagree. The null is the refuted ND-06 v0.1 rule rather than a horizontal line,
because the previous holdout's constant null produced a margin that flattered the result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.depression_score import ATTRIBUTION
from flysim.errors import ConfigurationError
from flysim.reservations import duplicate_arrays, read_mat_variable
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot
from flysim.stp_families import amplitudes, family

# The contract's numbers, mirrored so a test can assert the two agree.
R1_MARGIN = 0.5
R2_MARGIN = 0.5
REDERIVE_TOLERANCE = 1e-6

TRAIN_SOURCE = "rozenfeld2023-repo/Figure 3/Fig3E_and_F.mat"


def _verify(*, manifest_path: Path, relative_path: str, staging_root: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    entries = [
        entry
        for dataset in manifest["datasets"]
        for entry in dataset["files"]
        if entry["path"] == relative_path
    ]
    if len(entries) != 1:
        raise ConfigurationError(f"{relative_path} is not reserved exactly once by the manifest")
    path = staging_root / relative_path
    if not path.is_file():
        raise ConfigurationError(f"Reserved file is missing: {path}")
    observed = sha256_file(path)
    if observed != entries[0]["sha256"]:
        raise ConfigurationError(
            f"{relative_path} has changed since it was reserved: manifest recorded "
            f"{entries[0]['sha256'][:16]}..., file is {observed[:16]}..."
        )
    return {
        "path": relative_path,
        "sha256": observed,
        "matches_sealed_manifest": True,
        "manifest_sha256": sha256_file(manifest_path),
    }


def _refuse_duplicates(
    *, staging_root: Path, names: list[str], spent: list[dict[str, Any]]
) -> dict[str, Any]:
    """No train array may be a re-shipped copy of anything already spent."""
    checked: list[dict[str, Any]] = []
    for source in spent:
        found = duplicate_arrays(
            candidate=staging_root / TRAIN_SOURCE,
            spent=staging_root / str(source["file"]),
            names=names + list(source.get("variables", [])),
        )
        checked.append({"against": source["file"], "duplicate_arrays": list(found)})
        if found:
            raise ConfigurationError(
                f"{TRAIN_SOURCE} stores the same arrays as the spent {source['file']}: "
                f"{list(found)}. Scoring it would be scoring spent data."
            )
    return {
        "checked_against": checked,
        "no_duplicate_found": True,
        "what_a_clean_result_does_not_prove": (
            "Independence of the animals. Equal stored bytes prove equal data; unequal "
            "bytes prove nothing about which cells were recorded. The contract's "
            "subject-independence audit classifies this holdout as UNKNOWN-OVERLAP on the "
            "published animal counts and the methods' statement that several protocols "
            "were run per cell."
        ),
    }


def _normalise(values: np.ndarray) -> dict[str, Any]:
    """Both registered normalisations of one train array, and what was dropped.

    The arrays are absolute evoked currents and presumably negative, so magnitudes are
    taken first. The primary normalisation divides the cohort-mean trajectory by its own
    first element; the secondary averages each animal's trajectory divided by its own
    first pulse, which divides by a single noisy measurement and is reported rather than
    scored.
    """
    magnitudes = np.abs(np.asarray(values, dtype=np.float64))
    animals, pulses = magnitudes.shape
    all_nan_rows = int(np.sum(np.all(~np.isfinite(magnitudes), axis=1)))
    finite = np.isfinite(magnitudes)
    counts = finite.sum(axis=0)
    if counts[0] < 2:
        raise ConfigurationError("The first pulse needs at least two finite values")
    with np.errstate(invalid="ignore"):
        means = np.array(
            [
                float(np.mean(magnitudes[finite[:, index], index]))
                if counts[index] >= 1
                else np.nan
                for index in range(pulses)
            ]
        )
        deviations = np.array(
            [
                float(np.std(magnitudes[finite[:, index], index], ddof=1))
                if counts[index] >= 2
                else np.nan
                for index in range(pulses)
            ]
        )
    errors = deviations / np.sqrt(np.maximum(counts, 1))
    primary = means / means[0]
    primary_error = errors / means[0]

    per_animal: list[np.ndarray] = []
    excluded_first_pulse = 0
    for row in range(animals):
        first = magnitudes[row, 0]
        if not np.isfinite(first) or first == 0.0:
            excluded_first_pulse += 1
            continue
        per_animal.append(magnitudes[row] / first)
    stacked = np.vstack(per_animal) if per_animal else np.zeros((0, pulses))
    with np.errstate(invalid="ignore"):
        secondary = np.nanmean(stacked, axis=0) if stacked.size else np.full(pulses, np.nan)
    return {
        "animals_supplied": animals,
        "pulses": pulses,
        "all_nan_rows": all_nan_rows,
        "finite_animals_per_pulse": [int(value) for value in counts],
        "animals_excluded_from_the_secondary_normalisation": excluded_first_pulse,
        "cohort_mean_first_pulse_magnitude": float(means[0]),
        "primary_normalised_trajectory": [float(value) for value in primary],
        "primary_standard_error": [float(value) for value in primary_error],
        "secondary_normalised_trajectory": [float(value) for value in secondary],
        "largest_difference_between_the_two_normalisations": float(
            np.nanmax(np.abs(primary - secondary))
        ),
    }


def _weighted_error(
    predicted: list[float], observed: list[float], errors: list[float]
) -> tuple[float, int]:
    """Weighted squared error from pulse two onward.

    The first pulse is excluded because the registered normalisation makes it exactly one
    for the data and for every model alike, so its standard error is zero and it carries
    no information. That is a forced consequence of the normalisation rule the contract
    fixed, not a choice made here, and it cannot favour any model over another.
    """
    total = 0.0
    scored = 0
    for index in range(1, len(observed)):
        value, error = observed[index], errors[index]
        if not np.isfinite(value) or not np.isfinite(error) or error <= 0.0:
            continue
        total += ((predicted[index] - value) / error) ** 2
        scored += 1
    return total, scored


def _rederive(model: dict[str, Any]) -> dict[str, list[float]]:
    """Recompute each frozen trajectory and refuse if the contract's copy has drifted."""
    family_id = str(model["family_id"])
    names = family(family_id).parameter_names
    missing = [name for name in names if name not in model["parameters"]]
    if missing:
        raise ConfigurationError(f"{family_id} is frozen without {missing}")
    theta = tuple(float(model["parameters"][name]) for name in names)
    out: dict[str, list[float]] = {}
    for label, row in model["by_frequency"].items():
        interval = 1000.0 / float(row["hertz"])
        values = amplitudes(family_id, theta, [i * interval for i in range(int(row["pulses"]))])
        curve = [float(value / values[0]) for value in values]
        for index, (recorded, recomputed) in enumerate(
            zip(row["trajectory"], curve, strict=True)
        ):
            if abs(float(recorded) - recomputed) > REDERIVE_TOLERANCE:
                raise ConfigurationError(
                    f"The frozen {family_id} trajectory at {label} pulse {index + 1} no "
                    f"longer reproduces: contract {recorded}, code {recomputed:.9f}"
                )
        out[label] = curve
    return out


def run_stp_train_discrimination(
    *,
    contract_path: Path,
    fit_artifact_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Open the four sealed wild-type train arrays once and score the frozen candidates."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The frozen plasticity train discrimination")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported train-discrimination contract schema")
    if contract.get("values_opened"):
        raise ConfigurationError(
            "This contract already records its values as opened; a second scoring pass "
            "would be a second look at the same holdout"
        )
    frozen = contract["frozen_predictions"]
    expected = str(frozen["fit_artifact_sha256"])
    observed_fit = sha256_file(fit_artifact_path)
    if observed_fit != expected:
        raise ConfigurationError(
            "The fit artifact is not the one this contract froze from: contract records "
            f"{expected[:16]}..., file is {observed_fit[:16]}..."
        )
    models = frozen["models"]
    curves = {label: _rederive(model) for label, model in models.items()}

    variables = list(contract["the_data"]["variables"])
    spent = [
        {
            "file": "rozenfeld2023-repo/Figure 3/Fig3D.mat",
            "variables": [f"new_all_flies_PP_{i:g}ms_control" for i in (10, 30, 100, 300, 1000)],
        },
        {
            "file": "rozenfeld2023-repo/Figure 3/Fig3H.mat",
            "variables": [f"new_all_flies_PP_{i:g}ms_control" for i in (10, 30, 100, 300, 1000)],
        },
        {"file": "rozenfeld2023-repo/Figure 3/Fig3B.mat", "variables": ["all_flies_1Hz_control"]},
    ]
    duplication = _refuse_duplicates(
        staging_root=staging_root, names=variables, spent=spent
    )
    unsealing = _verify(
        manifest_path=manifest_path, relative_path=TRAIN_SOURCE, staging_root=staging_root
    )

    path = staging_root / TRAIN_SOURCE
    cohorts: dict[str, dict[str, Any]] = {}
    for label, row in models["candidate_A_two_timescale_facilitation_free"][
        "by_frequency"
    ].items():
        variable = f"all_flies_{label}_control"
        if variable not in variables:
            raise ConfigurationError(f"The contract does not name {variable}")
        opened = read_mat_variable(path, variable)
        summary = _normalise(opened)
        if summary["pulses"] != int(row["pulses"]):
            raise ConfigurationError(
                f"{variable} has {summary['pulses']} pulses, the contract froze "
                f"{row['pulses']}"
            )
        cohorts[label] = {"variable": variable, **summary}

    scores: dict[str, Any] = {}
    for model_label, by_frequency in curves.items():
        rows: dict[str, Any] = {}
        total, scored_points = 0.0, 0
        for label, curve in by_frequency.items():
            cohort = cohorts[label]
            error, count = _weighted_error(
                curve,
                cohort["primary_normalised_trajectory"],
                cohort["primary_standard_error"],
            )
            total += error
            scored_points += count
            peak = int(np.nanargmax(cohort["primary_normalised_trajectory"])) + 1
            rows[label] = {
                "weighted_squared_error": error,
                "pulses_scored": count,
                "predicted_second_over_first": curve[1],
                "observed_second_over_first": cohort["primary_normalised_trajectory"][1],
                "predicted_peak_pulse": int(np.argmax(curve)) + 1,
                "observed_peak_pulse": peak,
                "predicted_steady_state_last_five": float(np.mean(curve[-5:])),
                "observed_steady_state_last_five": float(
                    np.nanmean(cohort["primary_normalised_trajectory"][-5:])
                ),
            }
        scores[model_label] = {
            "by_frequency": rows,
            "summed_weighted_squared_error": total,
            "pulses_scored": scored_points,
        }

    flat = {}
    flat_total, flat_points = 0.0, 0
    for label, cohort in cohorts.items():
        error, count = _weighted_error(
            [1.0] * cohort["pulses"],
            cohort["primary_normalised_trajectory"],
            cohort["primary_standard_error"],
        )
        flat[label] = {"weighted_squared_error": error, "pulses_scored": count}
        flat_total += error
        flat_points += count
    scores["null_2_flat"] = {
        "by_frequency": flat,
        "summed_weighted_squared_error": flat_total,
        "pulses_scored": flat_points,
    }

    verdicts = _verdicts(scores=scores, cohorts=cohorts, curves=curves)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-stp-train-discrimination-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "M/F",
        "assumption_ids": list(contract["assumption_ids"]),
        "attribution": ATTRIBUTION,
        "subject_independence_classification": str(
            contract["subject_independence_audit"]["classification"]
        ),
        "what_that_classification_means_for_this_result": str(
            contract["subject_independence_audit"]["consequences_declared_now_for_each_class"][
                "if_unknown_overlap_which_is_the_recorded_classification"
            ]
        ),
        "unsealing": {
            **unsealing,
            "variables_opened": variables,
            "not_a_duplicate_of_a_spent_cohort": duplication,
            "everything_else_stays_sealed": (
                "The four RNAi train arrays and all sixteen latency and jitter arrays in "
                "this file, every other Rozenfeld file, and the whole Takagi corpus."
            ),
        },
        "fit_artifact": {"path": str(fit_artifact_path), "sha256": observed_fit},
        "frozen_models_rederived": True,
        "cohorts": cohorts,
        "scores": scores,
        "hypotheses": verdicts,
        "verdict": verdicts["verdict"],
        "verdict_note": verdicts["verdict_note"],
        "no_refitting": str(contract["acceptance"]["no_refitting"]),
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


def _verdicts(
    *,
    scores: dict[str, Any],
    cohorts: dict[str, dict[str, Any]],
    curves: dict[str, dict[str, list[float]]],
) -> dict[str, Any]:
    """R1 to R4 and the registered degenerate-outcome checks."""
    first = "candidate_A_two_timescale_facilitation_free"
    second = "candidate_B_facilitation_depression"
    null = "null_1_nd06_v0_1_depression_only"
    left = scores[first]["summed_weighted_squared_error"]
    right = scores[second]["summed_weighted_squared_error"]

    separable = False
    gaps: dict[str, float] = {}
    for label, cohort in cohorts.items():
        errors = np.array(cohort["primary_standard_error"][1:])
        difference = np.abs(
            np.array(curves[first][label][1:]) - np.array(curves[second][label][1:])
        )
        with np.errstate(invalid="ignore"):
            gaps[label] = float(np.nanmax(difference))
            if np.any(difference > errors):
                separable = True

    better, worse = (first, second) if left <= right else (second, first)
    ratio = (
        scores[better]["summed_weighted_squared_error"]
        / scores[worse]["summed_weighted_squared_error"]
        if scores[worse]["summed_weighted_squared_error"] > 0.0
        else float("inf")
    )
    if not separable:
        r1, winner = "NO VERDICT", None
        r1_note = (
            "The two frozen trajectories never differ by more than the cohort standard "
            "error at any scored pulse, so this observable cannot separate them."
        )
    elif ratio <= R1_MARGIN:
        r1, winner = "SEPARATED", better
        r1_note = (
            f"{better} carries a summed weighted error of "
            f"{scores[better]['summed_weighted_squared_error']:.1f} against "
            f"{scores[worse]['summed_weighted_squared_error']:.1f}, a ratio of "
            f"{ratio:.4f} against the registered {R1_MARGIN}."
        )
    else:
        r1, winner = "NOT SEPARATED", None
        r1_note = (
            f"The better of the two carries a ratio of {ratio:.4f} against the registered "
            f"{R1_MARGIN}, so neither may be preferred."
        )

    null_total = scores[null]["summed_weighted_squared_error"]
    flat_total = scores["null_2_flat"]["summed_weighted_squared_error"]
    if winner is None:
        r2, r2_note = "NOT SCORED", "R1 named no winner, so there is nothing to compare."
        r2_ratio = None
    else:
        r2_ratio = (
            scores[winner]["summed_weighted_squared_error"] / null_total
            if null_total > 0.0
            else float("inf")
        )
        r2 = "PASSED" if r2_ratio <= R2_MARGIN else "FAILED"
        r2_note = (
            f"{winner} carries {scores[winner]['summed_weighted_squared_error']:.1f} "
            f"against ND-06 v0.1's {null_total:.1f}, a ratio of {r2_ratio:.4f} against the "
            f"registered {R2_MARGIN}."
        )

    steady = {
        label: {
            "observed": float(np.nanmean(cohort["primary_normalised_trajectory"][-5:])),
            "predicted_by_each": {
                model: float(np.mean(curves[model][label][-5:])) for model in curves
            },
        }
        for label, cohort in cohorts.items()
    }
    verdict = "PASSED" if (r1 == "SEPARATED" and r2 == "PASSED") else "FAILED"
    if r1 == "NO VERDICT":
        verdict = "NO VERDICT"
    return {
        "R1": {"verdict": r1, "winner": winner, "note": r1_note, "ratio": ratio,
               "largest_gap_between_the_frozen_curves": gaps},
        "R2": {"verdict": r2, "note": r2_note, "ratio": r2_ratio},
        "R3": {"verdict": "REPORTED", "steady_state_by_frequency": steady},
        "R4": {
            "verdict": "REPORTED",
            "by_frequency": {
                label: {
                    model: {
                        "predicted_second_over_first": scores[model]["by_frequency"][label][
                            "predicted_second_over_first"
                        ],
                        "predicted_peak_pulse": scores[model]["by_frequency"][label][
                            "predicted_peak_pulse"
                        ],
                    }
                    for model in curves
                }
                | {
                    "observed_second_over_first": cohorts[label][
                        "primary_normalised_trajectory"
                    ][1],
                    "observed_peak_pulse": int(
                        np.nanargmax(cohorts[label]["primary_normalised_trajectory"])
                    )
                    + 1,
                }
                for label in cohorts
            },
        },
        "degenerate_outcome_checks": {
            "D_R1_separable": separable,
            "D_R2_is_the_null_strong": {
                "nd06_v0_1_summed_error": null_total,
                "flat_null_summed_error": flat_total,
                "the_null_is_strong": null_total < flat_total,
                "consequence": (
                    "ND-06 v0.1 beats a horizontal line, so R2 is a real bar."
                    if null_total < flat_total
                    else "ND-06 v0.1 is worse than a horizontal line, so passing R2 is "
                    "passing against a weak null and the verdict must be read as such."
                ),
            },
        },
        "verdict": verdict,
        "verdict_note": f"R1 {r1} and R2 {r2}.",
    }
