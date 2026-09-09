# SPDX-License-Identifier: GPL-2.0-or-later
"""Score the frozen ORN-to-PN plasticity models against the sealed developmental cohorts.

This is the module that opens sealed data, so it opens as little as possible: the five
wild-type arrays of Fig3J (day 1) and the five of Fig3H (day 0), ten arrays in total.
Not the RNAi cohorts, not the trains, not the raw traces, not Fig6D, not the absolute
amplitudes, not the miniature EPSCs, not the Bruchpilot counts, and nothing in the
Takagi corpus. Every file is re-checked against the checksum in the sealed reservation
manifest before a byte of it is decoded.

Nothing here fits anything. The models come out of the committed holdout contract with
their parameters and their predicted curves both written down, and the run re-derives the
curves from the parameters and refuses to proceed if the two disagree -- which is how a
silent change in the simulator between the freeze and the score would be caught rather
than absorbed.

The verdict rule, the thresholds and all four degenerate-outcome checks are in the
contract and are read from it, not restated here.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.depression_score import (
    ALL_INTERVALS_MS,
    ATTRIBUTION,
    summarise,
    variable_for,
)
from flysim.errors import ConfigurationError
from flysim.reservations import read_mat_variable
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot
from flysim.stp_families import family, paired_pulse

# The contract's numbers, mirrored here so a test can assert the two agree.
A1_MAX_MISSES = 1
A1_HALF_WIDTH_LIMIT = 0.15
A1_MINIMUM_SCORABLE = 4
A2_RESIDUAL_RATIO_LIMIT = 0.5
A3_MINIMUM_AGREEMENTS = 3
SEPARABILITY_LIMIT = 0.02


def _verify(*, manifest_path: Path, relative_path: str, staging_root: Path) -> dict[str, Any]:
    """Refuse to open a file whose bytes are not the bytes that were reserved."""
    manifest = load_json(manifest_path)
    entries = [
        entry
        for dataset in manifest["datasets"]
        for entry in dataset["files"]
        if entry["path"] == relative_path
    ]
    if len(entries) != 1:
        raise ConfigurationError(
            f"{relative_path} is not reserved exactly once in {manifest_path.name}; "
            "an unsealing must name a file the manifest pinned"
        )
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
        "reserved_variables_in_this_file": len(entries[0]["reserved_names"]),
    }


def _open_cohort(
    *, spec: dict[str, Any], manifest_path: Path, staging_root: Path
) -> dict[str, Any]:
    """Open the five declared wild-type arrays of one cohort and summarise each."""
    relative_path = str(spec["file"])
    declared = set(spec["variables"])
    wanted = [variable_for(interval) for interval in ALL_INTERVALS_MS]
    if not set(wanted) <= declared:
        raise ConfigurationError(
            "This cohort would open a variable the contract does not name: "
            f"{sorted(set(wanted) - declared)}"
        )
    unsealing = _verify(
        manifest_path=manifest_path, relative_path=relative_path, staging_root=staging_root
    )
    path = staging_root / relative_path
    rows: list[dict[str, Any]] = []
    for interval in ALL_INTERVALS_MS:
        summary = summarise(read_mat_variable(path, variable_for(interval)))
        rows.append(
            {"interval_ms": interval, "variable": variable_for(interval), **summary}
        )
    return {
        "cohort": str(spec["cohort"]),
        "unsealing": {**unsealing, "variables_opened": wanted},
        "by_interval": rows,
    }


def _rederive(model: dict[str, Any]) -> list[float]:
    """Recompute the frozen curve from the frozen parameters and check it still matches.

    A frozen model is only frozen if the numbers and the code agree. If the simulator has
    moved since the freeze, this is where it is caught.
    """
    family_id = str(model["family_id"])
    spec = family(family_id)
    parameters = model["parameters"]
    missing = [name for name in spec.parameter_names if name not in parameters]
    if missing:
        raise ConfigurationError(f"{family_id} is frozen without {missing}")
    theta = tuple(float(parameters[name]) for name in spec.parameter_names)
    recomputed = [paired_pulse(family_id, theta, interval) for interval in ALL_INTERVALS_MS]
    recorded = [float(row["predicted"]) for row in model["predicted"]]
    for interval, left, right in zip(ALL_INTERVALS_MS, recorded, recomputed, strict=True):
        if abs(left - right) > 1e-9:
            raise ConfigurationError(
                f"The frozen {family_id} prediction at {interval:g} ms no longer "
                f"reproduces: contract says {left:.10f}, code gives {right:.10f}. The "
                "model is not frozen if the code has moved under it."
            )
    return recomputed


def _score_model(
    *, predicted: list[float], cohort: dict[str, Any], flat_level: float
) -> dict[str, Any]:
    """A1, A2 and A3 for one curve against one cohort, with the degenerate checks."""
    rows: list[dict[str, Any]] = []
    for value, observed in zip(predicted, cohort["by_interval"], strict=True):
        underpowered = observed["ci95_half_width"] > A1_HALF_WIDTH_LIMIT
        rows.append(
            {
                "interval_ms": observed["interval_ms"],
                "predicted": value,
                "observed_mean": observed["mean"],
                "observed_ci95": [observed["ci95_low"], observed["ci95_high"]],
                "observed_minus_predicted": observed["mean"] - value,
                "residual_in_standard_errors": (observed["mean"] - value)
                / observed["standard_error"],
                "inside": bool(observed["ci95_low"] <= value <= observed["ci95_high"]),
                "scorable": not underpowered,
                "no_verdict_because_underpowered": underpowered,
            }
        )
    scorable = [row for row in rows if row["scorable"]]
    misses = [row for row in scorable if not row["inside"]]
    if len(scorable) < A1_MINIMUM_SCORABLE:
        a1 = "NO VERDICT"
        a1_note = (
            f"Only {len(scorable)} of {len(rows)} intervals are scorable under the "
            f"registered half-width limit of {A1_HALF_WIDTH_LIMIT}, below the "
            f"registered minimum of {A1_MINIMUM_SCORABLE}."
        )
    else:
        a1 = "PASSED" if len(misses) <= A1_MAX_MISSES else "FAILED"
        a1_note = (
            f"{len(misses)} miss(es) among {len(scorable)} scorable intervals against a "
            f"registered tolerance of {A1_MAX_MISSES}"
            + (
                ": " + ", ".join(f"{row['interval_ms']:g} ms" for row in misses)
                if misses
                else ""
            )
            + "."
        )

    weights = np.array([1.0 / row["standard_error"] ** 2 for row in cohort["by_interval"]])
    means = np.array([row["mean"] for row in cohort["by_interval"]])
    model_residual = float(np.sum(weights * (np.array(predicted) - means) ** 2))
    null_residual = float(np.sum(weights * (flat_level - means) ** 2))
    ratio = model_residual / null_residual if null_residual > 0.0 else float("inf")
    a2 = "PASSED" if ratio <= A2_RESIDUAL_RATIO_LIMIT else "FAILED"

    predicted_steps = [later - earlier for earlier, later in pairwise(predicted)]
    observed_steps = [
        later["mean"] - earlier["mean"]
        for earlier, later in pairwise(cohort["by_interval"])
    ]
    overlaps = [
        earlier["ci95_low"] <= later["ci95_high"] and later["ci95_low"] <= earlier["ci95_high"]
        for earlier, later in pairwise(cohort["by_interval"])
    ]
    comparisons: list[dict[str, Any]] = []
    for index, (model_step, data_step, overlap) in enumerate(
        zip(predicted_steps, observed_steps, overlaps, strict=True)
    ):
        agrees = overlap or (model_step > 0.0) == (data_step > 0.0)
        comparisons.append(
            {
                "from_ms": ALL_INTERVALS_MS[index],
                "to_ms": ALL_INTERVALS_MS[index + 1],
                "predicted_change": model_step,
                "observed_change": data_step,
                "cohort_intervals_overlap": bool(overlap),
                "agrees": bool(agrees),
            }
        )
    agreements = sum(1 for row in comparisons if row["agrees"])
    a3 = "PASSED" if agreements >= A3_MINIMUM_AGREEMENTS else "FAILED"

    return {
        "by_interval": rows,
        "A1": {
            "verdict": a1,
            "note": a1_note,
            "misses": [row["interval_ms"] for row in misses],
            "intervals_scorable": len(scorable),
        },
        "A2": {
            "verdict": a2,
            "model_weighted_sse": model_residual,
            "flat_null_weighted_sse": null_residual,
            "ratio_model_over_null": ratio,
            "limit": A2_RESIDUAL_RATIO_LIMIT,
        },
        "A3": {
            "verdict": a3,
            "agreements": agreements,
            "required": A3_MINIMUM_AGREEMENTS,
            "by_comparison": comparisons,
        },
    }


def _degenerate_checks(
    *,
    cohort: dict[str, Any],
    fit_set: list[dict[str, Any]],
    primary: dict[str, Any],
    null_scores: dict[str, Any],
    primary_curve: list[float],
    secondary_curve: list[float] | None,
) -> dict[str, Any]:
    """The four checks the contract registered, all evaluated whatever the outcome."""
    null_a1 = str(null_scores["A1"]["verdict"])
    replication = [
        {
            "interval_ms": observed["interval_ms"],
            "holdout_mean": observed["mean"],
            "fit_set_mean": fitted["mean"],
            "difference": observed["mean"] - fitted["mean"],
            "fit_set_standard_error": fitted["standard_error"],
            "within_one_fit_set_standard_error": abs(observed["mean"] - fitted["mean"])
            <= fitted["standard_error"],
        }
        for observed, fitted in zip(cohort["by_interval"], fit_set, strict=True)
    ]
    separation = None
    if secondary_curve is not None:
        gaps = [
            abs(left - right)
            for left, right in zip(primary_curve, secondary_curve, strict=True)
        ]
        separation = {
            "largest_difference_between_the_frozen_curves": max(gaps),
            "by_interval": [
                {"interval_ms": interval, "difference": gap}
                for interval, gap in zip(ALL_INTERVALS_MS, gaps, strict=True)
            ],
            "limit": SEPARABILITY_LIMIT,
            "this_holdout_can_separate_them": max(gaps) >= SEPARABILITY_LIMIT,
        }
    return {
        "D1_underpowered_intervals": {
            "limit": A1_HALF_WIDTH_LIMIT,
            "intervals_dropped": [
                row["interval_ms"]
                for row in primary["by_interval"]
                if row["no_verdict_because_underpowered"]
            ],
            "minimum_scorable": A1_MINIMUM_SCORABLE,
        },
        "D2_the_flat_null_against_A1": {
            "flat_null_A1": null_a1,
            "A1_is_uninformative": null_a1 == "PASSED",
            "consequence": (
                "The flat null also lands inside the cohort's intervals, so A1 does not "
                "distinguish the model from a constant and the verdict rests on A2."
                if null_a1 == "PASSED"
                else "The flat null does not pass A1, so A1 carries information."
            ),
        },
        "D3_is_this_a_replication_rather_than_a_test": {
            "by_interval": replication,
            "all_five_within_one_fit_set_standard_error": all(
                row["within_one_fit_set_standard_error"] for row in replication
            ),
            "consequence": (
                "If every holdout mean sits within one fit-set standard error of the "
                "fit-set mean, this cohort is a replication of the same quantity rather "
                "than an independent test of it, and a pass must be recorded as such."
            ),
        },
        "D4_can_the_holdout_separate_the_two_frozen_models": separation,
    }


def run_stp_developmental_holdout(
    *,
    contract_path: Path,
    fit_artifact_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Open the two sealed wild-type cohorts once and score the frozen models."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The frozen plasticity holdout")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported developmental-holdout contract schema")
    if contract.get("values_opened"):
        raise ConfigurationError(
            "This contract already records its values as opened; a second scoring pass "
            "would be a second look at the same holdout"
        )
    expected = str(contract["depends_on"]["fit_artifact_sha256"])
    observed = sha256_file(fit_artifact_path)
    if observed != expected:
        raise ConfigurationError(
            "The fit artifact is not the one this contract froze from: contract records "
            f"{expected[:16]}..., file is {observed[:16]}..."
        )
    frozen = contract["frozen_models"]
    if frozen.get("primary") is None:
        raise ConfigurationError(
            "No primary model is frozen in this contract, so there is nothing to score "
            "and the cohorts must stay sealed"
        )
    primary_model = frozen["primary"]
    secondary_model = frozen.get("secondary")
    flat_level = float(frozen["flat_null"]["level"])

    primary_curve = _rederive(primary_model)
    secondary_curve = _rederive(secondary_model) if secondary_model else None

    cohorts = {
        role: _open_cohort(
            spec=contract["the_cohorts"][role],
            manifest_path=manifest_path,
            staging_root=staging_root,
        )
        for role in ("primary", "secondary")
    }

    scores: dict[str, Any] = {}
    for role, cohort in cohorts.items():
        entry: dict[str, Any] = {
            "primary_model": _score_model(
                predicted=primary_curve, cohort=cohort, flat_level=flat_level
            ),
            "flat_null": _score_model(
                predicted=[flat_level] * len(ALL_INTERVALS_MS),
                cohort=cohort,
                flat_level=flat_level,
            ),
        }
        if secondary_curve is not None:
            entry["secondary_model"] = _score_model(
                predicted=secondary_curve, cohort=cohort, flat_level=flat_level
            )
        scores[role] = entry

    fit_set = list(load_json(fit_artifact_path)["fit_set"]["by_interval"])
    checks = _degenerate_checks(
        cohort=cohorts["primary"],
        fit_set=fit_set,
        primary=scores["primary"]["primary_model"],
        null_scores=scores["primary"]["flat_null"],
        primary_curve=primary_curve,
        secondary_curve=secondary_curve,
    )

    a1 = str(scores["primary"]["primary_model"]["A1"]["verdict"])
    a2 = str(scores["primary"]["primary_model"]["A2"]["verdict"])
    if checks["D2_the_flat_null_against_A1"]["A1_is_uninformative"]:
        verdict = "PASSED" if a2 == "PASSED" else "FAILED"
        verdict_note = (
            f"A1 is uninformative on this cohort because the flat null also passes it, "
            f"so the registered fallback applies and the verdict is A2 alone: {a2}."
        )
    elif a1 == "NO VERDICT":
        verdict = "NO VERDICT"
        verdict_note = (
            "A1 is NO VERDICT under the registered power check, so no pass may be claimed."
        )
    else:
        verdict = "PASSED" if a1 == "PASSED" and a2 == "PASSED" else "FAILED"
        verdict_note = f"A1 {a1} and A2 {a2} on the primary cohort."

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-stp-developmental-holdout-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "M/F",
        "assumption_ids": list(contract["assumption_ids"]),
        "attribution": ATTRIBUTION,
        "fit_artifact": {"path": str(fit_artifact_path), "sha256": observed},
        "frozen_models": {
            "primary": {
                "family_id": primary_model["family_id"],
                "parameters": primary_model["parameters"],
                "predicted": primary_curve,
                "rederived_from_the_frozen_parameters": True,
            },
            "secondary": (
                {
                    "family_id": secondary_model["family_id"],
                    "parameters": secondary_model["parameters"],
                    "predicted": secondary_curve,
                    "rederived_from_the_frozen_parameters": True,
                }
                if secondary_model
                else None
            ),
            "flat_null_level": flat_level,
            "nothing_was_fitted_here": (
                "The parameters come from the committed contract and the curves were "
                "recomputed from them and checked against the recorded values before "
                "any cohort was opened. No optimiser ran in this module."
            ),
        },
        "cohorts": cohorts,
        "scores": scores,
        "degenerate_outcome_checks": checks,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "verdict_rule": str(contract["acceptance"]["verdict_rule"]),
        "what_a_pass_establishes": str(contract["acceptance"]["what_a_pass_would_establish"]),
        "what_a_pass_does_not_establish": str(
            contract["acceptance"]["what_a_pass_would_not_establish"]
        ),
        "no_refitting": str(contract["acceptance"]["no_refitting"]),
        "everything_else_stays_sealed": (
            "Ten arrays were opened: the five wild-type paired-pulse arrays of Fig3J and "
            "the five of Fig3H. No RNAi cohort, no train array, no raw trace, no "
            "miniature EPSC, no Bruchpilot count, nothing from Fig6D and nothing from "
            "the Takagi corpus."
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
