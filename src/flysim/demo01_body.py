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
from flysim.errors import CausalityError, ConfigurationError

# Every engineered stand-in this body relies on, named so the video and the artifact can
# both print them rather than implying a biological locomotor system.
SCAFFOLDS: tuple[str, ...] = (
    "FlyGym HybridTurningController: a published engineered central pattern generator "
    "driven by two normalised descending drives. It is not a VNC model and no part of the "
    "simulated VNC contributes to leg movement.",
    "Leg adhesion at a fixed gain, which no fly possesses as a switchable actuator.",
    "A female NeuroMechFly body prior driven by a male CNS graph.",
    "Standing is holding the default leg pose with adhesion engaged, not a postural "
    "control system.",
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

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Demo01BodyParameters:
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
        )
        if values.physics_dt_us <= 0:
            raise ConfigurationError("Physics timestep must be positive")
        if values.cue_radius_mm <= 0.0:
            raise ConfigurationError("Cue radius must be positive")
        if values.max_forward_mm_s <= 0.0 or values.max_yaw_rad_s <= 0.0:
            raise ConfigurationError("Command normalisation scales must be positive")
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

    def _apply_physics_action(self) -> None:
        from flygym_demo.complex_terrain.hybrid_controller import HybridControllerObservation

        forward = min(1.0, max(0.0, self._command[COMMAND_FORWARD]))
        turn = min(1.0, max(-1.0, self._command[COMMAND_YAW]))
        descending = np.clip(
            np.array([forward - turn, forward + turn], dtype=np.float64), -1.0, 1.0
        )
        if bool(np.allclose(descending, 0.0)):
            targets = self._standing_targets.copy()
            adhesion = np.ones(6, dtype=bool)
        else:
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
