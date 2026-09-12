# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

from flysim.demo02_embodied import _controller_only_values
from flysim.engines.body import (
    COMMAND_GROOM,
    COMMAND_JUMP,
    COMMAND_PROBOSCIS,
    COMMAND_WING_DEPRESSION,
)


def test_controller_only_commands_are_behaviour_specific() -> None:
    silent = _controller_only_values("grooming", False)
    assert all(value == 0.0 for value in silent.values())

    groom = _controller_only_values("grooming", True)
    feed = _controller_only_values("feeding", True)
    escape = _controller_only_values("escape", True)
    assert groom[COMMAND_GROOM] == 1.0 and sum(groom.values()) == 1.0
    assert feed[COMMAND_PROBOSCIS] == 1.0 and sum(feed.values()) == 1.0
    assert escape[COMMAND_JUMP] == 1.0
    assert escape[COMMAND_WING_DEPRESSION] == 1.0
    assert sum(escape.values()) == 2.0
