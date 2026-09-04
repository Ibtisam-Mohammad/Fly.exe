# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from flysim.connectome import SparseConnectome, import_aggregate_graph


def test_import_preserves_uint64_ids_and_aggregates_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "weights.csv"
    source.write_text(
        "body_pre,body_post,weight\n4294967297,9,2\n4294967297,9,3\n9,7,1\n",
        encoding="utf-8",
    )
    destination = tmp_path / "graph.npz"
    graph = import_aggregate_graph(source, destination)
    assert graph.body_ids.dtype == np.uint64
    assert graph.source_indices.dtype == np.uint32
    assert graph.contact_counts.dtype == np.uint32
    assert graph.neuron_count == 3
    assert graph.edge_count == 2
    assert sorted(graph.contact_counts.tolist()) == [1, 5]
    assert graph.body_id(graph.dense_index(4294967297)) == 4294967297
    restored = SparseConnectome.load(destination)
    assert np.array_equal(restored.body_ids, graph.body_ids)
    assert (tmp_path / "graph.json").exists()


def test_streaming_import_creates_mmap_graph_directory(tmp_path: Path) -> None:
    source = tmp_path / "weights.feather"
    feather.write_feather(
        pa.table(
            {
                "body_pre": pa.array([9, 12], type=pa.int64()),
                "body_post": pa.array([12, 9], type=pa.int64()),
                "weight": pa.array([3, 4], type=pa.int64()),
            }
        ),
        source,
    )
    destination = tmp_path / "graph"
    graph = import_aggregate_graph(source, destination, streaming_threshold_bytes=0)
    assert destination.is_dir()
    assert graph.neuron_count == 2
    assert graph.edge_count == 2
    assert graph.contact_counts.tolist() == [3, 4]
    assert (destination / "manifest.json").exists()
    restored = SparseConnectome.load(destination)
    assert np.array_equal(restored.source_indices, graph.source_indices)


def test_streaming_import_records_edges_excluded_by_annotation_universe(tmp_path: Path) -> None:
    source = tmp_path / "weights.feather"
    annotations = tmp_path / "annotations.feather"
    feather.write_feather(
        pa.table(
            {"body_pre": [9, 9], "body_post": [12, 99], "weight": [3, 2]}
        ),
        source,
    )
    feather.write_feather(
        pa.table({"bodyId": [9, 12], "status": ["Traced", "Traced"]}), annotations
    )
    destination = tmp_path / "graph"
    graph = import_aggregate_graph(
        source,
        destination,
        streaming_threshold_bytes=0,
        body_ids_source=annotations,
        body_statuses=("Traced",),
    )
    assert graph.body_ids.tolist() == [9, 12]
    assert graph.contact_counts.tolist() == [3]
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["annotation_candidate_count"] == 2
    assert manifest["raw_edge_count"] == 2
    assert manifest["excluded_edge_count"] == 1
    assert manifest["excluded_contact_count"] == 2
