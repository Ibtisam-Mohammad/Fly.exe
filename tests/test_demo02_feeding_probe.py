# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

from flysim.config import load_json, project_root
from flysim.demo02_feeding_probe import score_feeding_candidate, select_operating_point, spearman


def _measured(counts: list[int]) -> dict[str, object]:
    rows: dict[str, object] = {
        "baseline": {
            "readout_spikes": 0,
            "readout_hz": 0.0,
            "motor_mean_hz": 1.0,
            "motor_active_fraction": 0.01,
        },
        "recovery": {
            "readout_spikes": 0,
            "readout_hz": 0.0,
            "motor_mean_hz": 1.0,
            "motor_active_fraction": 0.01,
        },
    }
    for value, count in zip((0.25, 0.5, 0.75, 1.0), counts, strict=True):
        rows[f"concentration_{value:g}"] = {
            "concentration": value,
            "readout_spikes": count,
            "readout_hz": float(count),
            "motor_mean_hz": 10.0,
            "motor_active_fraction": 0.1,
        }
    return {"epochs": rows}


def test_spearman_handles_ties_without_scipy() -> None:
    assert spearman([0.25, 0.5, 0.75, 1.0], [1, 2, 2, 4]) > 0.9


def test_feeding_candidate_requires_large_graded_recovering_response() -> None:
    contract = load_json(
        project_root() / "configs/experiments/demo02-feeding-operating-point-v1.json"
    )
    score = score_feeding_candidate(_measured([5, 10, 15, 25]), contract)
    assert score["passes"] is True
    failed = score_feeding_candidate(_measured([0, 0, 0, 1]), contract)
    assert failed["passes"] is False
    assert failed["N2_the_route_responds"] is False


def test_feeding_selection_follows_frozen_rule() -> None:
    rows = [
        {
            "candidate": {
                "taste_max_rate_hz": 400.0,
                "synaptic_mv_per_contact": 0.7,
                "inhibitory_weight_gain": 1.5,
            },
            "score": {"passes": True, "values": {"response_range_spikes": 30}},
        },
        {
            "candidate": {
                "taste_max_rate_hz": 200.0,
                "synaptic_mv_per_contact": 0.5,
                "inhibitory_weight_gain": 2.0,
            },
            "score": {"passes": True, "values": {"response_range_spikes": 30}},
        },
    ]
    assert select_operating_point(rows) == rows[1]
