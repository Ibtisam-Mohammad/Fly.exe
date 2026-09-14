# SPDX-License-Identifier: GPL-2.0-or-later
"""Re-render a finished swarm run's scene from its recorded physics state.

The run records the whole scene's `qpos` once per coupling interval and no frames at all.
Rendering rebuilds the identical world, writes a recorded `qpos` into it and draws. That is
exact rather than approximate: `qpos` plus the model determines every body frame in the
scene, so a replayed frame is the frame the run would have produced from that state.

Two consequences that are worth having.

**Rendering cannot affect the simulation, structurally rather than by convention.** The
replay path refuses to run on a world that has been stepped, so the only thing that can be
replayed is a world that has never simulated anything.

**Shots are free.** Everything below is a pure function of the recorded trajectories and a
clock, so re-cutting the video is a few constants rather than a forty-minute re-run. This
is what lets the shot list be chosen after seeing what the flies actually did, which is the
only honest order to choose it in: the alternative is picking a camera first and then
needing the animals to cooperate.

The timeline is a list of shots. Each one owns its own mapping from video time to simulated
time, so a shot can run at real speed, at a quarter speed for a close-up, or revisit an
earlier moment from a different angle, without anything downstream needing to know.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.errors import ConfigurationError, ReadinessError
from flysim.swarm3d import (
    SwarmArenaParameters,
    SwarmFlySpec,
    SwarmObject,
    SwarmWorld,
)

# MuJoCo's default free camera has a 45 degree vertical field, which spans
# 2 * tan(22.5 deg) = 0.828 of the distance to whatever it is aimed at.
MUJOCO_VERTICAL_FIELD_SPAN = 0.828
# A NeuroMechFly is about 3 mm long. Closer than this and the near clip plane starts eating
# the animal; there is no shot worth that.
MINIMUM_CAMERA_DISTANCE_MM = 4.5


# --------------------------------------------------------------------------------------
# Reading a recording
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwarmTrajectories:
    """Per-fly position and heading at every recorded interval, plus the clock."""

    fly_ids: tuple[str, ...]
    labels: tuple[str, ...]
    t_us: np.ndarray
    x_mm: np.ndarray
    y_mm: np.ndarray
    z_mm: np.ndarray
    heading_rad: np.ndarray
    rows: tuple[dict[str, Any], ...]

    @property
    def intervals(self) -> int:
        return int(self.t_us.size)

    @property
    def duration_s(self) -> float:
        return float(self.t_us[-1]) / 1e6 if self.t_us.size else 0.0

    def index_at(self, sim_t_s: float) -> int:
        """Which recorded interval a wall-clock instant falls in. Clamped at both ends."""
        if self.t_us.size == 0:
            raise ReadinessError("The recording holds no intervals")
        target = sim_t_s * 1e6
        index = int(np.searchsorted(self.t_us, target, side="left"))
        return max(0, min(self.intervals - 1, index))

    def smoothed(self, window: int) -> SwarmTrajectories:
        """A copy whose positions are moving-averaged, for camera tracking only.

        The camera has to be smooth and a walking fly is not: a tripod gait moves the
        thorax a few tenths of a millimetre sideways twice a step, which a following camera
        turns into a shake that reads as a rendering fault. Only the camera reads this; the
        drawn body always comes from the unsmoothed recorded state.
        """
        if window <= 1:
            return self
        return replace(
            self,
            x_mm=_moving_average(self.x_mm, window),
            y_mm=_moving_average(self.y_mm, window),
            z_mm=_moving_average(self.z_mm, window),
            heading_rad=_unwrap_smooth(self.heading_rad, window),
        )


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or values.shape[0] < 2:
        return values
    kernel = np.ones(window, dtype=np.float64) / window
    out = np.empty_like(values)
    for column in range(values.shape[1]):
        padded = np.pad(values[:, column], (window // 2, window - 1 - window // 2), mode="edge")
        out[:, column] = np.convolve(padded, kernel, mode="valid")
    return out


def _unwrap_smooth(headings: np.ndarray, window: int) -> np.ndarray:
    """Smooth an angle without letting the pi/-pi seam throw the average across the circle."""
    if window <= 1 or headings.shape[0] < 2:
        return headings
    unwrapped = np.unwrap(headings, axis=0)
    return _moving_average(unwrapped, window)


def load_trace(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise ReadinessError(f"Trace is empty: {path}")
    return tuple(rows)


def read_trajectories(
    trace_path: Path, *, labels: dict[str, str] | None = None
) -> SwarmTrajectories:
    rows = load_trace(trace_path)
    fly_ids = tuple(entry["fly_id"] for entry in rows[0]["flies"])
    count = len(fly_ids)
    intervals = len(rows)
    t_us = np.empty(intervals, dtype=np.int64)
    x = np.empty((intervals, count), dtype=np.float64)
    y = np.empty((intervals, count), dtype=np.float64)
    z = np.empty((intervals, count), dtype=np.float64)
    heading = np.empty((intervals, count), dtype=np.float64)
    for step, row in enumerate(rows):
        t_us[step] = int(row["t_us"])
        for index, entry in enumerate(row["flies"]):
            pose = entry["pose"]
            x[step, index] = pose["x_mm"]
            y[step, index] = pose["y_mm"]
            z[step, index] = pose["z_mm"]
            heading[step, index] = pose["heading_rad"]
    named = labels or {}
    return SwarmTrajectories(
        fly_ids=fly_ids,
        labels=tuple(named.get(fly_id, fly_id) for fly_id in fly_ids),
        t_us=t_us,
        x_mm=x,
        y_mm=y,
        z_mm=z,
        heading_rad=heading,
        rows=rows,
    )


class PoseRecording:
    """The whole scene's recorded `qpos`, one row per coupling interval."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise ReadinessError(f"Recorded poses are missing: {path}")
        payload = np.load(path)
        self.qpos = np.asarray(payload["qpos"], dtype=np.float64)
        self.t_us = np.asarray(payload["t_us"], dtype=np.int64)
        if self.qpos.ndim != 2 or self.qpos.shape[0] == 0:
            raise ReadinessError(f"{path} holds no recorded physics state")

    def __len__(self) -> int:
        return int(self.qpos.shape[0])

    def at(self, index: int) -> np.ndarray:
        if not 0 <= index < len(self):
            raise ConfigurationError(
                f"Pose index {index} is outside the recorded range 0..{len(self) - 1}"
            )
        state: np.ndarray = self.qpos[index]
        return state


