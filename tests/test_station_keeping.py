# SPDX-License-Identifier: GPL-2.0-or-later
"""The Track A station-keeping controller, exercised without building a MuJoCo model.

The controller is arithmetic over the thorax pose, the registered gains and the actuator
channel, so it is tested directly. Two of these tests exist because of specific mistakes
made while building it: the offset limit landed outside the channel's monotone branch and
the controller saturated onto the worst operating point available to it, and the integral
kept accumulating while the offset was clamped so it could not respond when the error
reversed.
"""

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flysim.engines.flygym import (
    STATION_KEEPING_DOF,
    STATION_KEEPING_LEFT_LEGS,
    STATION_KEEPING_LEGS,
    FlyGymTrackABodyEngine,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parents[1]
ASSUMPTIONS = REPO / "configs" / "assumptions.json"

# The offset at which the measured drift velocity crosses zero, and the upper edge of the
# monotone branch it sits in. Both come from the static response curve recorded in
# docs/evidence/TRACK_A_STATION_KEEPING.md.
MEASURED_NULL_RAD = 0.055
MONOTONE_BRANCH_EDGE_RAD = 0.07


class _StubBody:
    """A body whose pose the test sets directly, with the real controller attached."""

    def __init__(self, pose: tuple[float, float, float] = (0.0, 0.0, 0.0), **gains: float) -> None:
        defaults = {
            "station_keeping_gain_rad_per_mm": 0.02,
            "station_keeping_integral_rad_per_mm_s": 0.06,
            "station_keeping_yaw_gain_rad_per_rad": 0.05,
            "station_keeping_yaw_integral_rad_per_rad_s": 0.4,
            "station_keeping_max_offset_rad": 0.07,
            "station_keeping_max_yaw_offset_rad": 0.02,
            "physics_dt_us": 500,
        }
        defaults.update(gains)
        self.parameters = type("P", (), defaults)
        self.pose = pose
        self._station_reference: tuple[float, float, float] | None = None
        self._station_offsets_rad = (0.0, 0.0)
        self._station_error_mm = 0.0
        self._station_peak_error_mm = 0.0
        self._station_fore_aft_integral_mm_s = 0.0
        self._station_yaw_integral_rad_s = 0.0
        self._actuator_index = {
            STATION_KEEPING_DOF.format(leg=leg): index
            for index, leg in enumerate(STATION_KEEPING_LEGS)
        }
        self._station_keeping_channel = (
            FlyGymTrackABodyEngine._build_station_keeping_channel(self)  # type: ignore[arg-type]
        )
        self._clamped_integral = FlyGymTrackABodyEngine._clamped_integral
        self._release_station_reference = self.release
        self._reset_station_keeping = self.reset

    def _pose(self) -> tuple[float, float, float, float]:
        x, y, heading = self.pose
        return x, y, 0.0, heading

    def apply(self, steps: int = 1) -> np.ndarray:
        targets = np.zeros(len(STATION_KEEPING_LEGS), dtype=np.float64)
        for _ in range(steps):
            targets[:] = 0.0
            FlyGymTrackABodyEngine._apply_station_keeping(self, targets)  # type: ignore[arg-type]
        return targets

    def release(self) -> None:
        FlyGymTrackABodyEngine._release_station_reference(self)  # type: ignore[arg-type]

    def reset(self) -> None:
        FlyGymTrackABodyEngine._reset_station_keeping(self)  # type: ignore[arg-type]


def _record(identifier: str) -> dict[str, Any]:
    records = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))["records"]
    return next(item for item in records if item["id"] == identifier)


# --- what the loop does ----------------------------------------------------------------


def test_the_first_call_latches_a_reference_and_commands_nothing() -> None:
    """Station-keeping holds wherever standing began, so it must observe before acting."""
    body = _StubBody(pose=(3.0, -1.0, 0.4))

    targets = body.apply()

    assert body._station_reference == (3.0, -1.0, 0.4)
    assert np.all(targets == 0.0)


