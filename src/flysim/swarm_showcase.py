# SPDX-License-Identifier: GPL-2.0-or-later
"""Record and render an honest full-CNS multi-agent target-approach cinematic."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

from flysim.config import load_json, project_root, sha256_json
from flysim.demo01_render import BrainAtlas, BrainProjection, render_brain
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError, ReadinessError, ValidationError
from flysim.multifly_live import build_full_cns_runtime
from flysim.runs import git_metadata

WIDTH = 1920
HEIGHT = 1080
ARENA_BOX = (54, 142, 1266, 1023)
SIDEBAR_BOX = (1296, 142, 1888, 1023)
BACKGROUND = (6, 13, 18)
PANEL = (10, 24, 29)
INK = (231, 249, 244)
DIM = (137, 166, 163)
CYAN = (83, 247, 211)
AMBER = (255, 196, 92)
CORAL = (255, 103, 120)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _distance(fly: dict[str, Any], target: dict[str, Any]) -> float:
    return math.hypot(
        float(fly["x_mm"]) - float(target["x_mm"]),
        float(fly["y_mm"]) - float(target["y_mm"]),
    )


def _reduced_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    commands = snapshot["pending_commands"]
    if any(bool(item.get("target_coordinates_available")) for item in commands.values()):
        raise ValidationError("A swarm decoder received target coordinates")
    return {
        "t_us": int(snapshot["arena"]["t_us"]),
        "flies": snapshot["arena"]["flies"],
        "stimuli": snapshot["arena"]["stimuli"],
        "collision_events": int(snapshot["arena"]["collision_events"]),
        "commands": commands,
        "causal_timing": snapshot["causal_timing"],
    }


def record_swarm_cns(
    *,
    root: Path,
    scenario_path: Path | None = None,
    output_root: Path | None = None,
    seed: int = 7,
) -> Path:
    """Execute the eight-state cohort once and save body plus sparse activity traces."""
    scenario_file = scenario_path or project_root() / "configs/scenarios/swarm-cns-cinematic.json"
    scenario = load_json(scenario_file)
    duration_us = int(scenario["duration_us"])
    coupling_us = int(scenario["coupling_us"])
    sample_every = int(scenario["activity_sample_every_intervals"])
    if duration_us <= 0 or coupling_us <= 0 or sample_every <= 0:
        raise ConfigurationError("Swarm duration, coupling and activity sampling must be positive")
    flies = list(scenario["full_cns_flies"])
    if len(flies) < 4 or any(str(item["mode"]) != "full-cns" for item in flies):
        raise ConfigurationError("The swarm cinematic needs at least four full-CNS agents")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        output_root or root / "runs" / "swarm-cns-cinematic-v1"
    ) / f"{timestamp}_seed-{seed}"
    destination.mkdir(parents=True, exist_ok=False)
    trace_path = destination / "trace.jsonl"
    activity_path = destination / "aggregate-activity.npz"
    started = time.perf_counter()
    runtime = build_full_cns_runtime(
        data_root=root,
        scenario_path=scenario_file,
        seed=seed,
    )
    try:
        if len(runtime.coordinator.neural_cohorts) != 1:
            raise ValidationError("Swarm recording must have exactly one shared neural cohort")
        cohort = runtime.coordinator.neural_cohorts[0]
        engine = cohort.engine
        if not isinstance(engine, TrackAGeNNEngine):
            raise ValidationError("Swarm recording requires the direct PyGeNN engine")
        graph = engine._graph
        if graph is None:
            raise ValidationError("Swarm neural engine has no initialized graph")
        if engine.batch_size != len(flies):
            raise ValidationError("Swarm batch size does not match the declared agents")
        first_pipeline = cast(Any, next(iter(cohort.pipelines.values())))
        populations = first_pipeline.encoder.populations
        initial = runtime.snapshot()
        initial_row = _reduced_snapshot(initial)
        rows = [initial_row]
        offsets = [0]
        active_indices: list[np.ndarray] = []
        active_counts: list[np.ndarray] = []
        activity_t_us: list[int] = []
        per_agent_totals: list[np.ndarray] = []
        steps = -(-duration_us // coupling_us)
        for step in range(steps):
            snapshot = runtime.step()
            rows.append(_reduced_snapshot(snapshot))
            if (step + 1) % sample_every == 0 or step + 1 == steps:
                counts_by_agent = engine.spike_counts_since_last_frame_batch()
                aggregate = counts_by_agent.sum(axis=0, dtype=np.int64)
                active = np.flatnonzero(aggregate).astype(np.int32)
                counts = aggregate[active].astype(np.int32)
                active_indices.append(active)
                active_counts.append(counts)
                offsets.append(offsets[-1] + int(active.size))
                activity_t_us.append(int(snapshot["arena"]["t_us"]))
                per_agent_totals.append(
                    counts_by_agent.sum(axis=1, dtype=np.int64).astype(np.int64)
                )

        with trace_path.open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        np.savez_compressed(
            activity_path,
            offsets=np.asarray(offsets, dtype=np.int64),
            dense_indices=(
                np.concatenate(active_indices) if active_indices else np.empty(0, dtype=np.int32)
            ),
            counts=(
                np.concatenate(active_counts) if active_counts else np.empty(0, dtype=np.int32)
            ),
            sample_t_us=np.asarray(activity_t_us, dtype=np.int64),
            per_agent_total_spikes=np.stack(per_agent_totals),
            batch_labels=np.asarray(engine.batch_labels),
            neuron_count=np.asarray(graph.neuron_count),
        )
        final_row = rows[-1]
        target = final_row["stimuli"][0]
        initial_by_id = {item["id"]: item for item in initial_row["flies"]}
        results = []
        for final_fly in final_row["flies"]:
            initial_fly = initial_by_id[final_fly["id"]]
            initial_distance = _distance(initial_fly, target)
            final_distance = _distance(final_fly, target)
            results.append(
                {
                    "agent_id": final_fly["id"],
                    "initial_distance_mm": initial_distance,
                    "final_distance_mm": final_distance,
                    "distance_reduction_mm": initial_distance - final_distance,
                    "path_length_mm": float(final_fly["path_length_mm"]),
                    "approached_target": final_distance < initial_distance,
                }
            )
        code = git_metadata()
        manifest = {
            "schema_version": "1.0",
            "presentation_id": "swarm-cns-cinematic-v1",
            "recorded_at_utc": timestamp,
            "code": code,
            "evidence_grade": False,
            "why_not_evidence": (
                "Presentation recording from the current working tree; no preregistered "
                "biological swarm hypothesis or validation contract exists."
            ),
            "seed": seed,
            "scenario": str(scenario_file.resolve()),
            "scenario_sha256": sha256_json(scenario),
            "runtime": initial["runtime"],
            "timing": {
                "coupling_us": coupling_us,
                "duration_us_requested": duration_us,
                "duration_us_recorded": int(final_row["t_us"]),
                "wall_seconds": time.perf_counter() - started,
                "activity_sample_every_intervals": sample_every,
            },
            "graph": {
                "neurons_per_agent": int(graph.neuron_count),
                "edges_shared": int(graph.edge_count),
                "connectivity_allocations": 1,
                "agents": engine.batch_size,
                "batch_labels": list(engine.batch_labels),
                "model_identity": engine.checkpoint()["model_identity"],
            },
            "populations": {
                "entry_body_ids": list(populations.entry_body_ids),
                "readout_body_ids": list(populations.readout_body_ids),
            },
            "target": target,
            "results": results,
            "agents_approaching_target": sum(bool(item["approached_target"]) for item in results),
            "collision_events": int(final_row["collision_events"]),
            "files": {
                "trace": {"name": trace_path.name, "sha256": _sha256(trace_path)},
                "activity": {
                    "name": activity_path.name,
                    "sha256": _sha256(activity_path),
                },
            },
            "claim_boundary": scenario["claim_boundary"],
            "scientific_validation_tier_awarded": None,
        }
        manifest_path = destination / "presentation-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return destination.resolve()
    finally:
        runtime.close()


def _font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

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


def _background() -> Any:
    from PIL import Image

    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    radial = np.exp(-(((x - WIDTH * 0.36) / 920.0) ** 2 + ((y - HEIGHT * 0.44) / 720.0) ** 2))
    base = np.empty((HEIGHT, WIDTH, 3), dtype=np.float32)
    base[..., 0] = 5 + 4 * radial
    base[..., 1] = 12 + 14 * radial
    base[..., 2] = 18 + 13 * radial
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="RGB")


def _screen(x_mm: float, y_mm: float, bounds: dict[str, list[float]]) -> tuple[float, float]:
    left, top, right, bottom = ARENA_BOX
    x = left + (x_mm - bounds["x"][0]) / (bounds["x"][1] - bounds["x"][0]) * (right - left)
    y = bottom - (y_mm - bounds["y"][0]) / (bounds["y"][1] - bounds["y"][0]) * (bottom - top)
    return x, y


def _draw_fly(draw: Any, fly: dict[str, Any], bounds: dict[str, list[float]]) -> None:
    x, y = _screen(float(fly["x_mm"]), float(fly["y_mm"]), bounds)
    heading = float(fly["heading_rad"])
    axis = (math.cos(heading), -math.sin(heading))
    perp = (-axis[1], axis[0])
    length = 44.0
    colour = str(fly["color"])

    def point(a: float, b: float) -> tuple[float, float]:
        return x + axis[0] * a + perp[0] * b, y + axis[1] * a + perp[1] * b

    for side in (-1.0, 1.0):
        for along, reach in ((4.0, 25.0), (-5.0, 29.0), (-14.0, 24.0)):
            hip = point(along, side * 7.0)
            knee = point(along - 3.0, side * reach)
            foot = point(along + 8.0, side * (reach + 9.0))
            draw.line((hip, knee, foot), fill=(119, 155, 148), width=2)
    for side in (-1.0, 1.0):
        wing = [
            point(-6.0, side * 5.0),
            point(-31.0, side * 25.0),
            point(4.0, side * 18.0),
        ]
        draw.polygon(wing, fill=(125, 215, 210, 65), outline=(116, 203, 197, 150))
    abdomen = [point(-length * 0.57, 0), point(-5, -9), point(7, 0), point(-5, 9)]
    draw.polygon(abdomen, fill=(25, 40, 42), outline=colour)
    thorax = [point(-6, -10), point(13, -8), point(18, 0), point(13, 8), point(-6, 10)]
    draw.polygon(thorax, fill=(18, 30, 32), outline=colour)
    hx, hy = point(20, 0)
    draw.ellipse((hx - 8, hy - 8, hx + 8, hy + 8), fill=colour, outline=(237, 255, 250))
    for side in (-1.0, 1.0):
        start = point(24, side * 4)
        end = point(36, side * 10)
        draw.line((start, end), fill=colour, width=2)


def _opening_card(manifest: dict[str, Any], scenario: dict[str, Any]) -> Any:
    from PIL import ImageDraw

    canvas = _background().copy()
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((92, 92), "MALECNS / COHORT CINEMATIC", font=_font(22, bold=True), fill=CYAN)
    draw.text((92, 156), scenario["cinematic"]["title"], font=_font(58, bold=True), fill=INK)
    draw.text((94, 232), scenario["cinematic"]["subtitle"], font=_font(30), fill=DIM)
    centre = (WIDTH * 0.72, HEIGHT * 0.48)
    draw.ellipse(
        (centre[0] - 68, centre[1] - 68, centre[0] + 68, centre[1] + 68),
        fill=(83, 247, 211, 30),
        outline=CYAN,
        width=3,
    )
    for index, fly in enumerate(scenario["full_cns_flies"]):
        angle = index * 2 * math.pi / len(scenario["full_cns_flies"])
        x = centre[0] + math.cos(angle) * 250
        y = centre[1] + math.sin(angle) * 250
        draw.line((x, y, centre[0], centre[1]), fill=(83, 247, 211, 55), width=2)
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=str(fly["color"]))
    facts = [
        f"{manifest['graph']['agents']} independent neural states",
        f"{manifest['graph']['neurons_per_agent']:,} neurons per state",
        f"{manifest['graph']['edges_shared']:,} shared aggregate edges",
        "body-relative visual input -> full graph -> descending rates -> E decoder",
    ]
    for index, text in enumerate(facts):
        y = 380 + index * 62
        draw.rounded_rectangle((92, y, 845, y + 44), radius=12, fill=(14, 35, 40, 220))
        draw.text((112, y + 9), text, font=_font(20), fill=INK)
    draw.text(
        (92, 948),
        "ENGINEERING VISUALISATION / V0 STRUCTURAL / NOT BIOLOGICAL SWARMING",
        font=_font(20, bold=True),
        fill=AMBER,
    )
    return canvas


def _closing_card(manifest: dict[str, Any]) -> Any:
    from PIL import ImageDraw

    canvas = _background().copy()
    draw = ImageDraw.Draw(canvas, "RGBA")
    results = manifest["results"]
    reductions = np.asarray([item["distance_reduction_mm"] for item in results])
    final_distances = np.asarray([item["final_distance_mm"] for item in results])
    draw.text((92, 102), "RECORDED COHORT RESULT", font=_font(22, bold=True), fill=CYAN)
    draw.text(
        (92, 168),
        f"{manifest['agents_approaching_target']} / {len(results)} moved closer",
        font=_font(64, bold=True),
        fill=INK,
    )
    result_text = (
        f"Median distance reduction {float(np.median(reductions)):.2f} mm  /  "
        f"final range {float(np.min(final_distances)):.2f}-"
        f"{float(np.max(final_distances)):.2f} mm"
    )
    draw.text((96, 258), result_text, font=_font(28), fill=DIM)
    sections = [
        (
            "WHAT RAN",
            "Each agent received its own retinotopic input and independent MaleCNS state. "
            "No decoder received target coordinates.",
        ),
        (
            "WHAT IS SHARED",
            "One donor topology and one sparse connectivity allocation. These are model "
            "replicates, not eight reconstructed individual flies.",
        ),
        (
            "WHAT IS NOT CLAIMED",
            "No social coordination, collective intelligence, validated physiology, or "
            "scientific tier beyond V0 Structural.",
        ),
    ]
    for index, (heading, body) in enumerate(sections):
        top = 380 + index * 170
        draw.rounded_rectangle((92, top, 1828, top + 132), radius=18, fill=(13, 31, 37, 225))
        draw.text((122, top + 20), heading, font=_font(19, bold=True), fill=AMBER)
        draw.text((122, top + 58), body, font=_font(23), fill=INK)
    return canvas


def render_swarm_cns(
    directory: Path,
    *,
    root: Path,
    output_path: Path | None = None,
    fps: int | None = None,
) -> Path:
    """Render only recorded values; never advance simulator state."""
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ReadinessError("Swarm rendering needs imageio and Pillow") from exc
    manifest_path = directory / "presentation-manifest.json"
    manifest = load_json(manifest_path)
    trace_path = directory / str(manifest["files"]["trace"]["name"])
    activity_path = directory / str(manifest["files"]["activity"]["name"])
    if _sha256(trace_path) != manifest["files"]["trace"]["sha256"]:
        raise ValidationError("Swarm trace checksum mismatch")
    if _sha256(activity_path) != manifest["files"]["activity"]["sha256"]:
        raise ValidationError("Swarm activity checksum mismatch")
    rows: list[dict[str, Any]] = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line
    ]
    if len(rows) < 2:
        raise ValidationError("Swarm trace is too short to render")
    scenario = load_json(Path(str(manifest["scenario"])))
    cinematic = scenario["cinematic"]
    render_fps = int(fps or cinematic["fps"])
    if render_fps < 24:
        raise ConfigurationError("Swarm cinematic requires at least 24 fps")
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
        width=536,
        height=312,
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
    cached_brain = render_brain(atlas, glow, projection=projection)
    last_sample = -1
    base = _background()
    opening = _opening_card(manifest, scenario)
    closing = _closing_card(manifest)
    opening_frames = round(float(cinematic["opening_seconds"]) * render_fps)
    simulation_frames = round(float(cinematic["simulation_seconds"]) * render_fps)
    closing_frames = round(float(cinematic["closing_seconds"]) * render_fps)
    target = manifest["target"]
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
    fly_ids = [str(item["id"]) for item in rows[0]["flies"]]
    colours = {str(item["id"]): str(item["color"]) for item in rows[0]["flies"]}
    tracks = {
        fly_id: [next(item for item in row["flies"] if item["id"] == fly_id) for row in rows]
        for fly_id in fly_ids
    }
    output = output_path or project_root() / "artifacts/showcase/swarm-cns-v1/swarm-cns-hero.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        output,
        fps=render_fps,
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
            next_cursor = min(len(rows) - 1, cursor + 1)
            t_us = int(
                (1.0 - fraction) * rows[cursor]["t_us"] + fraction * rows[next_cursor]["t_us"]
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
                cached_brain = render_brain(atlas, glow, projection=projection)

            canvas = base.copy()
            draw = ImageDraw.Draw(canvas, "RGBA")
            draw.rounded_rectangle(
                ARENA_BOX, radius=24, fill=(*PANEL, 248), outline=(35, 72, 75), width=2
            )
            draw.rounded_rectangle(
                SIDEBAR_BOX, radius=24, fill=(*PANEL, 248), outline=(35, 72, 75), width=2
            )
            left, top, right, bottom = ARENA_BOX
            for grid_x in np.linspace(bounds["x"][0], bounds["x"][1], 12):
                gx, _ = _screen(float(grid_x), 0.0, bounds)
                draw.line((gx, top + 18, gx, bottom - 18), fill=(70, 120, 116, 25), width=1)
            for grid_y in np.linspace(bounds["y"][0], bounds["y"][1], 9):
                _, gy = _screen(0.0, float(grid_y), bounds)
                draw.line((left + 18, gy, right - 18, gy), fill=(70, 120, 116, 25), width=1)
            tx, ty = _screen(float(target["x_mm"]), float(target["y_mm"]), bounds)
            pulse = 1.0 + 0.08 * math.sin(frame_index * 0.12)
            target_px = 74 * pulse
            for radius, alpha in ((target_px * 1.9, 18), (target_px * 1.45, 30), (target_px, 62)):
                draw.ellipse(
                    (tx - radius, ty - radius, tx + radius, ty + radius), fill=(*CYAN, alpha)
                )
            draw.ellipse(
                (tx - 25, ty - 25, tx + 25, ty + 25), fill=(220, 255, 246), outline=CYAN, width=3
            )
            draw.text(
                (tx - 71, ty + 92), "CALIBRATED VISUAL CUE", font=_font(14, bold=True), fill=CYAN
            )

            interpolated: dict[str, dict[str, Any]] = {}
            for fly_id in fly_ids:
                current = tracks[fly_id][cursor]
                following = tracks[fly_id][next_cursor]
                heading_a = float(current["heading_rad"])
                delta = (float(following["heading_rad"]) - heading_a + math.pi) % (
                    2 * math.pi
                ) - math.pi
                fly = {
                    **current,
                    "x_mm": (1.0 - fraction) * float(current["x_mm"])
                    + fraction * float(following["x_mm"]),
                    "y_mm": (1.0 - fraction) * float(current["y_mm"])
                    + fraction * float(following["y_mm"]),
                    "heading_rad": heading_a + fraction * delta,
                }
                interpolated[fly_id] = fly
                trail_start = max(0, cursor - 90)
                points = [
                    _screen(float(item["x_mm"]), float(item["y_mm"]), bounds)
                    for item in tracks[fly_id][trail_start : cursor + 1]
                ]
                if len(points) > 1:
                    draw.line(points, fill=colours[fly_id] + "75", width=3)
                _draw_fly(draw, fly, bounds)
                fx, fy = _screen(float(fly["x_mm"]), float(fly["y_mm"]), bounds)
                draw.text(
                    (fx - 30, fy - 48), fly_id, font=_font(13, bold=True), fill=colours[fly_id]
                )

            draw.text(
                (58, 34),
                "MALECNS COHORT / CLOSED-LOOP TARGET APPROACH",
                font=_font(22, bold=True),
                fill=CYAN,
            )
            draw.text(
                (58, 72),
                "Eight directions. Eight independent neural states.",
                font=_font(34, bold=True),
                fill=INK,
            )
            draw.text(
                (1380, 42),
                f"t = {t_us / 1_000_000:5.2f} biological s",
                font=_font(20, bold=True),
                fill=INK,
            )
            draw.text(
                (1380, 76),
                "OFFLINE PLAYBACK / RECORDED STATE",
                font=_font(15, bold=True),
                fill=AMBER,
            )

            brain_image = Image.fromarray(cached_brain)
            canvas.paste(brain_image, (1324, 174))
            draw.rectangle((1324, 174, 1860, 486), outline=(52, 100, 101), width=1)
            draw.text(
                (1328, 150),
                "AGGREGATE CNS ACTIVITY / RELEASED SOMA POSITIONS",
                font=_font(14, bold=True),
                fill=DIM,
            )
            draw.text(
                (1328, 496),
                f"{atlas.drawn:,} drawn / {atlas.missing:,} without released soma",
                font=_font(13),
                fill=DIM,
            )
            draw.text(
                (1328, 538),
                "DESCENDING DRIVE + TARGET DISTANCE",
                font=_font(15, bold=True),
                fill=INK,
            )
            command_row = rows[cursor]["commands"]
            for index, fly_id in enumerate(fly_ids):
                y = 575 + index * 45
                drive_raw = command_row[fly_id].get("descending_drive_hz")
                drive = float(drive_raw) if drive_raw is not None else 0.0
                distance = math.hypot(
                    float(interpolated[fly_id]["x_mm"]) - float(target["x_mm"]),
                    float(interpolated[fly_id]["y_mm"]) - float(target["y_mm"]),
                )
                draw.text((1328, y), fly_id, font=_font(14, bold=True), fill=colours[fly_id])
                draw.rounded_rectangle((1410, y + 1, 1690, y + 15), radius=7, fill=(28, 53, 57))
                draw.rounded_rectangle(
                    (1410, y + 1, 1410 + min(280.0, drive / 18.0 * 280.0), y + 15),
                    radius=7,
                    fill=colours[fly_id],
                )
                draw.text((1704, y - 3), f"{drive:4.1f} Hz", font=_font(13), fill=INK)
                draw.text((1793, y - 3), f"{distance:4.1f} mm", font=_font(13), fill=DIM)
            draw.text(
                (1328, 956),
                "one topology / one sparse allocation / separate state",
                font=_font(14, bold=True),
                fill=CYAN,
            )
            draw.text(
                (1328, 982),
                "visual encoder + LIF + decoder + body are P/E",
                font=_font(14),
                fill=AMBER,
            )
            draw.text(
                (60, 1040),
                "COHORT TARGET APPROACH, NOT SOCIAL SWARMING  |  V0 STRUCTURAL  |  "
                "DECODER RECEIVES NO TARGET COORDINATES",
                font=_font(16, bold=True),
                fill=AMBER,
            )
            writer.append_data(np.asarray(canvas))
        for _ in range(closing_frames):
            writer.append_data(np.asarray(closing))
    finally:
        writer.close()

    render_manifest = {
        "schema_version": "1.0",
        "presentation_id": manifest["presentation_id"],
        "source_manifest": str(manifest_path.resolve()),
        "source_manifest_sha256": _sha256(manifest_path),
        "video": str(output.resolve()),
        "video_sha256": _sha256(output),
        "resolution": [WIDTH, HEIGHT],
        "fps": render_fps,
        "duration_s": (opening_frames + simulation_frames + closing_frames) / render_fps,
        "rendering_advanced_simulator_state": False,
        "evidence_grade": False,
        "scientific_validation_tier_awarded": None,
        "claim_boundary": manifest["claim_boundary"],
    }
    render_manifest_path = output.with_name("render-manifest.json")
    render_manifest_path.write_text(
        json.dumps(render_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output.resolve()


def build_swarm_showcase(
    *,
    root: Path,
    scenario_path: Path | None = None,
    output_root: Path | None = None,
    source_directory: Path | None = None,
    output_path: Path | None = None,
    seed: int = 7,
    fps: int | None = None,
) -> dict[str, Any]:
    directory = source_directory or record_swarm_cns(
        root=root,
        scenario_path=scenario_path,
        output_root=output_root,
        seed=seed,
    )
    video = render_swarm_cns(directory, root=root, output_path=output_path, fps=fps)
    return {
        "source_directory": str(directory.resolve()),
        "video": str(video),
        "video_sha256": _sha256(video),
        "render_manifest": str(video.with_name("render-manifest.json")),
        "scientific_validation_tier_awarded": None,
    }


__all__ = ["build_swarm_showcase", "record_swarm_cns", "render_swarm_cns"]
