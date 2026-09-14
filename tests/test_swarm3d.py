# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the embodied 3D swarm.

The properties pinned here are the ones whose quiet failure would turn a demonstration
into a workaround:

* the multi-object encoder must reduce to DEMO-01's frozen single-cue encoder exactly,
  because if it does not, the swarm is running a different network from the one the
  registered operating-point search selected;
* the swarm world must move one fly exactly the way `Demo01VisualBody` moves it, because
  otherwise the shared machinery has silently forked;
* the replay renderer must refuse a world that has been stepped, because that guard is the
  only structural reason rendering cannot alter a run;
* the camera must never be able to select the run's best moments by eye, and the shot list
  must never be able to run off the end of a recording.

The tests that need MuJoCo are marked and skipped when it is unavailable; the rest still
catch parameter and wiring faults.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from flysim.demo01 import Demo01Populations, PopulationSpec
from flysim.demo01_visual import (
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualEncodingParameters,
)
from flysim.errors import CausalityError, ConfigurationError
from flysim.swarm3d import (
    SCAFFOLDS,
    SwarmArenaParameters,
    SwarmFlySpec,
    SwarmObject,
)
from flysim.swarm3d_replay import (
    MINIMUM_CAMERA_DISTANCE_MM,
    Shot,
    SwarmTrajectories,
    Timeline,
    camera_for,
)
from flysim.swarm3d_run import SwarmScenario
from flysim.swarm3d_vision import (
    MultiObjectLaminaEncoder,
    SceneObject,
    visible_objects_for,
)

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
SCENARIO = REPO / "configs/scenarios/swarm3d-showcase.json"
DEMO01_SCENARIO = REPO / "configs/scenarios/demo01-visual-approach.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scenario_raw() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


@pytest.fixture
def retina(contract: dict) -> RetinaMap:
    return RetinaMap.from_mapping(contract["retina_map"])


@pytest.fixture
def encoding(contract: dict) -> VisualEncodingParameters:
    return VisualEncodingParameters.from_mapping(
        {
            **contract["fixed_parameters"],
            "lamina_max_rate_hz": 400.0,
            "lamina_on_off_balance": 1.0,
        }
    )


@pytest.fixture
def populations() -> Demo01Populations:
    """A synthetic lamina, so the parity test runs without the released dataset.

    Two eyes, a spread of released column coordinates, one body deliberately left without
    a column so the "held out of the frame rather than given an invented position" rule is
    exercised, and an L1 population so the ON/OFF pathway gain is not constant.
    """
    left_off = tuple(range(1000, 1012))
    right_off = tuple(range(2000, 2012))
    left_on = tuple(range(3000, 3006))
    right_on = tuple(range(4000, 4006))
    hex_by_body: dict[int, tuple[float, float]] = {}
    for offset, bodies in ((0, left_off), (0, right_off), (3, left_on), (3, right_on)):
        for index, body in enumerate(bodies):
            hex_by_body[body] = (2.0 + 3.0 * index + offset, 14.0 + (index % 4) * 2.0)
    # One body with no released column: it must never reach a frame.
    hex_by_body.pop(left_off[-1])
    entry = {
        "lamina-off-left": left_off,
        "lamina-off-right": right_off,
        "lamina-on-left": left_on,
        "lamina-on-right": right_on,
    }
    readout = {"dn-visual-left": (9001, 9002), "dn-visual-right": (9003, 9004)}
    return Demo01Populations(
        annotations_sha256="0" * 64,
        entry=entry,
        readout=readout,
        monitors={"optic-lobe": left_off + right_off},
        specs=(
            PopulationSpec("lamina-off-left", "L2", None, "somaSide", "synthetic"),
        ),
        excluded_unknown_side={},
        entry_hex=hex_by_body,
    )


# ---------------------------------------------------------------------------
# The encoder extension must not be a new encoder
# ---------------------------------------------------------------------------


