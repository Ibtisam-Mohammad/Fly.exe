# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pytest

from flysim.errors import ValidationError
from flysim.evidence import sha256_file, validate_evidence_bundle
from flysim.v0 import CONTACT_ARTIFACTS, build_v0_evidence_bundle


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(root: Path, spec_path: Path, *, excessive_peak: bool = False) -> None:
    raw = root / "raw" / "male-cns-v1.0"
    artifacts = []
    locked: dict[str, object] = {}
    for index in range(7):
        artifact_id = f"artifact-{index}"
        filename = f"artifact-{index}.feather"
        path = raw / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"raw-{index}".encode())
        digest = sha256_file(path)
        artifacts.append(
            {
                "id": artifact_id,
                "filename": filename,
                "profiles": ["full"],
                "expected_bytes": path.stat().st_size,
                "gcs_generation": str(index + 1),
                "etag": f"etag-{index}",
                "md5_base64": f"md5-{index}",
                "crc32c_base64": f"crc-{index}",
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
    spec = tmp_path / "spec.json"
    _fixture(root, spec)

    bundle = build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")

    assert bundle.tier.value == "V0"
    assert set(bundle.gates.values()) == {True}
    assert validate_evidence_bundle(bundle.path)["valid"] is True


def test_build_v0_rejects_clean_rebuild_at_memory_ceiling(tmp_path: Path) -> None:
    root = tmp_path / "data"
    spec = tmp_path / "spec.json"
    _fixture(root, spec, excessive_peak=True)

    with pytest.raises(ValidationError, match="exceeded the 3-GiB RSS gate"):
        build_v0_evidence_bundle(root, spec, tmp_path / "V0.json")