def test_a_forward_error_commands_a_positive_common_offset() -> None:
    """The measured channel opposes forward drift as the offset increases."""
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()

    body.pose = (0.5, 0.0, 0.0)
    targets = body.apply()

    assert body._station_offsets_rad[0] > 0.0
    assert np.all(targets > 0.0)
    # Common mode means every leg gets the same push; nothing here should yaw the body.
    assert targets.std() == pytest.approx(0.0)


def test_the_error_is_measured_in_the_frame_standing_began_in() -> None:
    """A body facing +y that slid in world +x has slid sideways, not forward."""
    body = _StubBody(pose=(0.0, 0.0, math.pi / 2.0))
    body.apply()

    body.pose = (1.0, 0.0, math.pi / 2.0)
    body.apply()

    assert body._station_offsets_rad[0] == pytest.approx(0.0)
    # The displacement is still recorded, because it is real and must not vanish.
    assert body._station_error_mm == pytest.approx(1.0)


def test_a_heading_error_yaws_the_body_and_left_opposes_right() -> None:
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()

    body.pose = (0.0, 0.0, 0.1)
    targets = body.apply()

    left = [
        targets[body._actuator_index[STATION_KEEPING_DOF.format(leg=leg)]]
        for leg in STATION_KEEPING_LEGS
        if leg in STATION_KEEPING_LEFT_LEGS
    ]
    right = [
        targets[body._actuator_index[STATION_KEEPING_DOF.format(leg=leg)]]
        for leg in STATION_KEEPING_LEGS
        if leg not in STATION_KEEPING_LEFT_LEGS
    ]
    assert body._station_offsets_rad[1] > 0.0
    assert left[0] == pytest.approx(-right[0])
    assert all(value == pytest.approx(left[0]) for value in left)


def test_the_integral_accumulates_over_steps() -> None:
    """Proportional action alone cannot reach the offset the drift force needs."""
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()
    body.pose = (0.4, 0.0, 0.0)

    body.apply(steps=1)
    after_one = body._station_offsets_rad[0]
    body.apply(steps=200)
    after_many = body._station_offsets_rad[0]

    assert after_many > after_one
    proportional_only = body.parameters.station_keeping_gain_rad_per_mm * 0.4
    # One step of integral action is one 500 us sample, so the first offset is the
    # proportional term to within that.
    assert after_one == pytest.approx(proportional_only, abs=1e-4)
    assert after_many > proportional_only


# --- the two mistakes this controller made -------------------------------------------


def test_the_integral_cannot_wind_past_what_the_limit_allows() -> None:
    """Anti-windup. Without it the accumulator grows while the offset is clamped, and
    the controller cannot respond when the error later reverses."""
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()
    body.pose = (5.0, 0.0, 0.0)

    body.apply(steps=5000)
    limit = body.parameters.station_keeping_max_offset_rad
    integral_gain = body.parameters.station_keeping_integral_rad_per_mm_s
    assert abs(integral_gain * body._station_fore_aft_integral_mm_s) <= limit + 1e-12

    # And the wound-up controller must still respond to a reversal within a bounded time.
    body.pose = (-5.0, 0.0, 0.0)
    body.apply(steps=5000)
    assert body._station_offsets_rad[0] < 0.0


def test_the_registered_offset_limit_stays_inside_the_measured_monotone_branch() -> None:
    """The drift velocity is not monotone in the offset: it crosses zero near 0.055 rad
    but at 0.12 rad it is worse than no control at all. A limit outside the first branch
    lets the controller saturate onto its own worst operating point, which is what the
    first sweep did."""
    value = _record("MOTOR-04")["value"]

    assert value["station_keeping_max_offset_rad"] <= MONOTONE_BRANCH_EDGE_RAD
    assert value["station_keeping_max_offset_rad"] > MEASURED_NULL_RAD
    # The yaw term shares the per-leg budget, so it must not be able to consume it.
    assert value["station_keeping_max_yaw_offset_rad"] < value["station_keeping_max_offset_rad"]


