# SPDX-License-Identifier: GPL-2.0-or-later
"""Streaming sensitivity audit for alternative MaleCNS runtime body universes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc

from flysim.errors import DatasetError

UNIVERSES: dict[str, tuple[str, ...] | None] = {
    "all-segment": None,
    "Traced": ("Traced",),
    "Traced+Assign": ("Traced", "Assign"),
    "Traced+Assign+Anchor": ("Traced", "Assign", "Anchor"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _contains(sorted_ids: np.ndarray, values: np.ndarray) -> np.ndarray:
    indices = np.searchsorted(sorted_ids, values)
    in_bounds = indices < len(sorted_ids)
    result = np.zeros(len(values), dtype=np.bool_)
    result[in_bounds] = sorted_ids[indices[in_bounds]] == values[in_bounds]
    return result


def audit_body_universes(
    annotations_path: Path,
    aggregate_path: Path,
    output: Path,
    *,
    canary_body_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    annotations = feather.read_table(annotations_path, columns=["bodyId", "status"])
    body_ids = annotations.column("bodyId").to_numpy(zero_copy_only=False).astype(np.uint64)
    statuses = np.asarray(annotations.column("status").to_pylist(), dtype=object)
    universe_ids: dict[str, np.ndarray] = {}
    results: dict[str, dict[str, Any]] = {
        "all-segment": {"annotation_body_count": None, "edges": 0, "contacts": 0}
    }
    for name, allowed in UNIVERSES.items():
        if allowed is None:
            continue
        selected = np.isin(statuses, allowed)
        ids = np.unique(body_ids[selected])
        universe_ids[name] = ids
        results[name] = {
            "annotation_body_count": len(ids),
            "edges": 0,
            "contacts": 0,
        }

    canaries = np.asarray(sorted(set(canary_body_ids)), dtype=np.uint64)
    canary_edges = 0
    canary_contacts = 0
    with pa.memory_map(str(aggregate_path), "r") as source:
        reader = ipc.open_file(source)
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index).select(["body_pre", "body_post", "weight"])
            pre = batch.column(0).to_numpy(zero_copy_only=False).astype(np.uint64, copy=False)
            post = batch.column(1).to_numpy(zero_copy_only=False).astype(np.uint64, copy=False)
            weights = batch.column(2).to_numpy(zero_copy_only=False).astype(np.uint64, copy=False)
            if np.any(weights == 0):
                raise DatasetError("Aggregate universe audit found a zero-contact edge")
            results["all-segment"]["edges"] += batch.num_rows
            results["all-segment"]["contacts"] += int(weights.sum(dtype=np.uint64))
            for name, ids in universe_ids.items():
                keep = _contains(ids, pre) & _contains(ids, post)
                results[name]["edges"] += int(np.count_nonzero(keep))
                results[name]["contacts"] += int(weights[keep].sum(dtype=np.uint64))
            if canaries.size:
                canary_keep = _contains(canaries, pre) & _contains(canaries, post)
                canary_edges += int(np.count_nonzero(canary_keep))
                canary_contacts += int(weights[canary_keep].sum(dtype=np.uint64))

    all_edges = results["all-segment"]["edges"]
    all_contacts = results["all-segment"]["contacts"]
    for result in results.values():
        result["edge_fraction_of_all"] = result["edges"] / all_edges
        result["contact_fraction_of_all"] = result["contacts"] / all_contacts
    report = {
        "schema_version": "1.0",
        "audit": "MaleCNS-v1.0-body-universe-sensitivity",
        "annotations": str(annotations_path.resolve()),
        "annotations_sha256": _sha256(annotations_path),
        "aggregate": str(aggregate_path.resolve()),
        "aggregate_sha256": _sha256(aggregate_path),
        "universes": results,
        "canary_motif": {
            "body_ids": canaries.tolist(),
            "internal_edges": canary_edges,
            "internal_contacts": canary_contacts,
        },
        "decision": "proposed",
        "validation_tier_awarded": None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return {**report, "report": str(output.resolve()), "report_sha256": _sha256(output)}
