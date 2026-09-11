# SPDX-License-Identifier: GPL-2.0-or-later
"""Three behaviours, three readouts, three decoders that can see nothing but the network.

Separate experiments rather than one state machine. Track A's ``required_sequence`` made
every claim conditional on every other, which is how one failing criterion sank a thirty-run
matrix -- and the honest ceilings here differ by a wide margin. Escape has a monosynaptic
30.6 percent share of DNp01's input. Feeding has no labellum, no pharynx, no ingestion, and
a substituted entry population. Bundling them would let the strongest launder the weakest.

**Every decoder takes one argument.** DEMO-01's predecessor had ``decode(neural, sensors)``
and its behaviour turned out to be the sensor term. The signature is asserted in
`tests/test_sensory_bus.py`, not merely intended.

Two substitutions in feeding are forced by the body and are declared rather than hidden.
`MN9` is the pharyngeal pump, not a proboscis extensor, so decoding it to a rostrum command
would fabricate function rather than magnitude: it is recorded and never decoded. And the
strongest feeding route measured -- labellar bristle to MN9 at 48.6 times a matched null --
cannot be driven at all, because NeuroMechFly has no labellum on which to place a stimulus.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, NeuralOutputFrame, SignalType
from flysim.demo01 import PopulationSpec
from flysim.engines.body import (
    BEHAVIOUR_COMMAND_IDS,
    COMMAND_GROOM,
    COMMAND_JUMP,
    COMMAND_PROBOSCIS,
    COMMAND_WING_DEPRESSION,
)
from flysim.errors import ConfigurationError, DatasetError
from flysim.sensory_atlas import ChannelKey

BEHAVIOURS = ("grooming", "feeding", "escape")

# ---------------------------------------------------------------------------- populations

#: Grooming. Track A declared these six and the survey scored its entry against them at 106
#: times a matched null, the strongest route measured anywhere in this project.
GROOM_READOUT_SPECS = (
    PopulationSpec(
        "groom-dn-left", "DNg62", "L", "somaSide", "antennal grooming descending readout",
        additional_types=("DNge078", "DNg21"),
    ),
    PopulationSpec(
        "groom-dn-right", "DNg62", "R", "somaSide", "antennal grooming descending readout",
        additional_types=("DNge078", "DNg21"),
    ),
)

#: Feeding. The proboscis extensors, which is not where the strongest route goes.
FEED_READOUT_SPECS = (
    PopulationSpec(
        "proboscis-mn", "MN10", None, "somaSide", "proboscis extensor motor neurons",
        additional_types=("MN11D", "MN11V", "MN12D"),
    ),
    PopulationSpec(
        "pump-mn9", "MN9", None, "somaSide",
        "the pharyngeal pump. RECORDED AND NEVER DECODED: there is nothing to pump.",
    ),
)

#: Escape. Two cells, which is below the spike quantum -- but the giant fibre is genuinely
#: all-or-none, so it is decoded as a spike event and paired with a larger companion pool
#: that must move in the same interval.
ESCAPE_READOUT_SPECS = (
    PopulationSpec("giant-fibre-left", "DNp01", "L", "somaSide", "the giant fibre"),
    PopulationSpec("giant-fibre-right", "DNp01", "R", "somaSide", "the giant fibre"),
    PopulationSpec(
        "dn-loom-left", "DNp02", "L", "somaSide", "declared companion loom pool",
        additional_types=("DNp03", "DNp04", "DNp06"),
    ),
    PopulationSpec(
        "dn-loom-right", "DNp02", "R", "somaSide", "declared companion loom pool",
        additional_types=("DNp03", "DNp04", "DNp06"),
    ),
    PopulationSpec("jump-mn-ttmn", "TTMn", None, "somaSide", "the jump muscle motor neuron"),
    PopulationSpec("psi", "PSI", None, "somaSide", "the peripherally synapsing interneuron"),
)

READOUT_SPECS: dict[str, tuple[PopulationSpec, ...]] = {
    "grooming": GROOM_READOUT_SPECS,
    "feeding": FEED_READOUT_SPECS,
    "escape": ESCAPE_READOUT_SPECS,
}

#: What each behaviour actually decodes. Everything else in its readout is recorded.
DECODED: dict[str, tuple[str, ...]] = {
    "grooming": ("groom-dn-left", "groom-dn-right"),
    "feeding": ("proboscis-mn",),
    "escape": ("giant-fibre-left", "giant-fibre-right"),
}

#: Pools recorded every interval for the video and the trace, never decoded.
MONITOR_POOLS: dict[str, dict[str, str]] = {
    "sensory-all": {"column": "superclass", "value": "vnc_sensory"},
    "descending": {"column": "superclass", "value": "descending_neuron"},
    "vnc-motor": {"column": "superclass", "value": "vnc_motor"},
    "vnc-intrinsic": {"column": "superclass", "value": "vnc_intrinsic"},
}


@dataclass(frozen=True, slots=True)
class Demo02Populations:
    """Readout populations resolved by type and side, disjoint from the entry union."""

    annotations_sha256: str
    readout: dict[str, tuple[int, ...]]
    monitors: dict[str, tuple[int, ...]]
    specs: tuple[PopulationSpec, ...]
    excluded_unknown_side: dict[str, int]

    @property
    def readout_body_ids(self) -> tuple[int, ...]:
        seen: set[int] = set()
        for bodies in self.readout.values():
            seen.update(bodies)
        return tuple(sorted(seen))

    @classmethod
    def resolve(
        cls,
        annotations_path: Path,
        graph: SparseConnectome,
        *,
        behaviour: str,
        entry_body_ids: Sequence[int],
        monitor_pools: dict[str, dict[str, str]] | None = None,
    ) -> Demo02Populations:
        import hashlib

        import pyarrow.feather as feather

        specs = READOUT_SPECS[behaviour]
        table = feather.read_table(
            annotations_path, columns=("bodyId", "type", "superclass", "somaSide", "rootSide")
        )
        columns = {name: table.column(name).to_pylist() for name in table.column_names}
        in_graph = {int(body) for body in graph.body_ids}

        readout: dict[str, tuple[int, ...]] = {}
        excluded: dict[str, int] = {}
        for spec in specs:
            found: list[int] = []
            dropped = 0
            for row, body in enumerate(columns["bodyId"]):
                identifier = int(body)
                if identifier not in in_graph:
                    continue
                if not spec.accepts(columns["type"][row]):
                    continue
                if spec.side is not None:
                    side = str(columns[spec.side_column][row] or "")
                    if side not in {"L", "R"}:
                        dropped += 1
                        continue
                    if side != spec.side:
                        continue
                found.append(identifier)
            if not found:
                raise DatasetError(f"Readout population {spec.name} resolves to no bodies")
            readout[spec.name] = tuple(sorted(found))
            excluded[spec.name] = dropped

        monitors: dict[str, tuple[int, ...]] = {}
        for name, query in (monitor_pools or MONITOR_POOLS).items():
            column, value = query["column"], query["value"]
            monitors[name] = tuple(
                sorted(
                    int(body)
                    for row, body in enumerate(columns["bodyId"])
                    if int(body) in in_graph and str(columns[column][row] or "") == value
                )
            )

        entry = set(int(body) for body in entry_body_ids)
        overlap = entry & set().union(*(set(v) for v in readout.values()))
        if overlap:
            raise ConfigurationError(
                f"{len(overlap)} bodies are both driven and read, so the readout would be "
                "reading injected drive rather than network output."
            )
        digest = hashlib.sha256(annotations_path.read_bytes()).hexdigest()
        return cls(
            annotations_sha256=digest,
            readout=readout,
            monitors=monitors,
            specs=specs,
            excluded_unknown_side=excluded,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "annotations_sha256": self.annotations_sha256,
            "readout": {name: list(ids) for name, ids in sorted(self.readout.items())},
            "readout_sizes": {name: len(ids) for name, ids in sorted(self.readout.items())},
            "monitor_sizes": {name: len(ids) for name, ids in sorted(self.monitors.items())},
            "specs": [spec.as_dict() for spec in self.specs],
            "excluded_unknown_side": self.excluded_unknown_side,
        }


# ------------------------------------------------------------------------------- decoders


class BehaviourState(Enum):
    QUIESCENT = "QUIESCENT"
    WATCHING = "WATCHING"
    ACTING = "ACTING"
    SPENT = "SPENT"


@dataclass(frozen=True, slots=True)
class DecoderParameters:
    """Everything a behaviour decoder is allowed to know. Provenance E throughout."""

    quiescent_us: int = 1_500_000
    threshold_hz: float = 1.0
    half_rate_hz: float = 6.0
    initiation_hold_us: int = 150_000
    action_us: int = 3_000_000
    #: Escape only: spikes required in one coupling interval from a two-cell population.
    spike_threshold: int = 1
    #: Escape only: the companion pool must also move, so one stochastic spike cannot
    #: carry the demonstration on its own.
    companion_threshold_hz: float = 0.5
    #: Escape only: microseconds by which wing depression leads the jump. Literature
    #: ordering, not measured here.
    wing_lead_us: int = 0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> DecoderParameters:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        values = cls(**known)
        if values.threshold_hz < 0 or values.half_rate_hz <= 0:
            raise ConfigurationError("Decoder rates must be sensible")
        if values.spike_threshold < 1:
            raise ConfigurationError("A spike threshold below one is not an event")
        return values

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Decoder:
    """Shared timing. Subclasses add the mapping from rate to command."""

    parameters: DecoderParameters
    state: BehaviourState = field(default=BehaviourState.QUIESCENT, init=False)
    _held_us: int = field(default=0, init=False)
    _started_us: int | None = field(default=None, init=False)
    events: list[dict[str, Any]] = field(default_factory=list, init=False)

    def _advance(self, t_us: int, above: bool, coupling_us: int) -> bool:
        """Returns whether the behaviour should be commanded this interval."""
        if (
            self.state is BehaviourState.QUIESCENT
            and t_us >= self.parameters.quiescent_us
        ):
            self.state = BehaviourState.WATCHING
            self.events.append({"t_us": t_us, "state": self.state.value})
        if self.state is BehaviourState.WATCHING:
            self._held_us = self._held_us + coupling_us if above else 0
            if self._held_us >= self.parameters.initiation_hold_us:
                self.state = BehaviourState.ACTING
                self._started_us = t_us
                self.events.append({"t_us": t_us, "state": self.state.value})
        if self.state is BehaviourState.ACTING:
            assert self._started_us is not None
            if t_us - self._started_us >= self.parameters.action_us:
                self.state = BehaviourState.SPENT
                self.events.append({"t_us": t_us, "state": self.state.value})
                return False
            return True
        return False

    def decode(self, neural: NeuralOutputFrame) -> ActuatorCommandFrame:
        """Rate or spikes in, command out. One argument, and it is never a SensorFrame."""
        raise NotImplementedError

    def _frame(self, t_us: int, values: dict[str, float]) -> ActuatorCommandFrame:
        return ActuatorCommandFrame(
            t_us=t_us,
            ids=BEHAVIOUR_COMMAND_IDS,
            values=tuple(values.get(name, 0.0) for name in BEHAVIOUR_COMMAND_IDS),
            units=", ".join("normalized" for _ in BEHAVIOUR_COMMAND_IDS),
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-03", "MOTOR-06", "DEMO-02"),
            metadata={"state": self.state.value, "decoded_from": sorted(values)},
        )


@dataclass
class GroomDecoder(_Decoder):
    """Bilateral, graded, and deliberately not side-specific.

    The wiring will not support a side claim: eleven direct edges in total from the
    grooming subclass to this readout, and the largest bundle runs contralateral. The
    survey scores the route at hop 2 rather than hop 1 for the same reason. So both sides
    are summed, and the contract may not claim the fly grooms the correct antenna.
    """

    coupling_us: int = 15_000

    def decode(self, neural: NeuralOutputFrame) -> ActuatorCommandFrame:
        left = neural.value_for("groom-dn-left", 0.0)
        right = neural.value_for("groom-dn-right", 0.0)
        drive = 0.5 * (left + right)
        acting = self._advance(neural.t_us, drive >= self.parameters.threshold_hz,
                               self.coupling_us)
        intensity = (
            drive / (drive + self.parameters.half_rate_hz) if acting and drive > 0 else 0.0
        )
        return self._frame(neural.t_us, {COMMAND_GROOM: intensity} if acting else {})


@dataclass
class ProboscisDecoder(_Decoder):
    """Graded extension from the proboscis motor neurons. MN9 is never read here."""

    coupling_us: int = 15_000

    def decode(self, neural: NeuralOutputFrame) -> ActuatorCommandFrame:
        drive = neural.value_for("proboscis-mn", 0.0)
        acting = self._advance(neural.t_us, drive >= self.parameters.threshold_hz,
                               self.coupling_us)
        extension = (
            drive / (drive + self.parameters.half_rate_hz) if acting and drive > 0 else 0.0
        )
        return self._frame(neural.t_us, {COMMAND_PROBOSCIS: extension} if acting else {})


@dataclass
class EscapeDecoder(_Decoder):
    """A spike event, not a rate, because the giant fibre is genuinely all-or-none.

    Two cells cannot average away the spike quantum at a 15 ms interval, so a filtered
    rate from DNp01 would be one spike rendered as 33 Hz. The honest decode is a count in
    a window, paired with a declared companion pool of eight cells that must move in the
    same interval: one stochastic spike must not be able to launch the fly.
    """

    coupling_us: int = 15_000

    def decode(self, neural: NeuralOutputFrame) -> ActuatorCommandFrame:
        counts = neural.metadata.get("raw_population_spike_counts", {})
        spikes = int(counts.get("giant-fibre-left", 0)) + int(
            counts.get("giant-fibre-right", 0)
        )
        companion = 0.5 * (
            neural.value_for("dn-loom-left", 0.0) + neural.value_for("dn-loom-right", 0.0)
        )
        fired = (
            spikes >= self.parameters.spike_threshold
            and companion >= self.parameters.companion_threshold_hz
        )
        acting = self._advance(neural.t_us, fired, self.coupling_us)
        if not acting:
            return self._frame(neural.t_us, {})
        elapsed = neural.t_us - (self._started_us or neural.t_us)
        wings = 1.0 if elapsed >= -self.parameters.wing_lead_us else 0.0
        return self._frame(
            neural.t_us, {COMMAND_JUMP: 1.0, COMMAND_WING_DEPRESSION: wings}
        )


DECODERS = {
    "grooming": GroomDecoder,
    "feeding": ProboscisDecoder,
    "escape": EscapeDecoder,
}


# --------------------------------------------------------------------------------- entry


def entry_channels(behaviour: str) -> tuple[ChannelKey, ...]:
    """Which sensory channels each behaviour drives. Declared, and measured first.

    Grooming and feeding enter at the sense itself. Escape enters at the lamina surrogate
    instead of at LC4, because ADR-2026-014 already rejected skipping the optic lobe, and
    because the lamina is the only sensory entry in this project that has passed a causal
    contract.
    """
    if behaviour == "grooming":
        return (
            ChannelKey("antennal-jo-f-grooming", "antenna", "L"),
            ChannelKey("antennal-jo-f-grooming", "antenna", "R"),
        )
    if behaviour == "feeding":
        # All four legs the release puts taste bristles on. They are not evenly spread:
        # MetaLN carries 62 and ProLN 8, and there are none on the middle legs at all, so
        # a front-leg-only entry would drive 8 of the 70 bodies the sense has.
        return (
            ChannelKey("tarsal-taste", "leg-front", "L"),
            ChannelKey("tarsal-taste", "leg-front", "R"),
            ChannelKey("tarsal-taste", "leg-hind", "L"),
            ChannelKey("tarsal-taste", "leg-hind", "R"),
        )
    if behaviour == "escape":
        return ()
    raise ConfigurationError(f"Unknown behaviour: {behaviour}")


def selectivity_index(left: float, right: float) -> float:
    total = left + right
    return 0.0 if total <= 0 else (left - right) / total


def summarise_outcome(
    behaviour: str,
    *,
    trace: Sequence[dict[str, Any]],
    takeoff: dict[str, Any],
    displacement_mm: float,
) -> dict[str, Any]:
    """The quantities the acceptance contracts score, computed from the recording only."""
    acting = [row for row in trace if row.get("command", {}).get("state") == "ACTING"]
    peak = 0.0
    for row in trace:
        for name, value in row.get("readout_hz", {}).items():
            if name in DECODED[behaviour]:
                peak = max(peak, float(value))
    raw_spikes = sum(
        int(count)
        for row in trace
        for name, count in row.get("readout_raw_counts", {}).items()
        if name in DECODED[behaviour]
    )
    return {
        "intervals": len(trace),
        "acting_intervals": len(acting),
        "reached_acting": bool(acting),
        "peak_decoded_readout_hz": peak,
        "raw_decoded_spikes": raw_spikes,
        "displacement_mm": displacement_mm,
        "onset_us": acting[0]["t_us"] if acting else None,
        "takeoff": takeoff,
        "peak_achieved_proboscis_rad": max(
            (float(row.get("body", {}).get("proboscis_rad", 0.0)) for row in trace),
            default=0.0,
        ),
        "peak_groom_excursion_rad": max(
            (float(row.get("body", {}).get("groom_excursion_rad", 0.0)) for row in trace),
            default=0.0,
        ),
        "min_tarsus_arista_mm": min(
            (
                float(row.get("body", {}).get("tarsus_arista_mm", math.inf))
                for row in trace
            ),
            default=math.inf,
        ),
    }


def population_rate(
    counts: dict[str, int], bodies: int, window_us: int
) -> float:
    if bodies <= 0 or window_us <= 0:
        return 0.0
    total = float(sum(counts.values()))
    return total / bodies / (window_us / 1_000_000.0)


def as_float_array(values: Sequence[float]) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)
