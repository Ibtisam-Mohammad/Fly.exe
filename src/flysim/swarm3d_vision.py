# SPDX-License-Identifier: GPL-2.0-or-later
"""The DEMO-01 lamina encoder, extended to a scene holding more than one object.

DEMO-01's `RetinotopicVisualEncoder` takes one cue. That is not a limitation of the route
-- the arithmetic is per-object and the retina has room for all of them -- it is a
limitation of an experiment that was designed around a single cue, and the frozen module
is left exactly as it is because it is part of a recorded experiment.

What this module adds is the composition rule and the speed to run it. Each object lands
on its own retinal columns with its own angular size, and a lamina cell takes the strongest
drive reaching it:

    drive(cell) = max over objects of  spatial(cell, object) * loom(object) * pathway(cell)

With one object that maximum is the single term, so this reduces to DEMO-01's encoder
exactly. `tests/test_swarm3d.py` requires that: the same populations, the same parameters
and one cue must produce rates identical to `RetinotopicVisualEncoder.rates_for` to the
last bit, which is what makes the extension checkable rather than merely plausible.

A maximum is a declared choice and not the only defensible one. A real lamina cell sums
photon flux over its receptive field, so two objects landing on one column would combine
rather than compete. The maximum is used because the alternative -- summing drives that are
each already normalised to [0, 1] -- makes a cluster of small objects brighter than a large
one at the same distance, which inverts the looming signal the route is built on. The
choice is P/E and it is declared on screen.

Everything here is vectorised because the loop runs it for every fly at every coupling
interval. The scalar path in `demo01_visual` walks 6,200 Python tuples per call, which is
fine at one fly and sixty-six calls a second and is not fine at twelve.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from flysim.contracts import NeuralInputFrame, SignalType
from flysim.demo01_visual import (
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualEncodingParameters,
)
from flysim.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class SceneObject:
    """One thing a fly can see: where it is and how big it is. Nothing else."""

    object_id: str
    kind: str
    x_mm: float
    y_mm: float
    radius_mm: float


class MultiObjectLaminaEncoder:
    """Every visible object in the arena into per-body lamina rates, for one fly at a time.

    Constructed from the same `Demo01Populations`, `VisualEncodingParameters` and
    `RetinaMap` the single-cue encoder uses, so there is one set of numbers behind both.
    """

    def __init__(
        self,
        populations: Any,
        parameters: VisualEncodingParameters,
        retina: RetinaMap,
        *,
        stimulus_present: bool = True,
    ) -> None:
        # Build the scalar encoder too. It owns the member selection and the
        # "no released column means baseline" rule, and reusing it means the two cannot
        # drift apart in which bodies they drive.
        self._scalar = RetinotopicVisualEncoder(
            populations, parameters, retina, stimulus_present=stimulus_present
        )
        self.populations = populations
        self.parameters = parameters
        self.retina = retina
        self.stimulus_present = stimulus_present

        # DEMO-01 pushes a rate for exactly those entry bodies that carry a released
        # column coordinate. A body without one is absent from the frame rather than held
        # at baseline, so the same set is used here and the two frames address the same
        # neurons.
        members = self._scalar._members  # one selection rule, not two
        all_bodies = sorted(body for _, body, _, _ in members)
        if not all_bodies:
            raise ConfigurationError("No entry body to encode into")
        self._ids: tuple[int, ...] = tuple(all_bodies)
        position = {body: index for index, body in enumerate(all_bodies)}
        self._member_slot = np.asarray(
            [position[body] for _, body, _, _ in members], dtype=np.int64
        )
        self._hex1 = np.asarray([hex1 for _, _, hex1, _ in members], dtype=np.float64)
        self._hex2 = np.asarray([hex2 for _, _, _, hex2 in members], dtype=np.float64)
        self._is_left = np.asarray(
            [name.endswith("-left") for name, _, _, _ in members], dtype=bool
        )
        self._gain = np.asarray(
            [self._scalar._pathway_gain(name) for name, _, _, _ in members],
            dtype=np.float64,
        )
        self._baseline = float(parameters.lamina_baseline_rate_hz)
        self._span = float(
            parameters.lamina_max_rate_hz - parameters.lamina_baseline_rate_hz
        )
        self._columns_per_degree = retina.columns_per_degree()
        # Elevation is fixed at the horizon for every object in this scene, so the hex2
        # target never moves and is computed once.
        _, self._target_hex2 = retina.column_for(0.0, 0.0)
        self._azimuth_scale = (retina.hex1_max - retina.hex1_min) / (
            retina.azimuth_max_deg - retina.azimuth_min_deg
        )
        self._azimuth_offset = (
            retina.hex1_min - retina.azimuth_min_deg * self._azimuth_scale
        )
        self._static_metadata = {
            "entry_layer": "lamina monopolar cells L1-L5",
            "retina_to_lamina_synapse_executed": False,
            "why_not": (
                "All 66,533 photoreceptor output edges are zeroed by the frozen sign "
                "policy: fly photoreceptors are histaminergic and histamine is absent "
                "from the transmitter model, so every prediction is unresolved."
            ),
            "optic_lobe_computes_the_response": True,
            "on_off_balance": parameters.lamina_on_off_balance,
            "composition_rule": (
                "Each lamina cell takes the strongest drive reaching it from any visible "
                "object. With one object this is identical to the DEMO-01 encoder."
            ),
            "composition_rule_provenance": "P/E",
            "entry_bodies_with_column_coordinates": len(members),
            "entry_bodies_without_column_held_at_baseline": (
                self._scalar.bodies_without_column
            ),
            "retina_map": retina.as_dict(),
            "annotations_sha256": populations.annotations_sha256,
        }

    @property
    def ids(self) -> tuple[int, ...]:
        return self._ids

    @property
    def entry_body_count(self) -> int:
        return len(self._ids)

    def rates_for(
        self,
        objects: Sequence[SceneObject],
        *,
        x_mm: float,
        y_mm: float,
        heading_rad: float,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Per-body lamina rates in `ids` order, plus what the fly saw."""
        rates = np.full(len(self._ids), self._baseline, dtype=np.float64)
        scene: dict[str, Any] = {
            "stimulus_present": bool(self.stimulus_present and objects),
            "objects_visible": 0,
            "driven_bodies": 0,
            "nearest": None,
            "strongest": None,
            "per_object": [],
        }
        if not self.stimulus_present or not objects:
            return rates, scene

        count = len(objects)
        ox = np.fromiter((o.x_mm for o in objects), dtype=np.float64, count=count)
        oy = np.fromiter((o.y_mm for o in objects), dtype=np.float64, count=count)
        radius = np.fromiter((o.radius_mm for o in objects), dtype=np.float64, count=count)

        dx = ox - x_mm
        dy = oy - y_mm
        distance = np.hypot(dx, dy)
        bearing = np.arctan2(dy, dx) - heading_rad
        bearing = np.arctan2(np.sin(bearing), np.cos(bearing))
        bearing_deg = np.degrees(bearing)
        # Angular radius, saturating at a hemisphere when the object engulfs the eye. The
        # `distance > radius` guard is DEMO-01's, kept so the two agree at the boundary.
        ratio = np.where(distance > radius, radius / np.maximum(distance, 1e-12), 1.0)
        angular_radius_deg = np.degrees(np.arcsin(np.clip(ratio, -1.0, 1.0)))
        loom = angular_radius_deg / (
            angular_radius_deg + self.parameters.loom_half_angle_deg
        )

        target_left = self._azimuth_offset + bearing_deg * self._azimuth_scale
        target_right = self._azimuth_offset - bearing_deg * self._azimuth_scale
        sigma = (
            self.parameters.receptive_field_sigma_columns
            + angular_radius_deg * self._columns_per_degree
        )
        two_sigma_sq = 2.0 * sigma * sigma

        target = np.where(
            self._is_left[:, None], target_left[None, :], target_right[None, :]
        )
        d_sq = (self._hex1[:, None] - target) ** 2 + (
            self._hex2[:, None] - self._target_hex2
        ) ** 2
        drive = np.exp(-d_sq / two_sigma_sq[None, :])
        drive *= loom[None, :]
        drive *= self._gain[:, None]
        best = drive.max(axis=1)

        rates[self._member_slot] = self._baseline + np.clip(best, 0.0, 1.0) * self._span
        scene["objects_visible"] = count
        scene["driven_bodies"] = int(np.count_nonzero(best > 1e-4))

        nearest = int(np.argmin(distance))
        per_object_peak = drive.max(axis=0)
        strongest = int(np.argmax(per_object_peak))
        scene["per_object"] = [
            {
                "object_id": objects[index].object_id,
                "kind": objects[index].kind,
                "distance_mm": float(distance[index]),
                "bearing_deg": float(bearing_deg[index]),
                "angular_radius_deg": float(angular_radius_deg[index]),
                "loom_term": float(loom[index]),
                "peak_drive": float(per_object_peak[index]),
            }
            for index in range(count)
        ]
        scene["nearest"] = scene["per_object"][nearest]
        scene["strongest"] = scene["per_object"][strongest]
        return rates, scene

    def encode(
        self,
        t_us: int,
        objects: Sequence[SceneObject],
        *,
        x_mm: float,
        y_mm: float,
        heading_rad: float,
    ) -> NeuralInputFrame:
        rates, scene = self.rates_for(
            objects, x_mm=x_mm, y_mm=y_mm, heading_rad=heading_rad
        )
        return NeuralInputFrame(
            t_us=t_us,
            ids=self._ids,
            values=tuple(rates.tolist()),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="P/E",
            assumption_ids=("DATA-03", "DEMO-03", "SWARM-01"),
            metadata={**self._static_metadata, "scene": scene},
        )


