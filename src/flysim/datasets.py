# SPDX-License-Identifier: GPL-2.0-or-later
"""Acquisition and integrity validation for canonical data artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
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
        progress(f"resuming {artifact.id} from {resumed_from:,} bytes")

    request = urllib.request.Request(artifact.url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and resumed_from:
            header = exc.headers.get("Content-Range")
            match = _UNSATISFIED_CONTENT_RANGE.fullmatch(header.strip()) if header else None
            if match is not None and int(match.group(1)) == resumed_from:
                return sha256_file(temporary), resumed_from, resumed_from
        raise

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
            f"received {byte_count:,}; the partial file was kept for resume"
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
    lock = _load_lock(root, spec.dataset_id)
    lock["source_page"] = spec.source_page
    lock["license"] = spec.license
    lock["coordinate_notes"] = spec.coordinate_notes

    for artifact in spec.for_profile(profile):
        destination = directory / artifact.filename
        locked = lock["artifacts"].get(artifact.id)
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
        }
        _write_lock(root, spec.dataset_id, lock)
        progress(f"locked {artifact.id}: {observed}")
    return lock


def validate_dataset(
    spec: DatasetSpec,
    root: Path,
    profile: str | None = None,
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
        results.append(
            {
                "id": artifact.id,
                "path": str(destination.resolve()),
                "status": status,
                "sha256": observed,
                "locked_sha256": locked.get("sha256") if locked else None,
            }
        )
    return results
