# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather

from flysim.universes import audit_body_universes


def test_body_universe_sensitivity_is_nested_and_loss_aware(tmp_path: Path) -> None:
    annotations = tmp_path / "annotations.feather"
    aggregate = tmp_path / "weights.feather"
    feather.write_feather(
        pa.table({"bodyId": [1, 2, 3], "status": ["Traced", "Assign", "Anchor"]}),
        annotations,
    )
    feather.write_feather(
        pa.table(
            {
                "body_pre": [1, 1, 2, 3],
                "body_post": [1, 2, 3, 1],
                "weight": [2, 3, 5, 7],
            }
        ),
        aggregate,
    )
    report = audit_body_universes(
        annotations, aggregate, tmp_path / "report.json", canary_body_ids=(1, 2)
    )

    assert report["universes"]["all-segment"]["edges"] == 4
    assert report["universes"]["Traced"]["edges"] == 1
    assert report["universes"]["Traced+Assign"]["edges"] == 2
    assert report["universes"]["Traced+Assign+Anchor"]["edges"] == 4
    assert report["canary_motif"]["internal_contacts"] == 5