# --------------------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CameraFraming:
    lookat_mm: tuple[float, float, float]
    distance_mm: float
    azimuth_deg: float
    elevation_deg: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "lookat_mm": list(self.lookat_mm),
            "distance_mm": self.distance_mm,
            "azimuth_deg": self.azimuth_deg,
            "elevation_deg": self.elevation_deg,
        }


@dataclass(frozen=True, slots=True)
class Shot:
    """One continuous camera move over one stretch of recorded time.

    `sim_rate` is simulated seconds per video second: 1.0 plays the recording at the speed
    it was simulated, 0.25 is a quarter-speed close-up, and the value reaches the screen as
    a caption so that a slowed shot is never mistaken for a slow animal.
    """

    name: str
    caption: str
    video_seconds: float
    sim_start_s: float
    sim_rate: float = 1.0
    mode: str = "orbit"
    subject: str | None = None
    partner: str | None = None
    azimuth_start_deg: float = 45.0
    azimuth_end_deg: float = 45.0
    elevation_start_deg: float = -25.0
    elevation_end_deg: float = -25.0
    distance_start_mm: float = 90.0
    distance_end_mm: float = 90.0
    lookat_mm: tuple[float, float, float] | None = None
    lookat_z_mm: float = 1.6
    smoothing_intervals: int = 27

    def __post_init__(self) -> None:
        if self.video_seconds <= 0.0:
            raise ConfigurationError(f"Shot {self.name!r} needs a positive duration")
        if self.mode not in {"orbit", "follow", "pair", "top"}:
            raise ConfigurationError(f"Shot {self.name!r} has unknown mode {self.mode!r}")
        if self.mode in {"follow", "pair"} and not self.subject:
            raise ConfigurationError(f"Shot {self.name!r} names no subject")

    def sim_time(self, u: float) -> float:
        return self.sim_start_s + u * self.video_seconds * self.sim_rate

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "caption": self.caption,
            "video_seconds": self.video_seconds,
            "sim_start_s": self.sim_start_s,
            "sim_rate": self.sim_rate,
            "mode": self.mode,
            "subject": self.subject,
            "partner": self.partner,
        }


def _ease(u: float) -> float:
    """Smoothstep. Linear camera moves start and stop with a visible jerk."""
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


