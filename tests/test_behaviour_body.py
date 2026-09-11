# SPDX-License-Identifier: GPL-2.0-or-later
"""The behaviour body: one plant per experiment, and a sensor path that cannot shortcut.

These need MuJoCo and are slower than the rest of the suite, because the thing worth
checking is what the physics does rather than what the code says it does.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mujoco", reason="the body needs MuJoCo")
pytest.importorskip("flygym", reason="the body needs FlyGym")

from flysim.behaviour_body import (
    BEHAVIOURS,
    SPECIAL_DOFS,
    BehaviourBody,
    BehaviourBodyParameters,
)
from flysim.contracts import ActuatorCommandFrame, SignalType
from flysim.engines.body import (
    BEHAVIOUR_COMMAND_IDS,
    COMMAND_GROOM,
    COMMAND_IDS,
    COMMAND_JUMP,
)
from flysim.errors import ConfigurationError

ROOT = Path(os.environ.get("FLYSIM_DATA_ROOT", "/srv/flybrain-data"))
TRAJECTORY = (
    ROOT / "derived/auxiliary/ozdil-2026-antennal-grooming/track-a-grooming-trajectory.npz"
)
COUPLING_US = 15_000


def _body(behaviour: str, **overrides: object) -> BehaviourBody:
    settings = {"station_keeping_settle_us": 0, "antennal_stimulus_side": "none"}
    settings.update(overrides)
    return BehaviourBody(
        parameters=BehaviourBodyParameters(**settings),  # type: ignore[arg-type]
        behaviour=behaviour,
        seed=1,
        trajectory_path=TRAJECTORY if behaviour == "grooming" else None,
    )


def _command(t_us: int, **values: float) -> ActuatorCommandFrame:
    return ActuatorCommandFrame(
        t_us=t_us,
        ids=BEHAVIOUR_COMMAND_IDS,
        values=tuple(values.get(name, 0.0) for name in BEHAVIOUR_COMMAND_IDS),
        units="normalized",
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MOTOR-03",),
    )


def test_each_behaviour_actuates_a_different_plant_and_says_so() -> None:
    """DEMO-01's gains belong to a 42-actuator plant. A digest makes a swap detectable,
    because qpos stays 133 and the replay renderer only checks qpos shape."""
    digests = {}
    for behaviour in BEHAVIOURS:
        if behaviour == "grooming" and not TRAJECTORY.exists():
            continue
        body = _body(behaviour)
        try:
            described = body.describe()
            digests[behaviour] = described["actuator_set_digest"]
            assert described["qpos_size"] == 133
            assert described["leg_dof_count"] == 42
            assert described["actuated_dof_count"] > 42
        finally:
            body.close()
    assert len(set(digests.values())) == len(digests), digests


def test_only_the_declared_extra_joints_are_actuated() -> None:
    body = _body("escape")
    try:
        names = body.describe()["actuated_dofs"][42:]
        assert all("wing" in name for name in names)
        assert len(names) == 6
        # Feeding's joints must not be actuated here, or the plant is not what it says.
        assert not any("rostrum" in name or "pedicel" in name for name in names)
    finally:
        body.close()


def test_the_special_dof_table_covers_every_behaviour() -> None:
    assert set(SPECIAL_DOFS) == set(BEHAVIOURS)


def test_an_unknown_behaviour_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Unknown behaviour"):
        _body("flying")


def test_the_body_publishes_world_quantities_and_labels_each_kind() -> None:
    body = _body("feeding")
    try:
        sensors = body.sample_sensors()
        kinds = sensors.metadata["channel_kind"]
        assert len(sensors.ids) == len(sensors.values) == len(kinds)
        assert len(sensors.units.split(",")) == len(sensors.ids)
        assert kinds["world:antenna-deflection:l"] == "real"
        assert kinds["world:tarsal-sucrose:lf"] == "declared"
        # The senses with no world quantity are named rather than quietly missing.
        assert set(sensors.metadata["absent_channels"]) == {
            "temperature", "humidity", "sound", "wind",
        }
    finally:
        body.close()


def test_sucrose_needs_contact_and_not_merely_proximity() -> None:
    """Track A's sucrose channel was a distance threshold, so a fly could 'taste' food it
    had never touched. This one is gated on the tarsus actually being on the ground."""
    body = _body("feeding", sucrose_x_mm=0.0, sucrose_y_mm=0.0, sucrose_radius_mm=50.0)
    try:
        body.step_until(COUPLING_US)
        touching = body.sample_sensors().value_for("world:tarsal-sucrose:lf")
        assert touching > 0.0, "a planted tarsus inside a huge patch should taste it"
    finally:
        body.close()

    far = _body("feeding", sucrose_x_mm=500.0, sucrose_y_mm=500.0)
    try:
        far.step_until(COUPLING_US)
        assert far.sample_sensors().value_for("world:tarsal-sucrose:lf") == 0.0
    finally:
        far.close()


@pytest.mark.skipif(not TRAJECTORY.exists(), reason="the Ozdil derivative is not staged")
def test_station_keeping_drops_the_legs_the_replay_overwrites() -> None:
    """MOTOR-05. Track A computed all six channels during a bout and let the grooming
    replay overwrite the two front ones, so a third of the control effort was discarded
    while the integral kept accumulating its error."""
    body = _body("grooming")
    try:
        body.apply_actuators(_command(0, **{COMMAND_GROOM: 1.0}))
        body.step_until(COUPLING_US)
        legs = body.station_keeping()["active_channel_legs"]
        assert set(legs) == {"lm", "lh", "rm", "rh"}
        assert "lf" not in legs and "rf" not in legs
    finally:
        body.close()


def test_station_keeping_uses_every_leg_when_nothing_overwrites_it() -> None:
    body = _body("feeding")
    try:
        body.step_until(COUPLING_US)
        assert len(body.station_keeping()["active_channel_legs"]) == 6
    finally:
        body.close()


def test_a_jump_leaves_the_ground_and_the_record_says_no_lift_was_computed() -> None:
    body = _body("escape")
    try:
        for step in range(40):
            t_us = step * COUPLING_US
            body.apply_actuators(
                _command(t_us, **({COMMAND_JUMP: 1.0} if step >= 4 else {}))
            )
            body.step_until(t_us + COUPLING_US)
        takeoff = body.takeoff()
        # The measured standing contact-chatter floor is 5.0-5.5 ms, so this is a real
        # departure rather than contact noise.
        assert takeoff["longest_airborne_us"] > 20_000
        assert takeoff["z_rise_mm"] > 1.0
        assert takeoff["no_aerodynamic_force_was_computed"] is True
    finally:
        body.close()


def test_a_body_given_no_command_stays_on_the_ground() -> None:
    """The other half of the jump test: without it, 'it left the ground' is not a result."""
    body = _body("escape")
    try:
        for step in range(40):
            body.apply_actuators(_command(step * COUPLING_US))
            body.step_until(step * COUPLING_US + COUPLING_US)
        takeoff = body.takeoff()
        assert takeoff["longest_airborne_us"] <= 20_000
        assert takeoff["z_rise_mm"] < 1.0
    finally:
        body.close()


def test_a_command_frame_carrying_only_the_original_four_is_still_legal() -> None:
    """COMMAND_IDS stays four wide because five producers build values tuples against it
    positionally, and DEMO-01's recordings were made with it."""
    body = _body("escape")
    try:
        body.apply_actuators(
            ActuatorCommandFrame(
                t_us=0,
                ids=COMMAND_IDS,
                values=(0.0, 0.0, 0.0, 0.0),
                units="normalized",
                signal_type=SignalType.ACTUATOR_COMMAND,
                provenance="E",
                assumption_ids=("MOTOR-03",),
            )
        )
        body.step_until(COUPLING_US)
    finally:
        body.close()


def test_qpos_is_a_copy_so_a_recording_cannot_alias_the_simulator() -> None:
    body = _body("feeding")
    try:
        first = body.qpos()
        first[:] = 0.0
        assert not np.allclose(body.qpos(), 0.0)
    finally:
        body.close()
