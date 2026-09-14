# SPDX-License-Identifier: GPL-2.0-or-later
"""Reference-style scientific renderer for a recorded multi-state MaleCNS cohort.

The renderer never advances simulation state. The arena shows recorded x/y/heading with a
NeuroMechFly mesh as a presentation proxy; it must not be mistaken for recorded MuJoCo gait.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json
from flysim.demo01_render import (
    BrainAtlas,
    BrainProjection,
    TraceChannel,
    TraceStrip,
    draw_strips,
    render_brain,
)
from flysim.errors import ConfigurationError, ReadinessError, ValidationError

WIDTH = 1920
HEIGHT = 1080
HEADER_HEIGHT = 70
PANEL_HEIGHT = 640
TRACE_HEIGHT = 310
FOOTER_HEIGHT = 60
BRAIN_WIDTH = 1120
BACKGROUND = (9, 11, 16)
PANEL = (14, 17, 24)
INK = (232, 236, 244)
DIM = (128, 138, 156)
WARN = (255, 206, 84)
COOL = (120, 180, 255)
LEFT = (255, 90, 110)
RIGHT = (255, 190, 90)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _fonts() -> dict[str, Any]:
    from PIL import ImageFont

    def pick(size: int, *, bold: bool = False) -> Any:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        )
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default()

    return {
        "title": pick(27),
        "body": pick(17),
        "small": pick(14),
        "tiny": pick(12),
        "title_bold": pick(27, bold=True),
        "body_bold": pick(17, bold=True),
    }


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _card(
    manifest: dict[str, Any],
    *,
    heading: str,
    sections: list[tuple[str, str]],
    footer: str,
) -> Any:
    from PIL import Image, ImageDraw

    fonts = _fonts()
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    y = 120
    draw.text((140, y), heading, font=fonts["title"], fill=INK)
    y += 72
    draw.line((140, y, WIDTH - 140, y), fill=(40, 48, 62), width=2)
    y += 42
    for label, body in sections:
        draw.text((140, y), label, font=fonts["body"], fill=WARN)
        y += 31
        for line in _wrap(draw, body, fonts["body"], WIDTH - 320):
            draw.text((160, y), line, font=fonts["body"], fill=INK)
            y += 28
        y += 22
    footer_y = HEIGHT - 125
    for line in _wrap(draw, footer, fonts["small"], WIDTH - 320):
        draw.text((140, footer_y), line, font=fonts["small"], fill=DIM)
        footer_y += 24
    return canvas


def _opening_card(manifest: dict[str, Any]) -> Any:
    graph = manifest["graph"]
    return _card(
        manifest,
        heading="Eight independent MaleCNS states in one shared visual world",
        sections=[
            (
                "WHAT IS EXECUTED",
                f"{graph['agents']} independent states of {graph['neurons_per_agent']:,} "
                f"neurons. One {graph['edges_shared']:,}-edge MaleCNS topology is allocated "
                "once and stepped for every state.",
            ),
            (
                "THE ONLY ROUTE TO MOTION",
                "body-relative cue geometry, a retinotopic lamina drive, the complete runtime "
                "graph, bilateral descending rates, a causal engineering decoder, then the "
                "recorded body command. The decoder receives no target coordinates.",
            ),
            (
                "BODY VIEW",
                "The arena replays recorded x, y and heading. A NeuroMechFly mesh is used only "
                "as an anatomical pose proxy; these are not eight recorded MuJoCo gaits.",
            ),
            (
                "SCIENTIFIC CEILING",
                "V0 Structural. This is cohort target approach, not biological swarming, social "
                "coordination, validated physiology, or eight reconstructed animals.",
            ),
        ],
        footer=(
            f"seed {manifest['seed']}    model {graph['model_identity'][:16]}    "
            "presentation recording; no scientific tier is awarded"
        ),
    )


def _closing_card(manifest: dict[str, Any]) -> Any:
    results = manifest["results"]
    reductions = np.asarray([row["distance_reduction_mm"] for row in results], dtype=np.float64)
    final = np.asarray([row["final_distance_mm"] for row in results], dtype=np.float64)
    return _card(
        manifest,
        heading="What this recording does and does not establish",
        sections=[
            (
                "RECORDED RESULT",
                f"{manifest['agents_approaching_target']} of {len(results)} states moved closer. "
                f"Median distance reduction {np.median(reductions):.2f} mm; final distance "
                f"range {np.min(final):.2f} to {np.max(final):.2f} mm.",
            ),
            (
                "WHAT RAN",
                "Each state received its own body-relative visual input and maintained separate "
                "neural and random state. One immutable topology and sparse edge allocation were "
                "shared. Rendering read the saved trace and did not advance the model.",
            ),
            (
                "WHAT MAY NOT BE CLAIMED",
                "The flies do not sense or follow one another. This is not collective "
                "intelligence, social behaviour, validated neural physiology, or a complete "
                "neuromuscular simulation.",
            ),
        ],
        footer=(
            "Visual encoder, transmitter-sign LIF, decoder and kinematic body are P/E. "
            "The displayed NeuroMechFly mesh is a pose proxy. Tier remains V0 Structural."
        ),
    )


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) < 2:
        raise ValidationError("Swarm trace is too short to render")
    return rows


def _column(
    rows: list[dict[str, Any]], agent_ids: list[str], key: str, *, default: float = 0.0
) -> np.ndarray:
    values = np.empty((len(agent_ids), len(rows)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        commands = row["commands"]
        for agent_index, agent_id in enumerate(agent_ids):
            value = commands[agent_id].get(key)
            values[agent_index, row_index] = default if value is None else float(value)
    return values


def _distance_series(
    rows: list[dict[str, Any]], agent_ids: list[str], target: dict[str, Any]
) -> np.ndarray:
    values = np.empty((len(agent_ids), len(rows)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        flies = {str(fly["id"]): fly for fly in row["flies"]}
        for agent_index, agent_id in enumerate(agent_ids):
            fly = flies[agent_id]
            values[agent_index, row_index] = math.hypot(
                float(fly["x_mm"]) - float(target["x_mm"]),
                float(fly["y_mm"]) - float(target["y_mm"]),
            )
    return values


def _build_strips(
    rows: list[dict[str, Any]], agent_ids: list[str], target: dict[str, Any]
) -> tuple[TraceStrip, ...]:
    distances = _distance_series(rows, agent_ids, target)
    left = _column(rows, agent_ids, "descending_left_hz")
    right = _column(rows, agent_ids, "descending_right_hz")
    forward = _column(rows, agent_ids, "forward")
    yaw = _column(rows, agent_ids, "yaw")
    return (
        TraceStrip(
            title="target distance across eight independent states",
            unit="mm",
            channels=(
                TraceChannel("farthest", distances.max(axis=0), DIM),
                TraceChannel("cohort median", np.median(distances, axis=0), COOL),
                TraceChannel("nearest", distances.min(axis=0), (180, 192, 212)),
            ),
        ),
        TraceStrip(
            title="descending readout, causally filtered: cohort mean",
            unit="Hz",
            channels=(
                TraceChannel("DNp left", left.mean(axis=0), LEFT),
                TraceChannel("DNp right", right.mean(axis=0), RIGHT),
            ),
        ),
        TraceStrip(
            title="decoder command, the only quantity received by each body",
            unit="normalised",
            channels=(
                TraceChannel("mean forward drive", forward.mean(axis=0), (200, 220, 255)),
                TraceChannel("mean absolute turn drive", np.abs(yaw).mean(axis=0), (210, 150, 190)),
            ),
        ),
    )


def _arena_screen(
    x_mm: float,
    y_mm: float,
    bounds: dict[str, list[float]],
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    left, top, right, bottom = box
    x = left + (x_mm - bounds["x"][0]) / (bounds["x"][1] - bounds["x"][0]) * (right - left)
    y = bottom - (y_mm - bounds["y"][0]) / (bounds["y"][1] - bounds["y"][0]) * (bottom - top)
    return x, y


def _paste_proxy(canvas: Any, proxy: Any, x: float, y: float, heading_rad: float) -> None:
    from PIL import Image

    height = 76
    width = max(1, round(proxy.width / proxy.height * height))
    sprite = proxy.resize((width, height), Image.Resampling.LANCZOS)
    angle = math.degrees(heading_rad) - 90.0
    sprite = sprite.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    canvas.alpha_composite(sprite, (round(x - sprite.width / 2), round(y - sprite.height / 2)))


def render_swarm_scientific(
    directory: Path,
    *,
    root: Path,
    body_proxy_path: Path,
    output_path: Path,
    fps: int = 30,
) -> Path:
    """Render a saved swarm trace in the restrained DEMO-01 instrument style."""
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ReadinessError("Scientific swarm rendering needs imageio and Pillow") from exc
    if fps < 24:
        raise ConfigurationError("Scientific swarm cinematic requires at least 24 fps")
    manifest_path = directory / "presentation-manifest.json"
    manifest = load_json(manifest_path)
    trace_path = directory / str(manifest["files"]["trace"]["name"])
    activity_path = directory / str(manifest["files"]["activity"]["name"])
    if _sha256(trace_path) != manifest["files"]["trace"]["sha256"]:
        raise ValidationError("Swarm trace checksum mismatch")
    if _sha256(activity_path) != manifest["files"]["activity"]["sha256"]:
        raise ValidationError("Swarm activity checksum mismatch")
    if not body_proxy_path.is_file():
        raise ReadinessError(f"NeuroMechFly pose proxy does not exist: {body_proxy_path}")
    proxy = Image.open(body_proxy_path).convert("RGBA")
    if int(np.asarray(proxy.getchannel("A"), dtype=np.uint8).max()) == 0:
        raise ValidationError("NeuroMechFly pose proxy has no visible alpha")

    rows = _load_rows(trace_path)
    scenario = load_json(Path(str(manifest["scenario"])))
    target = manifest["target"]
    agent_ids = [str(fly["id"]) for fly in rows[0]["flies"]]
    tracks = {
        agent_id: [next(fly for fly in row["flies"] if fly["id"] == agent_id) for row in rows]
        for agent_id in agent_ids
    }
    strips = _build_strips(rows, agent_ids, target)
    fonts = _fonts()
    positions = root / "derived/male-cns-v1.0/soma-positions.npz"
    atlas = BrainAtlas.load(
        positions,
        neuron_count=int(manifest["graph"]["neurons_per_agent"]),
        entry_body_ids=manifest["populations"]["entry_body_ids"],
        readout_body_ids=manifest["populations"]["readout_body_ids"],
    )
    projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(6.0),
        width=BRAIN_WIDTH,
        height=PANEL_HEIGHT,
        view="dorsal",
    )
    activity = np.load(activity_path)
    offsets = np.asarray(activity["offsets"], dtype=np.int64)
    indices = np.asarray(activity["dense_indices"], dtype=np.int64)
    counts = np.asarray(activity["counts"], dtype=np.float32)
    sample_t_us = np.asarray(activity["sample_t_us"], dtype=np.int64)
    row_by_dense = np.full(int(manifest["graph"]["neurons_per_agent"]), -1, dtype=np.int64)
    row_by_dense[atlas.dense_index] = np.arange(atlas.drawn, dtype=np.int64)
    glow = np.zeros(atlas.drawn, dtype=np.float32)
    brain_frame = render_brain(atlas, glow, projection=projection)
    last_sample = -1
    bounds = {
        "x": [
            -float(scenario["arena"]["half_width_mm"]),
            float(scenario["arena"]["half_width_mm"]),
        ],
        "y": [
            -float(scenario["arena"]["half_height_mm"]),
            float(scenario["arena"]["half_height_mm"]),
        ],
    }
    arena_box = (
        BRAIN_WIDTH + 18,
        HEADER_HEIGHT + 76,
        WIDTH - 18,
        HEADER_HEIGHT + PANEL_HEIGHT - 18,
    )
    opening_frames = 4 * fps
    simulation_frames = 28 * fps
    closing_frames = 5 * fps
    opening = _opening_card(manifest)
    closing = _closing_card(manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        output_path,
        fps=fps,
        codec="libx264",
        quality=9,
        macro_block_size=1,
        pixelformat="yuv420p",
    )
    try:
        for _ in range(opening_frames):
            writer.append_data(np.asarray(opening))
        for frame_index in range(simulation_frames):
            progress = frame_index / max(simulation_frames - 1, 1)
            cursor_float = progress * (len(rows) - 1)
            cursor = min(len(rows) - 1, int(cursor_float))
            fraction = cursor_float - cursor
            following_cursor = min(len(rows) - 1, cursor + 1)
            t_us = int(
                (1.0 - fraction) * rows[cursor]["t_us"] + fraction * rows[following_cursor]["t_us"]
            )
            sample_index = int(np.searchsorted(sample_t_us, t_us, side="right") - 1)
            while last_sample < sample_index:
                last_sample += 1
                glow *= np.float32(0.38)
                start, stop = int(offsets[last_sample]), int(offsets[last_sample + 1])
                targets = row_by_dense[indices[start:stop]]
                keep = targets >= 0
                if np.any(keep):
                    np.add.at(glow, targets[keep], counts[start:stop][keep])
                brain_frame = render_brain(atlas, glow, projection=projection)

            canvas = Image.new("RGBA", (WIDTH, HEIGHT), (*BACKGROUND, 255))
            draw = ImageDraw.Draw(canvas, "RGBA")
            draw.rectangle((0, 0, WIDTH, HEADER_HEIGHT), fill=(13, 16, 23, 255))
            draw.text(
                (26, 12),
                "MaleCNS full-graph cohort target approach",
                font=fonts["title"],
                fill=INK,
            )
            draw.text(
                (26, 43),
                "8 independent states  |  165,122 neurons/state  |  "
                f"25,563,197 edges shared  |  t = {t_us / 1_000_000:.2f} s",
                font=fonts["small"],
                fill=DIM,
            )
            draw.text(
                (1280, 14),
                "V0 STRUCTURAL - ENGINEERING VISUALISATION",
                font=fonts["small"],
                fill=WARN,
            )
            draw.text(
                (1280, 40),
                "NOT BIOLOGICAL SWARMING - NO SOCIAL SENSING",
                font=fonts["tiny"],
                fill=DIM,
            )

            canvas.alpha_composite(Image.fromarray(brain_frame).convert("RGBA"), (0, HEADER_HEIGHT))
            draw.rectangle(
                (8, HEADER_HEIGHT + 8, 335, HEADER_HEIGHT + 178),
                fill=(9, 11, 16, 230),
                outline=(45, 52, 66, 255),
            )
            brain_lines = [
                "brain: released soma positions",
                "activity: 8 states summed for display",
                f"{atlas.drawn:,} of {manifest['graph']['neurons_per_agent']:,} drawn",
                f"{atlas.missing:,} lack a released soma position",
                "brightness: pooled spike count",
                "visual input: lamina entry scaffold",
                "readout: bilateral descending population",
            ]
            for index, text in enumerate(brain_lines):
                draw.text(
                    (18, HEADER_HEIGHT + 18 + index * 21),
                    text,
                    font=fonts["tiny"] if index else fonts["small"],
                    fill=INK if index == 0 else DIM,
                )

            draw.rectangle(
                (BRAIN_WIDTH, HEADER_HEIGHT, WIDTH, HEADER_HEIGHT + PANEL_HEIGHT),
                fill=(10, 12, 18, 255),
                outline=(48, 55, 70, 255),
            )
            draw.text(
                (BRAIN_WIDTH + 18, HEADER_HEIGHT + 10),
                "shared arena: recorded x / y / heading",
                font=fonts["small"],
                fill=DIM,
            )
            draw.text(
                (BRAIN_WIDTH + 18, HEADER_HEIGHT + 36),
                "NeuroMechFly mesh = anatomical pose proxy; body motion = kinematic P/E",
                font=fonts["tiny"],
                fill=WARN,
            )
            draw.rectangle(arena_box, fill=(23, 24, 27, 255), outline=(52, 60, 76, 255))
            for grid_x in np.linspace(bounds["x"][0], bounds["x"][1], 9):
                gx, _ = _arena_screen(float(grid_x), 0.0, bounds, arena_box)
                draw.line((gx, arena_box[1], gx, arena_box[3]), fill=(90, 94, 104, 24), width=1)
            for grid_y in np.linspace(bounds["y"][0], bounds["y"][1], 7):
                _, gy = _arena_screen(0.0, float(grid_y), bounds, arena_box)
                draw.line((arena_box[0], gy, arena_box[2], gy), fill=(90, 94, 104, 24), width=1)
            tx, ty = _arena_screen(float(target["x_mm"]), float(target["y_mm"]), bounds, arena_box)
            cue_radius = (
                float(target["radius_mm"])
                / (bounds["x"][1] - bounds["x"][0])
                * (arena_box[2] - arena_box[0])
            )
            draw.ellipse(
                (tx - cue_radius, ty - cue_radius, tx + cue_radius, ty + cue_radius),
                fill=(58, 62, 76, 220),
                outline=(178, 188, 212, 255),
                width=2,
            )
            draw.text((tx + cue_radius + 8, ty - 8), "visual cue", font=fonts["tiny"], fill=DIM)

            current_distances: list[float] = []
            for agent_index, agent_id in enumerate(agent_ids):
                current = tracks[agent_id][cursor]
                following = tracks[agent_id][following_cursor]
                heading = float(current["heading_rad"])
                delta = (float(following["heading_rad"]) - heading + math.pi) % (
                    2 * math.pi
                ) - math.pi
                x_mm = (1.0 - fraction) * float(current["x_mm"]) + fraction * float(
                    following["x_mm"]
                )
                y_mm = (1.0 - fraction) * float(current["y_mm"]) + fraction * float(
                    following["y_mm"]
                )
                heading += fraction * delta
                trail_start = max(0, cursor - 130)
                trail = [
                    _arena_screen(float(row["x_mm"]), float(row["y_mm"]), bounds, arena_box)
                    for row in tracks[agent_id][trail_start : cursor + 1]
                ]
                if len(trail) > 1:
                    shade = 120 + agent_index * 8
                    draw.line(trail, fill=(shade, min(205, shade + 35), 240, 150), width=2)
                sx, sy = _arena_screen(x_mm, y_mm, bounds, arena_box)
                _paste_proxy(canvas, proxy, sx, sy, heading)
                draw.text(
                    (sx + 22, sy - 28), f"{agent_index + 1:02d}", font=fonts["tiny"], fill=INK
                )
                current_distances.append(
                    math.hypot(x_mm - float(target["x_mm"]), y_mm - float(target["y_mm"]))
                )
            draw.text(
                (BRAIN_WIDTH + 30, HEADER_HEIGHT + PANEL_HEIGHT - 45),
                f"median distance {np.median(current_distances):.2f} mm   |   "
                f"range {np.min(current_distances):.2f}-{np.max(current_distances):.2f} mm",
                font=fonts["small"],
                fill=INK,
            )

            draw.rectangle(
                (0, HEADER_HEIGHT + PANEL_HEIGHT - 34, BRAIN_WIDTH, HEADER_HEIGHT + PANEL_HEIGHT),
                fill=(9, 11, 16, 235),
            )
            if t_us < 1_500_000:
                caption = "the cue is body-relative; the registered decoder remains quiescent"
            elif cursor < len(rows) - 10:
                caption = (
                    "bilateral descending rates independently steer eight recorded body states"
                )
            else:
                caption = "all eight states reduced distance to the shared cue"
            draw.text(
                (360, HEADER_HEIGHT + PANEL_HEIGHT - 28), caption, font=fonts["small"], fill=INK
            )

            draw_strips(
                draw,
                strips,
                origin=(18, HEADER_HEIGHT + PANEL_HEIGHT + 12),
                width=WIDTH - 36,
                height=TRACE_HEIGHT - 18,
                cursor=cursor,
                fonts=fonts,
            )
            footer_y = HEIGHT - FOOTER_HEIGHT
            draw.rectangle((0, footer_y, WIDTH, HEIGHT), fill=(13, 16, 23, 255))
            draw.text(
                (26, footer_y + 10),
                "The decoder receives no target coordinates. Visual encoder, LIF, decoder "
                "and kinematic body are P/E.",
                font=fonts["small"],
                fill=WARN,
            )
            draw.text(
                (26, footer_y + 34),
                "One donor topology; independent state; no inter-fly sensing. Mesh is a "
                "display proxy. Rendering changes no recorded quantity.",
                font=fonts["tiny"],
                fill=DIM,
            )
            writer.append_data(np.asarray(canvas.convert("RGB")))
        for _ in range(closing_frames):
            writer.append_data(np.asarray(closing))
    finally:
        writer.close()

    render_manifest = {
        "schema_version": "1.0",
        "presentation_id": "swarm-cns-scientific-v2",
        "source_manifest": str(manifest_path.resolve()),
        "source_manifest_sha256": _sha256(manifest_path),
        "body_proxy": str(body_proxy_path.resolve()),
        "body_proxy_sha256": _sha256(body_proxy_path),
        "body_proxy_semantics": (
            "NeuroMechFly default-pose mesh used for display only; x/y/heading come from the "
            "recorded kinematic body and no MuJoCo gait is implied."
        ),
        "video": str(output_path.resolve()),
        "video_sha256": _sha256(output_path),
        "resolution": [WIDTH, HEIGHT],
        "fps": fps,
        "duration_s": (opening_frames + simulation_frames + closing_frames) / fps,
        "rendering_advanced_simulator_state": False,
        "evidence_grade": False,
        "scientific_validation_tier_awarded": None,
        "claim_boundary": manifest["claim_boundary"],
    }
    manifest_output = output_path.with_name("render-manifest-scientific-v2.json")
    manifest_output.write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_path.resolve()


__all__ = ["render_swarm_scientific"]
