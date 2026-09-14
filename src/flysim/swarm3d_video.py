# SPDX-License-Identifier: GPL-2.0-or-later
"""Composite a swarm recording into a video: the arena, the brains, and the traces.

Nothing here touches a simulation. It reads a finished recording -- `trace.jsonl`,
`poses.npz` and one `spikes-<fly>.npz` per fly -- rebuilds the scene from the recorded
scenario, writes recorded physics states into it and draws. Re-rendering with different
settings produces a different video from identical numbers.

Two layouts, and the video moves between them:

**stage** -- the arena at 1280x760 beside one fly's brain at 640x760, with a trace strip
underneath carrying that fly's two descending readout rates and a raster of what every fly
in the swarm was doing at the same moment.

**grid** -- twelve brains at once, full frame. That shot exists because it is the one claim
about this system that a wide shot cannot make: these are twelve independent neural states,
not one simulation drawn twelve times, and the only way to see that is to watch twelve
activity patterns diverge from a shared starting condition.

The brain view is a projection of the released soma coordinates. A body without a released
position is simulated and recorded like every other neuron and simply cannot be drawn, and
the count appears on the frame rather than leaving a viewer to assume the cloud is the whole
graph. Brightness is spike count, not membrane voltage, under the fixed logarithmic map
`flysim.demo01_render` uses, so panels stay comparable frame for frame and run for run.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.demo01_render import (
    BrainAtlas,
    BrainProjection,
    SpikeRecording,
    render_brain,
)
from flysim.errors import ConfigurationError, ReadinessError
from flysim.swarm3d import SwarmArenaParameters, SwarmFlySpec, SwarmObject
from flysim.swarm3d_replay import (
    CameraFraming,
    PoseRecording,
    Shot,
    SwarmReplay,
    SwarmTrajectories,
    Timeline,
    camera_for,
    read_trajectories,
)

# Composition. 64 + 760 + 200 + 56 = 1080, and 1280 + 640 = 1920.
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
HEADER_HEIGHT = 64
STAGE_HEIGHT = 760
TRACE_HEIGHT = 200
FOOTER_HEIGHT = 56
STAGE_WIDTH = 1280
BRAIN_WIDTH = FRAME_WIDTH - STAGE_WIDTH

# The twelve-brain grid: 4 across, 3 down, inside the full 1920x960 body of the frame.
GRID_COLUMNS = 4
GRID_ROWS = 3
GRID_CELL_WIDTH = FRAME_WIDTH // GRID_COLUMNS
GRID_CELL_HEIGHT = (FRAME_HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT) // GRID_ROWS

INK = (232, 236, 244)
DIM = (128, 138, 156)
FAINT = (74, 82, 98)
BACKGROUND = (9, 11, 16)
PANEL = (14, 17, 24)
WARN = (255, 206, 84)
LEFT_COLOUR = (108, 196, 255)
RIGHT_COLOUR = (255, 138, 108)
DRIVE_COLOUR = (126, 232, 158)

# How a spike count at a 15 ms coupling interval becomes brightness at 30 frames a second.
# The glow at interval k is the sum of every earlier interval's count weighted by
# INTERVAL_DECAY to the power of the interval gap, which is a display choice and is stated
# on the frame. Computing it as a function of the cursor rather than carrying it forward in
# a variable is what lets the shot list revisit an earlier moment: the brightness of a
# frame depends only on which interval it shows, never on which frames came before it.
INTERVAL_DECAY = 0.89
GLOW_SPAN_INTERVALS = 26

# How near an object's surface a fly has to end for the recording to call it contact.
# A NeuroMechFly thorax is about 1 mm across, so a gap under a millimetre is a fly
# against the object. Nothing preregistered this and nothing scores it; it is a
# description of a finished recording, and the control is free to satisfy it -- on
# this pair of runs one control fly does, by drift.
CONTACT_GAP_MM = 1.0


def _fonts() -> dict[str, Any]:
    from PIL import ImageFont

    def pick(size: int) -> Any:
        for name in (
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "arial.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def pick_bold(size: int) -> Any:
        for name in (
            "DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "arialbd.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return pick(size)

    return {
        "hero": pick_bold(52),
        "title": pick_bold(26),
        "head": pick_bold(19),
        "body": pick(17),
        "small": pick(14),
        "tiny": pick(12),
        "mono": pick(15),
    }


# --------------------------------------------------------------------------------------
# Brightness
# --------------------------------------------------------------------------------------


def decayed_glow(
    spikes: SpikeRecording,
    row_by_dense: np.ndarray,
    cursor: int,
    *,
    drawn: int,
    span: int = GLOW_SPAN_INTERVALS,
    decay: float = INTERVAL_DECAY,
) -> np.ndarray:
    """Per-drawn-neuron activity at one recorded interval, decayed over the recent past.

    A pure function of `cursor`, which is what lets a shot jump backwards in time without
    the brain panel carrying brightness from a moment the viewer has not been shown yet.
    """
    glow = np.zeros(drawn, dtype=np.float32)
    first = max(0, cursor - span + 1)
    for interval in range(first, cursor + 1):
        indices, counts = spikes.interval(interval)
        if indices.size == 0:
            continue
        weight = decay ** (cursor - interval)
        target = row_by_dense[indices]
        keep = target >= 0
        if np.any(keep):
            np.add.at(glow, target[keep], counts[keep].astype(np.float32) * weight)
    return glow


# --------------------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------------------


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _header(draw: Any, fonts: dict[str, Any], *, title: str, right: str) -> None:
    draw.rectangle([0, 0, FRAME_WIDTH, HEADER_HEIGHT], fill=PANEL)
    draw.text((28, 19), title, font=fonts["title"], fill=INK)
    width = draw.textlength(right, font=fonts["small"])
    draw.text((FRAME_WIDTH - 28 - width, 25), right, font=fonts["small"], fill=DIM)
    draw.line(
        [0, HEADER_HEIGHT - 1, FRAME_WIDTH, HEADER_HEIGHT - 1], fill=(32, 38, 50), width=1
    )


def _footer(draw: Any, fonts: dict[str, Any], lines: tuple[str, str]) -> None:
    top = FRAME_HEIGHT - FOOTER_HEIGHT
    draw.rectangle([0, top, FRAME_WIDTH, FRAME_HEIGHT], fill=PANEL)
    draw.line([0, top, FRAME_WIDTH, top], fill=(32, 38, 50), width=1)
    draw.text((28, top + 8), lines[0], font=fonts["tiny"], fill=DIM)
    draw.text((28, top + 27), lines[1], font=fonts["tiny"], fill=FAINT)


def _caption_band(
    draw: Any,
    fonts: dict[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    text: str,
    colour: tuple[int, int, int] = INK,
) -> None:
    lines = _wrap(draw, text, fonts["body"], width - 32)[:2]
    height = 16 + 24 * len(lines)
    draw.rectangle([x, y - height, x + width, y], fill=(0, 0, 0))
    for index, line in enumerate(lines):
        draw.text((x + 16, y - height + 8 + index * 24), line, font=fonts["body"], fill=colour)


# --------------------------------------------------------------------------------------
# Trace strip
# --------------------------------------------------------------------------------------


def _draw_traces(
    draw: Any,
    fonts: dict[str, Any],
    trajectories: SwarmTrajectories,
    *,
    cursor: int,
    subject: int,
    subject_label: str,
    readout_left: np.ndarray,
    readout_right: np.ndarray,
    forward: np.ndarray,
    stimulus_present: bool,
) -> None:
    """Two panels: the subject's descending readout, and every fly's forward drive."""
    top = HEADER_HEIGHT + STAGE_HEIGHT
    draw.rectangle([0, top, FRAME_WIDTH, top + TRACE_HEIGHT], fill=PANEL)
    draw.line([0, top, FRAME_WIDTH, top], fill=(32, 38, 50), width=1)

    # -- left: the subject's two descending population rates ---------------------------
    pad = 28
    plot_x0, plot_x1 = pad, STAGE_WIDTH - 40
    plot_y0, plot_y1 = top + 34, top + TRACE_HEIGHT - 26
    window = 420
    first = max(0, cursor - window + 1)
    left = readout_left[first : cursor + 1, subject]
    right = readout_right[first : cursor + 1, subject]
    ceiling = max(
        1.0,
        float(np.max(readout_left[:, subject])),
        float(np.max(readout_right[:, subject])),
    )

    draw.text(
        (pad, top + 10),
        f"descending readout, {subject_label}",
        font=fonts["small"],
        fill=DIM,
    )
    key_x = pad + 250
    for label, colour, value in (
        ("DNp/DNa left", LEFT_COLOUR, left[-1] if left.size else 0.0),
        ("right", RIGHT_COLOUR, right[-1] if right.size else 0.0),
    ):
        draw.rectangle([key_x, top + 14, key_x + 12, top + 24], fill=colour)
        text = f"{label}  {value:5.2f} Hz"
        draw.text((key_x + 18, top + 11), text, font=fonts["small"], fill=INK)
        key_x += int(draw.textlength(text, font=fonts["small"])) + 42

    draw.line([plot_x0, plot_y1, plot_x1, plot_y1], fill=(40, 46, 60), width=1)
    draw.text(
        (plot_x1 + 6, plot_y0 - 7), f"{ceiling:.1f} Hz", font=fonts["tiny"], fill=FAINT
    )
    span = max(1, window - 1)
    for series, colour in ((left, LEFT_COLOUR), (right, RIGHT_COLOUR)):
        if series.size < 2:
            continue
        points = []
        offset = window - series.size
        for index, value in enumerate(series):
            px = plot_x0 + (plot_x1 - plot_x0) * (offset + index) / span
            py = plot_y1 - (plot_y1 - plot_y0) * min(1.0, value / ceiling)
            points.append((px, py))
        draw.line(points, fill=colour, width=2)

    # -- right: every fly's forward drive, as a raster --------------------------------
    raster_x0 = STAGE_WIDTH + 34
    raster_x1 = FRAME_WIDTH - 28
    draw.text(
        (raster_x0, top + 10),
        "forward drive, all flies",
        font=fonts["small"],
        fill=DIM,
    )
    rows = forward.shape[1]
    cell = (TRACE_HEIGHT - 58) / rows
    for fly in range(rows):
        y0 = top + 34 + cell * fly
        series = forward[first : cursor + 1, fly]
        offset = window - series.size
        for index, value in enumerate(series):
            if value <= 0.0:
                continue
            px0 = raster_x0 + (raster_x1 - raster_x0) * (offset + index) / span
            px1 = raster_x0 + (raster_x1 - raster_x0) * (offset + index + 1) / span
            shade = int(60 + 195 * min(1.0, value))
            colour = (
                int(DRIVE_COLOUR[0] * shade / 255),
                int(DRIVE_COLOUR[1] * shade / 255),
                int(DRIVE_COLOUR[2] * shade / 255),
            )
            draw.rectangle([px0, y0, max(px0 + 1, px1), y0 + cell - 1], fill=colour)
        if fly == subject:
            draw.rectangle(
                [raster_x0 - 6, y0, raster_x0 - 3, y0 + cell - 1], fill=(255, 255, 255)
            )
    note = (
        "stimulus absent: the encoder is held at baseline"
        if not stimulus_present
        else "one row per fly, brightness is commanded forward drive"
    )
    draw.text(
        (raster_x0, top + TRACE_HEIGHT - 20),
        note,
        font=fonts["tiny"],
        fill=WARN if not stimulus_present else FAINT,
    )


# --------------------------------------------------------------------------------------
# The render
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRecording:
    directory: Path
    summary: dict[str, Any]
    trajectories: SwarmTrajectories
    poses: PoseRecording
    spikes: dict[str, SpikeRecording]

    @classmethod
    def load(cls, directory: Path, *, load_spikes_for: Sequence[str] | None = None) -> RunRecording:
        summary_path = directory / "summary.json"
        if not summary_path.is_file():
            raise ReadinessError(f"No run summary at {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        labels = {
            fly["fly_id"]: fly.get("label", fly["fly_id"])
            for fly in summary["world"]["flies"]
        }
        trajectories = read_trajectories(directory / "trace.jsonl", labels=labels)
        poses = PoseRecording(directory / "poses.npz")
        wanted = (
            tuple(load_spikes_for)
            if load_spikes_for is not None
            else trajectories.fly_ids
        )
        spikes = {
            fly_id: SpikeRecording(directory / summary["recording"]["spikes"][fly_id])
            for fly_id in wanted
        }
        return cls(
            directory=directory,
            summary=summary,
            trajectories=trajectories,
            poses=poses,
            spikes=spikes,
        )


def _verify_scenario_matches(
    summary: dict[str, Any],
    flies: Sequence[SwarmFlySpec],
    objects: Sequence[SwarmObject],
) -> None:
    """Refuse to draw an arena the flies did not walk in.

    The scenario file is read for the objects' colours, which recordings made before
    2026-09-13 do not carry, and for nothing else. An edit to it between running and
    rendering would otherwise change the drawn world without changing anything that says
    so, which is exactly the kind of drift this project keeps finding. Every geometric
    quantity is therefore checked against what the run recorded.
    """
    recorded = summary["world"]
    recorded_flies = recorded["flies"]
    if len(recorded_flies) != len(flies):
        raise ConfigurationError(
            f"The recording holds {len(recorded_flies)} flies and the scenario declares "
            f"{len(flies)}. The scenario has changed since the run."
        )
    for entry, spec in zip(recorded_flies, flies, strict=True):
        if entry["fly_id"] != spec.fly_id or not (
            math.isclose(entry["x_mm"], spec.x_mm, abs_tol=1e-9)
            and math.isclose(entry["y_mm"], spec.y_mm, abs_tol=1e-9)
            and math.isclose(entry["heading_rad"], spec.heading_rad, abs_tol=1e-9)
        ):
            raise ConfigurationError(
                f"Fly {entry['fly_id']} started somewhere else in the run than the "
                "scenario now says. The scenario has changed since the run."
            )
    recorded_objects = {entry["object_id"]: entry for entry in recorded["objects"]}
    if set(recorded_objects) != {obj.object_id for obj in objects}:
        raise ConfigurationError(
            "The scenario's objects are not the run's objects. The scenario has changed "
            "since the run."
        )
    for obj in objects:
        entry = recorded_objects[obj.object_id]
        for name, value in (
            ("kind", obj.kind),
            ("x_mm", obj.x_mm),
            ("y_mm", obj.y_mm),
            ("radius_mm", obj.radius_mm),
            ("height_mm", obj.height_mm),
        ):
            if entry[name] != value:
                raise ConfigurationError(
                    f"Object {obj.object_id} had {name}={entry[name]!r} in the run and "
                    f"{value!r} in the scenario. The scenario has changed since the run."
                )


def final_object_census(
    trajectories: SwarmTrajectories, objects: Sequence[SwarmObject]
) -> dict[str, Any]:
    """Which object each fly ended up nearest, of any kind, from the recorded final pose.

    The run summary measures distance closed to the nearest *food* object, which is the
    quantity the demonstration was built around and is not the whole picture: the encoder
    has no colour channel and cannot tell a food sphere from a pillar. On a recording where
    most flies end at pillars, reporting only the food number would be the flattering half
    of what happened.
    """
    if not objects:
        return {"per_fly": [], "by_kind": {}, "note": "the arena holds no objects"}
    last = trajectories.intervals - 1
    per_fly: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    for index, fly_id in enumerate(trajectories.fly_ids):
        x = float(trajectories.x_mm[last, index])
        y = float(trajectories.y_mm[last, index])
        nearest = min(
            objects, key=lambda obj: (obj.x_mm - x) ** 2 + (obj.y_mm - y) ** 2
        )
        gap = float(math.hypot(nearest.x_mm - x, nearest.y_mm - y)) - nearest.radius_mm
        per_fly.append(
            {
                "fly_id": fly_id,
                "nearest_object": nearest.object_id,
                "kind": nearest.kind,
                "surface_gap_mm": gap,
            }
        )
        by_kind[nearest.kind] = by_kind.get(nearest.kind, 0) + 1
    touching = sum(1 for entry in per_fly if entry["surface_gap_mm"] <= CONTACT_GAP_MM)
    return {
        "per_fly": per_fly,
        "by_kind": by_kind,
        "flies_within_contact_gap": touching,
        "contact_gap_mm": CONTACT_GAP_MM,
        "what_this_is_not": (
            "No threshold on this was preregistered and none is scored. It describes what "
            "a finished recording did, and the control can satisfy it: on the pair of runs "
            "this video was cut from, one control fly reaches an object by drift alone."
        ),
        "measured_from": "the recorded pose at the last coupling interval",
        "surface_gap_mm_is": (
            "centre-to-centre distance minus the object's radius, so zero means the fly "
            "is against the object"
        ),
    }

def _series(trajectories: SwarmTrajectories, key: str, field: str) -> np.ndarray:
    rows = trajectories.rows
    out = np.zeros((len(rows), len(trajectories.fly_ids)), dtype=np.float64)
    for step, row in enumerate(rows):
        for index, entry in enumerate(row["flies"]):
            block = entry[key]
            out[step, index] = float(block.get(field, 0.0))
    return out


def render_showcase(
    recording: RunRecording,
    *,
    output_path: Path,
    timeline: Timeline,
    positions_path: Path,
    scenario_path: Path,
    fps: int = 30,
    grid_shots: frozenset[str] = frozenset(),
    compare_shots: frozenset[str] = frozenset(),
    control: RunRecording | None = None,
    seed: int = 1,
    title: str = "One connectome, twelve bodies",
    opening_seconds: float = 5.0,
    closing_seconds: float = 7.0,
    stills: Sequence[float] = (),
    stills_directory: Path | None = None,
    ground_half_size_mm: float = 420.0,
    progress: bool = False,
) -> dict[str, Any]:
    """Write the video. Returns a manifest describing exactly what was drawn."""
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw

    summary = recording.summary
    trajectories = recording.trajectories
    smoothed = trajectories.smoothed(window=15)
    fly_ids = trajectories.fly_ids
    fly_count = len(fly_ids)

    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    # The drawn extent of the ground plane, and nothing else, is a render-time choice. A
    # MuJoCo plane is a half-space: it is infinite for collision and its `size` is read by
    # the visualiser alone, so widening it pushes the horizon out of the widest shots
    # without touching a contact, a recorded state or a number.
    arena = SwarmArenaParameters.from_mapping(
        {**scenario["arena"], "ground_half_size_mm": ground_half_size_mm}
    )
    flies = tuple(SwarmFlySpec.from_mapping(item) for item in scenario["flies"])[:fly_count]
    objects = tuple(SwarmObject.from_mapping(item) for item in scenario.get("objects", ()))
    _verify_scenario_matches(summary, flies, objects)

    atlas = BrainAtlas.load(
        positions_path,
        neuron_count=int(summary["graph"]["neurons"]),
        entry_body_ids=summary.get("populations", {}).get("entry_body_ids", ()),
        readout_body_ids=summary.get("populations", {}).get("readout_body_ids", ()),
    )
    any_spikes = next(iter(recording.spikes.values()))
    row_by_dense = np.full(any_spikes.neuron_count, -1, dtype=np.int64)
    row_by_dense[atlas.dense_index] = np.arange(atlas.drawn, dtype=np.int64)

    stage_projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(4.0),
        width=BRAIN_WIDTH,
        height=STAGE_HEIGHT,
        view="frontal",
    )
    # Dorsal in the grid: the cell is landscape, and a portrait frontal view drawn into
    # it wastes half the cell and shrinks the optic lobes, which are the thing the grid
    # exists to show twelve of.
    grid_projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(8.0),
        width=GRID_CELL_WIDTH,
        height=GRID_CELL_HEIGHT,
        view="dorsal",
    )

    readout_left = _series(trajectories, "readout_hz", "dn-visual-left")
    readout_right = _series(trajectories, "readout_hz", "dn-visual-right")
    forward = _series(trajectories, "command", "forward")
    stimulus_present = bool(summary["vision"]["stimulus_present"])

    fonts = _fonts()
    census = final_object_census(trajectories, objects)
    control_census = (
        final_object_census(control.trajectories, objects)
        if control is not None
        else census
    )
    frame_count = timeline.frame_count(fps)
    centre_x = float(np.mean([obj.x_mm for obj in objects])) if objects else 0.0
    centre_y = float(np.mean([obj.y_mm for obj in objects])) if objects else 0.0

    commit = str(summary.get("code_commit") or "unknown")[:12]
    footer_left = (
        f"MaleCNS v1.0  {summary['graph']['neurons']:,} neurons  "
        f"{summary['graph']['edges']:,} edges executed per fly  |  "
        f"one connectivity allocation, {fly_count} independent neural states  |  "
        f"GeNN/CUDA + FlyGym 2.1/MuJoCo 3.9  |  seed {summary['seed']}  |  commit {commit}"
    )
    footer_right = (
        f"{atlas.drawn:,} of {summary['graph']['neurons']:,} somata drawn; "
        f"{atlas.missing:,} carry no released position and are simulated but not drawn.  "
        "Brightness is spike count with a declared decay, not membrane voltage.  "
        "Walking is an engineered pattern generator, not the simulated VNC.  "
        "Engineering demonstration: no validation tier is claimed."
    )

    # Contact-sheet mode renders a handful of chosen instants as PNGs through the
    # identical composition, so a cut can be judged in a minute instead of an hour.
    frame_indices: Sequence[int]
    if stills:
        frame_indices = [
            min(frame_count - 1, max(0, round(value * fps))) for value in stills
        ]
        opening_seconds = 0.0
        closing_seconds = 0.0
        still_root = stills_directory or output_path.parent / "stills"
        still_root.mkdir(parents=True, exist_ok=True)
    else:
        frame_indices = range(frame_count)
        still_root = output_path.parent

    writer = (
        None
        if stills
        else imageio.get_writer(
            output_path,
            fps=fps,
            codec="libx264",
            macro_block_size=1,
            # The brain panels are tens of thousands of isolated bright points, which is
            # close to the worst case for an inter-frame codec. CRF 20 keeps the file
            # small enough to live in the repository beside the other showcase videos
            # without the point cloud dissolving into blocks.
            ffmpeg_params=[
                "-pix_fmt", "yuv420p",
                "-preset", "slow",
                "-crf", "20",
                "-movflags", "+faststart",
            ],
        )
    )
    drawn_shots: list[dict[str, Any]] = []
    compare_resolution = (STAGE_HEIGHT, FRAME_WIDTH // 2)
    with SwarmReplay(
        arena, flies, objects, seed=seed, resolution=(STAGE_HEIGHT, STAGE_WIDTH)
    ) as replay:
        compare_replay: SwarmReplay | None = None
        if compare_shots and control is not None:
            compare_replay = SwarmReplay(
                arena, flies, objects, seed=seed, resolution=compare_resolution
            )

        if opening_seconds > 0.0 and writer is not None:
            opening = _title_card(
                replay, recording, fonts, title=title, summary=summary,
                fly_count=fly_count, objects=objects,
            )
            for _ in range(round(opening_seconds * fps)):
                writer.append_data(opening)

        for frame_index in frame_indices:
            video_t = frame_index / fps
            shot, u = timeline.at(video_t)
            sim_t = shot.sim_time(u)
            cursor = trajectories.index_at(sim_t)
            subject = (
                fly_ids.index(shot.subject)
                if shot.subject and shot.subject in fly_ids
                else 0
            )
            canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
            draw = ImageDraw.Draw(canvas)

            if (
                shot.name in compare_shots
                and compare_replay is not None
                and control is not None
            ):
                _compose_compare(
                    canvas,
                    draw,
                    fonts,
                    replay=compare_replay,
                    left=recording,
                    right=control,
                    shot=shot,
                    u=u,
                    trajectories=trajectories,
                    smoothed=smoothed,
                    centre=(centre_x, centre_y),
                    cursor=cursor,
                    census_by_side=(
                        census["flies_within_contact_gap"],
                        control_census["flies_within_contact_gap"],
                    ),
                )
            elif shot.name in grid_shots:
                _compose_grid(
                    canvas,
                    draw,
                    fonts,
                    atlas=atlas,
                    projection=grid_projection,
                    recording=recording,
                    row_by_dense=row_by_dense,
                    cursor=cursor,
                    trajectories=trajectories,
                    forward=forward,
                )
            else:
                _compose_stage(
                    canvas,
                    draw,
                    fonts,
                    replay=replay,
                    recording=recording,
                    atlas=atlas,
                    projection=stage_projection,
                    row_by_dense=row_by_dense,
                    cursor=cursor,
                    shot=shot,
                    u=u,
                    subject=subject,
                    trajectories=trajectories,
                    smoothed=smoothed,
                    centre=(centre_x, centre_y),
                    readout_left=readout_left,
                    readout_right=readout_right,
                    forward=forward,
                    stimulus_present=stimulus_present,
                )

            _header(
                draw,
                fonts,
                title=title,
                right=(
                    f"t = {sim_t:5.2f} s"
                    + (f"   x{shot.sim_rate:g} speed" if shot.sim_rate != 1.0 else "")
                    + f"   {summary['variant']}"
                ),
            )
            _footer(draw, fonts, (footer_left, footer_right))
            if writer is None:
                still = still_root / f"{shot.name}-{frame_index:05d}.png"
                canvas.save(still)
                print(f"  wrote {still}")
            else:
                writer.append_data(np.asarray(canvas))
            if progress and frame_index % 60 == 0:
                print(
                    f"  frame {frame_index:5d}/{frame_count}  "
                    f"shot {shot.name:<12} sim t={sim_t:6.2f}s",
                    flush=True,
                )
        if compare_replay is not None:
            compare_replay.close()
        if closing_seconds > 0.0 and writer is not None:
            control_summary = None
            if control is not None:
                control_summary = {
                    **control.summary,
                    "_contact": control_census["flies_within_contact_gap"],
                }
            closing = _closing_card(
                fonts,
                summary=summary,
                control=control_summary,
                atlas_drawn=atlas.drawn,
                atlas_missing=atlas.missing,
                census=census,
            )
            for _ in range(round(closing_seconds * fps)):
                writer.append_data(closing)
    if writer is not None:
        writer.close()

    for shot in timeline.shots:
        if shot.name in compare_shots:
            layout = "compare"
        elif shot.name in grid_shots:
            layout = "grid"
        else:
            layout = "stage"
        drawn_shots.append({**shot.as_dict(), "layout": layout})
    return {
        "video": None if stills else str(output_path),
        "stills": [str(value) for value in stills] if stills else None,
        "frames": frame_count + round((opening_seconds + closing_seconds) * fps),
        "timeline_frames": frame_count,
        "fps": fps,
        "resolution": [FRAME_WIDTH, FRAME_HEIGHT],
        "video_seconds": timeline.video_seconds + opening_seconds + closing_seconds,
        "opening_seconds": opening_seconds,
        "closing_seconds": closing_seconds,
        "control_recording": str(control.directory) if control else None,
        "shots": drawn_shots,
        "recording": str(recording.directory),
        "run_summary_sha256": None,
        "brain_view": {
            "somata_drawn": atlas.drawn,
            "somata_without_released_position": atlas.missing,
            "missing_by_superclass": atlas.missing_by_superclass,
            "brightness": (
                "spike count per neuron, summed over the preceding intervals with a "
                f"per-interval decay of {INTERVAL_DECAY} over {GLOW_SPAN_INTERVALS} "
                "intervals, then compressed by a fixed logarithmic map. Not membrane "
                "voltage, and never normalised per run."
            ),
            "projection": "released soma coordinates, orthographic, fixed viewpoint",
        },
        "rendering_advanced_simulator_state": False,
        "ground_plane_drawn_half_size_mm": ground_half_size_mm,
        "why_the_ground_plane_is_wider_than_the_run_declared": (
            "A MuJoCo plane geom is a half-space: infinite for collision, with `size` read "
            "by the visualiser alone. Widening the drawn extent moves the horizon out of "
            "the widest shots and changes no contact, no recorded state and no number."
        ),
        "scenario_checked_against_the_recording": True,
        "final_object_census": census,
        "control_final_object_census": control_census if control is not None else None,
        "what_separates_the_run_from_its_control": {
            "not_closing_distance": (
                "Both runs end nearer a food object. A body commanded to stand drifts "
                "forward along its own axis, which Track A measured (see "
                "docs/evidence/TRACK_A_STATION_KEEPING.md), and every fly was aimed so "
                "that food lies inside the encoder's mapped visual field, so the "
                "control leans the same way. Use flies_that_ended_against_an_object."
            ),
            "flies_that_ended_against_an_object": {
                "exact": census["flies_within_contact_gap"],
                "control": (
                    control_census["flies_within_contact_gap"]
                    if control is not None
                    else None
                ),
                "contact_gap_mm": census["contact_gap_mm"],
            },
            "flies_that_ever_walked": {
                "exact": sum(
                    1
                    for entry in summary["outcome"]["per_fly"]
                    if entry["locomotion_onset_us"]
                ),
                "control": (
                    sum(
                        1
                        for entry in control.summary["outcome"]["per_fly"]
                        if entry["locomotion_onset_us"]
                    )
                    if control is not None
                    else None
                ),
            },
            "mean_spiking_neurons_per_fly_per_interval": {
                "exact": summary["recording"][
                    "mean_active_neurons_per_interval_per_fly"
                ],
                "control": (
                    control.summary["recording"][
                        "mean_active_neurons_per_interval_per_fly"
                    ]
                    if control is not None
                    else None
                ),
            },
        },
        "how_the_arena_was_drawn": (
            "The scene was rebuilt from the scenario and every frame was drawn by writing "
            "a recorded whole-scene qpos into a world that has never been stepped. The "
            "replay path refuses to draw a world that has been stepped, so rendering "
            "cannot have advanced the simulation."
        ),
        "body_proxy_used": False,
        "evidence_grade": False,
        "validation_tier_awarded": None,
    }


def _compose_stage(
    canvas: Any,
    draw: Any,
    fonts: dict[str, Any],
    *,
    replay: SwarmReplay,
    recording: RunRecording,
    atlas: BrainAtlas,
    projection: BrainProjection,
    row_by_dense: np.ndarray,
    cursor: int,
    shot: Shot,
    u: float,
    subject: int,
    trajectories: SwarmTrajectories,
    smoothed: SwarmTrajectories,
    centre: tuple[float, float],
    readout_left: np.ndarray,
    readout_right: np.ndarray,
    forward: np.ndarray,
    stimulus_present: bool,
) -> None:
    from PIL import Image

    framing = camera_for(
        shot, u, trajectories, smoothed=smoothed, scene_centre=centre
    )
    decorations: list[dict[str, Any]] = []
    if shot.mode in {"follow", "pair"}:
        # A translucent halo over the fly the shot is about, so a viewer can keep hold of
        # one animal in a scene holding twelve. Drawn as decor, from the recorded pose.
        decorations.append(
            {
                "x_mm": float(trajectories.x_mm[cursor, subject]),
                "y_mm": float(trajectories.y_mm[cursor, subject]),
                # High enough to sit clear of the animal and large enough to find in a
                # crowded frame. At 0.26 mm and 1.35 mm up it was indistinguishable from a
                # leg once three flies were in shot, which defeats the point of marking
                # which one the caption is about.
                "z_mm": float(trajectories.z_mm[cursor, subject]) + 2.30,
                "radius_mm": 0.45,
                "rgba": (0.30, 1.00, 0.45, 0.92),
            }
        )
    stage = replay.render(recording.poses.at(cursor), framing, decorations=decorations)
    canvas.paste(Image.fromarray(stage), (0, HEADER_HEIGHT))

    fly_id = trajectories.fly_ids[subject]
    spikes = recording.spikes.get(fly_id)
    if spikes is not None:
        glow = decayed_glow(spikes, row_by_dense, cursor, drawn=atlas.drawn)
        brain = render_brain(atlas, glow, projection=projection)
        canvas.paste(Image.fromarray(brain), (STAGE_WIDTH, HEADER_HEIGHT))

    draw.line(
        [STAGE_WIDTH, HEADER_HEIGHT, STAGE_WIDTH, HEADER_HEIGHT + STAGE_HEIGHT],
        fill=(32, 38, 50),
        width=1,
    )
    label = trajectories.labels[subject]
    draw.rectangle(
        [STAGE_WIDTH + 1, HEADER_HEIGHT + 1, FRAME_WIDTH, HEADER_HEIGHT + 62],
        fill=(0, 0, 0),
    )
    draw.text(
        (STAGE_WIDTH + 18, HEADER_HEIGHT + 10),
        f"{label}  ·  its own 165,122-neuron state",
        font=fonts["head"],
        fill=INK,
    )
    driven = int(
        trajectories.rows[cursor]["flies"][subject]["scene"]["driven_lamina_bodies"]
    )
    state = trajectories.rows[cursor]["flies"][subject]["command"]["state"]
    draw.text(
        (STAGE_WIDTH + 18, HEADER_HEIGHT + 36),
        f"lamina cells driven {driven:>5}   ·   decoder {state}",
        font=fonts["small"],
        fill=DIM,
    )
    _caption_band(
        draw,
        fonts,
        x=0,
        y=HEADER_HEIGHT + STAGE_HEIGHT,
        width=STAGE_WIDTH,
        text=shot.caption,
    )
    _draw_traces(
        draw,
        fonts,
        trajectories,
        cursor=cursor,
        subject=subject,
        subject_label=label,
        readout_left=readout_left,
        readout_right=readout_right,
        forward=forward,
        stimulus_present=stimulus_present,
    )


def _compose_grid(
    canvas: Any,
    draw: Any,
    fonts: dict[str, Any],
    *,
    atlas: BrainAtlas,
    projection: BrainProjection,
    recording: RunRecording,
    row_by_dense: np.ndarray,
    cursor: int,
    trajectories: SwarmTrajectories,
    forward: np.ndarray,
) -> None:
    from PIL import Image

    for index, fly_id in enumerate(trajectories.fly_ids[: GRID_COLUMNS * GRID_ROWS]):
        spikes = recording.spikes.get(fly_id)
        if spikes is None:
            continue
        glow = decayed_glow(spikes, row_by_dense, cursor, drawn=atlas.drawn)
        panel = render_brain(atlas, glow, projection=projection)
        column = index % GRID_COLUMNS
        row = index // GRID_COLUMNS
        x = column * GRID_CELL_WIDTH
        y = HEADER_HEIGHT + row * GRID_CELL_HEIGHT
        canvas.paste(Image.fromarray(panel), (x, y))
        draw.rectangle(
            [x, y, x + GRID_CELL_WIDTH - 1, y + GRID_CELL_HEIGHT - 1],
            outline=(30, 36, 48),
            width=1,
        )
        label = trajectories.labels[index]
        drive = float(forward[cursor, index])
        draw.rectangle([x + 1, y + 1, x + GRID_CELL_WIDTH - 2, y + 26], fill=(0, 0, 0))
        draw.text((x + 12, y + 5), label, font=fonts["small"], fill=INK)
        bar = int(90 * min(1.0, drive))
        draw.rectangle(
            [x + GRID_CELL_WIDTH - 108, y + 10, x + GRID_CELL_WIDTH - 108 + bar, y + 19],
            fill=DRIVE_COLOUR,
        )
        draw.rectangle(
            [x + GRID_CELL_WIDTH - 108, y + 10, x + GRID_CELL_WIDTH - 18, y + 19],
            outline=(48, 56, 72),
            width=1,
        )



# --------------------------------------------------------------------------------------
# Cards and the comparison layout
# --------------------------------------------------------------------------------------


def _title_card(
    replay: SwarmReplay,
    recording: RunRecording,
    fonts: dict[str, Any],
    *,
    title: str,
    summary: dict[str, Any],
    fly_count: int,
    objects: Sequence[SwarmObject],
) -> np.ndarray:
    """The opening frame: the arena at rest, with what the viewer is about to see.

    Drawn over the real first recorded state rather than over a graphic, because the first
    thing the video should establish is that the scene is the simulation.
    """
    from PIL import Image, ImageDraw, ImageFilter

    framing = CameraFraming(
        lookat_mm=(0.0, 0.0, 1.6),
        distance_mm=102.0,
        azimuth_deg=38.0,
        elevation_deg=-27.0,
    )
    stage = replay.render(recording.poses.at(0), framing)
    backdrop = Image.fromarray(stage).resize((FRAME_WIDTH, FRAME_HEIGHT))
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=5))
    canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
    canvas.paste(backdrop, (0, 0))
    shade = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0))
    canvas = Image.blend(canvas, shade, 0.70)
    # A soft dark plate under the text. A checkered ground read through a blur is still
    # high contrast, and the smaller lines were competing with it.
    plate = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0))
    mask = Image.new("L", (FRAME_WIDTH, FRAME_HEIGHT), 0)
    ImageDraw.Draw(mask).rectangle([96, 236, 1560, 884], fill=150)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=48))
    canvas = Image.composite(plate, canvas, mask)
    draw = ImageDraw.Draw(canvas)

    food = sum(1 for obj in objects if obj.kind == "food")
    pillars = sum(1 for obj in objects if obj.kind == "pillar")
    lines = (
        (fonts["hero"], title, INK, 58),
        (
            fonts["title"],
            f"{fly_count} Drosophila bodies. {fly_count} independent copies of the "
            f"{summary['graph']['neurons']:,}-neuron male CNS connectome.",
            INK,
            40,
        ),
        (
            fonts["body"],
            f"{summary['graph']['edges']:,} synaptic edges executed per fly, every "
            "interval, on one GPU.",
            INK,
            30,
        ),
        (
            fonts["body"],
            f"{food} food spheres, {pillars} pillars, one ground plane. Each fly sees the "
            "scene through its own retinotopic lamina drive and steers on nothing but two "
            "descending population rates.",
            INK,
            30,
        ),
        (
            fonts["body"],
            "No fly is given a target coordinate. No fly is given a path. Nothing in any "
            "decoder can read the world.",
            (168, 226, 190),
            44,
        ),
        (
            fonts["small"],
            "Engineering demonstration of the simulator. The walking controller is a "
            "published pattern generator, not the simulated ventral nerve cord; the "
            "retina-to-lamina synapse is not executed; no validation tier is claimed.",
            WARN,
            0,
        ),
    )
    y = 274
    for font, text, colour, gap in lines:
        for piece in _wrap(draw, text, font, 1360):
            draw.text((150, y), piece, font=font, fill=colour)
            y += int(font.size * 1.35)
        y += gap
    return np.asarray(canvas)


def _column(
    draw: Any,
    fonts: dict[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    heading: str,
    heading_colour: tuple[int, int, int],
    entries: Sequence[str],
    font_key: str,
    leading: int,
) -> int:
    """Draw a headed column of wrapped paragraphs. Returns the y it finished at."""
    draw.text((x, y), heading, font=fonts["title"], fill=heading_colour)
    y += 46
    for entry in entries:
        for piece in _wrap(draw, entry, fonts[font_key], width):
            draw.text((x, y), piece, font=fonts[font_key], fill=INK if font_key == "body" else DIM)
            y += leading
        y += 10
    return y


def _closing_card(
    fonts: dict[str, Any],
    *,
    summary: dict[str, Any],
    control: dict[str, Any] | None,
    atlas_drawn: int,
    atlas_missing: int,
    census: dict[str, Any] | None = None,
) -> np.ndarray:
    """What the run measured, and every limit that qualifies it."""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    outcome = summary["outcome"]
    fly_count = summary["batch"]["size"]
    spiking = summary["recording"]["mean_active_neurons_per_interval_per_fly"]
    walked = sum(1 for entry in outcome["per_fly"] if entry["locomotion_onset_us"])
    touching = census["flies_within_contact_gap"] if census else None

    measured: list[str] = []
    if control is not None:
        control_outcome = control["outcome"]
        control_walked = sum(
            1 for entry in control_outcome["per_fly"] if entry["locomotion_onset_us"]
        )
        control_total = control["batch"]["size"]
        control_spiking = control["recording"][
            "mean_active_neurons_per_interval_per_fly"
        ]
        measured.append(
            f"Flies that ever walked: {walked} of {fly_count}, against "
            f"{control_walked} of {control_total} in the control, which is the same "
            "twelve flies on the same seed in the same bodies with the encoder held at "
            "its baseline."
        )
        if touching is not None:
            control_touching = control.get("_contact")
            measured.append(
                f"Flies that ended against an object: {touching} of {fly_count}"
                + (
                    f", against {control_touching} of {control_total}."
                    if control_touching is not None
                    else "."
                )
            )
        measured.append(
            f"Neurons spiking per fly per coupling interval: {spiking:,.0f}, against "
            f"{control_spiking:,.0f}."
        )
        measured.append(
            "What does NOT separate them on its own: distance closed to food. Both runs "
            f"end nearer a food object, {outcome['median_closed_mm']:+.2f} mm against "
            f"{control_outcome['median_closed_mm']:+.2f} mm. A body commanded to stand "
            "drifts forward along its own axis, and every fly was aimed so that food "
            "lies inside the encoder's mapped visual field, so the control leans that "
            "way too."
        )
    else:
        measured.append(
            f"Flies that ever walked: {walked} of {fly_count}. Neurons spiking per fly "
            f"per coupling interval: {spiking:,.0f}."
        )
        measured.append(
            f"{outcome['flies_that_closed_on_a_food_object']} of {fly_count} flies ended "
            f"nearer a food object, median {outcome['median_closed_mm']:+.2f} mm. With no "
            "control run beside it that number separates nothing."
        )
    if census is not None and census.get("by_kind"):
        parts = ", ".join(
            f"{count} at a {kind}" for kind, count in sorted(census["by_kind"].items())
        )
        measured.append(
            f"Where they finished, nearest object of any kind: {parts}. The encoder has "
            "no colour channel, so food and a pillar differ to it only in angular size."
        )
    measured.append(
        f"{summary['duration_us'] / 1e6:.0f} s of behaviour in "
        f"{summary['intervals']:,} coupling intervals of "
        f"{summary['coupling_us'] / 1000:.0f} ms, "
        f"{summary['graph']['neurons']:,} neurons and "
        f"{summary['graph']['edges']:,} edges executed per fly per interval over one "
        f"shared connectivity allocation, in "
        f"{summary['simulation_seconds'] / 60:.0f} minutes of wall clock."
    )

    limits = list(summary.get("omissions", ()))
    limits.append(
        f"{atlas_missing:,} of {summary['graph']['neurons']:,} simulated neurons carry no "
        f"released soma position and are recorded but never drawn; the cloud is "
        f"{atlas_drawn:,} of them."
    )
    limits.append(
        "No preregistered biological hypothesis and no acceptance contract exist for a "
        "swarm, so this run demonstrates machinery and validates no biology. No validation "
        "tier is awarded."
    )

    draw.text((120, 64), "What this run did", font=fonts["hero"], fill=INK)
    _column(
        draw,
        fonts,
        x=120,
        y=150,
        width=800,
        heading="Measured",
        heading_colour=INK,
        entries=measured,
        font_key="body",
        leading=26,
    )
    _column(
        draw,
        fonts,
        x=1010,
        y=150,
        width=790,
        heading="What it is not",
        heading_colour=WARN,
        entries=limits,
        font_key="small",
        leading=21,
    )

    _column(
        draw,
        fonts,
        x=120,
        y=640,
        width=1680,
        heading="Reproduce it",
        heading_colour=INK,
        entries=(
            "PYTHONPATH=src python scripts/run_swarm3d_showcase.py --root "
            f"/srv/flybrain-data --duration-s {summary['duration_us'] / 1e6:.0f} "
            "--variant exact --variant stimulus-absent",
            "PYTHONPATH=src python scripts/render_swarm3d_showcase.py "
            "--run RUN/exact --control RUN/stimulus-absent --out "
            "swarm3d-showcase.mp4",
            "Every camera move is a pure function of the recorded state and a clock. The "
            "replay path refuses a world that has ever been stepped, so rendering cannot "
            "advance a simulation. Boundary and method: docs/showcase/SWARM3D.md and "
            "docs/adr/ADR-2026-023-embodied-3d-swarm-showcase.md.",
        ),
        font_key="small",
        leading=21,
    )

    provenance = (
        f"commit {str(summary.get('code_commit') or 'unknown')[:12]}"
        f"{'  (working tree dirty)' if summary.get('worktree_dirty') else ''}   |   "
        f"contract {summary['experiment_id']} {summary['experiment_sha256'][:12]}   |   "
        f"scenario {summary['scenario_id']}   |   seed {summary['seed']}   |   "
        f"kernel {str(summary.get('kernel', {}).get('sha256', 'unknown'))[:12]}   |   "
        f"build key {summary['build_key']}   |   wiring {summary['wiring_digest']}"
    )
    draw.text((120, FRAME_HEIGHT - 58), provenance, font=fonts["tiny"], fill=FAINT)
    return np.asarray(canvas)


def _compose_compare(
    canvas: Any,
    draw: Any,
    fonts: dict[str, Any],
    *,
    replay: SwarmReplay,
    left: RunRecording,
    right: RunRecording,
    shot: Shot,
    u: float,
    trajectories: SwarmTrajectories,
    smoothed: SwarmTrajectories,
    centre: tuple[float, float],
    cursor: int,
    census_by_side: tuple[int, int],
) -> None:
    """The same moment, the same seed, with and without a scene for the encoder to read.

    This is the only panel in the video that makes a comparative claim, and it makes it the
    only way a comparative claim can honestly be made: by running the identical system
    twice and changing one thing.
    """
    from PIL import Image

    half = FRAME_WIDTH // 2
    framing = camera_for(shot, u, trajectories, smoothed=smoothed, scene_centre=centre)
    panels = (
        (left, "exact  -  the flies can see the arena", INK),
        (right, "control  -  identical seed, encoder held at baseline", WARN),
    )
    for index, (recording, label, colour) in enumerate(panels):
        index_cursor = min(cursor, len(recording.poses) - 1)
        panel = replay.render(recording.poses.at(index_cursor), framing)
        canvas.paste(Image.fromarray(panel), (index * half, HEADER_HEIGHT))
        draw.rectangle(
            [
                index * half + 1,
                HEADER_HEIGHT + 1,
                (index + 1) * half - 2,
                HEADER_HEIGHT + 40,
            ],
            fill=(0, 0, 0),
        )
        draw.text(
            (index * half + 20, HEADER_HEIGHT + 10),
            label,
            font=fonts["head"],
            fill=colour,
        )
        outcome = recording.summary["outcome"]
        walked = sum(
            1 for entry in outcome["per_fly"] if entry["locomotion_onset_us"]
        )
        total = recording.summary["batch"]["size"]
        spiking = recording.summary["recording"][
            "mean_active_neurons_per_interval_per_fly"
        ]
        # Over a sunlit ground plane, light text on no background is unreadable. The band
        # is the same black as the panel title's.
        draw.rectangle(
            [
                index * half + 1,
                HEADER_HEIGHT + STAGE_HEIGHT - 62,
                (index + 1) * half - 2,
                HEADER_HEIGHT + STAGE_HEIGHT - 1,
            ],
            fill=(0, 0, 0),
        )
        touching = census_by_side[index]
        draw.text(
            (index * half + 20, HEADER_HEIGHT + STAGE_HEIGHT - 54),
            f"walked  {walked}/{total}      "
            f"ended against an object  {touching}/{total}      "
            f"neurons spiking per interval  {spiking:,.0f}",
            font=fonts["head"],
            fill=colour,
        )
        draw.text(
            (index * half + 20, HEADER_HEIGHT + STAGE_HEIGHT - 28),
            "ended nearer a food object: "
            f"{outcome['flies_that_closed_on_a_food_object']}/{total}, median "
            f"{outcome['median_closed_mm']:+.2f} mm  -  both panels close, and that is "
            "the point",
            font=fonts["small"],
            fill=DIM,
        )
    draw.line(
        [half, HEADER_HEIGHT, half, HEADER_HEIGHT + STAGE_HEIGHT],
        fill=(40, 46, 60),
        width=2,
    )
    band_top = HEADER_HEIGHT + STAGE_HEIGHT
    draw.rectangle([0, band_top, FRAME_WIDTH, band_top + TRACE_HEIGHT], fill=PANEL)
    y = band_top + 22
    for piece in _wrap(draw, shot.caption, fonts["body"], FRAME_WIDTH - 240):
        draw.text((120, y), piece, font=fonts["body"], fill=INK)
        y += 28

__all__ = [
    "GLOW_SPAN_INTERVALS",
    "GRID_COLUMNS",
    "GRID_ROWS",
    "INTERVAL_DECAY",
    "RunRecording",
    "decayed_glow",
    "final_object_census",
    "render_showcase",
]
