# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.contacts import compare_contact_derivatives, import_contact_table
from flysim.datasets import sha256_file
from flysim.errors import ContactImportRecycle


def test_contact_import_is_sharded_lossless_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "contacts.feather"
    table = pa.table(
        {
            "point_id": pa.array(range(10), type=pa.uint64()),
            "x": pa.array(range(10), type=pa.int32()),
            "body": pa.array(range(100, 110), type=pa.uint64()),
            "conf": pa.array([0.75] * 10, type=pa.float32()),
        }
    )
    feather.write_feather(table, source, chunksize=2)
    output = tmp_path / "derived"
    expected = sha256_file(source)

    first = import_contact_table(
        "syn-points",
        source,
        output,
        memory_limit_gb=1.0,
        minimum_free_gb=0.0,
        row_group_rows=4,
        shard_rows=4,
        expected_sha256=expected,
    )
    second = import_contact_table(
        "syn-points",
        source,
        output,
        memory_limit_gb=1.0,
        minimum_free_gb=0.0,
        row_group_rows=4,
        shard_rows=4,
        expected_sha256=expected,
    )

    assert first.rows == 10
    assert first.shards == 3
    assert second.manifest_sha256 == first.manifest_sha256


def test_logical_digest_is_stable_across_safe_input_batch_sizes(tmp_path: Path) -> None:
    table = pa.table(
        {
            "point_id": pa.array(range(16), type=pa.uint64()),
            "body": pa.array(range(100, 116), type=pa.int64()),
            "x": pa.array(range(16), type=pa.int32()),
        }
    )
    digest_sets: list[list[str]] = []
    for chunksize in (1, 2):
        source = tmp_path / f"contacts-{chunksize}.feather"
        output = tmp_path / f"derived-{chunksize}"
        feather.write_feather(table, source, chunksize=chunksize)
        import_contact_table(
            "syn-points",
            source,
            output,
            memory_limit_gb=1.0,
            minimum_free_gb=0.0,
            row_group_rows=4,
            shard_rows=8,
        )
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        digest_sets.append([item["logical_sha256"] for item in manifest["shards"]])
    assert digest_sets[0] == digest_sets[1]


def test_contact_import_can_recycle_at_a_verified_shard(tmp_path: Path) -> None:
    source = tmp_path / "contacts.feather"
    output = tmp_path / "derived"
    feather.write_feather(pa.table({"point_id": range(12)}), source, chunksize=2)

    with pytest.raises(ContactImportRecycle) as raised:
        import_contact_table(
            "syn-points",
            source,
            output,
            memory_limit_gb=1.0,
            minimum_free_gb=0.0,
            row_group_rows=4,
            shard_rows=4,
            max_new_shards_per_process=1,
        )
    assert raised.value.retryable
    checkpoint = json.loads((output / "import-checkpoint.json").read_text())
    assert checkpoint["rows"] == 4

    result = import_contact_table(
        "syn-points",
        source,
        output,
        memory_limit_gb=1.0,
        minimum_free_gb=0.0,
        row_group_rows=4,
        shard_rows=4,
    )
    assert result.rows == 12


def test_contact_rebuild_digest_ignores_row_group_size(tmp_path: Path) -> None:
    source = tmp_path / "contacts.feather"
    feather.write_feather(
        pa.table({"point_id": range(16), "kind": ["PreSyn", "PostSyn"] * 8}),
        source,
        chunksize=2,
    )
    left = tmp_path / "left"
    right = tmp_path / "right"
    for artifact_id in (
        "connectome-weights",
        "syn-points",
        "syn-partners",
        "tbar-neurotransmitters",
    ):
        import_contact_table(
            artifact_id,
            source,
            left / artifact_id,
            minimum_free_gb=0.0,
            row_group_rows=4,
            shard_rows=8,
        )
        import_contact_table(
            artifact_id,
            source,
            right / artifact_id,
            minimum_free_gb=0.0,
            row_group_rows=2,
            shard_rows=8,
        )
    report = compare_contact_derivatives(
        left,
        right,
        tmp_path / "comparison.json",
        scan_batch_rows=2,
    )
    assert report["valid"]
