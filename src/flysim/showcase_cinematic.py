# SPDX-License-Identifier: GPL-2.0-or-later
"""Record and render the Eon showcase as an offline cinematic dashboard.

The accepted engineering matrix remains immutable. This module reruns only its declared hero
condition while copying full-graph spike counts and MuJoCo qpos at coupling boundaries. It then
renders those recorded values offline. The rerun must reproduce the accepted hero transition
signature before a video is written.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, project_root
from flysim.demo01_body import Demo01BodyParameters
from flysim.demo01_embodied import Demo01Recorder
from flysim.demo01_render import (
    BACKGROUND,
    DIM,
    INK,
    WARN,
    BrainAtlas,
    BrainProjection,
    SpikeRecording,
    _fonts,
    render_brain,
)
from flysim.demo01_replay import BodyReplay, PoseRecording, ShotPlan, frame_camera, smooth_track
from flysim.engines.body import COMMAND_FORWARD, COMMAND_GROOM, COMMAND_PROBOSCIS, COMMAND_YAW
from flysim.engines.reference import (
    OUTPUT_DNA_L,
    OUTPUT_DNA_R,
    OUTPUT_FEED,
    OUTPUT_FORWARD,
    OUTPUT_GROOM,
    SENSOR_CONTAMINATION,
    SENSOR_SUCROSE,
)
from flysim.errors import ConfigurationError, ReadinessError, ValidationError
from flysim.factory import build_track_a_demo
from flysim.runs import require_clean_worktree

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
HEADER_HEIGHT = 72
PANEL_HEIGHT = 620
BRAIN_WIDTH = 1110
BODY_WIDTH = FRAME_WIDTH - BRAIN_WIDTH
CHART_TOP = HEADER_HEIGHT + PANEL_HEIGHT
CHART_HEIGHT = 318
FOOTER_TOP = CHART_TOP + CHART_HEIGHT

STATE_COLOURS: dict[str, tuple[int, int, int]] = {
    "SEEK": (92, 188, 255),
    "GROOM": (255, 170, 72),
    "SEEK_RESUME": (92, 220, 170),
    "FEED_INITIATION": (255, 100, 120),
    "COMPLETE": (150, 235, 120),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _value(frame: dict[str, Any], identifier: str) -> float:
    ids = frame.get("ids", ())
    values = frame.get("values", ())
    try:
        return float(values[ids.index(identifier)])
    except (ValueError, IndexError):
        return 0.0


def food_distance_mm(row: dict[str, Any], food_xy: tuple[float, float]) -> float:
    """Thorax-centre distance used by the current engineered sucrose trigger."""
    return math.hypot(
        float(row["body"]["x_mm"]) - food_xy[0],
        float(row["body"]["y_mm"]) - food_xy[1],
    )


def _event_targets(events: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[str]:
    return [str(event["to_state"]) for event in events]


def _replay_body_parameters(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "physics_dt_us": int(raw["physics_dt_us"]),
        "initial_x_mm": float(raw["initial_x_mm"]),
        "initial_y_mm": float(raw["initial_y_mm"]),
        "initial_heading_rad": float(raw["initial_heading_rad"]),
        "spawn_height_mm": float(raw["spawn_height_mm"]),
        "cue_x_mm": float(raw["food_x_mm"]),
        "cue_y_mm": float(raw["food_y_mm"]),
        "cue_radius_mm": float(raw["food_contact_radius_mm"]),
        "cue_height_mm": float(raw["food_contact_radius_mm"]),
        "max_forward_mm_s": float(raw["max_forward_mm_s"]),
        "max_yaw_rad_s": float(raw["max_yaw_rad_s"]),
        "station_keeping_gain_rad_per_mm": float(raw["station_keeping_gain_rad_per_mm"]),
        "station_keeping_integral_rad_per_mm_s": float(
            raw["station_keeping_integral_rad_per_mm_s"]
        ),
        "station_keeping_yaw_gain_rad_per_rad": float(raw["station_keeping_yaw_gain_rad_per_rad"]),
        "station_keeping_yaw_integral_rad_per_rad_s": float(
            raw["station_keeping_yaw_integral_rad_per_rad_s"]
        ),
        "station_keeping_max_offset_rad": float(raw["station_keeping_max_offset_rad"]),
        "station_keeping_max_yaw_offset_rad": float(raw["station_keeping_max_yaw_offset_rad"]),
        "station_keeping_settle_us": 0,
    }


def record_cinematic_source(
    *,
    root: Path,
    acceptance_path: Path | None = None,
    graph_path: Path | None = None,
    output_root: Path | None = None,
) -> Path:
    """Rerun and record the accepted hero condition without rendering in the loop."""
    os.environ.setdefault("MUJOCO_GL", "osmesa")
    repository = project_root()
    contract = load_json(repository / "configs" / "experiments" / "eon-showcase-v1.json")
    acceptance_file = acceptance_path or root / "runs" / "eon-showcase-v1" / "acceptance.json"
    acceptance = load_json(acceptance_file)
    if acceptance.get("accepted_as_engineering_showcase") is not True:
        raise ReadinessError("The cinematic source requires an accepted engineering matrix")
    hero_seed = int(contract["hero_seed"])
    accepted_hero = acceptance.get("exact", {}).get(str(hero_seed))
    if not isinstance(accepted_hero, dict):
        raise ReadinessError(f"The acceptance artifact has no hero seed {hero_seed}")
    expected_events = [str(value) for value in accepted_hero["event_targets"]]
    clean = require_clean_worktree("The Eon cinematic recording")

    graph = graph_path or root / "derived" / "male-cns-v1.0" / "graph"
    population_path = root / "derived" / "male-cns-v1.0" / "population-resolution.json"
    transmitter_path = (
        root / "raw" / "male-cns-v1.0" / "body-neurotransmitters-male-cns-v1.0.feather"
    )
    annotations_path = (
        root / "raw" / "male-cns-v1.0" / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    trajectory_path = (
        root
        / "derived"
        / "auxiliary"
        / "ozdil-2026-antennal-grooming"
        / "track-a-grooming-trajectory.npz"
    )
    for required in (graph, population_path, transmitter_path, annotations_path, trajectory_path):
        if not required.exists():
            raise ReadinessError(f"Cinematic recording dependency is missing: {required}")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = output_root or root / "runs" / "eon-showcase-cinematic-v1"
    directory = destination / f"{timestamp}_seed-{hero_seed}_{str(clean['commit'])[:8]}"
    food_position = tuple(float(value) for value in contract["food_position_mm"])
    demo = build_track_a_demo(
        seed=hero_seed,
        graph_path=graph,
        population_resolution_path=population_path,
        transmitter_path=transmitter_path,
        grooming_trajectory_path=trajectory_path,
        build_path=root / "cache" / "genn" / "track-a" / "exact",
        variant="exact",
        food_position_mm=(food_position[0], food_position[1]),
        render=False,
        annotations_path=annotations_path,
    )
    recorder = Demo01Recorder(directory, neuron_count=int(contract["required_graph"]["neurons"]))
    recording: dict[str, Any]
    try:
        spike_reader = getattr(demo.neural, "spike_counts_since_last_frame", None)
        pose_reader = getattr(demo.body, "qpos", None)
        if not callable(spike_reader) or not callable(pose_reader):
            raise ReadinessError("The production engines do not expose presentation recording")

        def observe(row: dict[str, Any]) -> None:
            recorder.add_interval(row, spike_reader())
            recorder.add_pose(int(row["t_us"]), pose_reader())

        result = demo.scheduler.run_until(int(contract["duration_us"]), interval_observer=observe)
    finally:
        recording = recorder.close()
        demo.neural.close()

    observed_events = _event_targets(result.events)
    if observed_events != expected_events or not result.completed:
        raise ValidationError(
            "The cinematic rerun did not reproduce the accepted hero: "
            f"expected {expected_events}, observed {observed_events}"
        )

    population_ids = demo.populations.body_ids
    body_parameters = asdict(demo.body.parameters)
    manifest = {
        "schema_version": "1.0",
        "presentation_id": "eon-showcase-cinematic-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "code_commit": clean["commit"],
        "git_dirty": False,
        "seed": hero_seed,
        "source_acceptance": {
            "path": str(acceptance_file.resolve()),
            "sha256": _sha256_file(acceptance_file),
            "accepted_hero_manifest_sha256": accepted_hero["run"]["manifest_sha256"],
            "transition_signature": expected_events,
        },
        "rerun": {
            "completed": result.completed,
            "final_t_us": result.final_t_us,
            "events": list(result.events),
            "transition_signature_matches_accepted_hero": True,
        },
        "graph": {
            "neurons": demo.graph.neuron_count,
            "edges": demo.graph.edge_count,
            "source_sha256": demo.graph.source_sha256,
        },
        "timing": result.timing,
        "body_parameters": body_parameters,
        "replay_body_parameters": _replay_body_parameters(body_parameters),
        "populations": {
            "entry_body_ids": list(
                dict.fromkeys(
                    body
                    for name in (
                        "ethyl-acetate-receptor-entry",
                        "grooming-jo-f",
                        "sucrose-receptor-entry",
                    )
                    for body in population_ids[name]
                )
            ),
            "readout_body_ids": list(demo.populations.output_body_ids),
            "sizes": {name: len(values) for name, values in population_ids.items()},
        },
        "recording": recording,
        "display_truth": {
            "food_object_radius_mm": 0.25,
            "sucrose_trigger_radius_mm": body_parameters["food_contact_radius_mm"],
            "sucrose_trigger_uses": "thorax-centre proximity, not physical contact",
            "rendering_is_offline": True,
        },
    }
    for name in ("trace.jsonl", "spikes.npz", "poses.npz"):
        manifest.setdefault("artifact_sha256", {})[name] = _sha256_file(directory / name)
    manifest_path = directory / "presentation-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return directory


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
    *, heading: str, sections: list[tuple[str, str]], footer: str, fonts: dict[str, Any]
) -> Any:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 18, FRAME_HEIGHT), fill=(255, 174, 64))
    y = 105
    draw.text((105, y), heading, font=fonts["title"], fill=INK)
    y += 72
    draw.line((105, y, FRAME_WIDTH - 105, y), fill=(48, 58, 76), width=2)
    y += 40
    for label, body in sections:
        draw.text((105, y), label, font=fonts["body"], fill=WARN)
        y += 32
        for line in _wrap(draw, body, fonts["body"], FRAME_WIDTH - 240):
            draw.text((125, y), line, font=fonts["body"], fill=INK)
            y += 29
        y += 25
    footer_y = FRAME_HEIGHT - 115
    for line in _wrap(draw, footer, fonts["small"], FRAME_WIDTH - 240):
        draw.text((105, footer_y), line, font=fonts["small"], fill=DIM)
        footer_y += 24
    return canvas


def _draw_line_chart(
    draw: Any,
    *,
    box: tuple[int, int, int, int],
    title: str,
    channels: list[tuple[str, np.ndarray, tuple[int, int, int]]],
    cursor: int,
    fonts: dict[str, Any],
    maximum: float | None = None,
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill=(12, 15, 22), outline=(32, 39, 52))
    draw.text((left + 10, top + 5), title, font=fonts["tiny"], fill=DIM)
    plot_left, plot_top = left + 10, top + 27
    plot_right, plot_bottom = right - 10, bottom - 10
    max_value = maximum or max(
        1e-9,
        *(float(np.nanmax(np.abs(values))) for _, values, _ in channels),
    )
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill=(42, 49, 62))
    count = max(2, channels[0][1].size)
    for channel_index, (label, values, colour) in enumerate(channels):
        points: list[tuple[int, int]] = []
        for index in range(min(cursor + 1, values.size)):
            x = round(plot_left + index / (count - 1) * (plot_right - plot_left))
            scaled = max(-1.0, min(1.0, float(values[index]) / max_value))
            y = round(plot_bottom - max(0.0, scaled) * (plot_bottom - plot_top))
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill=colour, width=2)
        label_x = left + 10 + channel_index * 210
        draw.line((label_x, top + 20, label_x + 14, top + 20), fill=colour, width=3)
        draw.text((label_x + 19, top + 12), label, font=fonts["tiny"], fill=INK)


def _draw_trajectory(
    draw: Any,
    *,
    rows: list[dict[str, Any]],
    cursor: int,
    food_xy: tuple[float, float],
    trigger_radius: float,
    dust_xy: tuple[float, float],
    dust_radius: float,
    box: tuple[int, int, int, int],
    fonts: dict[str, Any],
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill=(10, 13, 19), outline=(58, 68, 86))
    draw.text((left + 8, top + 5), "recorded trajectory (top-down)", font=fonts["tiny"], fill=DIM)
    xs = np.asarray([float(row["body"]["x_mm"]) for row in rows] + [food_xy[0], dust_xy[0]])
    ys = np.asarray([float(row["body"]["y_mm"]) for row in rows] + [food_xy[1], dust_xy[1]])
    margin = max(trigger_radius, dust_radius) + 0.5
    x0, x1 = float(xs.min() - margin), float(xs.max() + margin)
    y0, y1 = float(ys.min() - margin), float(ys.max() + margin)
    scale = min((right - left - 24) / max(x1 - x0, 1e-6), (bottom - top - 42) / max(y1 - y0, 1e-6))

    def screen(x: float, y: float) -> tuple[int, int]:
        return (
            round(left + 12 + (x - x0) * scale),
            round(bottom - 12 - (y - y0) * scale),
        )

    dust = screen(*dust_xy)
    dust_px = round(dust_radius * scale)
    draw.ellipse(
        (dust[0] - dust_px, dust[1] - dust_px, dust[0] + dust_px, dust[1] + dust_px),
        fill=(92, 72, 48),
        outline=(170, 133, 82),
    )
    food = screen(*food_xy)
    trigger_px = round(trigger_radius * scale)
    draw.ellipse(
        (food[0] - trigger_px, food[1] - trigger_px, food[0] + trigger_px, food[1] + trigger_px),
        outline=(255, 190, 75),
        width=2,
    )
    object_px = max(4, round(0.25 * scale))
    draw.ellipse(
        (food[0] - object_px, food[1] - object_px, food[0] + object_px, food[1] + object_px),
        fill=(220, 60, 55),
    )
    path = [
        screen(float(row["body"]["x_mm"]), float(row["body"]["y_mm"])) for row in rows[: cursor + 1]
    ]
    if len(path) > 1:
        draw.line(path, fill=(100, 195, 255), width=2)
    if path:
        x, y = path[-1]
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(245, 245, 255))


def render_cinematic_source(
    directory: Path,
    *,
    positions_path: Path,
    output_path: Path | None = None,
    fps: int = 30,
) -> Path:
    """Render a presentation recording. No simulator state is advanced here."""
    if fps <= 0:
        raise ConfigurationError("Cinematic FPS must be positive")
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ReadinessError("Cinematic rendering needs imageio and Pillow") from exc

    manifest = load_json(directory / "presentation-manifest.json")
    rows = [
        json.loads(line)
        for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    spikes = SpikeRecording(directory / "spikes.npz")
    poses = PoseRecording(directory / "poses.npz")
    if len(rows) != spikes.intervals or len(rows) != len(poses):
        raise ValidationError("Cinematic trace, spike, and pose recordings disagree")
    populations = manifest["populations"]
    atlas = BrainAtlas.load(
        positions_path,
        neuron_count=spikes.neuron_count,
        entry_body_ids=populations["entry_body_ids"],
        readout_body_ids=populations["readout_body_ids"],
    )
    projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(6.0),
        width=BRAIN_WIDTH,
        height=PANEL_HEIGHT,
        view="dorsal",
    )
    fonts = _fonts()
    body_raw = manifest["body_parameters"]
    replay_parameters = Demo01BodyParameters.from_mapping(manifest["replay_body_parameters"])
    replay = BodyReplay(
        replay_parameters,
        seed=int(manifest["seed"]),
        resolution=(PANEL_HEIGHT, BODY_WIDTH),
    )
    interval_s = float(manifest["timing"]["coupling_us"]) / 1_000_000.0
    duration_s = len(rows) * interval_s
    frame_count = max(1, round(duration_s * fps))
    track_x, track_y, track_z, track_heading = smooth_track(
        np.asarray([row["body"]["x_mm"] for row in rows]),
        np.asarray([row["body"]["y_mm"] for row in rows]),
        np.asarray([row["body"]["z_mm"] for row in rows]),
        np.asarray([row["body"]["heading_rad"] for row in rows]),
        window=max(3, round(0.35 / interval_s)),
    )
    plan = ShotPlan.from_recording(duration_s=duration_s, onset_s=0.0, minimum_establish_s=1.5)
    food_xy = (float(body_raw["food_x_mm"]), float(body_raw["food_y_mm"]))
    trigger_radius = float(body_raw["food_contact_radius_mm"])
    dust_xy = (float(body_raw["dust_x_mm"]), float(body_raw["dust_y_mm"]))
    dust_radius = float(body_raw["dust_radius_mm"])

    contamination = np.asarray([_value(row["sensors"], SENSOR_CONTAMINATION) for row in rows])
    sucrose = np.asarray([_value(row["sensors"], SENSOR_SUCROSE) for row in rows])
    groom = np.asarray([_value(row["neural"], OUTPUT_GROOM) for row in rows])
    feed = np.asarray([_value(row["neural"], OUTPUT_FEED) for row in rows])
    forward = np.asarray([_value(row["actuators"], COMMAND_FORWARD) for row in rows])
    yaw = np.asarray([_value(row["actuators"], COMMAND_YAW) for row in rows])
    grooming_command = np.asarray([_value(row["actuators"], COMMAND_GROOM) for row in rows])
    feeding_command = np.asarray([_value(row["actuators"], COMMAND_PROBOSCIS) for row in rows])

    output = output_path or directory / "cinematic-demo.mp4"
    writer = imageio.get_writer(output, fps=fps, codec="libx264", quality=9, macro_block_size=1)
    glow = np.zeros(atlas.drawn, dtype=np.float32)
    row_by_dense = np.full(spikes.neuron_count, -1, dtype=np.int64)
    row_by_dense[atlas.dense_index] = np.arange(atlas.drawn, dtype=np.int64)
    opening = _card(
        heading="A MaleCNS fly seeks food, grooms, resumes, and initiates feeding",
        sections=[
            (
                "THE EXECUTED SYSTEM",
                "165,122 neurons and 25,563,197 aggregate edges are stepped in "
                "closed loop with a FlyGym body.",
            ),
            (
                "THE STORY",
                "Odour-guided seeking, antennal contamination, a grooming bout, resumed "
                "seeking, then MN9-associated rostrum extension inside the engineered "
                "sucrose trigger zone.",
            ),
            (
                "THE HONEST BOUNDARY",
                "Central sensory bridges and body controllers remain engineering scaffolds. "
                "The trigger is thorax-centre proximity, not physical mouth contact. No "
                "topology or physiology tier is claimed.",
            ),
        ],
        footer=(
            "V0 Structural | full graph | offline rendering from recorded spikes and MuJoCo poses"
        ),
        fonts=fonts,
    )
    closing = _card(
        heading="Engineering showcase complete",
        sections=[
            (
                "RECORDED RESULT",
                "The cinematic rerun reproduces the accepted hero transition signature: "
                "GROOM, SEEK_RESUME, FEED_INITIATION, COMPLETE.",
            ),
            (
                "CAUSAL MATRIX",
                "Two of three exact seeds completed. All four registered interface "
                "ablations blocked their corresponding transition.",
            ),
            (
                "WHAT REMAINS",
                "Physical mouth or tarsal food contact, a biological VNC-to-muscle "
                "pathway, ingestion, and validated neural dynamics remain future work.",
            ),
        ],
        footer=f"commit {manifest['code_commit']} | rendering changes pixels only",
        fonts=fonts,
    )
    try:
        for _ in range(3 * fps):
            writer.append_data(np.asarray(opening))
        previous_cursor = -1
        for frame_index in range(frame_count):
            t_s = frame_index / fps
            cursor = min(len(rows) - 1, int(t_s / interval_s))
            glow *= np.float32(0.78)
            for interval in range(previous_cursor + 1, cursor + 1):
                indices, counts = spikes.interval(interval)
                targets = row_by_dense[indices]
                keep = targets >= 0
                if np.any(keep):
                    np.add.at(glow, targets[keep], counts[keep])
            previous_cursor = cursor
            brain = render_brain(atlas, glow, projection=projection)
            shot = plan.shot_at(t_s)
            framing = frame_camera(
                shot,
                fly_xyz_mm=(float(track_x[cursor]), float(track_y[cursor]), float(track_z[cursor])),
                heading_rad=float(track_heading[cursor]),
                cue_xy_mm=food_xy,
                cue_height_mm=trigger_radius,
                cue_radius_mm=trigger_radius,
                cue_present=True,
                t_s=t_s,
            )
            body_frame = replay.render(poses.at(cursor), framing, cue_visible=True)
            canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
            canvas.paste(Image.fromarray(brain), (0, HEADER_HEIGHT))
            canvas.paste(Image.fromarray(body_frame), (BRAIN_WIDTH, HEADER_HEIGHT))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, FRAME_WIDTH, HEADER_HEIGHT), fill=(12, 15, 22))
            state = str(rows[cursor]["state"])
            state_colour = STATE_COLOURS.get(state, INK)
            distance = food_distance_mm(rows[cursor], food_xy)
            draw.text(
                (24, 9), "MaleCNS Virtual Fly | Eon-class cinematic", font=fonts["title"], fill=INK
            )
            draw.text(
                (24, 44),
                f"t={t_s:5.2f}s  state={state}  thorax-to-food={distance:4.2f} mm",
                font=fonts["small"],
                fill=state_colour,
            )
            draw.text(
                (1320, 15),
                "FULL GRAPH | V0 STRUCTURAL | ENGINEERING SHOWCASE",
                font=fonts["small"],
                fill=WARN,
            )
            draw.rectangle(
                (BRAIN_WIDTH + 8, HEADER_HEIGHT + 8, FRAME_WIDTH - 8, HEADER_HEIGHT + 91),
                fill=(10, 12, 18),
            )
            draw.text(
                (BRAIN_WIDTH + 18, HEADER_HEIGHT + 14),
                "FlyGym body replay from recorded MuJoCo qpos",
                font=fonts["small"],
                fill=INK,
            )
            draw.text(
                (BRAIN_WIDTH + 18, HEADER_HEIGHT + 38),
                "translucent sphere = engineered 1.0 mm sucrose trigger zone",
                font=fonts["small"],
                fill=WARN,
            )
            draw.text(
                (BRAIN_WIDTH + 18, HEADER_HEIGHT + 62),
                "proximity bridge, not physical mouth contact",
                font=fonts["small"],
                fill=DIM,
            )
            draw.rectangle(
                (10, HEADER_HEIGHT + 10, 342, HEADER_HEIGHT + 182),
                fill=(10, 12, 18),
                outline=(35, 43, 56),
            )
            draw.text(
                (20, HEADER_HEIGHT + 17),
                "released MaleCNS soma positions",
                font=fonts["small"],
                fill=INK,
            )
            draw.text(
                (20, HEADER_HEIGHT + 42),
                f"{atlas.drawn:,} drawn | {atlas.missing:,} lack a released soma",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (20, HEADER_HEIGHT + 70),
                f"groom DN  {groom[cursor]:7.1f} Hz",
                font=fonts["small"],
                fill=(255, 115, 80),
            )
            draw.text(
                (20, HEADER_HEIGHT + 94),
                f"MN9       {feed[cursor]:7.1f} Hz",
                font=fonts["small"],
                fill=(255, 105, 145),
            )
            draw.text(
                (20, HEADER_HEIGHT + 118),
                f"DNg97     {_value(rows[cursor]['neural'], OUTPUT_FORWARD):7.1f} Hz",
                font=fonts["small"],
                fill=(100, 205, 255),
            )
            draw.text(
                (20, HEADER_HEIGHT + 142),
                "DNa L/R   "
                f"{_value(rows[cursor]['neural'], OUTPUT_DNA_L):5.1f} / "
                f"{_value(rows[cursor]['neural'], OUTPUT_DNA_R):5.1f} Hz",
                font=fonts["small"],
                fill=INK,
            )
            _draw_trajectory(
                draw,
                rows=rows,
                cursor=cursor,
                food_xy=food_xy,
                trigger_radius=trigger_radius,
                dust_xy=dust_xy,
                dust_radius=dust_radius,
                box=(
                    FRAME_WIDTH - 310,
                    HEADER_HEIGHT + PANEL_HEIGHT - 275,
                    FRAME_WIDTH - 15,
                    HEADER_HEIGHT + PANEL_HEIGHT - 15,
                ),
                fonts=fonts,
            )
            strip_height = 92
            _draw_line_chart(
                draw,
                box=(18, CHART_TOP + 8, FRAME_WIDTH - 18, CHART_TOP + 8 + strip_height),
                title="WORLD / SENSOR",
                channels=[
                    ("antenna contamination", contamination, (255, 178, 70)),
                    ("sucrose proximity", sucrose, (255, 95, 125)),
                ],
                cursor=cursor,
                fonts=fonts,
                maximum=1.0,
            )
            _draw_line_chart(
                draw,
                box=(18, CHART_TOP + 106, FRAME_WIDTH - 18, CHART_TOP + 106 + strip_height),
                title="NAMED NEURAL READOUTS",
                channels=[("grooming DN", groom, (255, 128, 78)), ("MN9", feed, (255, 92, 145))],
                cursor=cursor,
                fonts=fonts,
            )
            _draw_line_chart(
                draw,
                box=(18, CHART_TOP + 204, FRAME_WIDTH - 18, CHART_TOP + 204 + strip_height),
                title="CONTROLLER-MEDIATED BODY COMMANDS",
                channels=[
                    ("forward", forward, (105, 195, 255)),
                    ("|yaw|", np.abs(yaw), (185, 145, 255)),
                    ("groom", grooming_command, (255, 178, 70)),
                    ("proboscis", feeding_command, (255, 95, 125)),
                ],
                cursor=cursor,
                fonts=fonts,
                maximum=1.0,
            )
            draw.rectangle((0, FOOTER_TOP, FRAME_WIDTH, FRAME_HEIGHT), fill=(12, 15, 22))
            draw.text(
                (24, FOOTER_TOP + 12),
                "central sensory bridges -> full MaleCNS runtime -> named readouts -> "
                "engineered FlyGym controllers",
                font=fonts["small"],
                fill=WARN,
            )
            draw.text(
                (24, FOOTER_TOP + 38),
                "female body prior | no VNC-to-muscle pathway | feeding initiation only | "
                "offline camera smoothing affects pixels only",
                font=fonts["tiny"],
                fill=DIM,
            )
            writer.append_data(np.asarray(canvas))
        for _ in range(4 * fps):
            writer.append_data(np.asarray(closing))
    finally:
        writer.close()
        replay.close()

    render_manifest = {
        "schema_version": "1.0",
        "presentation_id": manifest["presentation_id"],
        "source_manifest_sha256": _sha256_file(directory / "presentation-manifest.json"),
        "video": output.name,
        "video_sha256": _sha256_file(output),
        "fps": fps,
        "resolution": [FRAME_WIDTH, FRAME_HEIGHT],
        "simulation_rendering": "offline from recorded spikes and qpos",
        "sucrose_zone_disclosure": manifest["display_truth"],
        "scientific_validation_tier_awarded": None,
    }
    (directory / "cinematic-render-manifest.json").write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output.resolve()


def build_cinematic_showcase(
    *,
    root: Path,
    acceptance_path: Path | None = None,
    output_root: Path | None = None,
    source_directory: Path | None = None,
    fps: int = 30,
) -> dict[str, Any]:
    """Record a matching hero rerun or re-render one, then return its checksums."""
    if source_directory is None:
        directory = record_cinematic_source(
            root=root,
            acceptance_path=acceptance_path,
            output_root=output_root,
        )
    else:
        directory = source_directory.resolve()
        if not (directory / "presentation-manifest.json").is_file():
            raise ReadinessError(f"The presentation recording is incomplete: {directory}")
    positions = root / "derived" / "male-cns-v1.0" / "soma-positions.npz"
    if not positions.is_file():
        raise ReadinessError(f"The released soma-position cache is missing: {positions}")
    video = render_cinematic_source(directory, positions_path=positions, fps=fps)
    return {
        "presentation_directory": str(directory.resolve()),
        "presentation_manifest": str((directory / "presentation-manifest.json").resolve()),
        "video": str(video),
        "video_sha256": _sha256_file(video),
        "render_manifest": str((directory / "cinematic-render-manifest.json").resolve()),
        "scientific_validation_tier_awarded": None,
    }


__all__ = [
    "build_cinematic_showcase",
    "food_distance_mm",
    "record_cinematic_source",
    "render_cinematic_source",
]
