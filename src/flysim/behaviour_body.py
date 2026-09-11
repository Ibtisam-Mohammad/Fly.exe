# SPDX-License-Identifier: GPL-2.0-or-later
"""One body for three behaviours, with the actuated joint set declared per experiment.

`Demo01VisualBody` actuates 42 leg degrees of freedom and nothing else. Every other joint a
fly has -- head, antennae, proboscis, wings, halteres, abdomen -- already exists in this
model's kinematic tree as a passive spring-damper hinge, because the skeleton is built with
``JointPreset.ALL_BIOLOGICAL``. Grooming and feeding were therefore never blocked by the
model: they were blocked by a missing ``add_actuators`` call.

**Why the joint set is per experiment and not global.** `demo01-visual-lateral.json` records
that DEMO-01's 0.12 station-keeping integral gain was doubled relative to Track A
*because that body actuates legs only*. That gain, the 2.294 mm residual standing drift, and
the +11.5 degree drift bearing that chose DEMO-01's cue placement are all properties of a
42-actuator plant. Actuating 51 joints everywhere would silently void all three. So each
behaviour declares the joints it needs, an actuator-set digest goes into every recording, and
no threshold derived on one plant may be reused on another.

**A defect this fixes rather than inherits.** In Track A's body a grooming command forces the
standing branch, so station keeping writes the femur-tibia pitch of all six legs -- and then
the grooming replay overwrites the two front ones, because the published trajectory drives
exactly those joints. Two of six control channels were computed and discarded every step
while the integral kept accumulating their full error, and the channel's authority was
measured with six planted legs when a bout stands on four. Here the channel is rebuilt from
the legs that are actually adhered and not overwritten. That is `MOTOR-05`, attempt 2.

**What the body does not do.** It publishes world quantities and it accepts commands. It
never computes a behaviour, never reads a decoder state, and no sensor value it publishes
reaches an actuator except by going through the network. `qpos` stays 133 whatever the
actuator set, so recordings remain replayable.

Provenance E for every controller here. The scaffolds are named in `SCAFFOLDS`.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from flysim.contracts import ActuatorCommandFrame, SensorFrame, SignalType
from flysim.engines.body import (
    COMMAND_FORWARD,
    COMMAND_GROOM,
    COMMAND_JUMP,
    COMMAND_PROBOSCIS,
    COMMAND_WING_DEPRESSION,
    COMMAND_YAW,
)
from flysim.engines.flygym import (
    STATION_KEEPING_DOF,
    STATION_KEEPING_LEFT_LEGS,
    STATION_KEEPING_LEGS,
    _clamp,
)
from flysim.errors import CausalityError, ConfigurationError

LEGS: tuple[str, ...] = ("lf", "lm", "lh", "rf", "rm", "rh")
#: The tergotrochanteral muscle inserts on the mesothoracic leg, and the release annotates
#: both TTMn and PSI as somaNeuromere T2. So a jump extends the middle legs.
JUMP_LEGS: tuple[str, ...] = ("lm", "rm")
FRONT_LEGS: tuple[str, ...] = ("lf", "rf")
#: The legs the release puts taste bristles on, by entry nerve: ProLN 8 on the front pair
#: and MetaLN 62 on the hind pair. None on the middle legs, so none are sampled there.
TASTE_LEGS: tuple[str, ...] = ("lf", "rf", "lh", "rh")

BEHAVIOURS: tuple[str, ...] = ("grooming", "feeding", "escape")

SENSOR_ANTENNA_DEFLECTION = "world:antenna-deflection:{side}"
SENSOR_LEG_CONTACT = "world:leg-contact:{leg}"
SENSOR_TARSAL_SUCROSE = "world:tarsal-sucrose:{leg}"
SENSOR_ANGULAR_VELOCITY = "world:body-angular-velocity:{axis}"
SENSOR_GRAVITY = "world:gravity-in-body-frame:{axis}"

SCAFFOLDS: tuple[str, ...] = (
    "FlyGym HybridTurningController: a published engineered central pattern generator "
    "driven by two normalised descending drives. It is not a VNC model, and no part of the "
    "simulated ventral cord contributes to leg movement.",
    "Leg adhesion at a fixed gain, which no fly possesses as a switchable actuator.",
    "A female NeuroMechFly body prior driven by a male CNS graph.",
    "Standing is a proportional-integral controller holding thorax pose through femur-tibia "
    "pitch. A fly does this with load-sensing sensilla and chordotonal reflexes distributed "
    "through the ventral cord, and nothing in a fly resembles one pose estimate driving "
    "several joints in common mode.",
    "Grooming movement is a replayed published trajectory from a tethered fly (Ozdil 2026 "
    "Fig 1C, checksum-locked). The network decides whether and how strongly to groom; it "
    "does not produce the movement, and a viewer must not read it as having done so.",
    "Feeding is a proboscis pose. NeuroMechFly has no labellum, no labrum and no pharynx, "
    "so there is no ingestion, no pumping and nothing to taste with at the mouth.",
    "A jump is a position ramp on two leg joints with adhesion released. The "
    "tergotrochanteral muscle is a single high-power twitch muscle and this is a servo.",
    "Wing motion generates exactly zero aerodynamic force: this model sets no density, no "
    "viscosity and carries no fluid geoms. All height in a takeoff comes from leg extension "
    "against the floor.",
    "The compiled world carries no light source, so nothing casts a shadow.",
)


@dataclass(frozen=True, slots=True)
class BehaviourBodyParameters:
    """Body geometry, controller gains, and the declared bindings of each command."""

    physics_dt_us: int = 500
    initial_x_mm: float = 0.0
    initial_y_mm: float = 0.0
    initial_heading_rad: float = 0.0
    spawn_height_mm: float = 0.5

    # Station keeping, ported from Track A and re-derived per actuator set.
    station_keeping_gain_rad_per_mm: float = 0.02
    station_keeping_integral_rad_per_mm_s: float = 0.12
    station_keeping_yaw_gain_rad_per_rad: float = 0.05
    station_keeping_yaw_integral_rad_per_rad_s: float = 0.4
    station_keeping_max_offset_rad: float = 0.07
    station_keeping_max_yaw_offset_rad: float = 0.02
    station_keeping_settle_us: int = 2_000_000

    # Grooming. Blend-in exists because snapping a free-standing body onto a tethered
    # fly's first sample delivers an impulse through the stance legs.
    groom_blend_in_us: int = 200_000

    # Feeding, Track A's registered extensions.
    feed_rostrum_extension_rad: float = 0.6
    feed_haustellum_extension_rad: float = 0.8

    # Escape. The joint and the sign were measured, not guessed: with adhesion released,
    # every candidate middle-leg joint was ramped to +/-0.8 and +/-1.4 rad and the peak
    # thorax rise recorded. Femur-tibia pitch at +1.4 gave 1.465 mm and 285 ms airborne;
    # the same joint at -1.4 gave 0.088 mm, coxa pitch gave 0.080 mm at either sign, and
    # coxa yaw at -0.8 gave 1.222 mm. So the extension is one joint, and it is the one the
    # tergotrochanteral system drives in a real escape. A coxa term is not included,
    # because at 0.08 mm it would be decoration.
    jump_femur_extension_rad: float = 1.4
    #: How long the extension target takes to travel, measured as a controller-only
    #: envelope with no network attached (Phase 0d). Airborne time against ramp and
    #: extension, in microseconds of the longest unbroken airborne streak:
    #:
    #:     ramp us |  1.0 rad   1.4 rad   1.8 rad
    #:           0 |    12000     23000     15000
    #:        5000 |    15000     90000      7000
    #:       15000 |    12500    148000      4000
    #:       30000 |    12000     21000      3000
    #:       60000 |    12500     15500      5000
    #:
    #: It is strongly non-monotone in extension: 1.8 rad is worse than 1.0 rad at every
    #: ramp, because over-extension folds the leg instead of pushing with it. So this pair
    #: is a tuned operating point of an engineering scaffold, in the same way Track A's
    #: station-keeping offset limit is, and it is reported as one rather than as a property
    #: of the body. The standing contact-chatter floor measured alongside it is 5.0 to
    #: 5.5 ms, which is what the 20 ms airborne criterion has to clear.
    jump_ramp_us: int = 15_000
    wing_depression_rad: float = 0.8

    # The sucrose patch. Contact is real; only the concentration is invented.
    sucrose_x_mm: float = 3.0
    sucrose_y_mm: float = 0.0
    sucrose_radius_mm: float = 1.2
    sucrose_concentration: float = 1.0

    # The antennal stimulus: a scripted mechanical deflection, one side at a time.
    antennal_stimulus_side: str = "L"
    antennal_stimulus_onset_us: int = 1_500_000
    antennal_stimulus_duration_us: int = 3_000_000
    antennal_stimulus_torque: float = 6.0e-5

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> BehaviourBodyParameters:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        values = cls(**known)
        if values.physics_dt_us <= 0:
            raise ConfigurationError("The physics step must be positive")
        if values.antennal_stimulus_side not in {"L", "R", "none"}:
            raise ConfigurationError("The antennal stimulus side must be L, R or none")
        if values.sucrose_radius_mm <= 0:
            raise ConfigurationError("The sucrose patch needs a positive radius")
        return values


#: Which joints each behaviour actuates beyond the legs, as (child segment, axes) pairs.
#: Declared per behaviour rather than globally: actuating all of them everywhere would
#: change the plant under DEMO-01's calibration without changing anything visible.
SPECIAL_DOFS: dict[str, tuple[tuple[frozenset[str], frozenset[str]], ...]] = {
    # Head and antennal pedicels: the joints the published grooming trajectory drives.
    "grooming": (
        (frozenset({"c_head"}), frozenset({"roll", "pitch", "yaw"})),
        (frozenset({"l_pedicel", "r_pedicel"}), frozenset({"pitch", "yaw"})),
    ),
    # Rostrum and haustellum. There is no labellum in this model, which is why feeding
    # can only be a pose.
    "feeding": (
        (frozenset({"c_rostrum", "c_haustellum"}), frozenset({"pitch"})),
        (frozenset({"c_head"}), frozenset({"pitch"})),
    ),
    # Wings, which move and generate no force whatsoever.
    "escape": ((frozenset({"l_wing", "r_wing"}), frozenset({"pitch", "roll", "yaw"})),),
}


def _special_dofs(behaviour: str, skeleton: Any) -> list[Any]:
    """The joints this behaviour needs beyond the legs, and no others."""
    try:
        wanted = SPECIAL_DOFS[behaviour]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown behaviour: {behaviour}") from exc
    return [
        dof
        for dof in skeleton.iter_jointdofs()
        if any(
            dof.child.name in children and dof.axis.value in axes
            for children, axes in wanted
        )
    ]


@dataclass
class BehaviourBody:
    """NeuroMechFly on flat ground, actuated for exactly one behaviour."""

    parameters: BehaviourBodyParameters
    behaviour: str
    seed: int
    trajectory_path: Path | None = None
    camera_resolution: tuple[int, int] = (720, 1280)
    _state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
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

        if self.behaviour not in BEHAVIOURS:
            raise ConfigurationError(f"Unknown behaviour: {self.behaviour}")
        self._mujoco = mujoco
        parameters = self.parameters
        neutral_pose = KinematicPosePreset.NEUTRAL.get_pose_by_axis_order(
            AxisOrder.YAW_PITCH_ROLL
        )
        skeleton = Skeleton(
            axis_order=AxisOrder.YAW_PITCH_ROLL, joint_preset=JointPreset.ALL_BIOLOGICAL
        )
        fly_name = f"{self.behaviour}_fly"
        fly = NeuroMechFly(name=fly_name)
        fly.add_joints(skeleton, neutral_pose=neutral_pose)
        leg_dofs = skeleton.get_actuated_dofs_from_preset(ActuatedDOFPreset.LEGS_ACTIVE_ONLY)
        special = _special_dofs(self.behaviour, skeleton)
        requested = [*leg_dofs, *special]
        fly.add_actuators(
            requested,
            ActuatorType.POSITION,
            neutral_input=neutral_pose,
            kp=45.0,
            forcerange=(-65.0, 65.0),
        )
        fly.add_leg_adhesion(gain=40.0)
        fly.colorize()
        camera = fly.add_tracking_camera(name=f"{self.behaviour}_camera")
        world = FlatGroundWorld(half_size=100.0)
        half_yaw = parameters.initial_heading_rad / 2.0
        world.add_fly(
            fly,
            spawn_position=np.array([
                parameters.initial_x_mm, parameters.initial_y_mm, parameters.spawn_height_mm
            ]),
            spawn_rotation=Rotation3D(
                "quat", (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
            ),
        )
        simulation = Simulation(world, timestep=parameters.physics_dt_us / 1_000_000.0)
        controller = HybridTurningController(
            timestep=parameters.physics_dt_us / 1_000_000.0, output_dof_order=leg_dofs
        )
        controller.reset(seed=self.seed)

        self._fly_name = fly_name
        self._fly = fly
        self._camera_name = camera.name
        self._simulation = simulation
        self._controller = controller
        self._actuator_type = ActuatorType.POSITION
        self._leg_dofs = leg_dofs
        self._actuated_dofs = fly.get_actuated_jointdofs_order(ActuatorType.POSITION)
        if list(self._actuated_dofs) != requested:
            raise ConfigurationError(
                "FlyGym returned a different actuator order than was requested, so every "
                "index in this module would point at the wrong joint."
            )
        self._actuator_index = {
            dof.name: index for index, dof in enumerate(self._actuated_dofs)
        }
        body_order = fly.get_bodysegs_order()
        self._thorax_index = body_order.index(type(fly).BODY_SEGMENT_CLASS("c_thorax"))
        self._joint_order = fly.get_jointdofs_order()

        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
        initial = simulation.get_joint_angles(fly_name)
        self._neutral_targets = np.asarray(
            [initial[self._joint_order.index(dof)] for dof in self._actuated_dofs],
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
        self._last_targets = settled.copy()
        self._groom_hold_targets = settled.copy()

        self._pedicel_neutral = self._read_pedicel_angles()
        self._trajectory_columns: dict[str, int] = {}
        self._trajectory: dict[str, np.ndarray] = {}
        self._source_to_actuator: dict[str, int] = {}
        if self.behaviour == "grooming":
            if self.trajectory_path is None:
                raise ConfigurationError(
                    "Grooming needs the checksum-locked Ozdil trajectory derivative"
                )
            from flysim.grooming import load_grooming_trajectory

            self._trajectory = load_grooming_trajectory(self.trajectory_path)
            self._trajectory_columns = {
                str(name): index
                for index, name in enumerate(self._trajectory["column_names"])
            }
            self._source_to_actuator = self._build_source_mapping()

        self._station_reference: tuple[float, float, float] | None = None
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0
        self._station_error_mm = 0.0
        self._station_peak_error_mm = 0.0
        self._station_offsets_rad = (0.0, 0.0)
        self._station_settle_us = 0
        self._station_channel_legs: tuple[str, ...] = ()
        self._converge_station_keeping()
        controller.reset(seed=self.seed, init_magnitudes=np.zeros(6, dtype=np.float64))

        self._command = dict.fromkeys(
            (
                COMMAND_FORWARD, COMMAND_YAW, COMMAND_GROOM, COMMAND_PROBOSCIS,
                COMMAND_JUMP, COMMAND_WING_DEPRESSION,
            ),
            0.0,
        )
        self._groom_started_us: int | None = None
        self._jump_started_us: int | None = None
        self._t_us = 0
        self._renderer: Any | None = None
        self._trajectory_log: list[tuple[int, float, float, float]] = []
        self._airborne_us = 0
        self._longest_airborne_us = 0
        self._peak_thorax_z_mm = self.pose()[2]
        self._standing_thorax_z_mm = self._peak_thorax_z_mm
        self._first_release_us: int | None = None

    # -- identity ----------------------------------------------------------------

    @property
    def actuator_set_digest(self) -> str:
        """A digest of the actuated joint names, stamped into every recording.

        ``qpos`` stays 133 whatever the actuator set, and the replay renderer only checks
        ``qpos`` shape, so a recording made on one plant would replay silently on another.
        Any threshold derived from drift belongs to one digest and no other.
        """
        payload = "\n".join(dof.name for dof in self._actuated_dofs)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def t_us(self) -> int:
        return self._t_us

    # -- world quantities --------------------------------------------------------

    def _read_pedicel_angles(self) -> dict[str, float]:
        angles = self._simulation.get_joint_angles(self._fly_name)
        out: dict[str, float] = {}
        for side in ("l", "r"):
            total = 0.0
            for axis in ("pitch", "yaw"):
                name = f"c_head-{side}_pedicel-{axis}"
                match = [d for d in self._joint_order if d.name == name]
                if match:
                    total += float(angles[self._joint_order.index(match[0])])
            out[side] = total
        return out

    def _antennal_deflection(self) -> dict[str, float]:
        """Radians of pedicel displacement from the settled pose. Real physics.

        Johnston's organ responds to antennal displacement, and the antenna is a real
        hinge in this model, so the grooming stimulus needs no invented dust field.
        """
        now = self._read_pedicel_angles()
        return {
            side: abs(now[side] - self._pedicel_neutral[side]) for side in ("l", "r")
        }

    def _leg_contact(self) -> dict[str, float]:
        found, *_ = self._simulation.get_ground_contact_info(self._fly_name)
        flags = np.asarray(found).reshape(len(LEGS), -1).any(axis=1)
        return {leg: float(bool(flags[index])) for index, leg in enumerate(LEGS)}

    def _tarsal_sucrose(self, contact: dict[str, float]) -> dict[str, float]:
        """Concentration at a taste-bearing tarsus, gated on real contact with the patch.

        The gate is physics: the tarsus has to be both on the ground and inside the patch.
        Only the concentration is declared, which is strictly stronger than a
        distance-to-food threshold that does not require touching anything.
        """
        positions = self._simulation.get_body_positions(self._fly_name)
        order = self._fly.get_bodysegs_order()
        out: dict[str, float] = {}
        for leg in TASTE_LEGS:
            segment = type(self._fly).BODY_SEGMENT_CLASS(f"{leg}_tarsus5")
            try:
                index = order.index(segment)
            except ValueError:
                out[leg] = 0.0
                continue
            x, y = float(positions[index][0]), float(positions[index][1])
            inside = math.hypot(
                x - self.parameters.sucrose_x_mm, y - self.parameters.sucrose_y_mm
            ) <= self.parameters.sucrose_radius_mm
            touching = contact.get(leg, 0.0) > 0.0
            out[leg] = (
                self.parameters.sucrose_concentration if inside and touching else 0.0
            )
        return out

    def sample_sensors(self) -> SensorFrame:
        """Every world quantity this body publishes, with its kind declared per channel."""
        deflection = self._antennal_deflection()
        contact = self._leg_contact()
        sucrose = self._tarsal_sucrose(contact)
        qvel = np.asarray(self._simulation.mj_data.qvel)
        angular = {
            "roll": float(qvel[3]) if qvel.size > 5 else 0.0,
            "pitch": float(qvel[4]) if qvel.size > 5 else 0.0,
            "yaw": float(qvel[5]) if qvel.size > 5 else 0.0,
        }
        quaternion = self._simulation.get_body_rotations(self._fly_name)[self._thorax_index]
        w, x, y, z = (float(v) for v in quaternion)
        gravity = {
            "roll": math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)),
            "pitch": math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x)))),
        }

        ids: list[str] = []
        values: list[float] = []
        units: list[str] = []
        kinds: dict[str, str] = {}

        def add(identifier: str, value: float, unit: str, kind: str) -> None:
            ids.append(identifier)
            values.append(float(value))
            units.append(unit)
            kinds[identifier] = kind

        for side in ("l", "r"):
            add(
                SENSOR_ANTENNA_DEFLECTION.format(side=side),
                deflection[side], "rad", "real",
            )
        for leg in LEGS:
            add(SENSOR_LEG_CONTACT.format(leg=leg), contact[leg], "boolean", "real")
        for leg in TASTE_LEGS:
            add(
                SENSOR_TARSAL_SUCROSE.format(leg=leg),
                sucrose[leg], "normalized", "declared",
            )
        for axis, value in angular.items():
            add(SENSOR_ANGULAR_VELOCITY.format(axis=axis), value, "rad/s", "real")
        for axis, value in gravity.items():
            add(SENSOR_GRAVITY.format(axis=axis), value, "rad", "real")

        return SensorFrame(
            t_us=self._t_us,
            ids=tuple(ids),
            values=tuple(values),
            units=",".join(units),
            signal_type=SignalType.WORLD_QUANTITY,
            provenance="M/E",
            assumption_ids=("SENS-01", "SENS-04", "SENS-05", "BODY-01"),
            metadata={
                "channel_units": dict(zip(ids, units, strict=True)),
                "channel_kind": kinds,
                "real_means": "a quantity MuJoCo computed from the physics",
                "declared_means": (
                    "an invented field. Here only the sucrose concentration: its contact "
                    "gate is real, its concentration is not."
                ),
                "absent_channels": {
                    "temperature": "MuJoCo carries no temperature field",
                    "humidity": "MuJoCo carries no humidity field",
                    "sound": "MuJoCo carries no acoustic field",
                    "wind": "this body has no fluid model at all",
                },
                "body_backend": "FlyGym 2.1 / MuJoCo 3.9, NeuroMechFly",
            },
        )

    # -- pose --------------------------------------------------------------------

    def pose(self) -> tuple[float, float, float, float]:
        position = self._simulation.get_body_positions(self._fly_name)[self._thorax_index]
        quaternion = self._simulation.get_body_rotations(self._fly_name)[self._thorax_index]
        w, x, y, z = (float(value) for value in quaternion)
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return float(position[0]), float(position[1]), float(position[2]), yaw

    def qpos(self) -> np.ndarray:
        return np.array(self._simulation.mj_data.qpos, copy=True)

    def trajectory(self) -> tuple[tuple[int, float, float, float], ...]:
        return tuple(self._trajectory_log)

    # -- commands ----------------------------------------------------------------

    def apply_actuators(self, frame: ActuatorCommandFrame) -> None:
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Actuator timestamp {frame.t_us} does not match body time {self._t_us}"
            )
        previous_groom = self._command[COMMAND_GROOM]
        previous_jump = self._command[COMMAND_JUMP]
        self._command = {
            identifier: frame.value_for(identifier, 0.0) for identifier in self._command
        }
        jump = self._command[COMMAND_JUMP]
        if previous_jump <= 0.0 < jump:
            self._jump_started_us = self._t_us
        elif jump <= 0.0:
            self._jump_started_us = None
        groom = self._command[COMMAND_GROOM]
        if previous_groom <= 0.0 < groom:
            self._groom_started_us = self._t_us
            self._groom_hold_targets = self._last_targets.copy()
        elif groom <= 0.0:
            self._groom_started_us = None

    # -- station keeping ---------------------------------------------------------

    def _build_station_keeping_channel(
        self, adhered: np.ndarray, overwritten: frozenset[str]
    ) -> tuple[tuple[int, float], ...]:
        """Only legs that are planted and whose FTi pitch nobody else is writing.

        This is the MOTOR-05 fix. Track A computed all six channels during a bout and then
        let the grooming replay overwrite the two front ones, so a third of the control
        effort was discarded while the integral kept accumulating its error.
        """
        channel: list[tuple[int, float]] = []
        legs: list[str] = []
        for index, leg in enumerate(STATION_KEEPING_LEGS):
            name = STATION_KEEPING_DOF.format(leg=leg)
            if name in overwritten or not bool(adhered[index]):
                continue
            try:
                actuator = self._actuator_index[name]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Station-keeping channel {name} is not an actuated DOF"
                ) from exc
            channel.append((actuator, 1.0 if leg in STATION_KEEPING_LEFT_LEGS else -1.0))
            legs.append(leg)
        self._station_channel_legs = tuple(legs)
        return tuple(channel)

    def _release_station_reference(self) -> None:
        self._station_reference = None
        self._station_offsets_rad = (0.0, 0.0)

    def _reset_station_keeping(self) -> None:
        self._release_station_reference()
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0

    @staticmethod
    def _clamped_integral(accumulated: float, gain: float, limit: float) -> float:
        if gain == 0.0:
            return 0.0
        bound = abs(limit / gain)
        return min(bound, max(-bound, accumulated))

    def _apply_station_keeping(
        self, targets: np.ndarray, adhered: np.ndarray, overwritten: frozenset[str]
    ) -> None:
        parameters = self.parameters
        proportional = parameters.station_keeping_gain_rad_per_mm
        integral = parameters.station_keeping_integral_rad_per_mm_s
        yaw_proportional = parameters.station_keeping_yaw_gain_rad_per_rad
        yaw_integral = parameters.station_keeping_yaw_integral_rad_per_rad_s
        if not any((proportional, integral, yaw_proportional, yaw_integral)):
            self._reset_station_keeping()
            return
        channel = self._build_station_keeping_channel(adhered, overwritten)
        if not channel:
            # Nothing to act through. Hold the wound-up bias rather than discarding it.
            self._station_offsets_rad = (0.0, 0.0)
            return
        x_mm, y_mm, _, heading_rad = self.pose()
        if self._station_reference is None:
            self._station_reference = (x_mm, y_mm, heading_rad)
            self._station_offsets_rad = (0.0, 0.0)
            self._station_error_mm = 0.0
            return
        reference_x, reference_y, reference_heading = self._station_reference
        delta_x = x_mm - reference_x
        delta_y = y_mm - reference_y
        fore_aft_mm = delta_x * math.cos(reference_heading) + delta_y * math.sin(
            reference_heading
        )
        yaw_error_rad = math.atan2(
            math.sin(heading_rad - reference_heading),
            math.cos(heading_rad - reference_heading),
        )
        limit = parameters.station_keeping_max_offset_rad
        yaw_limit = parameters.station_keeping_max_yaw_offset_rad
        dt_s = parameters.physics_dt_us / 1_000_000.0
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
        for index, sign in channel:
            targets[index] += _clamp(common + sign * differential, limit)
        self._station_offsets_rad = (common, differential)
        self._station_error_mm = math.hypot(delta_x, delta_y)
        self._station_peak_error_mm = max(
            self._station_peak_error_mm, self._station_error_mm
        )

    def _converge_station_keeping(self) -> None:
        mujoco = self._mujoco
        settle_us = self.parameters.station_keeping_settle_us
        if settle_us <= 0:
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
            self._apply_station_keeping(targets, adhered, frozenset())
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

    def station_keeping(self) -> dict[str, Any]:
        return {
            "settle_us": self._station_settle_us,
            "held_pose_error_mm": self._station_error_mm,
            "peak_pose_error_mm": self._station_peak_error_mm,
            "common_offset_rad": self._station_offsets_rad[0],
            "differential_offset_rad": self._station_offsets_rad[1],
            "active_channel_legs": list(self._station_channel_legs),
            "provenance": "E",
            "ported_from": "Track A, docs/evidence/TRACK_A_STATION_KEEPING.md",
            "motor_05_change": (
                "The channel is rebuilt each step from the legs that are adhered and not "
                "overwritten by a replay, instead of always writing all six and letting "
                "two be discarded."
            ),
        }

    # -- behaviour bindings ------------------------------------------------------

    def _build_source_mapping(self) -> dict[str, int]:
        from flygym.anatomy import BodySegment, JointDOF, RotationAxis

        transitions = {
            "ThC": ("c_thorax", "coxa"),
            "CTr": (None, "trochanterfemur"),
            "FTi": (None, "tibia"),
            "TiTa": (None, "tarsus1"),
        }
        parents = {
            "trochanterfemur": "coxa", "tibia": "trochanterfemur", "tarsus1": "tibia",
        }
        mapping: dict[str, int] = {}
        for source_name in self._trajectory_columns:
            parts = source_name.split("_")
            if parts[1] in {"LF", "RF"}:
                leg = parts[1].lower()
                transition, axis = parts[2], parts[3]
                parent_link, child_link = transitions[transition]
                parent = BodySegment(
                    parent_link
                    if parent_link is not None
                    else f"{leg}_{parents[child_link]}"
                )
                dof = JointDOF(parent, BodySegment(f"{leg}_{child_link}"), RotationAxis(axis))
            elif parts[1] == "head":
                dof = JointDOF(
                    BodySegment("c_thorax"), BodySegment("c_head"), RotationAxis(parts[2])
                )
            elif parts[1] == "antenna":
                side = parts[3].lower()
                dof = JointDOF(
                    BodySegment("c_head"),
                    BodySegment(f"{side}_pedicel"),
                    RotationAxis(parts[2]),
                )
            else:
                raise ConfigurationError(f"Unsupported grooming signal: {source_name}")
            index = self._actuator_index.get(dof.name)
            if index is None:
                raise ConfigurationError(
                    f"Published grooming signal has no actuator here: {source_name}"
                )
            mapping[source_name] = index
        return mapping

    def _groom_targets(self, targets: np.ndarray) -> frozenset[str]:
        """Replay the published trajectory, scaled by the decoded intensity."""
        if self._groom_started_us is None or not self._source_to_actuator:
            return frozenset()
        intensity = min(1.0, max(0.0, self._command[COMMAND_GROOM]))
        elapsed_us = self._t_us - self._groom_started_us
        source_time = self._trajectory["time_s"]
        source_angles = self._trajectory["angles_rad"]
        elapsed_s = min(float(source_time[-1]), max(0.0, elapsed_us / 1_000_000.0))
        blend = (
            1.0
            if self.parameters.groom_blend_in_us <= 0
            else min(1.0, elapsed_us / self.parameters.groom_blend_in_us)
        )
        # MOTOR-06: the replay is scaled about the hold pose, so the decoded drive changes
        # how far the legs travel rather than only whether they move at all.
        weight = blend * intensity
        written: set[str] = set()
        for source_name, actuator_index in self._source_to_actuator.items():
            column = self._trajectory_columns[source_name]
            replayed = float(np.interp(elapsed_s, source_time, source_angles[:, column]))
            held = float(self._groom_hold_targets[actuator_index])
            targets[actuator_index] = held + weight * (replayed - held)
            written.add(self._actuated_dofs[actuator_index].name)
        return frozenset(written)

    def _feeding_targets(self, targets: np.ndarray) -> None:
        extension = min(1.0, max(0.0, self._command[COMMAND_PROBOSCIS]))
        if extension <= 0.0:
            return
        for name, amount in (
            ("c_head-c_rostrum-pitch", self.parameters.feed_rostrum_extension_rad),
            ("c_rostrum-c_haustellum-pitch", self.parameters.feed_haustellum_extension_rad),
        ):
            index = self._actuator_index.get(name)
            if index is not None:
                targets[index] = self._neutral_targets[index] + extension * amount

    def _jump_targets(self, targets: np.ndarray) -> bool:
        """Extend the middle legs against the floor. Returns whether adhesion is released.

        TTMn and PSI are both annotated somaNeuromere T2, so the jump acts on the
        mesothoracic pair. This is a position ramp, not a muscle.
        """
        commanded = min(1.0, max(0.0, self._command[COMMAND_JUMP]))
        if commanded <= 0.0:
            return False
        # Ramp the target rather than stepping it. A step is not more impulsive here: it
        # saturates the position servo against a leg that has not yet loaded, and the
        # envelope sweep measured 23 ms of airborne time for a step against 148 ms for a
        # one-interval ramp at the same extension.
        ramp_us = self.parameters.jump_ramp_us
        if self._jump_started_us is None or ramp_us <= 0:
            fraction = 1.0
        else:
            fraction = min(1.0, (self._t_us - self._jump_started_us) / ramp_us)
        extension = commanded * fraction
        for leg in JUMP_LEGS:
            name = STATION_KEEPING_DOF.format(leg=leg)
            index = self._actuator_index.get(name)
            if index is not None:
                targets[index] = (
                    self._neutral_targets[index]
                    + extension * self.parameters.jump_femur_extension_rad
                )
        return True

    def _wing_targets(self, targets: np.ndarray) -> None:
        """Move the wings toward depression. Generates exactly zero lift; see SCAFFOLDS."""
        depression = min(1.0, max(0.0, self._command[COMMAND_WING_DEPRESSION]))
        if depression <= 0.0:
            return
        for side in ("l", "r"):
            index = self._actuator_index.get(f"c_thorax-{side}_wing-pitch")
            if index is not None:
                targets[index] = (
                    self._neutral_targets[index]
                    + depression * self.parameters.wing_depression_rad
                )

    # -- stimulus ----------------------------------------------------------------

    def _apply_antennal_stimulus(self) -> bool:
        """A scripted mechanical torque on one antenna. The world, not the brain.

        This is the grooming stimulus: a real force on a real hinge, replacing Track A's
        invented contamination scalar, which the arbiter read directly into its transition
        rule. Returns whether the stimulus is currently on.
        """
        parameters = self.parameters
        if parameters.antennal_stimulus_side == "none":
            return False
        onset = parameters.antennal_stimulus_onset_us
        if not onset <= self._t_us < onset + parameters.antennal_stimulus_duration_us:
            return False
        side = parameters.antennal_stimulus_side.lower()
        order = self._fly.get_bodysegs_order()
        segment = type(self._fly).BODY_SEGMENT_CLASS(f"{side}_funiculus")
        try:
            index = order.index(segment)
        except ValueError:
            return False
        data = self._simulation.mj_data
        model = self._simulation.mj_model
        body_id = model.body(f"{self._fly_name}/{segment.name}").id if hasattr(
            model, "body"
        ) else index
        data.xfrc_applied[body_id, 3] = parameters.antennal_stimulus_torque
        return True

    def _clear_antennal_stimulus(self) -> None:
        self._simulation.mj_data.xfrc_applied[:, :] = 0.0

    # -- stepping ----------------------------------------------------------------

    def _apply_physics_action(self) -> None:
        from flygym_demo.complex_terrain.hybrid_controller import HybridControllerObservation

        forward = min(1.0, max(0.0, self._command[COMMAND_FORWARD]))
        turn = min(1.0, max(-1.0, self._command[COMMAND_YAW]))
        behaving = any(
            self._command[key] > 0.0
            for key in (COMMAND_GROOM, COMMAND_PROBOSCIS, COMMAND_JUMP)
        )
        if behaving:
            descending = np.zeros(2, dtype=np.float64)
        else:
            descending = np.clip(
                np.array([forward - turn, forward + turn], dtype=np.float64), -1.0, 1.0
            )
        standing = bool(np.allclose(descending, 0.0))
        if standing:
            action = None
            targets = self._standing_targets.copy()
        else:
            self._release_station_reference()
            observation = HybridControllerObservation.from_sim(
                self._simulation, self._fly_name
            )
            action = self._controller.step(descending, observation)
            targets = self._neutral_targets.copy()
            targets[: len(self._leg_dofs)] = action.joint_angles

        overwritten = self._groom_targets(targets)
        self._feeding_targets(targets)
        self._wing_targets(targets)
        jumping = self._jump_targets(targets)

        if jumping:
            adhesion = np.zeros(6, dtype=bool)
        elif self._command[COMMAND_GROOM] > 0.0:
            # Front legs leave the ground to reach the antennae.
            adhesion = np.array([False, True, True, False, True, True], dtype=bool)
        elif action is None:
            adhesion = np.ones(6, dtype=bool)
        else:
            adhesion = action.adhesion_onoff

        if standing and not jumping:
            self._apply_station_keeping(targets, adhesion, overwritten)

        self._last_targets = targets.copy()
        self._simulation.set_actuator_inputs(self._fly_name, self._actuator_type, targets)
        self._simulation.set_leg_adhesion_states(self._fly_name, adhesion)

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step the body backward from {self._t_us} to {t_us}")
        if (t_us - self._t_us) % self.parameters.physics_dt_us:
            raise CausalityError("Body boundary is not aligned to the physics step")
        while self._t_us < t_us:
            self._clear_antennal_stimulus()
            self._apply_antennal_stimulus()
            self._apply_physics_action()
            self._simulation.step()
            self._t_us += self.parameters.physics_dt_us
            contact = self._leg_contact()
            airborne = not any(value > 0.0 for value in contact.values())
            if airborne:
                self._airborne_us += self.parameters.physics_dt_us
                # The longest unbroken streak, not the current one: a criterion asking
                # whether the fly left the ground must not be answered by whatever
                # happened to be true when the recording stopped.
                self._longest_airborne_us = max(
                    self._longest_airborne_us, self._airborne_us
                )
                if self._first_release_us is None:
                    self._first_release_us = self._t_us
            else:
                self._airborne_us = 0
            self._peak_thorax_z_mm = max(self._peak_thorax_z_mm, self.pose()[2])
        x_mm, y_mm, _, heading = self.pose()
        self._trajectory_log.append((self._t_us, x_mm, y_mm, heading))

    # -- readout -----------------------------------------------------------------

    def takeoff(self) -> dict[str, Any]:
        """What the body did vertically, for the escape criteria."""
        return {
            "standing_thorax_z_mm": self._standing_thorax_z_mm,
            "peak_thorax_z_mm": self._peak_thorax_z_mm,
            "z_rise_mm": self._peak_thorax_z_mm - self._standing_thorax_z_mm,
            "longest_airborne_us": self._longest_airborne_us,
            "airborne_us_at_end": self._airborne_us,
            "first_all_legs_released_us": self._first_release_us,
            "no_aerodynamic_force_was_computed": True,
            "why": (
                "This model sets no density and no viscosity and carries no fluid geoms, "
                "so wing motion produces no force. All height is leg extension."
            ),
        }

    def metrics(self) -> dict[str, Any]:
        """Body quantities the acceptance criteria score, all read from the physics.

        Every one is *achieved* rather than commanded. A criterion scored on a command is
        satisfied by issuing the command, which is not the same as the body moving: a
        position servo working against a passive hinge can be told to extend and not go
        anywhere.
        """
        angles = self._simulation.get_joint_angles(self._fly_name)

        def angle(name: str) -> float:
            match = [d for d in self._joint_order if d.name == name]
            return float(angles[self._joint_order.index(match[0])]) if match else 0.0

        proboscis = abs(angle("c_head-c_rostrum-pitch")) + abs(
            angle("c_rostrum-c_haustellum-pitch")
        )
        excursion = 0.0
        if self._source_to_actuator:
            deviations = [
                abs(
                    angle(self._actuated_dofs[index].name)
                    - float(self._groom_hold_targets[index])
                )
                for index in self._source_to_actuator.values()
            ]
            excursion = float(np.mean(deviations)) if deviations else 0.0
        return {
            "proboscis_rad": proboscis,
            "groom_excursion_rad": excursion,
            "tarsus_arista_mm": self._tarsus_arista_distance_mm(),
            "thorax_z_mm": self.pose()[2],
        }

    def _tarsus_arista_distance_mm(self) -> float:
        """Closest approach between either front tarsus tip and either arista tip.

        This is what distinguishes a leg that reaches the antenna from a leg that waves.
        A replayed trajectory will move the joints whatever happens, so the criterion has
        to ask about the geometry rather than about the angles.
        """
        order = self._fly.get_bodysegs_order()
        positions = self._simulation.get_body_positions(self._fly_name)

        def point(name: str) -> np.ndarray | None:
            segment = type(self._fly).BODY_SEGMENT_CLASS(name)
            try:
                return np.asarray(positions[order.index(segment)], dtype=np.float64)
            except ValueError:
                return None

        best = math.inf
        for leg in FRONT_LEGS:
            tarsus = point(f"{leg}_tarsus5")
            if tarsus is None:
                continue
            for side in ("l", "r"):
                arista = point(f"{side}_arista")
                if arista is None:
                    continue
                best = min(best, float(np.linalg.norm(tarsus - arista)))
        return best

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "FlyGym-2.1-MuJoCo-3.9-NeuroMechFly",
            "behaviour": self.behaviour,
            "parameters": asdict(self.parameters),
            "actuated_dofs": [dof.name for dof in self._actuated_dofs],
            "actuated_dof_count": len(self._actuated_dofs),
            "actuator_set_digest": self.actuator_set_digest,
            "leg_dof_count": len(self._leg_dofs),
            "qpos_size": int(self._simulation.mj_data.qpos.size),
            "female_body_prior": True,
            "scaffolds": list(SCAFFOLDS),
            "sensor_channels_published": list(self.sample_sensors().ids),
            "station_keeping": self.station_keeping(),
            "grooming_trajectory": (
                {
                    "source": "Ozdil-2026-Fig1-panel-C",
                    "signals": len(self._trajectory_columns),
                    "mapped_actuators": len(self._source_to_actuator),
                }
                if self._source_to_actuator
                else None
            ),
        }

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
