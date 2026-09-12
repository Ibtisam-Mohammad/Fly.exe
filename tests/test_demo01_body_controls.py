# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

from flysim.demo01_embodied import CONTROL_VARIANTS, _body_control_command
from flysim.engines.body import COMMAND_FORWARD, COMMAND_YAW


def test_demo01_exposes_graph_free_body_controls() -> None:
    assert "command-replay" in CONTROL_VARIANTS
    assert "controller-only" in CONTROL_VARIANTS


def test_controller_only_is_fixed_and_does_not_read_the_target() -> None:
    still = _body_control_command(
        variant="controller-only", t_us=0, quiescent_us=100, replay=None, step=0
    )
    moving = _body_control_command(
        variant="controller-only", t_us=100, quiescent_us=100, replay=None, step=1
    )
    assert still.value_for(COMMAND_FORWARD) == 0.0
    assert moving.value_for(COMMAND_FORWARD) == 0.5
    assert moving.value_for(COMMAND_YAW) == 0.0
    assert moving.metadata["graph_attached"] is False


def test_command_replay_uses_the_same_recorded_row_without_delay() -> None:
    replay = [{"command": {"forward": 0.25, "yaw": -0.5, "state": "LOCOMOTING"}}]
    command = _body_control_command(
        variant="command-replay", t_us=0, quiescent_us=100, replay=replay, step=0
    )
    assert command.value_for(COMMAND_FORWARD) == 0.25
    assert command.value_for(COMMAND_YAW) == -0.5
    assert command.metadata["graph_attached"] is False
