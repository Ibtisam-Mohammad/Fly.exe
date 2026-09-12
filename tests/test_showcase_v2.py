# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from flysim.cli import build_parser
from flysim.config import load_json
from flysim.showcase_v2 import evaluate_showcase_v2

REPO = Path(__file__).resolve().parents[1]
CONTRACT = load_json(REPO / "configs/experiments/eon-showcase-v2.json")


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "path": str(path.relative_to(path.parents[1])).replace("\\", "/"),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _controls() -> dict[str, dict[str, bool]]:
    return {
        name: {"passed": True}
        for name in (
            "readout-ablated",
            "stimulus-absent",
            "command-replay",
            "controller-only",
        )
    }


def _bundle(tmp_path: Path, *, grooming_displacement_passed: bool = True) -> Path:
    bundle_root = tmp_path / "bundle"
    evidence = bundle_root / "evidence"
    commit = "a" * 40
    navigation: list[dict[str, Any]] = []
    for target in CONTRACT["components"]["navigation"]["targets"]:
        criteria = {
            f"{prefix}_fixture": {"passed": True}
            for prefix in CONTRACT["components"]["navigation"]["required_criteria"]
        }
        verdict = {
            "experiment_id": "demo01-acceptance-v1",
            "criteria": criteria,
            "measured": {"exact": {"final_cue_distance_mm": 2.0}},
        }
        artifact = _write_json(evidence / f"navigation-{target['id']}.json", verdict)
        navigation.append(
            {
                "target_id": target["id"],
                "seed": target["seed"],
                "cue_position_mm": [target["cue_x_mm"], target["cue_y_mm"]],
                "code_commit": commit,
                "verdict": artifact,
                "controls": _controls(),
            }
        )
    grooming_criteria = {
        f"{prefix}_fixture": {"status": "pass"}
        for prefix in CONTRACT["components"]["grooming"]["required_criteria"]
    }
    if not grooming_displacement_passed:
        grooming_criteria["G6_fixture"] = {"status": "fail"}
    grooming = _write_json(
        evidence / "grooming.json",
        {
            "experiment_id": "demo02-grooming-v1",
            "verdict": "FULL-GRAPH CAUSAL GROOMING",
            "criteria": grooming_criteria,
        },
    )
    feeding = _write_json(
        evidence / "feeding.json",
        {
            "experiment_id": "demo02-feeding-v2",
            "verdict": "FULL-GRAPH CAUSAL PROBOSCIS EXTENSION FROM TARSAL TASTE",
            "criteria": {
                f"{prefix}_fixture": {"status": "pass"}
                for prefix in CONTRACT["components"]["feeding"]["required_criteria"]
            },
        },
    )
    video = bundle_root / "showcase.mp4"
    video.write_bytes(b"fixture video")
    render_manifest = _write_json(
        evidence / "render-manifest.json",
        {
            "duration_s": 72.0,
            "resolution": [1920, 1080],
            "fps": 30,
            "layout": "exact-versus-ablation",
            "chapters": ["navigation", "grooming", "feeding", "limitations"],
            "labels": CONTRACT["video"]["required_labels"],
        },
    )
    bundle = {
        "experiment_id": "eon-showcase-v2",
        "scientific_validation_tier_awarded": None,
        "components": {
            "navigation": navigation,
            "grooming": {
                "code_commit": commit,
                "verdict": grooming,
                "controls": _controls(),
            },
            "feeding": {
                "code_commit": commit,
                "verdict": feeding,
                "controls": _controls(),
            },
        },
        "video": {
            "path": "showcase.mp4",
            "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "manifest": render_manifest,
        },
    }
    path = bundle_root / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def test_v2_accepts_only_complete_independent_bundle(tmp_path: Path) -> None:
    report = evaluate_showcase_v2(contract=CONTRACT, bundle_path=_bundle(tmp_path))
    assert report["accepted_as_engineering_showcase"] is True
    assert report["scientific_validation_tier_awarded"] is None
    assert report["video"]["passed"] is True


def test_v2_rejects_grooming_that_exceeds_body_gate(tmp_path: Path) -> None:
    report = evaluate_showcase_v2(
        contract=CONTRACT,
        bundle_path=_bundle(tmp_path, grooming_displacement_passed=False),
    )
    assert report["accepted_as_engineering_showcase"] is False
    assert "grooming: independent behaviour contract did not pass" in report["failures"]


def test_v2_cli_is_explicit_and_does_not_replace_historical_v1_command() -> None:
    args = build_parser().parse_args(["showcase", "validate-v2", "bundle.json"])
    assert args.showcase_command == "validate-v2"
    assert args.bundle == Path("bundle.json")
    render = build_parser().parse_args(
        ["showcase", "render-v2", "bundle.json", "--output", "showcase.mp4"]
    )
    assert render.showcase_command == "render-v2"
    assert render.output == Path("showcase.mp4")
