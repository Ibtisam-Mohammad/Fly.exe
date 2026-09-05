# SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence-derived V0 review and immutable bundle construction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flysim.errors import ValidationError
from flysim.evidence import EvidenceBundle, ValidationTier, build_evidence_bundle, sha256_file

CONTACT_ARTIFACTS = (
    "connectome-weights",
    "syn-points",
    "syn-partners",
    "tbar-neurotransmitters",
)
CONTACT_CHECKS = (
    "packed_point_id_bijection",
    "point_id_uniqueness",
    "partner_endpoint_resolution",
    "aggregate_pair_reconciliation",
    "tbar_point_and_probability_resolution",
    "polyadic_fanout_preserved",
)
UNIVERSE_ORDER = (
    "Traced",
    "Traced+Assign",
    "Traced+Assign+Anchor",
    "all-segment",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read V0 evidence artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"V0 evidence artifact is not a JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _write_json_immutable(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _read_json(path) == payload:
            return
        raise ValidationError(f"Refusing to replace changed V0 review artifact: {path}")
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _raw_profile_review(root: Path, spec_path: Path) -> dict[str, Any]:
    raw_root = root / "raw" / "male-cns-v1.0"
    lock = _read_json(raw_root / "dataset-lock.json")
    spec = _read_json(spec_path)
    _require(lock.get("dataset_id") == "male-cns:v1.0", "Dataset lock is not MaleCNS v1.0")
    _require(spec.get("dataset_id") == lock.get("dataset_id"), "Dataset spec and lock disagree")
    _require("8 nm" in str(spec.get("coordinate_notes", "")), "8-nm coordinate units missing")
    declared = [item for item in spec.get("artifacts", []) if "full" in item.get("profiles", [])]
    _require(
        len(declared) == 7,
        f"Full MaleCNS profile must contain seven artifacts, got {len(declared)}",
    )
    locked = lock.get("artifacts")
    if not isinstance(locked, dict):
        raise ValidationError("Dataset lock has no artifact mapping")
    records: list[dict[str, Any]] = []
    for item in declared:
        artifact_id = str(item["id"])
        _require(artifact_id in locked, f"Dataset lock is missing {artifact_id}")
        record = locked[artifact_id]
        filename = str(item["filename"])
        source = raw_root / filename
        _require(source.is_file(), f"Locked raw artifact is missing: {source}")
        expected_bytes = int(item["expected_bytes"])
        _require(source.stat().st_size == expected_bytes, f"Raw byte count changed: {source}")
        _require(record.get("bytes") == expected_bytes, f"Lock byte count disagrees: {artifact_id}")
        _require(record.get("filename") == filename, f"Lock filename disagrees: {artifact_id}")
        for identity in ("gcs_generation", "etag", "md5_base64", "crc32c_base64"):
            _require(bool(item.get(identity)), f"Pinned {identity} is missing for {artifact_id}")
        observed_sha256 = sha256_file(source)
        _require(
            observed_sha256 == record.get("sha256"),
            f"Raw SHA-256 changed for {artifact_id}",
        )
        records.append(
            {
                "artifact_id": artifact_id,
                "filename": filename,
                "bytes": expected_bytes,
                "sha256": observed_sha256,
                "gcs_generation": item["gcs_generation"],
                "etag": item["etag"],
                "md5_base64": item["md5_base64"],
                "crc32c_base64": item["crc32c_base64"],
            }
        )
    return {
        "schema_version": "1.0",
        "review": "MaleCNS-v1.0-raw-profile-integrity",
        "dataset_id": "male-cns:v1.0",
        "coordinate_units": "8 nm voxel coordinates for synapse tables",
        "artifacts": records,
        "valid": True,
    }


def _validate_contact_report(report: dict[str, Any]) -> None:
    _require(report.get("valid") is True, "Strict contact audit did not pass")
    checks = report.get("checks")
    if not isinstance(checks, dict):
        raise ValidationError("Strict contact audit has no checks")
    for name in CONTACT_CHECKS:
        _require(checks.get(name, {}).get("passed") is True, f"Contact check failed: {name}")


def _validate_morphology(root: Path, manifest: dict[str, Any]) -> None:
    _require(manifest.get("complete") is True, "Morphology canary manifest is incomplete")
    canaries = manifest.get("canaries")
    if not isinstance(canaries, list) or len(canaries) < 8:
        raise ValidationError("Too few morphology canaries")
    canary_root = root / "derived" / "male-cns-v1.0" / "morphology-canaries"
    for canary in canaries:
        _require(canary.get("valid") is True, f"Invalid morphology canary: {canary.get('body_id')}")
        path = canary_root / str(canary["filename"])
        _require(path.is_file(), f"Morphology canary is missing: {path}")
        _require(path.stat().st_size == canary.get("bytes"), f"Morphology size changed: {path}")
        _require(sha256_file(path) == canary.get("sha256"), f"Morphology hash changed: {path}")


def _validate_universe_report(report: dict[str, Any]) -> None:
    universes = report.get("universes")
    if not isinstance(universes, dict):
        raise ValidationError("Body-universe report has no universes")
    prior_edges = -1
    prior_contacts = -1
    for name in UNIVERSE_ORDER:
        _require(name in universes, f"Body-universe report is missing {name}")
        item = universes[name]
        edges = int(item.get("edges", 0))
        contacts = int(item.get("contacts", 0))
        _require(edges > 0 and contacts > 0, f"Body universe {name} is empty")
        _require(
            edges >= prior_edges and contacts >= prior_contacts,
            "Body universes are not monotonic",
        )
        _require(0 < float(item.get("edge_fraction_of_all", 0)) <= 1, "Invalid edge fraction")
        _require(0 < float(item.get("contact_fraction_of_all", 0)) <= 1, "Invalid contact fraction")
        prior_edges, prior_contacts = edges, contacts
    motif = report.get("canary_motif", {})
    _require(int(motif.get("internal_edges", 0)) > 0, "Body-universe canary motif has no edges")
    _require(
        int(motif.get("internal_contacts", 0)) > 0,
        "Body-universe canary motif has no contacts",
    )


def _validate_comparison(report: dict[str, Any], label: str) -> None:
    comparisons = report.get("comparisons")
    _require(report.get("valid") is True, f"{label} comparison did not pass")
    if not isinstance(comparisons, list) or len(comparisons) != 4:
        raise ValidationError(f"{label} is incomplete")
    observed = {item.get("artifact_id") for item in comparisons if item.get("matches") is True}
    _require(observed == set(CONTACT_ARTIFACTS), f"{label} does not cover all contact artifacts")


def _validate_structural_reference(report: dict[str, Any]) -> None:
    _require(report.get("valid") is True, "Structural reference audit did not pass")
    count_checks = report.get("count_checks")
    if not isinstance(count_checks, dict) or not count_checks:
        raise ValidationError("Structural reference audit has no count checks")
    _require(all(value is True for value in count_checks.values()), "Official count check failed")
    _require(
        report.get("selected_motifs", {}).get("valid") is True,
        "Selected structural motif check failed",
    )
    _require(
        report.get("confidence_sensitivity", {}).get("valid") is True,
        "Confidence sensitivity check failed",
    )
    _require(
        report.get("cross_connectome_comparison", {}).get("valid") is True,
        "Cross-connectome comparison check failed",
    )


def _validate_clean_manifests(root: Path) -> None:
    limit_bytes = 3 * 1024**3
    layouts = (("contacts-rebuild-262144", 262_144), ("contacts-rebuild-131072", 131_072))
    for directory, row_group_rows in layouts:
        for artifact_id in CONTACT_ARTIFACTS:
            path = root / "derived" / "male-cns-v1.0" / directory / artifact_id / "manifest.json"
            manifest = _read_json(path)
            _require(manifest.get("complete") is True, f"Clean rebuild is incomplete: {path}")
            _require(
                manifest.get("row_group_rows") == row_group_rows,
                f"Clean rebuild has the wrong row-group size: {path}",
            )
            _require(
                0 < int(manifest.get("peak_rss_bytes", 0)) < limit_bytes,
                f"Clean rebuild exceeded the 3-GiB RSS gate: {path}",
            )


def build_v0_evidence_bundle(root: Path, spec_path: Path, output: Path) -> EvidenceBundle:
    """Derive all V0 gates from verified artifacts, then build an immutable bundle."""
    root = root.resolve()
    evidence_root = root / "evidence" / "male-cns-v1.0"
    contact_path = evidence_root / "contact-structural-audit.json"
    universe_path = evidence_root / "body-universe-sensitivity.json"
    original_compare_path = evidence_root / "canonical-contact-rebuild.json"
    batch_compare_path = evidence_root / "contact-batch-size-reproducibility.json"
    structural_path = evidence_root / "structural-reference-audit.json"
    morphology_path = root / "derived" / "male-cns-v1.0" / "morphology-canaries" / "manifest.json"

    contact = _read_json(contact_path)
    universe = _read_json(universe_path)
    original_compare = _read_json(original_compare_path)
    batch_compare = _read_json(batch_compare_path)
    structural = _read_json(structural_path)
    morphology = _read_json(morphology_path)
    _validate_contact_report(contact)
    _validate_morphology(root, morphology)
    _validate_universe_report(universe)
    _validate_comparison(original_compare, "Canonical rebuild")
    _validate_comparison(batch_compare, "Batch-size reproducibility")
    _validate_structural_reference(structural)
    _validate_clean_manifests(root)

    raw_review = _raw_profile_review(root, spec_path.resolve())
    raw_review_path = evidence_root / "raw-profile-integrity-review.json"
    _write_json_immutable(raw_review_path, raw_review)
    artifact_values = (
        f"raw-profile-integrity={raw_review_path}",
        f"contact-structural-audit={contact_path}",
        f"morphology-canaries={morphology_path}",
        f"body-universe-sensitivity={universe_path}",
        f"canonical-contact-rebuild={original_compare_path}",
        f"batch-size-reproducibility={batch_compare_path}",
        f"structural-reference-audit={structural_path}",
    )
    gate_values = (
        "raw_profile_integrity=true",
        "schema_and_units=true",
        "endpoint_joins=true",
        "polyadic_preservation=true",
        "aggregate_reconciliation=true",
        "morphology_canaries=true",
        "body_universe_sensitivity=true",
        "batch_size_reproducibility=true",
        "official_counts_and_motifs=true",
        "confidence_sensitivity=true",
        "cross_connectome_comparison=true",
    )
    return build_evidence_bundle(
        ValidationTier.V0,
        output,
        artifact_values,
        gate_values,
    )