GEOMETRIES = (
    (10.7, 9.0, 2.5, 0.0, 0.0, 0.0),
    (-6.0, 4.0, 1.2, 3.0, -2.0, 1.1),
    (0.0, 0.0, 3.0, 0.4, 0.1, -2.7),
    (20.0, -15.0, 0.55, 0.0, 0.0, 0.0),
    (-30.0, -2.0, 4.0, 5.0, 5.0, 2.9),
)


@pytest.mark.parametrize("geometry", GEOMETRIES)
def test_one_object_reproduces_the_demo01_encoder(
    populations: Demo01Populations,
    encoding: VisualEncodingParameters,
    retina: RetinaMap,
    geometry: tuple[float, float, float, float, float, float],
) -> None:
    """With a single cue the maximum is the single term, so the rates must agree.

    This is the test that makes the extension checkable. If it ever fails, the swarm is
    not running the network the registered DEMO-01 search selected, whatever the summary
    says.
    """
    cue_x, cue_y, radius, fly_x, fly_y, heading = geometry
    scalar = RetinotopicVisualEncoder(populations, encoding, retina)
    multi = MultiObjectLaminaEncoder(populations, encoding, retina)

    rates, _ = scalar.rates_for(
        VisualCue(x_mm=cue_x, y_mm=cue_y, radius_mm=radius),
        x_mm=fly_x,
        y_mm=fly_y,
        heading_rad=heading,
    )
    expected_ids = tuple(sorted(rates))
    assert multi.ids == expected_ids

    observed, scene = multi.rates_for(
        (SceneObject("cue", "food", cue_x, cue_y, radius),),
        x_mm=fly_x,
        y_mm=fly_y,
        heading_rad=heading,
    )
    reference = np.asarray([rates[body] for body in expected_ids])
    assert np.allclose(observed, reference, rtol=0.0, atol=1e-9)
    assert scene["objects_visible"] == 1


def test_a_body_without_a_released_column_never_reaches_a_frame(
    populations: Demo01Populations,
    encoding: VisualEncodingParameters,
    retina: RetinaMap,
) -> None:
    multi = MultiObjectLaminaEncoder(populations, encoding, retina)
    without_column = 1011
    assert without_column not in multi.ids
    assert multi.entry_body_count == sum(
        1 for bodies in populations.entry.values() for body in bodies
    ) - 1


def test_adding_an_object_can_only_raise_a_cells_drive(
    populations: Demo01Populations,
    encoding: VisualEncodingParameters,
    retina: RetinaMap,
) -> None:
    """The composition is a maximum, so a second object cannot dim a lamina cell.

    A rule that could dim one -- an average, say -- would let a distant object suppress a
    near one, which is the opposite of what the looming term means.
    """
    multi = MultiObjectLaminaEncoder(populations, encoding, retina)
    a = SceneObject("a", "food", 12.0, 3.0, 2.0)
    b = SceneObject("b", "pillar", -4.0, 9.0, 1.4)
    kwargs = {"x_mm": 0.0, "y_mm": 0.0, "heading_rad": 0.2}
    only_a, _ = multi.rates_for((a,), **kwargs)
    only_b, _ = multi.rates_for((b,), **kwargs)
    both, _ = multi.rates_for((a, b), **kwargs)
    assert np.all(both >= only_a - 1e-12)
    assert np.all(both >= only_b - 1e-12)
    assert np.allclose(both, np.maximum(only_a, only_b), atol=1e-12)


def test_stimulus_absent_holds_every_body_at_baseline(
    populations: Demo01Populations,
    encoding: VisualEncodingParameters,
    retina: RetinaMap,
) -> None:
    """The control must remove the scene, not merely move it out of the way."""
    multi = MultiObjectLaminaEncoder(
        populations, encoding, retina, stimulus_present=False
    )
    rates, scene = multi.rates_for(
        (SceneObject("a", "food", 1.0, 0.5, 3.0),),
        x_mm=0.0,
        y_mm=0.0,
        heading_rad=0.0,
    )
    assert np.all(rates == encoding.lamina_baseline_rate_hz)
    assert scene["stimulus_present"] is False
    assert scene["driven_bodies"] == 0


