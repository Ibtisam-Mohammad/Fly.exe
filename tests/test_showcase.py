# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flysim.cli import build_parser
from flysim.config import load_json
from flysim.render import showcase_disclosures
from flysim.showcase import _latest_reusable_run, evaluate_showcase
from flysim.showcase_cinematic import food_distance_mm

REPO = Path(__file__).resolve().parents[1]
CONTRACT = load_json(REPO / "configs/experiments/eon-showcase-v1.json")


def _run(
    root: Path,
    name: str,
    *,
    seed: int,
    states: list[str],
    completed: bool,
    commit: str = "a" * 40,
    groom_displacement_mm: float = 1.0,
) -> Path:
    directory = root / name
    directory.mkdir()
    events = [
        {
            "t_us": (index + 1) * 15_000,
            "from_state": "SEEK",
            "to_state": state,
            "reason": "fixture",
        }
        for index, state in enumerate(states)
    ]
    manifest: dict[str, Any] = {
        "created_at": "2026-09-12T00:00:00+00:00",
        "random_seed": seed,
        "scenario": {"id": CONTRACT["scenario_id"]},
        "git": {"commit": commit, "dirty": False, "evidence_grade": True},
        "connectome": {
            "neurons": 165122,
            "aggregate_edges": 25563197,
            "threshold_applied": False,
            "control_variant": "exact",
        },
        "interventions": {"ablated_input_ids": [], "ablated_output_ids": []},
        "run_metadata": {
            "requested_duration_us": 12_000_000,
            "food_position_mm": [8.0, 1.0],
        },
        "result": {
            "completed": completed,
            "events": events,
            "highest_validation_tier": None,
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "validation-report.json").write_text(
        json.dumps(
            {
                "valid": True,
                "behavioral_criteria": {
                    "groom_net_displacement_mm": groom_displacement_mm,
                    "groom_net_displacement_limit_mm": 2.5,
                    "groom_net_displacement_passed": groom_displacement_mm <= 2.5,
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def _matrix(tmp_path: Path) -> tuple[dict[int, Path], dict[str, Path], dict[str, Path]]:
    sequence = ["GROOM", "SEEK_RESUME", "FEED_INITIATION", "COMPLETE"]
    exact = {
        1: _run(tmp_path, "exact-1", seed=1, states=sequence, completed=True),
        2: _run(tmp_path, "exact-2", seed=2, states=sequence, completed=True),
        3: _run(tmp_path, "exact-3", seed=3, states=["GROOM"], completed=False),
    }
    controls = {
        "contamination-input-ablated": _run(
            tmp_path, "c-contamination", seed=1, states=[], completed=False
        ),
        "groom-readout-ablated": _run(tmp_path, "c-groom", seed=1, states=[], completed=False),
        "sucrose-input-ablated": _run(
            tmp_path,
            "c-sucrose",
            seed=1,
            states=["GROOM", "SEEK_RESUME"],
            completed=False,
        ),
        "mn9-readout-ablated": _run(
            tmp_path,
            "c-mn9",
            seed=1,
            states=["GROOM", "SEEK_RESUME"],
            completed=False,
        ),
    }
    diagnostics = {
        "zero-weight": _run(tmp_path, "d-zero", seed=1, states=[], completed=False),
        "shuffled-connectome": _run(
            tmp_path, "d-shuffle", seed=1, states=["GROOM"], completed=False
        ),
    }
    return exact, controls, diagnostics


def test_showcase_accepts_two_of_three_and_four_causal_controls(tmp_path: Path) -> None:
    exact, controls, diagnostics = _matrix(tmp_path)
    report = evaluate_showcase(
        contract=CONTRACT,
        exact_directories=exact,
        control_directories=controls,
        diagnostic_directories=diagnostics,
    )

    assert report["accepted_as_engineering_showcase"] is True
    assert report["completed_exact_seeds"] == 2
    assert report["scientific_validation_tier_awarded"] is None
    assert all(item["passed"] for item in report["required_controls"].values())
    assert all(item["gates_acceptance"] is False for item in report["diagnostic_controls"].values())


def test_showcase_fails_closed_when_an_ablation_reaches_its_state(tmp_path: Path) -> None:
    exact, controls, diagnostics = _matrix(tmp_path)
    controls["mn9-readout-ablated"] = _run(
        tmp_path,
        "bad-mn9",
        seed=1,
        states=["GROOM", "SEEK_RESUME", "FEED_INITIATION"],
        completed=False,
    )

    report = evaluate_showcase(
        contract=CONTRACT,
        exact_directories=exact,
        control_directories=controls,
        diagnostic_directories=diagnostics,
    )

    assert report["accepted_as_engineering_showcase"] is False
    assert "control mn9-readout-ablated did not block FEED_INITIATION" in report["failures"]


def test_showcase_fails_closed_on_recorded_grooming_displacement(tmp_path: Path) -> None:
    exact, controls, diagnostics = _matrix(tmp_path)
    exact[1] = _run(
        tmp_path,
        "exact-1-drifting",
        seed=1,
        states=["GROOM", "SEEK_RESUME", "FEED_INITIATION", "COMPLETE"],
        completed=True,
        groom_displacement_mm=8.477,
    )

    report = evaluate_showcase(
        contract=CONTRACT,
        exact_directories=exact,
        control_directories=controls,
        diagnostic_directories=diagnostics,
    )

    assert report["accepted_as_engineering_showcase"] is False
    assert any("grooming-displacement gate" in item for item in report["failures"])


def test_showcase_labels_chain_coupled_controls_honestly(tmp_path: Path) -> None:
    exact, controls, diagnostics = _matrix(tmp_path)
    report = evaluate_showcase(
        contract=CONTRACT,
        exact_directories=exact,
        control_directories=controls,
        diagnostic_directories=diagnostics,
    )

    assert (
        report["required_controls"]["contamination-input-ablated"]["control_class"]
        == "sequence-dependency"
    )
    assert (
        report["required_controls"]["sucrose-input-ablated"]["control_class"]
        == "causal-interface-ablation"
    )


def test_showcase_cli_surface_is_stable() -> None:
    args = build_parser().parse_args(
        ["showcase", "build", "--root", "/srv/flybrain-data", "--no-render"]
    )
    assert args.showcase_command == "build"
    assert args.no_render is True


def test_showcase_render_discloses_every_claim_boundary() -> None:
    labels = showcase_disclosures(
        {
            "connectome": {
                "graph_used": True,
                "neurons": 165122,
                "aggregate_edges": 25563197,
            }
        }
    )
    joined = " | ".join(labels)
    for required in CONTRACT["required_video_labels"]:
        assert required in joined


def test_showcase_resume_requires_the_complete_condition_signature(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        "exact",
        seed=1,
        states=["GROOM"],
        completed=False,
    )
    expected = {
        "commit": "a" * 40,
        "seed": 1,
        "scenario_id": CONTRACT["scenario_id"],
        "food_position": [8.0, 1.0],
        "ablated_inputs": (),
        "ablated_outputs": (),
        "control_variant": "exact",
    }

    assert _latest_reusable_run(tmp_path, duration_us=12_000_000, **expected) == run
    assert _latest_reusable_run(tmp_path, duration_us=11_000_000, **expected) is None


def test_cinematic_cli_surface_is_stable() -> None:
    args = build_parser().parse_args(
        [
            "showcase",
            "cinematic",
            "--root",
            "/srv/flybrain-data",
            "--fps",
            "24",
            "--source-directory",
            "/tmp/presentation",
        ]
    )
    assert args.showcase_command == "cinematic"
    assert args.fps == 24
    assert args.source_directory == Path("/tmp/presentation")


def test_cinematic_food_distance_uses_recorded_thorax_pose() -> None:
    row = {"body": {"x_mm": 8.6, "y_mm": 1.8}}
    assert food_distance_mm(row, (8.0, 1.0)) == pytest.approx(1.0)
