# SPDX-License-Identifier: GPL-2.0-or-later
"""FlyGym 2.1 body adapter for the visibly engineered Track A demonstration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.contracts import ActuatorCommandFrame, SensorFrame, SignalType
from flysim.engines.body import (
    COMMAND_FORWARD,
    COMMAND_GROOM,
    COMMAND_IDS,
    COMMAND_PROBOSCIS,
    COMMAND_YAW,
)
from flysim.engines.reference import (
    SENSOR_CONTAMINATION,
    SENSOR_ODOR_L,
    SENSOR_ODOR_R,
    SENSOR_SUCROSE,
    SENSOR_TOUCH,
)
from flysim.errors import CausalityError, ConfigurationError
from flysim.grooming import load_grooming_trajectory


@dataclass(frozen=True, slots=True)
class FlyGymTrackAParameters:
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
    max_forward_mm_s: float
    max_yaw_rad_s: float
    feed_rostrum_extension_rad: float
    feed_haustellum_extension_rad: float
    spawn_height_mm: float


class FlyGymTrackABodyEngine:
    """Physical female-body prior with explicit high-level actuator scaffolds."""

    def __init__(
        self,
        parameters: FlyGymTrackAParameters,
        trajectory_path: Path,
        *,
        seed: int,
        render: bool = False,
        fps: int = 30,
    ) -> None:
        if parameters.physics_dt_us <= 0:
            raise ConfigurationError("FlyGym physics timestep must be positive")
        if parameters.max_forward_mm_s <= 0 or parameters.max_yaw_rad_s <= 0:
            raise ConfigurationError("FlyGym command normalization scales must be positive")
        if fps <= 0:
            raise ConfigurationError("FlyGym render FPS must be positive")
        import mujoco
        from flygym import Simulation
        from flygym.anatomy import (
            ActuatedDOFPreset,
            AxisOrder,
            JointPreset,
            Skeleton,
        )
        from flygym.compose import (
            ActuatorType,
            FlatGroundWorld,
            KinematicPosePreset,
            NeuroMechFly,
        )
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain.turning_controller import HybridTurningController

        self.parameters = parameters
        self._t_us = 0
        self.contamination = 0.0
        self.proboscis_extension = 0.0
        self.dust_exposure_complete = False
        self._command = {identifier: 0.0 for identifier in COMMAND_IDS}
        self._groom_started_us: int | None = None
        self._render = render
        self._trajectory = load_grooming_trajectory(trajectory_path)
        self._trajectory_columns = {
            str(name): index for index, name in enumerate(self._trajectory["column_names"])
        }

        neutral_pose = KinematicPosePreset.NEUTRAL.get_pose_by_axis_order(
            AxisOrder.YAW_PITCH_ROLL
        )
        skeleton = Skeleton(
            axis_order=AxisOrder.YAW_PITCH_ROLL,
            joint_preset=JointPreset.ALL_BIOLOGICAL,
        )
        fly_name = "track_a_fly"
        fly = NeuroMechFly(name=fly_name)
        fly.add_joints(skeleton, neutral_pose=neutral_pose)
        leg_dofs = skeleton.get_actuated_dofs_from_preset(
            ActuatedDOFPreset.LEGS_ACTIVE_ONLY
        )
        special_dofs = [
            dof
            for dof in skeleton.iter_jointdofs()
            if (
                (dof.child.name == "c_head" and dof.axis.value in {"roll", "pitch", "yaw"})
                or (
                    dof.child.name in {"l_pedicel", "r_pedicel"}
                    and dof.axis.value in {"pitch", "yaw"}
                )
                or (
                    dof.child.name in {"c_rostrum", "c_haustellum"}
                    and dof.axis.value == "pitch"
                )
            )
        ]
        actuated_dofs = [*leg_dofs, *special_dofs]
        fly.add_actuators(
            actuated_dofs,
            ActuatorType.POSITION,
            neutral_input=neutral_pose,
            kp=45.0,
            forcerange=(-65.0, 65.0),
        )
        fly.add_leg_adhesion(gain=40.0)
        fly.colorize()
        camera = fly.add_tracking_camera(name="track_a_camera")
        world = FlatGroundWorld(half_size=100.0)
        half_yaw = parameters.initial_heading_rad / 2.0
        spawn_rotation = Rotation3D(
            "quat",
            (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw)),
        )
        world.add_fly(
            fly,
            spawn_position=np.array(
                [parameters.initial_x_mm, parameters.initial_y_mm, parameters.spawn_height_mm]
            ),
            spawn_rotation=spawn_rotation,
        )
        simulation = Simulation(world, timestep=parameters.physics_dt_us / 1_000_000.0)
        if render:
            simulation.set_renderer(
                camera.name,
                camera_res=(544, 960),
                playback_speed=1.0,
                output_fps=fps,
            )
        controller = HybridTurningController(
            timestep=parameters.physics_dt_us / 1_000_000.0,
            output_dof_order=leg_dofs,
        )
        controller.reset(seed=seed)
        body_order = fly.get_bodysegs_order()
        thorax = type(fly).BODY_SEGMENT_CLASS("c_thorax")
        self._thorax_index = body_order.index(thorax)
        self._fly_name = fly_name
        self._fly = fly
        self._simulation = simulation
        self._controller = controller
        self._actuator_type = ActuatorType.POSITION
        self._leg_dofs = leg_dofs
        self._actuated_dofs = fly.get_actuated_jointdofs_order(ActuatorType.POSITION)
        if self._actuated_dofs != actuated_dofs:
            raise ConfigurationError("FlyGym changed the requested Track A actuator order")
        joint_order = fly.get_jointdofs_order()
        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
        initial_angles = simulation.get_joint_angles(fly_name)
        self._neutral_targets = np.asarray(
            [initial_angles[joint_order.index(dof)] for dof in self._actuated_dofs],
            dtype=np.float64,
        )
        self._actuator_index = {dof.name: index for index, dof in enumerate(self._actuated_dofs)}
        self._source_to_actuator = self._build_source_mapping()
        settled_targets = self._neutral_targets.copy()
        settled_targets[: len(leg_dofs)] = (
            controller.preprogrammed_steps.default_pose_by_dof_order(leg_dofs)
        )
        simulation.set_actuator_inputs(fly_name, ActuatorType.POSITION, settled_targets)
        simulation.set_leg_adhesion_states(fly_name, np.ones(6, dtype=bool))
        simulation.warmup()
        simulation.mj_data.qvel[:] = 0.0
        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
        self._standing_targets = settled_targets.copy()
        controller.reset(seed=seed, init_magnitudes=np.zeros(6, dtype=np.float64))

    @property
    def t_us(self) -> int:
        return self._t_us

    def _build_source_mapping(self) -> dict[str, int]:
        from flygym.anatomy import BodySegment, JointDOF, RotationAxis

        mapping: dict[str, int] = {}
        transitions = {
            "ThC": ("c_thorax", "coxa"),
            "CTr": (None, "trochanterfemur"),
            "FTi": (None, "tibia"),
            "TiTa": (None, "tarsus1"),
        }
        for source_name in self._trajectory_columns:
            components = source_name.split("_")
            if components[1] in {"LF", "RF"}:
                leg = components[1].lower()
                transition, axis = components[2], components[3]
                parent_link, child_link = transitions[transition]
                parent = BodySegment(
                    parent_link if parent_link is not None else self._leg_parent(leg, child_link)
                )
                child = BodySegment(f"{leg}_{child_link}")
                dof = JointDOF(parent, child, RotationAxis(axis))
            elif components[1] == "head":
                dof = JointDOF(
                    BodySegment("c_thorax"),
                    BodySegment("c_head"),
                    RotationAxis(components[2]),
                )
            elif components[1] == "antenna":
                side = components[3].lower()
                dof = JointDOF(
                    BodySegment("c_head"),
                    BodySegment(f"{side}_pedicel"),
                    RotationAxis(components[2]),
                )
            else:
                raise ConfigurationError(f"Unsupported grooming signal: {source_name}")
            try:
                mapping[source_name] = self._actuator_index[dof.name]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Published grooming signal does not map to a FlyGym actuator: {source_name}"
                ) from exc
        return mapping

    @staticmethod
    def _leg_parent(leg: str, child_link: str) -> str:
        parents = {
            "trochanterfemur": "coxa",
            "tibia": "trochanterfemur",
            "tarsus1": "tibia",
        }
        return f"{leg}_{parents[child_link]}"

    def _odor_at(self, x_mm: float, y_mm: float) -> float:
        distance_sq = (x_mm - self.parameters.food_x_mm) ** 2 + (
            y_mm - self.parameters.food_y_mm
        ) ** 2
        raw = self.parameters.source_strength / (distance_sq + self.parameters.softening_mm2)
        return raw / (raw + self.parameters.half_saturation)

    def _pose(self) -> tuple[float, float, float, float]:
        position = self._simulation.get_body_positions(self._fly_name)[self._thorax_index]
        quaternion = self._simulation.get_body_rotations(self._fly_name)[self._thorax_index]
        w, x, y, z = (float(value) for value in quaternion)
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return float(position[0]), float(position[1]), float(position[2]), yaw

    def sample_sensors(self) -> SensorFrame:
        x_mm, y_mm, _, heading_rad = self._pose()
        half_sep = self.parameters.antenna_separation_mm / 2.0
        left_x = x_mm - math.sin(heading_rad) * half_sep
        left_y = y_mm + math.cos(heading_rad) * half_sep
        right_x = x_mm + math.sin(heading_rad) * half_sep
        right_y = y_mm - math.cos(heading_rad) * half_sep
        food_distance = math.hypot(
            x_mm - self.parameters.food_x_mm, y_mm - self.parameters.food_y_mm
        )
        contact_found, *_ = self._simulation.get_ground_contact_info(self._fly_name)
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
                1.0 if bool(np.any(contact_found)) else 0.0,
            ),
            units="normalized [0,1]",
            signal_type=SignalType.WORLD_QUANTITY,
            provenance="P/E",
            assumption_ids=("SENS-03", "SENS-04", "BODY-01"),
            metadata={
                "odor": "ethyl acetate",
                "left_antenna_xy_mm": [left_x, left_y],
                "right_antenna_xy_mm": [right_x, right_y],
                "body_backend": "FlyGym 2.1 / MuJoCo 3.9",
            },
        )

    def apply_actuators(self, frame: ActuatorCommandFrame) -> None:
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Actuator timestamp {frame.t_us} does not match FlyGym time {self._t_us}"
            )
        old_grooming = self._command[COMMAND_GROOM]
        self._command = {
            identifier: frame.value_for(identifier, 0.0) for identifier in COMMAND_IDS
        }
        if old_grooming <= 0.0 < self._command[COMMAND_GROOM]:
            self._groom_started_us = self._t_us
        elif self._command[COMMAND_GROOM] <= 0.0:
            self._groom_started_us = None

    def _groom_targets(self, targets: np.ndarray) -> None:
        if self._groom_started_us is None:
            return
        elapsed_s = (self._t_us - self._groom_started_us) / 1_000_000.0
        source_time = self._trajectory["time_s"]
        source_angles = self._trajectory["angles_rad"]
        elapsed_s = min(float(source_time[-1]), max(0.0, elapsed_s))
        for source_name, actuator_index in self._source_to_actuator.items():
            source_index = self._trajectory_columns[source_name]
            targets[actuator_index] = np.interp(
                elapsed_s, source_time, source_angles[:, source_index]
            )

    def _feeding_targets(self, targets: np.ndarray) -> None:
        extension = min(1.0, max(0.0, self._command[COMMAND_PROBOSCIS]))
        adjustments = {
            "c_head-c_rostrum-pitch": self.parameters.feed_rostrum_extension_rad,
            "c_rostrum-c_haustellum-pitch": self.parameters.feed_haustellum_extension_rad,
        }
        for dof_name, amount in adjustments.items():
            index = self._actuator_index[dof_name]
            targets[index] = self._neutral_targets[index] + extension * amount

    def _apply_physics_action(self) -> None:
        from flygym_demo.complex_terrain.hybrid_controller import HybridControllerObservation

        forward = min(
            1.0,
            max(0.0, self._command[COMMAND_FORWARD] / self.parameters.max_forward_mm_s),
        )
        turn = min(
            1.0,
            max(-1.0, self._command[COMMAND_YAW] / self.parameters.max_yaw_rad_s),
        )
        if self._command[COMMAND_GROOM] > 0.0 or self._command[COMMAND_PROBOSCIS] > 0.0:
            descending = np.zeros(2, dtype=np.float64)
        else:
            descending = np.clip(
                np.array([forward - turn, forward + turn], dtype=np.float64),
                -1.0,
                1.0,
            )
        is_standing = bool(np.allclose(descending, 0.0))
        if is_standing:
            action = None
            targets = self._standing_targets.copy()
        else:
            observation = HybridControllerObservation.from_sim(
                self._simulation, self._fly_name
            )
            action = self._controller.step(descending, observation)
            targets = self._neutral_targets.copy()
            targets[: len(self._leg_dofs)] = action.joint_angles
        if self._command[COMMAND_GROOM] > 0.0:
            self._groom_targets(targets)
            adhesion = np.array([False, True, True, False, True, True], dtype=bool)
        else:
            adhesion = (
                np.ones(6, dtype=bool) if action is None else action.adhesion_onoff
            )
        self._feeding_targets(targets)
        self._simulation.set_actuator_inputs(
            self._fly_name, self._actuator_type, targets
        )
        if adhesion is not None:
            self._simulation.set_leg_adhesion_states(self._fly_name, adhesion)

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step FlyGym backward from {self._t_us} to {t_us}")
        if (t_us - self._t_us) % self.parameters.physics_dt_us:
            raise CausalityError("Track A body boundary is not aligned to the physics step")
        while self._t_us < t_us:
            self._apply_physics_action()
            old_x, old_y, _, _ = self._pose()
            self._simulation.step()
            if self._render:
                self._simulation.render_as_needed()
            next_t = self._t_us + self.parameters.physics_dt_us
            x_mm, y_mm, _, _ = self._pose()
            distance_moved = math.hypot(x_mm - old_x, y_mm - old_y)
            dust_distance = math.hypot(
                x_mm - self.parameters.dust_x_mm, y_mm - self.parameters.dust_y_mm
            )
            can_deposit = not (
                self.parameters.single_dust_exposure and self.dust_exposure_complete
            )
            dt_s = self.parameters.physics_dt_us / 1_000_000.0
            if (
                can_deposit
                and dust_distance <= self.parameters.dust_radius_mm
                and distance_moved > 0
            ):
                self.contamination += self.parameters.dust_deposition_per_s * dt_s
                if self.contamination >= self.parameters.dust_exposure_cap:
                    self.contamination = self.parameters.dust_exposure_cap
                    self.dust_exposure_complete = True
            grooming = min(1.0, max(0.0, self._command[COMMAND_GROOM]))
            self.contamination -= grooming * self.parameters.groom_removal_per_s * dt_s
            self.contamination = min(1.0, max(0.0, self.contamination))
            self.proboscis_extension = min(
                1.0, max(0.0, self._command[COMMAND_PROBOSCIS])
            )
            self._t_us = next_t

    def snapshot(self) -> dict[str, Any]:
        x_mm, y_mm, z_mm, heading_rad = self._pose()
        return {
            "t_us": self._t_us,
            "x_mm": x_mm,
            "y_mm": y_mm,
            "z_mm": z_mm,
            "heading_rad": heading_rad,
            "contamination": self.contamination,
            "proboscis_extension": self.proboscis_extension,
            "dust_exposure_complete": self.dust_exposure_complete,
            "command": dict(self._command),
            "backend": "FlyGym-2.1-MuJoCo-3.9",
            "female_body_prior": True,
            "grooming_controller": "Ozdil-2026-Fig1-panel-C-trajectory",
        }

    def save_video(self, output: Path) -> Path:
        if not self._render or self._simulation.renderer is None:
            raise ConfigurationError("FlyGym rendering was not enabled for this run")
        output.parent.mkdir(parents=True, exist_ok=True)
        self._simulation.renderer.save_video(output)
        return output.resolve()
