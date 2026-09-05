# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded structural reference, confidence, and cross-connectome audits."""

from __future__ import annotations

import json
import os
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.compute as pc
import pyarrow.feather as feather
import pyarrow.parquet as pq

from flysim.errors import DatasetError
from flysim.evidence import sha256_file

PAPER_COUNTS = {
    "proofread_neurons": 166_691,
    "valid_superclass_graph_neurons": 166_391,
    "valid_superclass_graph_edges": 25_563_426,
    "presynaptic_sites_rounded": 46_000_000,
    "postsynaptic_contacts_rounded": 312_000_000,
}
CONFIDENCE_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
NOTEBOOK_OUTPUT_COUNTS = (20, 11_691, 25_563_426, 166_391, 6_237_402, 165_752, 929_735, 11_687)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"Cannot read structural evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DatasetError(f"Structural evidence is not a JSON object: {path}")
    return value


def _relative_error(observed: int, expected: int) -> float:
    return abs(observed - expected) / expected


def _confidence_sensitivity(partner_root: Path) -> dict[str, Any]:
    counts = np.zeros(len(CONFIDENCE_THRESHOLDS), dtype=np.uint64)
    invalid = 0
    rows = 0
    for path in sorted(partner_root.glob("part-*.parquet")):
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=65_536, columns=["conf_pre", "conf_post"]):
            pre = batch.column(0).to_numpy(zero_copy_only=False)
            post = batch.column(1).to_numpy(zero_copy_only=False)
            confidence = np.minimum(pre, post)
            invalid += int(np.count_nonzero(~np.isfinite(confidence)))
            for index, threshold in enumerate(CONFIDENCE_THRESHOLDS):
                counts[index] += np.uint64(np.count_nonzero(confidence >= threshold))
            rows += batch.num_rows
    if not rows:
        raise DatasetError("Confidence audit found no synaptic partner rows")
    count_values = [int(value) for value in counts]
    monotonic = all(left >= right for left, right in pairwise(count_values))
    return {
        "rows": rows,
        "invalid_or_nonfinite": invalid,
        "threshold_counts": {
            f"{threshold:.1f}": count
            for threshold, count in zip(CONFIDENCE_THRESHOLDS, count_values, strict=True)
        },
        "nonincreasing": monotonic,
        "valid": invalid == 0 and monotonic and count_values[0] == rows and count_values[-1] > 0,
    }


def _annotation_canary_review(annotations_path: Path, canary_config_path: Path) -> dict[str, Any]:
    """Verify stable IDs and selected sensorimotor annotations against a pinned canary card."""
    config = _read_json(canary_config_path)
    canaries = config.get("canaries")
    if not isinstance(canaries, list) or not canaries:
        raise DatasetError("Morphology canary configuration has no annotation canaries")
    expected_ids = {int(item["body_id"]) for item in canaries}
    table = feather.read_table(
        annotations_path,
        columns=["bodyId", "status", "type", "instance", "superclass"],
    )
    body_ids = table.column("bodyId").to_numpy(zero_copy_only=False)
    indices: dict[int, list[int]] = {}
    for index, raw_body_id in enumerate(body_ids):
        body_id = int(raw_body_id)
        if body_id in expected_ids:
            indices.setdefault(body_id, []).append(index)
    rows = table.to_pydict()
    records: list[dict[str, Any]] = []
    for canary in canaries:
        body_id = int(canary["body_id"])
        matches = indices.get(body_id, [])
        unique = len(matches) == 1
        row = {name: rows[name][matches[0]] for name in rows} if unique else {}
        side = str(canary["side"])
        fields_match = unique and all(
            row.get(field) == canary[f"expected_{field}"]
            for field in ("status", "type", "superclass")
        )
        instance_matches_side = unique and str(row.get("instance", "")).endswith(f"_{side}")
        records.append(
            {
                "body_id": body_id,
                "label": canary["label"],
                "rows": len(matches),
                "observed_status": row.get("status"),
                "observed_type": row.get("type"),
                "observed_instance": row.get("instance"),
                "observed_superclass": row.get("superclass"),
                "fields_match": fields_match,
                "instance_matches_side": instance_matches_side,
                "valid": bool(unique and fields_match and instance_matches_side),
            }
        )
    return {
        "annotations_sha256": sha256_file(annotations_path),
        "canary_config_sha256": sha256_file(canary_config_path),
        "canaries": records,
        "valid": all(record["valid"] for record in records),
    }


