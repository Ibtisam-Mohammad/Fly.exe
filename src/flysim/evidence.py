# SPDX-License-Identifier: GPL-2.0-or-later
"""Immutable evidence bundles are the sole authority for validation-tier claims."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from flysim.errors import ValidationError


class ValidationTier(StrEnum):
    V0 = "V0"
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"
    V4 = "V4"
    V5 = "V5"
    V6 = "V6"
    V7 = "V7"
    V8 = "V8"


REQUIRED_GATES: dict[ValidationTier, tuple[str, ...]] = {
    ValidationTier.V0: (
        "raw_profile_integrity",
        "schema_and_units",
        "endpoint_joins",
        "polyadic_preservation",
        "aggregate_reconciliation",
        "morphology_canaries",
        "body_universe_sensitivity",
        "batch_size_reproducibility",
    ),
    ValidationTier.V1: ("cellular_held_out_response",),
    ValidationTier.V2: ("synaptic_held_out_response",),
    ValidationTier.V3: ("circuit_held_out_response", "causal_controls"),
    ValidationTier.V4: ("brain_wide_held_out_activity", "observation_model"),
    ValidationTier.V5: ("motor_interface_response", "proprioceptor_response"),
    ValidationTier.V6: ("embodied_held_out_metrics", "perturbation_recovery"),
    ValidationTier.V7: ("behavioral_held_out_metrics", "state_interventions"),
    ValidationTier.V8: ("cross_animal_generalization", "unseen_task_generalization"),
}


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    bundle_id: str
    tier: ValidationTier
    path: Path
    sha256: str
    artifacts: tuple[dict[str, Any], ...]
    gates: dict[str, bool]


def _parse_artifacts(values: tuple[str, ...]) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path:
            raise ValidationError(f"Invalid artifact {value!r}; expected NAME=PATH")
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise ValidationError(f"Evidence artifact is missing or not a file: {path}")
        parsed.append((name, path))
    if len({name for name, _ in parsed}) != len(parsed):
        raise ValidationError("Evidence artifact names must be unique")
    return parsed


def _parse_gates(values: tuple[str, ...]) -> dict[str, bool]:
    gates: dict[str, bool] = {}
    for value in values:
        name, separator, raw_result = value.partition("=")
        if not separator or raw_result.lower() not in {"true", "false"}:
            raise ValidationError(f"Invalid gate {value!r}; expected NAME=true|false")
        gates[name] = raw_result.lower() == "true"
    return gates


def build_evidence_bundle(
    tier: ValidationTier,
    output: Path,
    artifact_values: tuple[str, ...],
    gate_values: tuple[str, ...],
) -> EvidenceBundle:
    """Build an immutable, self-hashed bundle only after every tier gate passes."""
    artifacts = _parse_artifacts(artifact_values)
    gates = _parse_gates(gate_values)
    required = REQUIRED_GATES[tier]
    missing = sorted(set(required) - gates.keys())
    failed = sorted(name for name in required if not gates.get(name, False))
    if missing or failed:
        raise ValidationError(
            f"Cannot award {tier.value}; missing gates={missing}, failed gates={failed}"
        )
    if not artifacts:
        raise ValidationError("An evidence bundle requires at least one hashed artifact")

    created_at = datetime.now(UTC)
    bundle_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{tier.value}"
    artifact_records: list[dict[str, Any]] = [
        {
            "name": name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for name, path in artifacts
    ]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "bundle_id": bundle_id,
        "tier": tier.value,
        "created_at": created_at.isoformat(),
        "required_gates": list(required),
        "gates": gates,
        "artifacts": artifact_records,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValidationError(f"Refusing to overwrite evidence bundle: {output}")
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return EvidenceBundle(
        bundle_id=bundle_id,
        tier=tier,
        path=output,
        sha256=sha256_file(output),
        artifacts=tuple(payload["artifacts"]),
        gates=gates,
    )


def validate_evidence_bundle(path: Path) -> dict[str, Any]:
    """Validate bundle structure, required gates, and every referenced artifact hash."""
    path = path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tier = ValidationTier(payload["tier"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Malformed evidence bundle {path}: {exc}") from exc

    failures: list[str] = []
    gates = payload.get("gates", {})
    for gate in REQUIRED_GATES[tier]:
        if gates.get(gate) is not True:
            failures.append(f"required gate not passed: {gate}")
    artifacts = payload.get("artifacts", [])
    if not artifacts:
        failures.append("no evidence artifacts")
    for artifact in artifacts:
        artifact_path = Path(str(artifact.get("path", "")))
        if not artifact_path.is_file():
            failures.append(f"artifact missing: {artifact_path}")
            continue
        if artifact_path.stat().st_size != artifact.get("bytes"):
            failures.append(f"artifact byte count changed: {artifact_path}")
            continue
        observed = sha256_file(artifact_path)
        if observed != artifact.get("sha256"):
            failures.append(f"artifact checksum changed: {artifact_path}")
    return {
        "schema_version": "1.0",
        "bundle": str(path),
        "bundle_sha256": sha256_file(path),
        "tier": tier.value,
        "valid": not failures,
        "failures": failures,
        "artifact_count": len(artifacts),
    }
