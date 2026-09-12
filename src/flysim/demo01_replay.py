# SPDX-License-Identifier: GPL-2.0-or-later
"""Re-render a finished DEMO-01 run's body from its recorded physics state.

The first version of this demonstration rendered the body camera *during* the run, which
meant the camera was frozen into the recording: fixing a shot cost a full re-simulation of
four control variants. It also meant one formula had to serve every moment of the run, and
the formula chosen framed the midpoint between fly and cue at a distance that grew with
their separation. That is exactly backwards. As the fly arrives, the separation goes to
zero, the camera closes in, and a 2.5 mm cue at 5 mm fills the frame while the 3 mm fly
that the video is about slides off the edge. The climax of the run was the one moment you
could not watch.

So the body is no longer rendered during the run. The run records `qpos`, the full
generalised position vector of the MuJoCo model, once per coupling interval. Every joint
angle, the free joint, everything the renderer needs. Rendering then rebuilds the identical
model, writes a recorded `qpos` into it and draws. That is exact rather than approximate:
`qpos` plus the model determines every body frame in the scene, so a replayed frame is the
frame the run would have produced from that state.

Three consequences worth stating.

**Rendering can no longer affect the simulation, structurally rather than by convention.**
The replay path refuses to run on a body that has been stepped, so the only thing that can
be replayed is a body that has never simulated anything.

**Shots can be recut for free.** Everything below is a pure function of the recorded
trajectory and the clock, so a shot list is a few constants rather than a re-run.

**The cue is drawn only when the cue exists.** The previous renderer drew it
unconditionally, so the stimulus-absent control -- the panel whose whole claim is that
there is nothing to see -- showed a cue sitting in front of a fly that could not see it.
The number was never affected; the picture said the opposite of the caption. Here the cue's
visibility is read from the recorded `cue.present` flag.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.demo01_body import Demo01BodyParameters, Demo01VisualBody
from flysim.errors import ConfigurationError, ReadinessError

# --------------------------------------------------------------------------------------
# Appearance
# --------------------------------------------------------------------------------------
#
# The compiled model carries no light source at all (nlight = 0), so the scene is lit
# entirely by MuJoCo's camera-attached headlight and nothing can cast a shadow. That is a
# property of the world this run used, and it is not repaired here by adding a fake contact
# shadow under the fly: an invented shadow is invented light transport, and this project
# does not draw what it did not compute. What is adjusted is only material and lighting
# constants, none of which any solver reads.
#
# The ground was the loudest problem. Its checker repeats 250 times across a 200 mm plane,
# one square every 0.8 mm, against a fly 3 mm long -- fine enough to read as visual noise
# rather than as ground. Coarsening it to one square every 15 mm keeps the motion reference
# that a featureless plane would lose while getting out of the way of the animal.
#
# Colour could not be fixed by tinting, which was the first attempt. Measured, the checker
# texture spans only 76 to 102 out of 255, so it is a dark, nearly flat grey and any tint
# multiplied into it stays dark. The texture is repainted instead, in two close sand tones,
# which is why the ground reads as ground rather than as a physics-engine floor.
GROUND_TEXTURE_REPEAT = 13.0
GROUND_LIGHT_RGB = (232, 224, 206)
GROUND_DARK_RGB = (214, 205, 186)
GROUND_REFLECTANCE = 0.05
# The released skybox is 255 in every channel, a pure white wall behind the animal that
# blows out the top of every low-angle shot. A flat, slightly cool sky sits behind the fly
# instead of competing with it.
SKY_RGB = (198, 212, 232)
HEADLIGHT_AMBIENT = 0.45
HEADLIGHT_DIFFUSE = 0.75
HEADLIGHT_SPECULAR = 0.08


def _checker(height: int, width: int) -> np.ndarray:
    """Two sand tones in a two-by-two block, tiled by the material's repeat count.

    Low contrast on purpose. The ground has to give a moving fly somewhere to move over
    without competing with it for attention.
    """
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    light = np.asarray(GROUND_LIGHT_RGB, dtype=np.uint8)
    dark = np.asarray(GROUND_DARK_RGB, dtype=np.uint8)
    half_h, half_w = height // 2, width // 2
    tile[:half_h, :half_w] = light
    tile[half_h:, half_w:] = light
    tile[:half_h, half_w:] = dark
    tile[half_h:, :half_w] = dark
    return tile


# --------------------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------------------

# Order matters and is not the obvious one. The profile shot comes second, immediately
# after the fly starts walking, because that is the only window in which it is actually
# walking: in the run this was built for, the fly closes 14 mm in about eight seconds and
# then stands at the cue for the remaining ten. A leg shot scheduled late would have shown
# a stationary animal, which is what the first cut of the shot list did.
SHOT_ORDER = ("establish", "profile", "follow", "arrival")

# MuJoCo's default free camera has a 45 degree vertical field, which spans
# 2 * tan(22.5 deg) = 0.828 of the distance to whatever it is aimed at.
MUJOCO_VERTICAL_FIELD_SPAN = 0.828
# No shot may let the cue exceed this fraction of frame height. The demonstration's success
# condition is that the fly closes on a 2.5 mm sphere, so at the end of a successful run it
# is standing within the sphere's own radius -- underneath a ball wider than itself. No
# choice of angle rescues that; only distance does, and it has to be a floor that every
# shot obeys rather than a per-shot constant somebody can forget to set.
CUE_MAX_FRAME_FRACTION = 0.45


@dataclass(frozen=True, slots=True)
class ShotFraming:
    """How one shot places the camera, as constants a test can pin.

    ``lookat_bias`` slides the aim point from the fly toward the cue. It is deliberately
    small everywhere except the establishing shot: the subject of this video is the fly,
    and aiming at the midpoint is what put the cue in the middle of frame and the fly at
    the edge.
    """

    lookat_bias: float
    lookat_lift_mm: float
    distance_base_mm: float
    distance_per_separation: float
    distance_min_mm: float
    distance_max_mm: float
    azimuth_offset_deg: float
    azimuth_drift_deg_per_s: float
    elevation_deg: float


SHOT_FRAMING: dict[str, ShotFraming] = {
    # Wide and high: the arena, the fly and the object it will walk to, all at once, while
    # the opening titles are still on screen.
    "establish": ShotFraming(
        lookat_bias=0.50,
        lookat_lift_mm=1.40,
        distance_base_mm=4.0,
        distance_per_separation=1.05,
        distance_min_mm=11.0,
        distance_max_mm=42.0,
        azimuth_offset_deg=148.0,
        azimuth_drift_deg_per_s=5.0,
        elevation_deg=-32.0,
    ),
    # Side on and almost level, close enough that the legs are the subject. This is the
    # only shot where the gait is legible, and the gait is an engineered pattern generator,
    # which the caption says while it is on screen.
    "profile": ShotFraming(
        lookat_bias=0.0,
        lookat_lift_mm=0.40,
        distance_base_mm=5.2,
        distance_per_separation=0.0,
        distance_min_mm=5.2,
        distance_max_mm=5.2,
        azimuth_offset_deg=246.0,
        azimuth_drift_deg_per_s=0.0,
        elevation_deg=-6.0,
    ),
    # Behind and low, near the animal's own eye height. A turn reads as a turn because the
    # camera turns with the body, and the cue swells in frame as the fly closes on it
    # rather than sitting statically in the middle.
    "follow": ShotFraming(
        lookat_bias=0.18,
        lookat_lift_mm=0.55,
        distance_base_mm=3.2,
        distance_per_separation=0.40,
        distance_min_mm=5.5,
        distance_max_mm=15.0,
        azimuth_offset_deg=152.0,
        azimuth_drift_deg_per_s=0.0,
        elevation_deg=-13.0,
    ),
    # Three-quarter, and raised enough to look over the top of the cue rather than into it.
    # The distance that makes this shot work is not set here: it comes from the cue-size
    # floor, which is the only thing that can frame a fly standing under a sphere.
    "arrival": ShotFraming(
        lookat_bias=0.15,
        lookat_lift_mm=0.35,
        distance_base_mm=3.0,
        distance_per_separation=0.90,
        distance_min_mm=6.5,
        distance_max_mm=12.0,
        azimuth_offset_deg=208.0,
        azimuth_drift_deg_per_s=0.0,
        elevation_deg=-19.0,
    ),
}


@dataclass(frozen=True, slots=True)
class CameraFraming:
    """A resolved camera placement for one frame."""

    shot: str
    lookat_mm: tuple[float, float, float]
    distance_mm: float
    azimuth_deg: float
    elevation_deg: float


@dataclass(frozen=True, slots=True)
class ShotPlan:
    """When each shot runs, derived from the run's own events rather than authored.

    The first cut lands on the moment the decoder first commands locomotion, so the shot
    changes because the fly started walking rather than because a timeline said so. The
    remaining cuts divide what is left in fixed proportions. A variant that never walks
    still gets a plan -- it simply establishes for a moment and then sits on a standing fly,
    which is the honest picture of that control.
    """

    duration_s: float
    establish_until_s: float
    profile_until_s: float
    follow_until_s: float

    PROFILE_SHARE = 0.25
    FOLLOW_SHARE = 0.45

    @classmethod
    def from_recording(
        cls,
        *,
        duration_s: float,
        onset_s: float | None,
        minimum_establish_s: float = 2.5,
    ) -> ShotPlan:
        if duration_s <= 0.0:
            raise ConfigurationError("A shot plan needs a positive duration")
        wanted = minimum_establish_s if onset_s is None else onset_s
        establish = min(max(wanted, 1.5), 0.35 * duration_s)
        remaining = duration_s - establish
        profile = establish + cls.PROFILE_SHARE * remaining
        follow = profile + cls.FOLLOW_SHARE * remaining
        return cls(
            duration_s=duration_s,
            establish_until_s=establish,
            profile_until_s=profile,
            follow_until_s=follow,
        )

    def shot_at(self, t_s: float) -> str:
        if t_s < self.establish_until_s:
            return "establish"
        if t_s < self.profile_until_s:
            return "profile"
        if t_s < self.follow_until_s:
            return "follow"
        return "arrival"

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "cuts_s": [
                round(self.establish_until_s, 3),
                round(self.profile_until_s, 3),
                round(self.follow_until_s, 3),
            ],
            "order": list(SHOT_ORDER),
            "first_cut_is": (
                "the interval in which the decoder first commanded locomotion, so the shot "
                "changes because the fly moved"
            ),
        }


def frame_camera(
    shot: str,
    *,
    fly_xyz_mm: tuple[float, float, float],
    heading_rad: float,
    cue_xy_mm: tuple[float, float],
    cue_height_mm: float,
    cue_radius_mm: float,
    cue_present: bool,
    t_s: float,
) -> CameraFraming:
    """Resolve one shot into a camera placement. Pure: no model, no renderer, no state.

    When there is no cue the aim point collapses onto the fly and the separation term goes
    to zero, so the stimulus-absent control gets a clean, close shot of a standing animal
    rather than a camera drifting toward an object that is not there.
    """
    try:
        framing = SHOT_FRAMING[shot]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown shot {shot!r}; expected one of {SHOT_ORDER}") from exc
    fly_x, fly_y, fly_z = fly_xyz_mm
    target_x, target_y = (cue_xy_mm if cue_present else (fly_x, fly_y))
    separation = math.hypot(target_x - fly_x, target_y - fly_y)
    distance = (
        framing.distance_base_mm + framing.distance_per_separation * separation
    )
    distance = min(framing.distance_max_mm, max(framing.distance_min_mm, distance))
    if cue_present:
        # The floor that keeps a 5 mm sphere from becoming the whole frame when the fly is
        # standing under it. The camera sits behind the fly looking past it at the cue, so
        # the camera-to-cue distance is about the shot distance plus the separation, and
        # the requirement is on that sum. This overrides the per-shot maximum on purpose:
        # a shot that cannot show its own subject is not a shot.
        widest = 2.0 * cue_radius_mm / (
            CUE_MAX_FRAME_FRACTION * MUJOCO_VERTICAL_FIELD_SPAN
        )
        distance = max(distance, widest - separation)
    lift = framing.lookat_lift_mm
    aim_z = fly_z + lift
    if cue_present and framing.lookat_bias > 0.0:
        aim_z = (1.0 - framing.lookat_bias) * (fly_z + lift) + framing.lookat_bias * max(
            fly_z + lift, cue_height_mm
        )
    return CameraFraming(
        shot=shot,
        lookat_mm=(
            fly_x + framing.lookat_bias * (target_x - fly_x),
            fly_y + framing.lookat_bias * (target_y - fly_y),
            aim_z,
        ),
        distance_mm=distance,
        azimuth_deg=(
            math.degrees(heading_rad)
            + framing.azimuth_offset_deg
            + framing.azimuth_drift_deg_per_s * t_s
        ),
        elevation_deg=framing.elevation_deg,
    )


def smooth_track(
    x_mm: np.ndarray,
    y_mm: np.ndarray,
    z_mm: np.ndarray,
    heading_rad: np.ndarray,
    *,
    window: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Low-pass the trajectory the *camera* follows, never the trajectory that is measured.

    A walking fly pitches and yaws with every step, and a camera bolted rigidly to that
    signal shakes. Smoothing only the camera track leaves every recorded number untouched:
    the trajectory inset, the displacement and the acceptance contract all read the raw
    poses. This is a display filter and is declared as one on the frame.

    Heading is unwrapped before smoothing, because averaging across the wrap from +pi to
    -pi would swing the camera through half a turn.
    """
    if window <= 1:
        return (
            np.asarray(x_mm, dtype=np.float64),
            np.asarray(y_mm, dtype=np.float64),
            np.asarray(z_mm, dtype=np.float64),
            np.asarray(heading_rad, dtype=np.float64),
        )
    smoothed = [_moving_average(values, window) for values in (x_mm, y_mm, z_mm)]
    unwrapped = np.unwrap(np.asarray(heading_rad, dtype=np.float64))
    heading = _moving_average(unwrapped, window)
    return smoothed[0], smoothed[1], smoothed[2], heading


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or window <= 1:
        return array
    half = max(1, window // 2)
    padded = np.pad(array, half, mode="edge")
    kernel = np.ones(2 * half + 1, dtype=np.float64) / float(2 * half + 1)
    return np.convolve(padded, kernel, mode="valid")[: array.size]


# --------------------------------------------------------------------------------------
# The recorded physics state
# --------------------------------------------------------------------------------------


class PoseRecording:
    """The per-interval ``qpos`` written by a run, read back for rendering."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise ReadinessError(f"Pose recording is missing: {path}")
        payload = np.load(path)
        self.qpos = np.asarray(payload["qpos"], dtype=np.float64)
        self.t_us = np.asarray(payload["t_us"], dtype=np.int64)
        if self.qpos.ndim != 2 or self.qpos.shape[0] != self.t_us.size:
            raise ConfigurationError(
                f"Pose recording is malformed: qpos {self.qpos.shape} against "
                f"{self.t_us.size} timestamps"
            )
        self.intervals = int(self.t_us.size)

    def __len__(self) -> int:
        return self.intervals

    def at(self, index: int) -> np.ndarray:
        state: np.ndarray = self.qpos[min(max(index, 0), self.intervals - 1)]
        return state


# --------------------------------------------------------------------------------------
# The replay renderer
# --------------------------------------------------------------------------------------


class BodyReplay:
    """Rebuilds the run's model and draws recorded states through an arbitrary camera.

    The model is constructed from the run's own recorded body parameters, with one change:
    the station-keeping settle window is switched off. That window exists to charge a
    controller integral before a run starts, and this object never runs anything -- it
    overwrites the full state on every frame -- so the four thousand physics steps it costs
    would change nothing except the time to render.
    """

    def __init__(
        self,
        parameters: Demo01BodyParameters,
        *,
        seed: int,
        resolution: tuple[int, int],
        appearance: bool = True,
    ) -> None:
        self._body = Demo01VisualBody(
            replace(parameters, station_keeping_settle_us=0),
            seed=seed,
            camera_resolution=resolution,
        )
        self.parameters = parameters
        if appearance:
            self._apply_appearance()

    def _paint_texture(self, index: int, pixels: np.ndarray) -> None:
        """Overwrite one texture's bytes. Textures are read by the visualiser alone."""
        model = self._body.render_model
        height = int(model.tex_height[index])
        width = int(model.tex_width[index])
        channels = (
            int(model.tex_nchannel[index]) if hasattr(model, "tex_nchannel") else 3
        )
        start = int(model.tex_adr[index])
        tile = np.zeros((height, width, channels), dtype=np.uint8)
        tile[..., : min(3, channels)] = pixels[..., : min(3, channels)]
        if channels > 3:
            tile[..., 3:] = 255
        model.tex_data[start : start + tile.size] = tile.reshape(-1)

    def _apply_appearance(self) -> None:
        """Material, texture and lighting constants only. No solver reads any of these."""
        mujoco = self._body.mujoco
        model = self._body.render_model

        for index in range(int(model.ntex)):
            if int(model.tex_type[index]) == mujoco.mjtTexture.mjTEXTURE_SKYBOX:
                height = int(model.tex_height[index])
                width = int(model.tex_width[index])
                sky = np.tile(
                    np.asarray(SKY_RGB, dtype=np.uint8), (height, width, 1)
                )
                self._paint_texture(index, sky)

        for geom in range(int(model.ngeom)):
            if model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_PLANE:
                continue
            material = int(model.geom_matid[geom])
            if material < 0:
                model.geom_rgba[geom] = np.asarray(
                    [c / 255.0 for c in GROUND_LIGHT_RGB] + [1.0],
                    dtype=model.geom_rgba.dtype,
                )
                continue
            model.mat_texrepeat[material] = np.asarray(
                [GROUND_TEXTURE_REPEAT, GROUND_TEXTURE_REPEAT],
                dtype=model.mat_texrepeat.dtype,
            )
            # White, so the repainted texture arrives at the screen as it was written.
            model.mat_rgba[material] = np.asarray(
                [1.0, 1.0, 1.0, 1.0], dtype=model.mat_rgba.dtype
            )
            model.mat_reflectance[material] = GROUND_REFLECTANCE
            for texture in np.asarray(model.mat_texid[material]).ravel():
                if int(texture) < 0:
                    continue
                height = int(model.tex_height[int(texture)])
                width = int(model.tex_width[int(texture)])
                self._paint_texture(int(texture), _checker(height, width))

        model.vis.headlight.ambient[:] = HEADLIGHT_AMBIENT
        model.vis.headlight.diffuse[:] = HEADLIGHT_DIFFUSE
        model.vis.headlight.specular[:] = HEADLIGHT_SPECULAR

    def render(
        self,
        qpos: np.ndarray,
        framing: CameraFraming,
        *,
        cue_visible: bool,
        cue_rgba: tuple[float, float, float, float] | None = None,
        cue_core_radius_mm: float | None = None,
        cue_core_rgba: tuple[float, float, float, float] = (0.90, 0.10, 0.05, 1.0),
    ) -> np.ndarray:
        kwargs: dict[str, Any] = {
            "framing": framing,
            "cue_visible": cue_visible,
            "cue_core_radius_mm": cue_core_radius_mm,
            "cue_core_rgba": cue_core_rgba,
        }
        if cue_rgba is not None:
            kwargs["cue_rgba"] = cue_rgba
        return self._body.render_replay_frame(qpos, **kwargs)

    def close(self) -> None:
        self._body.close()

    def __enter__(self) -> BodyReplay:
        return self

    def __exit__(self, *exception: Any) -> None:
        self.close()


__all__ = [
    "CUE_MAX_FRAME_FRACTION",
    "GROUND_TEXTURE_REPEAT",
    "SHOT_FRAMING",
    "SHOT_ORDER",
    "BodyReplay",
    "CameraFraming",
    "PoseRecording",
    "ShotFraming",
    "ShotPlan",
    "frame_camera",
    "smooth_track",
]
