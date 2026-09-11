# SPDX-License-Identifier: GPL-2.0-or-later
"""One bus, many senses, one frame per coupling interval.

Three properties of the injection API force this shape rather than suggest it.

``TrackAGeNNEngine.push_inputs`` **zeroes every neuron's** ``InputRateHz`` **on every call**
before writing the frame, so senses cannot be pushed one after another -- the second call
would erase the first. Everything enabled has to arrive in a single frame.

``SignalFrame`` **rejects duplicate ids**, so two encoders claiming one body is a hard
failure at the moment of injection, deep inside a run. That is why the channels come from a
partition (:mod:`flysim.sensory_atlas`) and why a binding addresses a
:class:`~flysim.sensory_atlas.ChannelKey` rather than a selector: overlap is unrepresentable
here, not merely checked.

``entry_body_ids`` **is hashed into the GeNN model identity**, so changing the entry set
forces a CUDA rebuild. The bus therefore declares one frozen union once -- every in-graph
sensory body plus the lamina surrogate -- and enabling or disabling a modality is a change of
*rate*, never of membership. That costs one capability, recorded in `ADR-2026-016`: the
entry outgoing gain becomes all-or-nothing across every modality and is committed to 1.0.

**What the bus does not do.** It never sees a pose, a distance or a target. It converts world
quantities into rates and nothing else. The decoder on the other side never sees a
`SensorFrame` at all. That separation is what DEMO-01 bought by deleting its predecessor's
`decode(neural, sensors)` signature, and it is the property most worth not losing.

**A limitation to state rather than discover.** Because one frame carries everything, the
per-channel delay queues can only be drained at a coupling boundary, so sensory delay is
quantised to the coupling interval. A 5 ms antennal conduction delay and a 12 ms leg delay
are indistinguishable at 15 ms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from flysim.contracts import NeuralInputFrame, SensorFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError
from flysim.sensory_atlas import ChannelKey, SensoryAtlas
from flysim.timing import CausalDelayQueue
from flysim.transducers import SaturatingTransducer

BUS_ASSUMPTIONS = ("DEMO-03", "SENS-01", "SENS-05")


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    """One sense, at one organ, on one side, driven by one world quantity."""

    key: ChannelKey
    sensor_id: str
    transducer: SaturatingTransducer
    delay_us: int
    gain: float = 1.0
    enabled: bool = True
    kind: str = "real"
    why: str = ""

    def __post_init__(self) -> None:
        if self.delay_us < 0:
            raise ConfigurationError("A sensory delay cannot be negative")
        if self.gain < 0.0:
            raise ConfigurationError("A channel gain cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": str(self.key),
            "sensor_id": self.sensor_id,
            "transducer": self.transducer.as_dict(),
            "delay_us": self.delay_us,
            "gain": self.gain,
            "enabled": self.enabled,
            "kind": self.kind,
            "why": self.why,
        }


@dataclass
class SensoryBus:
    """Assembles every enabled channel into one causal input frame."""

    atlas: SensoryAtlas
    bindings: tuple[ChannelBinding, ...]
    coupling_us: int
    _index: dict[str, np.ndarray] = field(default_factory=dict, init=False, repr=False)
    _queues: dict[str, CausalDelayQueue[float]] = field(
        default_factory=dict, init=False, repr=False
    )
    _t_us: int = field(default=-1, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.coupling_us <= 0:
            raise ConfigurationError("The coupling interval must be positive")
        union = set(self.atlas.entry_union)
        seen: dict[str, str] = {}
        for binding in self.bindings:
            name = str(binding.key)
            if name in seen:
                raise ConfigurationError(
                    f"Channel {name} is bound twice, by {seen[name]} and by "
                    f"{binding.sensor_id}. One channel, one encoder."
                )
            seen[name] = binding.sensor_id
            bodies = self.atlas.bodies_for(binding.key)
            if not bodies:
                raise ConfigurationError(
                    f"Channel {name} resolves to no bodies, so binding it drives nothing."
                )
            if self.atlas.modality_kind.get(binding.key.modality) == "absent":
                raise ConfigurationError(
                    f"Channel {name} belongs to an absent modality. Absent means no world "
                    "quantity exists to transduce, so it may not be bound."
                )
            missing = [body for body in bodies if body not in union]
            if missing:
                raise ConfigurationError(
                    f"Channel {name} has {len(missing)} bodies outside the frozen entry "
                    "union, so driving it would need a new kernel."
                )
            self._index[name] = np.asarray(bodies, dtype=np.int64)
            self._queues[name] = CausalDelayQueue(binding.delay_us)
            if binding.delay_us % self.coupling_us:
                raise ConfigurationError(
                    f"Channel {name} declares a {binding.delay_us} us delay, which is not "
                    f"a multiple of the {self.coupling_us} us coupling interval. Sensory "
                    "delay is quantised to that interval because one frame carries every "
                    "sense; declare a multiple rather than a value the bus cannot deliver."
                )

    # ------------------------------------------------------------------ encode

    def encode(self, t_us: int, sensors: SensorFrame) -> NeuralInputFrame:
        """Transduce, delay, and merge. The only path from the world into the network."""
        if t_us < 0:
            raise CausalityError("Cannot encode before t=0")
        if t_us <= self._t_us:
            raise CausalityError(
                f"The bus is at {self._t_us} us and was asked to encode {t_us} us again; "
                "a sensory frame may not be produced twice for one interval."
            )
        if sensors.t_us != t_us:
            raise CausalityError(
                f"Sensor frame is stamped {sensors.t_us} us but the bus is encoding "
                f"{t_us} us. The bus never reads a sample from another interval."
            )
        self._t_us = t_us

        rate_by_channel: dict[str, float] = {}
        raw_by_channel: dict[str, float] = {}
        for binding in self.bindings:
            name = str(binding.key)
            queue = self._queues[name]
            queue.push(t_us, sensors.value_for(binding.sensor_id, 0.0))
            ready = queue.pop_ready(t_us)
            # An undelivered channel is silent, not held: nothing has arrived yet.
            quantity = float(ready[-1]) if ready else 0.0
            raw_by_channel[name] = quantity
            if not binding.enabled:
                rate_by_channel[name] = 0.0
                continue
            rate_by_channel[name] = binding.transducer.rate_hz(quantity) * binding.gain

        ids: list[int] = []
        values: list[float] = []
        for binding in self.bindings:
            name = str(binding.key)
            rate = rate_by_channel[name]
            if rate <= 0.0:
                continue
            ids.extend(int(body) for body in self._index[name])
            values.extend([rate] * self._index[name].size)

        active = [name for name, rate in rate_by_channel.items() if rate > 0.0]
        return NeuralInputFrame(
            t_us=t_us,
            ids=tuple(ids),
            values=tuple(values),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="P/E",
            assumption_ids=BUS_ASSUMPTIONS,
            metadata={
                "channel_rate_hz": rate_by_channel,
                "channel_world_quantity": raw_by_channel,
                "channel_kind": {
                    str(b.key): b.kind for b in self.bindings
                },
                "active_channels": sorted(active),
                "silent_channels": sorted(
                    name for name, rate in rate_by_channel.items() if rate <= 0.0
                ),
                # By definition the count of neurons whose refractory period is bypassed
                # this interval. A stimulus-absent control must report zero.
                "entry_bodies_with_nonzero_rate": len(ids),
                "entry_union_bodies": len(self.atlas.entry_union),
                "entry_union_sha256": self.atlas.entry_union_sha256,
                "delay_quantised_to_us": self.coupling_us,
                "the_bus_cannot_see": (
                    "pose, distance, heading, time to target, or any decoder state. It "
                    "converts world quantities to rates and nothing else."
                ),
            },
        )

    # ------------------------------------------------------------------ record

    def describe(self) -> dict[str, Any]:
        return {
            "coupling_us": self.coupling_us,
            "bindings": [binding.as_dict() for binding in self.bindings],
            "entry_union_bodies": len(self.atlas.entry_union),
            "entry_union_sha256": self.atlas.entry_union_sha256,
            "bound_channels": len(self.bindings),
            "bound_bodies": int(sum(a.size for a in self._index.values())),
            "atlas": self.atlas.as_dict(),
            "why_one_frame": (
                "push_inputs zeroes every neuron's InputRateHz before writing, so a second "
                "push would erase the first. Every enabled sense arrives together."
            ),
            "declared_limitations": [
                "Sensory delay is quantised to the coupling interval, so conduction "
                "delays that differ by less than one interval are indistinguishable.",
                "Baseline rate is zero for every channel, so there is no spontaneous "
                "sensory drive. A nonzero baseline would remove the refractory period of "
                "every entry neuron and raise its ceiling from about 455 Hz to 10000 Hz.",
                "Every transducer is a declared saturating curve, not a measured receptor "
                "response.",
                "The entry outgoing gain is committed to 1.0 for every modality, because "
                "the entry set is frozen once to keep the kernel identity stable.",
            ],
        }