def _cross_connectome_review(supplement_root: Path, card_path: Path) -> dict[str, Any]:
    card = _read_json(card_path)
    if card.get("source_commit") != "67767d2233657983993ff6c2be48e836a935863c":
        raise DatasetError("MaleCNS paper supplement is not pinned to the reviewed commit")
    artifact_records = {
        str(artifact["filename"]): artifact for artifact in card.get("artifacts", [])
    }
    for artifact in artifact_records.values():
        path = supplement_root / str(artifact["filename"])
        if not path.is_file() or path.stat().st_size != artifact.get("bytes"):
            raise DatasetError(f"MaleCNS supplement artifact is missing or changed: {path}")
        if sha256_file(path) != artifact.get("sha256"):
            raise DatasetError(f"MaleCNS supplement checksum changed: {path}")

    edge_path = supplement_root / "mcns_fw_edge_comp.feather"
    table = feather.read_table(edge_path)
    expected_columns = {
        "pre",
        "post",
        "weight_m",
        "weight_f",
        "t",
        "p_corr",
        "verdict_corr",
    }
    if set(table.column_names) != expected_columns:
        raise DatasetError("MaleCNS/FlyWire aligned-edge schema changed")
    male = table.column("weight_m").to_numpy(zero_copy_only=False)
    female = table.column("weight_f").to_numpy(zero_copy_only=False)
    finite_nonnegative = bool(
        np.all(np.isfinite(male))
        and np.all(np.isfinite(female))
        and np.all(male >= 0)
        and np.all(female >= 0)
    )
    verdict_counts = {
        str(item["values"]): int(item["counts"])
        for item in pc.value_counts(table.column("verdict_corr")).to_pylist()
    }
    mappings = _read_json(supplement_root / "mcns_fw_edge_comp_mappings.json")
    numeric_mapping_ids = all(str(key).isdigit() for key in mappings)
    nonempty_mapping_labels = all(bool(value) for value in mappings.values())

    notebook = _read_json(supplement_root / "quantify-neuron-connections.ipynb")
    notebook_text = json.dumps(notebook)
    notebook_counts_present = all(str(value) in notebook_text for value in NOTEBOOK_OUTPUT_COUNTS)
    expected_edge_rows = int(artifact_records[edge_path.name]["rows"])
    expected_mapping_rows = int(
        artifact_records["mcns_fw_edge_comp_mappings.json"]["entries"]
    )
    valid = (
        table.num_rows == expected_edge_rows
        and finite_nonnegative
        and len(mappings) == expected_mapping_rows
        and numeric_mapping_ids
        and nonempty_mapping_labels
        and notebook_counts_present
    )
    return {
        "source_commit": card["source_commit"],
        "scope": "paper-author MaleCNS-to-FlyWire cross-matched central-brain type edges",
        "aligned_edge_rows": table.num_rows,
        "mapping_rows": len(mappings),
        "finite_nonnegative_weights": finite_nonnegative,
        "verdict_counts": verdict_counts,
        "paper_count_outputs_present": notebook_counts_present,
        "valid": valid,
        "claim_boundary": (
            "Cross-sex, cross-specimen structural comparison with MaleCNS VNC connections "
            "excluded; not physiological conservation"
        ),
    }


