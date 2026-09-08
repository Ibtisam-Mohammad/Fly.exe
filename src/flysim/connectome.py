# SPDX-License-Identifier: GPL-2.0-or-later
"""Loss-aware import of the MaleCNS aggregate chemical-contact graph."""

from __future__ import annotations

import gc
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.feather as pa_feather
import pyarrow.ipc as pa_ipc

from .errors import DatasetError

SOURCE_ALIASES = ("body_pre", "bodyPre", "source", "source_id", "pre_id")
TARGET_ALIASES = ("body_post", "bodyPost", "target", "target_id", "post_id")
COUNT_ALIASES = ("weight", "count", "syn_count", "contact_count", "synapse_count")
BODY_ID_ALIASES = ("bodyId", "body", "body_id")
STREAMING_THRESHOLD_BYTES = 256 * 1024 * 1024


def _resolve_column(names: list[str], aliases: tuple[str, ...], role: str) -> str:
    for alias in aliases:
        if alias in names:
            return alias
    raise DatasetError(f"Could not resolve {role} column; found {names}, expected one of {aliases}")


def _record_batches(path: Path) -> tuple[pa.Schema, Iterator[pa.RecordBatch]]:
    if path.suffix.lower() == ".csv":
        table = pa_csv.read_csv(path)
        return table.schema, iter(table.to_batches())
    source = pa.memory_map(str(path), "r")
    try:
        reader = pa_ipc.open_file(source)
    except pa.ArrowInvalid as exc:
        source.close()
        raise DatasetError(f"Not a readable Arrow/Feather file: {path}") from exc

    def batches() -> Iterator[pa.RecordBatch]:
        try:
            for index in range(reader.num_record_batches):
                yield reader.get_batch(index)
        finally:
            source.close()

    return reader.schema, batches()


@dataclass(frozen=True, slots=True)
class SparseConnectome:
    body_ids: np.ndarray
    source_indices: np.ndarray
    target_indices: np.ndarray
    contact_counts: np.ndarray
    source_release: str
    source_sha256: str

    def validate(self) -> None:
        if self.body_ids.dtype != np.uint64:
            raise DatasetError("body_ids must be uint64")
        if self.source_indices.dtype != np.uint32 or self.target_indices.dtype != np.uint32:
            raise DatasetError("dense indices must be uint32")
        if self.contact_counts.dtype != np.uint32:
            raise DatasetError("contact counts must be uint32")
        if len(self.source_indices) != len(self.target_indices) or len(self.source_indices) != len(
            self.contact_counts
        ):
            raise DatasetError("edge arrays differ in length")
        if self.body_ids.size and not np.all(self.body_ids[:-1] < self.body_ids[1:]):
            raise DatasetError("body IDs must be strictly increasing")
        if self.source_indices.size:
            if int(self.source_indices.max()) >= len(self.body_ids):
                raise DatasetError("source dense index out of bounds")
            if int(self.target_indices.max()) >= len(self.body_ids):
                raise DatasetError("target dense index out of bounds")
        if np.any(self.contact_counts == 0):
            raise DatasetError("zero-contact edges are invalid")

    @property
    def neuron_count(self) -> int:
        return int(self.body_ids.size)

    @property
    def edge_count(self) -> int:
        return int(self.contact_counts.size)

    def dense_index(self, body_id: int) -> int:
        index = int(np.searchsorted(self.body_ids, np.uint64(body_id)))
        if index == len(self.body_ids) or int(self.body_ids[index]) != body_id:
            raise KeyError(body_id)
        return index

    def body_id(self, dense_index: int) -> int:
        return int(self.body_ids[dense_index])

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                body_ids=self.body_ids,
                source_indices=self.source_indices,
                target_indices=self.target_indices,
                contact_counts=self.contact_counts,
                source_release=np.array(self.source_release),
                source_sha256=np.array(self.source_sha256),
            )
        os.replace(temporary, path)

    def save_directory(self, path: Path, *, extra_manifest: dict[str, object]) -> None:
        """Save an mmap-friendly graph directory without materializing array copies."""
        self.validate()
        if path.exists():
            raise DatasetError(f"Refusing to overwrite graph directory: {path}")
        temporary = path.with_name(path.name + ".part")
        if temporary.exists():
            raise DatasetError(f"Incomplete graph directory already exists: {temporary}")
        temporary.mkdir(parents=True)
        np.save(temporary / "body_ids.npy", self.body_ids, allow_pickle=False)
        np.save(temporary / "source_indices.npy", self.source_indices, allow_pickle=False)
        np.save(temporary / "target_indices.npy", self.target_indices, allow_pickle=False)
        np.save(temporary / "contact_counts.npy", self.contact_counts, allow_pickle=False)
        manifest = {
            "schema_version": "1.1",
            "array_sha256": graph_array_hashes(temporary),
            "source_release": self.source_release,
            "source_sha256": self.source_sha256,
            "neuron_count": self.neuron_count,
            "edge_count": self.edge_count,
            "threshold_applied": False,
            "body_id_dtype": "uint64",
            "dense_index_dtype": "uint32",
            "contact_count_dtype": "uint32",
            **extra_manifest,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)

    @classmethod
    def load(cls, path: Path) -> SparseConnectome:
        if path.is_dir():
            manifest_path = path / "manifest.json"
            if not manifest_path.exists():
                raise DatasetError(f"Graph manifest is missing: {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            graph = cls(
                body_ids=np.load(path / "body_ids.npy", mmap_mode="r", allow_pickle=False),
                source_indices=np.load(
                    path / "source_indices.npy", mmap_mode="r", allow_pickle=False
                ),
                target_indices=np.load(
                    path / "target_indices.npy", mmap_mode="r", allow_pickle=False
                ),
                contact_counts=np.load(
                    path / "contact_counts.npy", mmap_mode="r", allow_pickle=False
                ),
                source_release=str(manifest["source_release"]),
                source_sha256=str(manifest["source_sha256"]),
            )
            graph.validate()
            verify_graph_array_hashes(path, manifest)
            return graph
        with np.load(path, allow_pickle=False) as data:
            graph = cls(
                body_ids=data["body_ids"],
                source_indices=data["source_indices"],
                target_indices=data["target_indices"],
                contact_counts=data["contact_counts"],
                source_release=str(data["source_release"]),
                source_sha256=str(data["source_sha256"]),
            )
        graph.validate()
        return graph


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


