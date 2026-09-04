# SPDX-License-Identifier: GPL-2.0-or-later
import io
from pathlib import Path
from typing import Any, ClassVar

import pytest

from flysim.datasets import ArtifactSpec, DatasetSpec, sync_dataset, validate_dataset
from flysim.errors import DatasetError


def spec(source: Path) -> DatasetSpec:
    return DatasetSpec(
        schema_version="1.0",
        dataset_id="test:v1",
        source_page="https://example.invalid",
        license="CC0",
        coordinate_notes="test units",
        artifacts=(
            ArtifactSpec(
                id="artifact",
                filename="artifact.bin",
                url=source.resolve().as_uri(),
                profiles=("starter",),
                published_size="4 B",
                sha256=None,
            ),
        ),
    )


def test_sync_locks_and_validates_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"test")
    root = tmp_path / "data"
    dataset = spec(source)
    lock = sync_dataset(dataset, root, "starter", minimum_free_gb=0.0, progress=lambda _: None)
    assert lock["artifacts"]["artifact"]["bytes"] == 4
    assert validate_dataset(dataset, root, "starter")[0]["status"] == "ok"

    downloaded = root / "raw" / "test-v1" / "artifact.bin"
    downloaded.write_bytes(b"changed")
    assert validate_dataset(dataset, root, "starter")[0]["status"] == "checksum-mismatch"
    with pytest.raises(DatasetError, match="checksum changed"):
        sync_dataset(dataset, root, "starter", minimum_free_gb=0.0, progress=lambda _: None)


def test_sync_resumes_validated_http_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"unused")
    root = tmp_path / "data"
    dataset = spec(source)
    partial = root / "raw" / "test-v1" / "artifact.bin.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"te")
    requests: list[Any] = []

    class RangeResponse(io.BytesIO):
        status = 206
        headers: ClassVar[dict[str, str]] = {
            "Content-Length": "2",
            "Content-Range": "bytes 2-3/4",
        }

        def getcode(self) -> int:
            return self.status

    def urlopen(request: Any, timeout: int) -> RangeResponse:
        requests.append(request)
        assert timeout == 120
        return RangeResponse(b"st")

    monkeypatch.setattr("flysim.datasets.urllib.request.urlopen", urlopen)
    lock = sync_dataset(dataset, root, "starter", minimum_free_gb=0.0, progress=lambda _: None)

    assert requests[0].headers["Range"] == "bytes=2-"
    assert (root / "raw" / "test-v1" / "artifact.bin").read_bytes() == b"test"
    assert lock["artifacts"]["artifact"]["resumed_from_bytes"] == 2


def test_sync_keeps_partial_when_stream_breaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"unused")
    root = tmp_path / "data"
    dataset = spec(source)

    class BrokenResponse(io.BytesIO):
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Length": "4"}

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            data = super().read(size)
            if data:
                return data[:2]
            return data

    monkeypatch.setattr(
        "flysim.datasets.urllib.request.urlopen",
        lambda request, timeout: BrokenResponse(b"te"),
    )
    with pytest.raises(DatasetError, match="partial file was kept"):
        sync_dataset(dataset, root, "starter", minimum_free_gb=0.0, progress=lambda _: None)

    assert (root / "raw" / "test-v1" / "artifact.bin.part").read_bytes() == b"te"
