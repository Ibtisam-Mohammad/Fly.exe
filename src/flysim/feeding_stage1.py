# SPDX-License-Identifier: GPL-2.0-or-later
"""Frozen execution and post-hoc evaluation of the Stage 1 feeding screen."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.circuit import (
    build_control_graph,
    load_cell_types,
    parameters_from_experiment,
    run_genn_population_screen,
    select_population_path_circuit,
)
from flysim.config import load_json, project_root, sha256_json
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.errors import DatasetError, ReadinessError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs

_MAX_SEEDS_PER_GENN_BATCH = 10


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _immutable_snapshot(path: Path) -> tuple[Path, str]:
    digest = sha256_file(path)
    snapshot = path.with_name(f"{path.stem}-{digest[:16]}{path.suffix}")
    if snapshot.exists() and sha256_file(snapshot) != digest:
        raise DatasetError(f"Immutable feeding-screen snapshot collision: {snapshot}")
    if not snapshot.exists():
        temporary = snapshot.with_suffix(snapshot.suffix + ".part")
        shutil.copyfile(path, temporary)
        os.replace(temporary, snapshot)
    return snapshot, digest


def _code_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=project_root(),
    ).stdout.strip()


def _run_chunked_screen(
    *,
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    populations: dict[str, tuple[int, ...]],
    parameters: Any,
    readouts: tuple[int, ...],
    frequency_hz: float,
    seed_labels: tuple[int, ...],
    master_seed: int,
    build_path: Path,
) -> dict[str, Any]:
    """Respect GeNN's CUDA batch-axis bound without changing trial coverage."""
    chunks = [
        seed_labels[index : index + _MAX_SEEDS_PER_GENN_BATCH]
        for index in range(0, len(seed_labels), _MAX_SEEDS_PER_GENN_BATCH)
    ]
    results = [
        run_genn_population_screen(
            graph,
            edge_signs,
            populations,
            parameters,
            readouts,
            frequency_hz=frequency_hz,
            seed_labels=chunk,
            master_seed=master_seed + int(chunk[0]),
            build_path=build_path,
        )
        for chunk in chunks
    ]
    return {
        "population_names": list(results[0].population_names),
        "seed_labels": [seed for result in results for seed in result.seed_labels],
        "readout_body_ids": list(results[0].readout_body_ids),
        "readout_rates_hz": np.concatenate(
            [result.readout_rates_hz for result in results], axis=1
        ).tolist(),
        "total_spike_counts": np.concatenate(
            [result.total_spike_counts for result in results], axis=1
        ).tolist(),
        "finite_state": all(result.finite_state for result in results),
        "master_seed": master_seed,
        "chunk_master_seeds": [result.master_seed for result in results],
        "runtime_seconds": float(sum(result.runtime_seconds for result in results)),
        "model_identities": [result.model_identity for result in results],
        "execution_chunks": len(results),
        "maximum_seeds_per_chunk": _MAX_SEEDS_PER_GENN_BATCH,
    }