GRAPH_ARRAY_FILENAMES = (
    "body_ids.npy",
    "source_indices.npy",
    "target_indices.npy",
    "contact_counts.npy",
)


def graph_array_hashes(path: Path) -> dict[str, str]:
    """SHA-256 of every runtime array in a graph directory."""
    return {name: file_sha256(path / name) for name in GRAPH_ARRAY_FILENAMES}


def verify_graph_array_hashes(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify the runtime arrays against the hashes recorded in their manifest.

    The graph loaded by every Track A run used to carry no per-array hash at all, so a
    changed ``.npy`` file was undetectable. Manifests written before this check exist on
    disk; they report ``verified: False`` with a reason instead of silently passing.
    """
    recorded = manifest.get("array_sha256")
    if not isinstance(recorded, dict) or not recorded:
        return {
            "verified": False,
            "reason": "the graph manifest records no per-array hashes",
        }
    missing = sorted(set(GRAPH_ARRAY_FILENAMES) - recorded.keys())
    if missing:
        raise DatasetError(f"Graph manifest is missing array hashes: {missing}")
    for name in GRAPH_ARRAY_FILENAMES:
        observed = file_sha256(path / name)
        if observed != recorded[name]:
            raise DatasetError(
                f"Runtime graph array changed since import: {path / name} "
                f"(recorded {recorded[name]}, observed {observed})"
            )
    return {"verified": True, "arrays": len(GRAPH_ARRAY_FILENAMES)}


def import_aggregate_graph(
    source_path: Path,
    output_path: Path,
    source_release: str = "male-cns:v1.0",
    streaming_threshold_bytes: int = STREAMING_THRESHOLD_BYTES,
    body_ids_source: Path | None = None,
    body_statuses: tuple[str, ...] | None = None,
) -> SparseConnectome:
    """Import every aggregate edge; no confidence or weight threshold is applied."""
    use_streaming = (
        source_path.suffix.lower() != ".csv"
        and source_path.stat().st_size >= streaming_threshold_bytes
    )
    if use_streaming:
        return _import_streaming_aggregate_graph(
            source_path,
            output_path,
            source_release,
            body_ids_source=body_ids_source,
            body_statuses=body_statuses,
        )

    schema, batches = _record_batches(source_path)
    names = schema.names
    source_name = _resolve_column(names, SOURCE_ALIASES, "presynaptic body")
    target_name = _resolve_column(names, TARGET_ALIASES, "postsynaptic body")
    count_name = _resolve_column(names, COUNT_ALIASES, "contact count")

    sources: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    counts: list[np.ndarray] = []
    for batch in batches:
        selected = batch.select([source_name, target_name, count_name])
        if any(column.null_count for column in selected.columns):
            raise DatasetError("Aggregate graph contains null source, target, or count values")
        sources.append(selected.column(0).to_numpy(zero_copy_only=False).astype(np.uint64))
        targets.append(selected.column(1).to_numpy(zero_copy_only=False).astype(np.uint64))
        counts.append(selected.column(2).to_numpy(zero_copy_only=False).astype(np.uint64))
    if not sources:
        raise DatasetError("Aggregate graph contains no edges")

    source_ids = np.concatenate(sources)
    target_ids = np.concatenate(targets)
    raw_counts = np.concatenate(counts)
    if np.any(raw_counts == 0):
        raise DatasetError("Aggregate source contains zero-contact edges")
    body_ids = np.unique(np.concatenate((source_ids, target_ids))).astype(np.uint64)
    dense_sources = np.searchsorted(body_ids, source_ids).astype(np.uint32)
    dense_targets = np.searchsorted(body_ids, target_ids).astype(np.uint32)

    order = np.lexsort((dense_targets, dense_sources))
    dense_sources = dense_sources[order]
    dense_targets = dense_targets[order]
    raw_counts = raw_counts[order]
    starts = np.r_[
        True,
        (dense_sources[1:] != dense_sources[:-1])
        | (dense_targets[1:] != dense_targets[:-1]),
    ]
    indices = np.flatnonzero(starts)
    aggregate_counts = np.add.reduceat(raw_counts, indices)
    if np.any(aggregate_counts > np.iinfo(np.uint32).max):
        raise DatasetError("An aggregate edge exceeds uint32 contact-count capacity")

    graph = SparseConnectome(
        body_ids=body_ids,
        source_indices=dense_sources[indices].astype(np.uint32),
        target_indices=dense_targets[indices].astype(np.uint32),
        contact_counts=aggregate_counts.astype(np.uint32),
        source_release=source_release,
        source_sha256=file_sha256(source_path),
    )
    graph.save(output_path)
    sidecar = {
        "schema_version": "1.0",
        "source_release": source_release,
        "source_path": str(source_path.resolve()),
        "source_sha256": graph.source_sha256,
        "neuron_count": graph.neuron_count,
        "edge_count": graph.edge_count,
        "threshold_applied": False,
        "body_id_dtype": "uint64",
        "dense_index_dtype": "uint32",
        "contact_count_dtype": "uint32",
    }
    output_path.with_suffix(".json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return graph


def _import_streaming_aggregate_graph(
    source_path: Path,
    output_path: Path,
    source_release: str,
    *,
    body_ids_source: Path | None,
    body_statuses: tuple[str, ...] | None,
) -> SparseConnectome:
    """Import an already-aggregated large table with bounded resident memory.

    The official MaleCNS connectome-weights artifact defines one row per aggregate
    segment pair. This path validates types/ranges and preserves every row retained
    by the explicit biological-body universe. It does not reinterpret a contact
    count as a functional weight.
    """
    schema, batches = _record_batches(source_path)
    names = schema.names
    source_name = _resolve_column(names, SOURCE_ALIASES, "presynaptic body")
    target_name = _resolve_column(names, TARGET_ALIASES, "postsynaptic body")
    count_name = _resolve_column(names, COUNT_ALIASES, "contact count")

    max_uint32 = np.iinfo(np.uint32).max
    annotation_candidate_count: int | None = None
    excluded_edge_count = 0
    excluded_contact_count = 0
    if body_ids_source is not None:
        annotation_schema = pa_feather.read_table(body_ids_source, memory_map=True).schema
        body_name = _resolve_column(annotation_schema.names, BODY_ID_ALIASES, "body ID")
        annotation_columns = [body_name]
        if body_statuses is not None:
            if "status" not in annotation_schema.names:
                raise DatasetError("Annotation status filter requested but status is absent")
            annotation_columns.append("status")
        annotation_table = pa_feather.read_table(
            body_ids_source, columns=annotation_columns, memory_map=True
        )
        annotation_ids = annotation_table.column(body_name)
        if annotation_ids.null_count:
            raise DatasetError("Annotation body IDs contain null values")
        raw_body_ids = annotation_ids.to_numpy(zero_copy_only=False)
        if np.any(raw_body_ids < 0):
            raise DatasetError("Annotation body IDs must be nonnegative")
        if body_statuses is not None:
            allowed_statuses = frozenset(body_statuses)
            status_values = annotation_table.column("status").to_pylist()
            status_mask = np.fromiter(
                (status in allowed_statuses for status in status_values),
                dtype=np.bool_,
                count=len(status_values),
            )
            raw_body_ids = raw_body_ids[status_mask]
            if len(raw_body_ids) == 0:
                raise DatasetError(f"No annotation bodies have statuses {body_statuses}")
        annotation_body_ids = np.unique(raw_body_ids).astype(np.uint64)
        annotation_candidate_count = len(annotation_body_ids)
        annotation_body_id_set = {int(body_id) for body_id in annotation_body_ids}
        edge_count = 0
        for batch in batches:
            selected = batch.select([source_name, target_name, count_name])
            _validate_aggregate_batch(selected, max_uint32)
            source_values = selected.column(0).to_numpy(zero_copy_only=False).astype(
                np.uint64, copy=False
            )
            target_values = selected.column(1).to_numpy(zero_copy_only=False).astype(
                np.uint64, copy=False
            )
            keep = _values_present_in_set(
                source_values, annotation_body_id_set
            ) & _values_present_in_set(target_values, annotation_body_id_set)
            retained = int(np.count_nonzero(keep))
            edge_count += retained
            excluded_edge_count += batch.num_rows - retained
            count_values = selected.column(2).to_numpy(zero_copy_only=False)
            excluded_contact_count += int(
                count_values[~keep].sum(dtype=np.uint64)
            )
        body_ids = annotation_body_ids
    else:
        body_ids = np.empty(0, dtype=np.uint64)
        edge_count = 0
        for batch in batches:
            selected = batch.select([source_name, target_name, count_name])
            _validate_aggregate_batch(selected, max_uint32)
            source_values = selected.column(0).to_numpy(zero_copy_only=False)
            target_values = selected.column(1).to_numpy(zero_copy_only=False)
            batch_ids = np.unique(np.concatenate((source_values, target_values))).astype(
                np.uint64
            )
            body_ids = np.union1d(body_ids, batch_ids).astype(np.uint64, copy=False)
            edge_count += batch.num_rows
    if edge_count == 0:
        raise DatasetError("Aggregate graph contains no edges")
    if len(body_ids) > max_uint32:
        raise DatasetError("The graph has more neurons than a uint32 dense index can address")

    if output_path.exists():
        raise DatasetError(f"Refusing to overwrite graph directory: {output_path}")
    temporary = output_path.with_name(output_path.name + ".part")
    if temporary.exists():
        raise DatasetError(f"Incomplete graph directory already exists: {temporary}")
    temporary.mkdir(parents=True)
    saved_sources = np.lib.format.open_memmap(
        temporary / "source_indices.npy", mode="w+", dtype=np.uint32, shape=(edge_count,)
    )
    saved_targets = np.lib.format.open_memmap(
        temporary / "target_indices.npy", mode="w+", dtype=np.uint32, shape=(edge_count,)
    )
    saved_counts = np.lib.format.open_memmap(
        temporary / "contact_counts.npy", mode="w+", dtype=np.uint32, shape=(edge_count,)
    )
    dense_by_body_id = {int(body_id): index for index, body_id in enumerate(body_ids)}
    _, second_pass = _record_batches(source_path)
    offset = 0
    for batch in second_pass:
        selected = batch.select([source_name, target_name, count_name])
        _validate_aggregate_batch(selected, max_uint32)
        source_values = selected.column(0).to_numpy(zero_copy_only=False).astype(
            np.uint64, copy=False
        )
        target_values = selected.column(1).to_numpy(zero_copy_only=False).astype(
            np.uint64, copy=False
        )
        count_values = selected.column(2).to_numpy(zero_copy_only=False)
        if body_ids_source is not None:
            keep = _values_present_in_set(
                source_values, dense_by_body_id
            ) & _values_present_in_set(target_values, dense_by_body_id)
            source_values = source_values[keep]
            target_values = target_values[keep]
            count_values = count_values[keep]
        next_offset = offset + len(source_values)
        source_indices = np.fromiter(
            (dense_by_body_id.get(int(value), -1) for value in source_values),
            dtype=np.int64,
            count=len(source_values),
        )
        target_indices = np.fromiter(
            (dense_by_body_id.get(int(value), -1) for value in target_values),
            dtype=np.int64,
            count=len(target_values),
        )
        if np.any(source_indices < 0) or np.any(target_indices < 0):
            raise DatasetError("Connectome contains an unresolved body ID")
        saved_sources[offset:next_offset] = source_indices.astype(np.uint32)
        saved_targets[offset:next_offset] = target_indices.astype(np.uint32)
        saved_counts[offset:next_offset] = count_values.astype(np.uint32, copy=False)
        offset = next_offset
    if offset != edge_count:
        raise DatasetError(f"Arrow row metadata reported {edge_count}, imported {offset}")

    saved_body_ids = np.lib.format.open_memmap(
        temporary / "body_ids.npy", mode="w+", dtype=np.uint64, shape=body_ids.shape
    )
    saved_body_ids[:] = body_ids
    for array in (saved_body_ids, saved_sources, saved_targets, saved_counts):
        array.flush()
    source_hash = file_sha256(source_path)
    manifest = {
        "schema_version": "1.1",
        "storage": "npy-directory-v1",
        "array_sha256": graph_array_hashes(temporary),
        "body_ids_source_sha256": (
            file_sha256(body_ids_source) if body_ids_source else None
        ),
        "source_release": source_release,
        "source_path": str(source_path.resolve()),
        "source_sha256": source_hash,
        "source_contract": "official aggregate segment-pair contact table",
        "body_ids_source": str(body_ids_source.resolve()) if body_ids_source else None,
        "body_statuses": list(body_statuses) if body_statuses else None,
        "body_universe_assumption_id": "DATA-04" if body_statuses else None,
        "annotation_candidate_count": annotation_candidate_count,
        "raw_edge_count": edge_count + excluded_edge_count,
        "excluded_edge_count": excluded_edge_count,
        "excluded_contact_count": excluded_contact_count,
        "body_universe_filter_applied": body_ids_source is not None,
        "duplicate_aggregation_performed": False,
        "neuron_count": int(body_ids.size),
        "edge_count": edge_count,
        "threshold_applied": False,
        "body_id_dtype": "uint64",
        "dense_index_dtype": "uint32",
        "contact_count_dtype": "uint32",
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    del array, saved_body_ids, saved_sources, saved_targets, saved_counts
    gc.collect()
    os.replace(temporary, output_path)
    return SparseConnectome.load(output_path)


def _validate_aggregate_batch(selected: pa.RecordBatch, max_uint32: int) -> None:
    if any(column.null_count for column in selected.columns):
        raise DatasetError("Aggregate graph contains null source, target, or count values")
    source_values = selected.column(0).to_numpy(zero_copy_only=False)
    target_values = selected.column(1).to_numpy(zero_copy_only=False)
    count_values = selected.column(2).to_numpy(zero_copy_only=False)
    if np.any(source_values < 0) or np.any(target_values < 0):
        raise DatasetError("Body IDs must be nonnegative")
    if np.any(count_values <= 0):
        raise DatasetError("Aggregate source contains nonpositive contact counts")
    if np.any(count_values > max_uint32):
        raise DatasetError("An aggregate edge exceeds uint32 contact-count capacity")


def _values_present_in_set(
    values: np.ndarray, candidates: set[int] | dict[int, int]
) -> np.ndarray:
    return np.fromiter(
        (int(value) in candidates for value in values),
        dtype=np.bool_,
        count=len(values),
    )
