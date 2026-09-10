# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the DEMO-01 body.

The body is where a demonstration quietly goes wrong. A fly that slides while standing
makes a control variant travel further than the run it is controlling for, which is
exactly what happened here before the stance was fixed, so the properties pinned below are
the ones whose failure would corrupt the acceptance criteria without looking like a bug.

The tests that need MuJoCo are marked and skipped when it is unavailable, because the rest
still catch parameter and wiring faults.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from flysim.demo01_body import (
    SCAFFOLDS,
    Demo01BodyParameters,
    Demo01VisualBody,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parent.parent
SCENARIO = REPO / "configs/scenarios/demo01-visual-approach.json"

pytest.importorskip("mujoco", reason="the body needs MuJoCo")


@pytest.fixture(scope="module")
def scenario() -> dict:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


@pytest.fixture
def parameters(scenario: dict) -> Demo01BodyParameters:
    return Demo01BodyParameters.from_mapping(scenario["body"])


# ---------------------------------------------------------------------------
# Parameters and the scenario that supplies them
# ---------------------------------------------------------------------------


def test_the_coupling_interval_is_a_whole_number_of_physics_steps(scenario: dict) -> None:
    """A coupling boundary off the physics grid raises mid-run, after minutes of compute."""
    contract = json.loads(
        (REPO / "configs/experiments/demo01-visual-operating-point-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert int(contract["coupling_us"]) % int(scenario["body"]["physics_dt_us"]) == 0


def test_the_settle_window_is_a_whole_number_of_physics_steps(scenario: dict) -> None:
    body = scenario["body"]
    assert int(body["station_keeping_settle_us"]) % int(body["physics_dt_us"]) == 0


def test_the_body_uses_track_as_registered_spawn_height_and_step(scenario: dict) -> None:
    """Both were invented once and both broke the stance, so both are pinned.

    A 1.35 mm spawn made the fly fall and land hard: the thorax sank from 1.374 to 0.798 mm
    and the body slid. A 1000 us step made contacts less stable.
    """
    body = scenario["body"]
    assert body["spawn_height_mm"] == 0.5
    assert body["physics_dt_us"] == 500


def test_the_offset_limits_stay_inside_the_measured_monotone_branch(scenario: dict) -> None:
    """Track A measured the channel reversing sign near 0.055 rad and being worse than no
    control at 0.12 rad. Raising the limit past that saturates onto the worst point."""
    body = scenario["body"]
    assert body["station_keeping_max_offset_rad"] <= 0.07
    assert body["station_keeping_max_yaw_offset_rad"] <= 0.02


def test_the_scenario_records_why_the_body_values_are_what_they_are(scenario: dict) -> None:
    why = scenario["body"]["why_these_body_values"]
    assert "1.35" in why["spawn_height_mm"]
    assert "14.413" in why["station_keeping"]
    assert "2.294" in why["station_keeping"]
    assert "non-monotone" in why["the_offset_limits_are_not_safety_margins"]


def test_bad_parameters_are_refused(scenario: dict) -> None:
    base = dict(scenario["body"])
    for bad in (
        {"physics_dt_us": 0},
        {"cue_radius_mm": 0.0},
        {"max_forward_mm_s": 0.0},
        {"max_yaw_rad_s": 0.0},
        {"station_keeping_max_offset_rad": -0.01},
        {"station_keeping_max_yaw_offset_rad": -0.01},
        {"station_keeping_settle_us": 777},
    ):
        with pytest.raises(ConfigurationError):
            Demo01BodyParameters.from_mapping({**base, **bad})


def test_the_scaffolds_are_named_rather_than_implied() -> None:
    """The video prints these, so they must say what is engineered and what is missing."""
    joined = " ".join(SCAFFOLDS).lower()
    assert "central pattern generator" in joined
    assert "adhesion" in joined
    assert "female" in joined
    assert "proportional-integral" in joined


# ---------------------------------------------------------------------------
# The stance, which is the part that broke
# ---------------------------------------------------------------------------


def test_the_integral_survives_a_walk_but_the_position_reference_does_not(
    parameters: Demo01BodyParameters,
) -> None:
    """Track A's distinction, which my first port lost.

    The integral has converged on the actuator bias that cancels the drift force, and that
    force belongs to the standing configuration rather than to a position. Discarding it
    whenever the fly walks makes every new stance re-converge from zero, and the
    re-convergence excursion is most of the displacement the standing criteria measure.
    """
    body = Demo01VisualBody(parameters, seed=1, camera_resolution=(64, 64))
    try:
        body._station_fore_aft_integral_mm_s = 1.25
        body._station_yaw_integral_rad_s = 0.75
        body._station_reference = (1.0, 2.0, 0.3)
        body._release_station_reference()
        assert body._station_reference is None
        assert body._station_fore_aft_integral_mm_s == 1.25
        assert body._station_yaw_integral_rad_s == 0.75
        # Only an explicit reset discards the bias.
        body._reset_station_keeping()
        assert body._station_fore_aft_integral_mm_s == 0.0
        assert body._station_yaw_integral_rad_s == 0.0
    finally:
        body.close()


def test_the_station_keeping_channel_covers_all_six_legs(
    parameters: Demo01BodyParameters,
) -> None:
    body = Demo01VisualBody(parameters, seed=1, camera_resolution=(64, 64))
    try:
        channel = body._station_keeping_channel
        assert len(channel) == 6
        signs = sorted(sign for _, sign in channel)
        # Three legs on each side, so common mode shifts fore-aft and differential yaws.
        assert signs == [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
    finally:
        body.close()


def test_the_convergence_window_leaves_the_body_where_it_found_it(
    parameters: Demo01BodyParameters,
) -> None:
    """The settle is a calibration, not simulated behaviour, so it must not move the fly."""
    with_settle = Demo01VisualBody(parameters, seed=1, camera_resolution=(64, 64))
    try:
        settled_pose = with_settle.pose()
        assert with_settle.station_keeping()["settle_us"] > 0
    finally:
        with_settle.close()

    from dataclasses import replace

    without = Demo01VisualBody(
        replace(parameters, station_keeping_settle_us=0), seed=1, camera_resolution=(64, 64)
    )
    try:
        bare_pose = without.pose()
        assert without.station_keeping()["settle_us"] == 0
    finally:
        without.close()

    # The settle charges the integral and restores every physics state, so the starting
    # pose has to match to well under a body length.
    assert math.hypot(settled_pose[0] - bare_pose[0], settled_pose[1] - bare_pose[1]) < 0.05
    assert abs(settled_pose[2] - bare_pose[2]) < 0.05


def test_the_body_publishes_no_sensory_channel(parameters: Demo01BodyParameters) -> None:
    """A sensory channel is a shortcut waiting to be taken, so there are none."""
    body = Demo01VisualBody(parameters, seed=1, camera_resolution=(64, 64))
    try:
        described = body.describe()
        assert described["sensor_channels_published"] == []
        assert "shortcut" in described["why_no_sensor_channels"]
        assert not hasattr(body, "sample_sensors")
    finally:
        body.close()


@pytest.mark.slow
def test_a_fly_commanded_to_stand_stays_put(parameters: Demo01BodyParameters) -> None:
    """The measured bound. Its failure is what made a control travel further than its run.

    Five seconds rather than twenty, to keep the test quick; the 20 s figure recorded in
    the scenario is 2.294 mm and the drift is close to linear in time, so 1.5 mm over 5 s
    is the same claim with margin.
    """
    from flysim.contracts import ActuatorCommandFrame, SignalType
    from flysim.engines.body import COMMAND_IDS

    body = Demo01VisualBody(parameters, seed=1, camera_resolution=(64, 64))
    try:
        x0, y0, _, _ = body.pose()
        coupling_us = 15000
        for step in range(5_000_000 // coupling_us):
            t_us = step * coupling_us
            body.apply_actuators(
                ActuatorCommandFrame(
                    t_us=t_us,
                    ids=COMMAND_IDS,
                    values=(0.0, 0.0, 0.0, 0.0),
                    units="normalized",
                    signal_type=SignalType.ACTUATOR_COMMAND,
                    provenance="E",
                    assumption_ids=("MOTOR-06",),
                    metadata={"decoder_state": "QUIESCENT"},
                )
            )
            body.step_until(t_us + coupling_us)
        x1, y1, _, _ = body.pose()
        drift = math.hypot(x1 - x0, y1 - y0)
        assert drift < 1.5, f"a standing fly drifted {drift:.3f} mm in 5 s"
    finally:
        body.close()