def preregister_feeding_screen(
    *,
    preparation_path: Path,
    experiment_path: Path,
    population_resolution_path: Path,
    graph_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Freeze mappings, model, controls and gates without retaining outcome labels."""
    preparation = load_json(preparation_path)
    experiment = load_json(experiment_path)
    graph = SparseConnectome.load(graph_path)
    population_resolution = load_json(population_resolution_path)
    readouts = next(
        (
            tuple(int(value) for value in item["body_ids"])
            for item in population_resolution["populations"]
            if item["id"] == "feeding-mn9"
        ),
        (),
    )
    if len(readouts) != 2:
        raise ReadinessError("Feeding screen requires exactly two resolved MaleCNS MN9 bodies")
    populations = [
        {
            "source_type": str(item["source_type"]),
            "mapping_status": str(item["mapping_status"]),
            "male_cns_body_ids": [int(value) for value in item["male_cns_body_ids"]],
        }
        for item in preparation["transfer_records"]
        if item["male_cns_body_ids"]
    ]
    if len(populations) != 101:
        raise ReadinessError(f"Expected 101 mapped feeding-screen types, found {len(populations)}")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "preregistered-label-blind",
        "experiment_id": experiment["experiment_id"],
        "code_commit": _code_commit(),
        "graph_path": str(graph_path.resolve()),
        "graph_source_sha256": graph.source_sha256,
        "preparation_sha256": sha256_file(preparation_path),
        "experiment_sha256": sha256_file(experiment_path),
        "experiment_logical_sha256": sha256_json(experiment),
        "population_resolution_sha256": sha256_file(population_resolution_path),
        "input_populations": populations,
        "readout_body_ids": list(readouts),
        "published_parameters": experiment["published_parameters"],
        "reference_duration_and_trial_count": experiment["reference"],
        "transfer_protocol": experiment["transfer_protocol"],
        "outcome_fields_present": False,
        "outcome_fields_excluded": [
            "observed_extension_fraction",
            "observed_positive",
            "predicted_left_mn9_rate_hz",
            "predicted_right_mn9_rate_hz",
            "predicted_positive",
        ],
        "assumption_ids": experiment["assumption_ids"],
        "provenance": experiment["provenance"],
        "claim_boundary": experiment["transfer_protocol"]["claim_boundary"],
        "validation_tier_awarded": None,
    }
    # Per-population records are the leakage boundary. The exclusion declaration
    # above intentionally names the forbidden source fields.
    if any(
        set(item) - {"source_type", "mapping_status", "male_cns_body_ids"}
        for item in payload["input_populations"]
    ):
        raise DatasetError("Preregistration leaked feeding-screen outcome fields")
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot.resolve()),
    }


def execute_feeding_screen(
    *,
    root: Path,
    preregistration_path: Path,
    annotations_path: Path,
    transmitter_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Generate predictions without opening the biological outcome table."""
    preregistration = load_json(preregistration_path)
    if preregistration.get("status") != "preregistered-label-blind":
        raise DatasetError("Feeding screen is not a frozen label-blind preregistration")
    graph = SparseConnectome.load(Path(preregistration["graph_path"]))
    populations = {
        str(item["source_type"]): tuple(int(value) for value in item["male_cns_body_ids"])
        for item in preregistration["input_populations"]
    }
    readouts = tuple(int(value) for value in preregistration["readout_body_ids"])
    protocol = preregistration["transfer_protocol"]
    selection = select_population_path_circuit(
        graph,
        populations,
        readouts,
        maximum_hops=int(protocol["maximum_path_hops"]),
    )
    if selection.no_path_input_body_ids:
        raise ReadinessError(
            f"Mapped feeding inputs lack a bounded path: {selection.no_path_input_body_ids}"
        )
    selected_populations = {
        name: tuple(body_id for body_id in values if body_id in selection.input_body_ids)
        for name, values in populations.items()
    }
    if any(not values for values in selected_populations.values()):
        raise ReadinessError("At least one mapped feeding population has no selected input body")
    cell_types = load_cell_types(annotations_path, selection.graph.body_ids)
    parameters = parameters_from_experiment(
        {
            "published_parameters": preregistration["published_parameters"],
            "transfer_protocol": protocol,
            "reference": preregistration["reference_duration_and_trial_count"],
        }
    )
    seed_labels = tuple(int(value) for value in protocol["seed_labels"])
    master_seed = int(protocol["master_seed"])
    frequency = float(protocol["input_frequency_hz"])
    weak_edge_max = int(protocol["weak_edge_max_contacts"])
    base_signs = build_shiu_regression_signs(
        selection.graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy.ZERO,
        seed=master_seed,
    )
    runs: list[dict[str, Any]] = []
    for variant in protocol["structural_controls"]:
        control_graph = build_control_graph(
            selection.graph,
            str(variant),
            cell_types=cell_types,
            seed=master_seed,
            weak_edge_max_contacts=weak_edge_max,
        )
        signs = build_shiu_regression_signs(
            control_graph,
            transmitter_path,
            unresolved_policy=UnresolvedSignPolicy.ZERO,
            seed=master_seed,
        )
        run = _run_chunked_screen(
            graph=control_graph,
            edge_signs=signs.edge_signs,
            populations=selected_populations,
            parameters=parameters,
            readouts=readouts,
            frequency_hz=frequency,
            seed_labels=seed_labels,
            master_seed=master_seed,
            build_path=root
            / "cache"
            / "genn"
            / "stage1-feeding"
            / f"{variant}-{control_graph.source_sha256[:12]}",
        )
        runs.append(
            {
                "family": "structural-control",
                "variant": variant,
                "graph_sha256": control_graph.source_sha256,
                "neurons": control_graph.neuron_count,
                "edges": control_graph.edge_count,
                "unresolved_sign_policy": UnresolvedSignPolicy.ZERO.value,
                **run,
            }
        )

    for policy_name in protocol["sign_controls"]:
        policy = UnresolvedSignPolicy(str(policy_name))
        if policy is UnresolvedSignPolicy.ZERO:
            continue
        signs = build_shiu_regression_signs(
            selection.graph,
            transmitter_path,
            unresolved_policy=policy,
            seed=master_seed,
        )
        run = _run_chunked_screen(
            graph=selection.graph,
            edge_signs=signs.edge_signs,
            populations=selected_populations,
            parameters=parameters,
            readouts=readouts,
            frequency_hz=frequency,
            seed_labels=seed_labels,
            master_seed=master_seed,
            build_path=root
            / "cache"
            / "genn"
            / "stage1-feeding"
            / f"sign-{policy.value}-{selection.graph.source_sha256[:12]}",
        )
        runs.append(
            {
                "family": "sign-sensitivity",
                "variant": policy.value,
                "graph_sha256": selection.graph.source_sha256,
                "neurons": selection.graph.neuron_count,
                "edges": selection.graph.edge_count,
                "unresolved_sign_policy": policy.value,
                **run,
            }
        )

    zero_run = _run_chunked_screen(
        graph=selection.graph,
        edge_signs=np.zeros(selection.graph.edge_count, dtype=np.float32),
        populations=selected_populations,
        parameters=parameters,
        readouts=readouts,
        frequency_hz=frequency,
        seed_labels=seed_labels,
        master_seed=master_seed,
        build_path=root
        / "cache"
        / "genn"
        / "stage1-feeding"
        / f"zero-weight-{selection.graph.source_sha256[:12]}",
    )
    runs.append(
        {
            "family": "negative-control",
            "variant": "zero-weight",
            "graph_sha256": selection.graph.source_sha256,
            "neurons": selection.graph.neuron_count,
            "edges": selection.graph.edge_count,
            **zero_run,
        }
    )

    sensitivity_parameters = replace(
        parameters, dt_ms=float(protocol["timestep_sensitivity_ms"])
    )
    dt_run = _run_chunked_screen(
        graph=selection.graph,
        edge_signs=base_signs.edge_signs,
        populations=selected_populations,
        parameters=sensitivity_parameters,
        readouts=readouts,
        frequency_hz=frequency,
        seed_labels=seed_labels,
        master_seed=master_seed,
        build_path=root
        / "cache"
        / "genn"
        / "stage1-feeding"
        / f"dt-{sensitivity_parameters.dt_ms}-{selection.graph.source_sha256[:12]}",
    )
    runs.append(
        {
            "family": "numerical-sensitivity",
            "variant": f"dt-{sensitivity_parameters.dt_ms}-ms",
            "graph_sha256": selection.graph.source_sha256,
            "neurons": selection.graph.neuron_count,
            "edges": selection.graph.edge_count,
            **dt_run,
        }
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "predictions-frozen-before-outcome-evaluation",
        "experiment_id": preregistration["experiment_id"],
        "code_commit": _code_commit(),
        "preregistration_path": str(preregistration_path.resolve()),
        "preregistration_sha256": sha256_file(preregistration_path),
        "selection": selection.as_dict(),
        "parameters": {
            "primary_dt_ms": parameters.dt_ms,
            "sensitivity_dt_ms": sensitivity_parameters.dt_ms,
            "duration_ms": parameters.duration_ms,
            "input_frequency_hz": frequency,
        },
        "runs": runs,
        "biological_outcomes_loaded": False,
        "all_states_finite": all(bool(item["finite_state"]) for item in runs),
        "validation_tier_awarded": None,
    }
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot.resolve()),
    }


