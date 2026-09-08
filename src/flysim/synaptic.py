# SPDX-License-Identifier: GPL-2.0-or-later
"""Synaptic-tier (V2) structure and waveform analysis.

`V2 Synaptic` requires sign, unitary amplitude, kinetics, release failure and short-term
plasticity for mapped pairs. Two of those five have registered evidence, one is confounded
by the only unconsumed source, and two have no registered source at all. This module
supplies what can honestly be computed:

* the contact structure of identified receptor-to-projection-neuron connections in the
  V0-locked graph, tested against a published physiological claim about the same synapse;
* a per-contact scale in physical units implied by a published unitary amplitude; and
* preregistered feature tests of a frozen unitary-EPSC kernel.

`ND-04` states that contact count is not synaptic strength. Everything here is arranged so
that assertion can be checked rather than assumed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from flysim.circuit import load_cell_types
from flysim.config import load_json, sha256_json, write_json_atomic
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance

RECEPTOR_TYPE_PREFIX = "ORN_"


@dataclass(frozen=True, slots=True)
class GlomerularConnection:
    """One receptor-to-projection-neuron population and its contact structure."""

    glomerulus: str
    receptor_type: str
    projection_type: str
    projection_body_index: int
    converging_receptor_neurons: int
    total_contacts: int
    minimum_contacts: int
    median_contacts: float
    maximum_contacts: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "glomerulus": self.glomerulus,
            "receptor_type": self.receptor_type,
            "projection_type": self.projection_type,
            "projection_body_index": self.projection_body_index,
            "converging_receptor_neurons": self.converging_receptor_neurons,
            "total_contacts": self.total_contacts,
            "minimum_contacts": self.minimum_contacts,
            "median_contacts_per_connection": self.median_contacts,
            "maximum_contacts": self.maximum_contacts,
        }


def projection_type_pattern(tracts: tuple[str, ...]) -> re.Pattern[str]:
    if not tracts:
        raise ConfigurationError("At least one projection-neuron tract suffix is required")
    alternatives = "|".join(sorted(tracts, key=len, reverse=True))
    return re.compile(rf"^(?P<glomerulus>[A-Za-z0-9]+)_(?:{alternatives})PN$")


def olfactory_convergence_profile(
    source_indices: np.ndarray,
    target_indices: np.ndarray,
    contact_counts: np.ndarray,
    cell_types: tuple[str, ...],
    *,
    tracts: tuple[str, ...],
) -> list[GlomerularConnection]:
    """Contact structure of every identified receptor-to-projection-neuron population.

    The unit is one postsynaptic projection neuron, because that is the unit a paired
    recording measures: one PN, and the ORNs that converge on it.
    """
    types = np.asarray(cell_types, dtype=object)
    pattern = projection_type_pattern(tracts)
    receptor_indices: dict[str, set[int]] = {}
    for index, label in enumerate(cell_types):
        if label.startswith(RECEPTOR_TYPE_PREFIX):
            receptor_indices.setdefault(label[len(RECEPTOR_TYPE_PREFIX) :], set()).add(index)

    connections: list[GlomerularConnection] = []
    for projection_type in sorted({label for label in cell_types if pattern.match(label)}):
        match = pattern.match(projection_type)
        assert match is not None
        glomerulus = match.group("glomerulus")
        receptors = receptor_indices.get(glomerulus)
        if not receptors:
            continue
        for body_index in np.flatnonzero(types == projection_type):
            incoming = target_indices == body_index
            sources = source_indices[incoming]
            counts = contact_counts[incoming]
            keep = np.fromiter(
                (int(value) in receptors for value in sources),
                dtype=np.bool_,
                count=sources.size,
            )
            if not keep.any():
                continue
            selected = counts[keep].astype(np.int64)
            connections.append(
                GlomerularConnection(
                    glomerulus=glomerulus,
                    receptor_type=f"{RECEPTOR_TYPE_PREFIX}{glomerulus}",
                    projection_type=projection_type,
                    projection_body_index=int(body_index),
                    converging_receptor_neurons=int(keep.sum()),
                    total_contacts=int(selected.sum()),
                    minimum_contacts=int(selected.min()),
                    median_contacts=float(np.median(selected)),
                    maximum_contacts=int(selected.max()),
                )
            )
    return connections


def coefficient_of_variation(values: np.ndarray) -> float:
    """Standard deviation over mean; the scale-free spread the matching claim is about."""
    array = np.asarray(values, dtype=np.float64)
    if array.size < 2:
        raise ConfigurationError("A coefficient of variation needs at least two values")
    mean = float(np.mean(array))
    if mean == 0.0:
        raise ConfigurationError("A coefficient of variation is undefined at a zero mean")
    return float(np.std(array, ddof=1) / mean)


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(1, values.size + 1, dtype=np.float64)
    # Ties take the mean of the ranks they span, which is what Spearman requires.
    sorted_values = values[order]
    start = 0
    while start < values.size:
        stop = start + 1
        while stop < values.size and sorted_values[stop] == sorted_values[start]:
            stop += 1
        if stop - start > 1:
            ranks[order[start:stop]] = np.mean(ranks[order[start:stop]])
        start = stop
    return ranks


def spearman_rho(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation, implemented directly so no optional dependency is needed."""
    left = np.asarray(x, dtype=np.float64)
    right = np.asarray(y, dtype=np.float64)
    if left.shape != right.shape or left.ndim != 1:
        raise ConfigurationError("Spearman inputs must be one-dimensional and the same length")
    if left.size < 3:
        raise ConfigurationError("A rank correlation needs at least three observations")
    ranked_left = _average_ranks(left)
    ranked_right = _average_ranks(right)
    centred_left = ranked_left - ranked_left.mean()
    centred_right = ranked_right - ranked_right.mean()
    denominator = math.sqrt(float(np.sum(centred_left**2) * np.sum(centred_right**2)))
    if denominator == 0.0:
        raise ConfigurationError("A rank correlation is undefined when either input is constant")
    return float(np.sum(centred_left * centred_right) / denominator)


