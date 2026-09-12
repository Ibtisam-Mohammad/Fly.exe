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

# The station-keeping controller acts through the femur-tibia pitch of every leg:
# common mode shifts the body fore-aft over planted feet, differential mode yaws it.
# Both were chosen by measuring the drift response of all six leg joint groups
# (docs/evidence/TRACK_A_STATION_KEEPING.md); FTi pitch has the largest authority in
# each mode. This is an engineering scaffold with no biological content.
STATION_KEEPING_LEGS: tuple[str, ...] = ("lf", "lm", "lh", "rf", "rm", "rh")
STATION_KEEPING_LEFT_LEGS: frozenset[str] = frozenset({"lf", "lm", "lh"})
STATION_KEEPING_DOF = "{leg}_trochanterfemur-{leg}_tibia-pitch"
# A second fore-aft channel, driven by the same demand as the first at a registered
# weight. It exists because the primary channel is authority-limited: its offset
# saturates at the edge of its monotone branch and the plant's restoring velocity there
# caps near 0.2 mm/s, which is less than the drift force at some standing poses.
STATION_KEEPING_SECONDARY_DOFS: dict[str, str] = {
    "CTr_pitch": "{leg}_coxa-{leg}_trochanterfemur-pitch",
    "ThC_roll": "c_thorax-{leg}_coxa-roll",
    "TiTa_pitch": "{leg}_tibia-{leg}_tarsus1-pitch",
}

# BODY-01 also carries provenance rules that describe how experiments must be built.
# Project only the numeric arena/body fields into the dataclass so adding metadata to the
# assumption record cannot accidentally change this runtime constructor's public interface.
TRACK_A_BODY_PARAMETER_KEYS: tuple[str, ...] = (
    "initial_x_mm",
    "initial_y_mm",
    "initial_heading_rad",
    "spawn_height_mm",
    "food_x_mm",
    "food_y_mm",
    "dust_x_mm",
    "dust_y_mm",
    "dust_radius_mm",
    "dust_entry_clearance_mm",
)