def test_a_fly_is_not_visible_to_itself_and_invisible_objects_stay_invisible() -> None:
    poses = ((0.0, 0.0, 1.1, 0.0), (5.0, 2.0, 1.1, 1.0), (-3.0, 4.0, 1.1, 2.0))
    objects = (
        SwarmObject("seen", "food", 8.0, 0.0, 2.0, 1.8, (1.0, 0.0, 0.0, 1.0)),
        SwarmObject(
            "unseen", "pillar", -8.0, 0.0, 1.0, 3.0, (0.5, 0.5, 0.5, 1.0),
            visible_to_vision=False,
        ),
    )
    seen = visible_objects_for(
        0, poses, objects, fly_visual_radius_mm=0.55, include_other_flies=True
    )
    ids = {item.object_id for item in seen}
    assert "seen" in ids
    assert "unseen" not in ids
    assert ids == {"seen", "fly:1", "fly:2"}
    assert all(item.radius_mm == 0.55 for item in seen if item.kind == "fly")

    alone = visible_objects_for(
        0, poses, objects, fly_visual_radius_mm=0.55, include_other_flies=False
    )
    assert {item.object_id for item in alone} == {"seen"}


# ---------------------------------------------------------------------------
# The scenario
# ---------------------------------------------------------------------------


def test_the_shipped_scenario_loads_and_is_internally_consistent() -> None:
    scenario = SwarmScenario.load(SCENARIO)
    assert len({fly.fly_id for fly in scenario.flies}) == len(scenario.flies)
    assert len({obj.object_id for obj in scenario.objects}) == len(scenario.objects)
    assert any(obj.kind == "food" for obj in scenario.objects)
    assert any(obj.kind == "pillar" for obj in scenario.objects)


def test_no_fly_starts_inside_an_object_or_on_top_of_another_fly() -> None:
    """A fly spawned inside a pillar is a physics explosion waiting for the first step."""
    scenario = SwarmScenario.load(SCENARIO)
    body_radius_mm = 1.5
    for fly in scenario.flies:
        for obj in scenario.objects:
            gap = math.hypot(obj.x_mm - fly.x_mm, obj.y_mm - fly.y_mm)
            assert gap > obj.radius_mm + body_radius_mm, (
                f"{fly.fly_id} starts {gap:.2f} mm from {obj.object_id}"
            )
    for index, fly in enumerate(scenario.flies):
        for other in scenario.flies[index + 1 :]:
            gap = math.hypot(other.x_mm - fly.x_mm, other.y_mm - fly.y_mm)
            assert gap > 2.0 * body_radius_mm


def test_the_arena_carries_demo01s_station_keeping_values_unchanged() -> None:
    """Nothing about a wider arena changes what holds a standing body still.

    If these ever diverge, the swarm's standing controller is a different controller from
    the one Track A measured and DEMO-01 inherited, and its drift is unmeasured.
    """
    swarm = json.loads(SCENARIO.read_text(encoding="utf-8"))["arena"]
    demo01 = json.loads(DEMO01_SCENARIO.read_text(encoding="utf-8"))["body"]
    for name in (
        "physics_dt_us",
        "spawn_height_mm",
        "station_keeping_gain_rad_per_mm",
        "station_keeping_integral_rad_per_mm_s",
        "station_keeping_yaw_gain_rad_per_rad",
        "station_keeping_yaw_integral_rad_per_rad_s",
        "station_keeping_max_offset_rad",
        "station_keeping_max_yaw_offset_rad",
        "station_keeping_settle_us",
    ):
        assert swarm[name] == demo01[name], name


def test_the_scenario_decoder_is_demo01s_frozen_decoder() -> None:
    swarm = json.loads(SCENARIO.read_text(encoding="utf-8"))["decoder"]
    demo01 = json.loads(DEMO01_SCENARIO.read_text(encoding="utf-8"))["decoder"]
    for name in (
        "quiescent_us",
        "forward_half_rate_hz",
        "forward_threshold_hz",
        "initiation_hold_us",
        "yaw_gain_per_hz",
        "max_yaw_rad_s",
        "turn_sign",
    ):
        assert swarm[name] == demo01[name], name


