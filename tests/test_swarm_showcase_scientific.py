# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import numpy as np

from flysim.swarm_showcase_scientific import (
    HEIGHT,
    WIDTH,
    _build_strips,
    _closing_card,
    _opening_card,
)


def _manifest() -> dict[str, object]:
    return {
        "seed": 7,
        "graph": {
            "agents": 2,
            "neurons_per_agent": 165122,
            "edges_shared": 25563197,
            "model_identity": "a" * 64,
        },
        "agents_approaching_target": 2,
        "results": [
            {"distance_reduction_mm": 8.0, "final_distance_mm": 3.0},
            {"distance_reduction_mm": 10.0, "final_distance_mm": 1.0},
        ],
    }


def test_reference_style_cards_render_at_release_resolution() -> None:
    manifest = _manifest()
    assert _opening_card(manifest).size == (WIDTH, HEIGHT)
    assert _closing_card(manifest).size == (WIDTH, HEIGHT)


def test_reference_style_strips_are_derived_from_recorded_rows() -> None:
    target = {"x_mm": 0.0, "y_mm": 0.0}
    rows = [
        {
            "flies": [
                {"id": "A", "x_mm": 4.0, "y_mm": 0.0},
                {"id": "B", "x_mm": 0.0, "y_mm": 6.0},
            ],
            "commands": {
                "A": {
                    "descending_left_hz": 2.0,
                    "descending_right_hz": 4.0,
                    "forward": 0.2,
                    "yaw": -0.6,
                },
                "B": {
                    "descending_left_hz": 6.0,
                    "descending_right_hz": 8.0,
                    "forward": 0.4,
                    "yaw": 0.2,
                },
            },
        },
        {
            "flies": [
                {"id": "A", "x_mm": 2.0, "y_mm": 0.0},
                {"id": "B", "x_mm": 0.0, "y_mm": 4.0},
            ],
            "commands": {
                "A": {
                    "descending_left_hz": 3.0,
                    "descending_right_hz": 5.0,
                    "forward": 0.6,
                    "yaw": -0.4,
                },
                "B": {
                    "descending_left_hz": 7.0,
                    "descending_right_hz": 9.0,
                    "forward": 0.8,
                    "yaw": 0.4,
                },
            },
        },
    ]
    distance, descending, command = _build_strips(rows, ["A", "B"], target)
    assert np.allclose(distance.channels[1].values, [5.0, 3.0])
    assert np.allclose(descending.channels[0].values, [4.0, 5.0])
    assert np.allclose(command.channels[0].values, [0.3, 0.7])
    assert np.allclose(command.channels[1].values, [0.4, 0.4])