def test_no_leg_is_pushed_past_the_offset_limit() -> None:
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()
    body.pose = (50.0, 0.0, 1.0)

    targets = body.apply(steps=5000)

    assert np.all(np.abs(targets) <= body.parameters.station_keeping_max_offset_rad + 1e-12)


# --- disabling and resetting ---------------------------------------------------------


def test_zero_gains_leave_the_body_exactly_as_it_was() -> None:
    """The open-loop pose hold must remain reachable, so a zeroed controller is inert."""
    body = _StubBody(
        pose=(0.0, 0.0, 0.0),
        station_keeping_gain_rad_per_mm=0.0,
        station_keeping_integral_rad_per_mm_s=0.0,
        station_keeping_yaw_gain_rad_per_rad=0.0,
        station_keeping_yaw_integral_rad_per_rad_s=0.0,
    )
    body.pose = (5.0, 5.0, 1.0)

    targets = body.apply(steps=10)

    assert np.all(targets == 0.0)
    assert body._station_reference is None


def test_walking_releases_the_position_but_keeps_the_bias() -> None:
    """The bias holds the body up; it is a property of the load, not of a position.

    Discarding it on every walk makes each new stance re-converge from zero, and the
    re-convergence excursion is itself most of the displacement the standing criteria
    measure. So walking releases only where the body was standing.
    """
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()
    body.pose = (1.0, 0.0, 0.2)
    body.apply(steps=500)
    assert body._station_fore_aft_integral_mm_s > 0.0

    body.release()

    assert body._station_reference is None
    assert body._station_offsets_rad == (0.0, 0.0)
    assert body._station_fore_aft_integral_mm_s > 0.0
    assert body._station_yaw_integral_rad_s > 0.0


def test_a_full_reset_does_discard_the_bias() -> None:
    """Only a disabled controller clears it, so a zeroed build carries nothing forward."""
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()
    body.pose = (1.0, 0.0, 0.2)
    body.apply(steps=500)

    body.reset()

    assert body._station_fore_aft_integral_mm_s == 0.0
    assert body._station_yaw_integral_rad_s == 0.0


def test_a_disabled_axis_does_not_accumulate() -> None:
    body = _StubBody(pose=(0.0, 0.0, 0.0), station_keeping_integral_rad_per_mm_s=0.0)
    body.apply()
    body.pose = (1.0, 0.0, 0.0)

    body.apply(steps=100)

    assert body._station_fore_aft_integral_mm_s == 0.0
    assert body._station_offsets_rad[0] == pytest.approx(0.02 * 1.0)


def test_the_peak_error_is_recorded_and_never_falls() -> None:
    body = _StubBody(pose=(0.0, 0.0, 0.0))
    body.apply()

    body.pose = (2.0, 0.0, 0.0)
    body.apply()
    body.pose = (0.1, 0.0, 0.0)
    body.apply()

    assert body._station_error_mm == pytest.approx(0.1)
    assert body._station_peak_error_mm == pytest.approx(2.0)


def test_a_missing_control_channel_fails_closed() -> None:
    body = _StubBody()
    body._actuator_index = {"something-else": 0}

    with pytest.raises(ConfigurationError, match="not an actuated Track A DOF"):
        FlyGymTrackABodyEngine._build_station_keeping_channel(body)  # type: ignore[arg-type]


# --- what the registry has to say about it -------------------------------------------


def test_the_controller_is_registered_as_an_engineering_scaffold() -> None:
    record = _record("MOTOR-04")

    assert record["provenance"] == "E"
    # It must say plainly that no fly does this, or it will be read as a model of one.
    assert "campaniform" in record["biological_mismatch"]
    assert "no biological content" in record["biological_mismatch"].lower() or (
        "Entirely non-biological" in record["biological_mismatch"]
    )
    scenario = json.loads(
        (REPO / "configs" / "scenarios" / "eon-malecns.json").read_text(encoding="utf-8")
    )
    assert "MOTOR-04" in scenario["required_assumptions"]
