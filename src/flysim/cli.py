# SPDX-License-Identifier: GPL-2.0-or-later
"""Stable command-line surface for agents and human operators."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flysim.benchmark import estimate_sparse_memory
from flysim.config import project_root
from flysim.connectome import SparseConnectome, import_aggregate_graph
from flysim.contacts import (
    audit_contact_derivatives,
    compare_contact_derivatives,
    import_contact_table,
)
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
    validate_evidence_bundle,
)
from flysim.factory import build_reference_demo
from flysim.feeding_stage1 import (
    evaluate_feeding_screen,
    execute_feeding_screen,
    preregister_feeding_screen,
)
from flysim.morphology import sync_morphology_canaries
from flysim.polarity import UnresolvedSignPolicy, write_edge_sign_variant
from flysim.populations import resolve_populations
from flysim.provenance import AssumptionRegistry
from flysim.render import render_run
from flysim.runs import write_run
from flysim.shiu_feeding import prepare_shiu_feeding_screen
from flysim.stage1 import run_shiu_malecns_transfer
from flysim.structural import audit_structural_references
from flysim.universes import audit_body_universes
from flysim.v0 import build_v0_evidence_bundle
from flysim.validation import validate_run


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
    bundle = build_v0_evidence_bundle(args.root, args.spec, args.output)
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
            "threads": args.threads,
            "temporary_storage": str(args.temporary_storage),
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
    _print_json({**report, "report": str(report_path.resolve())})
    return 0 if report["valid"] else 2


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
    if missing:
        raise ReadinessError("eon-malecns is scientifically gated; missing: " + ", ".join(missing))
    raise ReadinessError(
        "The graph and population gate passed, but the direct PyGeNN Track A dynamics adapter "
        "has not passed NumPy/Brian2/GeNN parity."
    )


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
        default=project_root() / "configs" / "neural" / "cell-dynamics-v0.1.json",
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
    eon_malecns.add_argument("--headless", action="store_true")
    eon_malecns.set_defaults(func=_command_run_eon_malecns)

    render = commands.add_parser("render")
    render.add_argument("run_directory", type=Path)
    render.add_argument("--fps", type=int, default=30)
    render.set_defaults(func=_command_render)

    validate = commands.add_parser("validate")
    validate.add_argument("run_directory", type=Path)
    validate.set_defaults(func=_command_validate)

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
