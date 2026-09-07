# SPDX-License-Identifier: GPL-2.0-or-later
"""Stage 1 open-loop MaleCNS circuit benchmark orchestration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.circuit import (
    TransferLIFParameters,
    build_control_graph,
    compare_backend_runs,
    dataclass_payload,
    load_cell_types,
    load_population_ids,
    make_stimulus_schedule,
    parameters_from_experiment,
    run_brian2_circuit,
    run_genn_circuit,
    run_numpy_circuit,
    select_shortest_path_circuit,
)
from flysim.config import load_json, project_root, sha256_json
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.dynamics import DynamicsRegistry, edge_type_pair_keys
from flysim.errors import DatasetError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.shiu_reference import load_or_build_shiu_figure5g_reference


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _immutable_snapshot(path: Path) -> tuple[Path, str]:
    digest = sha256_file(path)
    snapshot = path.with_name(f"{path.stem}-{digest[:16]}{path.suffix}")
    if snapshot.exists():
        if sha256_file(snapshot) != digest:
            raise DatasetError(f"Immutable Stage 1 snapshot hash collision: {snapshot}")
    else:
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


def _population_resolution_status(path: Path) -> dict[str, str]:
    payload = load_json(path)
    return {str(item["id"]): str(item["status"]) for item in payload["populations"]}


def _save_or_validate_circuit(graph: SparseConnectome, output: Path) -> None:
    if output.exists():
        existing = SparseConnectome.load(output)
        if existing.source_sha256 != graph.source_sha256:
            raise DatasetError(f"A different circuit artifact already exists: {output}")
        return
    graph.save_directory(
        output,
        extra_manifest={
            "derivative": "directed-shortest-path-circuit",
            "canonical_graph_unchanged": True,
            "provenance": "M/P/E",
            "assumption_ids": ["DATA-03", "ND-03", "ND-04"],
        },
    )


def _summarize_control_rates(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[float]] = {}
    for record in records:
        rates = [float(value) for value in record["readout_rates_hz"]]
        by_variant.setdefault(str(record["variant"]), []).append(float(np.mean(rates)))
    return {
        variant: {
            "runs": len(values),
            "mean_readout_rate_hz": float(np.mean(values)),
            "std_readout_rate_hz": float(np.std(values)),
        }
        for variant, values in sorted(by_variant.items())
    }


def _compare_reference_curve(
    records: list[dict[str, Any]], reference: dict[str, Any]
) -> dict[str, Any]:
    exact = [item for item in records if item.get("variant") == "exact"]
    by_frequency: dict[float, list[float]] = {}
    for item in exact:
        frequency = float(item["frequency_hz"])
        by_frequency.setdefault(frequency, []).append(
            float(np.mean([float(value) for value in item["readout_rates_hz"]]))
        )
    published = {float(item["frequency_hz"]): item for item in reference["curve"]}
    overlap = sorted(set(by_frequency) & set(published))
    transfer_rates = np.asarray(
        [float(np.mean(by_frequency[frequency])) for frequency in overlap], dtype=np.float64
    )
    reference_rates = np.asarray(
        [float(published[frequency]["mean_rate_hz"]) for frequency in overlap],
        dtype=np.float64,
    )
    correlation: float | None = None
    if overlap and np.std(transfer_rates) > 0.0 and np.std(reference_rates) > 0.0:
        correlation = float(np.corrcoef(transfer_rates, reference_rates)[0, 1])
    return {
        "frequencies_hz": overlap,
        "male_cns_bilateral_mean_rates_hz": transfer_rates.tolist(),
        "flywire_abn1_mean_rates_hz": reference_rates.tolist(),
        "pearson_frequency_response": correlation,
        "interpretation": (
            "Cross-connectome simulation-to-simulation transfer only; this is not a held-out "
            "biological response or a V3 gate."
        ),
    }


def _curve_metrics(
    predicted_by_frequency: dict[float, float],
    reference_by_frequency: dict[float, float],
) -> dict[str, Any]:
    frequencies = sorted(set(predicted_by_frequency) & set(reference_by_frequency))
    predicted = np.asarray(
        [predicted_by_frequency[frequency] for frequency in frequencies], dtype=np.float64
    )
    reference = np.asarray(
        [reference_by_frequency[frequency] for frequency in frequencies], dtype=np.float64
    )
    errors = predicted - reference
    reference_positive = reference > 0.0
    predicted_positive_count = int(np.count_nonzero(predicted[reference_positive] > 0.0))
    reference_positive_count = int(np.count_nonzero(reference_positive))
    correlation: float | None = None
    if frequencies and np.std(predicted) > 0.0 and np.std(reference) > 0.0:
        correlation = float(np.corrcoef(predicted, reference)[0, 1])
    return {
        "frequencies_hz": frequencies,
        "predicted_mean_rates_hz": predicted.tolist(),
        "reference_mean_rates_hz": reference.tolist(),
        "rmse_hz": float(np.sqrt(np.mean(np.square(errors)))) if frequencies else None,
        "mae_hz": float(np.mean(np.abs(errors))) if frequencies else None,
        "pearson_frequency_response": correlation,
        "reference_positive_frequency_count": reference_positive_count,
        "predicted_positive_on_reference_positive_count": predicted_positive_count,
        "positive_response_coverage": (
            float(predicted_positive_count / reference_positive_count)
            if reference_positive_count
            else None
        ),
    }


def _fit_nd04_contact_scale(
    *,
    graph: SparseConnectome,
    edge_signs: np.ndarray,
    input_body_ids: tuple[int, ...],
    readout_body_ids: tuple[int, ...],
    parameters: TransferLIFParameters,
    seeds: tuple[int, ...],
    reference: dict[str, Any],
    fit_protocol: dict[str, Any],
) -> dict[str, Any]:
    candidates = tuple(float(value) for value in fit_protocol["candidate_values_mv_per_contact"])
    training = tuple(float(value) for value in fit_protocol["training_frequencies_hz"])
    held_out = tuple(float(value) for value in fit_protocol["held_out_frequencies_hz"])
    if not candidates or any(value <= 0.0 for value in candidates):
        raise DatasetError("ND-04 fit candidates must be a non-empty positive grid")
    if not training or not held_out or set(training) & set(held_out):
        raise DatasetError("ND-04 training and held-out frequency sets must be non-empty/disjoint")
    reference_rates = {
        float(item["frequency_hz"]): float(item["mean_rate_hz"])
        for item in reference["curve"]
    }
    missing = (set(training) | set(held_out)) - set(reference_rates)
    if missing:
        raise DatasetError(f"ND-04 fit frequencies absent from reference curve: {sorted(missing)}")

    schedules = {
        (frequency, seed): make_stimulus_schedule(
            graph,
            input_body_ids,
            frequency_hz=frequency,
            parameters=parameters,
            seed=seed,
        )
        for frequency in (*training, *held_out)
        for seed in seeds
    }

    def evaluate(scale: float, frequencies: tuple[float, ...]) -> dict[str, Any]:
        fitted_parameters = replace(parameters, synaptic_mv_per_contact=scale)
        predicted: dict[float, float] = {}
        seed_rates: dict[str, list[float]] = {}
        for frequency in frequencies:
            values = []
            for seed in seeds:
                result = run_numpy_circuit(
                    graph,
                    edge_signs,
                    schedules[(frequency, seed)],
                    fitted_parameters,
                    readout_body_ids,
                )
                values.append(float(np.mean(result.readout_rates_hz)))
            predicted[frequency] = float(np.mean(values))
            seed_rates[str(frequency)] = values
        return {
            **_curve_metrics(predicted, reference_rates),
            "seed_mean_readout_rates_hz": seed_rates,
        }

    candidate_results: list[dict[str, Any]] = []
    for scale in candidates:
        metrics = evaluate(scale, training)
        candidate_results.append(
            {
                "synaptic_mv_per_contact": scale,
                "training": metrics,
            }
        )
    winner = min(
        candidate_results,
        key=lambda item: (
            float(item["training"]["rmse_hz"]),
            float(item["synaptic_mv_per_contact"]),
        ),
    )
    fitted_scale = float(winner["synaptic_mv_per_contact"])
    return {
        "status": "completed",
        "assumption_id": "ND-04",
        "parameter": "synaptic_mv_per_contact",
        "units": "mV/contact",
        "provenance": "F/E",
        "objective": fit_protocol["objective"],
        "tie_break": fit_protocol["tie_break"],
        "candidate_results": candidate_results,
        "selected_value": fitted_scale,
        "training_metrics": winner["training"],
        "held_out_metrics": evaluate(fitted_scale, held_out),
        "frozen_before_held_out_evaluation": True,
        "claim_boundary": fit_protocol["claim_boundary"],
        "validation_tier_awarded": None,
    }


def run_shiu_malecns_transfer(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    population_resolution_path: Path,
    dynamics_registry_path: Path,
    output_path: Path,
    backends: tuple[str, ...],
    prepare_only: bool,
) -> dict[str, Any]:
    experiment = load_json(experiment_path)
    source_root = root / "raw" / "auxiliary" / "shiu-2024-brain-model"
    reference_output = (
        root / "evidence" / "male-cns-v1.0" / "shiu-figure5g-reference.json"
    )
    reference: dict[str, Any] | None = None
    if (source_root / "results.zip").is_file():
        reference = load_or_build_shiu_figure5g_reference(
            source_root=source_root,
            dataset_card_path=(
                project_root() / "configs" / "datasets" / "shiu-2024-brain-model.json"
            ),
            output_path=reference_output,
        )
    populations = load_population_ids(population_resolution_path)
    graph = SparseConnectome.load(graph_path)
    inputs = populations["shiu-jon-f-input"]
    readouts = populations["shiu-abn1-readout"]
    silencers = populations["shiu-inhibitory-control"]
    maximum_hops = int(experiment["transfer_protocol"]["maximum_path_hops"])
    selected = select_shortest_path_circuit(
        graph,
        inputs,
        readouts,
        maximum_hops=maximum_hops,
    )
    artifact_root = output_path.parent / f"{experiment['experiment_id']}-circuit"
    _save_or_validate_circuit(selected.graph, artifact_root)
    annotations = (
        root
        / "raw"
        / "male-cns-v1.0"
        / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    transmitters = (
        root
        / "raw"
        / "male-cns-v1.0"
        / "body-neurotransmitters-male-cns-v1.0.feather"
    )
    cell_types = load_cell_types(annotations, selected.graph.body_ids)
    dynamics_registry = DynamicsRegistry.load(dynamics_registry_path)
    dynamics_resolution = dynamics_registry.resolve(cell_types)
    type_pair_counts = Counter(edge_type_pair_keys(selected.graph, cell_types))
    parameters = parameters_from_experiment(experiment)
    population_status = _population_resolution_status(population_resolution_path)
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment["experiment_id"],
        "source_figure": experiment["source_figure"],
        "code_commit": _code_commit(),
        "experiment_path": str(experiment_path.resolve()),
        "experiment_sha256": sha256_file(experiment_path),
        "experiment_logical_sha256": sha256_json(experiment),
        "population_resolution_path": str(population_resolution_path.resolve()),
        "population_resolution_sha256": sha256_file(population_resolution_path),
        "population_status": population_status,
        "selection": selected.as_dict(),
        "circuit_artifact": str(artifact_root.resolve()),
        "circuit_sha256": selected.graph.source_sha256,
        "cell_type_counts": {
            value or "untyped": cell_types.count(value) for value in sorted(set(cell_types))
        },
        "dynamics_registry_path": str(dynamics_registry_path.resolve()),
        "dynamics_registry_file_sha256": sha256_file(dynamics_registry_path),
        "dynamics_resolution": dynamics_resolution.as_dict(),
        "type_pair_edge_counts": dict(sorted(type_pair_counts.items())),
        "typed_dynamics_execution": {
            "status": "registry-resolved-not-enabled",
            "reason": (
                "The Stage 1 regression remains the source-faithful LIF baseline. "
                "Hybrid spiking/graded execution and fitted type-pair scales require "
                "independent training and validation evidence."
            ),
            "validation_tier_awarded": None,
        },
        "parameters": dataclass_payload(parameters),
        "assumption_ids": experiment["assumption_ids"],
        "provenance": experiment["provenance"],
        "claim_boundary": experiment["claim_boundary"],
        "reference_crosswalk": experiment["crosswalk"],
        "published_reference": (
            {
                "status": reference["status"],
                "path": reference["output"],
                "sha256": reference["sha256"],
                "reproduction_boundary": reference["reproduction_boundary"],
            }
            if reference is not None
            else {
                "status": "acquisition-pending",
                "reason": "Checksum-locked results.zip is not yet available",
            }
        ),
        "silencing_control": {
            "status": "available" if silencers else "unavailable",
            "male_cns_body_ids": list(silencers),
            "reason": (
                None
                if silencers
                else "CB0496 has no MaleCNS v1.0 annotation match; no substitute was guessed"
            ),
        },
        "validation_tier_awarded": None,
    }
    if prepare_only:
        base["status"] = "prepared"
        base["runs"] = []
        _atomic_json(output_path, base)
        return {**base, "output": str(output_path.resolve()), "sha256": sha256_file(output_path)}

    protocol = experiment["transfer_protocol"]
    controls = tuple(str(value) for value in protocol["controls"])
    frequencies = tuple(float(value) for value in protocol["frequencies_hz"])
    seeds = tuple(int(value) for value in protocol["seeds"])
    weak_edge_max = int(protocol["weak_edge_max_contacts"])
    control_runs: list[dict[str, Any]] = []
    exact_by_key: dict[tuple[float, int], Any] = {}
    for variant in controls:
        if variant == "silenced-cb0496" and not silencers:
            control_runs.append(
                {
                    "variant": variant,
                    "status": "unavailable",
                    "reason": "No mapped MaleCNS CB0496 body IDs",
                }
            )
            continue
        control_graph = build_control_graph(
            selected.graph,
            variant,
            cell_types=cell_types,
            seed=seeds[0],
            weak_edge_max_contacts=weak_edge_max,
            silenced_body_ids=silencers,
        )
        sign_result = build_shiu_regression_signs(
            control_graph,
            transmitters,
            unresolved_policy=UnresolvedSignPolicy.ZERO,
            seed=seeds[0],
        )
        for frequency in frequencies:
            for seed in seeds:
                schedule = make_stimulus_schedule(
                    control_graph,
                    selected.input_body_ids,
                    frequency_hz=frequency,
                    parameters=parameters,
                    seed=seed,
                )
                result = run_numpy_circuit(
                    control_graph,
                    sign_result.edge_signs,
                    schedule,
                    parameters,
                    selected.readout_body_ids,
                )
                if variant == "exact":
                    exact_by_key[(frequency, seed)] = result
                control_runs.append(
                    {
                        "variant": variant,
                        "status": "completed",
                        "frequency_hz": frequency,
                        "seed": seed,
                        "graph_sha256": control_graph.source_sha256,
                        "neurons": control_graph.neuron_count,
                        "edges": control_graph.edge_count,
                        **result.as_dict(
                            control_graph,
                            np.asarray(
                                [
                                    control_graph.dense_index(body_id)
                                    for body_id in selected.readout_body_ids
                                ],
                                dtype=np.uint32,
                            ),
                        ),
                    }
                )

    comparison_frequency = 100.0 if 100.0 in frequencies else frequencies[0]
    comparison_seed = seeds[0]
    exact_graph = selected.graph
    exact_signs = build_shiu_regression_signs(
        exact_graph,
        transmitters,
        unresolved_policy=UnresolvedSignPolicy.ZERO,
        seed=comparison_seed,
    ).edge_signs
    comparison_schedule = make_stimulus_schedule(
        exact_graph,
        selected.input_body_ids,
        frequency_hz=comparison_frequency,
        parameters=parameters,
        seed=comparison_seed,
    )
    backend_runs: dict[str, Any] = {}
    numpy_run = exact_by_key[(comparison_frequency, comparison_seed)]
    readout_indices = np.asarray(
        [exact_graph.dense_index(body_id) for body_id in selected.readout_body_ids],
        dtype=np.uint32,
    )
    backend_runs["numpy"] = numpy_run.as_dict(
        exact_graph, readout_indices, include_trace=True
    )
    comparisons: list[dict[str, Any]] = []
    if "brian2" in backends:
        brian2_run = run_brian2_circuit(
            exact_graph,
            exact_signs,
            comparison_schedule,
            parameters,
            selected.readout_body_ids,
        )
        backend_runs["brian2"] = brian2_run.as_dict(
            exact_graph, readout_indices, include_trace=True
        )
        comparisons.append(
            compare_backend_runs(
                numpy_run,
                brian2_run,
                spike_time_tolerance_ms=float(protocol["backend_spike_time_tolerance_ms"]),
                rate_relative_tolerance=float(protocol["backend_rate_relative_tolerance"]),
            )
        )
    if "genn" in backends:
        genn_run = run_genn_circuit(
            exact_graph,
            exact_signs,
            comparison_schedule,
            parameters,
            selected.readout_body_ids,
            root / "cache" / "genn" / "stage1" / str(experiment["experiment_id"]),
        )
        backend_runs["genn"] = genn_run.as_dict(
            exact_graph, readout_indices, include_trace=True
        )
        comparisons.append(
            compare_backend_runs(
                numpy_run,
                genn_run,
                spike_time_tolerance_ms=float(protocol["backend_spike_time_tolerance_ms"]),
                rate_relative_tolerance=float(protocol["backend_rate_relative_tolerance"]),
            )
        )

    sign_controls: list[dict[str, Any]] = []
    for policy in UnresolvedSignPolicy:
        sign_result = build_shiu_regression_signs(
            exact_graph,
            transmitters,
            unresolved_policy=policy,
            seed=comparison_seed,
        )
        result = run_numpy_circuit(
            exact_graph,
            sign_result.edge_signs,
            comparison_schedule,
            parameters,
            selected.readout_body_ids,
        )
        sign_controls.append(
            {
                "policy": policy.value,
                "known_neurons": sign_result.known_neurons,
                "unresolved_neurons": sign_result.unresolved_neurons,
                **result.as_dict(exact_graph, readout_indices),
            }
        )

    backend_parity_passed = (
        all(bool(item["passed"]) for item in comparisons) if comparisons else None
    )
    fit_protocol = protocol.get("nd04_contact_scale_fit")
    contact_scale_fit: dict[str, Any] | None = None
    if fit_protocol is not None:
        if reference is None:
            contact_scale_fit = {
                "status": "blocked",
                "reason": "Checksum-locked published-output reference is unavailable",
                "validation_tier_awarded": None,
            }
        elif backend_parity_passed is not True:
            contact_scale_fit = {
                "status": "blocked",
                "reason": "Numerical backend parity must pass before ND-04 fitting",
                "validation_tier_awarded": None,
            }
        else:
            contact_scale_fit = _fit_nd04_contact_scale(
                graph=exact_graph,
                edge_signs=exact_signs,
                input_body_ids=selected.input_body_ids,
                readout_body_ids=selected.readout_body_ids,
                parameters=parameters,
                seeds=seeds,
                reference=reference,
                fit_protocol=fit_protocol,
            )

    completed_control_variants = {
        str(item["variant"])
        for item in control_runs
        if item.get("status") == "completed"
    }
    required_structural_controls = {
        "cell-type-only",
        "shuffled-connectivity",
        "uniform-weights",
        "randomized-weights",
        "weak-edge-dropout",
    }
    held_out_coverage = (
        contact_scale_fit.get("held_out_metrics", {}).get("positive_response_coverage")
        if contact_scale_fit is not None
        else None
    )
    stage1_gate_assessment = {
        "numerical_backend_parity": backend_parity_passed,
        "all_11_reference_frequencies_executed": len(frequencies) == 11,
        "required_structural_controls_completed": required_structural_controls
        <= completed_control_variants,
        "held_out_positive_response_coverage": held_out_coverage,
        "transferred_causal_silencing_control": "available" if silencers else "unavailable",
        "independent_biological_experiment": "pending",
        "stage1_exit_gate_passed": False,
        "blocking_reasons": [
            "The one-parameter ND-04 fit does not generalize across held-out frequencies.",
            "The mapped CB0496 silencing population is unavailable in MaleCNS v1.0.",
            "This reference is archived FlyWire simulation output, not biological response data.",
            "A second independent biologically anchored circuit experiment is pending.",
        ],
        "validation_tier_awarded": None,
    }

    base.update(
        {
            "status": "completed",
            "control_runs": control_runs,
            "control_summary": _summarize_control_rates(
                [item for item in control_runs if item.get("status") == "completed"]
            ),
            "backend_comparison_condition": {
                "variant": "exact",
                "frequency_hz": comparison_frequency,
                "seed": comparison_seed,
            },
            "backend_runs": backend_runs,
            "backend_comparisons": comparisons,
            "backend_parity_passed": backend_parity_passed,
            "sign_controls": sign_controls,
            "reference_comparison": (
                _compare_reference_curve(control_runs, reference)
                if reference is not None
                else None
            ),
            "nd04_contact_scale_fit": contact_scale_fit,
            "stage1_gate_assessment": stage1_gate_assessment,
        }
    )
    _atomic_json(output_path, base)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **base,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot.resolve()),
    }