def epsc_waveform_features(time_ms: np.ndarray, trace_pa: np.ndarray) -> dict[str, float]:
    """Baseline-corrected unitary-EPSC features.

    This is the single definition used by both the frozen post-freeze review and the
    preregistered held-out test, so the two cannot drift apart.
    """
    times = np.asarray(time_ms, dtype=np.float64)
    trace = np.asarray(trace_pa, dtype=np.float64)
    baseline = float(np.mean(trace[times < 40.0]))
    inward = baseline - trace
    peak_index = int(np.argmax(inward))
    peak = float(inward[peak_index])
    peak_time = float(times[peak_index])
    target = peak / math.e
    after_peak = np.flatnonzero((np.arange(len(times)) > peak_index) & (inward <= target))
    decay_ms = float(times[int(after_peak[0])] - peak_time) if len(after_peak) else math.nan
    return {
        "baseline_pa": baseline,
        "peak_inward_amplitude_pa": peak,
        "peak_time_ms": peak_time,
        "peak_to_one_over_e_ms": decay_ms,
    }


def difference_of_exponentials_kernel(
    time_ms: np.ndarray, *, onset_ms: float, rise_tau_ms: float, decay_tau_ms: float
) -> np.ndarray:
    """Unit-peak causal kernel, matching the frozen fit's parameterisation exactly."""
    if decay_tau_ms <= rise_tau_ms or rise_tau_ms <= 0.0:
        raise ConfigurationError("The decay time constant must exceed a positive rise constant")
    times = np.asarray(time_ms, dtype=np.float64)
    elapsed = np.maximum(0.0, times - onset_ms)
    kernel = np.exp(-elapsed / decay_tau_ms) - np.exp(-elapsed / rise_tau_ms)
    kernel[times < onset_ms] = 0.0
    peak = float(np.max(kernel))
    if peak <= 0.0:
        raise ConfigurationError("The difference-of-exponentials kernel has no positive peak")
    return kernel / peak


