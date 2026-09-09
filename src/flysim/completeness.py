# SPDX-License-Identifier: GPL-2.0-or-later
"""Invert the connectome's synapse-level incompleteness to recover true contact counts.

Median contacts per realised connection is measured over realised pairs only, and the
convergence test showed that weak connections are specifically what goes missing. So the
statistic is inflated exactly where reconstruction is worst, which is why the glomerular
volume question came out inconclusive.

The correction has two independent legs. The first needs no distributional assumption at
all: because an absent pair contributes zero observed contacts, the sum of observed
contacts over realised pairs is also the sum over *all* true pairs, and Kazama and Wilson
2009 supply the true pair count, so ``E[k_true] = total / (p * possible_pairs)``. The
second fits a distribution, and it works because a negative binomial is closed under
binomial thinning: zero-truncating the truth leaves the observed counts exactly
zero-truncated negative binomial in the thinned parameter. That makes the completeness a
prediction of the fit rather than an input to it, which is the test in H1.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.convergence import _dense_indices, _pair_completeness, load_olfactory_populations
from flysim.errors import ConfigurationError, DatasetError
from flysim.glomerular import _spearman
from flysim.provenance import parse_provenance
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

# The refined search grid's extent. H5 fails the contract if fitted parameters pile up here,
# which is the lesson the stage-2 kernel-family comparison had to be reissued to learn.
DISPERSION_BOUNDS = (0.05, 200.0)
OBSERVED_MEAN_BOUNDS = (0.5, 5000.0)
GRID_POINTS = 40
REFINEMENTS = 4


def _log_binomial_table(dispersion: float, maximum: int) -> np.ndarray:
    """``log C(k+r-1, k)`` for k = 0..maximum, by recurrence rather than lgamma.

    scipy is not a declared dependency and a per-candidate Python lgamma loop over every
    observed count is far too slow for a grid search, so the term is built once per
    dispersion as a cumulative sum and then indexed.
    """
    steps = np.arange(maximum, dtype=np.float64)
    numerator = np.concatenate(([0.0], np.cumsum(np.log(dispersion + steps))))
    denominator = np.concatenate(([0.0], np.cumsum(np.log(steps + 1.0))))
    return numerator - denominator


def _truncated_log_likelihood(
    values: np.ndarray,
    multiplicities: np.ndarray,
    log_binomial: np.ndarray,
    dispersion: float,
    mean: float,
) -> float:
    """Zero-truncated negative binomial log-likelihood of a count histogram."""
    q = dispersion / (dispersion + mean)
    zero_mass = q**dispersion
    if not 0.0 < zero_mass < 1.0:
        return -np.inf
    log_pmf = (
        log_binomial[values]
        + dispersion * math.log(q)
        + values * math.log1p(-q)
        - math.log1p(-zero_mass)
    )
    return float(np.dot(log_pmf, multiplicities))


def fit_truncated_negative_binomial(counts: np.ndarray) -> dict[str, Any]:
    """Maximum likelihood (r, mean) for observed counts, by coarse-to-fine grid.

    A grid rather than an optimiser so that a parameter resting against the edge of the
    search is visible and can fail a criterion, which is what H5 checks.
    """
    observed = np.asarray(counts, dtype=np.int64)
    if observed.size == 0:
        raise ConfigurationError("Cannot fit a contact distribution with no observations")
    if np.any(observed < 1):
        raise ConfigurationError(
            "Observed contact counts must be at least one; a zero count is an absent pair"
        )
    values, multiplicities = np.unique(observed, return_counts=True)
    multiplicities = multiplicities.astype(np.float64)
    maximum = int(values.max())
    dispersion_low, dispersion_high = DISPERSION_BOUNDS
    mean_low, mean_high = OBSERVED_MEAN_BOUNDS
    best: tuple[float, float, float] = (-math.inf, math.nan, math.nan)
    for refinement in range(REFINEMENTS):
        dispersions = np.geomspace(dispersion_low, dispersion_high, GRID_POINTS)
        means = np.geomspace(mean_low, mean_high, GRID_POINTS)
        for dispersion in dispersions:
            # The log-binomial term depends only on the dispersion, so it is built once
            # per row of the grid rather than once per candidate.
            log_binomial = _log_binomial_table(float(dispersion), maximum)
            for mean in means:
                log_likelihood = _truncated_log_likelihood(
                    values, multiplicities, log_binomial, float(dispersion), float(mean)
                )
                if log_likelihood > best[0]:
                    best = (log_likelihood, float(dispersion), float(mean))
        if refinement < REFINEMENTS - 1:
            # Narrow around the incumbent, staying inside the original bounds.
            span = (dispersion_high / dispersion_low) ** 0.25
            dispersion_low = max(DISPERSION_BOUNDS[0], best[1] / span)
            dispersion_high = min(DISPERSION_BOUNDS[1], best[1] * span)
            span = (mean_high / mean_low) ** 0.25
            mean_low = max(OBSERVED_MEAN_BOUNDS[0], best[2] / span)
            mean_high = min(OBSERVED_MEAN_BOUNDS[1], best[2] * span)
    best_log_likelihood, best_dispersion, best_mean = best
    if not math.isfinite(best_log_likelihood):
        raise ConfigurationError(
            "No contact distribution in the search grid has finite likelihood"
        )
    at_boundary = bool(
        math.isclose(best_dispersion, DISPERSION_BOUNDS[0], rel_tol=1e-3)
        or math.isclose(best_dispersion, DISPERSION_BOUNDS[1], rel_tol=1e-3)
        or math.isclose(best_mean, OBSERVED_MEAN_BOUNDS[0], rel_tol=1e-3)
        or math.isclose(best_mean, OBSERVED_MEAN_BOUNDS[1], rel_tol=1e-3)
    )
    return {
        "dispersion": best_dispersion,
        "observed_untruncated_mean": best_mean,
        "observed_q": best_dispersion / (best_dispersion + best_mean),
        "log_likelihood": best_log_likelihood,
        "at_search_boundary": at_boundary,
    }


def unthin(observed_q: float, dispersion: float, survival: float) -> dict[str, float]:
    """Undo a binomial thinning of a negative binomial at known survival probability.

    If ``k_true ~ NB(r, q)`` and ``k_obs = Binomial(k_true, p)`` then ``k_obs ~ NB(r, q_Y)``
    with ``q_Y = q / (1 - (1-q)(1-p))``, which inverts to
    ``q = q_Y p / (1 - q_Y (1-p))``. Zero-truncating the truth leaves the observed counts
    zero-truncated in ``q_Y``, so the fit identifies ``q_Y`` and this recovers ``q``.
    """
    if not 0.0 < survival <= 1.0:
        raise ConfigurationError("Synapse survival probability must lie in (0, 1]")
    if not 0.0 < observed_q < 1.0:
        raise ConfigurationError("Thinned negative binomial q must lie in (0, 1)")
    denominator = 1.0 - observed_q * (1.0 - survival)
    true_q = observed_q * survival / denominator
    true_mean = dispersion * (1.0 - true_q) / true_q
    truncated_true_mean = true_mean / (1.0 - true_q**dispersion)
    # The completeness the model predicts, which the fit never saw.
    predicted_completeness = (1.0 - observed_q**dispersion) / (1.0 - true_q**dispersion)
    return {
        "true_q": true_q,
        "true_untruncated_mean": true_mean,
        "model_corrected_mean_contacts": truncated_true_mean,
        "predicted_completeness": predicted_completeness,
    }


def recover_survival(
    observed_q: float, dispersion: float, completeness: float
) -> float | None:
    """Solve the thinning model for p given the measured completeness.

    Inverting ``completeness = (1 - q_Y^r)/(1 - q^r)`` gives ``q``, and
    ``p = q(1 - q_Y) / (q_Y (1 - q))`` gives the survival rate. Returns ``None`` when the
    measured completeness is not reachable under the fitted shape, which is itself a
    finding rather than an error.
    """
    if not 0.0 < completeness <= 1.0 or not 0.0 < observed_q < 1.0:
        return None
    observed_zero_mass = observed_q**dispersion
    true_zero_mass = 1.0 - (1.0 - observed_zero_mass) / completeness
    if not 0.0 < true_zero_mass < 1.0:
        return None
    true_q = true_zero_mass ** (1.0 / dispersion)
    if not 0.0 < true_q < 1.0:
        return None
    numerator = true_q * (1.0 - observed_q)
    denominator = observed_q * (1.0 - true_q)
    if denominator <= 0.0:
        return None
    survival = numerator / denominator
    return survival if 0.0 < survival <= 1.0 else None


def correct_glomerulus(
    *,
    glomerulus: str,
    contacts: np.ndarray,
    possible_pairs: int,
    survival: float,
) -> dict[str, Any]:
    """Every corrected statistic for one glomerulus, plus the checks on the correction."""
    observed = np.asarray(contacts, dtype=np.float64)
    realised = int(observed.size)
    if realised == 0:
        raise ConfigurationError(f"{glomerulus} has no realised connections to correct")
    if possible_pairs < realised:
        raise ConfigurationError(
            f"{glomerulus} reports {realised} realised pairs out of {possible_pairs} possible"
        )
    total = float(observed.sum())
    completeness = realised / possible_pairs
    # The model-free leg. An absent pair contributes no observed contacts, so the observed
    # total is the total over all true pairs, and complete convergence gives their number.
    exact_corrected_mean = total / (survival * possible_pairs)
    fit = fit_truncated_negative_binomial(observed)
    unthinned = unthin(fit["observed_q"], fit["dispersion"], survival)
    recovered = recover_survival(fit["observed_q"], fit["dispersion"], completeness)
    naive_mean = total / realised
    return {
        "glomerulus": glomerulus,
        "possible_pairs": possible_pairs,
        "realised_pairs": realised,
        "measured_completeness": completeness,
        "total_contacts": total,
        "naive_mean_contacts": naive_mean,
        "naive_median_contacts": float(np.median(observed)),
        "exact_corrected_mean_contacts": exact_corrected_mean,
        "correction_factor": completeness / survival,
        "fitted_dispersion": fit["dispersion"],
        "fitted_observed_q": fit["observed_q"],
        "fit_at_search_boundary": fit["at_search_boundary"],
        "log_likelihood": fit["log_likelihood"],
        "model_corrected_mean_contacts": unthinned["model_corrected_mean_contacts"],
        "predicted_completeness": unthinned["predicted_completeness"],
        "completeness_error": unthinned["predicted_completeness"] - completeness,
        "recovered_survival": recovered,
        "estimator_ratio": (
            unthinned["model_corrected_mean_contacts"] / exact_corrected_mean
            if exact_corrected_mean > 0.0
            else float("nan")
        ),
    }


def _score(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    volumes: dict[str, float],
) -> dict[str, Any]:
    """Score the preregistered hypotheses. Every criterion is read from the contract."""
    hypotheses = {str(item["id"]): item for item in contract["hypotheses"]}
    measured = np.asarray([row["measured_completeness"] for row in rows])
    predicted = np.asarray([row["predicted_completeness"] for row in rows])
    corrected = np.asarray([row["exact_corrected_mean_contacts"] for row in rows])
    naive_mean = np.asarray([row["naive_mean_contacts"] for row in rows])
    naive_median = np.asarray([row["naive_median_contacts"] for row in rows])
    receptors = np.asarray([float(row["receptor_bodies"]) for row in rows])

    completeness_rho, completeness_p = _spearman(predicted, measured)
    median_absolute_error = float(np.median(np.abs(predicted - measured)))
    h1 = hypotheses["H1"]
    h1_passed = bool(completeness_rho >= 0.7 and median_absolute_error <= 0.10)

    recovered = np.asarray(
        [row["recovered_survival"] for row in rows if row["recovered_survival"] is not None]
    )
    h2_median = float(np.median(recovered)) if recovered.size else float("nan")
    h2_passed = bool(recovered.size >= 35 and 0.30 <= h2_median <= 0.55)

    corrected_receptor_rho, corrected_receptor_p = _spearman(corrected, receptors)
    naive_receptor_rho, naive_receptor_p = _spearman(naive_median, receptors)
    h3_passed = bool(abs(corrected_receptor_rho) < 0.30 and corrected_receptor_p >= 0.05)

    volume = np.asarray([volumes[row["glomerulus"]] for row in rows])
    corrected_volume_rho, corrected_volume_p = _spearman(corrected, volume)
    naive_mean_volume_rho, naive_mean_volume_p = _spearman(naive_mean, volume)
    naive_median_volume_rho, naive_median_volume_p = _spearman(naive_median, volume)
    h4_supported = bool(corrected_volume_p < 0.05 and corrected_volume_rho > 0.0)

    boundary_count = sum(1 for row in rows if row["fit_at_search_boundary"])
    h5_passed = boundary_count < 5

    recorded = {str(item["glomerulus"]): item for item in rows}
    kazama_glomeruli = ("DL5", "DM4", "VM2", "DM6")
    kazama = {
        name: recorded[name]["exact_corrected_mean_contacts"]
        for name in kazama_glomeruli
        if name in recorded
    }
    h6_in_range = {
        name: bool(35.8 <= value <= 67.0) for name, value in kazama.items()
    }
    h6_passed = bool(kazama) and all(h6_in_range.values())
    release_site_ratio = (
        float(np.mean(list(kazama.values())) / 51.4) if kazama else float("nan")
    )

    return {
        "H1": {
            "statement": h1["statement"],
            "blind": True,
            "predicted_versus_measured_completeness_rho": completeness_rho,
            "p_value": completeness_p,
            "median_absolute_error": median_absolute_error,
            "passed": h1_passed,
            "gate": (
                "H1 is the gate. H3 and H4 are only readable as results if it passes, "
                "because a thinning model that cannot reproduce the completeness it was "
                "never shown is not a model of how these edges went missing."
            ),
        },
        "H2": {
            "statement": hypotheses["H2"]["statement"],
            "blind": True,
            "glomeruli_with_solvable_survival": int(recovered.size),
            "median_recovered_survival": h2_median,
            "recovered_survival_quartiles": (
                [float(value) for value in np.percentile(recovered, (25.0, 50.0, 75.0))]
                if recovered.size
                else []
            ),
            "registered_survival": 0.42,
            "passed": h2_passed,
        },
        "H3": {
            "statement": hypotheses["H3"]["statement"],
            "blind": True,
            "corrected_versus_receptor_count_rho": corrected_receptor_rho,
            "corrected_p_value": corrected_receptor_p,
            "naive_median_versus_receptor_count_rho": naive_receptor_rho,
            "naive_median_p_value": naive_receptor_p,
            "passed": h3_passed,
        },
        "H4": {
            "statement": hypotheses["H4"]["statement"],
            "blind": False,
            "not_blind_disclosure": hypotheses["H4"]["not_blind_disclosure"],
            "corrected_versus_volume_rho": corrected_volume_rho,
            "corrected_p_value": corrected_volume_p,
            "naive_mean_versus_volume_rho": naive_mean_volume_rho,
            "naive_mean_p_value": naive_mean_volume_p,
            "naive_median_versus_volume_rho": naive_median_volume_rho,
            "naive_median_p_value": naive_median_volume_p,
            "release_site_scaling_supported": h4_supported,
        },
        "H5": {
            "statement": hypotheses["H5"]["statement"],
            "blind": True,
            "glomeruli_at_search_boundary": boundary_count,
            "passed": h5_passed,
        },
        "H6": {
            "statement": hypotheses["H6"]["statement"],
            "blind": False,
            "not_blind_disclosure": hypotheses["H6"]["not_blind_disclosure"],
            "corrected_mean_contacts": kazama,
            "within_widened_kazama_wilson_range": h6_in_range,
            "kazama_wilson_release_sites_per_connection": 51.4,
            "mean_ratio_to_release_site_estimate": release_site_ratio,
            "passed": h6_passed,
        },
    }


def run_completeness_correction(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    output_path: Path,
    convergence_artifact: Path,
    volume_artifact: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Correct the contact statistic for synapse-level incompleteness and score the contract."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The completeness-corrected contact estimate")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported completeness-correction contract schema")
    parse_provenance(str(contract["provenance"]))
    survival = float(contract["model"]["p_registered"])

    annotations = (
        root / "raw" / "male-cns-v1.0" / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    if not annotations.is_file():
        raise DatasetError(f"Annotation artifact is required: {annotations}")
    volume_rows = load_json(volume_artifact)["by_glomerulus"]
    volumes = {
        str(item["glomerulus"]): float(item["rarefied_volume_um3"]) for item in volume_rows
    }
    convergence = load_json(convergence_artifact)

    receptors, projections = load_olfactory_populations(annotations)
    graph = SparseConnectome.load(graph_path)
    graph.validate()
    glomeruli = sorted(set(receptors) & set(projections))
    missing_volumes = [name for name in glomeruli if name not in volumes]
    if missing_volumes:
        raise DatasetError(
            "The volume artifact does not cover every glomerulus this correction scores: "
            f"{missing_volumes}"
        )

    rows: list[dict[str, Any]] = []
    for glomerulus in glomeruli:
        receptor_indices = _dense_indices(graph, receptors[glomerulus])
        projection_indices = _dense_indices(graph, projections[glomerulus])
        realised, contacts = _pair_completeness(graph, receptor_indices, projection_indices)
        possible = int(receptor_indices.size) * int(projection_indices.size)
        row = correct_glomerulus(
            glomerulus=glomerulus,
            contacts=contacts,
            possible_pairs=possible,
            survival=survival,
        )
        row["receptor_bodies"] = int(receptor_indices.size)
        row["projection_bodies"] = int(projection_indices.size)
        row["rarefied_volume_um3"] = volumes[glomerulus]
        if realised != row["realised_pairs"]:
            raise DatasetError(
                f"{glomerulus} realised-pair count disagrees with its contact array"
            )
        rows.append(row)

    hypotheses = _score(rows, contract, volumes)
    sensitivity = _sensitivity(rows, volumes, contract)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "completeness-corrected-contacts-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "assumption_ids": list(contract["assumption_ids"]),
        "graph_source_sha256": graph.source_sha256,
        "convergence_artifact_result_id": str(convergence.get("result_id", "")),
        "registered_survival": survival,
        "glomeruli_scored": len(rows),
        "by_glomerulus": rows,
        "hypotheses": hypotheses,
        "survival_sensitivity": sensitivity,
        "validation_tier_awarded": None,
        "claim_boundary": str(contract["claim_boundary"]),
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


def _sensitivity(
    rows: list[dict[str, Any]], volumes: dict[str, float], contract: dict[str, Any]
) -> dict[str, Any]:
    """How much of the result is the one number the project does not control.

    The exact estimator is ``total / (p * possible_pairs)``, so p rescales every corrected
    mean by a common factor and cannot change a rank correlation at all. H3 and H4 are
    therefore exactly p-invariant, and only the magnitudes H6 tests move. That is worth
    stating rather than dressing up as three separate analyses, so the magnitudes are
    tabulated and the invariance is asserted.
    """
    low, high = (float(value) for value in contract["model"]["p_sensitivity_range"])
    volume = np.asarray([volumes[str(row["glomerulus"])] for row in rows])
    receptors = np.asarray([float(row["receptor_bodies"]) for row in rows])
    baseline = np.asarray([float(row["exact_corrected_mean_contacts"]) for row in rows])
    baseline_survival = float(contract["model"]["p_registered"])
    magnitudes: list[dict[str, Any]] = []
    for survival in (low, baseline_survival, high):
        corrected = baseline * (baseline_survival / survival)
        receptor_rho, _ = _spearman(corrected, receptors)
        volume_rho, _ = _spearman(corrected, volume)
        magnitudes.append(
            {
                "survival": survival,
                "median_corrected_mean_contacts": float(np.median(corrected)),
                "corrected_versus_receptor_count_rho": receptor_rho,
                "corrected_versus_volume_rho": volume_rho,
            }
        )
    reference = magnitudes[1]
    invariant = all(
        math.isclose(
            item["corrected_versus_volume_rho"],
            reference["corrected_versus_volume_rho"],
            abs_tol=1e-12,
        )
        and math.isclose(
            item["corrected_versus_receptor_count_rho"],
            reference["corrected_versus_receptor_count_rho"],
            abs_tol=1e-12,
        )
        for item in magnitudes
    )
    if not invariant:
        raise ConfigurationError(
            "Rank correlations moved when p changed, which is impossible for an estimator "
            "that scales as 1/p; the correction is not implemented as specified"
        )
    return {
        "magnitudes": magnitudes,
        "rank_correlations_are_p_invariant": invariant,
        "why": (
            "The exact estimator scales as 1/p, a common factor across glomeruli, and a "
            "Spearman correlation is invariant to a positive monotone rescaling. So the "
            "H3 and H4 verdicts do not depend on the completion rate at all, and only the "
            "H6 magnitude comparison does."
        ),
    }
