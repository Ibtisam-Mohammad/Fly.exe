# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit causal delay queues for backend-neutral scheduler boundaries."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import TypeVar

from flysim.errors import CausalityError, ConfigurationError

FrameT = TypeVar("FrameT")


@dataclass(order=True, slots=True)
class _QueuedFrame[FrameT]:
    available_t_us: int
    sequence: int
    frame: FrameT = field(compare=False)


class CausalDelayQueue[FrameT]:
    def __init__(self, delay_us: int) -> None:
        if delay_us < 0:
            raise ConfigurationError("A causal delay cannot be negative")
        self.delay_us = delay_us
        self._sequence = 0
        self._items: list[_QueuedFrame[FrameT]] = []

    def push(self, source_t_us: int, frame: FrameT) -> int:
        if source_t_us < 0:
            raise CausalityError("A delayed frame cannot originate before t=0")
        available = source_t_us + self.delay_us
        heapq.heappush(self._items, _QueuedFrame(available, self._sequence, frame))
        self._sequence += 1
        return available

    def pop_ready(self, t_us: int) -> tuple[FrameT, ...]:
        ready: list[FrameT] = []
        while self._items and self._items[0].available_t_us <= t_us:
            ready.append(heapq.heappop(self._items).frame)
        return tuple(ready)

    def checkpoint(self) -> dict[str, object]:
        return {
            "delay_us": self.delay_us,
            "pending": len(self._items),
            "next_available_t_us": self._items[0].available_t_us if self._items else None,
        }