def analyse_synaptic_structure(
    contract_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Test the published homeostatic-matching claim against V0-locked contact structure.

    The claim is physiological and the data are structural, so the test is deliberately
    narrow: it asks only whether contact number could be the mechanism, and reports what
    per-contact scale the published unitary amplitude would imply if it were.
    """
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported synaptic-structure contract schema")
    parse_provenance(str(contract["provenance"]))

    rule = contract["population_rule"]
    tracts = tuple(str(value) for value in rule["tracts"])
    minimum_glomeruli = int(rule["minimum_glomeruli"])
    artifacts = {str(item["path"]): item for item in contract["required_artifacts"]}
    graph_relative = next(key for key in artifacts if key.endswith("graph"))
    annotation_relative = next(key for key in artifacts if key.endswith(".feather"))

    graph = SparseConnectome.load(root / graph_relative)
    graph.validate()
    cell_types = load_cell_types(root / annotation_relative, graph.body_ids)
    connections = olfactory_convergence_profile(
        graph.source_indices,
        graph.target_indices,
        graph.contact_counts,
        cell_types,
        tracts=tracts,
    )
    if not connections:
        raise DatasetError("No identified receptor-to-projection-neuron connection was found")

    by_glomerulus: dict[str, list[GlomerularConnection]] = {}
    for connection in connections:
        by_glomerulus.setdefault(connection.glomerulus, []).append(connection)
    glomeruli = sorted(by_glomerulus)
    if len(glomeruli) < minimum_glomeruli:
        raise DatasetError(
            f"Only {len(glomeruli)} glomeruli resolved, below the registered minimum "
            f"of {minimum_glomeruli}"
        )

    summaries: list[dict[str, Any]] = []
    for glomerulus in glomeruli:
        rows = by_glomerulus[glomerulus]
        converging = float(np.mean([row.converging_receptor_neurons for row in rows]))
        median_contacts = float(np.median([row.median_contacts for row in rows]))
        total_contacts = float(np.mean([row.total_contacts for row in rows]))
        summaries.append(
            {
                "glomerulus": glomerulus,
                "projection_neuron_count": len(rows),
                "converging_receptor_neurons": converging,
                "median_contacts_per_connection": median_contacts,
                "mean_total_contacts_per_projection_neuron": total_contacts,
                "projection_types": sorted({row.projection_type for row in rows}),
            }
        )

    converging_counts = np.asarray(
        [item["converging_receptor_neurons"] for item in summaries], dtype=np.float64
    )
    total_contact_values = np.asarray(
        [item["mean_total_contacts_per_projection_neuron"] for item in summaries],
        dtype=np.float64,
    )
    median_contact_values = np.asarray(
        [item["median_contacts_per_connection"] for item in summaries], dtype=np.float64
    )
    cv_converging = coefficient_of_variation(converging_counts)
    cv_total = coefficient_of_variation(total_contact_values)
    rho = spearman_rho(converging_counts, median_contact_values)

    claim = contract["published_claim_under_test"]
    dozen = claim["several_dozen_contacts_range"]
    median_of_medians = float(np.median(median_contact_values))
    unitary = claim["unitary_epsp_mv"]
    scale_rows = [
        {
            "glomerulus": item["glomerulus"],
            "median_contacts_per_connection": item["median_contacts_per_connection"],
            "per_contact_mv_at_minimum_unitary": (
                float(unitary["minimum"]) / item["median_contacts_per_connection"]
            ),
            "per_contact_mv_at_maximum_unitary": (
                float(unitary["maximum"]) / item["median_contacts_per_connection"]
            ),
        }
        for item in summaries
        if item["median_contacts_per_connection"] > 0.0
    ]
    low = np.asarray(
        [row["per_contact_mv_at_minimum_unitary"] for row in scale_rows], dtype=np.float64
    )
    high = np.asarray(
        [row["per_contact_mv_at_maximum_unitary"] for row in scale_rows], dtype=np.float64
    )
    comparison = contract["derived_scale"]["comparison_value"]
    registered_scale = float(comparison["synaptic_mv_per_contact"])

    hypotheses = {
        "H1": {
            "statement": contract["hypotheses"][0]["statement"],
            "coefficient_of_variation_converging_receptor_neurons": cv_converging,
            "coefficient_of_variation_total_contacts": cv_total,
            "supports_structural_matching": bool(cv_total < cv_converging),
        },
        "H2": {
            "statement": contract["hypotheses"][1]["statement"],
            "spearman_rho": rho,
            "supports_structural_matching": bool(rho < 0.0),
        },
        "H3": {
            "statement": contract["hypotheses"][2]["statement"],
            "median_of_median_contacts_per_connection": median_of_medians,
            "several_dozen_range": [int(dozen["minimum"]), int(dozen["maximum"])],
            "consistent_with_published_estimate": bool(
                float(dozen["minimum"]) <= median_of_medians <= float(dozen["maximum"])
            ),
        },
    }
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-synaptic-structure-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "graph_source_sha256": graph.source_sha256,
        "neurons": graph.neuron_count,
        "edges": graph.edge_count,
        "glomeruli_resolved": len(glomeruli),
        "projection_neurons_profiled": len(connections),
        "per_glomerulus": summaries,
        "hypotheses": hypotheses,
        "derived_per_contact_scale_mv": {
            "formula": str(contract["derived_scale"]["formula"]),
            "published_unitary_epsp_mv": [
                float(unitary["minimum"]),
                float(unitary["maximum"]),
            ],
            "minimum_unitary": {
                "minimum": float(np.min(low)),
                "median": float(np.median(low)),
                "maximum": float(np.max(low)),
            },
            "maximum_unitary": {
                "minimum": float(np.min(high)),
                "median": float(np.median(high)),
                "maximum": float(np.max(high)),
            },
            "registered_engineering_scale_mv_per_contact": registered_scale,
            "registered_scale_inside_derived_range": bool(
                float(np.min(low)) <= registered_scale <= float(np.max(high))
            ),
            "per_glomerulus": scale_rows,
        },
        "artifact_validity": {
            "minimum_glomeruli_resolved": len(glomeruli) >= minimum_glomeruli,
            "all_values_finite": bool(
                np.all(np.isfinite(converging_counts))
                and np.all(np.isfinite(total_contact_values))
                and np.all(np.isfinite(median_contact_values))
            ),
            "every_reported_pair_has_at_least_one_contact": all(
                row.total_contacts > 0 for row in connections
            ),
        },
        "disclosure": str(contract["disclosure"]),
        "tier_policy": str(contract["tier_policy"]),
        "declared_blockers": [str(value) for value in contract["declared_blockers"]],
        "claim_boundary": str(contract["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    write_json_atomic(output, result)
    return result


def evaluate_uepsc_kinetics_holdout(
    contract_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Score the frozen unitary-EPSC kernel against preregistered numeric feature limits."""
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported uEPSC holdout contract schema")
    parse_provenance(str(contract["provenance"]))

    frozen = contract["frozen_fit"]
    fit_path = root / str(frozen["path"])
    observed_fit_sha256 = sha256_file(fit_path) if fit_path.is_file() else None
    if observed_fit_sha256 != str(frozen["sha256"]):
        raise DatasetError(
            "Frozen uEPSC fit SHA-256 mismatch: "
            f"expected {frozen['sha256']}, observed {observed_fit_sha256}"
        )
    fit = load_json(fit_path)
    if fit.get("frozen_before_held_out_evaluation") is not True:
        raise DatasetError("The uEPSC holdout requires a pre-frozen fit")
    kernel_parameters = fit["uepsc_model"]["parameters"]

    artifact = contract["required_artifact"]
    artifact_path = root / str(artifact["path"])
    observed_artifact_sha256 = sha256_file(artifact_path) if artifact_path.is_file() else None
    if observed_artifact_sha256 != str(artifact["sha256"]):
        raise DatasetError(
            "uEPSC artifact SHA-256 mismatch: "
            f"expected {artifact['sha256']}, observed {observed_artifact_sha256}"
        )

    held_out = tuple(str(value) for value in contract["held_out_specimen_ids"])
    consumed = frozenset(str(value) for value in contract["consumed_specimen_ids"])
    overlap = sorted(consumed.intersection(held_out))
    if overlap:
        raise DatasetError(f"The holdout names already consumed recorded cells: {overlap}")

    table = pq.read_table(artifact_path)
    payload = table.to_pydict()
    specimens = np.asarray(payload["specimen_id"], dtype=object)
    times_all = np.asarray(payload["time_ms"], dtype=np.float64)
    currents_all = np.asarray(payload["current_pa"], dtype=np.float64)
    time_ms: np.ndarray | None = None
    observed: list[dict[str, Any]] = []
    for specimen_id in held_out:
        selection = specimens == specimen_id
        if not selection.any():
            raise DatasetError(f"No normalized waveform for recorded cell {specimen_id}")
        specimen_times = times_all[selection]
        if time_ms is None:
            time_ms = specimen_times
        elif not np.array_equal(time_ms, specimen_times):
            raise DatasetError(f"Recorded cell {specimen_id} uses a different sample grid")
        observed.append(
            {
                "specimen_id": specimen_id,
                **epsc_waveform_features(specimen_times, currents_all[selection]),
            }
        )
    assert time_ms is not None

    kernel = difference_of_exponentials_kernel(
        time_ms,
        onset_ms=float(kernel_parameters["onset_ms"]),
        rise_tau_ms=float(kernel_parameters["rise_tau_ms"]),
        decay_tau_ms=float(kernel_parameters["decay_tau_ms"]),
    )
    amplitude = float(kernel_parameters["population_amplitude_pa"])
    model_features = epsc_waveform_features(time_ms, -amplitude * kernel)

    peak_time_errors = [
        abs(model_features["peak_time_ms"] - float(item["peak_time_ms"])) for item in observed
    ]
    decay_fractions = [
        abs(model_features["peak_to_one_over_e_ms"] - float(item["peak_to_one_over_e_ms"]))
        / float(item["peak_to_one_over_e_ms"])
        for item in observed
    ]
    amplitude_errors = [
        model_features["peak_inward_amplitude_pa"] - float(item["peak_inward_amplitude_pa"])
        for item in observed
    ]
    minimum_peak = min(float(item["peak_inward_amplitude_pa"]) for item in observed)

    gated = {item["id"]: item for item in contract["gated_criteria"]}
    missing = {"sign", "peak_time", "decay_time"} - set(gated)
    if missing:
        raise ConfigurationError(f"The contract omits gated criteria {sorted(missing)}")
    peak_time_limit = float(gated["peak_time"]["limit_ms"])
    decay_limit = float(gated["decay_time"]["limit_fraction"])

    median_peak_time_error = float(np.median(peak_time_errors))
    median_decay_fraction = float(np.median(decay_fractions))
    sign_pass = bool(minimum_peak > 0.0)
    peak_time_pass = bool(median_peak_time_error <= peak_time_limit)
    decay_pass = bool(median_decay_fraction <= decay_limit)

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-uepsc-kinetics-holdout-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "frozen_fit_path": str(fit_path),
        "frozen_fit_sha256": observed_fit_sha256,
        "parameters_refitted": False,
        "held_out_specimen_ids": list(held_out),
        "model_features": model_features,
        "held_out_features": observed,
        "gated": {
            "sign": {
                "minimum_held_out_peak_inward_amplitude_pa": minimum_peak,
                "passed": sign_pass,
            },
            "peak_time": {
                "median_absolute_error_ms": median_peak_time_error,
                "per_cell_absolute_error_ms": peak_time_errors,
                "limit_ms": peak_time_limit,
                "passed": peak_time_pass,
            },
            "decay_time": {
                "median_absolute_fractional_error": median_decay_fraction,
                "per_cell_absolute_fractional_error": decay_fractions,
                "limit": decay_limit,
                "passed": decay_pass,
            },
        },
        "reported_not_gated": {
            "peak_amplitude_error_pa": amplitude_errors,
            "median_peak_amplitude_error_pa": float(np.median(amplitude_errors)),
            "reason": str(contract["reported_but_not_gated"][0]["reason"]),
        },
        "acceptance": {
            "v2_kinetics_subgate_pass": sign_pass and peak_time_pass and decay_pass,
            "awards_v2": False,
            "why_not": str(contract["acceptance"]["why_not"]),
        },
        "threshold_provenance": str(contract["threshold_provenance"]),
        "tier_policy": str(contract["tier_policy"]),
        "declared_blockers": [str(value) for value in contract["declared_blockers"]],
        "claim_boundary": str(contract["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    write_json_atomic(output, result)
    return result
