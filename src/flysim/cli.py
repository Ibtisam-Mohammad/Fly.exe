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
from flysim.datasets import DatasetSpec, default_data_root, sync_dataset, validate_dataset
from flysim.errors import FlySimError, ReadinessError
from flysim.factory import build_reference_demo
from flysim.populations import resolve_populations
from flysim.provenance import AssumptionRegistry
from flysim.render import render_run
from flysim.runs import write_run
from flysim.validation import validate_run


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


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
    )
    _print_json(lock)
    return 0


def _command_data_validate(args: argparse.Namespace) -> int:
    spec = DatasetSpec.load(args.spec)
    results = validate_dataset(spec, args.root, args.profile)
    _print_json({"dataset_id": spec.dataset_id, "artifacts": results})
    return 0 if all(item["status"] == "ok" for item in results) else 2


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


def _command_benchmark(args: argparse.Namespace) -> int:
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

    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    neural = benchmark_commands.add_parser("neural")
    neural.add_argument("--scales", type=float, nargs="+", default=[0.01, 0.1, 1.0])
    neural.add_argument("--graph", type=Path)
    neural.add_argument("--assumptions", type=Path, default=_default_assumptions())
    neural.add_argument("--genn", action="store_true", help="run measured CUDA load benchmark")
    neural.add_argument("--seed", type=int, default=1)
    neural.add_argument("--output", type=Path)
    neural.add_argument("--build-root", type=Path)
    neural.set_defaults(func=_command_benchmark)

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

    render = commands.add_parser("render")
    render.add_argument("run_directory", type=Path)
    render.add_argument("--fps", type=int, default=30)
    render.set_defaults(func=_command_render)

    validate = commands.add_parser("validate")
    validate.add_argument("run_directory", type=Path)
    validate.set_defaults(func=_command_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FlySimError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
