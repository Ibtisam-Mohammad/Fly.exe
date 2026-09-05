# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded-memory normalization of immutable MaleCNS Arrow contact tables."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import resource
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from flysim.datasets import sha256_file
from flysim.errors import ContactImportRecycle, DatasetError

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


@dataclass(frozen=True, slots=True)
class LogicalDerivativeDigest:
    artifact_id: str
    rows: int
    batches: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    max_new_shards_per_process: int | None = None,
    expected_sha256: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
) -> ContactImportResult:
    """Stream native IPC batches into immutable, resumable Parquet shards."""
    if not source.is_file():
        raise DatasetError(f"Contact source is missing: {source}")
    if row_group_rows <= 0 or shard_rows <= 0 or shard_rows % row_group_rows:
        raise DatasetError("Shard rows must be a positive multiple of row-group rows")
    if max_new_shards_per_process is not None and max_new_shards_per_process <= 0:
        raise DatasetError("Maximum new shards per process must be positive when set")
    output.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(output).free / (1024**3)
    if free_gb < minimum_free_gb:
        raise DatasetError(
            f"Refusing contact import: {output.resolve()} has {free_gb:.1f} GB free; "
            f"at least {minimum_free_gb:.1f} GB is required"
        )

    checkpoint_path = output / "import-checkpoint.json"
    manifest_path = output / "manifest.json"
    stored_identity: dict[str, Any] | None = None
    if manifest_path.exists():
        stored_identity = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif checkpoint_path.exists():
        stored_identity = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (
        expected_sha256 is not None
        and stored_identity is not None
        and stored_identity.get("source_sha256") == expected_sha256
        and stored_identity.get("source_bytes", source.stat().st_size) == source.stat().st_size
        and stored_identity.get("source_mtime_ns", source.stat().st_mtime_ns)
        == source.stat().st_mtime_ns
    ):
        # The immutable dataset lock was freshly deep-validated before construction. Re-reading
        # tens of gigabytes on every process restart adds no identity evidence, so a matching
        # derivative checkpoint resumes from the already pinned lock identity.
        source_sha256 = expected_sha256
    else:
        source_sha256 = sha256_file(source)
    if expected_sha256 is not None and source_sha256 != expected_sha256:
        raise DatasetError(
            f"Contact source checksum mismatch for {artifact_id}: expected "
            f"{expected_sha256}, got {source_sha256}"
        )
    if manifest_path.exists():
        payload = stored_identity or json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("source_sha256") != source_sha256:
            raise DatasetError(f"Completed derivative source changed: {source}")
        if payload.get("row_group_rows") != row_group_rows:
            raise DatasetError("Completed derivative uses a different row-group size")
        if payload.get("shard_rows") != shard_rows:
            raise DatasetError("Completed derivative uses a different shard size")
        _validate_checkpoint_shards(output, payload["shards"])
        if "source_bytes" not in payload or "source_mtime_ns" not in payload:
            payload["source_bytes"] = source.stat().st_size
            payload["source_mtime_ns"] = source.stat().st_mtime_ns
            _write_json_atomic(manifest_path, payload)
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
        "source_bytes": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "next_batch": 0,
        "rows": 0,
        "shards": [],
        "row_group_rows": row_group_rows,
        "shard_rows": shard_rows,
    }
    if checkpoint_path.exists():
        if not resume:
            raise DatasetError(f"Contact import checkpoint exists: {checkpoint_path}")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("source_sha256") != source_sha256:
            raise DatasetError("Contact import checkpoint belongs to a different source")
        checkpoint.setdefault("source_bytes", source.stat().st_size)
        checkpoint.setdefault("source_mtime_ns", source.stat().st_mtime_ns)
        checkpoint.setdefault("row_group_rows", row_group_rows)
        checkpoint.setdefault("shard_rows", shard_rows)
        if checkpoint["row_group_rows"] != row_group_rows:
            raise DatasetError("Contact import checkpoint uses a different row-group size")
        if checkpoint["shard_rows"] != shard_rows:
            raise DatasetError("Contact import checkpoint uses a different shard size")
        _validate_checkpoint_shards(output, checkpoint["shards"])

    memory_limit_bytes = int(memory_limit_gb * 1024**3)
    with pa.memory_map(str(source), "r") as mapped:
        reader = ipc.open_file(mapped)
        checkpoint.setdefault("source_schema_sha256", _schema_sha256(reader.schema))
        next_batch = int(checkpoint["next_batch"])
        row_group_batches: list[pa.RecordBatch] = []
        row_group_buffered_rows = 0
        shard_rows_written = 0
        shard_first_batch = next_batch
        shard_last_batch = next_batch
        writer: pq.ParquetWriter | None = None
        logical_digest = hashlib.sha256()
        destination: Path | None = None
        temporary: Path | None = None
        new_shards = 0
        for batch_index in range(next_batch, reader.num_record_batches):
            batch = _normalize_unsigned_ids(reader.get_batch(batch_index))
            row_group_batches.append(batch)
            row_group_buffered_rows += batch.num_rows
            is_last = batch_index + 1 == reader.num_record_batches
            if row_group_buffered_rows < row_group_rows and not is_last:
                continue

            table = pa.Table.from_batches(row_group_batches, schema=row_group_batches[0].schema)
            checkpoint.setdefault("normalized_schema_sha256", _schema_sha256(table.schema))
            if writer is None:
                shard_index = len(checkpoint["shards"])
                filename = f"part-{shard_index:06d}.parquet"
                destination = output / filename
                temporary = destination.with_suffix(".parquet.part")
                temporary.unlink(missing_ok=True)
                writer = pq.ParquetWriter(
                    temporary,
                    table.schema,
                    compression="zstd",
                    compression_level=DEFAULT_ZSTD_LEVEL,
                    use_dictionary=True,
                    write_statistics=True,
                    write_page_checksum=True,
                )
                shard_first_batch = batch_index - len(row_group_batches) + 1
            writer.write_table(table, row_group_size=row_group_rows)
            logical_digest.update(bytes.fromhex(_logical_table_sha256(table)))
            shard_rows_written += table.num_rows
            shard_last_batch = batch_index
            row_group_batches = []
            row_group_buffered_rows = 0
            if _peak_rss_bytes() > memory_limit_bytes:
                writer.close()
                raise DatasetError("Contact importer exceeded its peak RSS limit")
            if shard_rows_written < shard_rows and not is_last:
                continue

            writer.close()
            writer = None
            if destination is None or temporary is None:
                raise DatasetError("Contact shard writer lost its destination")
            os.replace(temporary, destination)
            checkpoint["shards"].append(
                {
                    "filename": destination.name,
                    "rows": shard_rows_written,
                    "bytes": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                    "logical_sha256": logical_digest.hexdigest(),
                    "logical_digest_policy": "sha256-of-fixed-row-group-logical-digests-v1",
                    "first_source_batch": shard_first_batch,
                    "last_source_batch": shard_last_batch,
                }
            )
            checkpoint["next_batch"] = shard_last_batch + 1
            checkpoint["rows"] = int(checkpoint["rows"]) + shard_rows_written
            process_peak_rss_bytes = _peak_rss_bytes()
            checkpoint["peak_rss_bytes"] = max(
                int(checkpoint.get("peak_rss_bytes", 0)), process_peak_rss_bytes
            )
            _write_json_atomic(checkpoint_path, checkpoint)
            progress(
                f"normalized {artifact_id}: {checkpoint['rows']:,} rows, "
                f"{len(checkpoint['shards']):,} shards"
            )
            if process_peak_rss_bytes > memory_limit_bytes:
                raise DatasetError("Contact importer exceeded its peak RSS limit")
            new_shards += 1
            shard_rows_written = 0
            logical_digest = hashlib.sha256()
            destination = None
            temporary = None
            del table
            gc.collect()
            pa.default_memory_pool().release_unused()
            if (
                max_new_shards_per_process is not None
                and new_shards >= max_new_shards_per_process
                and not is_last
            ):
                raise ContactImportRecycle(
                    "Contact import checkpoint is safe; recycle the worker process"
                )

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