def visible_objects_for(
    fly_index: int,
    poses: Sequence[tuple[float, float, float, float]],
    arena_objects: Sequence[Any],
    *,
    fly_visual_radius_mm: float,
    include_other_flies: bool = True,
) -> tuple[SceneObject, ...]:
    """What one fly can see: every visible arena object, and every other fly.

    Other flies enter as spheres of one declared radius. A fly is not a sphere and this
    does not claim otherwise; what it does claim is that a moving object of roughly that
    angular size is present at that bearing, which is the only thing the encoder reads.
    """
    seen: list[SceneObject] = [
        SceneObject(
            object_id=obj.object_id,
            kind=obj.kind,
            x_mm=obj.x_mm,
            y_mm=obj.y_mm,
            radius_mm=obj.radius_mm,
        )
        for obj in arena_objects
        if getattr(obj, "visible_to_vision", True)
    ]
    if include_other_flies:
        for index, (x_mm, y_mm, _, _) in enumerate(poses):
            if index == fly_index:
                continue
            seen.append(
                SceneObject(
                    object_id=f"fly:{index}",
                    kind="fly",
                    x_mm=x_mm,
                    y_mm=y_mm,
                    radius_mm=fly_visual_radius_mm,
                )
            )
    return tuple(seen)


def bearing_and_angular_radius(
    obj: SceneObject, *, x_mm: float, y_mm: float, heading_rad: float
) -> tuple[float, float]:
    """The scalar form, kept for tests and for the trace. Mirrors `VisualCue.geometry_from`."""
    dx, dy = obj.x_mm - x_mm, obj.y_mm - y_mm
    distance = math.hypot(dx, dy)
    bearing = math.atan2(dy, dx) - heading_rad
    bearing = math.atan2(math.sin(bearing), math.cos(bearing))
    ratio = obj.radius_mm / distance if distance > obj.radius_mm else 1.0
    return math.degrees(bearing), math.degrees(math.asin(min(1.0, max(-1.0, ratio))))


__all__ = [
    "MultiObjectLaminaEncoder",
    "SceneObject",
    "bearing_and_angular_radius",
    "visible_objects_for",
]
