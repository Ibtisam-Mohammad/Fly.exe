# SPDX-License-Identifier: GPL-2.0-or-later
"""Render a DEMO-02 control matrix as one synchronised comparison.

**The subject is the control matrix, not the fly.** A single panel of the exact escape run
shows a fly leaping and tumbling, and every viewer reads that as a dramatic escape. It is a
fly hopping 1.5 mm and then falling onto its back in a world with no air. Four panels on one
clock cannot be misread that way: the thing happens, it stops happening when either cause is
removed, and the wings are what wreck it.

Three overlay decisions are corrections to numbers that are true and misleading.

**Roll is on every panel and turns red past 90 degrees.** The exact run ends at 179.4
degrees. Without this the flip reads as flight.

**The airborne clock is split.** "2,216,000 us airborne" is true and is mostly a fly lying on
its back with no tarsus touching. It is shown as off-ground time and inverted time
separately, computed from the recorded roll rather than asserted.

**The word loom does not appear.** Criterion E4 struck it: the object fires the giant fibre
in the matched-size-static case too, because the frozen encoder computes angular size and
not expansion rate.

Rendering is separated from simulation by construction (ADR-2026-015): the run recorded
``qpos`` and no video, and this rebuilds the identical plant and writes recorded state into
it. ``qpos`` is 133 wide whatever the actuated joint set is, so the recording's actuator-set
digest is checked before a frame is drawn.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.behaviour_body import SCAFFOLDS, BehaviourBody, BehaviourBodyParameters
from flysim.demo01_replay import (
    GROUND_REFLECTANCE,
    GROUND_TEXTURE_REPEAT,
    HEADLIGHT_AMBIENT,
    HEADLIGHT_DIFFUSE,
    HEADLIGHT_SPECULAR,
    SKY_RGB,
    _checker,
)
from flysim.errors import ConfigurationError

INVERTED_ROLL_DEG = 90.0

#: Words that may not appear on a frame, and what to say instead. Enforced rather than
#: remembered: `_forbid` raises if a caption carries one.
FORBIDDEN_WORDS = {
    "loom": "a visual object of sufficient angular size",
    "looming": "a visual object of sufficient angular size",
    "flight": "a ballistic hop",
    "flying": "a ballistic hop",
    "lift": "no aerodynamic force is computed",
}


def _forbid(text: str) -> str:
    lowered = text.lower()
    for word, instead in FORBIDDEN_WORDS.items():
        if f" {word} " in f" {lowered} " or lowered.startswith(f"{word} "):
            raise ConfigurationError(
                f"Caption contains {word!r}, which the contract struck. Say "
                f"{instead!r} instead: {text!r}"
            )
    return text


@dataclass(frozen=True, slots=True)
class PanelSpec:
    """One variant, its label, and the one sentence a viewer needs about it."""

    variant: str
    title: str
    note: str


#: The escape comparison. Top row is the result, bottom row is why it is a result.
ESCAPE_PANELS = (
    PanelSpec("exact", "EXACT", "brain intact, object present"),
    PanelSpec("jump-only", "JUMP ONLY", "wing command silenced"),
    PanelSpec("readout-ablated", "READOUT ABLATED", "giant fibre silenced"),
    PanelSpec("stimulus-absent", "NO OBJECT", "nothing to see"),
)

#: The effector decomposition, which is where the zero-lift prediction is visible.
EFFECTOR_PANELS = (
    PanelSpec("exact", "JUMP + WINGS", "both effectors"),
    PanelSpec("jump-only", "JUMP ONLY", "legs alone"),
    PanelSpec("wing-only", "WINGS ONLY", "wings alone: predicted 0.0 mm"),
)


@dataclass(frozen=True, slots=True)
class Framing:
    lookat_mm: tuple[float, float, float]
    distance_mm: float
    azimuth_deg: float
    elevation_deg: float


class PanelReplay:
    """Rebuilds one recorded plant and draws frames from recorded qpos."""

    def __init__(
        self,
        directory: Path,
        *,
        resolution: tuple[int, int],
        trajectory_path: Path | None = None,
    ) -> None:
        self.directory = directory
        self.summary = json.loads(
            (directory / "summary.json").read_text(encoding="utf-8")
        )
        self.rows = [
            json.loads(line)
            for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        poses = np.load(directory / "poses.npz")
        self.qpos = poses["qpos"]
        self.t_us = poses["t_us"]
        body_spec = self.summary["body"]
        self._body = BehaviourBody(
            parameters=replace(
                BehaviourBodyParameters.from_mapping(body_spec["parameters"]),
                station_keeping_settle_us=0,
            ),
            behaviour=self.summary["behaviour"],
            seed=int(self.summary["seed"]),
            trajectory_path=trajectory_path,
            camera_resolution=resolution,
        )
        digest = body_spec.get("actuator_set_digest")
        if digest and self._body.actuator_set_digest != digest:
            raise ConfigurationError(
                f"{directory.name} was recorded on actuator set {digest[:12]} and the "
                f"rebuilt plant is {self._body.actuator_set_digest[:12]}. qpos is 133 wide "
                "either way, so this would render correctly and be the wrong body."
            )
        self._mujoco = self._body._mujoco
        self._sim = self._body._simulation
        self._resolution = resolution
        self._renderer: Any | None = None
        self._paint()

    # -- appearance, matched to DEMO-01 so the two videos are comparable ------------

    def _paint_texture(self, index: int, pixels: np.ndarray) -> None:
        """Overwrite one texture's bytes, respecting its channel count.

        Building the tile at the texture's own channel count rather than assuming three
        is the whole trick: a four-channel texture needs an alpha plane or the write is
        the wrong length. Same arithmetic as DEMO-01's renderer.
        """
        model = self._sim.mj_model
        height = int(model.tex_height[index])
        width = int(model.tex_width[index])
        channels = (
            int(model.tex_nchannel[index]) if hasattr(model, "tex_nchannel") else 3
        )
        tile = np.zeros((height, width, channels), dtype=np.uint8)
        tile[..., : min(3, channels)] = pixels[..., : min(3, channels)]
        if channels > 3:
            tile[..., 3:] = 255
        start = int(model.tex_adr[index])
        model.tex_data[start : start + tile.size] = tile.reshape(-1)

    def _paint(self) -> None:
        """Material, texture and lighting constants only. No solver reads any of these."""
        mujoco = self._mujoco
        model = self._sim.mj_model
        for index in range(int(model.ntex)):
            height = int(model.tex_height[index])
            width = int(model.tex_width[index])
            if int(model.tex_type[index]) == mujoco.mjtTexture.mjTEXTURE_SKYBOX:
                self._paint_texture(
                    index,
                    np.tile(np.asarray(SKY_RGB, dtype=np.uint8), (height, width, 1)),
                )
            else:
                self._paint_texture(index, _checker(height, width))
        for material in range(int(model.nmat)):
            model.mat_texrepeat[material] = GROUND_TEXTURE_REPEAT
            model.mat_reflectance[material] = GROUND_REFLECTANCE
        model.vis.headlight.ambient[:] = HEADLIGHT_AMBIENT
        model.vis.headlight.diffuse[:] = HEADLIGHT_DIFFUSE
        model.vis.headlight.specular[:] = HEADLIGHT_SPECULAR

    # -- per-frame quantities, all read from the recording -------------------------

    def roll_deg(self, index: int) -> float:
        row = self.rows[min(index, len(self.rows) - 1)]
        return abs(
            math.degrees(
                float(row.get("sensors", {}).get("world:gravity-in-body-frame:roll", 0.0))
            )
        )

    def inverted(self, index: int) -> bool:
        return self.roll_deg(index) > INVERTED_ROLL_DEG

    def airborne(self, index: int) -> bool:
        row = self.rows[min(index, len(self.rows) - 1)]
        contacts = [
            float(value)
            for name, value in row.get("sensors", {}).items()
            if name.startswith("world:leg-contact:")
        ]
        return bool(contacts) and not any(contacts)

    def giant_fibre_spikes(self, index: int) -> int:
        row = self.rows[min(index, len(self.rows) - 1)]
        counts = row.get("readout_raw_counts", {})
        return sum(
            int(counts.get(name, 0))
            for name in ("giant-fibre-left", "giant-fibre-right")
        )

    def state(self, index: int) -> str:
        row = self.rows[min(index, len(self.rows) - 1)]
        return str(row.get("command", {}).get("state", "QUIESCENT"))

    def z_mm(self, index: int) -> float:
        return float(self.rows[min(index, len(self.rows) - 1)]["pose"]["z_mm"])

    def angular_radius_deg(self, index: int) -> float:
        row = self.rows[min(index, len(self.rows) - 1)]
        return float((row.get("scene") or {}).get("angular_radius_deg", 0.0))

    def split_airborne_us(self) -> tuple[int, int]:
        """Off-ground time, and how much of it is spent inverted.

        The recording reports 2,216,000 us airborne for the exact run. Most of that is a
        fly on its back, because every airborne test here is "no tarsus touching".
        """
        step = int(self.t_us[1] - self.t_us[0]) if len(self.t_us) > 1 else 15_000
        off = sum(1 for i in range(len(self.rows)) if self.airborne(i))
        upside = sum(
            1 for i in range(len(self.rows)) if self.airborne(i) and self.inverted(i)
        )
        return off * step, upside * step

    # -- drawing -------------------------------------------------------------------

    def render(self, index: int, framing: Framing) -> np.ndarray:
        mujoco = self._mujoco
        data = self._sim.mj_data
        state = np.asarray(self.qpos[min(index, len(self.qpos) - 1)], dtype=np.float64)
        if state.shape != data.qpos.shape:
            raise ConfigurationError(
                f"Recorded qpos is {state.shape}, this plant needs {data.qpos.shape}"
            )
        data.qpos[:] = state
        data.qvel[:] = 0.0
        mujoco.mj_forward(self._sim.mj_model, data)
        if self._renderer is None:
            self._renderer = mujoco.Renderer(
                self._sim.mj_model,
                height=self._resolution[0],
                width=self._resolution[1],
            )
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(self._sim.mj_model, camera)
        camera.lookat[:] = framing.lookat_mm
        camera.distance = framing.distance_mm
        camera.azimuth = framing.azimuth_deg
        camera.elevation = framing.elevation_deg
        self._renderer.update_scene(data, camera)
        return np.asarray(self._renderer.render())

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._body.close()


def framing_for(replay: PanelReplay, index: int, *, distance_mm: float) -> Framing:
    """Track the thorax, and keep the hop inside the frame."""
    row = replay.rows[min(index, len(replay.rows) - 1)]["pose"]
    # Framed on the fly rather than on the arena. The hop is 1.5 mm on a 3 mm body, so a
    # camera far enough to show the horizon shows the event as a twitch.
    return Framing(
        lookat_mm=(float(row["x_mm"]), float(row["y_mm"]), float(row["z_mm"]) + 0.35),
        distance_mm=distance_mm,
        azimuth_deg=228.0,
        elevation_deg=-11.0,
    )


def caption_for(summary: dict[str, Any], verdict: dict[str, Any]) -> list[str]:
    graph = summary["graph"]
    return [
        _forbid(
            f"{graph['neurons']:,} neurons  {graph['edges']:,} edges  all executed   "
            f"tier V0 Structural - engineering acceptance, not evidence"
        ),
        _forbid(
            "NO AERODYNAMIC FORCE IS COMPUTED. The jump is a position ramp on two leg "
            "joints; the wings generate nothing."
        ),
        _forbid(f"verdict: {verdict.get('verdict', 'not scored')}   "
                f"commit {str(summary['code_commit'])[:8]}"),
    ]


def scaffolds() -> tuple[str, ...]:
    return SCAFFOLDS