def _binary_metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    predicted = scores > 0.0
    tp = int(np.sum(predicted & labels))
    fp = int(np.sum(predicted & ~labels))
    tn = int(np.sum(~predicted & ~labels))
    fn = int(np.sum(~predicted & labels))
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    positive_scores = scores[labels]
    negative_scores = scores[~labels]
    comparisons = (
        (positive_scores[:, None] > negative_scores[None, :]).sum()
        + 0.5 * (positive_scores[:, None] == negative_scores[None, :]).sum()
    )
    auroc = float(comparisons / (positive_scores.size * negative_scores.size))
    return {
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
        },
        "accuracy": float((tp + tn) / labels.size),
        "balanced_accuracy": float((sensitivity + specificity) / 2.0),
        "sensitivity": float(sensitivity),
        "specificity": float(specificity),
        "auroc": auroc,
        "positive_count": int(labels.sum()),
        "negative_count": int((~labels).sum()),
    }


def evaluate_feeding_screen(
    *,
    preparation_path: Path,
    preregistration_path: Path,
    predictions_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Open biological outcomes only after prediction artifact immutability."""
    preparation = load_json(preparation_path)
    preregistration = load_json(preregistration_path)
    predictions = load_json(predictions_path)
    if predictions["preregistration_sha256"] != sha256_file(preregistration_path):
        raise DatasetError("Predictions do not refer to the current preregistration")
    if predictions.get("status") != "predictions-frozen-before-outcome-evaluation":
        raise DatasetError("Feeding predictions were not frozen before evaluation")
    labels_by_name = {
        str(item["source_type"]): bool(item["observed_positive"])
        for item in preparation["transfer_records"]
        if item["male_cns_body_ids"]
    }
    names = tuple(str(item["source_type"]) for item in preregistration["input_populations"])
    labels = np.asarray([labels_by_name[name] for name in names], dtype=np.bool_)
    metrics: dict[str, dict[str, Any]] = {}
    scores: dict[str, np.ndarray] = {}
    for run in predictions["runs"]:
        if tuple(run["population_names"]) != names:
            raise DatasetError(f"Population order changed in run {run['variant']}")
        rates = np.asarray(run["readout_rates_hz"], dtype=np.float64)
        bilateral_means = rates.mean(axis=1)
        run_scores = bilateral_means.min(axis=1)
        scores[str(run["variant"])] = run_scores
        metrics[str(run["variant"])] = {
            **_binary_metrics(labels, run_scores),
            "mean_bilateral_rates_hz": bilateral_means.tolist(),
            "finite_state": bool(run["finite_state"]),
            "runtime_seconds": float(run["runtime_seconds"]),
        }
    exact = metrics["exact"]
    gate = preregistration["transfer_protocol"]["stage1_pass_rule"]
    required_controls = tuple(str(value) for value in gate["required_controls"])
    control_margins = {
        name: float(exact["auroc"] - metrics[name]["auroc"])
        for name in required_controls
    }
    dt_name = f"dt-{preregistration['transfer_protocol']['timestep_sensitivity_ms']}-ms"
    primary_predictions = scores["exact"] > 0.0
    dt_predictions = scores[dt_name] > 0.0
    dt_agreement = float(np.mean(primary_predictions == dt_predictions))
    dt_auroc_delta = float(abs(exact["auroc"] - metrics[dt_name]["auroc"]))
    gates = {
        "exact_balanced_accuracy": exact["balanced_accuracy"]
        >= float(gate["minimum_exact_balanced_accuracy"]),
        "exact_auroc": exact["auroc"] >= float(gate["minimum_exact_auroc"]),
        "required_control_margins": all(
            value >= float(gate["minimum_auroc_margin_over_required_controls"])
            for value in control_margins.values()
        ),
        "timestep_prediction_agreement": dt_agreement
        >= float(gate["minimum_dt_prediction_agreement"]),
        "timestep_auroc_delta": dt_auroc_delta <= float(gate["maximum_dt_auroc_delta"]),
        "all_states_finite": bool(predictions["all_states_finite"]),
        "zero_weight_has_no_mn9_response": bool(np.all(scores["zero-weight"] == 0.0)),
        "predictions_frozen_before_outcomes": True,
    }
    passed = all(gates.values())
    blocking_reasons = [name for name, value in gates.items() if not value]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "passed" if passed else "failed",
        "experiment_id": preregistration["experiment_id"],
        "code_commit": _code_commit(),
        "preparation_sha256": sha256_file(preparation_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "predictions_sha256": sha256_file(predictions_path),
        "mapped_type_count": len(names),
        "metrics": metrics,
        "required_control_auroc_margins": control_margins,
        "timestep_sensitivity": {
            "prediction_agreement": dt_agreement,
            "auroc_delta": dt_auroc_delta,
        },
        "preregistered_gates": gates,
        "stage1_exit_gate_passed": passed,
        "blocking_reasons": blocking_reasons,
        "validation_review": (
            "selected-V3-circuit-evidence-passed"
            if passed
            else "selected-V3-circuit-evidence-failed"
        ),
        "validation_tier_awarded": None,
        "tier_reason": (
            "The repository's tier chain requires V1 and V2 before a V3 bundle; this "
            "experiment is reported as selected circuit evidence, not an awarded V3 tier."
        ),
    }
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot.resolve()),
    }
