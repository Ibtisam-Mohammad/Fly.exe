# SPDX-License-Identifier: GPL-2.0-or-later
"""Many NeuroMechFly bodies in one MuJoCo scene, with objects they can walk into.

Why this exists. The multi-fly runtime in `flysim.multifly` puts every agent on a
`SharedKinematicArena`: a disc that is integrated forward from a forward speed and a yaw
rate. That arena was built to answer a capacity question -- can one GPU hold N independent
165,122-neuron states over one connectivity allocation -- and it answers it honestly. It
cannot answer an embodiment question, because it has no legs, no ground, no contact and no
three-dimensional scene. A video rendered from it is a diagram of a disc, whatever is drawn
on top.

This module is the embodied counterpart. It builds one `FlatGroundWorld` holding N
NeuroMechFly bodies and the objects between them, each fly driven exactly the way DEMO-01
drives its single fly: two normalised descending drives into the published
`HybridTurningController`, a standing controller ported from Track A when both drives are
zero, and leg adhesion at a fixed gain. `tests/test_swarm3d.py` runs one fly through this
world and through `Demo01VisualBody` under the same command sequence and requires the two
trajectories to agree, so the duplication is checked rather than asserted.

Three things are worth stating about what the scene is.

**The objects are real.** Food spheres and obstacle pillars are geoms in the compiled
model with explicit contact pairs against the same body segments the ground touches, so a
fly that walks into a pillar is stopped by the solver rather than by a rule. They are not
viewer decorations, which is what DEMO-01's single cue is.

**The flies are visible to each other.** Each fly is presented to every other fly's
retinotopic encoder as a sphere of one declared radius. That is a scaffold, and it is
declared: a fly is not a sphere, and nothing here models how a fly looks to a fly.

**Rendering still cannot touch the simulation.** `render_replay_frame` refuses on a world
that has been stepped, exactly as DEMO-01's does, so the only thing that can be drawn is a
world that has never simulated anything and is having recorded states written into it.

Provenance E for everything in this file. There is no biological content in a ground
plane, a light, or a contact pair.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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

# Every engineered stand-in this world relies on. The video prints these verbatim, so a
# viewer is told what is a model and what is a prop before being shown either.
SCAFFOLDS: tuple[str, ...] = (
    "FlyGym HybridTurningController: a published engineered central pattern generator "
    "driven by two normalised descending drives. It is not a VNC model, and no part of "
    "the simulated VNC contributes to leg movement.",
    "Leg adhesion at a fixed gain, which no fly possesses as a switchable actuator.",
    "A female NeuroMechFly body prior driven by a male CNS graph.",
    "Standing is a proportional-integral controller holding thorax pose through the "
    "femur-tibia pitch of all six legs, ported from Track A. A fly does this with "
    "load-sensing sensilla and chordotonal reflexes distributed through the ventral cord.",
    "Objects are spheres and cylinders with a position, a radius and a contact pair. They "
    "have no texture, no odour, no taste and no nutritional value. Food is a coloured "
    "sphere that the encoder sees as an object of that angular size and nothing more.",
    "Each fly is presented to the other flies' encoders as a sphere of one declared "
    "radius. Nothing here models how a fly looks to a fly.",
    "Every fly in the scene carries the same connectome and the same parameters. They "
    "differ in where they start, what they see from there, and their independent "
    "membrane-noise stream. They are not individuals.",
)

# Appearance. Nothing in this block is read by a solver; every constant here reaches the
# screen and stops. The values are chosen for a scene about 60 mm across holding animals
# 3 mm long, which is a far wider shot than DEMO-01's and needs a coarser ground and a
# light that casts a readable shadow at that scale.
GROUND_LIGHT_RGB = (214, 206, 190)
GROUND_DARK_RGB = (191, 181, 163)
GROUND_REFLECTANCE = 0.04
# One flat sky colour, and the same colour in the haze, so the ground fades into the
# sky rather than ending at an edge. A gradient across a cube map meets itself at the
# face seams, which is what the first cut showed across the top of every wide shot.
SKY_RGB = (168, 190, 219)
HEADLIGHT_AMBIENT = 0.20
HEADLIGHT_DIFFUSE = 0.22
HEADLIGHT_SPECULAR = 0.04
SHADOW_TEXTURE_SIZE = 4096
SHADOW_CLIP_MM = 200.0
# Where the ground starts fading into the sky, as a fraction of the visible extent.
HAZE_FRACTION = 0.22
# Rendered grid spacing on the infinite ground plane, in mm.
GROUND_GRID_SPACING_MM = 14.0

FOOD_RGBA: tuple[float, float, float, float] = (0.86, 0.27, 0.11, 1.0)
PILLAR_RGBA: tuple[float, float, float, float] = (0.44, 0.42, 0.38, 1.0)


def _checker_tile(height: int, width: int) -> np.ndarray:
    """Two sand tones in a two-by-two block, tiled by the material's repeat count."""
    tile = np.zeros((height, width, 3), dtype=np.uint8)
    light = np.asarray(GROUND_LIGHT_RGB, dtype=np.uint8)
    dark = np.asarray(GROUND_DARK_RGB, dtype=np.uint8)
    half_h, half_w = height // 2, width // 2
    tile[:half_h, :half_w] = light
    tile[half_h:, half_w:] = light
    tile[:half_h, half_w:] = dark
    tile[half_h:, :half_w] = dark
    return tile


