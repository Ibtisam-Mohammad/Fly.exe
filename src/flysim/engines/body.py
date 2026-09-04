# SPDX-License-Identifier: GPL-2.0-or-later
"""Kinematic preview body and procedural arena for early integration tests."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from flysim.contracts import ActuatorCommandFrame, SensorFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError

from .reference import (
    SENSOR_CONTAMINATION,
    SENSOR_ODOR_L,
    SENSOR_ODOR_R,
    SENSOR_SUCROSE,
    SENSOR_TOUCH,
)

COMMAND_FORWARD = "actuator:forward-velocity"
COMMAND_YAW = "actuator:yaw-rate"
COMMAND_GROOM = "actuator:grooming-intensity"
COMMAND_PROBOSCIS = "actuator:proboscis-extension"
COMMAND_IDS = (COMMAND_FORWARD, COMMAND_YAW, COMMAND_GROOM, COMMAND_PROBOSCIS)


@dataclass(frozen=True, slots=True)
class KinematicParameters:
    physics_dt_us: int
    initial_x_mm: float
    initial_y_mm: float
    initial_heading_rad: float
    food_x_mm: float
    food_y_mm: float
    dust_x_mm: float
    dust_y_mm: float
    dust_radius_mm: float
    source_strength: float
    softening_mm2: float
    half_saturation: float
    antenna_separation_mm: float
    dust_deposition_per_s: float
    dust_exposure_cap: float
    single_dust_exposure: bool
    groom_removal_per_s: float
    food_contact_radius_mm: float


class KinematicBodyEngine:
    """Explicit `E` point-body preview, not NeuroMechFly."""

    def __init__(self, parameters: KinematicParameters) -> None:
        if parameters.physics_dt_us <= 0:
            raise ConfigurationError("Body physics timestep must be positive")
        self.parameters = parameters
        self._t_us = 0
        self.x_mm = parameters.initial_x_mm
        self.y_mm = parameters.initial_y_mm
        self.heading_rad = parameters.initial_heading_rad
        self.contamination = 0.0
        self.proboscis_extension = 0.0
        self.dust_exposure_complete = False
        self._command = {identifier: 0.0 for identifier in COMMAND_IDS}

    @property
    def t_us(self) -> int:
        return self._t_us

    def _odor_at(self, x_mm: float, y_mm: float) -> float:
        distance_sq = (x_mm - self.parameters.food_x_mm) ** 2 + (
            y_mm - self.parameters.food_y_mm
        ) ** 2
        raw = self.parameters.source_strength / (distance_sq + self.parameters.softening_mm2)
        return raw / (raw + self.parameters.half_saturation)

    def sample_sensors(self) -> SensorFrame:
        half_sep = self.parameters.antenna_separation_mm / 2.0
        left_x = self.x_mm - math.sin(self.heading_rad) * half_sep
        left_y = self.y_mm + math.cos(self.heading_rad) * half_sep
        right_x = self.x_mm + math.sin(self.heading_rad) * half_sep
        right_y = self.y_mm - math.cos(self.heading_rad) * half_sep
        food_distance = math.hypot(
            self.x_mm - self.parameters.food_x_mm, self.y_mm - self.parameters.food_y_mm
        )
        return SensorFrame(
            t_us=self._t_us,
            ids=(
                SENSOR_ODOR_L,
                SENSOR_ODOR_R,
                SENSOR_CONTAMINATION,
                SENSOR_SUCROSE,
                SENSOR_TOUCH,
            ),
            values=(
                self._odor_at(left_x, left_y),
                self._odor_at(right_x, right_y),
                self.contamination,
                1.0 if food_distance <= self.parameters.food_contact_radius_mm else 0.0,
                1.0,
            ),
            units="normalized [0,1]",
            signal_type=SignalType.WORLD_QUANTITY,
            provenance="E",
            assumption_ids=("SENS-03", "SENS-04", "BODY-01"),
            metadata={
                "odor": "ethyl acetate",
                "left_antenna_xy_mm": [left_x, left_y],
                "right_antenna_xy_mm": [right_x, right_y],
            },
        )

    def apply_actuators(self, frame: ActuatorCommandFrame) -> None:
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Actuator timestamp {frame.t_us} does not match body time {self._t_us}"
            )
        self._command = {identifier: frame.value_for(identifier, 0.0) for identifier in COMMAND_IDS}

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step body backward from {self._t_us} to {t_us}")
        while self._t_us < t_us:
            next_t = min(t_us, self._t_us + self.parameters.physics_dt_us)
            dt_s = (next_t - self._t_us) / 1_000_000.0
            forward = self._command[COMMAND_FORWARD]
            yaw = self._command[COMMAND_YAW]
            grooming = min(1.0, max(0.0, self._command[COMMAND_GROOM]))
            self.heading_rad = math.atan2(
                math.sin(self.heading_rad + yaw * dt_s),
                math.cos(self.heading_rad + yaw * dt_s),
            )
            self.x_mm += math.cos(self.heading_rad) * forward * dt_s
            self.y_mm += math.sin(self.heading_rad) * forward * dt_s

            dust_distance = math.hypot(
                self.x_mm - self.parameters.dust_x_mm, self.y_mm - self.parameters.dust_y_mm
            )
            can_deposit = not (
                self.parameters.single_dust_exposure and self.dust_exposure_complete
            )
            if (
                can_deposit
                and dust_distance <= self.parameters.dust_radius_mm
                and abs(forward) > 0.0
            ):
                self.contamination += self.parameters.dust_deposition_per_s * dt_s
                if self.contamination >= self.parameters.dust_exposure_cap:
                    self.contamination = self.parameters.dust_exposure_cap
                    self.dust_exposure_complete = True
            self.contamination -= grooming * self.parameters.groom_removal_per_s * dt_s
            self.contamination = min(1.0, max(0.0, self.contamination))
            self.proboscis_extension = min(
                1.0, max(0.0, self._command[COMMAND_PROBOSCIS])
            )
            self._t_us = next_t

    def snapshot(self) -> dict[str, Any]:
        return {
            "t_us": self._t_us,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "heading_rad": self.heading_rad,
            "contamination": self.contamination,
            "proboscis_extension": self.proboscis_extension,
            "dust_exposure_complete": self.dust_exposure_complete,
            "command": dict(self._command),
            "backend": "kinematic-preview",
        }
