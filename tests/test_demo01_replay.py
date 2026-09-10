# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the offline body renderer and its shot list.

The shot list is the part of this project most likely to drift into decoration, so the
tests below are about the properties that make a shot honest rather than about how it
looks: that the camera keeps the animal as the subject, that it never quietly reframes on
an object the brain cannot see, that a cut happens because the fly moved rather than
because a timeline said so, and that the display-only smoothing stays display-only.

The regression that motivated all of this is pinned directly. The first camera aimed at the
midpoint between fly and cue at a distance proportional to their separation, so as the fly
arrived the shot collapsed and a 2.5 mm sphere filled a frame the 3 mm fly had left.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from flysim.demo01_replay import (
    SHOT_FRAMING,
    SHOT_ORDER,
    CameraFraming,
    PoseRecording,
    ShotPlan,
    frame_camera,
    smooth_track,
)
from flysim.errors import ConfigurationError, ReadinessError

CUE_XY = (0.0, 14.0)
CUE_RADIUS = 2.5
CUE_HEIGHT = 2.5


def _framing(shot: str, *, fly=(0.0, 0.0, 1.05), heading=0.0, present=True, t_s=0.0):
    return frame_camera(
        shot,
        fly_xyz_mm=fly,
        heading_rad=heading,
        cue_xy_mm=CUE_XY,
        cue_height_mm=CUE_HEIGHT,
        cue_radius_mm=CUE_RADIUS,
        cue_present=present,
        t_s=t_s,
    )


# ---------------------------------------------------------------------------
# The shot plan cuts on the run's own events
# ---------------------------------------------------------------------------


def test_the_first_cut_lands_on_the_moment_the_fly_started_walking() -> None:
    plan = ShotPlan.from_recording(duration_s=20.0, onset_s=2.1)
    assert plan.establish_until_s == pytest.approx(2.1)
    assert plan.shot_at(2.05) == "establish"
    assert plan.shot_at(2.15) == "profile"


def test_the_leg_shot_happens_while_the_fly_is_still_walking() -> None:
    """In this run the fly closes 14 mm in about eight seconds and then stands.

    A leg shot scheduled late would be a close-up of a stationary animal, which is what
    ordering the shots the obvious way produced.
    """
    plan = ShotPlan.from_recording(duration_s=20.0, onset_s=1.7)
    assert plan.shot_at(3.0) == "profile"
    assert plan.profile_until_s < 8.0


def test_a_variant_that_never_walks_still_gets_a_plan() -> None:
    """Two of the four controls never locomote, and they still have to be watchable."""
    plan = ShotPlan.from_recording(duration_s=20.0, onset_s=None)
    assert plan.shot_at(0.0) == "establish"
    assert plan.shot_at(19.9) == "arrival"


def test_the_shots_run_in_order_and_never_go_backwards() -> None:
    plan = ShotPlan.from_recording(duration_s=20.0, onset_s=2.1)
    seen = [plan.shot_at(t / 10.0) for t in range(200)]
    order = [shot for index, shot in enumerate(seen) if index == 0 or shot != seen[index - 1]]
    assert order == list(SHOT_ORDER)


def test_a_very_late_onset_cannot_eat_the_whole_video() -> None:
    """A fly that starts walking at 18 s must not get an 18 second establishing shot."""
    plan = ShotPlan.from_recording(duration_s=20.0, onset_s=18.0)
    assert plan.establish_until_s == pytest.approx(7.0)


def test_a_zero_duration_recording_is_refused() -> None:
    with pytest.raises(ConfigurationError):
        ShotPlan.from_recording(duration_s=0.0, onset_s=None)


# ---------------------------------------------------------------------------
# The camera keeps the fly as the subject
# ---------------------------------------------------------------------------


def test_the_camera_aims_nearer_the_fly_than_the_cue_once_it_is_following() -> None:
    """The regression. Aiming at the midpoint is what put the cue in the middle of frame."""
    for shot in ("follow", "profile", "arrival"):
        framing = _framing(shot)
        to_fly = math.hypot(framing.lookat_mm[0], framing.lookat_mm[1])
        to_cue = math.hypot(
            framing.lookat_mm[0] - CUE_XY[0], framing.lookat_mm[1] - CUE_XY[1]
        )
        assert to_fly < to_cue, shot


def test_the_shot_does_not_collapse_when_the_fly_arrives() -> None:
    """At the end of a successful run the fly is inside the cue's own radius.

    The old formula went to `1.15 * separation + 2.5 * radius` about a midpoint, so at a
    separation of 1.9 mm it framed a 5 mm sphere from 8 mm and lost the animal. The floor
    below is what stops that, and it has to account for the cue's size and not only for how
    far away its centre is.
    """
    arrived = _framing("arrival", fly=(0.0, 12.1, 1.05))
    assert arrived.distance_mm >= 6.5
    # Far enough back that the sphere is not the whole frame: MuJoCo's default 45 degree
    # vertical field of view spans 0.828 * distance at the aim point.
    assert 0.828 * arrived.distance_mm > 2.0 * CUE_RADIUS


