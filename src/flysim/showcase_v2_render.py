# SPDX-License-Identifier: GPL-2.0-or-later
"""Render the corrected showcase as an exact-versus-ablation editorial comparison."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

from flysim.config import load_json
from flysim.errors import ReadinessError, ValidationError
from flysim.runs import require_clean_worktree
from flysim.showcase_v2 import evaluate_showcase_v2

WIDTH, HEIGHT = 1920, 1080


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Chapter:
    name: str
    title: str
    duration_s: float
    exact: Path
    ablation: Path
    exact_sha256: str
    ablation_sha256: str


def _font(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _resolve_video(root: Path, raw: dict[str, Any]) -> tuple[Path, str]:
    path = (root / Path(str(raw["path"]))).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValidationError(f"Presentation source is missing or outside the bundle: {path}")
    digest = _sha256(path)
    if digest != str(raw["sha256"]):
        raise ValidationError(f"Presentation source checksum mismatch: {path}")
    return path, digest


def _chapters(bundle: dict[str, Any], root: Path) -> tuple[Chapter, ...]:
    source = bundle.get("presentation_sources")
    if not isinstance(source, dict):
        raise ValidationError("v2 draft bundle has no presentation_sources object")
    titles = {
        "navigation": "Visual target approach",
        "grooming": "Antennal-grooming initiation",
        "feeding": "Tarsal-taste feeding initiation",
    }
    result: list[Chapter] = []
    for name in ("navigation", "grooming", "feeding"):
        raw = source.get(name)
        if not isinstance(raw, dict):
            raise ValidationError(f"Presentation sources are missing {name}")
        exact, exact_hash = _resolve_video(root, raw["exact"])
        ablation, ablation_hash = _resolve_video(root, raw["ablation"])
        result.append(
            Chapter(
                name=name,
                title=titles[name],
                duration_s=16.0,
                exact=exact,
                ablation=ablation,
                exact_sha256=exact_hash,
                ablation_sha256=ablation_hash,
            )
        )
    return tuple(result)


def _card(title: str, lines: list[str]) -> np.ndarray:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (WIDTH, HEIGHT), (9, 13, 22))
    draw = ImageDraw.Draw(canvas)
    draw.text((90, 105), title, font=_font(52), fill=(242, 248, 255))
    y = 235
    for line in lines:
        draw.text((110, y), line, font=_font(28), fill=(172, 195, 220))
        y += 64
    draw.text(
        (90, 1010),
        "ENGINEERING SHOWCASE | V0 Structural; no new validation tier",
        font=_font(22),
        fill=(255, 190, 75),
    )
    return np.asarray(canvas)


def _panel(frame: np.ndarray, size: tuple[int, int]) -> Any:
    from PIL import Image

    image = Image.fromarray(np.asarray(frame, dtype=np.uint8)).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    return image


def render_showcase_v2(
    *,
    contract_path: Path,
    bundle_path: Path,
    output_path: Path,
    fps: int = 30,
) -> dict[str, Any]:
    """Render only after all non-video gates pass; never advance simulator state."""
    if fps < 30:
        raise ValidationError("The v2 contract requires at least 30 fps")
    contract = load_json(contract_path)
    readiness = evaluate_showcase_v2(
        contract=contract, bundle_path=bundle_path, require_video=False
    )
    if not readiness["ready_for_cinematic"]:
        raise ReadinessError(
            "The v2 component gates did not pass; refusing to make a persuasive video: "
            + "; ".join(readiness["failures"])
        )
    clean = require_clean_worktree("The corrected Eon showcase render")
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ReadinessError("The v2 renderer needs imageio and Pillow") from exc

    bundle = load_json(bundle_path)
    root = bundle_path.parent.resolve()
    chapters = _chapters(bundle, root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        output_path, fps=fps, codec="libx264", quality=9, macro_block_size=1
    )
    opening_s, limitations_s, closing_s = 5.0, 8.0, 5.0
    labels = list(contract["video"]["required_labels"])
    sources: dict[str, Any] = {}
    try:
        opening = _card(
            "A virtual fly, with the controls beside it",
            [
                "Three independently executed full-graph behaviour chapters",
                "Left: exact run    Right: causal ablation",
                "Visual approach, grooming initiation, feeding initiation",
                "Engineering controllers are labelled; no ingestion is claimed",
            ],
        )
        for _ in range(round(opening_s * fps)):
            writer.append_data(opening)
        for chapter in chapters:
            exact_reader = imageio.get_reader(chapter.exact)
            ablation_reader = imageio.get_reader(chapter.ablation)
            try:
                exact_count = int(cast(Any, exact_reader).count_frames())
                ablation_count = int(cast(Any, ablation_reader).count_frames())
                if exact_count < 1 or ablation_count < 1:
                    raise ValidationError(f"Empty video source for {chapter.name}")
                frames = round(chapter.duration_s * fps)
                sources[chapter.name] = {
                    "exact": {"path": str(chapter.exact), "sha256": chapter.exact_sha256},
                    "ablation": {
                        "path": str(chapter.ablation),
                        "sha256": chapter.ablation_sha256,
                    },
                    "source_frames": [exact_count, ablation_count],
                    "presentation_frames": frames,
                }
                for index in range(frames):
                    left = _panel(exact_reader.get_data(index % exact_count), (920, 760))
                    right = _panel(ablation_reader.get_data(index % ablation_count), (920, 760))
                    canvas = Image.new("RGB", (WIDTH, HEIGHT), (9, 13, 22))
                    draw = ImageDraw.Draw(canvas)
                    draw.text((32, 24), chapter.title, font=_font(38), fill=(242, 248, 255))
                    draw.text((35, 95), "EXACT FULL GRAPH", font=_font(25), fill=(90, 220, 180))
                    draw.text((995, 95), "CAUSAL ABLATION", font=_font(25), fill=(255, 120, 110))
                    canvas.paste(left, (20 + (920 - left.width) // 2, 145))
                    canvas.paste(right, (980 + (920 - right.width) // 2, 145))
                    draw.text(
                        (28, 930),
                        "Offline comparison; source clips may loop to fill the editorial chapter",
                        font=_font(21),
                        fill=(160, 175, 195),
                    )
                    draw.text(
                        (28, 985),
                        "ENGINEERING SHOWCASE | V0 Structural | separately executed chapters",
                        font=_font(23),
                        fill=(255, 190, 75),
                    )
                    writer.append_data(np.asarray(canvas))
            finally:
                exact_reader.close()
                ablation_reader.close()
        limitations = _card(
            "What the demonstration does not establish",
            [
                "Not a digital twin and not recovered source-fly physiology",
                "Female NeuroMechFly body prior; engineered locomotor controller",
                "Grooming movement is a trajectory replay triggered by neural output",
                "Feeding chapter stops at rostrum extension: no ingestion or pumping",
                "The three chapters are separate experiments, not one autonomous run",
            ],
        )
        for _ in range(round(limitations_s * fps)):
            writer.append_data(limitations)
        closing = _card(
            "Showcase complete — evidence boundary unchanged",
            [
                "Every visual claim is paired with a causal control",
                "All source recordings and this render are checksum locked",
                "Scientific ceiling remains V0 Structural",
            ],
        )
        for _ in range(round(closing_s * fps)):
            writer.append_data(closing)
    finally:
        writer.close()

    duration_s = opening_s + sum(item.duration_s for item in chapters) + limitations_s + closing_s
    manifest = {
        "schema_version": "2.0",
        "experiment_id": contract["experiment_id"],
        "renderer_commit": clean["commit"],
        "renderer_worktree_dirty": clean["dirty"],
        "duration_s": duration_s,
        "resolution": [WIDTH, HEIGHT],
        "fps": fps,
        "layout": "exact-versus-ablation",
        "chapters": ["navigation", "grooming", "feeding", "limitations"],
        "labels": labels,
        "sources": sources,
        "video": str(output_path.resolve()),
        "video_sha256": _sha256(output_path),
        "rendering_advanced_simulator_state": False,
        "scientific_validation_tier_awarded": None,
    }
    manifest_path = output_path.with_name("render-manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {**manifest, "manifest": str(manifest_path.resolve())}


__all__ = ["Chapter", "render_showcase_v2"]
