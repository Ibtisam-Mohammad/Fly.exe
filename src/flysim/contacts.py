# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded-memory normalization of immutable MaleCNS Arrow contact tables."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from flysim.datasets import sha256_file
from flysim.errors import DatasetError

DEFAULT_MEMORY_LIMIT_GB = 3.0
DEFAULT_MINIMUM_FREE_GB = 80.0
DEFAULT_ROW_GROUP_ROWS = 262_144
DEFAULT_SHARD_ROWS = 1_048_576
DEFAULT_ZSTD_LEVEL = 3


@dataclass(frozen=True, slots=True)
class ContactImportResult:
    artifact_id: str
    output: Path
    source_sha256: str
    rows: int
    shards: int
    peak_rss_bytes: int
    manifest_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "output": str(self.output),
            "source_sha256": self.source_sha256,
            "rows": self.rows,
            "shards": self.shards,
            "peak_rss_bytes": self.peak_rss_bytes,
            "manifest_sha256": self.manifest_sha256,
        }


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if os.name == "nt" else value * 1024)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _schema_sha256(schema: pa.Schema) -> str:
    return hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()


def _logical_table_sha256(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _validate_checkpoint_shards(output: Path, shards: list[dict[str, Any]]) -> None:
    for shard in shards:
        path = output / str(shard["filename"])
        if not path.is_file():
            raise DatasetError(f"Verified contact shard is missing: {path}")
        if path.stat().st_size != shard["bytes"] or sha256_file(path) != shard["sha256"]:
            raise DatasetError(f"Verified contact shard changed: {path}")


def _normalize_unsigned_ids(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Losslessly expose nonnegative biological identifiers as uint64."""
    normalized = batch
    for name in batch.schema.names:
        field = batch.schema.field(name)
        if not (name == "sv" or name.startswith("body")) or not pa.types.is_int64(field.type):
            continue
        column_index = normalized.schema.get_field_index(name)
        column = normalized.column(column_index)
        has_negative = bool(pc.any(pc.less(column, pa.scalar(0, pa.int64()))).as_py())
        if has_negative:
            raise DatasetError(f"Identifier column {name!r} contains negative values")
        normalized = normalized.set_column(column_index, name, pc.cast(column, pa.uint64()))
    return normalized


def import_contact_table(
    artifact_id: str,
    source: Path,
    output: Path,
    *,
    resume: bool = True,
    memory_limit_gb: float = DEFAULT_MEMORY_LIMIT_GB,
    minimum_free_gb: float = DEFAULT_MINIMUM_FREE_GB,
    row_group_rows: int = DEFAULT_ROW_GROUP_ROWS,
    shard_rows: int = DEFAULT_SHARD_ROWS,
    expected_sha256: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> ContactImportResult:
    """Stream native IPC batches into immutable, resumable Parquet shards."""
    if not source.is_file():
        raise DatasetError(f"Contact source is missing: {source}")
    if row_group_rows <= 0 or shard_rows <= 0 or shard_rows % row_group_rows:
        raise DatasetError("Shard rows must be a positive multiple of row-group rows")
    output.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(output).free / (1024**3)
    if free_gb < minimum_free_gb:
        raise DatasetError(
            f"Refusing contact import: {output.resolve()} has {free_gb:.1f} GB free; "
            f"at least {minimum_free_gb:.1f} GB is required"
        )

    source_sha256 = sha256_file(source)
    if expected_sha256 is not None and source_sha256 != expected_sha256:
        raise DatasetError(
            f"Contact source checksum mismatch for {artifact_id}: expected "
            f"{expected_sha256}, got {source_sha256}"
        )
    checkpoint_path = output / "import-checkpoint.json"
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("source_sha256") != source_sha256:
            raise DatasetError(f"Completed derivative source changed: {source}")
        _validate_checkpoint_shards(output, payload["shards"])
        return ContactImportResult(
            artifact_id=artifact_id,
            output=output.resolve(),
            source_sha256=source_sha256,
            rows=int(payload["rows"]),
            shards=len(payload["shards"]),
            peak_rss_bytes=int(payload["peak_rss_bytes"]),
            manifest_sha256=sha256_file(manifest_path),
        )

    checkpoint: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "source": str(source.resolve()),
        "source_sha256": source_sha256,
        "next_batch": 0,
        "rows": 0,
        "shards": [],
    }
    if checkpoint_path.exists():
        if not resume:
            raise DatasetError(f"Contact import checkpoint exists: {checkpoint_path}")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("source_sha256") != source_sha256:
            raise DatasetError("Contact import checkpoint belongs to a different source")
        _validate_checkpoint_shards(output, checkpoint["shards"])

    memory_limit_bytes = int(memory_limit_gb * 1024**3)
    with pa.memory_map(str(source), "r") as mapped:
        reader = ipc.open_file(mapped)
        checkpoint.setdefault("source_schema_sha256", _schema_sha256(reader.schema))
        next_batch = int(checkpoint["next_batch"])
        buffered: list[pa.RecordBatch] = []
        buffered_rows = 0
        for batch_index in range(next_batch, reader.num_record_batches):
            batch = _normalize_unsigned_ids(reader.get_batch(batch_index))
            buffered.append(batch)
            buffered_rows += batch.num_rows
            is_last = batch_index + 1 == reader.num_record_batches
            if buffered_rows < shard_rows and not is_last:
                if _peak_rss_bytes() > memory_limit_bytes:
                    raise DatasetError("Contact importer exceeded its peak RSS limit")
                continue

            table = pa.Table.from_batches(buffered, schema=buffered[0].schema)
            checkpoint.setdefault("normalized_schema_sha256", _schema_sha256(table.schema))
            shard_index = len(checkpoint["shards"])
            filename = f"part-{shard_index:06d}.parquet"
            destination = output / filename
            temporary = destination.with_suffix(".parquet.part")
            pq.write_table(
                table,
                temporary,
                compression="zstd",
                compression_level=DEFAULT_ZSTD_LEVEL,
                row_group_size=row_group_rows,
                use_dictionary=True,
                write_statistics=True,
            )
            os.replace(temporary, destination)
            checkpoint["shards"].append(
                {
                    "filename": filename,
                    "rows": table.num_rows,
                    "bytes": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                    "logical_sha256": _logical_table_sha256(table),
                    "first_source_batch": int(checkpoint["next_batch"]),
                    "last_source_batch": batch_index,
                }
            )
            checkpoint["next_batch"] = batch_index + 1
            checkpoint["rows"] = int(checkpoint["rows"]) + table.num_rows
            checkpoint["peak_rss_bytes"] = _peak_rss_bytes()
            _write_json_atomic(checkpoint_path, checkpoint)
            progress(
                f"normalized {artifact_id}: {checkpoint['rows']:,} rows, "
                f"{len(checkpoint['shards']):,} shards"
            )
            if checkpoint["peak_rss_bytes"] > memory_limit_bytes:
                raise DatasetError("Contact importer exceeded its peak RSS limit")
            buffered = []
            buffered_rows = 0

    manifest = {
        **checkpoint,
        "complete": True,
        "input_batch_policy": "native IPC record batches",
        "identifier_normalization": "nonnegative int64 body and sv IDs cast losslessly to uint64",
        "normalized_schema_sha256": checkpoint["normalized_schema_sha256"],
        "row_group_rows": row_group_rows,
        "shard_rows": shard_rows,
        "compression": "zstd",
        "compression_level": DEFAULT_ZSTD_LEVEL,
        "canonical_threshold_applied": False,
    }
    _write_json_atomic(manifest_path, manifest)
    checkpoint_path.unlink(missing_ok=True)
    return ContactImportResult(
        artifact_id=artifact_id,
        output=output.resolve(),
        source_sha256=source_sha256,
        rows=int(manifest["rows"]),
        shards=len(manifest["shards"]),
        peak_rss_bytes=int(manifest["peak_rss_bytes"]),
        manifest_sha256=sha256_file(manifest_path),
    )


def audit_contact_derivatives(
    contacts_root: Path,
    report_path: Path,
    temporary_storage: Path,
    *,
    memory_limit_gb: float = DEFAULT_MEMORY_LIMIT_GB,
    threads: int = 2,
) -> dict[str, Any]:
    """Run the exhaustive Stage-0 contact, polyad, and aggregate reconciliation audit."""
    try:
        import duckdb
    except ImportError as exc:
        raise DatasetError("Contact audit requires the optional DuckDB dependency") from exc
    required = ("syn-points", "syn-partners", "tbar-neurotransmitters", "connectome-weights")
    for artifact_id in required:
        manifest_path = contacts_root / artifact_id / "manifest.json"
        if not manifest_path.is_file():
            raise DatasetError(f"Completed contact derivative is missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_checkpoint_shards(contacts_root / artifact_id, manifest["shards"])
        if manifest.get("complete") is not True or manifest.get("canonical_threshold_applied"):
            raise DatasetError(f"Invalid canonical contact manifest: {manifest_path}")

    temporary_storage.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit='{float(memory_limit_gb)}GB'")
    escaped_temp = str(temporary_storage.resolve()).replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped_temp}'")
    for artifact_id in required:
        glob = str((contacts_root / artifact_id / "*.parquet").resolve()).replace("'", "''")
        view_name = artifact_id.replace("-", "_")
        connection.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_parquet('{glob}')")

    checks: dict[str, dict[str, Any]] = {}

    def scalar_check(name: str, query: str, expected: int = 0) -> None:
        row = connection.execute(query).fetchone()
        if row is None:
            raise DatasetError(f"Contact audit query returned no result: {name}")
        observed = int(row[0])
        checks[name] = {"passed": observed == expected, "observed": observed, "expected": expected}

    scalar_check(
        "packed_point_id_bijection",
        """
        SELECT count(*) FROM syn_points
        WHERE point_id != ((CAST(z AS UBIGINT) << 42) |
                           (CAST(y AS UBIGINT) << 21) | CAST(x AS UBIGINT))
           OR x < 0 OR y < 0 OR z < 0 OR x >= 2097152 OR y >= 2097152 OR z >= 4194304
        """,
    )
    scalar_check(
        "point_id_uniqueness",
        "SELECT count(*) - count(DISTINCT point_id) FROM syn_points",
    )
    scalar_check(
        "partner_endpoint_resolution",
        """
        WITH endpoints AS (
          SELECT *,
            ((CAST(z_pre AS UBIGINT) << 42) | (CAST(y_pre AS UBIGINT) << 21) |
             CAST(x_pre AS UBIGINT)) AS pre_id,
            ((CAST(z_post AS UBIGINT) << 42) | (CAST(y_post AS UBIGINT) << 21) |
             CAST(x_post AS UBIGINT)) AS post_id
          FROM syn_partners
        )
        SELECT count(*) FROM endpoints e
        LEFT JOIN syn_points pre ON pre.point_id=e.pre_id
        LEFT JOIN syn_points post ON post.point_id=e.post_id
        WHERE pre.point_id IS NULL OR post.point_id IS NULL
           OR pre.kind != 'PreSyn' OR post.kind != 'PostSyn'
           OR pre.body != e.body_pre OR post.body != e.body_post
           OR pre.conf != e.conf_pre OR post.conf != e.conf_post
        """,
    )
    scalar_check(
        "aggregate_pair_reconciliation",
        """
        WITH observed AS (
          SELECT body_pre, body_post, count(*)::BIGINT AS weight
          FROM syn_partners GROUP BY body_pre, body_post
        )
        SELECT count(*) FROM observed o
        FULL OUTER JOIN connectome_weights w USING (body_pre, body_post)
        WHERE o.body_pre IS NULL OR w.body_pre IS NULL OR o.weight != w.weight
        """,
    )
    probability_columns = (
        "nt_acetylcholine_prob", "nt_dopamine_prob", "nt_gaba_prob",
        "nt_glutamate_prob", "nt_histamine_prob", "nt_octopamine_prob",
        "nt_serotonin_prob",
    )
    invalid_probability = " OR ".join(
        f"NOT isfinite({name}) OR {name} < 0 OR {name} > 1" for name in probability_columns
    )
    scalar_check(
        "tbar_point_and_probability_resolution",
        f"""
        SELECT count(*) FROM tbar_neurotransmitters t
        LEFT JOIN syn_points p USING (point_id)
        WHERE p.point_id IS NULL OR p.kind != 'PreSyn' OR p.body != t.body
           OR p.x != t.x OR p.y != t.y OR p.z != t.z OR p.conf != t.conf
           OR {invalid_probability}
        """,
    )
    polyads = connection.execute(
        """
        SELECT count(*) AS presynaptic_sites, count_if(fanout > 1) AS polyadic_sites,
               max(fanout) AS maximum_fanout
        FROM (
          SELECT x_pre, y_pre, z_pre, count(*) AS fanout
          FROM syn_partners GROUP BY x_pre, y_pre, z_pre
        )
        """
    ).fetchone()
    if polyads is None:
        raise DatasetError("Polyadic contact audit returned no result")
    checks["polyadic_fanout_preserved"] = {
        "passed": int(polyads[1]) > 0,
        "presynaptic_sites": int(polyads[0]),
        "polyadic_sites": int(polyads[1]),
        "maximum_fanout": int(polyads[2]),
    }
    connection.close()
    failures = sorted(name for name, result in checks.items() if result["passed"] is not True)
    report = {
        "schema_version": "1.0",
        "audit": "MaleCNS-v1.0-contact-structural-audit",
        "valid": not failures,
        "failures": failures,
        "checks": checks,
        "derivative_manifest_sha256": {
            artifact_id: sha256_file(contacts_root / artifact_id / "manifest.json")
            for artifact_id in required
        },
        "validation_tier_awarded": None,
        "remaining_v0_gates": [
            "morphology_canaries", "body_universe_sensitivity",
            "batch_size_reproducibility", "V0 evidence bundle review",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(report_path, report)
    return report
