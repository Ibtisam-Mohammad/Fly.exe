# SPDX-License-Identifier: GPL-2.0-or-later
"""Score the jointly-fitted ORN-to-PN models once against the sealed day-0 1 Hz train.

One array: Fig3G's wild-type 32-pulse trajectory in twenty animals, never decoded. Not
its RNAi partner, nothing else in the file, nothing in any other file.

Three guards run before a byte of payload is decoded: the manifest checksum, the
stored-byte duplicate check against every spent array, and the re-derivation of every
frozen trajectory from its frozen parameters. A fourth runs immediately after: the
contract's registered internal consistency check on the cohort's first-pulse magnitude,
which exists because the train experiment earlier today scored latency arrays as
amplitudes and none of the provenance guards could have caught it.

Nothing here fits anything. The null is ND-06 v0.1, the refuted predecessor, rather than
a horizontal line.
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
from flysim.stp_joint import normalise_train

J1_FRACTION = 0.80
J1_MINIMUM_SCORABLE = 20
J2_RATIO = 0.5
REDERIVE_TOLERANCE = 1e-6

# The registered internal consistency check: a wild-type evoked current of the same sign
# and order as the fit set's 50.43 pA.
REFERENCE_FIRST_PULSE_PA = 50.43
FIRST_PULSE_FACTOR = 5.0


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


def _refuse_duplicates(
    *, staging_root: Path, relative_path: str, variable: str, spent: list[dict[str, Any]]
) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    for source in spent:
        names = [variable, *source.get("variables", [])]
        found = duplicate_arrays(
            candidate=staging_root / relative_path,
            spent=staging_root / str(source["file"]),
            names=names,
        )
        checked.append({"against": source["file"], "duplicate_arrays": list(found)})
        if found:
            raise ConfigurationError(
                f"{relative_path} stores the same arrays as the spent {source['file']}: "
                f"{list(found)}. Scoring it would be scoring spent data."
            )
    return {"checked_against": checked, "no_duplicate_found": True}


def _rederive(model: dict[str, Any]) -> list[float]:
    family_id = str(model["family_id"])
    names = family(family_id).parameter_names
    missing = [name for name in names if name not in model["parameters"]]
    if missing:
        raise ConfigurationError(f"{family_id} is frozen without {missing}")
    theta = tuple(float(model["parameters"][name]) for name in names)
    recorded = [float(v) for v in model["one_hz_trajectory"]]
    values = amplitudes(family_id, theta, [i * 1000.0 for i in range(len(recorded))])
    curve = [float(v / values[0]) for v in values]
    for index, (left, right) in enumerate(zip(recorded, curve, strict=True)):
        if abs(left - right) > REDERIVE_TOLERANCE:
            raise ConfigurationError(
                f"The frozen {family_id} trajectory at pulse {index + 1} no longer "
                f"reproduces: contract {left}, code {right:.9f}"
            )
    return curve


def _score(curve: list[float], cohort: dict[str, Any]) -> dict[str, Any]:
    observed = cohort["normalised"]
    errors = cohort["standard_error"]
    inside, scored, error_sum = 0, 0, 0.0
    rows: list[dict[str, Any]] = []
    for index in range(1, len(observed)):
        value, error = observed[index], errors[index]
        if not np.isfinite(value) or not np.isfinite(error) or error <= 0.0:
            continue
        scored += 1
        within = abs(curve[index] - value) <= 1.96 * error
        inside += int(within)
        error_sum += ((curve[index] - value) / error) ** 2
        rows.append(
            {
                "pulse": index + 1,
                "predicted": curve[index],
                "observed": value,
                "standard_error": error,
                "inside": bool(within),
            }
        )
    return {
        "pulses_scored": scored,
        "pulses_inside": inside,
        "fraction_inside": inside / scored if scored else 0.0,
        "weighted_squared_error": error_sum,
        "steady_state_predicted": float(np.mean(curve[-5:])),
        "by_pulse": rows,
    }


def run_joint_holdout(
    *,
    contract_path: Path,
    fit_artifact_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Open Fig3G's wild-type train once and score the frozen models."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The joint-fit day-0 train holdout")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported joint-holdout contract schema")
    if contract.get("values_opened"):
        raise ConfigurationError(
            "This contract already records its values as opened; a second scoring pass "
            "would be a second look at the same holdout"
        )
    expected = str(contract["depends_on"]["fit_artifact_sha256"])
    observed_fit = sha256_file(fit_artifact_path)
    if observed_fit != expected:
        raise ConfigurationError(
            "The fit artifact is not the one this contract froze from: contract records "
            f"{expected[:16]}..., file is {observed_fit[:16]}..."
        )
    frozen = contract["frozen_models"]
    curves = {role: _rederive(frozen[role]) for role in ("primary", "secondary", "null_nd06_v0_1")}

    spec = contract["the_cohort"]
    relative_path, variable = str(spec["file"]), str(spec["variable"])
    duplication = _refuse_duplicates(
        staging_root=staging_root,
        relative_path=relative_path,
        variable=variable,
        spent=list(contract["depends_on"]["spent_arrays"]),
    )
    unsealing = _verify(
        manifest_path=manifest_path, relative_path=relative_path, staging_root=staging_root
    )
    raw = read_mat_variable(staging_root / relative_path, variable)
    cohort = normalise_train(raw)

    magnitude = cohort["first_pulse_magnitude"]
    ratio = magnitude / REFERENCE_FIRST_PULSE_PA
    consistent = bool(
        np.isfinite(magnitude) and 1.0 / FIRST_PULSE_FACTOR <= ratio <= FIRST_PULSE_FACTOR
    )
    consistency = {
        "cohort_mean_first_pulse_magnitude": magnitude,
        "reference": REFERENCE_FIRST_PULSE_PA,
        "ratio": ratio,
        "allowed_factor": FIRST_PULSE_FACTOR,
        "passes": consistent,
        "why_this_check_exists": (
            "The train experiment earlier today scored per-pulse latency arrays as "
            "amplitudes and every provenance guard passed, because they check identity "
            "rather than whether the quantity is the quantity. This is the registered "
            "internal check the data can fail on their own terms."
        ),
    }
    if raw.shape[1] != len(curves["primary"]):
        raise ConfigurationError(
            f"{variable} has {raw.shape[1]} pulses, the contract froze {len(curves['primary'])}"
        )

    scores = {role: _score(curve, cohort) for role, curve in curves.items()}
    verdicts = _verdicts(scores=scores, cohort=cohort, consistency=consistency)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-stp-joint-holdout-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "M/F",
        "assumption_ids": list(contract["assumption_ids"]),
        "attribution": ATTRIBUTION,
        "unsealing": {
            **unsealing,
            "variable_opened": variable,
            "not_a_duplicate_of_a_spent_cohort": duplication,
            "everything_else_stays_sealed": str(spec["everything_else_stays_sealed"]),
        },
        "internal_consistency_check": consistency,
        "fit_artifact": {"path": str(fit_artifact_path), "sha256": observed_fit},
        "frozen_models_rederived": True,
        "cohort": cohort,
        "scores": scores,
        "hypotheses": verdicts,
        "verdict": verdicts["verdict"],
        "verdict_note": verdicts["verdict_note"],
        "the_developmental_caveat": str(contract["the_developmental_caveat_declared_in_advance"]),
        "what_a_pass_establishes": str(contract["acceptance"]["what_a_pass_would_establish"]),
        "what_a_pass_does_not_establish": str(
            contract["acceptance"]["what_a_pass_would_not_establish"]
        ),
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
    *, scores: dict[str, Any], cohort: dict[str, Any], consistency: dict[str, Any]
) -> dict[str, Any]:
    primary, null = scores["primary"], scores["null_nd06_v0_1"]
    if not consistency["passes"]:
        return {
            "J1": {"verdict": "NO VERDICT"},
            "J2": {"verdict": "NO VERDICT"},
            "verdict": "NO VERDICT",
            "verdict_note": (
                "The registered internal consistency check failed: the cohort's mean "
                f"first-pulse magnitude is {consistency['cohort_mean_first_pulse_magnitude']:.3f} "
                f"against a reference {consistency['reference']}. The array is not the "
                "quantity this contract believes it is and no score is reported."
            ),
        }
    if primary["pulses_scored"] < J1_MINIMUM_SCORABLE:
        j1, j1_note = "NO VERDICT", (
            f"Only {primary['pulses_scored']} pulses are scorable against a registered "
            f"minimum of {J1_MINIMUM_SCORABLE}."
        )
    else:
        j1 = "PASSED" if primary["fraction_inside"] >= J1_FRACTION else "FAILED"
        j1_note = (
            f"{primary['pulses_inside']} of {primary['pulses_scored']} pulses inside, a "
            f"fraction of {primary['fraction_inside']:.3f} against the registered "
            f"{J1_FRACTION}."
        )
    ratio = (
        primary["weighted_squared_error"] / null["weighted_squared_error"]
        if null["weighted_squared_error"] > 0.0
        else float("inf")
    )
    j2 = "PASSED" if ratio <= J2_RATIO else "FAILED"
    null_passes_j1 = null["fraction_inside"] >= J1_FRACTION
    verdict = "PASSED" if (j1 == "PASSED" and j2 == "PASSED") else "FAILED"
    if j1 == "NO VERDICT":
        verdict = "PASSED" if j2 == "PASSED" else "FAILED"
    observed_steady = float(np.mean([v for v in cohort["normalised"][-5:] if np.isfinite(v)]))
    return {
        "J1": {"verdict": j1, "note": j1_note, **{k: primary[k] for k in
               ("pulses_scored", "pulses_inside", "fraction_inside")}},
        "J2": {
            "verdict": j2,
            "model_weighted_sse": primary["weighted_squared_error"],
            "nd06_v0_1_weighted_sse": null["weighted_squared_error"],
            "ratio": ratio,
            "limit": J2_RATIO,
        },
        "J3": {
            "verdict": "REPORTED",
            "observed_steady_state": observed_steady,
            "predicted": {role: scores[role]["steady_state_predicted"] for role in scores},
        },
        "J4": {
            "verdict": "REPORTED",
            "secondary_weighted_sse": scores["secondary"]["weighted_squared_error"],
            "secondary_fraction_inside": scores["secondary"]["fraction_inside"],
            "primary_weighted_sse": primary["weighted_squared_error"],
        },
        "degenerate_outcome_checks": {
            "the_null_also_passes_J1": null_passes_j1,
            "consequence": (
                "ND-06 v0.1 also lands inside at the required fraction, so J1 does not "
                "discriminate and the verdict rests on J2."
                if null_passes_j1
                else "ND-06 v0.1 does not pass J1, so J1 carries information."
            ),
        },
        "verdict": verdict,
        "verdict_note": f"J1 {j1} and J2 {j2}.",
    }
