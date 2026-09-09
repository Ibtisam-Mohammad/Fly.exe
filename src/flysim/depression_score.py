# SPDX-License-Identifier: GPL-2.0-or-later
"""Score the frozen ND-06 rule against the reserved Rozenfeld paired-pulse observations.

This is the module that opens sealed data, so it is built to open as little as possible.
It runs in two stages, each of which records exactly which file and which variables it
touched: ``primary`` opens the single 100 ms wild-type array that the registry's open
prediction was written for, and ``intervals`` opens the remaining four wild-type arrays.
Nothing else in the Rozenfeld corpus is read by either stage — not the RNAi cohorts, not
the trains, not the replication cohorts, not the raw traces.

Before opening anything it re-checks the file against the checksum recorded in the sealed
reservation manifest, so the bytes being scored are demonstrably the bytes that were
reserved.

Nothing here refits anything. The utilisation and the recovery time constant are read from
the registry and used as they stand, which is the rule the first external failure at 7 Hz
was recorded under: refitting to an external test converts the only external check into a
training set.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.depression import load_published_fits, paired_pulse_ratio
from flysim.errors import ConfigurationError
from flysim.glomerular import _two_sided_t_p
from flysim.reservations import read_mat_variable
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

PRIMARY_INTERVAL_MS = 100.0
ALL_INTERVALS_MS: tuple[float, ...] = (10.0, 30.0, 100.0, 300.0, 1000.0)
STAGES: dict[str, tuple[float, ...]] = {
    "primary": (PRIMARY_INTERVAL_MS,),
    "intervals": ALL_INTERVALS_MS,
}
HALF_WIDTH_LIMIT = 0.10

# Fixed before any value was read, and disclosed as an addendum because the committed
# contract's missing-data rule was written for the train arrays only. A paired-pulse array
# holds one ratio per animal, so the only sensible rule is that a non-finite entry drops
# that animal, and the number dropped is reported alongside the number scored.
MISSING_DATA_RULE = (
    "One paired-pulse ratio per animal. A non-finite entry excludes that animal from that "
    "interval and the count of exclusions is reported. Fixed before any value was opened, "
    "and recorded as an addendum: the contract's nan_handling_fixed_now clause was written "
    "for the train arrays and does not cover a one-value-per-animal array."
)

ATTRIBUTION = (
    "Rozenfeld, Ezra-Nevo, Barnea, Hadad, Yakir and Yovel-Rodrigues et al., Homeostatic "
    "synaptic plasticity rescues neural coding reliability, Nature Communications 2023, "
    "doi 10.1038/s41467-023-38575-6. Source data from github.com/RoteMSN/"
    "Rozenfeld-et-al-2023 at commit 4e53fd71d6a8ad062543fe9e989ef2299eca75ba, MIT licence."
)


def variable_for(interval_ms: float) -> str:
    """The wild-type array name for one interval, as named in the committed contract."""
    if interval_ms not in ALL_INTERVALS_MS:
        raise ConfigurationError(f"{interval_ms} ms is not a preregistered interval")
    return f"new_all_flies_PP_{interval_ms:g}ms_control"


def t_quantile(*, degrees: int, two_sided_alpha: float = 0.05) -> float:
    """The two-sided Student-t critical value, by bisecting the tested tail function.

    The project already carries a calibrated regularised incomplete beta for Spearman's
    p-value, so the quantile is obtained by inverting that rather than by adding a second
    implementation or a table to keep in step with it.
    """
    if degrees < 1:
        raise ConfigurationError("A t quantile needs at least one degree of freedom")
    if not 0.0 < two_sided_alpha < 1.0:
        raise ConfigurationError("The two-sided alpha must lie in (0, 1)")
    low, high = 0.0, 1000.0
    for _ in range(200):
        middle = 0.5 * (low + high)
        if _two_sided_t_p(middle, degrees) > two_sided_alpha:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def summarise(values: np.ndarray) -> dict[str, Any]:
    """Cohort mean with a Student-t 95 percent interval, and what was dropped."""
    flat = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = flat[np.isfinite(flat)]
    excluded = int(flat.size - finite.size)
    if finite.size < 2:
        raise ConfigurationError("A cohort needs at least two finite observations")
    count = int(finite.size)
    mean = float(finite.mean())
    deviation = float(finite.std(ddof=1))
    error = deviation / np.sqrt(count)
    critical = t_quantile(degrees=count - 1)
    half_width = float(critical * error)
    return {
        "animals_supplied": int(flat.size),
        "animals_scored": count,
        "animals_excluded_non_finite": excluded,
        "mean": mean,
        "standard_deviation": deviation,
        "standard_error": float(error),
        "t_critical_95": float(critical),
        "ci95_low": mean - half_width,
        "ci95_high": mean + half_width,
        "ci95_half_width": half_width,
        "minimum": float(finite.min()),
        "maximum": float(finite.max()),
    }


def _verify_against_manifest(
    *, manifest_path: Path, relative_path: str, staging_root: Path
) -> dict[str, Any]:
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
    entry = entries[0]
    path = staging_root / relative_path
    if not path.is_file():
        raise ConfigurationError(f"Reserved file is missing: {path}")
    observed = sha256_file(path)
    if observed != entry["sha256"]:
        raise ConfigurationError(
            f"{relative_path} has changed since it was reserved: manifest recorded "
            f"{entry['sha256'][:16]}..., file is {observed[:16]}..."
        )
    return {
        "path": relative_path,
        "sha256": observed,
        "matches_sealed_manifest": True,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "reserved_variables_in_this_file": len(entry["reserved_names"]),
    }


def _predictions(registry_path: Path, rule_id: str) -> dict[str, Any]:
    fits = load_published_fits(registry_path, rule_id=rule_id)
    primary = next(fit for fit in fits if fit.primary)
    floor = min(1.0 - fit.utilisation for fit in fits)
    by_interval: dict[float, dict[str, Any]] = {}
    for interval in ALL_INTERVALS_MS:
        by_fit = {
            fit.fit_id: paired_pulse_ratio(
                utilisation=fit.utilisation,
                recovery_tau_ms=fit.recovery_tau_ms,
                interval_ms=interval,
            )
            for fit in fits
        }
        by_interval[interval] = {
            "primary": by_fit[primary.fit_id],
            "family_lowest": min(by_fit.values()),
            "family_highest": max(by_fit.values()),
        }
    return {
        "floor": floor,
        "by_interval": by_interval,
        "primary_fit": primary.as_dict(),
        "fits_used_as_registered": [fit.as_dict() for fit in fits],
        "nothing_was_refitted": (
            "The utilisation and the recovery time constant are the registered values. No "
            "parameter was adjusted before, during or after scoring."
        ),
    }


def _score_interval(
    *, interval_ms: float, observed: dict[str, Any], predicted: dict[str, Any], floor: float
) -> dict[str, Any]:
    contains = observed["ci95_low"] <= predicted["primary"] <= observed["ci95_high"]
    underpowered = observed["ci95_half_width"] > HALF_WIDTH_LIMIT
    return {
        "interval_ms": interval_ms,
        "variable": variable_for(interval_ms),
        "observed": observed,
        "predicted_primary": predicted["primary"],
        "predicted_family_band": [predicted["family_lowest"], predicted["family_highest"]],
        "ci_contains_the_prediction": bool(contains),
        "underpowered_by_the_registered_half_width_rule": bool(underpowered),
        "observed_minus_predicted": observed["mean"] - predicted["primary"],
        "mean_below_the_family_floor": bool(observed["mean"] < floor),
        "ci_high_below_the_family_floor": bool(observed["ci95_high"] < floor),
    }


def run_depression_external_test(
    *,
    stage: str,
    contract_path: Path,
    registry_path: Path,
    manifest_path: Path,
    staging_root: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Open the named wild-type arrays for one stage and score the registered hypotheses."""
    if stage not in STAGES:
        raise ConfigurationError(f"Unknown stage {stage!r}; expected one of {sorted(STAGES)}")
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree(f"The depression external test, stage {stage!r}")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported depression external-test contract schema")
    if contract.get("values_opened"):
        raise ConfigurationError(
            "This contract already records its values as opened; a second scoring pass "
            "would be a second look at the same holdout"
        )
    design = contract["prediction_grid"]
    source = contract["data"]["primary_source"]
    relative_path = str(source["file"])

    unsealing = _verify_against_manifest(
        manifest_path=manifest_path,
        relative_path=relative_path,
        staging_root=staging_root,
    )
    intervals = STAGES[stage]
    opened = [variable_for(interval) for interval in intervals]
    declared = set(source["variables"])
    if not set(opened) <= declared:
        raise ConfigurationError(
            "This stage would open a variable the contract does not name: "
            f"{sorted(set(opened) - declared)}"
        )

    predictions = _predictions(registry_path, str(design["rule_id"]))
    path = staging_root / relative_path
    scored: list[dict[str, Any]] = []
    for interval in intervals:
        values = read_mat_variable(path, variable_for(interval))
        scored.append(
            _score_interval(
                interval_ms=interval,
                observed=summarise(values),
                predicted=predictions["by_interval"][interval],
                floor=predictions["floor"],
            )
        )

    hypotheses = _verdicts(stage=stage, scored=scored, floor=predictions["floor"])
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": f"stage2-depression-external-test-{stage}-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "M/F",
        "assumption_ids": list(contract["assumption_ids"]),
        "stage": stage,
        "attribution": ATTRIBUTION,
        "unsealing": {
            **unsealing,
            "variables_opened": opened,
            "variables_opened_count": len(opened),
            "everything_else_stays_sealed": (
                "No RNAi array, no train array, no replication cohort, no raw trace, no "
                "miniature EPSC and no Bruchpilot count was opened by this run. The reader "
                "takes the variable name as an argument and returns only that variable."
            ),
            "missing_data_rule": MISSING_DATA_RULE,
        },
        "predictions": predictions,
        "by_interval": scored,
        "hypotheses": hypotheses,
        "no_refitting": (
            "No parameter is changed on this outcome, and no revision may claim this test as "
            "evidence. Refitting to an external test converts the only external check into a "
            "training set, which is the rule the 7 Hz failure was recorded under."
        ),
        "claim_boundary": (
            "Compound evoked paired-pulse ratios in wild-type controls, scored against the "
            "registered ND-06 rule through the VAL-02 observation model, whose clauses are "
            "all false in detail and whose biases run in both directions. It awards no tier, "
            "it does not reinstate the retired synaptic leg, and it says nothing about "
            "whether presynaptic depletion is the mechanism."
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


def _verdicts(*, stage: str, scored: list[dict[str, Any]], floor: float) -> list[dict[str, Any]]:
    """H1 in the primary stage; H1, H2 and H3 once all five intervals are open."""
    by_interval = {row["interval_ms"]: row for row in scored}
    primary = by_interval[PRIMARY_INTERVAL_MS]
    if primary["underpowered_by_the_registered_half_width_rule"]:
        h1 = "NO VERDICT"
        h1_note = (
            f"The 95 percent half-width is {primary['observed']['ci95_half_width']:.4f}, above "
            f"the registered {HALF_WIDTH_LIMIT} limit, so the interval is too wide to "
            "distinguish agreement from lack of power. Registered as NO VERDICT rather than "
            "as a pass."
        )
    else:
        h1 = "PASSED" if primary["ci_contains_the_prediction"] else "FAILED"
        h1_note = (
            f"Observed mean {primary['observed']['mean']:.4f} with a 95 percent interval of "
            f"[{primary['observed']['ci95_low']:.4f}, {primary['observed']['ci95_high']:.4f}] "
            f"over {primary['observed']['animals_scored']} animals, against the registered "
            f"prediction {primary['predicted_primary']:.4f}."
        )
    verdicts: list[dict[str, Any]] = [
        {
            "id": "H1",
            "name": "the registered prediction at the interval it was registered for",
            "primary": True,
            "verdict": h1,
            "note": h1_note,
        }
    ]
    if stage != "intervals":
        verdicts.append(
            {
                "id": "H2",
                "verdict": "NOT SCORED IN THIS STAGE",
                "note": "The floor test needs all five intervals; this stage opened one.",
            }
        )
        verdicts.append(
            {
                "id": "H3",
                "verdict": "NOT SCORED IN THIS STAGE",
                "note": "Monotonicity needs all five intervals; this stage opened one.",
            }
        )
        return verdicts

    below = [row["interval_ms"] for row in scored if row["mean_below_the_family_floor"]]
    verdicts.append(
        {
            "id": "H2",
            "name": "the floor the model cannot go below",
            "verdict": "FAILED" if below else "PASSED",
            "note": (
                f"The registered family cannot produce a ratio below {floor:.4f} at any "
                "interval. Cohort means below it: "
                + (", ".join(f"{value:g} ms" for value in below) if below else "none")
                + "."
            ),
            "intervals_below_the_floor": below,
        }
    )
    means = [by_interval[interval]["observed"]["mean"] for interval in ALL_INTERVALS_MS]
    monotone = all(later >= earlier for earlier, later in pairwise(means))
    verdicts.append(
        {
            "id": "H3",
            "name": "recovery is monotone in interval",
            "verdict": "PASSED" if monotone else "FAILED",
            "note": (
                "Cohort means in interval order: "
                + ", ".join(f"{value:.4f}" for value in means)
                + "."
            ),
            "means_in_interval_order": means,
        }
    )
    return verdicts