def audit_structural_references(
    root: Path,
    supplement_card: Path,
    canary_config: Path,
    output: Path,
) -> dict[str, Any]:
    """Audit paper counts, structural canary motifs, confidence, and FlyWire comparison."""
    root = root.resolve()
    evidence_root = root / "evidence" / "male-cns-v1.0"
    contact = _read_json(evidence_root / "contact-structural-audit.json")
    universe = _read_json(evidence_root / "body-universe-sensitivity.json")
    if contact.get("valid") is not True:
        raise DatasetError("Strict contact audit must pass before structural reference audit")
    checks = contact.get("checks", {})
    polyads = checks.get("polyadic_fanout_preserved", {})
    observed = {
        "proofread_neurons_traced_status": int(
            universe["universes"]["Traced"]["annotation_body_count"]
        ),
        "traced_graph_edges": int(universe["universes"]["Traced"]["edges"]),
        "presynaptic_sites": int(polyads["presynaptic_sites"]),
        "postsynaptic_contacts": int(
            _read_json(
                root
                / "derived"
                / "male-cns-v1.0"
                / "contacts"
                / "syn-partners"
                / "manifest.json"
            )["rows"]
        ),
    }
    count_checks = {
        "proofread_neurons_within_2pct": _relative_error(
            observed["proofread_neurons_traced_status"], PAPER_COUNTS["proofread_neurons"]
        )
        <= 0.02,
        "graph_edges_within_1pct": _relative_error(
            observed["traced_graph_edges"], PAPER_COUNTS["valid_superclass_graph_edges"]
        )
        <= 0.01,
        "presynaptic_sites_within_2pct": _relative_error(
            observed["presynaptic_sites"], PAPER_COUNTS["presynaptic_sites_rounded"]
        )
        <= 0.02,
        "postsynaptic_contacts_within_1pct": _relative_error(
            observed["postsynaptic_contacts"], PAPER_COUNTS["postsynaptic_contacts_rounded"]
        )
        <= 0.01,
    }
    motif = universe.get("canary_motif", {})
    motif_valid = (
        polyads.get("passed") is True
        and int(polyads.get("polyadic_sites", 0)) > 0
        and int(polyads.get("maximum_fanout", 0)) > 1
        and int(motif.get("internal_edges", 0)) > 0
        and int(motif.get("internal_contacts", 0)) > 0
    )
    confidence = _confidence_sensitivity(
        root / "derived" / "male-cns-v1.0" / "contacts" / "syn-partners"
    )
    annotation_canaries = _annotation_canary_review(
        root
        / "raw"
        / "male-cns-v1.0"
        / "body-annotations-male-cns-v1.0-minconf-0.5.feather",
        canary_config.resolve(),
    )
    cross_connectome = _cross_connectome_review(
        root / "raw" / "auxiliary" / "berg-malecns-2025-supplement",
        supplement_card.resolve(),
    )
    valid = (
        all(count_checks.values())
        and motif_valid
        and confidence["valid"]
        and confidence["rows"] == observed["postsynaptic_contacts"]
        and annotation_canaries["valid"]
        and cross_connectome["valid"]
    )
    report = {
        "schema_version": "1.0",
        "audit": "MaleCNS-v1.0-structural-reference-audit",
        "paper_reference": "https://doi.org/10.1016/j.cell.2026.08.015",
        "paper_counts": PAPER_COUNTS,
        "observed_v1": observed,
        "count_checks": count_checks,
        "count_definition_note": (
            "Paper notebook outputs are for v0.9 and its valid-superclass/weight-threshold "
            "definitions; v1.0 status-universe values are compared with declared tolerances."
        ),
        "selected_motifs": {
            "polyadic_sites": polyads,
            "bilateral_sensorimotor_canary": motif,
            "annotation_canaries": annotation_canaries,
            "valid": motif_valid and annotation_canaries["valid"],
        },
        "confidence_sensitivity": confidence,
        "cross_connectome_comparison": cross_connectome,
        "valid": bool(valid),
        "validation_tier_awarded": None,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return {**report, "report": str(output), "report_sha256": sha256_file(output)}
