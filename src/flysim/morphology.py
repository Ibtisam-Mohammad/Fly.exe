# SPDX-License-Identifier: GPL-2.0-or-later
"""Lazy immutable SWC canary cache for Stage-0 morphology validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path
from typing import Any

from flysim.errors import DatasetError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_swc(path: Path) -> dict[str, Any]:
    """Validate SWC syntax, finite 8-nm coordinates, node identity, and parents."""
    node_ids: set[int] = set()
    parent_ids: list[int] = []
    roots = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 7:
                raise DatasetError(f"Invalid SWC field count at {path}:{line_number}")
            try:
                node_id = int(fields[0])
                _ = int(fields[1])
                coordinates = tuple(float(value) for value in fields[2:6])
                parent_id = int(fields[6])
            except ValueError as exc:
                raise DatasetError(f"Invalid SWC value at {path}:{line_number}") from exc
            if node_id <= 0 or node_id in node_ids:
                raise DatasetError(f"Invalid or duplicate SWC node ID at {path}:{line_number}")
            if not all(math.isfinite(value) for value in coordinates):
                raise DatasetError(f"Non-finite SWC coordinate/radius at {path}:{line_number}")
            node_ids.add(node_id)
            parent_ids.append(parent_id)
            roots += parent_id == -1
    if not node_ids or roots < 1:
        raise DatasetError(f"SWC has no nodes or root: {path}")
    missing_parents = sorted({parent for parent in parent_ids if parent != -1} - node_ids)
    if missing_parents:
        raise DatasetError(f"SWC references missing parent nodes: {missing_parents[:10]}")
    return {"nodes": len(node_ids), "roots": roots, "valid": True}


def sync_morphology_canaries(config_path: Path, output: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    existing: dict[str, Any] = {}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    existing_by_id = {int(item["body_id"]): item for item in existing.get("canaries", [])}
    records: list[dict[str, Any]] = []
    for canary in config["canaries"]:
        body_id = int(canary["body_id"])
        destination = output / f"{body_id}.swc"
        locked = existing_by_id.get(body_id)
        if destination.exists() and not locked:
            raise DatasetError(f"Unregistered skeleton will not be overwritten: {destination}")
        if destination.exists() and locked:
            if _sha256(destination) != locked["sha256"]:
                raise DatasetError(f"Locked skeleton changed: {destination}")
            swc = validate_swc(destination)
            records.append({**locked, **swc})
            continue
        if locked and not destination.exists():
            raise DatasetError(f"Locked skeleton is missing: {destination}")
        url = f"{config['base_url']}/{body_id}.swc"
        request = urllib.request.Request(url, headers={"User-Agent": "malecns-flysim/0.1"})
        temporary = destination.with_suffix(".swc.part")
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("xb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
            identity = {
                "gcs_generation": response.headers.get("x-goog-generation"),
                "etag": response.headers.get("ETag", "").strip('"') or None,
            }
        swc = validate_swc(temporary)
        os.replace(temporary, destination)
        records.append(
            {
                **canary,
                **swc,
                "filename": destination.name,
                "bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
                **identity,
            }
        )
        manifest = {
            "schema_version": "1.0",
            "dataset_id": config["dataset_id"],
            "coordinate_units": config["coordinate_units"],
            "config_sha256": _sha256(config_path),
            "canaries": records,
            "complete": False,
        }
        partial_manifest = manifest_path.with_suffix(".json.part")
        partial_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(partial_manifest, manifest_path)
    manifest = {
        "schema_version": "1.0",
        "dataset_id": config["dataset_id"],
        "coordinate_units": config["coordinate_units"],
        "config_sha256": _sha256(config_path),
        "canaries": records,
        "complete": len(records) == len(config["canaries"]),
    }
    partial_manifest = manifest_path.with_suffix(".json.part")
    partial_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(partial_manifest, manifest_path)
    return {
        **manifest,
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": _sha256(manifest_path),
    }