def test_no_shot_lets_the_cue_take_over_the_frame() -> None:
    """The floor that every shot obeys, checked against MuJoCo's actual field of view.

    A successful run ends with the fly nearer the cue's centre than its radius, so without
    this the closing shot is a black ball with legs underneath.
    """
    for shot in SHOT_ORDER:
        for separation in (0.4, 1.1, 2.5, 6.0, 14.0):
            framing = _framing(shot, fly=(0.0, 14.0 - separation, 1.05))
            camera_to_cue = framing.distance_mm + separation
            assert 2.0 * CUE_RADIUS / (0.828 * camera_to_cue) <= 0.46, (shot, separation)


def test_the_cue_floor_overrides_a_shots_own_maximum() -> None:
    """Otherwise a per-shot constant silently wins and the frame fills with cue again."""
    close = _framing("arrival", fly=(0.0, 13.5, 1.05))
    assert close.distance_mm > SHOT_FRAMING["arrival"].distance_max_mm


def test_the_establishing_shot_is_the_only_one_that_frames_the_midpoint() -> None:
    framing = _framing("establish")
    assert framing.lookat_mm[1] == pytest.approx(7.0)
    assert framing.distance_mm > _framing("follow").distance_mm


def test_with_no_cue_the_camera_ignores_where_the_cue_would_have_been() -> None:
    """The stimulus-absent control must not be shot as though something were there."""
    absent = _framing("follow", present=False)
    assert absent.lookat_mm[0] == pytest.approx(0.0)
    assert absent.lookat_mm[1] == pytest.approx(0.0)
    assert absent.distance_mm == pytest.approx(5.5)


def test_the_camera_turns_with_the_body_so_a_turn_reads_as_a_turn() -> None:
    ahead = _framing("follow", heading=0.0)
    turned = _framing("follow", heading=math.radians(90.0))
    assert turned.azimuth_deg - ahead.azimuth_deg == pytest.approx(90.0)


def test_an_unknown_shot_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ConfigurationError):
        _framing("closeup")


def test_a_framing_is_immutable() -> None:
    framing = _framing("follow")
    assert isinstance(framing, CameraFraming)
    with pytest.raises(AttributeError):
        framing.distance_mm = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Smoothing is a display filter and must behave like one
# ---------------------------------------------------------------------------


def test_smoothing_shortens_nothing_and_calms_the_shake() -> None:
    rng = np.random.default_rng(0)
    steps = np.linspace(0.0, 10.0, 200)
    shaken = steps + rng.normal(0.0, 0.3, steps.size)
    x, _, _, _ = smooth_track(shaken, shaken, shaken, np.zeros(200), window=21)
    assert x.size == 200
    assert np.std(np.diff(x)) < np.std(np.diff(shaken))


def test_smoothing_does_not_swing_the_camera_through_half_a_turn_at_the_wrap() -> None:
    """Heading crossing +pi to -pi must not average to zero and spin the shot."""
    heading = np.array([3.10, 3.13, -3.13, -3.10])
    _, _, _, smoothed = smooth_track(
        np.zeros(4), np.zeros(4), np.zeros(4), heading, window=3
    )
    assert np.all(np.abs(smoothed) > 3.0)


def test_a_window_of_one_leaves_the_track_alone() -> None:
    values = np.array([0.0, 5.0, 0.0])
    x, _, _, _ = smooth_track(values, values, values, values, window=1)
    assert x.tolist() == values.tolist()


# ---------------------------------------------------------------------------
# The recorded physics state
# ---------------------------------------------------------------------------


def test_a_missing_pose_recording_is_reported_rather_than_guessed(tmp_path) -> None:
    with pytest.raises(ReadinessError):
        PoseRecording(tmp_path / "poses.npz")


def test_a_pose_recording_whose_arrays_disagree_is_refused(tmp_path) -> None:
    path = tmp_path / "poses.npz"
    np.savez_compressed(
        path, qpos=np.zeros((3, 133)), t_us=np.array([0, 1], dtype=np.int64)
    )
    with pytest.raises(ConfigurationError):
        PoseRecording(path)


def test_a_pose_recording_clamps_rather_than_running_off_the_end(tmp_path) -> None:
    path = tmp_path / "poses.npz"
    qpos = np.arange(9, dtype=np.float64).reshape(3, 3)
    np.savez_compressed(path, qpos=qpos, t_us=np.array([1, 2, 3], dtype=np.int64))
    poses = PoseRecording(path)
    assert len(poses) == 3
    assert poses.at(99).tolist() == [6.0, 7.0, 8.0]
    assert poses.at(-5).tolist() == [0.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# The cue is drawn as what it actually is
# ---------------------------------------------------------------------------


def test_the_cue_is_drawn_translucent_because_it_has_no_collision() -> None:
    """A successful run ends with the fly standing inside the cue.

    The encoder models the cue in the horizontal plane with no height and no collision,
    and saturates its angular radius at a hemisphere once the fly is nearer than the
    radius. Drawing it opaque asserts a solidity that does not exist, and hides the animal
    at the moment the demonstration succeeds.
    """
    from flysim.demo01_body import CUE_RGBA

    assert CUE_RGBA[3] < 1.0


def test_the_scaffolds_say_the_cue_can_be_walked_through() -> None:
    from flysim.demo01_body import SCAFFOLDS

    cue = next(text for text in SCAFFOLDS if text.startswith("The cue"))
    assert "no collision" in cue
    assert "hemisphere" in cue