def camera_for(
    shot: Shot,
    u: float,
    trajectories: SwarmTrajectories,
    *,
    smoothed: SwarmTrajectories | None = None,
    scene_centre: tuple[float, float] = (0.0, 0.0),
) -> CameraFraming:
    """Where the camera is at fraction `u` through one shot."""
    track = smoothed if smoothed is not None else trajectories
    eased = _ease(u)
    distance = (
        shot.distance_start_mm
        + (shot.distance_end_mm - shot.distance_start_mm) * eased
    )
    elevation = (
        shot.elevation_start_deg
        + (shot.elevation_end_deg - shot.elevation_start_deg) * eased
    )
    azimuth = (
        shot.azimuth_start_deg + (shot.azimuth_end_deg - shot.azimuth_start_deg) * eased
    )
    index = track.index_at(shot.sim_time(u))

    if shot.mode == "orbit" or shot.mode == "top":
        lookat = shot.lookat_mm or (scene_centre[0], scene_centre[1], shot.lookat_z_mm)
    elif shot.mode == "follow":
        slot = trajectories.fly_ids.index(shot.subject or "")
        lookat = (
            float(track.x_mm[index, slot]),
            float(track.y_mm[index, slot]),
            shot.lookat_z_mm,
        )
        # Sit behind and to one side of the animal, so a turn is a turn on screen rather
        # than the world rotating around a fly that stays pointing at the lens.
        heading_deg = math.degrees(float(track.heading_rad[index, slot]))
        azimuth = heading_deg + 180.0 + (
            shot.azimuth_start_deg
            + (shot.azimuth_end_deg - shot.azimuth_start_deg) * eased
        )
    elif shot.mode == "pair":
        slot = trajectories.fly_ids.index(shot.subject or "")
        if shot.partner and shot.partner in trajectories.fly_ids:
            other = trajectories.fly_ids.index(shot.partner)
            centre_x = 0.5 * (track.x_mm[index, slot] + track.x_mm[index, other])
            centre_y = 0.5 * (track.y_mm[index, slot] + track.y_mm[index, other])
            separation = float(
                np.hypot(
                    track.x_mm[index, slot] - track.x_mm[index, other],
                    track.y_mm[index, slot] - track.y_mm[index, other],
                )
            )
            # Keep both in frame: the separation has to fit inside the vertical field.
            distance = max(distance, separation / MUJOCO_VERTICAL_FIELD_SPAN * 1.6)
        else:
            centre_x = float(track.x_mm[index, slot])
            centre_y = float(track.y_mm[index, slot])
        lookat = (float(centre_x), float(centre_y), shot.lookat_z_mm)
    else:  # pragma: no cover -- __post_init__ rejects anything else
        raise ConfigurationError(f"Unknown shot mode {shot.mode!r}")

    return CameraFraming(
        lookat_mm=(float(lookat[0]), float(lookat[1]), float(lookat[2])),
        distance_mm=max(MINIMUM_CAMERA_DISTANCE_MM, float(distance)),
        azimuth_deg=float(azimuth),
        elevation_deg=float(elevation),
    )



def clearest_azimuth_offset(
    trajectories: SwarmTrajectories,
    *,
    subject: str,
    sim_start_s: float,
    sim_end_s: float,
    distance_mm: float,
    elevation_deg: float,
    obstacles: Sequence[tuple[float, float, float]] = (),
    candidates: Sequence[float] = tuple(range(-180, 180, 10)),
    samples: int = 9,
    smoothed: SwarmTrajectories | None = None,
) -> tuple[float, float]:
    """The azimuth offset that keeps other flies furthest off the camera-to-subject line.

    Returns the offset in degrees and the clearance it achieves, in millimetres. Clearance
    is the smallest perpendicular distance from any non-subject fly to the segment joining
    camera and subject, counting only flies that lie between the two, and floored by how
    close any fly comes to the lens itself.

    `obstacles` are static (x, y, radius) triples -- the food spheres and pillars. They
    have to be scored as well as the flies: a 4 mm food sphere between lens and subject
    hides the animal completely, which is what the first v3 cut did to its close-up.

    This chooses where to stand. It cannot choose what the animals did, which is already
    recorded, and the manifest records the offset it picked.
    """
    track = smoothed if smoothed is not None else trajectories
    slot = trajectories.fly_ids.index(subject)
    others = [index for index in range(len(trajectories.fly_ids)) if index != slot]
    if not others:
        return 0.0, float("inf")
    times = [
        sim_start_s + (sim_end_s - sim_start_s) * step / max(1, samples - 1)
        for step in range(samples)
    ]
    elevation = math.radians(elevation_deg)
    best_offset, best_clearance = float(candidates[0]), -1e9
    for offset in candidates:
        per_sample: list[float] = []
        for when in times:
            clearance = float("inf")
            index = track.index_at(when)
            target = np.array(
                [
                    float(track.x_mm[index, slot]),
                    float(track.y_mm[index, slot]),
                ]
            )
            azimuth = math.radians(
                math.degrees(float(track.heading_rad[index, slot])) + 180.0 + offset
            )
            reach = distance_mm * math.cos(elevation)
            camera = target - np.array(
                [reach * math.cos(azimuth), reach * math.sin(azimuth)]
            )
            axis = target - camera
            length = float(np.hypot(*axis))
            if length <= 1e-9:
                continue
            unit = axis / length
            blockers: list[tuple[np.ndarray, float]] = [
                (
                    np.array(
                        [
                            float(trajectories.x_mm[index, other]),
                            float(trajectories.y_mm[index, other]),
                        ]
                    ),
                    0.0,
                )
                for other in others
            ]
            blockers.extend(
                (np.array([x, y]), radius) for x, y, radius in obstacles
            )
            for point, radius in blockers:
                along = float(np.dot(point - camera, unit))
                to_lens = float(np.hypot(*(point - camera))) - radius
                # Something beside or behind the camera does not block the shot, but one
                # nearly touching the lens does whatever direction it is in.
                if along < 0.0 or along > length:
                    clearance = min(clearance, to_lens)
                    continue
                perpendicular = (
                    float(np.hypot(*(point - camera - along * unit))) - radius
                )
                clearance = min(clearance, perpendicular, to_lens)
            per_sample.append(clearance)
        # The median, not the minimum. A subject that walks to a food sphere is beside it
        # for the last second of any shot, and scoring on the worst instant would condemn
        # every angle equally and pick the first one.
        score = float(np.median(per_sample)) if per_sample else float("inf")
        if score > best_clearance:
            best_offset, best_clearance = float(offset), score
    return best_offset, best_clearance

