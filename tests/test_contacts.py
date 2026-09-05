# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather

from flysim.contacts import import_contact_table
from flysim.datasets import sha256_file


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
