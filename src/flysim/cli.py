# SPDX-License-Identifier: GPL-2.0-or-later
"""Stable command-line surface for agents and human operators."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flysim.benchmark import estimate_sparse_memory
from flysim.bilateral import run_bilateral_symmetry
from flysim.completeness import run_completeness_correction
from flysim.config import project_root
from flysim.connectome import (
    SparseConnectome,
    graph_array_hashes,
    import_aggregate_graph,
    verify_graph_array_hashes,
)
from flysim.contacts import (
    audit_contact_derivatives,
    compare_contact_derivatives,
    import_contact_table,
)
from flysim.convergence import run_orn_pn_convergence
from flysim.datasets import (
    DatasetSpec,
    dataset_status,
    default_data_root,
    sync_dataset,
    validate_dataset,
)
from flysim.errors import FlySimError, ReadinessError, ValidationError
from flysim.evidence import (
    ValidationTier,
    build_evidence_bundle,
    resolve_supported_tier,
    validate_evidence_bundle,
)
from flysim.factory import build_reference_demo, build_track_a_demo
from flysim.feeding_stage1 import (
    evaluate_feeding_screen,
    execute_feeding_screen,
    preregister_feeding_screen,
)
from flysim.glomerular import run_glomerular_volume_scaling
from flysim.grooming import import_grooming_trajectory
from flysim.morphology import sync_morphology_canaries
from flysim.polarity import UnresolvedSignPolicy, write_edge_sign_variant
from flysim.populations import resolve_populations
from flysim.provenance import AssumptionRegistry
from flysim.render import render_run
from flysim.runs import (
    attach_run_artifact,
    git_metadata,
    require_clean_worktree,
    write_run,
)
from flysim.shiu_feeding import prepare_shiu_feeding_screen
from flysim.stage1 import run_shiu_malecns_transfer
from flysim.stage2 import (
    GOUWENS_MODELDB_COMMIT,
    NANAMI_REPOSITORY_COMMIT,
    Stage2ExperimentSpec,
    build_projection_neuron_ensemble,
    evaluate_dynamic_projection_neuron_holdout,
    fit_dynamic_projection_neuron_model,
    fit_projection_neuron_model,
    import_gouwens_dm1_priors,
    import_gugel_figure7,
    import_invivo_cellular_pack,
    import_nanami_pn_trace,
    measure_invivo_cellular_pack,
    review_dynamic_projection_neuron_timestep,
    review_projection_neuron_fit,
)
from flysim.structural import audit_structural_references
from flysim.synaptic import (
    analyse_synaptic_structure,
    compare_uepsc_kernel_families,
    evaluate_stage2_exit_gate,
    evaluate_uepsc_kinetics_holdout,
    fit_uepsc_prior,
)
from flysim.universes import audit_body_universes
from flysim.v0 import CONTACT_CHECKS as V0_CONTACT_CHECKS
from flysim.v0 import build_v0_evidence_bundle
from flysim.validation import validate_run
from flysim.widened import run_widened_grooming_transfer


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _progress_jsonl(message: str) -> None:
    print(json.dumps({"event": "progress", "message": message}), file=sys.stderr, flush=True)


def _default_dataset_spec() -> Path:
    return project_root() / "configs" / "datasets" / "malecns-v1.0.json"


def _default_assumptions() -> Path:
    return project_root() / "configs" / "assumptions.json"


def _command_data_sync(args: argparse.Namespace) -> int:
    spec = DatasetSpec.load(args.spec)
    lock = sync_dataset(
        spec=spec,
        root=args.root,
        profile=args.profile,
        minimum_free_gb=args.minimum_free_gb,
        progress=_progress_jsonl,
    )
    _print_json(lock)
    return 0


def _command_data_validate(args: argparse.Namespace) -> int:
    spec = DatasetSpec.load(args.spec)
    results = validate_dataset(
        spec, args.root, args.profile, remote=args.remote, deep=args.deep
    )
    _print_json({"dataset_id": spec.dataset_id, "artifacts": results})
    return 0 if all(item["status"] == "ok" for item in results) else 2


def _command_data_status(args: argparse.Namespace) -> int:
    spec = DatasetSpec.load(args.spec)
    _print_json(dataset_status(spec, args.root, args.profile))
    return 0


def _command_data_import_dm1_priors(args: argparse.Namespace) -> int:
    payload = import_gouwens_dm1_priors(
        args.source,
        args.output,
        expected_commit=args.expected_commit,
    )
    _print_json(
        {
            "artifact_id": payload["artifact_id"],
            "output": str(args.output.resolve()),
            "record_count": payload["record_count"],
            "logical_sha256": payload["logical_sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_data_import_gugel_figure7(args: argparse.Namespace) -> int:
    payload = import_gugel_figure7(args.source, args.output)
    _print_json(
        {
            "artifact_id": payload["artifact_id"],
            "output": str(args.output.resolve()),
            "artifacts": payload["artifacts"],
            "logical_sha256": payload["logical_sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_data_import_nanami_pn(args: argparse.Namespace) -> int:
    payload = import_nanami_pn_trace(
        args.source,
        args.output,
        expected_commit=args.expected_commit,
    )
    _print_json(
        {
            "artifact_id": payload["artifact_id"],
            "output": str(args.output.resolve()),
            "source_commit": payload["source_commit"],
            "normalized_artifact": payload["normalized_artifact"],
            "logical_sha256": payload["logical_sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_stage2_import_invivo_pack(args: argparse.Namespace) -> int:
    manifest = import_invivo_cellular_pack(args.config, args.source, args.output)
    _print_json(
        {
            "artifact_id": manifest["artifact_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": manifest["logical_sha256"],
            "verified_source_artifact_count": manifest["verified_source_artifact_count"],
            "normalized_artifacts": manifest["normalized_artifacts"],
            "stimulus_resolution": manifest["stimulus_resolution"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_stage2_measure_cellular(args: argparse.Namespace) -> int:
    result = measure_invivo_cellular_pack(args.contract, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "unit_resolved_summary": result["unit_resolved"]["by_prominence_mv"][
                f"{result['spike_detection_primary']['prominence_mv']:g}"
            ]["summary"],
            "signalling_evidence": result["signalling_evidence"],
            "sealed_pn_challenge": result["sealed_pn_challenge"],
            "v1_coverage": result["v1_coverage"],
            "artifact_validity": result["artifact_validity"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if all(result["artifact_validity"].values()) else 2


def _command_stage2_exit_gate(args: argparse.Namespace) -> int:
    result = evaluate_stage2_exit_gate(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "legs": [
                {
                    "id": leg["id"],
                    "observed_value": leg["observed_value"],
                    "criterion": leg["criterion"],
                    "passed": leg["passed"],
                }
                for leg in result["legs"]
            ],
            "legs_failed": result["legs_failed"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if result["acceptance"]["stage2_exit_gate_passed"] else 2


def _command_stage2_synaptic_structure(args: argparse.Namespace) -> int:
    result = analyse_synaptic_structure(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "glomeruli_resolved": result["glomeruli_resolved"],
            "projection_neurons_profiled": result["projection_neurons_profiled"],
            "hypotheses": result["hypotheses"],
            "derived_per_contact_scale_mv": {
                key: value
                for key, value in result["derived_per_contact_scale_mv"].items()
                if key != "per_glomerulus"
            },
            "artifact_validity": result["artifact_validity"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if all(result["artifact_validity"].values()) else 2


def _command_stage2_uepsc_holdout(args: argparse.Namespace) -> int:
    result = evaluate_uepsc_kinetics_holdout(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "gated": result["gated"],
            "reported_not_gated": result["reported_not_gated"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if result["acceptance"]["v2_kinetics_subgate_pass"] else 2


def _command_stage2_uepsc_kernel_family(args: argparse.Namespace) -> int:
    result = compare_uepsc_kernel_families(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "direct_peak_amplitude_pa": {
                key: result["direct_peak_amplitude_pa"][key]
                for key in ("mean", "median", "sem")
            },
            "single_component": {
                key: result["single_component"][key]
                for key in (
                    "onset_ms",
                    "rise_tau_ms",
                    "decay_tau_ms",
                    "kernel_half_decay_ms",
                    "population_amplitude_pa",
                    "training_huber_pa2",
                )
            },
            "two_component": {
                key: result["two_component"][key]
                for key in (
                    "onset_ms",
                    "rise_tau_ms",
                    "fast_decay_tau_ms",
                    "slow_decay_tau_ms",
                    "fast_fraction",
                    "kernel_half_decay_ms",
                    "population_amplitude_pa",
                    "training_huber_pa2",
                    "continuous_parameter_at_search_boundary",
                )
            },
            "hypotheses": result["hypotheses"],
            "hypotheses_descriptive": result["hypotheses_descriptive"],
            "output": result["output"],
            "sha256": result["sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_stage2_uepsc_prior(args: argparse.Namespace) -> int:
    result = fit_uepsc_prior(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "kernel": result["kernel"],
            "against_published_half_decay": result["against_published_half_decay"],
            "against_frozen_fit": result["against_frozen_fit"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_benchmark_glomerular_volume(args: argparse.Namespace) -> int:
    result = run_glomerular_volume_scaling(
        root=args.root,
        graph_path=args.graph,
        experiment_path=args.experiment,
        output_path=args.output,
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "glomeruli_scored": result["glomeruli_scored"],
            "rarefaction": result["rarefaction"],
            "hypotheses": result["hypotheses"],
            "hypotheses_descriptive": result["hypotheses_descriptive"],
            "output": result["output"],
            "sha256": result["sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_track_a_station_validation(args: argparse.Namespace) -> int:
    from flysim.station_validation import run_station_keeping_validation

    result = run_station_keeping_validation(
        root=args.root,
        experiment_path=args.experiment,
        output_path=args.output,
        registry_path=args.assumptions,
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "result_id": result["result_id"],
            "poses_scored": result["poses_scored"],
            "poses_rejected_by_dust_guard": result["poses_rejected_by_dust_guard"],
            "acceptance": result["acceptance"],
            "v4_b3_diagnostic": result["v4_b3_diagnostic"],
            "by_pose": result["by_pose"],
            "output": result["output"],
            "sha256": result["sha256"],
            "code_commit": result["code_commit"],
        }
    )
    return 0


def _command_benchmark_bilateral_symmetry(args: argparse.Namespace) -> int:
    result = run_bilateral_symmetry(
        root=args.root,
        graph_path=args.graph,
        experiment_path=args.experiment,
        output_path=args.output,
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "glomeruli_with_both_sides": result["glomeruli_with_both_sides"],
            "projection_neurons": result["projection_neurons"],
            "hypotheses": result["hypotheses"],
            "output": result["output"],
            "sha256": result["sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_benchmark_completeness_correction(args: argparse.Namespace) -> int:
    result = run_completeness_correction(
        root=args.root,
        graph_path=args.graph,
        experiment_path=args.experiment,
        output_path=args.output,
        convergence_artifact=args.convergence_artifact,
        volume_artifact=args.volume_artifact,
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "glomeruli_scored": result["glomeruli_scored"],
            "registered_survival": result["registered_survival"],
            "hypotheses": result["hypotheses"],
            "survival_sensitivity": result["survival_sensitivity"],
            "output": result["output"],
            "sha256": result["sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_benchmark_orn_pn_convergence(args: argparse.Namespace) -> int:
    result = run_orn_pn_convergence(
        root=args.root,
        graph_path=args.graph,
        experiment_path=args.experiment,
        output_path=args.output,
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "glomeruli_tested": result["glomeruli_tested"],
            "totals": result["totals"],
            "completeness_distribution": result["completeness_distribution"],
            "hypotheses": result["hypotheses"],
            "hypotheses_descriptive": result["hypotheses_descriptive"],
            "output": result["output"],
            "sha256": result["sha256"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_benchmark_widened_circuit(args: argparse.Namespace) -> int:
    population_path = args.populations or (
        args.root / "derived" / "male-cns-v1.0" / "shiu-antennal-grooming-populations.json"
    )
    result = run_widened_grooming_transfer(
        root=args.root,
        graph_path=args.graph,
        experiment_path=args.experiment,
        population_resolution_path=population_path,
        output_path=args.output,
        backends=tuple(args.backend),
        allow_dirty_tree=args.allow_dirty_tree,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "by_path_length": [
                {
                    "maximum_path_length": block["maximum_path_length"],
                    "neurons": block["selection"]["neurons"],
                    "edges": block["selection"]["edges"],
                    "inhibition": block["inhibition"],
                    "backend_parity_passed": block["backend_parity_passed"],
                    "hypotheses": block["hypotheses"],
                }
                for block in result["by_path_length"]
            ],
            "output": result["output"],
            "sha256": result["sha256"],
            "immutable_snapshot": result["immutable_snapshot"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_stage2_pn_ensemble(args: argparse.Namespace) -> int:
    result = build_projection_neuron_ensemble(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "accepted_candidate_count": result["accepted_candidate_count"],
            "ensemble": {
                "parameter_samples": result["ensemble"]["parameter_samples"],
                "seeds_per_condition": result["ensemble"]["seeds_per_condition"],
                "member_count": result["ensemble"]["member_count"],
            },
            "parameter_uncertainty": result["parameter_uncertainty"],
            "training_diagnostics": result["training_diagnostics"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    required = (
        "meets_val01_parameter_samples",
        "meets_val01_seeds_per_condition",
        "all_predictions_finite",
        "no_forbidden_specimen_read",
    )
    return 0 if all(result["acceptance"][key] for key in required) else 2


def _command_stage2_readiness(args: argparse.Namespace) -> int:
    report = Stage2ExperimentSpec.load(args.experiment).readiness(args.root)
    _print_json(report)
    return 0 if report["fit_ready"] else 2


def _command_stage2_fit_pn(args: argparse.Namespace) -> int:
    result = fit_projection_neuron_model(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "acceptance": result["acceptance"],
            "fi_model": result["fi_model"],
            "uepsc_model": result["uepsc_model"],
            "validation_tier_awarded": None,
        }
    )
    required = (
        "fi_pass",
        "uepsc_pass",
        "all_states_finite",
        "no_continuous_fit_at_search_boundary",
    )
    return 0 if all(result["acceptance"][key] for key in required) else 2


def _command_stage2_fit_pn_dynamic(args: argparse.Namespace) -> int:
    result = fit_dynamic_projection_neuron_model(args.experiment, args.root, args.output)
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "family": result["family"],
            "parameter_distribution": result["parameter_distribution"],
            "training": result["training"],
            "external_evaluation_pending": True,
            "validation_tier_awarded": None,
        }
    )
    required = ("all_states_finite", "dynamic_improves_training_rmse")
    return 0 if all(result["acceptance"][key] for key in required) else 2


def _command_stage2_evaluate_pn_dynamic(args: argparse.Namespace) -> int:
    result = evaluate_dynamic_projection_neuron_holdout(
        args.evaluation, args.root, args.output
    )
    _print_json(
        {
            "result_id": result["result_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "metrics": result["metrics"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if result["acceptance"]["cellular_fi_subgate_pass"] else 2


def _command_stage2_review_pn_dynamic_timestep(args: argparse.Namespace) -> int:
    result = review_dynamic_projection_neuron_timestep(
        args.review, args.root, args.output
    )
    _print_json(
        {
            "review_id": result["review_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": result["logical_sha256"],
            "reference": result["reference"],
            "sensitivity": result["sensitivity"],
            "acceptance": result["acceptance"],
            "validation_tier_awarded": None,
        }
    )
    return 0 if result["acceptance"]["numerical_sensitivity_pass"] else 2


def _command_stage2_review_pn(args: argparse.Namespace) -> int:
    review = review_projection_neuron_fit(
        args.fit_result,
        args.root,
        args.output,
        expected_fit_sha256=args.expected_fit_sha256,
    )
    _print_json(
        {
            "review_id": review["review_id"],
            "output": str(args.output.resolve()),
            "logical_sha256": review["logical_sha256"],
            "parameters_changed": review["parameters_changed"],
            "model_features": review["model_features"],
            "feature_errors": review["feature_errors"],
            "v2_coverage": review["v2_coverage"],
            "tier_blockers": review["tier_blockers"],
            "validation_tier_awarded": None,
        }
    )
    return 0


def _command_evidence_build(args: argparse.Namespace) -> int:
    tier = ValidationTier(args.tier)
    if tier is ValidationTier.V0:
        if args.artifact or args.gate:
            raise ValidationError(
                "V0 gates are evidence-derived; omit --artifact/--gate and use --root/--spec"
            )
        bundle = build_v0_evidence_bundle(args.root, args.spec, args.output)
    else:
        bundle = build_evidence_bundle(tier, args.output, tuple(args.artifact), tuple(args.gate))
    _print_json(
        {
            "bundle_id": bundle.bundle_id,
            "tier": bundle.tier.value,
            "path": str(bundle.path),
            "sha256": bundle.sha256,
            "artifact_count": len(bundle.artifacts),
        }
    )
    return 0


def _command_evidence_validate(args: argparse.Namespace) -> int:
    result = validate_evidence_bundle(args.bundle)
    _print_json(result)
    return 0 if result["valid"] else 2


def _command_evidence_build_v0(args: argparse.Namespace) -> int:
    # A bundle pins repository files, so the code and documents it attests to must be
    # recoverable from git.
    git_state = (
        {**git_metadata(), "clean_worktree_check_waived": True}
        if args.allow_dirty_tree
        else require_clean_worktree("Building a V0 evidence bundle")
    )
    bundle = build_v0_evidence_bundle(args.root, args.spec, args.output)
    _print_json(
        {
            "bundle_id": bundle.bundle_id,
            "tier": bundle.tier.value,
            "path": str(bundle.path),
            "sha256": bundle.sha256,
            "artifact_count": len(bundle.artifacts),
            "git": git_state,
            "validation": validate_evidence_bundle(bundle.path),
        }
    )
    return 0


def _command_data_import(args: argparse.Namespace) -> int:
    source = args.source or (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
    )
    output = args.output or args.root / "derived" / "male-cns-v1.0" / "graph"
    annotations = args.annotations or (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    graph = import_aggregate_graph(
        source,
        output,
        body_ids_source=annotations,
        body_statuses=tuple(args.status or ["Traced"]),
    )
    _print_json(
        {
            "output": str(output.resolve()),
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
            "source_sha256": graph.source_sha256,
            "threshold_applied": False,
        }
    )
    return 0


def _command_data_resolve_populations(args: argparse.Namespace) -> int:
    annotations = args.annotations or (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    output = args.output or (
        args.root / "derived" / "male-cns-v1.0" / "population-resolution.json"
    )
    payload = resolve_populations(annotations, args.registry, output)
    _print_json(
        {
            "output": str(output.resolve()),
            "all_required_resolved": payload["all_required_resolved"],
            "populations": [
                {
                    "id": item["id"],
                    "status": item["status"],
                    "body_id_count": len(item["body_ids"]),
                }
                for item in payload["populations"]
            ],
        }
    )
    return 0 if payload["all_required_resolved"] else 2


def _command_data_import_grooming(args: argparse.Namespace) -> int:
    source = args.source or (
        args.root
        / "raw"
        / "auxiliary"
        / "ozdil-2026-antennal-grooming"
        / "Fig1_panelC.pkl"
    )
    output = args.output or (
        args.root
        / "derived"
        / "auxiliary"
        / "ozdil-2026-antennal-grooming"
        / "track-a-grooming-trajectory.npz"
    )
    payload = import_grooming_trajectory(source, output)
    _print_json(payload)
    return 0


def _command_data_build_edge_signs(args: argparse.Namespace) -> int:
    graph = SparseConnectome.load(args.graph)
    source = args.transmitters or (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "body-neurotransmitters-male-cns-v1.0.feather"
    )
    payload = write_edge_sign_variant(
        graph,
        source,
        args.output,
        unresolved_policy=UnresolvedSignPolicy(args.unresolved_policy),
        seed=args.seed,
    )
    _print_json(payload)
    return 0


def _command_data_import_contacts(args: argparse.Namespace) -> int:
    spec = DatasetSpec.load(args.spec)
    status = dataset_status(spec, args.root, "full")
    if not status["complete"]:
        pending = [item["id"] for item in status["artifacts"] if item["state"] != "locked"]
        raise ReadinessError(f"Full-profile lock is incomplete; pending: {pending}")
    raw_directory = args.root / "raw" / spec.dataset_id.replace(":", "-")
    lock_path = raw_directory / "dataset-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    output_root = args.output_root or (
        args.root / "derived" / "male-cns-v1.0" / "contacts"
    )
    contact_artifact_ids = {
        "syn-points",
        "syn-partners",
        "tbar-neurotransmitters",
        "connectome-weights",
    }
    selected_artifact_ids = set(args.artifact or contact_artifact_ids)
    results: list[dict[str, Any]] = []
    for artifact in spec.artifacts:
        if artifact.id not in selected_artifact_ids:
            continue
        _progress_jsonl(f"normalizing {artifact.id}")
        result = import_contact_table(
            artifact.id,
            raw_directory / artifact.filename,
            output_root / artifact.id,
            resume=args.resume,
            memory_limit_gb=args.memory_limit_gb,
            minimum_free_gb=args.minimum_free_gb,
            row_group_rows=args.row_group_rows,
            shard_rows=args.shard_rows,
            max_new_shards_per_process=args.max_new_shards_per_process,
            expected_sha256=lock["artifacts"][artifact.id]["sha256"],
            progress=_progress_jsonl,
        )
        results.append(result.as_dict())
    _print_json(
        {
            "schema_version": "1.0",
            "dataset_id": spec.dataset_id,
            # Normalization is a single-threaded PyArrow IPC stream with no temporary
            # storage. The DuckDB --threads and --temporary-storage knobs belong to
            # `data audit-contacts`; recording them here implied they were applied.
            "normalization_backend": "pyarrow-ipc-stream",
            "results": results,
        }
    )
    return 0


def _command_data_verify_contact_rebuild(args: argparse.Namespace) -> int:
    report = compare_contact_derivatives(
        args.left,
        args.right,
        args.output,
        scan_batch_rows=args.scan_batch_rows,
    )
    _print_json(report)
    return 0 if report["valid"] else 2


def _command_data_audit_contacts(args: argparse.Namespace) -> int:
    contacts_root = args.root / "derived" / "male-cns-v1.0" / "contacts"
    report_path = args.output or (
        args.root / "evidence" / "male-cns-v1.0" / "contact-structural-audit.json"
    )
    report = audit_contact_derivatives(
        contacts_root,
        report_path,
        args.temporary_storage,
        memory_limit_gb=args.memory_limit_gb,
        threads=args.threads,
        progress=_progress_jsonl,
    )
    strict_failures: list[str] = []
    if args.strict:
        # --strict used to be accepted and ignored while the README and the foundation
        # supervisor both relied on it. It now requires every registered V0 contact check
        # to be present and passing, not merely an absent overall failure.
        checks = report.get("checks", {})
        for name in V0_CONTACT_CHECKS:
            if name not in checks:
                strict_failures.append(f"required contact check did not run: {name}")
            elif checks[name].get("passed") is not True:
                strict_failures.append(f"required contact check failed: {name}")
    _print_json(
        {
            **report,
            "report": str(report_path.resolve()),
            "strict": bool(args.strict),
            "strict_failures": strict_failures,
        }
    )
    return 0 if report["valid"] and not strict_failures else 2


def _command_data_sync_skeleton_canaries(args: argparse.Namespace) -> int:
    output = args.output or (
        args.root / "derived" / "male-cns-v1.0" / "morphology-canaries"
    )
    result = sync_morphology_canaries(args.config, output)
    _print_json(result)
    return 0 if result["complete"] else 2


def _command_data_audit_body_universes(args: argparse.Namespace) -> int:
    raw = args.root / "raw" / "male-cns-v1.0"
    annotations = raw / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    aggregate = raw / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
    output = args.output or (
        args.root / "evidence" / "male-cns-v1.0" / "body-universe-sensitivity.json"
    )
    result = audit_body_universes(
        annotations,
        aggregate,
        output,
        canary_body_ids=(10442, 10760, 523769, 10360, 127912, 26519, 10331, 16949),
    )
    _print_json(result)
    return 0


def _command_data_audit_structural_references(args: argparse.Namespace) -> int:
    output = args.output or (
        args.root / "evidence" / "male-cns-v1.0" / "structural-reference-audit.json"
    )
    result = audit_structural_references(
        args.root,
        args.supplement_card,
        args.canary_config,
        output,
    )
    _print_json(result)
    return 0 if result["valid"] else 2


def _command_benchmark(args: argparse.Namespace) -> int:
    if args.parity:
        command = [
            sys.executable,
            str(project_root() / "scripts" / "validate_lif_parity.py"),
        ]
        if args.output is not None:
            command.extend(("--output", str(args.output)))
        if args.build_root is not None:
            command.extend(("--build-path", str(args.build_root)))
        return subprocess.run(command, check=False).returncode
    if args.genn:
        if args.graph is None:
            raise ReadinessError("--genn requires --graph")
        command = [
            sys.executable,
            str(project_root() / "scripts" / "benchmark_genn_graph.py"),
            "--graph",
            str(args.graph),
            "--scales",
            *(str(scale) for scale in args.scales),
            "--seed",
            str(args.seed),
        ]
        if args.output is not None:
            command.extend(("--output", str(args.output)))
        if args.build_root is not None:
            command.extend(("--build-root", str(args.build_root)))
        return subprocess.run(command, check=False).returncode
    registry = AssumptionRegistry.load(args.assumptions)
    graph = SparseConnectome.load(args.graph) if args.graph else None
    estimates = estimate_sparse_memory(
        tuple(args.scales), registry.value_map("BENCH-01"), graph=graph
    )
    _print_json(
        {
            "backend": "dry-run-memory-estimate",
            "provenance": "M/E" if graph is None else "M/E from imported graph counts",
            "graph": str(args.graph.resolve()) if args.graph else None,
            "estimates": [item.as_dict() for item in estimates],
            "warning": (
                "This excludes generated kernels, allocator overhead and recording buffers; "
                "it is not a measured GeNN allocation or runtime benchmark."
            ),
        }
    )
    return 0


def _command_benchmark_circuit(args: argparse.Namespace) -> int:
    experiment_path = args.experiment
    if str(experiment_path) == "shiu-antennal-grooming":
        experiment_path = (
            project_root() / "configs" / "experiments" / "shiu-antennal-grooming.json"
        )
    population_path = args.populations or (
        args.root
        / "derived"
        / "male-cns-v1.0"
        / "shiu-antennal-grooming-populations.json"
    )
    output = args.output or (
        args.root
        / "evidence"
        / "male-cns-v1.0"
        / "shiu-antennal-grooming-transfer.json"
    )
    result = run_shiu_malecns_transfer(
        root=args.root,
        graph_path=args.graph,
        experiment_path=experiment_path,
        population_resolution_path=population_path,
        dynamics_registry_path=args.dynamics_registry,
        output_path=output,
        backends=tuple(args.backend),
        prepare_only=args.prepare_only,
    )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "status": result["status"],
            "selection": result["selection"],
            "silencing_control": result["silencing_control"],
            "backend_parity_passed": result.get("backend_parity_passed"),
            "output": result["output"],
            "sha256": result["sha256"],
            "immutable_snapshot": result.get("immutable_snapshot"),
            "validation_tier_awarded": result["validation_tier_awarded"],
        }
    )
    return 0


def _command_benchmark_feeding_screen(args: argparse.Namespace) -> int:
    annotations = args.annotations or (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    evidence_root = args.root / "evidence" / "male-cns-v1.0"
    preparation = args.preparation or evidence_root / "shiu-feeding-screen-preparation.json"
    preregistration = (
        args.preregistration or evidence_root / "shiu-feeding-screen-preregistration.json"
    )
    predictions = args.predictions or evidence_root / "shiu-feeding-screen-predictions.json"
    population_resolution = args.population_resolution or (
        args.root / "derived" / "male-cns-v1.0" / "population-resolution.json"
    )
    graph = args.graph or args.root / "derived" / "male-cns-v1.0" / "graph"
    if args.phase == "prepare-source":
        output = args.output or preparation
        result = prepare_shiu_feeding_screen(
            root=args.root,
            annotations_path=annotations,
            experiment_path=args.experiment,
            output_path=output,
        )
    elif args.phase == "preregister":
        output = args.output or preregistration
        result = preregister_feeding_screen(
            preparation_path=preparation,
            experiment_path=args.experiment,
            population_resolution_path=population_resolution,
            graph_path=graph,
            output_path=output,
        )
    elif args.phase == "execute":
        output = args.output or predictions
        transmitter = args.transmitters or (
            args.root
            / "raw"
            / "male-cns-v1.0"
            / "body-neurotransmitters-male-cns-v1.0.feather"
        )
        result = execute_feeding_screen(
            root=args.root,
            preregistration_path=preregistration,
            annotations_path=annotations,
            transmitter_path=transmitter,
            output_path=output,
        )
    else:
        output = args.output or evidence_root / "shiu-feeding-screen-stage1-review.json"
        result = evaluate_feeding_screen(
            preparation_path=preparation,
            preregistration_path=preregistration,
            predictions_path=predictions,
            output_path=output,
        )
    _print_json(
        {
            "experiment_id": result["experiment_id"],
            "status": result["status"],
            "phase": args.phase,
            "stage1_exit_gate_passed": result.get("stage1_exit_gate_passed"),
            "blocking_reasons": result.get("blocking_reasons"),
            "output": result["output"],
            "sha256": result["sha256"],
            "immutable_snapshot": result.get("immutable_snapshot"),
            "validation_tier_awarded": result["validation_tier_awarded"],
        }
    )
    return 2 if args.phase == "evaluate" and not result["stage1_exit_gate_passed"] else 0


def _split_ids(values: Sequence[str]) -> frozenset[str]:
    return frozenset(item for value in values for item in value.split(",") if item)


def _command_run_demo(args: argparse.Namespace) -> int:
    if args.graph is not None:
        raise ReadinessError(
            "The full-graph Track A adapter is not ready. The current command runs only the "
            "visibly labelled engineering circuit; omit --graph or complete the GeNN gate."
        )
    ablated_inputs = _split_ids(args.ablate_input)
    ablated_outputs = _split_ids(args.ablate_output)
    demo = build_reference_demo(
        seed=args.seed,
        ablated_inputs=ablated_inputs,
        ablated_outputs=ablated_outputs,
    )
    duration = args.duration_us or demo.duration_us
    result = demo.scheduler.run_until(duration)
    written = write_run(
        result=result,
        scenario=demo.scenario,
        registry=demo.registry,
        seed=args.seed,
        output_root=args.output_root,
        ablated_inputs=tuple(sorted(ablated_inputs)),
        ablated_outputs=tuple(sorted(ablated_outputs)),
        evidence_grade=not args.allow_dirty_tree,
    )
    validation = validate_run(written.directory)
    video: str | None = None
    if args.render:
        video = str(render_run(written.directory, fps=args.fps))
    _print_json(
        {
            "run_id": written.run_id,
            "run_directory": str(written.directory),
            "completed": result.completed,
            "final_state": result.final_state.value,
            "validation": validation,
            "video": video,
            "claim": demo.scenario.claim_boundary,
        }
    )
    return 0 if validation["valid"] else 2


def _command_run_full_vnc(args: argparse.Namespace) -> int:
    missing: list[str] = []
    if args.graph is None or not args.graph.exists():
        missing.append("imported MaleCNS aggregate graph")
    data_root = args.root
    for name in ("sensor-registry.parquet", "motor-registry.parquet"):
        if not (data_root / "derived" / "male-cns-v1.0" / name).exists():
            missing.append(name)
    try:
        __import__("pygenn")
    except ImportError:
        missing.append("PyGeNN 5.4 production backend")
    try:
        __import__("flygym")
    except ImportError:
        missing.append("FlyGym 2.1 body backend")
    if missing:
        raise ReadinessError(
            "full-vnc-walk is scientifically gated; missing: " + ", ".join(missing)
        )
    raise ReadinessError(
        "Dependencies are present, but the full-VNC motor decoder has not passed "
        "its interface gate."
    )


def _command_run_eon_malecns(args: argparse.Namespace) -> int:
    if args.headless:
        os.environ.setdefault("MUJOCO_GL", "osmesa")
    if (args.food_x_mm is None) != (args.food_y_mm is None):
        raise ValidationError("--food-x-mm and --food-y-mm must be supplied together")
    missing: list[str] = []
    if not args.graph.exists():
        missing.append("imported MaleCNS aggregate graph")
    population_path = (
        args.root / "derived" / "male-cns-v1.0" / "population-resolution.json"
    )
    if not population_path.is_file():
        missing.append("numeric Track A population-resolution registry")
    else:
        population_resolution = json.loads(population_path.read_text(encoding="utf-8"))
        if population_resolution.get("all_required_resolved") is not True:
            unresolved = [
                item["id"]
                for item in population_resolution.get("populations", [])
                if item.get("status") != "resolved"
            ]
            missing.append(f"resolved numeric populations: {unresolved}")
    transmitter_path = (
        args.root
        / "raw"
        / "male-cns-v1.0"
        / "body-neurotransmitters-male-cns-v1.0.feather"
    )
    trajectory_path = (
        args.root
        / "derived"
        / "auxiliary"
        / "ozdil-2026-antennal-grooming"
        / "track-a-grooming-trajectory.npz"
    )
    if not transmitter_path.is_file():
        missing.append("MaleCNS body transmitter predictions")
    if not trajectory_path.is_file():
        missing.append("checksum-locked Ozdil grooming trajectory derivative")
    try:
        __import__("pygenn")
    except ImportError:
        missing.append("PyGeNN 5.4 production backend")
    try:
        __import__("flygym")
    except ImportError:
        missing.append("FlyGym 2.1 body backend")
    if missing:
        raise ReadinessError("eon-malecns is scientifically gated; missing: " + ", ".join(missing))
    import time

    ablated_inputs = _split_ids(args.ablate_input)
    ablated_outputs = _split_ids(args.ablate_output)
    food_position = (
        (float(args.food_x_mm), float(args.food_y_mm))
        if args.food_x_mm is not None and args.food_y_mm is not None
        else None
    )
    build_path = (
        args.root
        / "cache"
        / "genn"
        / "track-a"
        / args.control
    )
    # The project tier is resolved from a currently valid evidence bundle. It is never a
    # literal, so a bundle that stops validating immediately demotes the recorded claim.
    project_tier = resolve_supported_tier(args.root / "evidence" / "male-cns-v1.0")
    build_started = time.perf_counter()
    demo = build_track_a_demo(
        seed=args.seed,
        graph_path=args.graph,
        population_resolution_path=population_path,
        transmitter_path=transmitter_path,
        grooming_trajectory_path=trajectory_path,
        build_path=build_path,
        variant=args.control,
        ablated_inputs=ablated_inputs,
        ablated_outputs=ablated_outputs,
        food_position_mm=food_position,
        render=args.render,
        fps=args.fps,
        suppress_groom_replay=args.suppress_groom_replay,
        dynamics_registry_path=args.cell_dynamics,
        annotations_path=(
            args.annotations
            if args.annotations is not None
            else args.root
            / "raw"
            / "male-cns-v1.0"
            / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
        ),
    )
    try:
        duration = args.duration_us or demo.duration_us
        # Graph load, transmitter signs, GeNN code generation and model load are one-off
        # start-up costs. Reporting them inside the throughput figure understated the
        # steady-state loop, so both numbers are recorded separately.
        build_wall_seconds = time.perf_counter() - build_started
        simulation_started = time.perf_counter()
        result = demo.scheduler.run_until(duration)
        simulation_wall_seconds = time.perf_counter() - simulation_started
        wall_seconds = time.perf_counter() - build_started
        biological_seconds = result.final_t_us / 1_000_000.0
        written = write_run(
            result=result,
            scenario=demo.scenario,
            registry=demo.registry,
            seed=args.seed,
            output_root=args.output_root,
            ablated_inputs=tuple(sorted(ablated_inputs)),
            ablated_outputs=tuple(sorted(ablated_outputs)),
            connectome_metadata={
                "canonical_release": demo.registry.records["DATA-01"].value,
                "graph_used": True,
                "resolved_body_ids": True,
                "graph_path": str(args.graph.resolve()),
                "graph_source_sha256": demo.graph.source_sha256,
                "neurons": demo.graph.neuron_count,
                "aggregate_edges": demo.graph.edge_count,
                "threshold_applied": False,
                "population_registry_id": demo.populations.registry_id,
                "population_resolution_sha256": demo.populations.resolution_sha256,
                "control_variant": demo.variant,
            },
            evidence_grade=not args.allow_dirty_tree,
            run_metadata={
                "engineering_track": "A",
                "project_evidence_tier": project_tier,
                "tier_awarded_by_this_run": None,
                "wall_seconds": wall_seconds,
                "model_build_and_load_wall_seconds": build_wall_seconds,
                "simulation_wall_seconds": simulation_wall_seconds,
                "biological_seconds": biological_seconds,
                "biological_seconds_per_wall_second": (
                    biological_seconds / simulation_wall_seconds
                ),
                "biological_seconds_per_wall_second_cold_start": (
                    biological_seconds / wall_seconds
                ),
                "throughput_definition": (
                    "biological_seconds_per_wall_second measures the steady-state coupled "
                    "loop; the cold-start figure additionally includes graph load, GeNN "
                    "code generation, and model load"
                ),
                "food_position_mm": list(food_position) if food_position else None,
                "central_relay_bypasses": ["DM1_lPN", "GNG588/Fdg"],
                "groom_net_displacement_limit_mm": float(
                    demo.registry.value_map("MOTOR-03")["groom_max_net_displacement_mm"]
                ),
                **demo.body.groom_displacement(),
                **demo.body.station_keeping(),
                "groom_replay_suppressed": args.suppress_groom_replay,
            },
        )
        video: str | None = None
        video_sha256: str | None = None
        if args.render:
            video_path = demo.body.save_video(written.directory / "flygym.mp4")
            video_record = attach_run_artifact(written, "flygym_video", video_path)
            video = video_record["path"]
            video_sha256 = video_record["sha256"]
        validation = validate_run(written.directory)
    finally:
        demo.neural.close()
    _print_json(
        {
            "run_id": written.run_id,
            "run_directory": str(written.directory),
            "completed": result.completed,
            "final_state": result.final_state.value,
            "control_variant": demo.variant,
            "wall_seconds": wall_seconds,
            "model_build_and_load_wall_seconds": build_wall_seconds,
            "simulation_wall_seconds": simulation_wall_seconds,
            "biological_seconds_per_wall_second": (
                biological_seconds / simulation_wall_seconds
            ),
            "biological_seconds_per_wall_second_cold_start": (
                biological_seconds / wall_seconds
            ),
            "validation": validation,
            "video": video,
            "video_sha256": video_sha256,
            "claim": demo.scenario.claim_boundary,
            "groom_displacement": demo.body.groom_displacement(),
            "station_keeping": demo.body.station_keeping(),
            "project_evidence_tier": project_tier,
        }
    )
    return 0 if validation["valid"] and result.completed else 2


def _command_data_verify_graph(args: argparse.Namespace) -> int:
    """Verify, or backfill, the per-array hashes of an imported runtime graph."""
    graph_path = args.graph
    manifest_path = graph_path / "manifest.json"
    if not manifest_path.is_file():
        raise ValidationError(f"Graph manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest.get("array_sha256")
    if not isinstance(recorded, dict) or not recorded:
        if not args.write_missing_hashes:
            _print_json(
                {
                    "graph": str(graph_path),
                    "verified": False,
                    "reason": "the graph manifest records no per-array hashes",
                    "remedy": "rerun with --write-missing-hashes to pin the arrays in place",
                }
            )
            return 2
        manifest["array_sha256"] = graph_array_hashes(graph_path)
        manifest["array_sha256_backfilled"] = True
        manifest["array_sha256_backfill_note"] = (
            "Hashes were computed from the arrays already on disk, so they pin the graph "
            "from this point on but do not independently attest to the original import."
        )
        temporary = manifest_path.with_suffix(".json.part")
        temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + chr(10), encoding="utf-8"
        )
        os.replace(temporary, manifest_path)
        _print_json(
            {
                "graph": str(graph_path),
                "verified": True,
                "backfilled": True,
                "array_sha256": manifest["array_sha256"],
            }
        )
        return 0
    report = verify_graph_array_hashes(graph_path, manifest)
    _print_json({"graph": str(graph_path), **report, "array_sha256": recorded})
    return 0 if report.get("verified") else 2


def _command_render(args: argparse.Namespace) -> int:
    path = render_run(args.run_directory, fps=args.fps)
    _print_json({"video": str(path)})
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    report = validate_run(args.run_directory)
    _print_json(report)
    return 0 if report["valid"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flysim")
    commands = parser.add_subparsers(dest="command", required=True)

    data = commands.add_parser("data", help="Acquire and validate canonical datasets")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    status = data_commands.add_parser("status")
    status.add_argument("--profile", choices=("metadata", "starter", "full"), default="full")
    status.add_argument("--root", type=Path, default=default_data_root())
    status.add_argument("--spec", type=Path, default=_default_dataset_spec())
    status.add_argument("--json", action="store_true", help="accepted for stable agent scripts")
    status.set_defaults(func=_command_data_status)

    sync = data_commands.add_parser("sync")
    sync.add_argument(
        "--profile", choices=("metadata", "starter", "full"), default="starter"
    )
    sync.add_argument("--root", type=Path, default=default_data_root())
    sync.add_argument("--spec", type=Path, default=_default_dataset_spec())
    sync.add_argument("--minimum-free-gb", type=float, default=40.0)
    sync.set_defaults(func=_command_data_sync)

    data_validate = data_commands.add_parser("validate")
    data_validate.add_argument("--profile", choices=("metadata", "starter", "full"))
    data_validate.add_argument("--root", type=Path, default=default_data_root())
    data_validate.add_argument("--spec", type=Path, default=_default_dataset_spec())
    data_validate.add_argument("--remote", action="store_true")
    data_validate.add_argument("--deep", action="store_true")
    data_validate.set_defaults(func=_command_data_validate)

    importer = data_commands.add_parser("import-aggregate")
    importer.add_argument("--root", type=Path, default=default_data_root())
    importer.add_argument("--source", type=Path)
    importer.add_argument("--annotations", type=Path)
    importer.add_argument(
        "--status",
        action="append",
        help="annotation status to include; repeat for more (default: Traced)",
    )
    importer.add_argument("--output", type=Path)
    importer.set_defaults(func=_command_data_import)

    contacts = data_commands.add_parser("import-contacts")
    contacts.add_argument("--root", type=Path, default=default_data_root())
    contacts.add_argument("--spec", type=Path, default=_default_dataset_spec())
    contacts.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    contacts.add_argument("--memory-limit-gb", type=float, default=3.0)
    contacts.add_argument("--threads", type=int, default=2)
    contacts.add_argument("--minimum-free-gb", type=float, default=80.0)
    contacts.add_argument("--output-root", type=Path)
    contacts.add_argument("--row-group-rows", type=int, default=262_144)
    contacts.add_argument("--shard-rows", type=int, default=1_048_576)
    contacts.add_argument(
        "--artifact",
        action="append",
        choices=(
            "connectome-weights",
            "syn-points",
            "syn-partners",
            "tbar-neurotransmitters",
        ),
        help="normalize only this contact artifact; repeat to select more",
    )
    contacts.add_argument(
        "--max-new-shards-per-process",
        type=int,
        help="checkpoint and request a clean worker after this many new shards",
    )
    contacts.add_argument(
        "--temporary-storage",
        type=Path,
        default=Path("/srv/flybrain-data/tmp/contact-audit"),
    )
    contacts.set_defaults(func=_command_data_import_contacts)

    rebuild = data_commands.add_parser("verify-contact-rebuild")
    rebuild.add_argument("--left", type=Path, required=True)
    rebuild.add_argument("--right", type=Path, required=True)
    rebuild.add_argument("--output", type=Path, required=True)
    rebuild.add_argument("--scan-batch-rows", type=int, default=65_536)
    rebuild.set_defaults(func=_command_data_verify_contact_rebuild)

    contact_audit = data_commands.add_parser("audit-contacts")
    contact_audit.add_argument("--root", type=Path, default=default_data_root())
    contact_audit.add_argument("--strict", action="store_true")
    contact_audit.add_argument("--memory-limit-gb", type=float, default=3.0)
    contact_audit.add_argument("--threads", type=int, default=2)
    contact_audit.add_argument(
        "--temporary-storage",
        type=Path,
        default=Path("/srv/flybrain-data/tmp/contact-audit"),
    )
    contact_audit.add_argument("--output", type=Path)
    contact_audit.set_defaults(func=_command_data_audit_contacts)

    skeletons = data_commands.add_parser("sync-skeleton-canaries")
    skeletons.add_argument("--root", type=Path, default=default_data_root())
    skeletons.add_argument(
        "--config",
        type=Path,
        default=project_root() / "configs" / "datasets" / "morphology-canaries.json",
    )
    skeletons.add_argument("--output", type=Path)
    skeletons.set_defaults(func=_command_data_sync_skeleton_canaries)

    universes = data_commands.add_parser("audit-body-universes")
    universes.add_argument("--root", type=Path, default=default_data_root())
    universes.add_argument("--output", type=Path)
    universes.set_defaults(func=_command_data_audit_body_universes)

    structural = data_commands.add_parser("audit-structural-references")
    structural.add_argument("--root", type=Path, default=default_data_root())
    structural.add_argument(
        "--supplement-card",
        type=Path,
        default=project_root()
        / "configs"
        / "datasets"
        / "berg-malecns-2025-supplement.json",
    )
    structural.add_argument(
        "--canary-config",
        type=Path,
        default=project_root() / "configs" / "datasets" / "morphology-canaries.json",
    )
    structural.add_argument("--output", type=Path)
    structural.set_defaults(func=_command_data_audit_structural_references)

    verify_graph = data_commands.add_parser(
        "verify-graph", help="verify or backfill the runtime graph array hashes"
    )
    verify_graph.add_argument("--graph", type=Path, required=True)
    verify_graph.add_argument("--write-missing-hashes", action="store_true")
    verify_graph.set_defaults(func=_command_data_verify_graph)

    resolver = data_commands.add_parser("resolve-populations")
    resolver.add_argument("--root", type=Path, default=default_data_root())
    resolver.add_argument("--annotations", type=Path)
    resolver.add_argument(
        "--registry",
        type=Path,
        default=project_root() / "configs" / "populations" / "eon-demo.json",
    )
    resolver.add_argument("--output", type=Path)
    resolver.set_defaults(func=_command_data_resolve_populations)

    grooming = data_commands.add_parser(
        "import-grooming-trajectory",
        help="convert the checksum-locked Ozdil Figure 1 trajectory to portable NPZ",
    )
    grooming.add_argument("--root", type=Path, default=default_data_root())
    grooming.add_argument("--source", type=Path)
    grooming.add_argument("--output", type=Path)
    grooming.set_defaults(func=_command_data_import_grooming)

    signs = data_commands.add_parser("build-edge-signs")
    signs.add_argument("--root", type=Path, default=default_data_root())
    signs.add_argument("--graph", type=Path, required=True)
    signs.add_argument("--transmitters", type=Path)
    signs.add_argument("--output", type=Path, required=True)
    signs.add_argument(
        "--unresolved-policy",
        choices=tuple(item.value for item in UnresolvedSignPolicy),
        required=True,
    )
    signs.add_argument("--seed", type=int, default=1)
    signs.set_defaults(func=_command_data_build_edge_signs)

    dm1_priors = data_commands.add_parser(
        "import-dm1-priors",
        help="normalize the pinned Gouwens-Wilson DM1 passive-model fits",
    )
    dm1_priors.add_argument("--source", type=Path, required=True)
    dm1_priors.add_argument("--output", type=Path, required=True)
    dm1_priors.add_argument("--expected-commit", default=GOUWENS_MODELDB_COMMIT)
    dm1_priors.set_defaults(func=_command_data_import_dm1_priors)

    gugel_figure7 = data_commands.add_parser(
        "import-gugel-figure7",
        help="normalize the checksum-locked eLife Figure 7 DL5 physiology",
    )
    gugel_figure7.add_argument("--source", type=Path, required=True)
    gugel_figure7.add_argument("--output", type=Path, required=True)
    gugel_figure7.set_defaults(func=_command_data_import_gugel_figure7)

    nanami_pn = data_commands.add_parser(
        "import-nanami-pn",
        help="normalize the pinned external Nanami PN current-clamp trace",
    )
    nanami_pn.add_argument("--source", type=Path, required=True)
    nanami_pn.add_argument("--output", type=Path, required=True)
    nanami_pn.add_argument("--expected-commit", default=NANAMI_REPOSITORY_COMMIT)
    nanami_pn.set_defaults(func=_command_data_import_nanami_pn)

    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    neural = benchmark_commands.add_parser("neural")
    neural.add_argument("--scales", type=float, nargs="+", default=[0.01, 0.1, 1.0])
    neural.add_argument("--graph", type=Path)
    neural.add_argument("--assumptions", type=Path, default=_default_assumptions())
    neural_mode = neural.add_mutually_exclusive_group()
    neural_mode.add_argument(
        "--genn", action="store_true", help="run measured CUDA graph-load benchmark"
    )
    neural_mode.add_argument(
        "--parity", action="store_true", help="compare NumPy, Brian2, and direct PyGeNN"
    )
    neural.add_argument("--seed", type=int, default=1)
    neural.add_argument("--output", type=Path)
    neural.add_argument("--build-root", type=Path)
    neural.set_defaults(func=_command_benchmark)

    circuit = benchmark_commands.add_parser("circuit")
    circuit.add_argument(
        "--experiment",
        type=Path,
        default=Path("shiu-antennal-grooming"),
        help="experiment key or JSON specification",
    )
    circuit.add_argument("--root", type=Path, default=default_data_root())
    circuit.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    circuit.add_argument("--populations", type=Path)
    circuit.add_argument(
        "--dynamics-registry",
        type=Path,
        default=project_root() / "configs" / "neural" / "cell-dynamics-v0.4.json",
    )
    circuit.add_argument("--output", type=Path)
    circuit.add_argument(
        "--backend",
        action="append",
        choices=("numpy", "brian2", "genn"),
        default=[],
        help="additional parity backend; NumPy controls always run",
    )
    circuit.add_argument("--prepare-only", action="store_true")
    circuit.set_defaults(func=_command_benchmark_circuit)

    widened = benchmark_commands.add_parser(
        "widened-circuit",
        help="rerun the ND-04 sweep on bounded-path circuits wider than the shortest paths",
    )
    widened.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "shiu-antennal-grooming-widened.json",
    )
    widened.add_argument("--root", type=Path, default=default_data_root())
    widened.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    widened.add_argument("--populations", type=Path)
    widened.add_argument("--output", type=Path, required=True)
    widened.add_argument(
        "--backend",
        action="append",
        choices=("numpy", "genn"),
        default=["numpy"],
        help="parity backend; the sweep is blocked unless GeNN parity passes",
    )
    widened.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="produce an explicitly non-evidence-grade run from an uncommitted worktree",
    )
    widened.set_defaults(func=_command_benchmark_widened_circuit)

    convergence = benchmark_commands.add_parser(
        "orn-pn-convergence",
        help="test the published complete ORN-to-PN convergence against the locked connectome",
    )
    convergence.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "orn-pn-convergence-v1.json",
    )
    convergence.add_argument("--root", type=Path, default=default_data_root())
    convergence.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    convergence.add_argument("--output", type=Path, required=True)
    convergence.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="produce an explicitly non-evidence-grade run from an uncommitted worktree",
    )
    convergence.set_defaults(func=_command_benchmark_orn_pn_convergence)

    volume = benchmark_commands.add_parser(
        "glomerular-volume",
        help="test the published release-site scaling against measured glomerular volume",
    )
    volume.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "glomerular-volume-scaling-v1.json",
    )
    volume.add_argument("--root", type=Path, default=default_data_root())
    volume.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    volume.add_argument("--output", type=Path, required=True)
    volume.add_argument("--allow-dirty-tree", action="store_true")
    volume.set_defaults(func=_command_benchmark_glomerular_volume)

    station = benchmark_commands.add_parser(
        "station-keeping-validation",
        help="score the frozen station-keeping controller on the registered validation poses",
    )
    station.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "track-a-acceptance-v5-criteria.json",
    )
    station.add_argument("--root", type=Path, default=default_data_root())
    station.add_argument(
        "--assumptions",
        type=Path,
        default=project_root() / "configs" / "assumptions.json",
    )
    station.add_argument("--output", type=Path, required=True)
    station.add_argument("--allow-dirty-tree", action="store_true")
    station.set_defaults(func=_command_track_a_station_validation)

    bilateral = benchmark_commands.add_parser(
        "bilateral-symmetry",
        help="test the published ipsilateral/contralateral ORN-to-PN equality on the graph",
    )
    bilateral.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "stage2-bilateral-symmetry-v1.json",
    )
    bilateral.add_argument("--root", type=Path, default=default_data_root())
    bilateral.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    bilateral.add_argument("--output", type=Path, required=True)
    bilateral.add_argument("--allow-dirty-tree", action="store_true")
    bilateral.set_defaults(func=_command_benchmark_bilateral_symmetry)

    correction = benchmark_commands.add_parser(
        "completeness-corrected-contacts",
        help="invert synapse-level incompleteness to recover contacts per true connection",
    )
    correction.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "completeness-corrected-contacts-v1.json",
    )
    correction.add_argument("--root", type=Path, default=default_data_root())
    correction.add_argument(
        "--graph",
        type=Path,
        default=default_data_root() / "derived" / "male-cns-v1.0" / "graph",
    )
    correction.add_argument(
        "--convergence-artifact",
        type=Path,
        default=default_data_root()
        / "evidence"
        / "male-cns-v1.0"
        / "orn-pn-convergence-v1.json",
    )
    correction.add_argument(
        "--volume-artifact",
        type=Path,
        default=default_data_root()
        / "evidence"
        / "male-cns-v1.0"
        / "glomerular-volume-scaling-v1.json",
    )
    correction.add_argument("--output", type=Path, required=True)
    correction.add_argument("--allow-dirty-tree", action="store_true")
    correction.set_defaults(func=_command_benchmark_completeness_correction)

    feeding_screen = benchmark_commands.add_parser(
        "feeding-screen",
        help="prepare the independent Shiu Figure 2 behavioral-screen transfer",
    )
    feeding_screen.add_argument("--root", type=Path, default=default_data_root())
    feeding_screen.add_argument(
        "--phase",
        choices=("prepare-source", "preregister", "execute", "evaluate"),
        default="prepare-source",
    )
    feeding_screen.add_argument(
        "--annotations",
        type=Path,
    )
    feeding_screen.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "shiu-feeding-screen.json",
    )
    feeding_screen.add_argument("--output", type=Path)
    feeding_screen.add_argument("--preparation", type=Path)
    feeding_screen.add_argument("--preregistration", type=Path)
    feeding_screen.add_argument("--predictions", type=Path)
    feeding_screen.add_argument("--population-resolution", type=Path)
    feeding_screen.add_argument("--graph", type=Path)
    feeding_screen.add_argument("--transmitters", type=Path)
    feeding_screen.set_defaults(func=_command_benchmark_feeding_screen)

    run = commands.add_parser("run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    demo = run_commands.add_parser("eon-demo")
    demo.add_argument("--seed", type=int, default=1)
    demo.add_argument("--duration-us", type=int)
    demo.add_argument("--output-root", type=Path, default=Path("runs"))
    demo.add_argument("--ablate-input", action="append", default=[])
    demo.add_argument("--ablate-output", action="append", default=[])
    demo.add_argument("--graph", type=Path)
    demo.add_argument("--headless", action="store_true")
    demo.add_argument("--render", action="store_true")
    demo.add_argument("--fps", type=int, default=30)
    demo.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="record an explicitly non-evidence-grade run from an uncommitted worktree",
    )
    demo.set_defaults(func=_command_run_demo)

    full_vnc = run_commands.add_parser("full-vnc-walk")
    full_vnc.add_argument("--seed", type=int, default=1)
    full_vnc.add_argument("--graph", type=Path)
    full_vnc.add_argument("--root", type=Path, default=default_data_root())
    full_vnc.add_argument("--headless", action="store_true")
    full_vnc.set_defaults(func=_command_run_full_vnc)

    eon_malecns = run_commands.add_parser("eon-malecns")
    eon_malecns.add_argument("--seed", type=int, default=1)
    eon_malecns.add_argument("--graph", type=Path, required=True)
    eon_malecns.add_argument("--root", type=Path, default=default_data_root())
    eon_malecns.add_argument("--duration-us", type=int)
    eon_malecns.add_argument("--output-root", type=Path, default=Path("runs"))
    eon_malecns.add_argument("--ablate-input", action="append", default=[])
    eon_malecns.add_argument("--ablate-output", action="append", default=[])
    eon_malecns.add_argument(
        "--control",
        choices=("exact", "zero-weight", "shuffled-connectome"),
        default="exact",
    )
    eon_malecns.add_argument(
        "--suppress-groom-replay",
        action="store_true",
        help=(
            "Run the B1 paired control: hold the grooming pose instead of replaying the "
            "published joint trajectory, leaving the adhesion pattern, bout window, seed "
            "and food position identical. The difference in body displacement is what the "
            "replay itself contributes."
        ),
    )
    eon_malecns.add_argument("--food-x-mm", type=float)
    eon_malecns.add_argument("--food-y-mm", type=float)
    eon_malecns.add_argument("--headless", action="store_true")
    eon_malecns.add_argument(
        "--cell-dynamics",
        type=Path,
        default=None,
        help=(
            "Resolve per-type membrane parameters from this dynamics registry. Omit to keep "
            "the single global Shiu-style LIF that every recorded Track A run used."
        ),
    )
    eon_malecns.add_argument(
        "--annotations",
        type=Path,
        default=None,
        help="Body-annotation table used to resolve cell types for --cell-dynamics.",
    )
    eon_malecns.add_argument("--render", action="store_true")
    eon_malecns.add_argument("--fps", type=int, default=30)
    eon_malecns.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="record an explicitly non-evidence-grade run from an uncommitted worktree",
    )
    eon_malecns.set_defaults(func=_command_run_eon_malecns)

    render = commands.add_parser("render")
    render.add_argument("run_directory", type=Path)
    render.add_argument("--fps", type=int, default=30)
    render.set_defaults(func=_command_render)

    validate = commands.add_parser("validate")
    validate.add_argument("run_directory", type=Path)
    validate.set_defaults(func=_command_validate)

    stage2 = commands.add_parser("stage2", help="Inspect fitted-dynamics readiness")
    stage2_commands = stage2.add_subparsers(dest="stage2_command", required=True)
    stage2_exit = stage2_commands.add_parser(
        "exit-gate",
        help="Re-evaluate the Stage 2 exit criteria against checksum-pinned evidence",
    )
    stage2_exit.add_argument("--root", type=Path, default=default_data_root())
    stage2_exit.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-exit-gate.json",
    )
    stage2_exit.add_argument("--output", type=Path, required=True)
    stage2_exit.set_defaults(func=_command_stage2_exit_gate)
    stage2_synaptic = stage2_commands.add_parser(
        "synaptic-structure",
        help="Test the published homeostatic-matching claim against locked contact structure",
    )
    stage2_synaptic.add_argument("--root", type=Path, default=default_data_root())
    stage2_synaptic.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-synaptic-structure.json",
    )
    stage2_synaptic.add_argument("--output", type=Path, required=True)
    stage2_synaptic.set_defaults(func=_command_stage2_synaptic_structure)
    stage2_uepsc = stage2_commands.add_parser(
        "uepsc-holdout",
        help="Score the frozen unitary-EPSC kernel against preregistered feature limits",
    )
    stage2_uepsc.add_argument("--root", type=Path, default=default_data_root())
    stage2_uepsc.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "stage2-uepsc-kinetics-holdout.json",
    )
    stage2_uepsc.add_argument("--output", type=Path, required=True)
    stage2_uepsc.set_defaults(func=_command_stage2_uepsc_holdout)
    stage2_uepsc_prior = stage2_commands.add_parser(
        "uepsc-prior",
        help="refit the unitary-EPSC kernel on every recording as a labelled, unvalidated prior",
    )
    stage2_uepsc_prior.add_argument("--root", type=Path, default=default_data_root())
    stage2_uepsc_prior.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-uepsc-prior-refit.json",
    )
    stage2_uepsc_prior.add_argument("--output", type=Path, required=True)
    stage2_uepsc_prior.set_defaults(func=_command_stage2_uepsc_prior)
    stage2_kernel_family = stage2_commands.add_parser(
        "uepsc-kernel-family",
        help="compare the single-decay and two-decay uEPSC kernel families on the same data",
    )
    stage2_kernel_family.add_argument("--root", type=Path, default=default_data_root())
    stage2_kernel_family.add_argument(
        "--experiment",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "stage2-uepsc-kernel-family-v1.json",
    )
    stage2_kernel_family.add_argument("--output", type=Path, required=True)
    stage2_kernel_family.set_defaults(func=_command_stage2_uepsc_kernel_family)
    stage2_ensemble = stage2_commands.add_parser(
        "pn-ensemble",
        help="Widen the frozen PN family into a VAL-01 uncertainty ensemble",
    )
    stage2_ensemble.add_argument("--root", type=Path, default=default_data_root())
    stage2_ensemble.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-pn-ensemble.json",
    )
    stage2_ensemble.add_argument("--output", type=Path, required=True)
    stage2_ensemble.set_defaults(func=_command_stage2_pn_ensemble)
    stage2_import_pack = stage2_commands.add_parser(
        "import-invivo-pack",
        help="Normalize the locked in vivo cellular pack",
    )
    stage2_import_pack.add_argument(
        "--config",
        type=Path,
        default=project_root()
        / "configs"
        / "datasets"
        / "nanami-2024-invivo-cellular-pack.json",
    )
    stage2_import_pack.add_argument("--source", type=Path, required=True)
    stage2_import_pack.add_argument("--output", type=Path, required=True)
    stage2_import_pack.set_defaults(func=_command_stage2_import_invivo_pack)
    stage2_measure = stage2_commands.add_parser(
        "measure-cellular",
        help="Measure V1 observables from the locked in vivo cellular pack",
    )
    stage2_measure.add_argument("--root", type=Path, default=default_data_root())
    stage2_measure.add_argument(
        "--contract",
        type=Path,
        default=project_root()
        / "configs"
        / "experiments"
        / "stage2-cellular-observables.json",
    )
    stage2_measure.add_argument("--output", type=Path, required=True)
    stage2_measure.set_defaults(func=_command_stage2_measure_cellular)
    stage2_readiness = stage2_commands.add_parser(
        "readiness", help="validate a preregistered physiology fit contract"
    )
    stage2_readiness.add_argument("--root", type=Path, default=default_data_root())
    stage2_readiness.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-pn-physiology.json",
    )
    stage2_readiness.set_defaults(func=_command_stage2_readiness)
    stage2_fit_pn = stage2_commands.add_parser(
        "fit-pn", help="fit and freeze the preregistered projection-neuron family"
    )
    stage2_fit_pn.add_argument("--root", type=Path, default=default_data_root())
    stage2_fit_pn.add_argument(
        "--experiment",
        type=Path,
        default=project_root() / "configs" / "experiments" / "stage2-pn-physiology.json",
    )
    stage2_fit_pn.add_argument("--output", type=Path, required=True)
    stage2_fit_pn.set_defaults(func=_command_stage2_fit_pn)
    stage2_fit_pn_dynamic = stage2_commands.add_parser(
        "fit-pn-dynamic",
        help="fit and freeze the ramp-aware PN family without opening its external trace",
    )
    stage2_fit_pn_dynamic.add_argument("--root", type=Path, default=default_data_root())
    stage2_fit_pn_dynamic.add_argument(
        "--experiment",
        type=Path,
        default=(
            project_root() / "configs" / "experiments" / "stage2-pn-dynamic-revision.json"
        ),
    )
    stage2_fit_pn_dynamic.add_argument("--output", type=Path, required=True)
    stage2_fit_pn_dynamic.set_defaults(func=_command_stage2_fit_pn_dynamic)
    stage2_evaluate_pn_dynamic = stage2_commands.add_parser(
        "evaluate-pn-dynamic",
        help="evaluate a frozen dynamic PN distribution on excluded recorded cells",
    )
    stage2_evaluate_pn_dynamic.add_argument(
        "--root", type=Path, default=default_data_root()
    )
    stage2_evaluate_pn_dynamic.add_argument(
        "--evaluation",
        type=Path,
        default=(
            project_root() / "configs" / "experiments" / "stage2-pn-condition-holdout.json"
        ),
    )
    stage2_evaluate_pn_dynamic.add_argument("--output", type=Path, required=True)
    stage2_evaluate_pn_dynamic.set_defaults(func=_command_stage2_evaluate_pn_dynamic)
    stage2_review_pn_dynamic_timestep = stage2_commands.add_parser(
        "review-pn-dynamic-timestep",
        help="review a frozen dynamic PN holdout conclusion at a smaller timestep",
    )
    stage2_review_pn_dynamic_timestep.add_argument(
        "--root", type=Path, default=default_data_root()
    )
    stage2_review_pn_dynamic_timestep.add_argument(
        "--review",
        type=Path,
        default=(
            project_root()
            / "configs"
            / "experiments"
            / "stage2-pn-dynamic-timestep-review.json"
        ),
    )
    stage2_review_pn_dynamic_timestep.add_argument("--output", type=Path, required=True)
    stage2_review_pn_dynamic_timestep.set_defaults(
        func=_command_stage2_review_pn_dynamic_timestep
    )
    stage2_review_pn = stage2_commands.add_parser(
        "review-pn", help="audit feature errors from an immutable frozen PN fit"
    )
    stage2_review_pn.add_argument("--root", type=Path, default=default_data_root())
    stage2_review_pn.add_argument("--fit-result", type=Path, required=True)
    stage2_review_pn.add_argument("--expected-fit-sha256", required=True)
    stage2_review_pn.add_argument("--output", type=Path, required=True)
    stage2_review_pn.set_defaults(func=_command_stage2_review_pn)

    evidence = commands.add_parser("evidence", help="Build and validate scientific evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_build = evidence_commands.add_parser("build")
    evidence_build.add_argument(
        "--tier", choices=tuple(tier.value for tier in ValidationTier), required=True
    )
    evidence_build.add_argument("--artifact", action="append", default=[], help="NAME=PATH")
    evidence_build.add_argument("--gate", action="append", default=[], help="NAME=true|false")
    evidence_build.add_argument("--root", type=Path, default=default_data_root())
    evidence_build.add_argument("--spec", type=Path, default=_default_dataset_spec())
    evidence_build.add_argument("--output", type=Path, required=True)
    evidence_build.set_defaults(func=_command_evidence_build)
    evidence_build_v0 = evidence_commands.add_parser(
        "build-v0", help="derive V0 gates from the canonical locked evidence artifacts"
    )
    evidence_build_v0.add_argument("--root", type=Path, default=default_data_root())
    evidence_build_v0.add_argument("--spec", type=Path, default=_default_dataset_spec())
    evidence_build_v0.add_argument("--output", type=Path, required=True)
    evidence_build_v0.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="build from an uncommitted worktree; the bundle records that it was waived",
    )
    evidence_build_v0.set_defaults(func=_command_evidence_build_v0)
    evidence_validate = evidence_commands.add_parser("validate")
    evidence_validate.add_argument("bundle", type=Path)
    evidence_validate.set_defaults(func=_command_evidence_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FlySimError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "code": getattr(exc, "code", "VALUE_ERROR"),
                    "retryable": getattr(exc, "retryable", False),
                }
            ),
            file=sys.stderr,
        )
        return 75 if isinstance(exc, FlySimError) and exc.retryable else 2


if __name__ == "__main__":
    raise SystemExit(main())