def _sky_tile(height: int, width: int) -> np.ndarray:
    """One flat colour on every cube face, so there is no seam to see."""
    return np.tile(np.asarray(SKY_RGB, dtype=np.uint8), (height, width, 1))


# --------------------------------------------------------------------------------------
# Scene description
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwarmObject:
    """One thing in the arena: where it is, how big, and whether the flies can see it."""

    object_id: str
    kind: str
    x_mm: float
    y_mm: float
    radius_mm: float
    height_mm: float
    rgba: tuple[float, float, float, float]
    visible_to_vision: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {"food", "pillar"}:
            raise ConfigurationError(
                f"Object {self.object_id!r} has unknown kind {self.kind!r}; "
                "expected 'food' or 'pillar'"
            )
        if self.radius_mm <= 0.0:
            raise ConfigurationError(f"Object {self.object_id!r} needs a positive radius")
        if self.height_mm <= 0.0:
            raise ConfigurationError(f"Object {self.object_id!r} needs a positive height")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> SwarmObject:
        kind = str(raw["kind"])
        default_rgba = FOOD_RGBA if kind == "food" else PILLAR_RGBA
        rgba = raw.get("rgba")
        return cls(
            object_id=str(raw["object_id"]),
            kind=kind,
            x_mm=float(raw["x_mm"]),
            y_mm=float(raw["y_mm"]),
            radius_mm=float(raw["radius_mm"]),
            height_mm=float(raw.get("height_mm", raw["radius_mm"])),
            rgba=tuple(float(v) for v in rgba) if rgba else default_rgba,  # type: ignore[arg-type]
            visible_to_vision=bool(raw.get("visible_to_vision", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "kind": self.kind,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "radius_mm": self.radius_mm,
            "height_mm": self.height_mm,
            "rgba": list(self.rgba),
            "visible_to_vision": self.visible_to_vision,
        }


@dataclass(frozen=True, slots=True)
class SwarmFlySpec:
    """Where one fly starts and what to call it on screen."""

    fly_id: str
    x_mm: float
    y_mm: float
    heading_rad: float
    label: str = ""

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> SwarmFlySpec:
        return cls(
            fly_id=str(raw["fly_id"]),
            x_mm=float(raw["x_mm"]),
            y_mm=float(raw["y_mm"]),
            heading_rad=float(raw["heading_rad"]),
            label=str(raw.get("label", raw["fly_id"])),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fly_id": self.fly_id,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "heading_rad": self.heading_rad,
            "label": self.label or self.fly_id,
        }


@dataclass(frozen=True, slots=True)
class SwarmArenaParameters:
    """Physics and standing-controller constants, carried over from DEMO-01 unchanged.

    Every station-keeping value here is the value `configs/scenarios/demo01-visual-approach
    .json` registered, and the reason each one is what it is lives in that file and in
    `docs/evidence/TRACK_A_STATION_KEEPING.md`. They are not re-derived for a wider arena,
    because nothing about the arena changes what holds a standing body still.
    """

    physics_dt_us: int = 500
    ground_half_size_mm: float = 120.0
    spawn_height_mm: float = 0.5
    fly_visual_radius_mm: float = 0.55
    station_keeping_gain_rad_per_mm: float = 0.02
    station_keeping_integral_rad_per_mm_s: float = 0.12
    station_keeping_yaw_gain_rad_per_rad: float = 0.05
    station_keeping_yaw_integral_rad_per_rad_s: float = 0.4
    station_keeping_max_offset_rad: float = 0.07
    station_keeping_max_yaw_offset_rad: float = 0.02
    station_keeping_settle_us: int = 2_000_000

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> SwarmArenaParameters:
        known = {
            name: raw[name]
            for name in cls.__dataclass_fields__
            if name in raw
        }
        values = cls(**known)
        if values.physics_dt_us <= 0:
            raise ConfigurationError("Physics step must be positive")
        if values.ground_half_size_mm <= 0.0:
            raise ConfigurationError("Ground half-size must be positive")
        if values.fly_visual_radius_mm <= 0.0:
            raise ConfigurationError("A fly's declared visual radius must be positive")
        return values

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(slots=True)
class _FlyChannel:
    """Everything that is per-fly and mutable. One of these per body in the scene."""

    spec: SwarmFlySpec
    name: str
    controller: Any
    thorax_index: int
    neutral_targets: np.ndarray
    standing_targets: np.ndarray
    actuator_index: dict[str, int]
    station_channel: tuple[tuple[int, float], ...]
    qpos_slice: slice
    command_forward: float = 0.0
    command_yaw: float = 0.0
    station_reference: tuple[float, float, float] | None = None
    station_fore_aft_integral_mm_s: float = 0.0
    station_yaw_integral_rad_s: float = 0.0
    station_offsets_rad: tuple[float, float] = (0.0, 0.0)
    station_error_mm: float = 0.0
    station_peak_error_mm: float = 0.0
    trajectory: list[tuple[int, float, float, float]] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# The world
# --------------------------------------------------------------------------------------


class SwarmWorld:
    """N NeuroMechFly bodies, M objects, one ground plane, one compiled model."""

    def __init__(
        self,
        parameters: SwarmArenaParameters,
        flies: tuple[SwarmFlySpec, ...],
        objects: tuple[SwarmObject, ...],
        *,
        seed: int,
        camera_resolution: tuple[int, int] = (1080, 1920),
        appearance: bool = True,
        lighting: bool = True,
    ) -> None:
        if not flies:
            raise ConfigurationError("A swarm world needs at least one fly")
        if len({fly.fly_id for fly in flies}) != len(flies):
            raise ConfigurationError("Fly identifiers must be unique")
        if len({obj.object_id for obj in objects}) != len(objects):
            raise ConfigurationError("Object identifiers must be unique")

        import mujoco
        from flygym import Simulation
        from flygym.anatomy import (
            ActuatedDOFPreset,
            AxisOrder,
            ContactBodiesPreset,
            JointPreset,
            Skeleton,
        )
        from flygym.compose import (
            ActuatorType,
            ContactParams,
            FlatGroundWorld,
            KinematicPosePreset,
            NeuroMechFly,
        )
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain.turning_controller import HybridTurningController

        self.parameters = parameters
        self.flies = flies
        self.objects = objects
        self._mujoco = mujoco
        self._t_us = 0
        self._renderer: Any | None = None
        self._camera_resolution = camera_resolution
        self._stepped = False

        neutral_pose = KinematicPosePreset.NEUTRAL.get_pose_by_axis_order(
            AxisOrder.YAW_PITCH_ROLL
        )
        skeleton = Skeleton(
            axis_order=AxisOrder.YAW_PITCH_ROLL, joint_preset=JointPreset.ALL_BIOLOGICAL
        )
        world = FlatGroundWorld(half_size=parameters.ground_half_size_mm)

        # Objects go in before the flies so that their geom names exist when the contact
        # pairs are written, and so that nothing the world attaches later is renamed.
        self._object_geom_names = self._add_objects(mujoco, world.mjcf_root)

        contact_preset = ContactBodiesPreset.LEGS_THORAX_ABDOMEN_HEAD
        contact_segments = contact_preset.to_body_segments_list()
        contact_params = ContactParams()

        leg_dofs = skeleton.get_actuated_dofs_from_preset(
            ActuatedDOFPreset.LEGS_ACTIVE_ONLY
        )
        built: list[tuple[SwarmFlySpec, Any, Any]] = []
        for spec in flies:
            fly = NeuroMechFly(name=spec.fly_id)
            fly.add_joints(skeleton, neutral_pose=neutral_pose)
            fly.add_actuators(
                leg_dofs,
                ActuatorType.POSITION,
                neutral_input=neutral_pose,
                kp=45.0,
                forcerange=(-65.0, 65.0),
            )
            fly.add_leg_adhesion(gain=40.0)
            fly.colorize()
            half_yaw = spec.heading_rad / 2.0
            world.add_fly(
                fly,
                spawn_position=np.array(
                    [spec.x_mm, spec.y_mm, parameters.spawn_height_mm]
                ),
                spawn_rotation=Rotation3D(
                    "quat", (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
                ),
                bodysegs_with_ground_contact=contact_preset,
                # FlyGym names every ground-contact sensor `ground_contact_<leg>_leg` with
                # no fly prefix, so a second fly raises a duplicate-name error at attach
                # time. Nothing in this loop reads those sensors -- adhesion is commanded
                # by the walking controller, not by contact -- so they are not requested.
                add_ground_contact_sensors=False,
            )
            controller = HybridTurningController(
                timestep=parameters.physics_dt_us / 1_000_000.0,
                output_dof_order=leg_dofs,
            )
            controller.reset(seed=seed)
            built.append((spec, fly, controller))

        # Contact pairs between every object and the same body segments the ground
        # touches, with the same friction and solver constants. Without these the fly
        # geoms carry contype 0 and walk through a pillar, because FlyGym gives the ground
        # plane contype 0 as well and relies entirely on explicit pairs.
        self._object_pairs = 0
        for _, fly, _ in built:
            for segment in contact_segments:
                for body_geom in fly.bodyseg_to_mjcfgeom[segment]:
                    for object_geom in self._object_geom_names:
                        world.mjcf_root.add_pair(
                            geomname1=body_geom.name,
                            geomname2=object_geom,
                            name=f"{body_geom.name}-{object_geom}-object",
                            friction=contact_params.get_friction_tuple(),
                            solref=contact_params.get_solref_tuple(),
                            solimp=contact_params.get_solimp_tuple(),
                            margin=contact_params.margin,
                        )
                        self._object_pairs += 1

        if lighting:
            self._add_lights(mujoco, world.mjcf_root)

        simulation = Simulation(
            world, timestep=parameters.physics_dt_us / 1_000_000.0
        )
        self._simulation = simulation
        self._world = world
        self._actuator_type = ActuatorType.POSITION
        self._leg_dofs = leg_dofs

        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)

        self._channels: list[_FlyChannel] = []
        for spec, fly, controller in built:
            self._channels.append(
                self._build_channel(mujoco, spec, fly, controller, leg_dofs)
            )
        self._by_id = {channel.spec.fly_id: index
                       for index, channel in enumerate(self._channels)}

        # Settle every fly at once: they share one `mj_step`, so they have to.
        for channel in self._channels:
            simulation.set_actuator_inputs(
                channel.name, self._actuator_type, channel.standing_targets
            )
            simulation.set_leg_adhesion_states(channel.name, np.ones(6, dtype=bool))
        simulation.warmup()
        simulation.mj_data.qvel[:] = 0.0
        mujoco.mj_forward(simulation.mj_model, simulation.mj_data)

        self._station_settle_us = 0
        self._converge_station_keeping()

        for channel in self._channels:
            channel.controller.reset(
                seed=seed, init_magnitudes=np.zeros(6, dtype=np.float64)
            )

        if appearance:
            self._apply_appearance()

    # -- construction helpers -----------------------------------------------------

    def _add_objects(self, mujoco: Any, spec: Any) -> tuple[str, ...]:
        names: list[str] = []
        for obj in self.objects:
            body = spec.worldbody.add_body(
                name=f"object_{obj.object_id}",
                pos=[obj.x_mm, obj.y_mm, obj.height_mm],
            )
            geom_name = f"object_{obj.object_id}_geom"
            if obj.kind == "food":
                body.add_geom(
                    name=geom_name,
                    type=mujoco.mjtGeom.mjGEOM_SPHERE,
                    size=[obj.radius_mm, 0.0, 0.0],
                    rgba=list(obj.rgba),
                )
            else:
                body.add_geom(
                    name=geom_name,
                    type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                    size=[obj.radius_mm, obj.height_mm, 0.0],
                    rgba=list(obj.rgba),
                )
            names.append(geom_name)
        return tuple(names)

    def _add_lights(self, mujoco: Any, spec: Any) -> None:
        """A key light that casts shadows and a cool fill that does not.

        MuJoCo compiles no light into the FlyGym world at all, so without these the scene
        is lit entirely by the camera-attached headlight and nothing casts a shadow. A
        3 mm animal on a featureless plane with no contact shadow reads as a sticker.
        """
        spec.worldbody.add_light(
            name="swarm_key",
            pos=[40.0, -40.0, 70.0],
            dir=[-0.45, 0.45, -0.77],
            type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
            castshadow=1,
            ambient=[0.0, 0.0, 0.0],
            diffuse=[0.74, 0.72, 0.68],
            specular=[0.18, 0.18, 0.18],
        )
        spec.worldbody.add_light(
            name="swarm_fill",
            pos=[-50.0, 35.0, 50.0],
            dir=[0.56, -0.39, -0.73],
            type=mujoco.mjtLightType.mjLIGHT_DIRECTIONAL,
            castshadow=0,
            ambient=[0.0, 0.0, 0.0],
            diffuse=[0.24, 0.27, 0.34],
            specular=[0.0, 0.0, 0.0],
        )

    def _build_channel(
        self, mujoco: Any, spec: SwarmFlySpec, fly: Any, controller: Any, leg_dofs: Any
    ) -> _FlyChannel:
        simulation = self._simulation
        body_order = fly.get_bodysegs_order()
        thorax = type(fly).BODY_SEGMENT_CLASS("c_thorax")
        actuated = fly.get_actuated_jointdofs_order(self._actuator_type)
        actuator_index = {dof.name: index for index, dof in enumerate(actuated)}
        joint_order = fly.get_jointdofs_order()
        initial_angles = simulation.get_joint_angles(spec.fly_id)
        neutral_targets = np.asarray(
            [initial_angles[joint_order.index(dof)] for dof in actuated],
            dtype=np.float64,
        )
        standing = neutral_targets.copy()
        standing[: len(leg_dofs)] = (
            controller.preprogrammed_steps.default_pose_by_dof_order(leg_dofs)
        )

        station: list[tuple[int, float]] = []
        for leg in STATION_KEEPING_LEGS:
            name = STATION_KEEPING_DOF.format(leg=leg)
            try:
                index = actuator_index[name]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Station-keeping channel {name} is not an actuated DOF"
                ) from exc
            station.append((index, 1.0 if leg in STATION_KEEPING_LEFT_LEGS else -1.0))

        joint_id = mujoco.mj_name2id(
            simulation.mj_model, mujoco.mjtObj.mjOBJ_JOINT, spec.fly_id
        )
        if joint_id < 0:
            raise ConfigurationError(
                f"No free joint named {spec.fly_id!r} in the compiled model"
            )
        start = int(simulation.mj_model.jnt_qposadr[joint_id])
        return _FlyChannel(
            spec=spec,
            name=spec.fly_id,
            controller=controller,
            thorax_index=body_order.index(thorax),
            neutral_targets=neutral_targets,
            standing_targets=standing,
            actuator_index=actuator_index,
            station_channel=tuple(station),
            # The free joint plus every joint the fly's subtree owns. Recorded so a single
            # fly can be extracted from a whole-scene qpos without re-deriving the layout.
            qpos_slice=slice(start, start + 7 + len(joint_order)),
        )

    # -- appearance ---------------------------------------------------------------

    def _paint_texture(self, index: int, pixels: np.ndarray) -> None:
        model = self._simulation.mj_model
        height = int(model.tex_height[index])
        width = int(model.tex_width[index])
        channels = int(model.tex_nchannel[index]) if hasattr(model, "tex_nchannel") else 3
        start = int(model.tex_adr[index])
        tile = np.zeros((height, width, channels), dtype=np.uint8)
        tile[..., : min(3, channels)] = pixels[..., : min(3, channels)]
        if channels > 3:
            tile[..., 3:] = 255
        model.tex_data[start : start + tile.size] = tile.reshape(-1)

    def _apply_appearance(self) -> None:
        """Material, texture and lighting constants only. No solver reads any of these."""
        mujoco = self._mujoco
        model = self._simulation.mj_model

        for index in range(int(model.ntex)):
            if int(model.tex_type[index]) == mujoco.mjtTexture.mjTEXTURE_SKYBOX:
                self._paint_texture(
                    index,
                    _sky_tile(int(model.tex_height[index]), int(model.tex_width[index])),
                )

        for geom in range(int(model.ngeom)):
            if model.geom_type[geom] != mujoco.mjtGeom.mjGEOM_PLANE:
                continue
            # A MuJoCo plane geom with zero half-extents renders as a true infinite plane,
            # which is the only form the haze pass fades into the sky. It is also what the
            # plane already is for collision -- a plane is a half-space whatever its
            # rendered size -- so this ends the visible ground edge and the moire beyond it
            # without changing a contact. The third size element is the rendered grid
            # spacing in mm.
            model.geom_size[geom] = np.asarray(
                [0.0, 0.0, GROUND_GRID_SPACING_MM], dtype=model.geom_size.dtype
            )
            material = int(model.geom_matid[geom])
            if material < 0:
                model.geom_rgba[geom] = np.asarray(
                    [c / 255.0 for c in GROUND_LIGHT_RGB] + [1.0],
                    dtype=model.geom_rgba.dtype,
                )
                continue
            # On an infinite plane the repeat count has to be per millimetre rather than
            # per geom, or the checker is tiled an unbounded number of times and aliases
            # into a moire haze. `texuniform` switches the material to spatial repeats;
            # one two-by-two tile then spans two grid squares.
            model.mat_texuniform[material] = 1
            spatial = 1.0 / (2.0 * GROUND_GRID_SPACING_MM)
            model.mat_texrepeat[material] = np.asarray(
                [spatial, spatial], dtype=model.mat_texrepeat.dtype
            )
            model.mat_rgba[material] = np.asarray(
                [1.0, 1.0, 1.0, 1.0], dtype=model.mat_rgba.dtype
            )
            model.mat_reflectance[material] = GROUND_REFLECTANCE
            for texture in np.asarray(model.mat_texid[material]).ravel():
                if int(texture) < 0:
                    continue
                self._paint_texture(
                    int(texture),
                    _checker_tile(
                        int(model.tex_height[int(texture)]),
                        int(model.tex_width[int(texture)]),
                    ),
                )

        model.vis.headlight.ambient[:] = HEADLIGHT_AMBIENT
        model.vis.headlight.diffuse[:] = HEADLIGHT_DIFFUSE
        model.vis.headlight.specular[:] = HEADLIGHT_SPECULAR
        model.vis.quality.shadowsize = SHADOW_TEXTURE_SIZE
        # The shadow map covers a volume. Clipped too tightly, the ground beyond the clip
        # samples outside the map and renders as a dotted wedge in the direction of the key
        # light, which is what the first contact sheet showed on the right of every wide
        # shot. At 200 mm and 4096 texels a texel is about 0.1 mm, still far finer than the
        # 3 mm animal casting the shadow.
        model.vis.map.shadowclip = SHADOW_CLIP_MM
        model.vis.map.shadowscale = 1.3
        model.vis.rgba.haze[:] = [value / 255.0 for value in SKY_RGB] + [1.0]
        model.vis.map.haze = HAZE_FRACTION

    # -- state --------------------------------------------------------------------

    @property
    def t_us(self) -> int:
        return self._t_us

    @property
    def fly_count(self) -> int:
        return len(self._channels)

    @property
    def mujoco(self) -> Any:
        return self._mujoco

    @property
    def render_model(self) -> Any:
        return self._simulation.mj_model

    def index_of(self, fly_id: str) -> int:
        try:
            return self._by_id[fly_id]
        except KeyError as exc:
            raise ConfigurationError(f"No fly named {fly_id!r} in this world") from exc

    def pose(self, index: int) -> tuple[float, float, float, float]:
        """x mm, y mm, z mm, heading rad for one fly."""
        channel = self._channels[index]
        position = self._simulation.get_body_positions(channel.name)[channel.thorax_index]
        quaternion = self._simulation.get_body_rotations(channel.name)[
            channel.thorax_index
        ]
        w, x, y, z = (float(value) for value in quaternion)
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return float(position[0]), float(position[1]), float(position[2]), yaw

    def poses(self) -> tuple[tuple[float, float, float, float], ...]:
        return tuple(self.pose(index) for index in range(len(self._channels)))

    def qpos(self) -> np.ndarray:
        """A copy of the whole scene's generalised position vector."""
        return np.array(self._simulation.mj_data.qpos, copy=True)

    def qpos_slices(self) -> tuple[slice, ...]:
        return tuple(channel.qpos_slice for channel in self._channels)

    def station_keeping(self, index: int) -> dict[str, Any]:
        channel = self._channels[index]
        return {
            "settle_us": self._station_settle_us,
            "held_pose_error_mm": channel.station_error_mm,
            "peak_pose_error_mm": channel.station_peak_error_mm,
            "common_offset_rad": channel.station_offsets_rad[0],
            "differential_offset_rad": channel.station_offsets_rad[1],
            "provenance": "E",
            "ported_from": "Track A, docs/evidence/TRACK_A_STATION_KEEPING.md",
        }

    # -- actuation ----------------------------------------------------------------

    def apply_actuators(self, index: int, frame: ActuatorCommandFrame) -> None:
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Actuator timestamp {frame.t_us} does not match world time {self._t_us}"
            )
        channel = self._channels[index]
        channel.command_forward = frame.value_for(COMMAND_FORWARD, 0.0)
        channel.command_yaw = frame.value_for(COMMAND_YAW, 0.0)

    @staticmethod
    def _clamped_integral(accumulated: float, gain: float, limit: float) -> float:
        if gain == 0.0:
            return 0.0
        bound = abs(limit / gain)
        return min(bound, max(-bound, accumulated))

    def _release_station_reference(self, channel: _FlyChannel) -> None:
        channel.station_reference = None
        channel.station_offsets_rad = (0.0, 0.0)

    def _reset_station_keeping(self, channel: _FlyChannel) -> None:
        self._release_station_reference(channel)
        channel.station_fore_aft_integral_mm_s = 0.0
        channel.station_yaw_integral_rad_s = 0.0

    def _apply_station_keeping(
        self, index: int, channel: _FlyChannel, targets: np.ndarray
    ) -> None:
        """Null uncommanded drift by shifting the stance legs, never the physics.

        Ported unchanged from DEMO-01, which ported it unchanged from Track A. The integral
        does the work; the offset limit is part of the control design rather than a safety
        margin, because the measured drift response reverses sign inside the band; and
        there is deliberately no rate term.
        """
        parameters = self.parameters
        proportional = parameters.station_keeping_gain_rad_per_mm
        integral = parameters.station_keeping_integral_rad_per_mm_s
        yaw_proportional = parameters.station_keeping_yaw_gain_rad_per_rad
        yaw_integral = parameters.station_keeping_yaw_integral_rad_per_rad_s
        if not any((proportional, integral, yaw_proportional, yaw_integral)):
            self._reset_station_keeping(channel)
            return
        x_mm, y_mm, _, heading_rad = self.pose(index)
        if channel.station_reference is None:
            channel.station_reference = (x_mm, y_mm, heading_rad)
            channel.station_offsets_rad = (0.0, 0.0)
            channel.station_error_mm = 0.0
            return
        reference_x, reference_y, reference_heading = channel.station_reference
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
        channel.station_fore_aft_integral_mm_s = self._clamped_integral(
            channel.station_fore_aft_integral_mm_s + fore_aft_mm * dt_s, integral, limit
        )
        channel.station_yaw_integral_rad_s = self._clamped_integral(
            channel.station_yaw_integral_rad_s + yaw_error_rad * dt_s,
            yaw_integral,
            yaw_limit,
        )
        common = _clamp(
            proportional * fore_aft_mm
            + integral * channel.station_fore_aft_integral_mm_s,
            limit,
        )
        differential = _clamp(
            yaw_proportional * yaw_error_rad
            + yaw_integral * channel.station_yaw_integral_rad_s,
            yaw_limit,
        )
        for actuator, sign in channel.station_channel:
            targets[actuator] += _clamp(common + sign * differential, limit)
        channel.station_offsets_rad = (common, differential)
        channel.station_error_mm = math.hypot(delta_x, delta_y)
        channel.station_peak_error_mm = max(
            channel.station_peak_error_mm, channel.station_error_mm
        )

    def _converge_station_keeping(self) -> None:
        """Charge every fly's standing integral before the run starts, changing nothing else.

        The window is a calibration, not simulated behaviour, so the scene must come out of
        it exactly as it went in: every physics field the settle touches is saved and
        restored, and the only thing carried forward is each controller's own integral.
        All flies settle together because they share one `mj_step`.
        """
        mujoco = self._mujoco
        parameters = self.parameters
        settle_us = parameters.station_keeping_settle_us
        if settle_us <= 0 or not any(
            (
                parameters.station_keeping_gain_rad_per_mm,
                parameters.station_keeping_integral_rad_per_mm_s,
                parameters.station_keeping_yaw_gain_rad_per_rad,
                parameters.station_keeping_yaw_integral_rad_per_rad_s,
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
        for _ in range(settle_us // parameters.physics_dt_us):
            for index, channel in enumerate(self._channels):
                targets = channel.standing_targets.copy()
                self._apply_station_keeping(index, channel, targets)
                self._simulation.set_actuator_inputs(
                    channel.name, self._actuator_type, targets
                )
                self._simulation.set_leg_adhesion_states(channel.name, adhered)
            self._simulation.step()
        data.qpos[:] = saved[0]
        data.qvel[:] = saved[1]
        data.act[:] = saved[2]
        data.ctrl[:] = saved[3]
        data.time = saved[4]
        mujoco.mj_forward(self._simulation.mj_model, data)
        for channel in self._channels:
            self._release_station_reference(channel)
            channel.station_peak_error_mm = 0.0
        self._station_settle_us = settle_us

    def _apply_physics_action(self) -> None:
        from flygym_demo.complex_terrain.hybrid_controller import (
            HybridControllerObservation,
        )

        for index, channel in enumerate(self._channels):
            forward = min(1.0, max(0.0, channel.command_forward))
            turn = min(1.0, max(-1.0, channel.command_yaw))
            descending = np.clip(
                np.array([forward - turn, forward + turn], dtype=np.float64), -1.0, 1.0
            )
            if bool(np.allclose(descending, 0.0)):
                targets = channel.standing_targets.copy()
                self._apply_station_keeping(index, channel, targets)
                adhesion = np.ones(6, dtype=bool)
            else:
                self._release_station_reference(channel)
                observation = HybridControllerObservation.from_sim(
                    self._simulation, channel.name
                )
                action = channel.controller.step(descending, observation)
                targets = channel.neutral_targets.copy()
                targets[: len(self._leg_dofs)] = action.joint_angles
                adhesion = action.adhesion_onoff
            self._simulation.set_actuator_inputs(
                channel.name, self._actuator_type, targets
            )
            self._simulation.set_leg_adhesion_states(channel.name, adhesion)

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(
                f"Cannot step the world backward from {self._t_us} to {t_us}"
            )
        if (t_us - self._t_us) % self.parameters.physics_dt_us:
            raise CausalityError("World boundary is not aligned to the physics step")
        while self._t_us < t_us:
            self._apply_physics_action()
            self._simulation.step()
            self._t_us += self.parameters.physics_dt_us
            self._stepped = True
            self._reject_nonfinite_physics()
        for index, channel in enumerate(self._channels):
            x_mm, y_mm, _, heading = self.pose(index)
            channel.trajectory.append((self._t_us, x_mm, y_mm, heading))

    def _reject_nonfinite_physics(self) -> None:
        """Stop the instant the solver produces a non-finite state.

        Twelve articulated bodies sharing one solver can diverge in a way one body does
        not, and a diverged state propagates silently: `qpos` fills with NaN, every pose
        reads as NaN, the encoder sees nothing, and the run finishes and writes a summary
        full of nulls that looks like a result. Failing here costs the run and keeps the
        artifact honest.
        """
        data = self._simulation.mj_data
        if not (np.all(np.isfinite(data.qpos)) and np.all(np.isfinite(data.qvel))):
            bad = [
                channel.spec.fly_id
                for channel in self._channels
                if not np.all(np.isfinite(data.qpos[channel.qpos_slice]))
            ]
            raise CausalityError(
                f"The physics state stopped being finite at t={self._t_us} us "
                f"(flies: {bad or 'shared state'}). The run is void from here."
            )

    # -- rendering ----------------------------------------------------------------

    def _ensure_renderer(self) -> Any:
        if self._renderer is None:
            height, width = self._camera_resolution
            renderer = self._mujoco.Renderer(
                self._simulation.mj_model, height=height, width=width
            )
            renderer.scene.flags[self._mujoco.mjtRndFlag.mjRND_SHADOW] = 1
            # Reflection renders the whole scene a second time into the ground plane. At
            # the 0.04 reflectance this ground carries, that second pass costs about half
            # the frame time and changes almost no pixels, so it is off.
            renderer.scene.flags[self._mujoco.mjtRndFlag.mjRND_REFLECTION] = 0
            renderer.scene.flags[self._mujoco.mjtRndFlag.mjRND_HAZE] = 1
            self._renderer = renderer
        return self._renderer

    def render_replay_frame(
        self,
        qpos: np.ndarray,
        *,
        lookat_mm: tuple[float, float, float],
        distance_mm: float,
        azimuth_deg: float,
        elevation_deg: float,
        decorations: tuple[dict[str, Any], ...] = (),
    ) -> np.ndarray:
        """Draw a recorded scene state. Only legal on a world that has never been stepped.

        Writing into `qpos` is exactly the thing that must never happen to a running
        simulation, so rather than trusting the caller, the guard below makes it
        impossible. Offline rendering constructs a fresh world, which has not been
        stepped, and the running loop never can.
        """
        if self._stepped or self._t_us != 0:
            raise CausalityError(
                "render_replay_frame overwrites the physics state and may only be used on "
                f"a world that has never been stepped, but this one is at {self._t_us} us. "
                "Offline rendering must construct its own world."
            )
        state = np.asarray(qpos, dtype=np.float64)
        data = self._simulation.mj_data
        if state.shape != data.qpos.shape:
            raise ConfigurationError(
                f"Recorded qpos has shape {state.shape}, but this model needs "
                f"{data.qpos.shape}. The recording and the model disagree."
            )
        data.qpos[:] = state
        data.qvel[:] = 0.0
        self._mujoco.mj_forward(self._simulation.mj_model, data)

        mujoco = self._mujoco
        renderer = self._ensure_renderer()
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(self._simulation.mj_model, camera)
        camera.lookat[:] = lookat_mm
        camera.distance = distance_mm
        camera.azimuth = azimuth_deg
        camera.elevation = elevation_deg
        renderer.update_scene(data, camera=camera)
        for decoration in decorations:
            add_scene_sphere(mujoco, renderer.scene, **decoration)
        return np.asarray(renderer.render())

    def close(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def __enter__(self) -> SwarmWorld:
        return self

    def __exit__(self, *exception: Any) -> None:
        self.close()

    # -- description --------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        model = self._simulation.mj_model
        return {
            "backend": "FlyGym 2.1 / MuJoCo 3.9",
            "walking_controller": "flygym_demo HybridTurningController, one per fly",
            "flies": len(self._channels),
            "objects": [obj.as_dict() for obj in self.objects],
            "physics_dt_us": self.parameters.physics_dt_us,
            "model": {
                "nq": int(model.nq),
                "nv": int(model.nv),
                "nu": int(model.nu),
                "ngeom": int(model.ngeom),
                "nbody": int(model.nbody),
                "nlight": int(model.nlight),
                "explicit_object_contact_pairs": self._object_pairs,
            },
            "every_fly_is_a_separate_body": (
                "Each fly is a full NeuroMechFly attached to the world with its own free "
                "joint, its own actuators and its own walking controller. They share one "
                "`mj_step`, so they collide with each other and with the objects through "
                "the solver rather than through a rule."
            ),
            "scaffolds": list(SCAFFOLDS),
        }


def add_scene_sphere(
    mujoco: Any,
    scene: Any,
    *,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    radius_mm: float,
    rgba: tuple[float, float, float, float],
) -> bool:
    """Append a translucent marker to a viewer scene. Returns False if the scene is full.

    Used for things that exist in the recording but not in the model: the halo that marks
    which fly the shot is following, and the ring that marks where a fly's own encoder
    believes the nearest object is. Both are read from the trace, never invented, and both
    are drawn as decor so no solver can touch them.
    """
    if scene.ngeom >= scene.maxgeom:
        return False
    geom = scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(
        geom,
        type=mujoco.mjtGeom.mjGEOM_SPHERE,
        size=np.array([radius_mm, radius_mm, radius_mm], dtype=np.float64),
        pos=np.array([x_mm, y_mm, z_mm], dtype=np.float64),
        mat=np.eye(3, dtype=np.float64).reshape(9),
        rgba=np.array(rgba, dtype=np.float32),
    )
    geom.category = mujoco.mjtCatBit.mjCAT_DECOR
    scene.ngeom += 1
    return True


__all__ = [
    "FOOD_RGBA",
    "PILLAR_RGBA",
    "SCAFFOLDS",
    "SwarmArenaParameters",
    "SwarmFlySpec",
    "SwarmObject",
    "SwarmWorld",
    "add_scene_sphere",
]
