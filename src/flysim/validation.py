# SPDX-License-Identifier: GPL-2.0-or-later
"""Run-artifact validation without upgrading engineering demos to science claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from flysim.errors import DatasetError
from flysim.runs import read_trace


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_run(run_directory: Path) -> dict[str, Any]:
    manifest_path = run_directory / "manifest.json"
    if not manifest_path.exists():
        raise DatasetError(f"Run manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "run_id",
        "scenario",
        "assumption_set",
        "random_seed",
        "backends",
        "connectome",
        "scaffolds",
        "omissions",
        "result",
        "git",
        "artifacts",
    }
    failures: list[str] = []
    missing = sorted(required - manifest.keys())
    if missing:
        failures.append(f"manifest fields missing: {missing}")

    trace_path = run_directory / manifest.get("artifacts", {}).get("trace", "trace.jsonl")
    if not trace_path.exists():
        failures.append("trace artifact missing")
        trace: list[dict[str, Any]] = []
    else:
        observed = _sha256_file(trace_path)
        expected = manifest.get("artifacts", {}).get("trace_sha256")
        if observed != expected:
            failures.append(f"trace checksum mismatch: expected {expected}, got {observed}")
        trace = read_trace(run_directory)

    previous_t = -1
    for index, record in enumerate(trace):
        if not isinstance(record, dict) or "t_us" not in record:
            failures.append(f"malformed trace record {index}")
            continue
        t_us = int(record["t_us"])
        if t_us <= previous_t:
            failures.append(f"trace timestamp is not strictly increasing at record {index}")
        previous_t = t_us
        for component in ("body", "sensors", "neural", "actuators"):
            if component not in record or "t_us" not in record[component]:
                failures.append(f"trace record {index} lacks {component} timestamp")
                continue
            component_t = int(record[component]["t_us"])
            if component_t != t_us:
                failures.append(
                    f"{component} timestamp {component_t} differs from scheduler "
                    f"{t_us} at record {index}"
                )

    event_targets = [event["to_state"] for event in manifest.get("result", {}).get("events", [])]
    required_order = ["GROOM", "SEEK_RESUME", "FEED_INITIATION"]
    cursor = 0
    for state in event_targets:
        if cursor < len(required_order) and state == required_order[cursor]:
            cursor += 1
    completed = bool(manifest.get("result", {}).get("completed"))
    if completed and cursor != len(required_order):
        failures.append("completed demo lacks the required causal state sequence")
    if manifest.get("connectome", {}).get("graph_used") is False:
        tier = manifest.get("result", {}).get("highest_validation_tier")
        if tier is not None:
            failures.append(
                "an engineering run without a connectome must not claim a validation tier"
            )

    report = {
        "schema_version": "1.0",
        "run_id": manifest.get("run_id"),
        "valid": not failures,
        "failures": failures,
        "trace_records": len(trace),
        "completed": completed,
        "required_sequence_observed": cursor == len(required_order),
        "scientific_validation_tier": manifest.get("result", {}).get("highest_validation_tier"),
    }
    report_path = run_directory / "validation-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
