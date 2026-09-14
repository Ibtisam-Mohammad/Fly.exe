# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import math

import pytest

from flysim.config import load_json, project_root
from flysim.errors import ValidationError
from flysim.swarm_showcase import HEIGHT, WIDTH, _closing_card, _opening_card, _reduced_snapshot


def test_swarm_agents_begin_with_alternating_body_relative_cue_bearings() -> None:
    scenario = load_json(project_root() / "configs/scenarios/swarm-cns-cinematic.json")
    flies = scenario["full_cns_flies"]
    assert len(flies) == 8
    signs: list[int] = []
    for fly in flies:
        target_bearing = math.atan2(-float(fly["y_mm"]), -float(fly["x_mm"]))
        relative = (target_bearing - float(fly["heading_rad"]) + math.pi) % (2 * math.pi) - math.pi
        assert math.degrees(abs(relative)) == pytest.approx(45.0, abs=0.01)
        signs.append(1 if relative > 0 else -1)
    assert signs == [1, -1, 1, -1, 1, -1, 1, -1]


def test_swarm_recording_fails_if_a_decoder_saw_target_coordinates() -> None:
    snapshot = {
        "arena": {
            "t_us": 0,
            "flies": [],
            "stimuli": [],
            "collision_events": 0,
        },
        "pending_commands": {"CNS-01": {"target_coordinates_available": True}},
        "causal_timing": None,
    }
    with pytest.raises(ValidationError, match="target coordinates"):
        _reduced_snapshot(snapshot)


def test_swarm_title_cards_render_at_release_resolution() -> None:
    scenario = load_json(project_root() / "configs/scenarios/swarm-cns-cinematic.json")
    manifest = {
        "graph": {
            "agents": 8,
            "neurons_per_agent": 165122,
            "edges_shared": 25563197,
        },
        "results": [
            {
                "distance_reduction_mm": 5.0,
                "final_distance_mm": 2.0,
                "approached_target": True,
            }
            for _ in range(8)
        ],
        "agents_approaching_target": 8,
        "collision_events": 2,
    }
    assert _opening_card(manifest, scenario).size == (WIDTH, HEIGHT)
    assert _closing_card(manifest).size == (WIDTH, HEIGHT)
