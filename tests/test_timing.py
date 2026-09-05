# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from flysim.errors import ConfigurationError
from flysim.timing import CausalDelayQueue


def test_delay_queue_never_releases_future_state() -> None:
    queue: CausalDelayQueue[str] = CausalDelayQueue(delay_us=2_000)
    assert queue.push(10_000, "sensor-frame") == 12_000
    assert queue.pop_ready(11_999) == ()
    assert queue.pop_ready(12_000) == ("sensor-frame",)


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        CausalDelayQueue[object](-1)
