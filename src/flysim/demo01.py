# SPDX-License-Identifier: GPL-2.0-or-later
"""DEMO-01: full-graph closed-loop embodiment with no sensor-to-motor bypass.

The predecessor demonstration (`eon-malecns-v0.2`) reached its behaviour through two
engineered shortcuts that this module exists to remove. Both were declared scaffolds
rather than hidden, but together they meant the body's trajectory did not depend on the
simulated brain, which an audit of the recorded control traces measured directly:

* the controller added ``odor_gradient_yaw_gain_rad_s * (odor_left - odor_right)``
  straight into the yaw command, so steering correlated with the raw odour gradient at
  +0.975 and with the descending readout at only +0.132;
* the encoder injected an odour-proportional firing rate directly into ``oDN1``, the
  neuron whose rate became the forward drive, so forward drive was a re-read of the
  stimulus.

With every synaptic weight set to zero the predecessor still walked 100.2 mm and still
steered, at +0.994 correlation with the odour gradient. That is the defect this module
closes.

Here the only route from world to body is::

    odour field -> declared ORN populations -> full MaleCNS runtime
                -> declared descending populations -> E-provenance decoder -> MuJoCo

Nothing in the controller reads a sensor. There is no gain to set to zero, because there
is no term: `ApproachController` is constructed without access to the sensor frame's
odour channels at all.

Two further departures from the predecessor. Entry is at **real olfactory receptor
neurons** rather than at projection neurons: the released annotation table carries 53
``ORN_*`` types over 2,635 bodies, all present in the executed graph with a median
out-degree of 85, and laterality comes from the released ``rootSide`` column. So the
antennal-lobe relay is no longer bypassed. And the readout is a causal exponential
filter over the raw spike counts, because at a 15 ms coupling interval one spike is
66.7 Hz and the predecessor's decoder was reading a 0-to-2 spike counter.

Every parameter here is P/E or E. Nothing in this module is validated physiology, and
the operating point is engineering calibration searched against neural criteria only --
never against whether the fly reached the target.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from flysim.connectome import SparseConnectome
from flysim.contracts import (
    ActuatorCommandFrame,
    NeuralInputFrame,
    NeuralOutputFrame,
    SensorFrame,
    SignalType,
)
from flysim.engines.body import COMMAND_IDS
from flysim.errors import ConfigurationError, DatasetError

# Annotation columns used to declare a population. Laterality for sensory afferents comes
# from rootSide, because ORN somata sit outside the CNS and carry no somaSide.
SIDE_COLUMNS = ("somaSide", "rootSide")

# Released retinotopic column coordinates. Present for optic-lobe neurons only, and read
# verbatim: nothing here recomputes or interpolates a column assignment.
HEX_COLUMNS = ("assignedOlHex1", "assignedOlHex2")


@dataclass(frozen=True, slots=True)
class PopulationSpec:
    """One anatomically declared population: a type, a side, and where the side came from.

    ``match_column`` names the annotation column the type is matched against. It defaults
    to ``type`` so a bare cell type keeps working, and becomes ``superclass`` or ``class``
    when a whole anatomical class is declared -- every descending neuron on one side, say.
    ``additional_types`` accepts further values in the same column, which is how a
    functional group of separately named cell types becomes one declared population
    without inventing a name the annotation table does not carry.
    """

    name: str
    cell_type: str
    side: str | None
    side_column: str
    role: str
    match_column: str = "type"
    additional_types: tuple[str, ...] = ()
    # When set, the column value is accepted if it begins with any of these prefixes.
    # The released type names carry an anatomical naming convention -- DNp for posterior
    # descending, DNa for anterior, and so on -- so a prefix declares a real anatomical
    # group without enumerating every member type by hand.
    type_prefixes: tuple[str, ...] = ()

    @property
    def accepted_types(self) -> tuple[str, ...]:
        return (self.cell_type, *self.additional_types)

    def accepts(self, value: object) -> bool:
        if value is None:
            return False
        text = str(value)
        if self.type_prefixes:
            return text.startswith(self.type_prefixes)
        return text in self.accepted_types

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cell_type": self.cell_type,
            "accepted_types": list(self.accepted_types),
            "type_prefixes": list(self.type_prefixes),
            "match_column": self.match_column,
            "side": self.side,
            "side_column": self.side_column,
            "role": self.role,
        }


# The declared entry populations. Ethyl acetate is the registered odorant; Or42b and
# Or59b project to glomeruli DM1 and DM4, so the receptor neurons of those glomeruli are
# the anatomically correct entry point for it. This is a choice of WHERE to inject, which
# is declared; it is not a claim that the injected rate is a measured ORN response.
ENTRY_SPECS: tuple[PopulationSpec, ...] = (
    PopulationSpec("orn-dm1-left", "ORN_DM1", "L", "rootSide", "ethyl-acetate receptor entry"),
    PopulationSpec("orn-dm1-right", "ORN_DM1", "R", "rootSide", "ethyl-acetate receptor entry"),
    PopulationSpec("orn-dm4-left", "ORN_DM4", "L", "rootSide", "ethyl-acetate receptor entry"),
    PopulationSpec("orn-dm4-right", "ORN_DM4", "R", "rootSide", "ethyl-acetate receptor entry"),
)

# The declared readout populations. DNa01 and DNa02 are the best-established steering
# descending neurons and each is a single bilateral pair, which is why the causal filter
# matters: two bodies per side cannot average away the spike-count quantum.
READOUT_SPECS: tuple[PopulationSpec, ...] = (
    PopulationSpec("dn-steering-left", "DNa01", "L", "somaSide", "steering descending"),
    PopulationSpec("dn-steering-left-b", "DNa02", "L", "somaSide", "steering descending"),
    PopulationSpec("dn-steering-right", "DNa01", "R", "somaSide", "steering descending"),
    PopulationSpec("dn-steering-right-b", "DNa02", "R", "somaSide", "steering descending"),
)

LEFT_READOUTS = ("dn-steering-left", "dn-steering-left-b")
RIGHT_READOUTS = ("dn-steering-right", "dn-steering-right-b")

# Whole-class pools recorded as binned activity rather than per-neuron traces.
MONITOR_POOLS: dict[str, dict[str, str]] = {
    "orn-all": {"column": "class", "value": "olfactory"},
    "alpn-all": {"column": "class", "value": "ALPN"},
    "alln-all": {"column": "class", "value": "ALLN"},
    "descending-all": {"column": "superclass", "value": "descending_neuron"},
    "vnc-motor-all": {"column": "superclass", "value": "vnc_motor"},
}


@dataclass(frozen=True, slots=True)
class Demo01Populations:
    """Body IDs for every declared population, resolved against the executed graph."""

    annotations_sha256: str
    entry: dict[str, tuple[int, ...]]
    readout: dict[str, tuple[int, ...]]
    monitors: dict[str, tuple[int, ...]]
    specs: tuple[PopulationSpec, ...]
    excluded_unknown_side: dict[str, int]
    # Retinotopic column coordinates for entry bodies that carry them, taken verbatim
    # from the released assignedOlHex1/assignedOlHex2 annotation columns. Empty for
    # routes whose entry layer carries no column assignment.
    entry_hex: dict[int, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        annotations_path: Path,
        graph: SparseConnectome,
        *,
        entry_specs: tuple[PopulationSpec, ...] | None = None,
        readout_specs: tuple[PopulationSpec, ...] | None = None,
        monitor_pools: dict[str, dict[str, str]] | None = None,
        require_hex: bool = False,
    ) -> Demo01Populations:
        import pyarrow.feather as feather

        entry_specs = ENTRY_SPECS if entry_specs is None else entry_specs
        readout_specs = READOUT_SPECS if readout_specs is None else readout_specs
        monitor_pools = MONITOR_POOLS if monitor_pools is None else monitor_pools
        if not annotations_path.is_file():
            raise DatasetError(f"Annotation table is missing: {annotations_path}")
        digest = hashlib.sha256(annotations_path.read_bytes()).hexdigest()
        table = feather.read_table(annotations_path)
        needed = {"bodyId", "type", "class", "superclass", *SIDE_COLUMNS}
        if require_hex:
            needed |= set(HEX_COLUMNS)
        missing = sorted(needed - set(table.column_names))
        if missing:
            raise DatasetError(f"Annotation table lacks columns {missing}")
        columns = {name: table.column(name).to_pylist() for name in needed}
        in_graph = {int(value) for value in graph.body_ids}

        def resolve_spec(spec: PopulationSpec) -> tuple[tuple[int, ...], int]:
            bodies: list[int] = []
            unknown = 0
            sides = columns[spec.side_column]
            for index, value in enumerate(columns[spec.match_column]):
                if not spec.accepts(value):
                    continue
                body_id = int(columns["bodyId"][index])
                if body_id not in in_graph:
                    continue
                if spec.side is None or sides[index] == spec.side:
                    bodies.append(body_id)
                elif sides[index] not in ("L", "R"):
                    unknown += 1
            return tuple(sorted(bodies)), unknown

        entry: dict[str, tuple[int, ...]] = {}
        readout: dict[str, tuple[int, ...]] = {}
        excluded: dict[str, int] = {}
        entry_names = {spec.name for spec in entry_specs}
        for spec in (*entry_specs, *readout_specs):
            bodies, unknown = resolve_spec(spec)
            if not bodies:
                raise DatasetError(
                    f"Declared population {spec.name} ({spec.cell_type} "
                    f"{spec.side_column}={spec.side}) resolved to no body in the graph"
                )
            (entry if spec.name in entry_names else readout)[spec.name] = bodies
            if unknown:
                excluded[spec.cell_type] = unknown

        entry_hex: dict[int, tuple[float, float]] = {}
        if require_hex:
            wanted = {body for bodies in entry.values() for body in bodies}
            hex1, hex2 = columns[HEX_COLUMNS[0]], columns[HEX_COLUMNS[1]]
            for index, body in enumerate(columns["bodyId"]):
                body_id = int(body)
                if body_id not in wanted:
                    continue
                if hex1[index] is None or hex2[index] is None:
                    continue
                entry_hex[body_id] = (float(hex1[index]), float(hex2[index]))
            if not entry_hex:
                raise DatasetError(
                    "A retinotopic route needs released column coordinates, but no entry "
                    "body carries assignedOlHex1/assignedOlHex2"
                )

        monitors: dict[str, tuple[int, ...]] = {}
        for name, rule in monitor_pools.items():
            values = columns[rule["column"]]
            bodies = tuple(
                sorted(
                    int(columns["bodyId"][index])
                    for index, value in enumerate(values)
                    if value == rule["value"] and int(columns["bodyId"][index]) in in_graph
                )
            )
            if not bodies:
                raise DatasetError(f"Monitor pool {name} resolved to no body in the graph")
            monitors[name] = bodies

        # An entry body that is also a readout body would make the readout a re-read of
        # the injected rate, which is exactly the defect this module removes.
        overlap = set().union(*entry.values()) & set().union(*readout.values())
        if overlap:
            raise ConfigurationError(
                f"Entry and readout populations overlap at {sorted(overlap)}; the readout "
                "would be reading injected drive rather than network output"
            )
        return cls(
            annotations_sha256=digest,
            entry=entry,
            readout=readout,
            monitors=monitors,
            specs=(*entry_specs, *readout_specs),
            excluded_unknown_side=excluded,
            entry_hex=entry_hex,
        )

    @property
    def entry_body_ids(self) -> tuple[int, ...]:
        return tuple(sorted({body for bodies in self.entry.values() for body in bodies}))

    @property
    def readout_body_ids(self) -> tuple[int, ...]:
        return tuple(sorted({body for bodies in self.readout.values() for body in bodies}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "annotations_sha256": self.annotations_sha256,
            "specs": [spec.as_dict() for spec in self.specs],
            "entry_sizes": {name: len(bodies) for name, bodies in self.entry.items()},
            "readout_sizes": {name: len(bodies) for name, bodies in self.readout.items()},
            "monitor_sizes": {name: len(bodies) for name, bodies in self.monitors.items()},
            "entry_body_ids": list(self.entry_body_ids),
            "readout_body_ids": list(self.readout_body_ids),
            "entry_populations": {
                name: list(bodies) for name, bodies in self.entry.items()
            },
            "readout_populations": {
                name: list(bodies) for name, bodies in self.readout.items()
            },
            "excluded_unknown_side": dict(self.excluded_unknown_side),
            "entry_bodies_with_column_coordinates": len(self.entry_hex),
            "laterality_source": (
                "released annotation columns only: somaSide for central neurons, rootSide "
                "for olfactory afferents whose somata lie outside the CNS"
            ),
        }


@dataclass(frozen=True, slots=True)
class OrnEncodingParameters:
    """World-to-ORN transduction. P/E: a declared shape, not a measured response."""

    orn_max_rate_hz: float
    orn_baseline_rate_hz: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> OrnEncodingParameters:
        values = cls(
            orn_max_rate_hz=float(raw["orn_max_rate_hz"]),
            orn_baseline_rate_hz=float(raw["orn_baseline_rate_hz"]),
        )
        if values.orn_max_rate_hz <= 0.0:
            raise ConfigurationError("ORN maximum rate must be positive")
        if values.orn_baseline_rate_hz < 0.0:
            raise ConfigurationError("ORN baseline rate cannot be negative")
        if values.orn_baseline_rate_hz >= values.orn_max_rate_hz:
            raise ConfigurationError("ORN baseline must sit below the maximum rate")
        return values


class OrnSensoryEncoder:
    """World odour to declared ORN firing rates. The only input path in DEMO-01.

    Nothing else is injected. There is no forward-intent drive, no projection-neuron
    relay and no sucrose or contamination channel: the approach behaviour has to be
    produced by the graph from this input alone.
    """

    SENSOR_LEFT = "sensory:ethyl-acetate:left"
    SENSOR_RIGHT = "sensory:ethyl-acetate:right"

    def __init__(
        self,
        populations: Demo01Populations,
        parameters: OrnEncodingParameters,
        *,
        stimulus_present: bool = True,
    ) -> None:
        self.populations = populations
        self.parameters = parameters
        self.stimulus_present = stimulus_present

    def _rate(self, value: float) -> float:
        clamped = min(1.0, max(0.0, value))
        span = self.parameters.orn_max_rate_hz - self.parameters.orn_baseline_rate_hz
        return self.parameters.orn_baseline_rate_hz + clamped * span

    def encode(self, frame: NeuralInputFrame) -> NeuralInputFrame:
        left = frame.value_for(self.SENSOR_LEFT, 0.0)
        right = frame.value_for(self.SENSOR_RIGHT, 0.0)
        if not self.stimulus_present:
            # The stimulus-absent control. Baseline drive is retained so that the control
            # differs from the exact run only in the cue, not in whether ORNs are driven
            # at all.
            left = right = 0.0
        rates: dict[int, float] = {}
        for name, bodies in self.populations.entry.items():
            rate = self._rate(left if name.endswith("left") else right)
            for body_id in bodies:
                rates[body_id] = rate
        ids = tuple(sorted(rates))
        return NeuralInputFrame(
            t_us=frame.t_us,
            ids=ids,
            values=tuple(rates[body_id] for body_id in ids),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="P/E",
            assumption_ids=("DATA-03", "SENS-03", "DEMO-02"),
            metadata={
                "entry_layer": "olfactory receptor neurons",
                "antennal_lobe_bypassed": False,
                "stimulus_present": self.stimulus_present,
                "odour_left": left,
                "odour_right": right,
                "declared_populations": {
                    name: len(bodies) for name, bodies in self.populations.entry.items()
                },
                "annotations_sha256": self.populations.annotations_sha256,
            },
        )


@dataclass(frozen=True, slots=True)
class ReadoutParameters:
    """Causal exponential filter over declared descending populations. E provenance."""

    filter_tau_ms: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> ReadoutParameters:
        values = cls(filter_tau_ms=float(raw["readout_filter_tau_ms"]))
        if values.filter_tau_ms <= 0.0:
            raise ConfigurationError("Readout filter time constant must be positive")
        return values


@dataclass
class FilteredDescendingReadout:
    """Population spike counts, causally filtered into a rate, raw counts retained.

    The filter is a one-pole exponential over the instantaneous population rate::

        r <- r * a + (spikes / bodies / window_s) * (1 - a),   a = exp(-window / tau)

    It uses only the present and past, so it introduces no acausal smoothing. The raw
    integer counts travel in the frame metadata unchanged, because the filtered value is
    a derived convenience and the counts are the measurement.
    """

    populations: Demo01Populations
    parameters: ReadoutParameters
    ablated_population_ids: frozenset[str] = frozenset()
    _state: dict[str, float] = field(default_factory=dict)

    def reset(self) -> None:
        self._state.clear()

    def read(self, frame: NeuralOutputFrame) -> NeuralOutputFrame:
        window_us = int(frame.metadata.get("window_us", 0))
        if window_us <= 0:
            raise ConfigurationError("Filtered readout needs the engine's window_us")
        counts_raw = frame.metadata.get("spike_counts")
        if not isinstance(counts_raw, dict):
            raise ConfigurationError(
                "Filtered readout needs raw spike_counts from the engine; the engine must "
                "report integer counts beside the quantised rate"
            )
        window_s = window_us / 1_000_000.0
        decay = math.exp(-window_us / (self.parameters.filter_tau_ms * 1000.0))
        names = tuple(self.populations.readout)
        filtered: list[float] = []
        raw_rates: dict[str, float] = {}
        raw_counts: dict[str, int] = {}
        for name in names:
            bodies = self.populations.readout[name]
            spikes = sum(int(counts_raw[body_id]) for body_id in bodies)
            instantaneous = spikes / len(bodies) / window_s
            previous = self._state.get(name, 0.0)
            value = previous * decay + instantaneous * (1.0 - decay)
            self._state[name] = value
            raw_counts[name] = spikes
            raw_rates[name] = instantaneous
            filtered.append(0.0 if name in self.ablated_population_ids else value)
        return NeuralOutputFrame(
            t_us=frame.t_us,
            ids=names,
            values=tuple(filtered),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="M/P/E",
            assumption_ids=("DATA-03", "ND-01", "ND-03", "ND-04", "DEMO-02"),
            metadata={
                **frame.metadata,
                "filter": "causal one-pole exponential over population mean rate",
                "filter_tau_ms": self.parameters.filter_tau_ms,
                "filter_decay_per_interval": decay,
                "raw_population_spike_counts": raw_counts,
                "raw_population_rate_hz": raw_rates,
                "ablated_population_ids": sorted(self.ablated_population_ids),
                "population_members": {
                    name: list(self.populations.readout[name]) for name in names
                },
            },
        )


class ApproachState(StrEnum):
    QUIESCENT = "QUIESCENT"
    CUE_PRESENT = "CUE_PRESENT"
    LOCOMOTING = "LOCOMOTING"
    ARRIVED = "ARRIVED"


@dataclass(frozen=True, slots=True)
class ApproachParameters:
    """The E-provenance neural-to-locomotor decoder. Tuned only after the network is frozen."""

    quiescent_us: int
    forward_half_rate_hz: float
    forward_threshold_hz: float
    yaw_gain_per_hz: float
    max_yaw_rad_s: float
    arrival_radius_mm: float
    initiation_hold_us: int

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> ApproachParameters:
        values = cls(
            quiescent_us=int(raw["quiescent_us"]),
            forward_half_rate_hz=float(raw["forward_half_rate_hz"]),
            forward_threshold_hz=float(raw["forward_threshold_hz"]),
            yaw_gain_per_hz=float(raw["yaw_gain_per_hz"]),
            max_yaw_rad_s=float(raw["max_yaw_rad_s"]),
            arrival_radius_mm=float(raw["arrival_radius_mm"]),
            initiation_hold_us=int(raw["initiation_hold_us"]),
        )
        if values.quiescent_us < 0:
            raise ConfigurationError("Quiescent period cannot be negative")
        if values.forward_half_rate_hz <= 0.0 or values.max_yaw_rad_s <= 0.0:
            raise ConfigurationError("Decoder scales must be positive")
        if values.arrival_radius_mm <= 0.0:
            raise ConfigurationError("Arrival radius must be positive")
        return values


@dataclass(frozen=True, slots=True)
class ApproachEvent:
    t_us: int
    from_state: ApproachState
    to_state: ApproachState
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_us": self.t_us,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
        }


class ApproachController:
    """Decode descending population rates into forward and yaw drive. Nothing else.

    The predecessor's ``decode`` took the sensor frame and added an odour-gradient term
    to yaw. This one takes the sensor frame only to test the arrival radius and to record
    it in the trace; the returned command is a pure function of the neural readout. There
    is no gain that could re-enable a sensory shortcut because there is no such term.
    """

    def __init__(self, parameters: ApproachParameters) -> None:
        self.parameters = parameters
        self.state = ApproachState.QUIESCENT
        self.entered_state_us = 0
        self.events: list[ApproachEvent] = []
        self._above_threshold_since_us: int | None = None

    def _transition(self, t_us: int, to_state: ApproachState, reason: str) -> None:
        self.events.append(
            ApproachEvent(t_us=t_us, from_state=self.state, to_state=to_state, reason=reason)
        )
        self.state = to_state
        self.entered_state_us = t_us

    @staticmethod
    def _mean(frame: NeuralOutputFrame, names: Sequence[str]) -> float:
        return sum(frame.value_for(name) for name in names) / len(names)

    def decode(
        self, neural: NeuralOutputFrame, sensors: SensorFrame
    ) -> ActuatorCommandFrame:
        t_us = neural.t_us
        left = self._mean(neural, LEFT_READOUTS)
        right = self._mean(neural, RIGHT_READOUTS)
        drive = 0.5 * (left + right)

        # Distance is used for the arrival test and for the trace. It never enters the
        # command.
        target_distance_mm = float(sensors.metadata.get("target_distance_mm", float("nan")))

        if self.state is ApproachState.QUIESCENT:
            if t_us >= self.parameters.quiescent_us:
                self._transition(t_us, ApproachState.CUE_PRESENT, "quiescent-period-elapsed")
        elif self.state is ApproachState.CUE_PRESENT:
            if drive >= self.parameters.forward_threshold_hz:
                if self._above_threshold_since_us is None:
                    self._above_threshold_since_us = t_us
                elif t_us - self._above_threshold_since_us >= self.parameters.initiation_hold_us:
                    self._transition(
                        t_us, ApproachState.LOCOMOTING, "descending-drive-above-threshold"
                    )
            else:
                self._above_threshold_since_us = None
        elif self.state is ApproachState.LOCOMOTING and (
            math.isfinite(target_distance_mm)
            and target_distance_mm <= self.parameters.arrival_radius_mm
        ):
            self._transition(t_us, ApproachState.ARRIVED, "within-arrival-radius")

        forward = 0.0
        yaw = 0.0
        if self.state in (ApproachState.CUE_PRESENT, ApproachState.LOCOMOTING):
            forward = drive / (drive + self.parameters.forward_half_rate_hz)
            raw_yaw = self.parameters.yaw_gain_per_hz * (left - right)
            yaw = min(1.0, max(-1.0, raw_yaw / self.parameters.max_yaw_rad_s))
        return ActuatorCommandFrame(
            t_us=t_us,
            ids=COMMAND_IDS,
            values=(forward, yaw, 0.0, 0.0),
            units="normalized-drive [0,1], normalized-drive [-1,1], normalized, normalized",
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-06",),
            metadata={
                "controller_state": self.state.value,
                "vnc_bypass": True,
                "sensor_terms_in_command": [],
                "decoder_inputs": {
                    "descending_left_hz": left,
                    "descending_right_hz": right,
                    "descending_drive_hz": drive,
                },
                "target_distance_mm": target_distance_mm,
            },
        )


# --------------------------------------------------------------------------------------
# Operating-point criteria. Neural only, by construction: none of these functions can
# see the body, the trajectory or the distance to the target.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OperatingPointCriteria:
    """Thresholds a candidate P/E operating point must satisfy on neural grounds alone."""

    baseline_max_hz: float
    saturation_max_fraction: float
    min_cue_response_hz: float
    min_selectivity_index: float
    max_recovery_fraction: float
    min_active_fraction: float
    max_active_fraction: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> OperatingPointCriteria:
        return cls(
            baseline_max_hz=float(raw["baseline_max_hz"]),
            saturation_max_fraction=float(raw["saturation_max_fraction"]),
            min_cue_response_hz=float(raw["min_cue_response_hz"]),
            min_selectivity_index=float(raw["min_selectivity_index"]),
            max_recovery_fraction=float(raw["max_recovery_fraction"]),
            min_active_fraction=float(raw["min_active_fraction"]),
            max_active_fraction=float(raw["max_active_fraction"]),
        )


def selectivity_index(ipsi_hz: float, contra_hz: float) -> float:
    """Normalised bilateral difference in [-1, 1]; 0 when both sides are equal or silent."""
    total = ipsi_hz + contra_hz
    if total <= 0.0:
        return 0.0
    return (ipsi_hz - contra_hz) / total


def score_operating_point(
    *,
    baseline: dict[str, float],
    cue_left: dict[str, float],
    cue_right: dict[str, float],
    recovery: dict[str, float],
    pool_activity: dict[str, dict[str, float]],
    criteria: OperatingPointCriteria,
) -> dict[str, Any]:
    """Evaluate the four neural criteria. No behavioural quantity is admissible here.

    ``baseline``, ``cue_left``, ``cue_right`` and ``recovery`` map a declared readout
    population name to its mean filtered rate over the corresponding epoch.
    """
    left_names, right_names = LEFT_READOUTS, RIGHT_READOUTS

    def side_mean(epoch: dict[str, float], names: Sequence[str]) -> float:
        return sum(epoch[name] for name in names) / len(names)

    base_drive = 0.5 * (side_mean(baseline, left_names) + side_mean(baseline, right_names))
    left_cue_drive = 0.5 * (
        side_mean(cue_left, left_names) + side_mean(cue_left, right_names)
    )
    right_cue_drive = 0.5 * (
        side_mean(cue_right, left_names) + side_mean(cue_right, right_names)
    )
    recovery_drive = 0.5 * (
        side_mean(recovery, left_names) + side_mean(recovery, right_names)
    )

    # C1 stability: the network must not sit saturated, and a declared fraction of each
    # monitored pool has to be doing something without the whole pool firing.
    descending = pool_activity.get("descending-all", {})
    active_fraction = float(descending.get("active_fraction", 0.0))
    saturated = float(descending.get("mean_rate_hz", 0.0))
    refractory_ceiling_hz = 1000.0 / 2.2
    c1 = (
        base_drive <= criteria.baseline_max_hz
        and saturated <= criteria.saturation_max_fraction * refractory_ceiling_hz
        and criteria.min_active_fraction <= active_fraction <= criteria.max_active_fraction
    )

    # C2 cue responsiveness: the cue must raise descending drive above baseline.
    cue_response = max(left_cue_drive, right_cue_drive) - base_drive
    c2 = cue_response >= criteria.min_cue_response_hz

    # C3 bilateral selectivity that REVERSES with cue side. One-sided selectivity is not
    # enough: a fixed left-right asymmetry would satisfy that and carries no cue
    # information at all.
    left_index = selectivity_index(
        side_mean(cue_left, left_names), side_mean(cue_left, right_names)
    )
    right_index = selectivity_index(
        side_mean(cue_right, left_names), side_mean(cue_right, right_names)
    )
    reverses = left_index > 0.0 > right_index or right_index > 0.0 > left_index
    c3 = reverses and abs(left_index - right_index) >= criteria.min_selectivity_index

    # C4 recovery toward baseline once the cue is removed.
    span = max(left_cue_drive, right_cue_drive) - base_drive
    residual = (recovery_drive - base_drive) / span if span > 0.0 else 1.0
    c4 = residual <= criteria.max_recovery_fraction

    return {
        "baseline_drive_hz": base_drive,
        "cue_left_drive_hz": left_cue_drive,
        "cue_right_drive_hz": right_cue_drive,
        "recovery_drive_hz": recovery_drive,
        "cue_response_hz": cue_response,
        "left_cue_selectivity_index": left_index,
        "right_cue_selectivity_index": right_index,
        "selectivity_reverses_with_cue_side": reverses,
        "selectivity_swing": abs(left_index - right_index),
        "recovery_residual_fraction": residual,
        "descending_active_fraction": active_fraction,
        "descending_mean_rate_hz": saturated,
        "C1_stable_nonsaturated": bool(c1),
        "C2_cue_responsive": bool(c2),
        "C3_bilateral_selectivity_reverses": bool(c3),
        "C4_recovers_to_baseline": bool(c4),
        "all_criteria_met": bool(c1 and c2 and c3 and c4),
        "criteria": {
            "baseline_max_hz": criteria.baseline_max_hz,
            "saturation_max_fraction": criteria.saturation_max_fraction,
            "min_cue_response_hz": criteria.min_cue_response_hz,
            "min_selectivity_index": criteria.min_selectivity_index,
            "max_recovery_fraction": criteria.max_recovery_fraction,
            "active_fraction_window": [
                criteria.min_active_fraction,
                criteria.max_active_fraction,
            ],
        },
        "what_is_deliberately_not_here": (
            "No distance to target, no displacement, no approach success and no body "
            "quantity of any kind. The operating point is chosen on neural grounds so "
            "that the behavioural decoder cannot be compensating for a bad network."
        ),
    }


def bilateral_odour(
    *,
    x_mm: float,
    y_mm: float,
    heading_rad: float,
    source_x_mm: float,
    source_y_mm: float,
    source_strength: float,
    softening_mm2: float,
    half_saturation: float,
    antenna_separation_mm: float,
) -> tuple[float, float]:
    """The registered SENS-03 odour field sampled at two antenna positions.

    Duplicated from the body engines deliberately: the operating-point probe drives the
    network from a scripted pose sequence with no body attached, and must use exactly the
    field the embodied run will use.
    """
    half = antenna_separation_mm / 2.0
    offsets = (
        (x_mm - math.sin(heading_rad) * half, y_mm + math.cos(heading_rad) * half),
        (x_mm + math.sin(heading_rad) * half, y_mm - math.cos(heading_rad) * half),
    )
    out: list[float] = []
    for sample_x, sample_y in offsets:
        distance_sq = (sample_x - source_x_mm) ** 2 + (sample_y - source_y_mm) ** 2
        raw = source_strength / (distance_sq + softening_mm2)
        out.append(raw / (raw + half_saturation))
    return out[0], out[1]


def searched_parameter_grid(raw: dict[str, Any]) -> tuple[dict[str, float], ...]:
    """Expand the registered P/E search grid into candidate operating points."""
    tonic = [float(value) for value in raw["tonic_drive_mv"]]
    contact = [float(value) for value in raw["synaptic_mv_per_contact"]]
    gain = [float(value) for value in raw["central_entry_outgoing_gain"]]
    orn = [float(value) for value in raw["orn_max_rate_hz"]]
    if not (tonic and contact and gain and orn):
        raise ConfigurationError("Every searched axis needs at least one value")
    return tuple(
        {
            "tonic_drive_mv": t,
            "synaptic_mv_per_contact": c,
            "central_entry_outgoing_gain": g,
            "orn_max_rate_hz": o,
        }
        for t in tonic
        for c in contact
        for g in gain
        for o in orn
    )


__all__ = [
    "ENTRY_SPECS",
    "LEFT_READOUTS",
    "MONITOR_POOLS",
    "READOUT_SPECS",
    "RIGHT_READOUTS",
    "ApproachController",
    "ApproachEvent",
    "ApproachParameters",
    "ApproachState",
    "Demo01Populations",
    "FilteredDescendingReadout",
    "OperatingPointCriteria",
    "OrnEncodingParameters",
    "OrnSensoryEncoder",
    "PopulationSpec",
    "ReadoutParameters",
    "bilateral_odour",
    "score_operating_point",
    "searched_parameter_grid",
    "selectivity_index",
]