def logical_derivative_digest(
    artifact_root: Path, *, scan_batch_rows: int = 65_536
) -> LogicalDerivativeDigest:
    """Hash logical Arrow rows independently of Parquet row-group size."""
    if scan_batch_rows <= 0:
        raise DatasetError("Logical digest scan batch size must be positive")
    manifest_path = artifact_root / "manifest.json"
    if not manifest_path.is_file():
        raise DatasetError(f"Contact derivative manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("complete"):
        raise DatasetError(f"Contact derivative is incomplete: {artifact_root}")
    shards = manifest.get("shards", [])
    _validate_checkpoint_shards(artifact_root, shards)
    digest = hashlib.sha256()
    rows = 0
    batches = 0
    schema_identity: str | None = None
    for shard in shards:
        parquet = pq.ParquetFile(artifact_root / str(shard["filename"]))
        for batch in parquet.iter_batches(batch_size=scan_batch_rows):
            arrays: list[pa.Array] = []
            fields: list[pa.Field] = []
            for field, column in zip(batch.schema, batch.columns, strict=True):
                if pa.types.is_dictionary(field.type):
                    value_type = field.type.value_type
                    arrays.append(pc.cast(column, value_type))
                    fields.append(pa.field(field.name, value_type, nullable=field.nullable))
                else:
                    arrays.append(column)
                    fields.append(field)
            canonical = pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))
            current_schema = _schema_sha256(canonical.schema)
            if schema_identity is None:
                schema_identity = current_schema
                digest.update(bytes.fromhex(current_schema))
            elif current_schema != schema_identity:
                raise DatasetError(f"Logical schema changed within {artifact_root}")
            payload = canonical.serialize().to_pybytes()
            digest.update(len(payload).to_bytes(8, "little"))
            digest.update(payload)
            rows += canonical.num_rows
            batches += 1
    if rows != int(manifest["rows"]):
        raise DatasetError(
            f"Logical digest row count mismatch for {artifact_root}: {rows} != {manifest['rows']}"
        )
    return LogicalDerivativeDigest(
        artifact_id=str(manifest["artifact_id"]),
        rows=rows,
        batches=batches,
        sha256=digest.hexdigest(),
    )


