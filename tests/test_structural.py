# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.parquet as pq

import flysim.structural as structural
from flysim.evidence import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_confidence_sensitivity_is_monotonic(tmp_path: Path) -> None:
    table = pa.table(
        {
            "conf_pre": [0.5, 0.7, 0.9],
            "conf_post": [0.6, 0.8, 1.0],
        }
    )
    pq.write_table(table, tmp_path / "part-000000.parquet")

    result = structural._confidence_sensitivity(tmp_path)

    assert result["valid"] is True
    assert result["threshold_counts"] == {
        "0.5": 3,
        "0.6": 2,
        "0.7": 2,
        "0.8": 1,
        "0.9": 1,
    }


def test_cross_connectome_review_uses_pinned_card(tmp_path: Path) -> None:
    edge_path = tmp_path / "mcns_fw_edge_comp.feather"
    feather.write_feather(
        pa.table(
            {
                "pre": ["A", "B"],
                "post": ["B", "A"],
                "weight_m": [2.0, 0.0],
                "weight_f": [1.0, 3.0],
                "t": [0.0, 1.0],
                "p_corr": [0.5, 0.5],
                "verdict_corr": ["isomorphic", "dimorphic"],
            }
        ),
        edge_path,
    )
    mappings_path = tmp_path / "mcns_fw_edge_comp_mappings.json"
    _write_json(mappings_path, {"1": "A", "2": "B"})
    notebook_path = tmp_path / "quantify-neuron-connections.ipynb"
    _write_json(
        notebook_path,
        {"outputs": [str(value) for value in structural.NOTEBOOK_OUTPUT_COUNTS]},
    )
    artifacts = []
    for path in (edge_path, mappings_path, notebook_path):
        record: dict[str, object] = {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path == edge_path:
            record["rows"] = 2
        if path == mappings_path:
            record["entries"] = 2
        artifacts.append(record)
    card = tmp_path / "card.json"
    _write_json(
        card,
        {
            "source_commit": "67767d2233657983993ff6c2be48e836a935863c",
            "artifacts": artifacts,
        },
    )

    result = structural._cross_connectome_review(tmp_path, card)

    assert result["valid"] is True
    assert result["aligned_edge_rows"] == 2
    assert result["mapping_rows"] == 2
