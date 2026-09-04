# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

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