def _clamp(value: float, limit: float) -> float:
    return min(limit, max(-limit, value))


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
    dust_entry_clearance_mm: float
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
    groom_blend_in_us: int
    spawn_height_mm: float
    station_keeping_gain_rad_per_mm: float
    station_keeping_integral_rad_per_mm_s: float
    station_keeping_yaw_gain_rad_per_rad: float
    station_keeping_yaw_integral_rad_per_rad_s: float
    station_keeping_max_offset_rad: float
    station_keeping_max_yaw_offset_rad: float
    station_keeping_settle_us: int
    station_keeping_secondary_channel: str
    station_keeping_secondary_weight: float


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
        suppress_groom_replay: bool = False,
    ) -> None:
        if parameters.physics_dt_us <= 0:
            raise ConfigurationError("FlyGym physics timestep must be positive")
        if parameters.max_forward_mm_s <= 0 or parameters.max_yaw_rad_s <= 0:
            raise ConfigurationError("FlyGym command normalization scales must be positive")
        if fps <= 0:
            raise ConfigurationError("FlyGym render FPS must be positive")
        if parameters.station_keeping_max_offset_rad < 0.0:
            raise ConfigurationError("Station-keeping offset limit must not be negative")
        if parameters.station_keeping_max_yaw_offset_rad < 0.0:
            raise ConfigurationError("Station-keeping yaw offset limit must not be negative")
        if parameters.station_keeping_settle_us % parameters.physics_dt_us:
            raise ConfigurationError(
                "Station-keeping settle window must be a whole number of physics steps"
            )
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
        self._groom_origin_mm: tuple[float, float] | None = None
        self._groom_origin_heading_rad: float = 0.0
        self._groom_net_displacement_mm = 0.0
        self._groom_path_length_mm = 0.0
        self._groom_heading_change_rad = 0.0
        self._settled_pose_mm: tuple[float, float] = (0.0, 0.0)
        self._station_reference: tuple[float, float, float] | None = None
        self._station_offsets_rad: tuple[float, float] = (0.0, 0.0)
        self._station_error_mm = 0.0
        self._station_peak_error_mm = 0.0
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0
        self._station_settle_us = 0
        self._settled_dust_clearance_mm = 0.0
        self._render = render
        # B1's paired control. Suppressing only the joint replay isolates what the replay
        # itself translates the body by, leaving the adhesion pattern, the bout window,
        # the seed and the food position identical. Because the FlyGym body is
        # deterministic given those, the control is an exact matched reference rather
        # than a statistical one.
        self._suppress_groom_replay = suppress_groom_replay
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
        self._station_keeping_channel = self._build_station_keeping_channel()
        self._station_secondary_channel = self._build_secondary_channel()
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
        self._last_targets = settled_targets.copy()
        self._groom_hold_targets = settled_targets.copy()
        self._converge_station_keeping()
        controller.reset(seed=seed, init_magnitudes=np.zeros(6, dtype=np.float64))
        self._assert_settled_outside_dust()

    def _converge_station_keeping(self) -> None:
        """Charge the station-keeping integral before the run starts, changing nothing else.

        Without this the first stance of every run spends a second or two converging on
        the actuator bias that holds the body still, and that excursion is most of the
        displacement the standing criteria measure - a controller startup transient
        scored as a stance defect.

        The window is a calibration, not simulated behaviour, so the body must come out
        of it exactly as it went in. Every physics state the settle touches is saved and
        restored, and the only thing carried forward is the controller's own integral.
        The first attempt at this did not restore anything, and the 2 s of drift it let
        through moved the thorax about 1.2 mm into the dust patch, which the settled-body
        guard caught.
        """
        import mujoco

        settle_us = self.parameters.station_keeping_settle_us
        if settle_us <= 0 or not any(
            (
                self.parameters.station_keeping_gain_rad_per_mm,
                self.parameters.station_keeping_integral_rad_per_mm_s,
                self.parameters.station_keeping_yaw_gain_rad_per_rad,
                self.parameters.station_keeping_yaw_integral_rad_per_rad_s,
            )
        ):
            return
        data = self._simulation.mj_data
        saved = (
            np.array(data.qpos, copy=True),
            np.array(data.qvel, copy=True),
            np.array(data.act, copy=True),
            np.array(data.ctrl, copy=True),
            float(data.time),
        )
        adhered = np.ones(6, dtype=bool)
        for _ in range(settle_us // self.parameters.physics_dt_us):
            targets = self._standing_targets.copy()
            self._apply_station_keeping(targets)
            self._simulation.set_actuator_inputs(self._fly_name, self._actuator_type, targets)
            self._simulation.set_leg_adhesion_states(self._fly_name, adhered)
            self._simulation.step()
        data.qpos[:] = saved[0]
        data.qvel[:] = saved[1]
        data.act[:] = saved[2]
        data.ctrl[:] = saved[3]
        data.time = saved[4]
        mujoco.mj_forward(self._simulation.mj_model, data)
        self._release_station_reference()
        self._station_peak_error_mm = 0.0
        self._station_settle_us = settle_us

    @property
    def t_us(self) -> int:
        return self._t_us

    def _assert_settled_outside_dust(self) -> None:
        """Fail closed if the settled body already sits in the dust patch.

        The spawn position is the fly's root, while contamination is sensed at the
        thorax, which the 50 ms settling phase moves forward by roughly 0.85 mm. In the
        first Track A release that put the thorax inside the dust patch at t=0, so
        contamination accumulated before the fly had walked anywhere and grooming began
        on a fixed schedule instead of after an encounter.
        """
        x_mm, y_mm, _, _ = self._pose()
        distance = math.hypot(
            x_mm - self.parameters.dust_x_mm, y_mm - self.parameters.dust_y_mm
        )
        clearance = distance - self.parameters.dust_radius_mm
        if clearance < self.parameters.dust_entry_clearance_mm:
            raise ConfigurationError(
                "The settled Track A body must start outside the dust patch: thorax at "
                f"({x_mm:.3f}, {y_mm:.3f}) mm is {distance:.3f} mm from the dust centre "
                f"with radius {self.parameters.dust_radius_mm} mm, leaving {clearance:.3f} mm "
                f"of clearance below the required {self.parameters.dust_entry_clearance_mm} mm"
            )
        self._settled_pose_mm = (x_mm, y_mm)
        self._settled_dust_clearance_mm = clearance

    def groom_displacement(self) -> dict[str, float]:
        """Body translation accumulated while the grooming command was active.

        Grooming is a position-controller replay, not a locomotor command, so any
        translation during a bout is an uncommanded physical artefact and is measured
        rather than left implicit.
        """
        return {
            "groom_net_displacement_mm": self._groom_net_displacement_mm,
            "groom_path_length_mm": self._groom_path_length_mm,
            "groom_heading_change_rad": self._groom_heading_change_rad,
        }

    def _build_station_keeping_channel(self) -> tuple[tuple[int, float], ...]:
        """Actuator index and differential sign for each leg the controller acts through."""
        channel: list[tuple[int, float]] = []
        for leg in STATION_KEEPING_LEGS:
            name = STATION_KEEPING_DOF.format(leg=leg)
            try:
                index = self._actuator_index[name]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Station-keeping channel {name} is not an actuated Track A DOF"
                ) from exc
            channel.append((index, 1.0 if leg in STATION_KEEPING_LEFT_LEGS else -1.0))
        return tuple(channel)

    def _build_secondary_channel(self) -> tuple[int, ...]:
        """Actuator indices of the second fore-aft channel, or empty when unused."""
        name = self.parameters.station_keeping_secondary_channel
        if not name or self.parameters.station_keeping_secondary_weight == 0.0:
            return ()
        try:
            template = STATION_KEEPING_SECONDARY_DOFS[name]
        except KeyError as exc:
            raise ConfigurationError(
                f"Unknown station-keeping secondary channel {name!r}; known channels are "
                f"{sorted(STATION_KEEPING_SECONDARY_DOFS)}"
            ) from exc
        indices: list[int] = []
        for leg in STATION_KEEPING_LEGS:
            dof = template.format(leg=leg)
            try:
                indices.append(self._actuator_index[dof])
            except KeyError as exc:
                raise ConfigurationError(
                    f"Station-keeping secondary channel {dof} is not an actuated Track A DOF"
                ) from exc
        return tuple(indices)

    def station_keeping(self) -> dict[str, float]:
        """What the station-keeping controller is currently doing, for the run record."""
        common, differential = self._station_offsets_rad
        return {
            "station_keeping_active": float(self._station_reference is not None),
            "station_keeping_common_offset_rad": common,
            "station_keeping_differential_offset_rad": differential,
            "station_keeping_error_mm": self._station_error_mm,
            "station_keeping_peak_error_mm": self._station_peak_error_mm,
            "station_keeping_fore_aft_integral_mm_s": self._station_fore_aft_integral_mm_s,
            "station_keeping_yaw_integral_rad_s": self._station_yaw_integral_rad_s,
            "station_keeping_settle_us": float(self._station_settle_us),
        }

    def _release_station_reference(self) -> None:
        """Forget where the body was standing, but keep the bias that holds it up.

        The integral converges on the actuator bias that cancels the drift force, and
        that force is a property of the standing configuration and the body's load rather
        than of any particular position. Discarding it on every walk would make each new
        stance re-converge from zero, and the re-convergence excursion is itself most of
        the displacement B3 measures. So the position reference is released and the bias
        is carried forward.
        """
        self._station_reference = None
        self._station_offsets_rad = (0.0, 0.0)

    def _reset_station_keeping(self) -> None:
        self._release_station_reference()
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0

    def _apply_station_keeping(self, targets: np.ndarray) -> None:
        """Null uncommanded body drift by shifting the stance legs, not the physics.

        The standing branch is otherwise an open-loop pose hold, so the persistent net
        force diagnosed in docs/evidence/TRACK_A_STATION_KEEPING.md integrates without
        opposition at about 0.88 mm/s. This is proportional-integral feedback on thorax
        pose against the pose held when standing began, acting through the femur-tibia
        pitch of all six legs: common mode shifts the body fore-aft over planted feet,
        differential mode yaws it.

        The integral term is what does the real work, and it is not decoration. The
        channel's response reverses sign at about 0.055 rad, so its useful band is narrow
        and a proportional gain stiff enough to hold a small error saturates that band
        and limit-cycles. The integral discovers the bias that cancels the drift force
        instead of it being chosen by hand, which also means it re-derives that bias for
        whatever pose the fly stopped walking in.

        The offset limit is not a safety margin, it is part of the control design. The
        measured response is non-monotone: drift velocity falls from +1.02 mm/s at zero
        offset through zero near 0.055 rad, but at 0.12 rad it is +1.40 mm/s, worse than
        no control at all. The limit therefore has to keep both the proportional term and
        the wound-up integral inside the first monotone branch, or the controller
        saturates onto the worst operating point available to it. That is not a
        hypothetical: it is what the first PI sweep did.

        There is deliberately no rate term. One was implemented and swept: at the
        smallest gain tried it moved the body 5.9 mm instead of 0.36 mm and rotated it
        1.2 rad. Differentiating the thorax pose over a 500 us step measures per-step
        contact jitter far more than it measures drift, so the term injects noise at 2 kHz
        into a channel that is already near saturation.

        Provenance E. There is no biological content here. A real fly holds station with
        load-sensing campaniform sensilla and femoral chordotonal reflexes distributed
        through the VNC; nothing in a fly resembles one thorax pose estimate driving the
        femur-tibia pitch of all six legs in common mode.
        """
        proportional = self.parameters.station_keeping_gain_rad_per_mm
        integral = self.parameters.station_keeping_integral_rad_per_mm_s
        yaw_proportional = self.parameters.station_keeping_yaw_gain_rad_per_rad
        yaw_integral = self.parameters.station_keeping_yaw_integral_rad_per_rad_s
        if not any((proportional, integral, yaw_proportional, yaw_integral)):
            self._reset_station_keeping()
            return
        x_mm, y_mm, _, heading_rad = self._pose()
        if self._station_reference is None:
            # Latch where standing began, so the fly holds wherever it stopped rather
            # than being pulled back towards its spawn.
            self._station_reference = (x_mm, y_mm, heading_rad)
            self._station_offsets_rad = (0.0, 0.0)
            self._station_error_mm = 0.0
            return
        reference_x, reference_y, reference_heading = self._station_reference
        delta_x = x_mm - reference_x
        delta_y = y_mm - reference_y
        # Fore-aft in the frame the reference pose defined, so a body that has rotated
        # corrects along its own axis rather than the world's.
        fore_aft_mm = delta_x * math.cos(reference_heading) + delta_y * math.sin(
            reference_heading
        )
        yaw_error_rad = math.atan2(
            math.sin(heading_rad - reference_heading),
            math.cos(heading_rad - reference_heading),
        )
        limit = self.parameters.station_keeping_max_offset_rad
        yaw_limit = self.parameters.station_keeping_max_yaw_offset_rad
        dt_s = self.parameters.physics_dt_us / 1_000_000.0
        self._station_fore_aft_integral_mm_s = self._clamped_integral(
            self._station_fore_aft_integral_mm_s + fore_aft_mm * dt_s, integral, limit
        )
        self._station_yaw_integral_rad_s = self._clamped_integral(
            self._station_yaw_integral_rad_s + yaw_error_rad * dt_s, yaw_integral, yaw_limit
        )
        common = _clamp(
            proportional * fore_aft_mm + integral * self._station_fore_aft_integral_mm_s,
            limit,
        )
        differential = _clamp(
            yaw_proportional * yaw_error_rad + yaw_integral * self._station_yaw_integral_rad_s,
            yaw_limit,
        )
        for index, sign in self._station_keeping_channel:
            targets[index] += _clamp(common + sign * differential, limit)
        # The secondary channel carries the same demand at a registered weight, including
        # while the primary is saturated, which is exactly when the extra authority is
        # needed. It is clamped on its own so it cannot leave its own usable band.
        secondary = _clamp(
            self.parameters.station_keeping_secondary_weight * common, limit
        )
        for index in self._station_secondary_channel:
            targets[index] += secondary
        self._station_offsets_rad = (common, differential)
        self._station_error_mm = math.hypot(delta_x, delta_y)
        self._station_peak_error_mm = max(self._station_peak_error_mm, self._station_error_mm)

    @staticmethod
    def _clamped_integral(accumulated: float, gain: float, limit: float) -> float:
        """Anti-windup: the integral may never demand more than the offset limit allows.

        Without this the accumulator keeps growing while the offset is clamped, and the
        controller cannot respond when the error later reverses.
        """
        if gain == 0.0:
            return 0.0
        ceiling = limit / abs(gain)
        return min(ceiling, max(-ceiling, accumulated))

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
            x_mm, y_mm, _, heading_rad = self._pose()
            self._groom_origin_mm = (x_mm, y_mm)
            self._groom_origin_heading_rad = heading_rad
            self._groom_hold_targets = self._last_targets.copy()
        elif self._command[COMMAND_GROOM] <= 0.0:
            self._groom_started_us = None
            self._groom_origin_mm = None

    def _groom_targets(self, targets: np.ndarray) -> None:
        if self._groom_started_us is None or self._suppress_groom_replay:
            return
        elapsed_us = self._t_us - self._groom_started_us
        elapsed_s = elapsed_us / 1_000_000.0
        source_time = self._trajectory["time_s"]
        source_angles = self._trajectory["angles_rad"]
        elapsed_s = min(float(source_time[-1]), max(0.0, elapsed_s))
        # The published trajectory was recorded from a tethered fly. Snapping a
        # free-standing body's foreleg position targets onto its first sample delivers an
        # impulse through the stance legs, so the replay is blended in over a registered
        # interval. This is an actuator scaffold, not part of the published kinematics.
        blend = (
            1.0
            if self.parameters.groom_blend_in_us <= 0
            else min(1.0, elapsed_us / self.parameters.groom_blend_in_us)
        )
        for source_name, actuator_index in self._source_to_actuator.items():
            source_index = self._trajectory_columns[source_name]
            replayed = float(
                np.interp(elapsed_s, source_time, source_angles[:, source_index])
            )
            held = float(self._groom_hold_targets[actuator_index])
            targets[actuator_index] = held + blend * (replayed - held)

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

        # The controller emits normalized descending drives, which are exactly what the
        # locomotor controller consumes. Neither value is a commanded or achieved speed.
        forward = min(1.0, max(0.0, self._command[COMMAND_FORWARD]))
        turn = min(1.0, max(-1.0, self._command[COMMAND_YAW]))
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
            self._apply_station_keeping(targets)
        else:
            self._release_station_reference()
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
        self._last_targets = targets.copy()
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
            if grooming > 0.0 and self._groom_origin_mm is not None:
                _, _, _, heading_rad = self._pose()
                self._groom_path_length_mm += distance_moved
                self._groom_net_displacement_mm = max(
                    self._groom_net_displacement_mm,
                    math.hypot(
                        x_mm - self._groom_origin_mm[0], y_mm - self._groom_origin_mm[1]
                    ),
                )
                self._groom_heading_change_rad = max(
                    self._groom_heading_change_rad,
                    abs(
                        math.atan2(
                            math.sin(heading_rad - self._groom_origin_heading_rad),
                            math.cos(heading_rad - self._groom_origin_heading_rad),
                        )
                    ),
                )
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
            "grooming_controller": (
                "suppressed-for-B1-paired-control"
                if self._suppress_groom_replay
                else "Ozdil-2026-Fig1-panel-C-trajectory"
            ),
            "groom_replay_suppressed": self._suppress_groom_replay,
            "settled_dust_clearance_mm": self._settled_dust_clearance_mm,
            **self.groom_displacement(),
            **self.station_keeping(),
        }

    def qpos(self) -> np.ndarray:
        """Copy the complete body pose for deterministic offline rendering."""
        return np.asarray(self._simulation.mj_data.qpos, dtype=np.float64).copy()

    def save_video(self, output: Path) -> Path:
        if not self._render or self._simulation.renderer is None:
            raise ConfigurationError("FlyGym rendering was not enabled for this run")
        output.parent.mkdir(parents=True, exist_ok=True)
        self._simulation.renderer.save_video(output)
        return output.resolve()
