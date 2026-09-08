# SPDX-License-Identifier: GPL-2.0-or-later
"""Acquisition and integrity validation for canonical data artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .config import load_json
from .errors import DatasetError

Progress = Callable[[str], None]

_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_DOWNLOAD_PROGRESS_BYTES = 512 * 1024 * 1024
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")
_UNSATISFIED_CONTENT_RANGE = re.compile(r"^bytes \*/(\d+)$")


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    id: str
    filename: str
    url: str
    profiles: tuple[str, ...]
    published_size: str
    sha256: str | None
    expected_bytes: int | None = None
    gcs_generation: str | None = None
    etag: str | None = None
    md5_base64: str | None = None
    crc32c_base64: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    schema_version: str
    dataset_id: str
    source_page: str
    license: str
    coordinate_notes: str
    artifacts: tuple[ArtifactSpec, ...]

    @classmethod
    def load(cls, path: Path) -> DatasetSpec:
        raw = load_json(path)
        artifacts = tuple(
            ArtifactSpec(
                id=str(item["id"]),
                filename=str(item["filename"]),
                url=str(item["url"]),
                profiles=tuple(item["profiles"]),
                published_size=str(item["published_size"]),
                sha256=item.get("sha256"),
                expected_bytes=(
                    int(item["expected_bytes"]) if item.get("expected_bytes") is not None else None
                ),
                gcs_generation=item.get("gcs_generation"),
                etag=item.get("etag"),
                md5_base64=item.get("md5_base64"),
                crc32c_base64=item.get("crc32c_base64"),
            )
            for item in raw["artifacts"]
        )
        return cls(
            schema_version=str(raw["schema_version"]),
            dataset_id=str(raw["dataset_id"]),
            source_page=str(raw["source_page"]),
            license=str(raw["license"]),
            coordinate_notes=str(raw["coordinate_notes"]),
            artifacts=artifacts,
        )

    def for_profile(self, profile: str) -> tuple[ArtifactSpec, ...]:
        selected = tuple(item for item in self.artifacts if profile in item.profiles)
        if not selected:
            choices = sorted({value for item in self.artifacts for value in item.profiles})
            raise DatasetError(f"Unknown dataset profile {profile!r}; choose from {choices}")
        return selected


def default_data_root() -> Path:
    configured = os.environ.get("FLYSIM_DATA_ROOT")
    return Path(configured).expanduser() if configured else Path("data")


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _crc32c_checksum() -> Any | None:
    """Return a fresh incremental CRC32C accumulator, or ``None`` when unavailable.

    The pinned Google Cloud Storage identity includes a Castagnoli CRC32C. Python's
    standard library has no CRC32C and a pure-Python implementation cannot read the
    28-GB raw profile in a useful time, so the check is reported as *unavailable*
    rather than silently skipped when the optional native module is absent.
    """
    try:
        import google_crc32c
    except ImportError:
        return None
    return google_crc32c.Checksum()


def file_digests(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> dict[str, str | None]:
    """Compute SHA-256 and the upstream-comparable base64 MD5/CRC32C in a single read.

    ``crc32c_base64`` is ``None`` when no native CRC32C implementation is installed;
    callers must report that as *unverified* rather than as a passing check.
    """
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    crc32c = _crc32c_checksum()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            sha.update(chunk)
            md5.update(chunk)
            if crc32c is not None:
                crc32c.update(chunk)
    return {
        "sha256": sha.hexdigest(),
        "md5_base64": base64.b64encode(md5.digest()).decode("ascii"),
        "crc32c_base64": (
            base64.b64encode(crc32c.digest()).decode("ascii") if crc32c is not None else None
        ),
    }


def _dataset_directory(root: Path, dataset_id: str) -> Path:
    return root / "raw" / dataset_id.replace(":", "-")


def _lock_path(root: Path, dataset_id: str) -> Path:
    return _dataset_directory(root, dataset_id) / "dataset-lock.json"


def _load_lock(root: Path, dataset_id: str) -> dict[str, Any]:
    path = _lock_path(root, dataset_id)
    if not path.exists():
        return {"schema_version": "1.0", "dataset_id": dataset_id, "artifacts": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("dataset_id") != dataset_id:
        raise DatasetError(f"Dataset lock identity mismatch at {path}")
    return cast(dict[str, Any], raw)


def _write_lock(root: Path, dataset_id: str, lock: dict[str, Any]) -> None:
    path = _lock_path(root, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _mutation_lock(root: Path, dataset_id: str) -> Iterator[None]:
    """Prevent two data writers from mutating one dataset directory."""
    path = _dataset_directory(root, dataset_id) / ".flysim-data.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise DatasetError(
            f"Dataset mutation is already locked: {path}. Investigate the recorded PID before "
            "removing a stale lock."
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(f"pid={os.getpid()}\n")
        yield
    finally:
        path.unlink(missing_ok=True)


def ensure_free_space(root: Path, minimum_free_gb: float) -> None:
    root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(root).free / (1024**3)
    if free_gb < minimum_free_gb:
        raise DatasetError(
            f"Refusing data mutation: {root.resolve()} has {free_gb:.1f} GB free; "
            f"at least {minimum_free_gb:.1f} GB is required"
        )


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    code = response.getcode()
    return code if isinstance(code, int) else None


def _content_range(header: str | None) -> tuple[int, int, int | None] | None:
    if header is None:
        return None
    match = _CONTENT_RANGE.fullmatch(header.strip())
    if match is None:
        return None
    start, end, total = match.groups()
    return int(start), int(end), None if total == "*" else int(total)


def _download_resumable(
    artifact: ArtifactSpec,
    temporary: Path,
    progress: Progress,
) -> tuple[str, int, int]:
    """Download to ``temporary``, resuming only a validated HTTP byte range."""
    resumed_from = temporary.stat().st_size if temporary.exists() else 0
    headers = {
        "Accept-Encoding": "identity",
        "User-Agent": "malecns-flysim/0.1",
    }
    if resumed_from:
        headers["Range"] = f"bytes={resumed_from}-"
        if artifact.etag is not None:
            headers["If-Range"] = f'"{artifact.etag}"'
        progress(f"resuming {artifact.id} from {resumed_from:,} bytes")

    url = artifact.url
    if artifact.gcs_generation is not None:
        separator = "&" if urllib.parse.urlsplit(url).query else "?"
        url = f"{url}{separator}generation={artifact.gcs_generation}"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and resumed_from:
            header = exc.headers.get("Content-Range")
            match = _UNSATISFIED_CONTENT_RANGE.fullmatch(header.strip()) if header else None
            if match is not None and int(match.group(1)) == resumed_from:
                return sha256_file(temporary), resumed_from, resumed_from
        raise DatasetError(
            f"HTTP {exc.code} while acquiring {artifact.id}: {exc.reason}",
            code="DATA_HTTP_ERROR",
            retryable=500 <= exc.code < 600,
        ) from exc
    except urllib.error.URLError as exc:
        raise DatasetError(
            f"Network failure while acquiring {artifact.id}: {exc.reason}",
            code="DATA_NETWORK_ERROR",
            retryable=True,
        ) from exc

    with response:
        status = _response_status(response)
        parsed_range = _content_range(response.headers.get("Content-Range"))
        append = resumed_from > 0 and status == 206
        if append:
            if parsed_range is None or parsed_range[0] != resumed_from:
                raise DatasetError(
                    f"Server returned an invalid resume range for {artifact.id}: "
                    f"requested byte {resumed_from}, got "
                    f"{response.headers.get('Content-Range')!r}"
                )
            expected_total = parsed_range[2]
            if artifact.expected_bytes is not None and expected_total != artifact.expected_bytes:
                raise DatasetError(
                    f"Remote size changed for {artifact.id}: expected "
                    f"{artifact.expected_bytes:,}, got {expected_total!r}"
                )
            mode = "ab"
        else:
            if resumed_from:
                progress(f"server did not honor resume for {artifact.id}; restarting safely")
                resumed_from = 0
            expected_length = response.headers.get("Content-Length")
            expected_total = int(expected_length) if expected_length is not None else None
            mode = "wb"

        byte_count = resumed_from
        next_progress = ((byte_count // _DOWNLOAD_PROGRESS_BYTES) + 1) * _DOWNLOAD_PROGRESS_BYTES
        with temporary.open(mode) as out:
            while chunk := response.read(_DOWNLOAD_CHUNK_BYTES):
                out.write(chunk)
                byte_count += len(chunk)
                if byte_count >= next_progress:
                    progress(f"received {artifact.id}: {byte_count / (1024**3):.1f} GiB")
                    next_progress += _DOWNLOAD_PROGRESS_BYTES

    if expected_total is not None and byte_count != expected_total:
        raise DatasetError(
            f"Incomplete download for {artifact.id}: expected {expected_total:,} bytes, "
            f"received {byte_count:,}; the partial file was kept for resume",
            code="DATA_STREAM_INCOMPLETE",
            retryable=True,
        )
    if artifact.expected_bytes is not None and byte_count != artifact.expected_bytes:
        raise DatasetError(
            f"Pinned byte count mismatch for {artifact.id}: expected "
            f"{artifact.expected_bytes:,}, received {byte_count:,}; the partial file was kept"
        )
    return sha256_file(temporary), byte_count, resumed_from


def sync_dataset(
    spec: DatasetSpec,
    root: Path,
    profile: str,
    minimum_free_gb: float = 40.0,
    progress: Progress = print,
) -> dict[str, Any]:
    """Download profile artifacts and pin observed checksums atomically."""
    ensure_free_space(root, minimum_free_gb)
    directory = _dataset_directory(root, spec.dataset_id)
    directory.mkdir(parents=True, exist_ok=True)
    failed_path = directory / "dataset.failed.json"
    if failed_path.exists():
        raise DatasetError(
            f"A terminal dataset failure is recorded at {failed_path}; investigate it before "
            "explicitly removing the failure record.",
            code="DATA_TERMINAL_FAILURE_RECORDED",
        )
    try:
        with _mutation_lock(root, spec.dataset_id):
            return _sync_dataset_locked(spec, root, profile, progress)
    except DatasetError as exc:
        if not exc.retryable:
            payload = {
                "schema_version": "1.0",
                "dataset_id": spec.dataset_id,
                "code": exc.code,
                "retryable": False,
                "error": str(exc),
                "observed_at_unix_s": int(time.time()),
            }
            temporary = failed_path.with_suffix(".json.part")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            os.replace(temporary, failed_path)
        raise


def _sync_dataset_locked(
    spec: DatasetSpec,
    root: Path,
    profile: str,
    progress: Progress,
) -> dict[str, Any]:
    directory = _dataset_directory(root, spec.dataset_id)
    lock = _load_lock(root, spec.dataset_id)
    lock["source_page"] = spec.source_page
    lock["license"] = spec.license
    lock["coordinate_notes"] = spec.coordinate_notes

    for artifact in spec.for_profile(profile):
        destination = directory / artifact.filename
        locked = lock["artifacts"].get(artifact.id)
        if locked and not destination.exists():
            raise DatasetError(
                f"Locked artifact is missing: {destination}. Restore it or explicitly remove "
                "the affected lock record after investigation; it will not be replaced silently."
            )
        if destination.exists() and not locked:
            raise DatasetError(
                f"Existing artifact is not checksum-locked: {destination}. Move it aside or "
                "audit and register it; it will not be overwritten."
            )
        if destination.exists() and locked:
            observed = sha256_file(destination)
            if observed == locked.get("sha256"):
                progress(f"verified {artifact.id}: {observed}")
                continue
            raise DatasetError(
                f"Existing artifact checksum changed: {destination}. "
                "Move it aside and investigate; it will not be overwritten."
            )

        temporary = destination.with_suffix(destination.suffix + ".part")
        progress(f"downloading {artifact.id} ({artifact.published_size})")
        observed, byte_count, resumed_from = _download_resumable(
            artifact, temporary, progress
        )
        if artifact.sha256 is not None and observed != artifact.sha256:
            temporary.unlink(missing_ok=True)
            raise DatasetError(
                f"Upstream checksum mismatch for {artifact.id}: "
                f"expected {artifact.sha256}, got {observed}"
            )
        os.replace(temporary, destination)
        lock["artifacts"][artifact.id] = {
            "filename": artifact.filename,
            "url": artifact.url,
            "bytes": byte_count,
            "sha256": observed,
            "observed_at_unix_s": int(time.time()),
            "resumed_from_bytes": resumed_from,
            "upstream_checksum_published": artifact.sha256 is not None,
            "expected_bytes": artifact.expected_bytes,
            "gcs_generation": artifact.gcs_generation,
            "etag": artifact.etag,
            "md5_base64": artifact.md5_base64,
            "crc32c_base64": artifact.crc32c_base64,
        }
        _write_lock(root, spec.dataset_id, lock)
        progress(f"locked {artifact.id}: {observed}")
    return lock


def dataset_status(spec: DatasetSpec, root: Path, profile: str) -> dict[str, Any]:
    """Report acquisition state without hashing multi-gigabyte artifacts."""
    lock = _load_lock(root, spec.dataset_id)
    directory = _dataset_directory(root, spec.dataset_id)
    artifacts: list[dict[str, Any]] = []
    for artifact in spec.for_profile(profile):
        destination = directory / artifact.filename
        partial = destination.with_suffix(destination.suffix + ".part")
        locked = lock["artifacts"].get(artifact.id)
        state = "locked" if destination.exists() and locked else "missing"
        if partial.exists():
            state = "partial"
        elif destination.exists() and not locked:
            state = "unlocked"
        elif locked and not destination.exists():
            state = "locked-missing"
        artifacts.append(
            {
                "id": artifact.id,
                "state": state,
                "bytes": destination.stat().st_size if destination.exists() else 0,
                "partial_bytes": partial.stat().st_size if partial.exists() else 0,
                "expected_bytes": artifact.expected_bytes,
                "sha256_locked": locked.get("sha256") if locked else None,
            }
        )
    return {
        "schema_version": "1.0",
        "dataset_id": spec.dataset_id,
        "profile": profile,
        "complete": all(item["state"] == "locked" for item in artifacts),
        "artifacts": artifacts,
    }


def _remote_identity(artifact: ArtifactSpec) -> dict[str, str | int | None]:
    request = urllib.request.Request(
        artifact.url,
        headers={"Accept-Encoding": "identity", "User-Agent": "malecns-flysim/0.1"},
        method="HEAD",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        headers = response.headers
        hashes = {
            name: value
            for raw in (headers.get_all("x-goog-hash") or [])
            for name, separator, value in (raw.partition("="),)
            if separator
        }
        return {
            "bytes": int(headers["Content-Length"]) if headers.get("Content-Length") else None,
            "gcs_generation": headers.get("x-goog-generation"),
            "etag": headers.get("ETag", "").strip('"') or None,
            "md5_base64": hashes.get("md5"),
            "crc32c_base64": hashes.get("crc32c"),
        }


_DEEP_SCHEMA_TYPES: dict[str, dict[str, str]] = {
    "connectome-weights": {"body_pre": "int64", "body_post": "int64", "weight": "int64"},
    "syn-points": {
        "x": "int32", "y": "int32", "z": "int32", "kind": "dictionary",
        "conf": "float", "sv": "int64", "body": "int64", "point_id": "uint64",
    },
    "syn-partners": {
        "x_pre": "int32", "y_pre": "int32", "z_pre": "int32", "body_pre": "int64",
        "conf_pre": "float", "x_post": "int32", "y_post": "int32", "z_post": "int32",
        "body_post": "int64", "conf_post": "float", "primary_post": "dictionary",
    },
    "tbar-neurotransmitters": {
        "point_id": "uint64", "x": "int32", "y": "int32", "z": "int32",
        "conf": "float", "sv": "int64", "body": "int64",
        "nt_acetylcholine_prob": "float", "nt_dopamine_prob": "float",
        "nt_gaba_prob": "float", "nt_glutamate_prob": "float",
        "nt_histamine_prob": "float", "nt_octopamine_prob": "float",
        "nt_serotonin_prob": "float",
    },
}


def validate_feather_footer(artifact_id: str, path: Path) -> tuple[bool, str | None]:
    """Validate that an IPC/Feather footer opens and required columns retain exact types."""
    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc

        with pa.memory_map(str(path), "r") as source:
            reader = ipc.open_file(source)
            schema = reader.schema
            _ = reader.num_record_batches
            expected = _DEEP_SCHEMA_TYPES.get(artifact_id, {})
            for name, expected_type in expected.items():
                index = schema.get_field_index(name)
                if index < 0:
                    return False, f"required column is missing: {name}"
                observed_type = schema.field(index).type
                if expected_type == "dictionary":
                    matches = pa.types.is_dictionary(observed_type)
                else:
                    matches = str(observed_type) == expected_type
                if not matches:
                    return (
                        False,
                        f"column {name} has type {observed_type}, expected {expected_type}",
                    )
        return True, None
    except Exception as exc:  # pyarrow exposes several backend-specific exception types
        return False, str(exc)


def validate_dataset(
    spec: DatasetSpec,
    root: Path,
    profile: str | None = None,
    *,
    remote: bool = False,
    deep: bool = False,
) -> list[dict[str, Any]]:
    lock = _load_lock(root, spec.dataset_id)
    selected: Iterable[ArtifactSpec] = spec.for_profile(profile) if profile else spec.artifacts
    results: list[dict[str, Any]] = []
    directory = _dataset_directory(root, spec.dataset_id)
    for artifact in selected:
        destination = directory / artifact.filename
        locked = lock["artifacts"].get(artifact.id)
        status = "missing"
        observed: str | None = None
        if destination.exists() and locked:
            observed = sha256_file(destination)
            status = "ok" if observed == locked.get("sha256") else "checksum-mismatch"
        elif destination.exists():
            status = "unlocked"
        details: dict[str, Any] = {}
        if (
            status == "ok"
            and locked
            and artifact.expected_bytes is not None
            and destination.stat().st_size != artifact.expected_bytes
        ):
            status = "byte-count-mismatch"
        if status == "ok" and deep and destination.suffix == ".feather":
            footer_valid, footer_error = validate_feather_footer(artifact.id, destination)
            details["feather_footer_valid"] = footer_valid
            if not footer_valid:
                status = "invalid-feather-footer"
                details["footer_error"] = footer_error
        if remote:
            try:
                identity = _remote_identity(artifact)
                details["remote_identity"] = identity
                comparisons = {
                    "bytes": artifact.expected_bytes,
                    "gcs_generation": artifact.gcs_generation,
                    "etag": artifact.etag,
                    "md5_base64": artifact.md5_base64,
                    "crc32c_base64": artifact.crc32c_base64,
                }
                changed = [
                    name
                    for name, expected in comparisons.items()
                    if expected is not None and identity.get(name) != expected
                ]
                if changed:
                    status = "remote-identity-mismatch"
                    details["remote_mismatches"] = changed
            except (OSError, urllib.error.URLError) as exc:
                status = "remote-unavailable"
                details["remote_error"] = str(exc)
        results.append(
            {
                "id": artifact.id,
                "path": str(destination.resolve()),
                "status": status,
                "sha256": observed,
                "locked_sha256": locked.get("sha256") if locked else None,
                **details,
            }
        )
    return results
