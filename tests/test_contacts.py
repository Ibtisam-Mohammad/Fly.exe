# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.contacts import (
    audit_contact_derivatives,
    compare_contact_derivatives,
    import_contact_table,
)
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


def test_contact_audit_resolves_pre_and_post_endpoints_separately(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")

    def point_id(x: int, y: int, z: int) -> int:
        return (z << 42) | (y << 21) | x

    pre = (1, 1, 1)
    posts = ((2, 1, 1), (3, 1, 1))
    tables = {
        "syn-points": pa.table(
            {
                "point_id": pa.array(
                    [point_id(*pre), *(point_id(*post) for post in posts)],
                    type=pa.uint64(),
                ),
                "x": [pre[0], *(post[0] for post in posts)],
                "y": [pre[1], *(post[1] for post in posts)],
                "z": [pre[2], *(post[2] for post in posts)],
                "body": pa.array([10, 20, 20], type=pa.uint64()),
                "conf": [0.9, 0.8, 0.8],
                "kind": ["PreSyn", "PostSyn", "PostSyn"],
            }
        ),
        "syn-partners": pa.table(
            {
                "x_pre": [pre[0], pre[0]],
                "y_pre": [pre[1], pre[1]],
                "z_pre": [pre[2], pre[2]],
                "body_pre": pa.array([10, 10], type=pa.uint64()),
                "conf_pre": [0.9, 0.9],
                "x_post": [post[0] for post in posts],
                "y_post": [post[1] for post in posts],
                "z_post": [post[2] for post in posts],
                "body_post": pa.array([20, 20], type=pa.uint64()),
                "conf_post": [0.8, 0.8],
            }
        ),
        "connectome-weights": pa.table(
            {
                "body_pre": pa.array([10], type=pa.uint64()),
                "body_post": pa.array([20], type=pa.uint64()),
                "weight": [2],
            }
        ),
        "tbar-neurotransmitters": pa.table(
            {
                "point_id": pa.array([point_id(*pre)], type=pa.uint64()),
                "x": [pre[0]],
                "y": [pre[1]],
                "z": [pre[2]],
                "body": pa.array([10], type=pa.uint64()),
                "conf": [0.9],
                "nt_acetylcholine_prob": [0.1],
                "nt_dopamine_prob": [0.1],
                "nt_gaba_prob": [0.1],
                "nt_glutamate_prob": [0.1],
                "nt_histamine_prob": [0.1],
                "nt_octopamine_prob": [0.1],
                "nt_serotonin_prob": [0.1],
            }
        ),
    }
    contacts = tmp_path / "contacts"
    for artifact_id, table in tables.items():
        source = tmp_path / f"{artifact_id}.feather"
        feather.write_feather(table, source, chunksize=1)
        import_contact_table(
            artifact_id,
            source,
            contacts / artifact_id,
            minimum_free_gb=0,
            row_group_rows=1,
            shard_rows=4,
        )

    report = audit_contact_derivatives(
        contacts,
        tmp_path / "audit.json",
        tmp_path / "duckdb-temp",
        memory_limit_gb=0.25,
        threads=1,
    )

    assert report["valid"] is True
    assert report["checks"]["partner_pre_endpoint_resolution"]["observed"] == 0
    assert report["checks"]["partner_post_endpoint_resolution"]["observed"] == 0
    assert report["checks"]["partner_endpoint_resolution"]["observed"] == 0
