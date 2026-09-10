# SPDX-License-Identifier: GPL-2.0-or-later
"""A minimal FlyGym body for DEMO-01: flat ground, one visual cue, nothing else.

Deliberately much smaller than the Track A body engine. That engine carries odour
diffusion, dust deposition, grooming replay, proboscis extension, food contact and a
two-channel station-keeping PI controller, all of which are Track A's evidence and none of
which DEMO-01 needs. Rather than add a visual mode to it and put that evidence at risk,
this is a separate body with only what the visual loop uses:

* a NeuroMechFly on flat ground with leg adhesion, identical construction to Track A's;
* the same `HybridTurningController` walking controller, driven by exactly the two
  normalised descending drives the neural decoder emits;
* a cue with a world position and a physical radius, which the encoder turns into retinal
  drive and the renderer draws;
* pose readout, and nothing that reads the cue on the body's behalf.

The body publishes no odour, no sucrose and no contamination channel. There is no sensory
value here that a controller could shortcut through, because the only world quantity that
exists is the cue's geometry, and that reaches the brain solely through the retinotopic
lamina encoder.

Provenance E throughout. The walking controller is a published engineered CPG, not a VNC
model, and the scaffolds it stands on are declared in `SCAFFOLDS`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from flysim.contracts import ActuatorCommandFrame
from flysim.engines.body import COMMAND_FORWARD, COMMAND_YAW
from flysim.engines.flygym import (
    STATION_KEEPING_DOF,
    STATION_KEEPING_LEFT_LEGS,
    STATION_KEEPING_LEGS,
    _clamp,
)
from flysim.errors import CausalityError, ConfigurationError

# Every engineered stand-in this body relies on, named so the video and the artifact can
# both print them rather than implying a biological locomotor system.
SCAFFOLDS: tuple[str, ...] = (
    "FlyGym HybridTurningController: a published engineered central pattern generator "
    "driven by two normalised descending drives. It is not a VNC model and no part of the "
    "simulated VNC contributes to leg movement.",
    "Leg adhesion at a fixed gain, which no fly possesses as a switchable actuator.",
    "A female NeuroMechFly body prior driven by a male CNS graph.",
    "Standing is a proportional-integral controller holding thorax pose through the "
    "femur-tibia pitch of all six legs, ported from Track A. Without it a body commanded "
    "to stand drifts at about 2 mm/s. A fly does this with load-sensing sensilla and "
    "chordotonal reflexes distributed through the ventral cord, and nothing in a fly "
    "resembles one pose estimate driving six joints in common mode.",
    "The cue is a geometric object with a radius and a position. It has no texture, no "
    "luminance spectrum and no background.",
)


@dataclass(frozen=True, slots=True)
class Demo01BodyParameters:
    """Body and cue geometry. All E provenance."""

    physics_dt_us: int
    initial_x_mm: float
    initial_y_mm: float
    initial_heading_rad: float
    spawn_height_mm: float
    cue_x_mm: float
    cue_y_mm: float
    cue_radius_mm: float
    cue_height_mm: float
    max_forward_mm_s: float
    max_yaw_rad_s: float
    # Station keeping, carried over unchanged from Track A's measured controller. See the
    # module docstring for why it is not optional.
    station_keeping_gain_rad_per_mm: float = 0.02
    station_keeping_integral_rad_per_mm_s: float = 0.06
    station_keeping_yaw_gain_rad_per_rad: float = 0.05
    station_keeping_yaw_integral_rad_per_rad_s: float = 0.4
    station_keeping_max_offset_rad: float = 0.07
    station_keeping_max_yaw_offset_rad: float = 0.02
    station_keeping_settle_us: int = 2000000

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Demo01BodyParameters:
        station: dict[str, Any] = {
            name: float(raw[name])
            for name in (
                "station_keeping_gain_rad_per_mm",
                "station_keeping_integral_rad_per_mm_s",
                "station_keeping_yaw_gain_rad_per_rad",
                "station_keeping_yaw_integral_rad_per_rad_s",
                "station_keeping_max_offset_rad",
                "station_keeping_max_yaw_offset_rad",
            )
            if name in raw
        }
        if "station_keeping_settle_us" in raw:
            station["station_keeping_settle_us"] = int(raw["station_keeping_settle_us"])
        values = cls(
            physics_dt_us=int(raw["physics_dt_us"]),
            initial_x_mm=float(raw["initial_x_mm"]),
            initial_y_mm=float(raw["initial_y_mm"]),
            initial_heading_rad=float(raw["initial_heading_rad"]),
            spawn_height_mm=float(raw["spawn_height_mm"]),
            cue_x_mm=float(raw["cue_x_mm"]),
            cue_y_mm=float(raw["cue_y_mm"]),
            cue_radius_mm=float(raw["cue_radius_mm"]),
            cue_height_mm=float(raw["cue_height_mm"]),
            max_forward_mm_s=float(raw["max_forward_mm_s"]),
            max_yaw_rad_s=float(raw["max_yaw_rad_s"]),
            **station,
        )
        if values.physics_dt_us <= 0:
            raise ConfigurationError("Physics timestep must be positive")
        if values.cue_radius_mm <= 0.0:
            raise ConfigurationError("Cue radius must be positive")
        if values.max_forward_mm_s <= 0.0 or values.max_yaw_rad_s <= 0.0:
            raise ConfigurationError("Command normalisation scales must be positive")
        if values.station_keeping_max_offset_rad < 0.0:
            raise ConfigurationError("Station-keeping offset limit must not be negative")
        if values.station_keeping_max_yaw_offset_rad < 0.0:
            raise ConfigurationError("Station-keeping yaw offset limit must not be negative")
        if values.station_keeping_settle_us % values.physics_dt_us:
            raise ConfigurationError(
                "Station-keeping settle window must be a whole number of physics steps"
            )
        return values


class Demo01VisualBody:
    """NeuroMechFly on flat ground with one visual cue. Pose in, leg movement out."""

    def __init__(
        self,
        parameters: Demo01BodyParameters,
        *,
        seed: int,
        camera_resolution: tuple[int, int] = (720, 1280),
    ) -> None:
        import mujoco
        from flygym import Simulation
        from flygym.anatomy import ActuatedDOFPreset, AxisOrder, JointPreset, Skeleton
        from flygym.compose import (
            ActuatorType,
            FlatGroundWorld,
            KinematicPosePreset,
            NeuroMechFly,
        )
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain.turning_controller import HybridTurningController

        self.parameters = parameters
        self._mujoco = mujoco
        neutral_pose = KinematicPosePreset.NEUTRAL.get_pose_by_axis_order(
            AxisOrder.YAW_PITCH_ROLL
        )
        skeleton = Skeleton(
            axis_order=AxisOrder.YAW_PITCH_ROLL, joint_preset=JointPreset.ALL_BIOLOGICAL
        )
        fly_name = "demo01_fly"
        fly = NeuroMechFly(name=fly_name)
        fly.add_joints(skeleton, neutral_pose=neutral_pose)
        leg_dofs = skeleton.get_actuated_dofs_from_preset(ActuatedDOFPreset.LEGS_ACTIVE_ONLY)
        fly.add_actuators(
            leg_dofs,
            ActuatorType.POSITION,
            neutral_input=neutral_pose,
            kp=45.0,
            forcerange=(-65.0, 65.0),
        )
        fly.add_leg_adhesion(gain=40.0)
        fly.colorize()
        camera = fly.add_tracking_camera(name="demo01_camera")
        world = FlatGroundWorld(half_size=100.0)
        half_yaw = parameters.initial_heading_rad / 2.0
        world.add_fly(
            fly,
            spawn_position=np.array(
                [parameters.initial_x_mm, parameters.initial_y_mm, parameters.spawn_height_mm]
            ),
            spawn_rotation=Rotation3D(
                "quat", (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
            ),
        )
        simulation = Simulation(world, timestep=parameters.physics_dt_us / 1_000_000.0)
        controller = HybridTurningController(
            timestep=parameters.physics_dt_us / 1_000_000.0, output_dof_order=leg_dofs
        )
        controller.reset(seed=seed)
        body_order = fly.get_bodysegs_order()
        thorax = type(fly).BODY_SEGMENT_CLASS("c_thorax")
        self._thorax_index = body_order.index(thorax)
        self._fly_name = fly_name
        self._fly = fly
        self._camera_name = camera.name
        self._simulation = simulation
        self._controller = controller
        self._actuator_type = ActuatorType.POSITION
        self._leg_dofs = leg_dofs
        self._actuated_dofs = fly.get_actuated_jointdofs_order(ActuatorType.POSITION)
        self._actuator_index = {
            dof.name: index for index, dof in enumerate(self._actuated_dofs)
        }
        joint_order = fly.get_jointdofs_order()
        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
        initial_angles = simulation.get_joint_angles(fly_name)
        self._neutral_targets = np.asarray(
            [initial_angles[joint_order.index(dof)] for dof in self._actuated_dofs],
            dtype=np.float64,
        )
        settled = self._neutral_targets.copy()
        settled[: len(leg_dofs)] = controller.preprogrammed_steps.default_pose_by_dof_order(
            leg_dofs
        )
        simulation.set_actuator_inputs(fly_name, self._actuator_type, settled)
        simulation.set_leg_adhesion_states(fly_name, np.ones(6, dtype=bool))
        simulation.warmup()
        simulation.mj_data.qvel[:] = 0.0
        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
        self._standing_targets = settled.copy()
        # The controller's state has to exist before the convergence window runs it.
        self._station_keeping_channel = self._build_station_keeping_channel()
        self._station_reference: tuple[float, float, float] | None = None
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0
        self._station_error_mm = 0.0
        self._station_peak_error_mm = 0.0
        self._station_offsets_rad = (0.0, 0.0)
        self._station_settle_us = 0
        self._converge_station_keeping()
        controller.reset(seed=seed, init_magnitudes=np.zeros(6, dtype=np.float64))
        self._command = {COMMAND_FORWARD: 0.0, COMMAND_YAW: 0.0}
        self._t_us = 0
        self._renderer: Any | None = None
        self._camera_resolution = camera_resolution
        self._trajectory: list[tuple[int, float, float, float]] = []

    # -- pose and cue -------------------------------------------------------------

    @property
    def t_us(self) -> int:
        return self._t_us

    def pose(self) -> tuple[float, float, float, float]:
        """x mm, y mm, z mm, heading rad."""
        position = self._simulation.get_body_positions(self._fly_name)[self._thorax_index]
        quaternion = self._simulation.get_body_rotations(self._fly_name)[self._thorax_index]
        w, x, y, z = (float(value) for value in quaternion)
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return float(position[0]), float(position[1]), float(position[2]), yaw

    def cue_distance_mm(self) -> float:
        x_mm, y_mm, _, _ = self.pose()
        return math.hypot(x_mm - self.parameters.cue_x_mm, y_mm - self.parameters.cue_y_mm)

    def trajectory(self) -> tuple[tuple[int, float, float, float], ...]:
        return tuple(self._trajectory)

    # -- actuation ----------------------------------------------------------------

    def apply_actuators(self, frame: ActuatorCommandFrame) -> None:
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Actuator timestamp {frame.t_us} does not match body time {self._t_us}"
            )
        self._command = {
            COMMAND_FORWARD: frame.value_for(COMMAND_FORWARD, 0.0),
            COMMAND_YAW: frame.value_for(COMMAND_YAW, 0.0),
        }

    def _build_station_keeping_channel(self) -> tuple[tuple[int, float], ...]:
        """Actuator index and differential sign for each leg the controller acts through.

        The femur-tibia pitch of all six legs: common mode shifts the body fore-aft over
        planted feet, differential mode yaws it. Both channels were chosen in Track A by
        measuring the drift response of every leg joint group, and FTi pitch has the
        largest authority in each mode.
        """
        channel: list[tuple[int, float]] = []
        for leg in STATION_KEEPING_LEGS:
            name = STATION_KEEPING_DOF.format(leg=leg)
            try:
                index = self._actuator_index[name]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Station-keeping channel {name} is not an actuated DOF"
                ) from exc
            channel.append((index, 1.0 if leg in STATION_KEEPING_LEFT_LEGS else -1.0))
        return tuple(channel)

    def _release_station_reference(self) -> None:
        """Forget where the body was standing, but keep the bias that holds it up.

        The integral converges on the actuator bias that cancels the drift force, and
        that force is a property of the standing configuration and the body's load rather
        than of any particular position. Discarding it whenever the fly walks would make
        every new stance re-converge from zero, and that re-convergence excursion is most
        of the displacement the standing criteria measure.
        """
        self._station_reference = None
        self._station_offsets_rad = (0.0, 0.0)

    def _reset_station_keeping(self) -> None:
        """Forget the pose *and* the bias. Only for when the controller is switched off."""
        self._release_station_reference()
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0

    def _converge_station_keeping(self) -> None:
        """Charge the station-keeping integral before the run starts, changing nothing else.

        Without this the first stance spends a second or two converging on the actuator
        bias that holds the body still, and that excursion is a controller startup
        transient scored as a stance defect.

        The window is a calibration, not simulated behaviour, so the body must come out of
        it exactly as it went in. Every physics state the settle touches is saved and
        restored, and the only thing carried forward is the controller's own integral.
        """
        mujoco = self._mujoco
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
            self._simulation.set_actuator_inputs(
                self._fly_name, self._actuator_type, targets
            )
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

    @staticmethod
    def _clamped_integral(accumulated: float, gain: float, limit: float) -> float:
        if gain == 0.0:
            return 0.0
        bound = abs(limit / gain)
        return min(bound, max(-bound, accumulated))

    def _apply_station_keeping(self, targets: np.ndarray) -> None:
        """Null uncommanded drift by shifting the stance legs, never the physics.

        Ported unchanged from Track A, whose measurements are in
        docs/evidence/TRACK_A_STATION_KEEPING.md. Three of its design decisions are load
        bearing and are kept rather than rediscovered:

        the integral term does the work, because the channel's response reverses sign near
        0.055 rad so a proportional gain stiff enough to hold a small error saturates that
        narrow band and limit-cycles;

        the offset limit is part of the control design and not a safety margin, because the
        measured response is non-monotone -- drift falls from +1.02 mm/s at zero offset
        through zero near 0.055 rad but is +1.40 mm/s at 0.12 rad, worse than no control --
        so both the proportional term and the wound-up integral have to stay inside the
        first monotone branch;

        there is deliberately no rate term, because differentiating thorax pose over a
        millisecond step measures contact jitter rather than drift, and the smallest rate
        gain Track A swept moved the body 5.9 mm instead of 0.36 mm.

        Provenance E. No biological content.
        """
        proportional = self.parameters.station_keeping_gain_rad_per_mm
        integral = self.parameters.station_keeping_integral_rad_per_mm_s
        yaw_proportional = self.parameters.station_keeping_yaw_gain_rad_per_rad
        yaw_integral = self.parameters.station_keeping_yaw_integral_rad_per_rad_s
        if not any((proportional, integral, yaw_proportional, yaw_integral)):
            self._reset_station_keeping()
            return
        x_mm, y_mm, _, heading_rad = self.pose()
        if self._station_reference is None:
            # Latch where standing began, so the fly holds where it stopped rather than
            # being pulled back toward its spawn.
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
            yaw_proportional * yaw_error_rad
            + yaw_integral * self._station_yaw_integral_rad_s,
            yaw_limit,
        )
        for index, sign in self._station_keeping_channel:
            targets[index] += _clamp(common + sign * differential, limit)
        self._station_offsets_rad = (common, differential)
        self._station_error_mm = math.hypot(delta_x, delta_y)
        self._station_peak_error_mm = max(
            self._station_peak_error_mm, self._station_error_mm
        )

    def station_keeping(self) -> dict[str, Any]:
        """What the controller did, for the run summary."""
        return {
            "settle_us": self._station_settle_us,
            "held_pose_error_mm": self._station_error_mm,
            "peak_pose_error_mm": self._station_peak_error_mm,
            "common_offset_rad": self._station_offsets_rad[0],
            "differential_offset_rad": self._station_offsets_rad[1],
            "provenance": "E",
            "ported_from": "Track A, docs/evidence/TRACK_A_STATION_KEEPING.md",
            "why": (
                "Without it a body commanded to stand travelled 6.675 mm and rotated 81 "
                "degrees in three seconds with zero commands issued, which is more than "
                "the run it was supposed to be a control for."
            ),
        }

    def _apply_physics_action(self) -> None:
        from flygym_demo.complex_terrain.hybrid_controller import HybridControllerObservation

        forward = min(1.0, max(0.0, self._command[COMMAND_FORWARD]))
        turn = min(1.0, max(-1.0, self._command[COMMAND_YAW]))
        descending = np.clip(
            np.array([forward - turn, forward + turn], dtype=np.float64), -1.0, 1.0
        )
        if bool(np.allclose(descending, 0.0)):
            targets = self._standing_targets.copy()
            self._apply_station_keeping(targets)
            adhesion = np.ones(6, dtype=bool)
        else:
            self._release_station_reference()
            observation = HybridControllerObservation.from_sim(
                self._simulation, self._fly_name
            )
            action = self._controller.step(descending, observation)
            targets = self._neutral_targets.copy()
            targets[: len(self._leg_dofs)] = action.joint_angles
            adhesion = action.adhesion_onoff
        self._simulation.set_actuator_inputs(self._fly_name, self._actuator_type, targets)
        self._simulation.set_leg_adhesion_states(self._fly_name, adhesion)

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step the body backward from {self._t_us} to {t_us}")
        if (t_us - self._t_us) % self.parameters.physics_dt_us:
            raise CausalityError("Body boundary is not aligned to the physics step")
        while self._t_us < t_us:
            self._apply_physics_action()
            self._simulation.step()
            self._t_us += self.parameters.physics_dt_us
        x_mm, y_mm, _, heading = self.pose()
        self._trajectory.append((self._t_us, x_mm, y_mm, heading))

    # -- rendering ----------------------------------------------------------------

    def render_frame(self, *, cue_visible: bool = True) -> np.ndarray:
        """One RGB frame framing both the fly and the cue, with the cue drawn in.

        The camera is a free camera aimed at the midpoint between the fly and the cue and
        pulled back far enough to hold both, rather than the body-fixed tracking camera,
        which sits close enough that the object the fly is reacting to is off screen. A
        demonstration whose stimulus is not visible does not show what it claims to.

        The cue is added as a viewer-scene geom rather than a model body, so the physics
        the fly experiences is identical whether or not a frame is rendered. Nothing the
        renderer does can influence the simulation.
        """
        mujoco = self._mujoco
        if self._renderer is None:
            height, width = self._camera_resolution
            self._renderer = mujoco.Renderer(
                self._simulation.mj_model, height=height, width=width
            )
        x_mm, y_mm, z_mm, heading = self.pose()
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(self._simulation.mj_model, camera)
        cue_x, cue_y = self.parameters.cue_x_mm, self.parameters.cue_y_mm
        separation = math.hypot(cue_x - x_mm, cue_y - y_mm)
        camera.lookat[:] = (
            0.5 * (x_mm + cue_x),
            0.5 * (y_mm + cue_y),
            max(1.0, 0.5 * (z_mm + self.parameters.cue_height_mm)),
        )
        # Enough distance to hold both, with a floor so the shot does not collapse onto
        # the fly when it arrives.
        camera.distance = max(7.0, 1.15 * separation + 2.5 * self.parameters.cue_radius_mm)
        # Look along the fly's heading from behind and above, so a turn is visible as a
        # turn rather than as a translation across frame.
        camera.azimuth = math.degrees(heading) + 150.0
        camera.elevation = -26.0
        self._renderer.update_scene(self._simulation.mj_data, camera=camera)
        if cue_visible:
            self._add_cue_geom()
        return np.asarray(self._renderer.render())

    def _add_cue_geom(self) -> None:
        mujoco = self._mujoco
        assert self._renderer is not None
        scene = self._renderer.scene
        if scene.ngeom >= scene.maxgeom:
            return
        geom = scene.geoms[scene.ngeom]
        radius = self.parameters.cue_radius_mm
        mujoco.mjv_initGeom(
            geom,
            type=mujoco.mjtGeom.mjGEOM_SPHERE,
            size=np.array([radius, radius, radius], dtype=np.float64),
            pos=np.array(
                [
                    self.parameters.cue_x_mm,
                    self.parameters.cue_y_mm,
                    self.parameters.cue_height_mm,
                ],
                dtype=np.float64,
            ),
            mat=np.eye(3, dtype=np.float64).reshape(9),
            # A dark object, because the OFF pathway is what the encoder drives.
            rgba=np.array([0.12, 0.12, 0.16, 1.0], dtype=np.float32),
        )
        geom.category = mujoco.mjtCatBit.mjCAT_DECOR
        scene.ngeom += 1

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "FlyGym 2.1 / MuJoCo 3.9",
            "walking_controller": "flygym_demo HybridTurningController",
            "physics_dt_us": self.parameters.physics_dt_us,
            "cue_xy_mm": [self.parameters.cue_x_mm, self.parameters.cue_y_mm],
            "cue_radius_mm": self.parameters.cue_radius_mm,
            "provenance": "E",
            "station_keeping": self.station_keeping(),
            "scaffolds": list(SCAFFOLDS),
            "sensor_channels_published": [],
            "why_no_sensor_channels": (
                "The body publishes no odour, sucrose, contamination or touch value. The "
                "only world quantity is the cue's geometry, and it reaches the brain "
                "solely through the retinotopic lamina encoder, so there is no sensory "
                "channel a controller could shortcut through."
            ),
        }


__all__ = ["SCAFFOLDS", "Demo01BodyParameters", "Demo01VisualBody"]