def test_every_scaffold_is_declared_in_prose_a_viewer_could_read() -> None:
    assert len(SCAFFOLDS) >= 6
    for entry in SCAFFOLDS:
        # A whole sentence, not a label. A scaffold declared as "adhesion" tells a viewer
        # nothing; one that says a fly has no switchable adhesive does.
        assert len(entry) >= 50, entry
        assert entry.rstrip().endswith("."), entry
        assert entry[0].isupper(), entry


def test_object_kinds_and_sizes_are_validated() -> None:
    with pytest.raises(ConfigurationError):
        SwarmObject("x", "rock", 0.0, 0.0, 1.0, 1.0, (0.0, 0.0, 0.0, 1.0))
    with pytest.raises(ConfigurationError):
        SwarmObject("x", "food", 0.0, 0.0, 0.0, 1.0, (0.0, 0.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------


def _trajectories(intervals: int = 200, flies: int = 3) -> SwarmTrajectories:
    t_us = np.arange(1, intervals + 1, dtype=np.int64) * 15_000
    angle = np.linspace(0.0, 2.0, intervals)[:, None] + np.arange(flies)[None, :]
    radius = np.linspace(20.0, 4.0, intervals)[:, None]
    return SwarmTrajectories(
        fly_ids=tuple(f"fly-{index}" for index in range(flies)),
        labels=tuple(f"FLY-{index}" for index in range(flies)),
        t_us=t_us,
        x_mm=radius * np.cos(angle),
        y_mm=radius * np.sin(angle),
        z_mm=np.full((intervals, flies), 1.1),
        heading_rad=angle,
        rows=tuple({"t_us": int(value), "flies": []} for value in t_us),
    )


def test_a_shot_rejects_a_mode_it_cannot_draw_and_a_subject_it_does_not_have() -> None:
    with pytest.raises(ConfigurationError):
        Shot(name="x", caption="", video_seconds=1.0, sim_start_s=0.0, mode="dolly")
    with pytest.raises(ConfigurationError):
        Shot(name="x", caption="", video_seconds=1.0, sim_start_s=0.0, mode="follow")
    with pytest.raises(ConfigurationError):
        Shot(name="x", caption="", video_seconds=0.0, sim_start_s=0.0)


def test_the_timeline_maps_every_video_instant_to_one_shot_and_one_recorded_time() -> None:
    timeline = Timeline(
        (
            Shot(name="a", caption="", video_seconds=4.0, sim_start_s=0.0, sim_rate=1.0),
            Shot(name="b", caption="", video_seconds=6.0, sim_start_s=10.0, sim_rate=0.5),
        )
    )
    assert timeline.video_seconds == 10.0
    assert timeline.frame_count(30) == 300
    shot, u = timeline.at(0.0)
    assert shot.name == "a" and u == 0.0
    shot, u = timeline.at(2.0)
    assert shot.name == "a" and u == pytest.approx(0.5)
    shot, u = timeline.at(4.0)
    assert shot.name == "b" and u == 0.0
    shot, u = timeline.at(7.0)
    assert shot.name == "b" and shot.sim_time(u) == pytest.approx(11.5)
    # Past the end, the last shot holds rather than raising, so a rounding error at the
    # final frame cannot lose the closing shot.
    shot, u = timeline.at(10.0)
    assert shot.name == "b" and u == 1.0


def test_a_recorded_time_past_the_end_of_the_recording_clamps() -> None:
    trajectories = _trajectories()
    assert trajectories.index_at(-5.0) == 0
    assert trajectories.index_at(1e6) == trajectories.intervals - 1


def test_the_camera_never_gets_closer_than_the_floor() -> None:
    trajectories = _trajectories()
    shot = Shot(
        name="close",
        caption="",
        video_seconds=4.0,
        sim_start_s=0.0,
        mode="follow",
        subject="fly-0",
        distance_start_mm=0.1,
        distance_end_mm=0.1,
    )
    for u in (0.0, 0.5, 1.0):
        framing = camera_for(shot, u, trajectories)
        assert framing.distance_mm >= MINIMUM_CAMERA_DISTANCE_MM


def test_a_pair_shot_opens_out_far_enough_to_hold_both_flies() -> None:
    trajectories = _trajectories()
    shot = Shot(
        name="pair",
        caption="",
        video_seconds=4.0,
        sim_start_s=0.0,
        mode="pair",
        subject="fly-0",
        partner="fly-1",
        distance_start_mm=5.0,
        distance_end_mm=5.0,
    )
    framing = camera_for(shot, 0.0, trajectories)
    separation = float(
        np.hypot(
            trajectories.x_mm[0, 0] - trajectories.x_mm[0, 1],
            trajectories.y_mm[0, 0] - trajectories.y_mm[0, 1],
        )
    )
    assert framing.distance_mm > separation


def test_smoothing_moves_the_camera_and_not_the_recorded_trajectory() -> None:
    trajectories = _trajectories()
    smoothed = trajectories.smoothed(window=9)
    assert smoothed.x_mm.shape == trajectories.x_mm.shape
    assert not np.allclose(smoothed.x_mm, trajectories.x_mm)
    # The original is untouched: the drawn body always comes from the recorded state.
    assert trajectories.smoothed(window=1) is trajectories


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------


def test_glow_depends_only_on_which_interval_is_shown(tmp_path: Path) -> None:
    """Two visits to the same moment must look the same, or the shot list is lying.

    The video revisits earlier stretches of the recording from different angles. A glow
    carried forward in a variable would make the second visit brighter than the first for
    reasons the viewer cannot see.
    """
    from flysim.demo01_render import SpikeRecording
    from flysim.swarm3d_video import decayed_glow

    rng = np.random.default_rng(7)
    intervals, neurons = 40, 64
    chunks = [rng.integers(0, neurons, size=int(rng.integers(1, 12))) for _ in range(intervals)]
    offsets = np.zeros(intervals + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([chunk.size for chunk in chunks])
    path = tmp_path / "spikes.npz"
    np.savez_compressed(
        path,
        offsets=offsets,
        indices=np.concatenate(chunks).astype(np.uint32),
        counts=np.ones(int(offsets[-1]), dtype=np.uint8),
        neuron_count=np.int64(neurons),
    )
    spikes = SpikeRecording(path)
    row_by_dense = np.arange(neurons, dtype=np.int64)

    first = decayed_glow(spikes, row_by_dense, 25, drawn=neurons)
    again = decayed_glow(spikes, row_by_dense, 25, drawn=neurons)
    assert np.array_equal(first, again)
    # And it is not simply the whole recording summed: the decay has to forget.
    assert not np.array_equal(
        first, decayed_glow(spikes, row_by_dense, 25, drawn=neurons, decay=1.0, span=26)
    )


# ---------------------------------------------------------------------------
# The world itself
# ---------------------------------------------------------------------------


mujoco = pytest.importorskip("mujoco", reason="the swarm world needs MuJoCo")
pytest.importorskip("flygym", reason="the swarm world needs FlyGym")


def _arena_from_demo01() -> tuple[SwarmArenaParameters, dict]:
    demo01 = json.loads(DEMO01_SCENARIO.read_text(encoding="utf-8"))["body"]
    arena = SwarmArenaParameters.from_mapping(
        {**demo01, "ground_half_size_mm": 100.0}
    )
    return arena, demo01


@pytest.mark.slow
def test_one_fly_in_the_swarm_world_moves_exactly_like_the_demo01_body() -> None:
    """The duplication is checked rather than asserted.

    `SwarmWorld` reimplements DEMO-01's per-fly actuation because DEMO-01's body owns a
    world of its own and cannot hold twelve. That is a fork, and a fork that drifts would
    mean the swarm's flies are not the fly the DEMO-01 evidence describes. This test walks
    both through the identical command sequence and requires the full generalised position
    vector to agree.
    """
    from flysim.contracts import ActuatorCommandFrame, SignalType
    from flysim.demo01_body import Demo01BodyParameters, Demo01VisualBody
    from flysim.engines.body import COMMAND_IDS
    from flysim.swarm3d import SwarmWorld

    arena, demo01 = _arena_from_demo01()
    body_parameters = Demo01BodyParameters.from_mapping(demo01)

    def command(t_us: int, forward: float, yaw: float) -> ActuatorCommandFrame:
        return ActuatorCommandFrame(
            t_us=t_us,
            ids=COMMAND_IDS,
            values=(forward, yaw, 0.0, 0.0),
            units="normalized",
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-06",),
            metadata={"decoder_state": "LOCOMOTING"},
        )

    spec = SwarmFlySpec(
        "demo01_fly",
        body_parameters.initial_x_mm,
        body_parameters.initial_y_mm,
        body_parameters.initial_heading_rad,
    )
    world = SwarmWorld(
        arena, (spec,), (), seed=1, camera_resolution=(120, 160),
        appearance=False, lighting=False,
    )
    body = Demo01VisualBody(body_parameters, seed=1, camera_resolution=(120, 160))
    try:
        sequence = [(0.0, 0.0)] * 20 + [(0.6, 0.2)] * 40 + [(0.8, -0.3)] * 40
        for step, (forward, yaw) in enumerate(sequence):
            t_us = step * 15_000
            world.apply_actuators(0, command(t_us, forward, yaw))
            body.apply_actuators(command(t_us, forward, yaw))
            world.step_until(t_us + 15_000)
            body.step_until(t_us + 15_000)
        assert np.allclose(world.qpos(), body.qpos(), rtol=0.0, atol=0.0)
        assert world.pose(0) == body.pose()
    finally:
        world.close()
        body.close()


@pytest.mark.slow
def test_the_replay_path_refuses_a_world_that_has_been_stepped() -> None:
    """The structural reason rendering cannot alter a run."""
    from flysim.swarm3d import SwarmWorld

    arena, _ = _arena_from_demo01()
    arena = SwarmArenaParameters.from_mapping(
        {**arena.as_dict(), "station_keeping_settle_us": 0}
    )
    world = SwarmWorld(
        arena,
        (SwarmFlySpec("a", 0.0, 0.0, 0.0),),
        (),
        seed=1,
        camera_resolution=(120, 160),
        appearance=False,
        lighting=False,
    )
    try:
        frame = world.render_replay_frame(
            world.qpos(),
            lookat_mm=(0.0, 0.0, 1.5),
            distance_mm=20.0,
            azimuth_deg=45.0,
            elevation_deg=-20.0,
        )
        assert frame.shape == (120, 160, 3)
        world.step_until(1_000)
        with pytest.raises(CausalityError):
            world.render_replay_frame(
                world.qpos(),
                lookat_mm=(0.0, 0.0, 1.5),
                distance_mm=20.0,
                azimuth_deg=45.0,
                elevation_deg=-20.0,
            )
    finally:
        world.close()


@pytest.mark.slow
def test_objects_are_compiled_into_the_model_with_contact_pairs() -> None:
    """A pillar a fly walks through is a decoration, not an obstacle."""
    from flysim.swarm3d import SwarmWorld

    arena, _ = _arena_from_demo01()
    objects = (
        SwarmObject("food-1", "food", 6.0, 0.0, 2.0, 1.7, (0.9, 0.3, 0.1, 1.0)),
        SwarmObject("pillar-1", "pillar", -6.0, 0.0, 1.2, 3.0, (0.4, 0.4, 0.4, 1.0)),
    )
    world = SwarmWorld(
        arena,
        (SwarmFlySpec("a", 0.0, 0.0, 0.0),),
        objects,
        seed=1,
        camera_resolution=(120, 160),
        appearance=False,
        lighting=False,
    )
    try:
        description = world.describe()
        assert description["model"]["explicit_object_contact_pairs"] > 0
        model = world.render_model
        for name in ("object_food-1_geom", "object_pillar-1_geom"):
            assert (
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name) >= 0
            ), name
    finally:
        world.close()
