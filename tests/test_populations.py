# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather

from flysim.populations import resolve_populations


def test_population_resolution_distinguishes_resolved_and_unresolved(tmp_path: Path) -> None:
    annotations = tmp_path / "annotations.feather"
    table = pa.table(
        {
            "bodyId": [10, 11],
            "instance": ["DNa01_L", "MN9_R"],
            "type": ["DNa01", "MN9"],
            "class": [None, None],
            "subclass": ["xl", "pm"],
            "entryNerve": [None, None],
            "exitNerve": [None, "PhN"],
            "receptorType": [None, None],
            "status": ["Traced", "Traced"],
        }
    )
    feather.write_feather(table, annotations)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "registry_id": "test",
                "dataset_id": "test:v1",
                "populations": [
                    {
                        "id": "dna",
                        "role": "test",
                        "combine": "any",
                        "queries": [{"field": "type", "operator": "exact", "value": "DNa01"}],
                        "expected_min": 1,
                        "expected_max": 1,
                        "provenance": "M",
                        "fallback": "none",
                    },
                    {
                        "id": "missing",
                        "role": "test",
                        "combine": "any",
                        "queries": [{"field": "type", "operator": "exact", "value": "oDN1"}],
                        "expected_min": 1,
                        "expected_max": 2,
                        "provenance": "P/E",
                        "fallback": "unresolved",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "resolution.json"
    result = resolve_populations(annotations, registry, output)
    assert result["populations"][0]["status"] == "resolved"
    assert result["populations"][0]["body_ids"] == [10]
    assert result["populations"][1]["status"] == "unresolved"
    assert result["all_required_resolved"] is False
    assert output.exists()

