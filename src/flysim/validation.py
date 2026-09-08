# SPDX-License-Identifier: GPL-2.0-or-later
"""Run-artifact validation without upgrading engineering demos to science claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from flysim.errors import DatasetError, ValidationError
from flysim.evidence import validate_evidence_bundle
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

    artifacts = manifest.get("artifacts", {})
    for artifact_id, relative_path in artifacts.items():
        if artifact_id == "trace" or artifact_id.endswith("_sha256"):
            continue
        artifact_path = (run_directory / str(relative_path)).resolve()
        try:
            artifact_path.relative_to(run_directory.resolve())
        except ValueError:
            failures.append(f"artifact {artifact_id} escapes the run directory")
            continue
        if not artifact_path.is_file():
            failures.append(f"artifact {artifact_id} is missing")
            continue
        expected = artifacts.get(f"{artifact_id}_sha256")
        if not expected:
            failures.append(f"artifact {artifact_id} lacks a checksum")
            continue
        observed = _sha256_file(artifact_path)
        if observed != expected:
            failures.append(
                f"artifact {artifact_id} checksum mismatch: expected {expected}, got {observed}"
            )

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

    events = manifest.get("result", {}).get("events", [])
    event_targets = [event["to_state"] for event in events]
    required_order = ["GROOM", "SEEK_RESUME", "FEED_INITIATION"]
    cursor = 0
    for state in event_targets:
        if cursor < len(required_order) and state == required_order[cursor]:
            cursor += 1
    completed = bool(manifest.get("result", {}).get("completed"))
    if completed and cursor != len(required_order):
        failures.append("completed demo lacks the required causal state sequence")

    # A manifest used to be able to claim any sequence of events without the trace
    # supporting it. Every claimed transition must appear at its stated timestamp.
    if trace:
        states_by_t = {
            int(record["t_us"]): record.get("state")
            for record in trace
            if isinstance(record, dict) and "t_us" in record
        }
        for event in events:
            event_t = int(event["t_us"])
            if event_t not in states_by_t:
                failures.append(f"claimed event at {event_t} us has no trace record")
            elif states_by_t[event_t] != event["to_state"]:
                failures.append(
                    f"claimed transition to {event['to_state']} at {event_t} us is not in the "
                    f"trace, which records {states_by_t[event_t]}"
                )
    elif events:
        failures.append("a run that claims transitions must record a trace")

    # A run that says it used the connectome must show a graph-backed neural readout.
    if manifest.get("connectome", {}).get("graph_used") is True and trace:
        neural_metadata = trace[0].get("neural", {}).get("metadata", {})
        if not neural_metadata.get("full_graph"):
            failures.append(
                "a run recorded as connectome-backed must trace a full-graph neural readout"
            )

    # Artifact integrity is separate from validation (docs/architecture.md). A run that breaches
    # a behavioural limit is still a well-formed record, so the breach is reported in its own
    # block and does not make the artifacts invalid. Acceptance is decided by the experiment.
    metadata = manifest.get("run_metadata", {})
    groom_limit = metadata.get("groom_net_displacement_limit_mm")
    groom_observed = metadata.get("groom_net_displacement_mm")
    behavioral: dict[str, Any] = {}
    if groom_limit is not None:
        behavioral["groom_net_displacement_limit_mm"] = float(groom_limit)
        behavioral["groom_net_displacement_mm"] = (
            float(groom_observed) if groom_observed is not None else None
        )
        if groom_observed is None:
            # A manifest that declares a limit and records no measurement is internally
            # inconsistent, which is an integrity failure rather than a behavioural one.
            failures.append("a declared grooming-displacement limit requires a measured value")
            behavioral["groom_displacement_passed"] = False
        else:
            passed = float(groom_observed) <= float(groom_limit)
            behavioral["groom_displacement_passed"] = passed
            if not passed:
                behavioral["groom_displacement_note"] = (
                    f"grooming-phase body displacement {float(groom_observed):.3f} mm exceeds "
                    f"the registered limit of {float(groom_limit):.3f} mm; the position-"
                    "controller replay moved the body instead of grooming in place"
                )
    if manifest.get("connectome", {}).get("graph_used") is False:
        tier = manifest.get("result", {}).get("highest_validation_tier")
        if tier is not None:
            failures.append(
                "an engineering run without a connectome must not claim a validation tier"
            )
    claimed_tier = manifest.get("result", {}).get("highest_validation_tier")
    if claimed_tier is not None:
        evidence = manifest.get("evidence_bundle")
        if not isinstance(evidence, dict):
            failures.append("a validation-tier claim requires an evidence_bundle record")
        else:
            bundle_path = Path(str(evidence.get("path", "")))
            if not bundle_path.is_absolute():
                bundle_path = run_directory / bundle_path
            if not bundle_path.is_file():
                failures.append(f"evidence bundle is missing: {bundle_path}")
            else:
                observed_bundle_sha = _sha256_file(bundle_path)
                if observed_bundle_sha != evidence.get("sha256"):
                    failures.append("evidence bundle checksum mismatch")
                try:
                    bundle_report = validate_evidence_bundle(bundle_path)
                except ValidationError as exc:
                    failures.append(f"evidence bundle is malformed: {exc}")
                else:
                    if not bundle_report["valid"]:
                        failures.append("evidence bundle validation failed")
                    if bundle_report["tier"] != claimed_tier:
                        failures.append("evidence bundle tier differs from run claim")

    report = {
        "schema_version": "1.0",
        "run_id": manifest.get("run_id"),
        "valid": not failures,
        "failures": failures,
        "trace_records": len(trace),
        "completed": completed,
        "required_sequence_observed": cursor == len(required_order),
        "scientific_validation_tier": claimed_tier,
        "behavioral": behavioral,
        "behavioral_criteria_passed": all(
            value
            for key, value in behavioral.items()
            if key.endswith("_passed")
        ),
    }
    report_path = run_directory / "validation-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