@dataclass(frozen=True, slots=True)
class Timeline:
    """The shot list, and the arithmetic that turns a video frame into a shot and a time."""

    shots: tuple[Shot, ...]

    def __post_init__(self) -> None:
        if not self.shots:
            raise ConfigurationError("A timeline needs at least one shot")

    @property
    def video_seconds(self) -> float:
        return float(sum(shot.video_seconds for shot in self.shots))

    def frame_count(self, fps: int) -> int:
        return round(self.video_seconds * fps)

    def at(self, video_t_s: float) -> tuple[Shot, float]:
        elapsed = 0.0
        for shot in self.shots:
            last = shot is self.shots[-1]
            if last or video_t_s < elapsed + shot.video_seconds:
                span = shot.video_seconds
                return shot, min(1.0, max(0.0, (video_t_s - elapsed) / span))
            elapsed += shot.video_seconds
        raise ConfigurationError("Timeline lookup fell off the end")  # pragma: no cover

    def as_dict(self) -> dict[str, Any]:
        return {
            "video_seconds": self.video_seconds,
            "shots": [shot.as_dict() for shot in self.shots],
        }


# --------------------------------------------------------------------------------------
# The replay world
# --------------------------------------------------------------------------------------


class SwarmReplay:
    """Rebuilds the run's scene and draws recorded states through an arbitrary camera.

    The world is constructed from the run's own recorded scenario, with one change: the
    station-keeping settle window is switched off. That window exists to charge a
    controller integral before a run starts, and this object never runs anything -- it
    overwrites the full state on every frame -- so the four thousand physics steps it costs
    would change nothing except the time to render.
    """

    def __init__(
        self,
        arena: SwarmArenaParameters,
        flies: Sequence[SwarmFlySpec],
        objects: Sequence[SwarmObject],
        *,
        seed: int,
        resolution: tuple[int, int],
    ) -> None:
        self._world = SwarmWorld(
            replace(arena, station_keeping_settle_us=0),
            tuple(flies),
            tuple(objects),
            seed=seed,
            camera_resolution=resolution,
            appearance=True,
            lighting=True,
        )
        self.arena = arena
        self.flies = tuple(flies)
        self.objects = tuple(objects)

    @property
    def world(self) -> SwarmWorld:
        return self._world

    def render(
        self,
        qpos: np.ndarray,
        framing: CameraFraming,
        *,
        decorations: Sequence[dict[str, Any]] = (),
    ) -> np.ndarray:
        return self._world.render_replay_frame(
            qpos,
            lookat_mm=framing.lookat_mm,
            distance_mm=framing.distance_mm,
            azimuth_deg=framing.azimuth_deg,
            elevation_deg=framing.elevation_deg,
            decorations=tuple(decorations),
        )

    def close(self) -> None:
        self._world.close()

    def __enter__(self) -> SwarmReplay:
        return self

    def __exit__(self, *exception: Any) -> None:
        self.close()


__all__ = [
    "MINIMUM_CAMERA_DISTANCE_MM",
    "MUJOCO_VERTICAL_FIELD_SPAN",
    "CameraFraming",
    "PoseRecording",
    "Shot",
    "SwarmReplay",
    "SwarmTrajectories",
    "Timeline",
    "camera_for",
    "clearest_azimuth_offset",
    "load_trace",
    "read_trajectories",
]
