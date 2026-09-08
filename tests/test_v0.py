# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.datasets import file_digests
from flysim.errors import ValidationError
from flysim.evidence import sha256_file, validate_evidence_bundle
from flysim.v0 import (
    CONTACT_ARTIFACTS,
    V0_SCOPED_ASSUMPTION_IDS,
    build_v0_evidence_bundle,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(
    root: Path,
    spec_path: Path,
    *,
    excessive_peak: bool = False,
    assumption_set_id: str = "foundation-v9.9-fixture",
) -> None:
    config_root = spec_path.parent.parent
    project_root = config_root.parent
    assumptions = config_root / "assumptions.json"
    _write(
        assumptions,
        {
            # The project-wide identifier is deliberately arbitrary: V0 is gated on the
            # content of the scoped DATA-* records, not on the mutable set identifier.
            "assumption_set_id": assumption_set_id,
            "records": [
                {
                    "id": assumption_id,
                    "status": "proposed" if assumption_id == "DATA-03" else "accepted",
                    "value": {"annotation_statuses": ["Traced"]}
                    if assumption_id == "DATA-04"
                    else {},
                }
                for assumption_id in V0_SCOPED_ASSUMPTION_IDS
            ],
        },
    )
    adr = project_root / "docs" / "adr" / "ADR-2026-002-traced-neuron-universe.md"
    adr.parent.mkdir(parents=True, exist_ok=True)
    adr.write_text(
        "Status: accepted\napproved_by: project-owner via test fixture\n",
        encoding="utf-8",
    )
    raw = root / "raw" / "male-cns-v1.0"
    artifacts = []
    locked: dict[str, object] = {}
    for index in range(7):
        artifact_id = f"artifact-{index}"
        filename = f"artifact-{index}.feather"
        path = raw / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        feather.write_feather(pa.table({"fixture": [f"raw-{index}"]}), path)
        digests = file_digests(path)
        digest = str(digests["sha256"])
        artifacts.append(
            {
                "id": artifact_id,
                "filename": filename,
                "profiles": ["full"],
                "expected_bytes": path.stat().st_size,
                "gcs_generation": str(index + 1),
                "etag": f"etag-{index}",
                "md5_base64": digests["md5_base64"],
                "crc32c_base64": digests["crc32c_base64"] or f"crc-{index}",
            }
        )
        locked[artifact_id] = {
            "filename": filename,
            "bytes": path.stat().st_size,
            "sha256": digest,
        }
    _write(
        spec_path,
        {
            "dataset_id": "male-cns:v1.0",
            "coordinate_notes": "Synapse tables use 8 nm voxel units",
            "artifacts": artifacts,
        },
    )
    canary_config = spec_path.parent / "morphology-canaries.json"
    _write(canary_config, {"canaries": [{"body_id": body_id} for body_id in range(8)]})
    _write(raw / "dataset-lock.json", {"dataset_id": "male-cns:v1.0", "artifacts": locked})

    evidence = root / "evidence" / "male-cns-v1.0"
    checks = {
        name: {"passed": True}
        for name in (
            "packed_point_id_bijection",
            "point_id_uniqueness",
            "partner_endpoint_resolution",
            "aggregate_pair_reconciliation",
            "tbar_point_and_probability_resolution",
            "polyadic_fanout_preserved",
        )
    }
    _write(evidence / "contact-structural-audit.json", {"valid": True, "checks": checks})
    universes: dict[str, object] = {}
    for index, name in enumerate(
        ("Traced", "Traced+Assign", "Traced+Assign+Anchor", "all-segment"), start=1
    ):
        universes[name] = {
            "edges": index,
            "contacts": index * 2,
            "edge_fraction_of_all": index / 4,
            "contact_fraction_of_all": index / 4,
        }
    _write(
        evidence / "body-universe-sensitivity.json",
        {
            "universes": universes,
            "canary_motif": {"internal_edges": 1, "internal_contacts": 2},
        },
    )
    comparison = {
        "valid": True,
        "comparisons": [
            {"artifact_id": artifact_id, "matches": True}
            for artifact_id in CONTACT_ARTIFACTS
        ],
    }
    _write(evidence / "canonical-contact-rebuild.json", comparison)
    _write(evidence / "contact-batch-size-reproducibility.json", comparison)
    _write(
        evidence / "structural-reference-audit.json",
        {
            "valid": True,
            "count_checks": {"published_counts": True},
            "selected_motifs": {"valid": True},
            "confidence_sensitivity": {"valid": True},
            "cross_connectome_comparison": {"valid": True},
        },
    )

    morphology = root / "derived" / "male-cns-v1.0" / "morphology-canaries"
    canaries = []
    for body_id in range(8):
        path = morphology / f"{body_id}.swc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"1 1 {body_id} 0 0 1 -1\n", encoding="utf-8")
        canaries.append(
            {
                "body_id": body_id,
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "valid": True,
            }
        )
    _write(
        morphology / "manifest.json",
        {
            "complete": True,
            "config_sha256": sha256_file(canary_config),
            "canaries": canaries,
        },
    )

    peak = 3 * 1024**3 if excessive_peak else 512 * 1024**2
    derived = root / "derived" / "male-cns-v1.0"
    layouts = (("contacts-rebuild-262144", 262_144), ("contacts-rebuild-131072", 131_072))
    for directory, rows in layouts:
        for artifact_id in CONTACT_ARTIFACTS:
            _write(
                derived / directory / artifact_id / "manifest.json",
                {"complete": True, "row_group_rows": rows, "peak_rss_bytes": peak},
            )


def test_build_v0_derives_gates_from_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "data"
    spec = tmp_path / "project" / "configs" / "datasets" / "spec.json"
    _fixture(root, spec)

    bundle = build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")

    assert bundle.tier.value == "V0"
    assert set(bundle.gates.values()) == {True}
    assert validate_evidence_bundle(bundle.path)["valid"] is True


def test_build_v0_rejects_clean_rebuild_at_memory_ceiling(tmp_path: Path) -> None:
    root = tmp_path / "data"
    spec = tmp_path / "project" / "configs" / "datasets" / "spec.json"
    _fixture(root, spec, excessive_peak=True)

    with pytest.raises(ValidationError, match="exceeded the 3-GiB RSS gate"):
        build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")


def test_build_v0_pins_a_scoped_snapshot_not_the_mutable_registry(tmp_path: Path) -> None:
    """An unrelated register edit must not invalidate a structural bundle."""
    root = tmp_path / "data"
    spec = tmp_path / "project" / "configs" / "datasets" / "spec.json"
    _fixture(root, spec)
    bundle = build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")

    names = {artifact["name"] for artifact in bundle.artifacts}
    assert "v0-foundation-assumptions" in names
    assert "assumption-registry" not in names

    registry_path = spec.parent.parent / "assumptions.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["assumption_set_id"] = "foundation-v99.0"
    payload["records"].append({"id": "TRACKA-01", "status": "accepted", "value": {}})
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_evidence_bundle(bundle.path)["valid"] is True


def test_build_v0_rejects_a_changed_scoped_assumption(tmp_path: Path) -> None:
    root = tmp_path / "data"
    spec = tmp_path / "project" / "configs" / "datasets" / "spec.json"
    _fixture(root, spec)
    build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")

    registry_path = spec.parent.parent / "assumptions.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    for record in payload["records"]:
        if record["id"] == "DATA-04":
            record["value"] = {"annotation_statuses": ["Traced", "Assign"]}
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="Traced runtime universe"):
        build_v0_evidence_bundle(root, spec, tmp_path / "V0-second.json")


def test_build_v0_verifies_upstream_md5_against_local_bytes(tmp_path: Path) -> None:
    root = tmp_path / "data"
    spec = tmp_path / "project" / "configs" / "datasets" / "spec.json"
    _fixture(root, spec)
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["artifacts"][0]["md5_base64"] = "AAAAAAAAAAAAAAAAAAAAAA=="
    spec.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="Upstream MD5 mismatch"):
        build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")
