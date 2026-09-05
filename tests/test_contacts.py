# SPDX-License-Identifier: GPL-2.0-or-later
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
