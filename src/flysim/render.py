# SPDX-License-Identifier: GPL-2.0-or-later
"""Post-render engineering runs without changing their immutable manifests."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from flysim.errors import ReadinessError
from flysim.runs import read_trace


def showcase_disclosures(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Return the visible claim boundary for an engineering-showcase render."""
    connectome = manifest.get("connectome", {})
    graph_label = (
        f"full MaleCNS graph: {connectome.get('neurons', '?')} neurons, "
        f"{connectome.get('aggregate_edges', '?')} edges"
        if connectome.get("graph_used")
        else "reference controller without the MaleCNS graph"
    )
    return (
        graph_label,
        "central sensory bridges -> neural readouts -> controller-mediated body",
        "female body prior; no VNC-to-muscle pathway",
        "feeding initiation only; no ingestion",
        "ENGINEERING SHOWCASE - V0 Structural; no new validation tier",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_render_dependencies() -> tuple[Any, Any, Any]:
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ReadinessError(
            "Rendering requires the render extra: uv sync --extra render"
        ) from exc
    return imageio, Image, ImageDraw


def render_run(run_directory: Path, fps: int = 30) -> Path:
    if fps <= 0:
        raise ValueError("fps must be positive")
    imageio, image_class, draw_module = _load_render_dependencies()
    trace = read_trace(run_directory)
    if not trace:
        raise ReadinessError(f"Run trace is empty: {run_directory}")
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body_parameters = {
        "food_x_mm": 8.0,
        "food_y_mm": 1.0,
        "dust_x_mm": 3.0,
        "dust_y_mm": 0.35,
        "dust_radius_mm": 0.8,
    }
    recorded_geometry = manifest.get("run_metadata", {}).get("world_geometry", {})
    if isinstance(recorded_geometry, dict):
        for key in body_parameters:
            if key in recorded_geometry:
                body_parameters[key] = float(recorded_geometry[key])
    # Rendering constants affect only pixels, never simulation state.
    width, height = 960, 544
    x_min, x_max = -1.0, 9.5
    y_min, y_max = -2.25, 3.65

    def screen(x_mm: float, y_mm: float) -> tuple[int, int]:
        x = round((x_mm - x_min) / (x_max - x_min) * width)
        y = round(height - (y_mm - y_min) / (y_max - y_min) * height)
        return x, y

    final_t_us = int(trace[-1]["t_us"])
    frame_count = max(1, math.ceil(final_t_us / 1_000_000 * fps))
    selected: list[dict[str, Any]] = []
    trace_index = 0
    for frame_index in range(frame_count):
        target_us = round(frame_index / fps * 1_000_000)
        while trace_index + 1 < len(trace) and int(trace[trace_index + 1]["t_us"]) <= target_us:
            trace_index += 1
        selected.append(trace[trace_index])

    output_path = run_directory / "demo.mp4"
    writer = imageio.get_writer(output_path, fps=fps, codec="libx264", quality=8)
    trail: list[tuple[int, int]] = []
    try:
        for record in selected:
            image = image_class.new("RGB", (width, height), (245, 241, 229))
            draw = draw_module.Draw(image)
            draw.rectangle((0, height - 54, width, height), fill=(35, 38, 43))
            food = screen(body_parameters["food_x_mm"], body_parameters["food_y_mm"])
            dust = screen(body_parameters["dust_x_mm"], body_parameters["dust_y_mm"])
            dust_px = round(body_parameters["dust_radius_mm"] / (x_max - x_min) * width)
            draw.ellipse(
                (dust[0] - dust_px, dust[1] - dust_px, dust[0] + dust_px, dust[1] + dust_px),
                fill=(211, 197, 176),
                outline=(145, 126, 98),
                width=2,
            )
            draw.ellipse(
                (food[0] - 18, food[1] - 18, food[0] + 18, food[1] + 18),
                fill=(206, 61, 54),
            )
            draw.text((food[0] - 23, food[1] + 23), "food", fill=(70, 30, 25))
            draw.text((dust[0] - 28, dust[1] + dust_px + 8), "dust", fill=(85, 70, 50))

            body = record["body"]
            position = screen(float(body["x_mm"]), float(body["y_mm"]))
            trail.append(position)
            if len(trail) > 1:
                draw.line(trail, fill=(96, 126, 152), width=2)
            heading = float(body["heading_rad"])
            head = (
                position[0] + round(math.cos(heading) * 15),
                position[1] - round(math.sin(heading) * 15),
            )
            draw.ellipse(
                (position[0] - 13, position[1] - 8, position[0] + 13, position[1] + 8),
                fill=(41, 43, 47),
            )
            draw.ellipse((head[0] - 6, head[1] - 6, head[0] + 6, head[1] + 6), fill=(77, 79, 84))
            for offset in (-1, 1):
                draw.line(
                    (
                        position[0],
                        position[1],
                        position[0] - round(math.sin(heading + offset * 0.8) * 22),
                        position[1] - round(math.cos(heading + offset * 0.8) * 22),
                    ),
                    fill=(41, 43, 47),
                    width=3,
                )
            extension = float(body["proboscis_extension"])
            if extension > 0.0:
                endpoint = (
                    head[0] + round(math.cos(heading) * 22 * extension),
                    head[1] - round(math.sin(heading) * 22 * extension),
                )
                draw.line((head, endpoint), fill=(118, 65, 49), width=4)

            state = str(record["state"])
            contamination = float(body["contamination"])
            t_s = int(record["t_us"]) / 1_000_000
            neural = dict(
                zip(record["neural"]["ids"], record["neural"]["values"], strict=True)
            )
            disclosures = showcase_disclosures(manifest)
            draw.text((24, 18), "MaleCNS Virtual Fly - Eon-class showcase", fill=(20, 25, 31))
            draw.text((24, 42), f"t={t_s:5.2f}s  state={state}", fill=(20, 25, 31))
            draw.text((24, 66), f"antenna contamination={contamination:.2f}", fill=(20, 25, 31))
            draw.text(
                (24, 90),
                f"groom DN={neural['readout:antennal-grooming-DN']:.1f} Hz  "
                f"MN9={neural['readout:MN9']:.1f} Hz",
                fill=(20, 25, 31),
            )
            for index, disclosure in enumerate(disclosures[:-1]):
                draw.text((24, 114 + index * 22), disclosure, fill=(20, 25, 31))
            draw.text(
                (24, height - 36),
                disclosures[-1],
                fill=(255, 214, 88),
            )
            writer.append_data(np.asarray(image))
    finally:
        writer.close()

    render_manifest = {
        "schema_version": "1.0",
        "source_run_id": manifest["run_id"],
        "source_manifest_sha256": _sha256_file(manifest_path),
        "video": output_path.name,
        "video_sha256": _sha256_file(output_path),
        "fps": fps,
        "playback": "one biological second per video second",
        "label": (
            "engineering showcase; full MaleCNS graph where recorded; central sensory "
            "bridges; controller-mediated body; female body prior; no VNC-to-muscle "
            "pathway; feeding initiation only; no ingestion; no new validation tier"
        ),
    }
    (run_directory / "render-manifest.json").write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_path.resolve()