def compare_contact_derivatives(
    left_root: Path,
    right_root: Path,
    output: Path,
    *,
    scan_batch_rows: int = 65_536,
) -> dict[str, Any]:
    """Require layout-independent logical equality for all contact artifacts."""
    artifact_ids = (
        "connectome-weights",
        "syn-points",
        "syn-partners",
        "tbar-neurotransmitters",
    )
    comparisons: list[dict[str, Any]] = []
    for artifact_id in artifact_ids:
        left = logical_derivative_digest(
            left_root / artifact_id, scan_batch_rows=scan_batch_rows
        )
        right = logical_derivative_digest(
            right_root / artifact_id, scan_batch_rows=scan_batch_rows
        )
        comparisons.append(
            {
                "artifact_id": artifact_id,
                "left": left.as_dict(),
                "right": right.as_dict(),
                "matches": left.rows == right.rows and left.sha256 == right.sha256,
            }
        )
    report = {
        "schema_version": "1.0",
        "gate": "batch_size_reproducibility",
        "scan_batch_rows": scan_batch_rows,
        "left_root": str(left_root.resolve()),
        "right_root": str(right_root.resolve()),
        "comparisons": comparisons,
        "valid": all(item["matches"] for item in comparisons),
    }
    _write_json_atomic(output, report)
    return report


def audit_contact_derivatives(
    contacts_root: Path,
    report_path: Path,
    temporary_storage: Path,
    *,
    memory_limit_gb: float = DEFAULT_MEMORY_LIMIT_GB,
    threads: int = 2,
    progress: Callable[[str], None] = lambda _: None,
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
    memory_limit_bytes = int(memory_limit_gb * 1024**3)
    connection.execute(f"SET memory_limit='{memory_limit_bytes}B'")
    connection.execute("SET preserve_insertion_order=false")
    escaped_temp = str(temporary_storage.resolve()).replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped_temp}'")
    for artifact_id in required:
        glob = str((contacts_root / artifact_id / "*.parquet").resolve()).replace("'", "''")
        view_name = artifact_id.replace("-", "_")
        connection.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_parquet('{glob}')")

    checks: dict[str, dict[str, Any]] = {}

    def scalar_check(name: str, query: str, expected: int = 0) -> None:
        progress(f"contact audit starting: {name}")
        try:
            row = connection.execute(query).fetchone()
        except Exception as exc:
            raise DatasetError(f"Contact audit check failed ({name}): {exc}") from exc
        if row is None:
            raise DatasetError(f"Contact audit query returned no result: {name}")
        observed = int(row[0])
        checks[name] = {"passed": observed == expected, "observed": observed, "expected": expected}
        progress(f"contact audit completed: {name}; observed={observed}; expected={expected}")

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
    progress("contact audit starting: polyadic_fanout_preserved")
    try:
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
    except Exception as exc:
        raise DatasetError(
            f"Contact audit check failed (polyadic_fanout_preserved): {exc}"
        ) from exc
    if polyads is None:
        raise DatasetError("Polyadic contact audit returned no result")
    checks["polyadic_fanout_preserved"] = {
        "passed": int(polyads[1]) > 0,
        "presynaptic_sites": int(polyads[0]),
        "polyadic_sites": int(polyads[1]),
        "maximum_fanout": int(polyads[2]),
    }
    progress(
        "contact audit completed: polyadic_fanout_preserved; "
        f"sites={int(polyads[0])}; polyadic={int(polyads[1])}; max_fanout={int(polyads[2])}"
    )
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
