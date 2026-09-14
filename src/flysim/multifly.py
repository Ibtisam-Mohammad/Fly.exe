# SPDX-License-Identifier: GPL-2.0-or-later
"""Causal shared-world orchestration for interactive multi-fly demonstrations.

The arena deliberately separates three things that a visually attractive demo can
otherwise blur together:

* the shared world owns stimulus coordinates and collision geometry;
* sensory encoders may inspect that world to construct receptor/neural input;
* motor decoders receive neural outputs only and never receive target coordinates.

The kinematic bodies in this module are an ``E`` web-preview and interaction scaffold.
They do not replace the FlyGym body or the scientific VNC-to-muscle milestone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from flysim.contracts import ActuatorCommandFrame, NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.engines.body import (
    BEHAVIOUR_COMMAND_IDS,
    COMMAND_FORWARD,
    COMMAND_PROBOSCIS,
    COMMAND_YAW,
)
from flysim.errors import CausalityError, ConfigurationError


class FlyMode(StrEnum):
    """Displayed execution class; it is not a validation tier."""

    FULL_CNS = "full-cns"
    SENSORY_ABLATED = "sensory-ablated"
    SHUFFLED_CONNECTOME = "shuffled-connectome"
    CONTROLLER_ONLY = "controller-only"
    COMMAND_REPLAY = "command-replay"
    PASSIVE = "passive"


class StimulusKind(StrEnum):
    FOOD = "food"
    VISUAL_TARGET = "visual-target"
    OBSTACLE = "obstacle"
    DUST = "dust"


@dataclass(slots=True)
class WorldStimulus:
    stimulus_id: str
    kind: StimulusKind
    x_mm: float
    y_mm: float
    radius_mm: float
    strength: float = 1.0
    remaining: float = 1.0
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.stimulus_id.strip():
            raise ConfigurationError("A world stimulus needs a nonempty ID")
        if not all(
            math.isfinite(value)
            for value in (self.x_mm, self.y_mm, self.radius_mm, self.strength, self.remaining)
        ):
            raise ConfigurationError("World stimulus values must be finite")
        if self.radius_mm <= 0.0 or self.strength < 0.0:
            raise ConfigurationError("Stimulus radius must be positive and strength nonnegative")
        if not 0.0 <= self.remaining <= 1.0:
            raise ConfigurationError("Stimulus remaining fraction must lie in [0, 1]")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.stimulus_id,
            "kind": self.kind.value,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "radius_mm": self.radius_mm,
            "strength": self.strength,
            "remaining": self.remaining,
            "revision": self.revision,
        }


@dataclass(slots=True)
class FlyAgentState:
    fly_id: str
    mode: FlyMode
    x_mm: float
    y_mm: float
    heading_rad: float
    radius_mm: float = 1.25
    color: str = "#55d6be"
    food_consumed: float = 0.0
    contacts: set[str] = field(default_factory=set)
    path_length_mm: float = 0.0

    def __post_init__(self) -> None:
        if not self.fly_id.strip():
            raise ConfigurationError("A fly needs a nonempty ID")
        if self.radius_mm <= 0.0:
            raise ConfigurationError("Fly collision radius must be positive")
        if not all(math.isfinite(value) for value in (self.x_mm, self.y_mm, self.heading_rad)):
            raise ConfigurationError("Fly pose must be finite")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.fly_id,
            "mode": self.mode.value,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "heading_rad": self.heading_rad,
            "radius_mm": self.radius_mm,
            "color": self.color,
            "food_consumed": self.food_consumed,
            "contacts": sorted(self.contacts),
            "path_length_mm": self.path_length_mm,
        }


@dataclass(frozen=True, slots=True)
class MultiFlyArenaParameters:
    physics_dt_us: int = 1_000
    half_width_mm: float = 30.0
    half_height_mm: float = 20.0
    max_forward_mm_s: float = 12.0
    max_yaw_rad_s: float = 3.0
    antenna_separation_mm: float = 0.35
    odor_softening_mm2: float = 4.0
    odor_half_saturation: float = 0.04
    food_depletion_per_s: float = 0.08

    def __post_init__(self) -> None:
        positive = (
            self.physics_dt_us,
            self.half_width_mm,
            self.half_height_mm,
            self.max_forward_mm_s,
            self.max_yaw_rad_s,
            self.antenna_separation_mm,
            self.odor_softening_mm2,
            self.odor_half_saturation,
            self.food_depletion_per_s,
        )
        if any(value <= 0 for value in positive):
            raise ConfigurationError("Every multi-fly arena scale must be positive")


@dataclass(frozen=True, slots=True)
class ArenaObservation:
    """Body-local quantities plus a target object visible only to a sensory encoder."""

    t_us: int
    fly_id: str
    x_mm: float
    y_mm: float
    heading_rad: float
    odor_left: float
    odor_right: float
    food_contact: bool
    fly_contacts: tuple[str, ...]
    primary_target: WorldStimulus | None

    def controller_view(self) -> dict[str, Any]:
        """The coordinate-free observation available to controller-only baselines."""
        return {
            "t_us": self.t_us,
            "odor_left": self.odor_left,
            "odor_right": self.odor_right,
            "food_contact": self.food_contact,
            "fly_contact_count": len(self.fly_contacts),
        }


def zero_command(t_us: int, *, source: str) -> ActuatorCommandFrame:
    return ActuatorCommandFrame(
        t_us=t_us,
        ids=BEHAVIOUR_COMMAND_IDS,
        values=tuple(0.0 for _ in BEHAVIOUR_COMMAND_IDS),
        units="normalized engineering commands",
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MOTOR-03", "MULTI-01"),
        metadata={"source": source, "target_coordinates_available": False},
    )


class SharedKinematicArena:
    """Deterministic shared fields and collision-disc bodies for the web preview."""

    def __init__(
        self,
        parameters: MultiFlyArenaParameters,
        flies: Sequence[FlyAgentState],
    ) -> None:
        if not flies:
            raise ConfigurationError("A multi-fly arena needs at least one fly")
        if len({fly.fly_id for fly in flies}) != len(flies):
            raise ConfigurationError("Fly IDs must be unique")
        self.parameters = parameters
        self.flies = {fly.fly_id: fly for fly in flies}
        self.stimuli: dict[str, WorldStimulus] = {}
        self._commands = {fly.fly_id: zero_command(0, source="initial-delay") for fly in flies}
        self._t_us = 0
        self._collision_events = 0

    @property
    def t_us(self) -> int:
        return self._t_us

    def place_stimulus(self, stimulus: WorldStimulus) -> None:
        previous = self.stimuli.get(stimulus.stimulus_id)
        if previous is not None:
            stimulus.revision = previous.revision + 1
        self.stimuli[stimulus.stimulus_id] = stimulus

    def remove_stimulus(self, stimulus_id: str) -> None:
        if stimulus_id not in self.stimuli:
            raise ConfigurationError(f"Unknown stimulus {stimulus_id!r}")
        del self.stimuli[stimulus_id]

    def _odor_raw_at(self, x_mm: float, y_mm: float) -> float:
        total = 0.0
        for stimulus in self.stimuli.values():
            if stimulus.kind is not StimulusKind.FOOD or stimulus.remaining <= 0.0:
                continue
            distance_sq = (x_mm - stimulus.x_mm) ** 2 + (y_mm - stimulus.y_mm) ** 2
            total += (
                stimulus.strength
                * stimulus.remaining
                / (distance_sq + self.parameters.odor_softening_mm2)
            )
        return total

    def odor_at(self, x_mm: float, y_mm: float) -> float:
        raw = self._odor_raw_at(x_mm, y_mm)
        return raw / (raw + self.parameters.odor_half_saturation) if raw > 0.0 else 0.0

    def _primary_target(self, fly: FlyAgentState) -> WorldStimulus | None:
        candidates = [
            stimulus
            for stimulus in self.stimuli.values()
            if stimulus.kind in {StimulusKind.FOOD, StimulusKind.VISUAL_TARGET}
            and stimulus.remaining > 0.0
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda value: (
                math.hypot(fly.x_mm - value.x_mm, fly.y_mm - value.y_mm),
                value.stimulus_id,
            ),
        )

    def observe(self, fly_id: str) -> ArenaObservation:
        try:
            fly = self.flies[fly_id]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown fly {fly_id!r}") from exc
        half = self.parameters.antenna_separation_mm / 2.0
        left_x = fly.x_mm - math.sin(fly.heading_rad) * half
        left_y = fly.y_mm + math.cos(fly.heading_rad) * half
        right_x = fly.x_mm + math.sin(fly.heading_rad) * half
        right_y = fly.y_mm - math.cos(fly.heading_rad) * half
        contact = any(
            stimulus.kind is StimulusKind.FOOD
            and stimulus.remaining > 0.0
            and math.hypot(fly.x_mm - stimulus.x_mm, fly.y_mm - stimulus.y_mm)
            <= fly.radius_mm + stimulus.radius_mm
            for stimulus in self.stimuli.values()
        )
        return ArenaObservation(
            t_us=self._t_us,
            fly_id=fly_id,
            x_mm=fly.x_mm,
            y_mm=fly.y_mm,
            heading_rad=fly.heading_rad,
            odor_left=self.odor_at(left_x, left_y),
            odor_right=self.odor_at(right_x, right_y),
            food_contact=contact,
            fly_contacts=tuple(sorted(fly.contacts)),
            primary_target=self._primary_target(fly),
        )

    def apply_command(self, fly_id: str, command: ActuatorCommandFrame) -> None:
        if command.t_us != self._t_us:
            raise CausalityError(
                f"Command for {fly_id} is stamped {command.t_us}, arena is {self._t_us}"
            )
        if fly_id not in self.flies:
            raise ConfigurationError(f"Unknown fly {fly_id!r}")
        self._commands[fly_id] = command

    def _blocked_by_obstacle(self, fly: FlyAgentState, x_mm: float, y_mm: float) -> bool:
        return any(
            stimulus.kind is StimulusKind.OBSTACLE
            and math.hypot(x_mm - stimulus.x_mm, y_mm - stimulus.y_mm)
            < fly.radius_mm + stimulus.radius_mm
            for stimulus in self.stimuli.values()
        )

    def _resolve_pair_collisions(self, positions: dict[str, list[float]]) -> None:
        fly_ids = sorted(self.flies)
        for fly in self.flies.values():
            fly.contacts.clear()
        for left_index, left_id in enumerate(fly_ids):
            for right_id in fly_ids[left_index + 1 :]:
                left = self.flies[left_id]
                right = self.flies[right_id]
                dx = positions[right_id][0] - positions[left_id][0]
                dy = positions[right_id][1] - positions[left_id][1]
                distance = math.hypot(dx, dy)
                minimum = left.radius_mm + right.radius_mm
                if distance >= minimum:
                    continue
                left.contacts.add(right_id)
                right.contacts.add(left_id)
                self._collision_events += 1
                if distance <= 1e-12:
                    dx, dy, distance = 1.0, 0.0, 1.0
                overlap = minimum - distance
                ux, uy = dx / distance, dy / distance
                left_mobile = left.mode is not FlyMode.PASSIVE
                right_mobile = right.mode is not FlyMode.PASSIVE
                if left_mobile and right_mobile:
                    positions[left_id][0] -= ux * overlap / 2.0
                    positions[left_id][1] -= uy * overlap / 2.0
                    positions[right_id][0] += ux * overlap / 2.0
                    positions[right_id][1] += uy * overlap / 2.0
                elif left_mobile:
                    positions[left_id][0] -= ux * overlap
                    positions[left_id][1] -= uy * overlap
                elif right_mobile:
                    positions[right_id][0] += ux * overlap
                    positions[right_id][1] += uy * overlap

    def _deplete_food(self, dt_s: float) -> None:
        for stimulus in self.stimuli.values():
            if stimulus.kind is not StimulusKind.FOOD or stimulus.remaining <= 0.0:
                continue
            consumers: list[FlyAgentState] = []
            for fly_id, fly in self.flies.items():
                command = self._commands[fly_id]
                if command.value_for(COMMAND_PROBOSCIS, 0.0) <= 0.5:
                    continue
                if (
                    math.hypot(fly.x_mm - stimulus.x_mm, fly.y_mm - stimulus.y_mm)
                    <= fly.radius_mm + stimulus.radius_mm
                ):
                    consumers.append(fly)
            if not consumers:
                continue
            requested_each = self.parameters.food_depletion_per_s * dt_s
            available = stimulus.remaining
            scale = min(1.0, available / (requested_each * len(consumers)))
            consumed_each = requested_each * scale
            stimulus.remaining = max(0.0, available - consumed_each * len(consumers))
            for fly in consumers:
                fly.food_consumed += consumed_each

    def step_until(self, t_us: int) -> None:
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step arena backward from {self._t_us} to {t_us}")
        if (t_us - self._t_us) % self.parameters.physics_dt_us:
            raise CausalityError("Arena boundary is not aligned to the physics step")
        while self._t_us < t_us:
            dt_s = self.parameters.physics_dt_us / 1_000_000.0
            positions: dict[str, list[float]] = {}
            headings: dict[str, float] = {}
            for fly_id, fly in self.flies.items():
                command = self._commands[fly_id]
                forward = max(-1.0, min(1.0, command.value_for(COMMAND_FORWARD, 0.0)))
                yaw = max(-1.0, min(1.0, command.value_for(COMMAND_YAW, 0.0)))
                if fly.mode is FlyMode.PASSIVE:
                    forward = yaw = 0.0
                heading = math.atan2(
                    math.sin(fly.heading_rad + yaw * self.parameters.max_yaw_rad_s * dt_s),
                    math.cos(fly.heading_rad + yaw * self.parameters.max_yaw_rad_s * dt_s),
                )
                x_mm = fly.x_mm + (
                    math.cos(heading) * forward * self.parameters.max_forward_mm_s * dt_s
                )
                y_mm = fly.y_mm + (
                    math.sin(heading) * forward * self.parameters.max_forward_mm_s * dt_s
                )
                if self._blocked_by_obstacle(fly, x_mm, y_mm):
                    x_mm, y_mm = fly.x_mm, fly.y_mm
                positions[fly_id] = [
                    max(-self.parameters.half_width_mm, min(self.parameters.half_width_mm, x_mm)),
                    max(
                        -self.parameters.half_height_mm,
                        min(self.parameters.half_height_mm, y_mm),
                    ),
                ]
                headings[fly_id] = heading
            self._resolve_pair_collisions(positions)
            for fly_id, fly in self.flies.items():
                old_x, old_y = fly.x_mm, fly.y_mm
                fly.x_mm, fly.y_mm = positions[fly_id]
                fly.heading_rad = headings[fly_id]
                fly.path_length_mm += math.hypot(fly.x_mm - old_x, fly.y_mm - old_y)
            self._deplete_food(dt_s)
            self._t_us += self.parameters.physics_dt_us

    def snapshot(self) -> dict[str, Any]:
        return {
            "t_us": self._t_us,
            "flies": [self.flies[fly_id].as_dict() for fly_id in sorted(self.flies)],
            "stimuli": [
                self.stimuli[stimulus_id].as_dict() for stimulus_id in sorted(self.stimuli)
            ],
            "collision_events": self._collision_events,
            "bounds_mm": {
                "x": [-self.parameters.half_width_mm, self.parameters.half_width_mm],
                "y": [-self.parameters.half_height_mm, self.parameters.half_height_mm],
            },
            "body_backend": "shared-kinematic-collision-discs",
            "body_provenance": "E",
        }


class BatchedNeuralEngine(Protocol):
    batch_size: int
    batch_labels: tuple[str, ...]

    @property
    def t_us(self) -> int: ...

    def push_batch_inputs(self, frames: Sequence[NeuralInputFrame]) -> None: ...

    def step_until(self, t_us: int) -> None: ...

    def read_batch_outputs(
        self, ids: tuple[str | int, ...], window_us: int
    ) -> tuple[NeuralOutputFrame, ...]: ...

    def checkpoint(self) -> dict[str, Any]: ...


class NeuralAgentPipeline(Protocol):
    output_ids: tuple[str | int, ...]

    def encode(self, observation: ArenaObservation) -> NeuralInputFrame: ...

    def decode(self, frame: NeuralOutputFrame) -> ActuatorCommandFrame: ...


@dataclass(frozen=True, slots=True)
class NeuralCohort:
    """One graph variant, shared once by all pipelines in this cohort."""

    cohort_id: str
    engine: BatchedNeuralEngine
    pipelines: Mapping[str, NeuralAgentPipeline]

    def __post_init__(self) -> None:
        labels = tuple(self.pipelines)
        if not self.cohort_id.strip():
            raise ConfigurationError("A neural cohort needs a nonempty ID")
        if labels != self.engine.batch_labels or len(labels) != self.engine.batch_size:
            raise ConfigurationError(
                "Neural-cohort pipeline order must exactly match engine batch labels"
            )
        output_sets = {pipeline.output_ids for pipeline in self.pipelines.values()}
        if len(output_sets) != 1:
            raise ConfigurationError("Every fly in a cohort must use the same output IDs")


class ControllerOnlyPolicy:
    """Coordinate-free bilateral-odor controller used only as a labelled baseline."""

    def __init__(
        self,
        *,
        forward_drive: float = 0.55,
        yaw_gain: float = 8.0,
        proboscis_on_contact: bool = True,
    ) -> None:
        self.forward_drive = forward_drive
        self.yaw_gain = yaw_gain
        self.proboscis_on_contact = proboscis_on_contact

    def decode(self, observation: ArenaObservation, *, command_t_us: int) -> ActuatorCommandFrame:
        local = observation.controller_view()
        signal = max(float(local["odor_left"]), float(local["odor_right"]))
        forward = self.forward_drive if signal > 1e-6 and not observation.food_contact else 0.0
        yaw = max(
            -1.0,
            min(1.0, self.yaw_gain * (observation.odor_left - observation.odor_right)),
        )
        proboscis = 1.0 if self.proboscis_on_contact and observation.food_contact else 0.0
        values = {
            COMMAND_FORWARD: forward,
            COMMAND_YAW: yaw,
            COMMAND_PROBOSCIS: proboscis,
        }
        return ActuatorCommandFrame(
            t_us=command_t_us,
            ids=BEHAVIOUR_COMMAND_IDS,
            values=tuple(values.get(identifier, 0.0) for identifier in BEHAVIOUR_COMMAND_IDS),
            units="normalized engineering commands",
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-03", "MULTI-01"),
            metadata={
                "source": "controller-only-bilateral-odor",
                "target_coordinates_available": False,
                "sensor_source_t_us": observation.t_us,
            },
        )


class MultiFlyCoordinator:
    """Advance one shared world with optional batched full-CNS agents causally."""

    def __init__(
        self,
        *,
        arena: SharedKinematicArena,
        coupling_us: int,
        neural_cohorts: Sequence[NeuralCohort] = (),
        controller_policies: Mapping[str, ControllerOnlyPolicy] | None = None,
    ) -> None:
        if coupling_us <= 0 or coupling_us % arena.parameters.physics_dt_us:
            raise ConfigurationError(
                "Coupling must be positive and a whole number of arena physics steps"
            )
        self.arena = arena
        self.coupling_us = coupling_us
        self.neural_cohorts = tuple(neural_cohorts)
        cohort_pipelines = {
            fly_id: pipeline
            for cohort in self.neural_cohorts
            for fly_id, pipeline in cohort.pipelines.items()
        }
        if sum(len(cohort.pipelines) for cohort in self.neural_cohorts) != len(cohort_pipelines):
            raise ConfigurationError("A fly may belong to only one neural cohort")
        self.controller_policies = dict(controller_policies or {})
        unknown = (set(cohort_pipelines) | set(self.controller_policies)) - set(arena.flies)
        if unknown:
            raise ConfigurationError(f"Policies reference unknown flies: {sorted(unknown)}")
        for cohort in self.neural_cohorts:
            if cohort.engine.t_us != arena.t_us:
                raise CausalityError("Neural cohort and arena must start at the same time")
        overlap = set(cohort_pipelines) & set(self.controller_policies)
        if overlap:
            raise ConfigurationError(
                f"Flies cannot have both neural and direct policies: {overlap}"
            )
        self._pending = {
            fly_id: zero_command(0, source="initial-sensorimotor-delay") for fly_id in arena.flies
        }
        self._events: list[dict[str, Any]] = []
        self._last_neural: dict[str, dict[str, Any]] = {}
        self._last_step: dict[str, Any] | None = None

    @property
    def t_us(self) -> int:
        return self.arena.t_us

    def place_stimulus(self, stimulus: WorldStimulus) -> None:
        self.arena.place_stimulus(stimulus)
        self._events.append(
            {"t_us": self.t_us, "event": "place-stimulus", "stimulus": stimulus.as_dict()}
        )

    def remove_stimulus(self, stimulus_id: str) -> None:
        self.arena.remove_stimulus(stimulus_id)
        self._events.append(
            {"t_us": self.t_us, "event": "remove-stimulus", "stimulus_id": stimulus_id}
        )

    def step(self) -> dict[str, Any]:
        current_t = self.t_us
        for fly_id, command in self._pending.items():
            self.arena.apply_command(fly_id, command)
        observations = {fly_id: self.arena.observe(fly_id) for fly_id in sorted(self.arena.flies)}
        next_t = current_t + self.coupling_us
        new_pending: dict[str, ActuatorCommandFrame] = {}
        for cohort in self.neural_cohorts:
            frames = tuple(
                pipeline.encode(observations[fly_id])
                for fly_id, pipeline in cohort.pipelines.items()
            )
            cohort.engine.push_batch_inputs(frames)
            cohort.engine.step_until(next_t)
            output_ids = next(iter(cohort.pipelines.values())).output_ids
            outputs = cohort.engine.read_batch_outputs(output_ids, self.coupling_us)
            for (fly_id, pipeline), output in zip(cohort.pipelines.items(), outputs, strict=True):
                command = pipeline.decode(output)
                if command.t_us != next_t:
                    raise CausalityError(
                        f"Neural decoder for {fly_id} stamped {command.t_us}, expected {next_t}"
                    )
                new_pending[fly_id] = command
                self._last_neural[fly_id] = {
                    "t_us": output.t_us,
                    "ids": [str(value) for value in output.ids],
                    "values_hz": list(output.values),
                    "batch_index": output.metadata.get("batch_index"),
                    "cohort_id": cohort.cohort_id,
                    "model_identity": output.metadata.get("model_identity"),
                    "full_graph": output.metadata.get("full_graph", False),
                }
        for fly_id, policy in self.controller_policies.items():
            new_pending[fly_id] = policy.decode(observations[fly_id], command_t_us=next_t)
        for fly_id in self.arena.flies:
            new_pending.setdefault(fly_id, zero_command(next_t, source="passive"))

        # Commands computed from observations at current_t become active only after the
        # body has finished the current interval on its already committed command.
        self.arena.step_until(next_t)
        self._pending = new_pending
        self._last_step = {
            "sensor_source_t_us": current_t,
            "body_endpoint_t_us": next_t,
            "commands_decoded_at_t_us": next_t,
            "commands_drive_interval_starting_t_us": next_t,
        }
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "mode": "multi-fly-interactive-engineering-demo",
            "validation_tier_awarded": None,
            "arena": self.arena.snapshot(),
            "neural": {
                "enabled": bool(self.neural_cohorts),
                "agents": dict(self._last_neural),
                "cohorts": [
                    {
                        "id": cohort.cohort_id,
                        "agents": list(cohort.pipelines),
                        "checkpoint": cohort.engine.checkpoint(),
                    }
                    for cohort in self.neural_cohorts
                ],
            },
            "pending_commands": {
                fly_id: {
                    "source": command.metadata.get("source", "neural-decoder"),
                    "forward": command.value_for(COMMAND_FORWARD, 0.0),
                    "yaw": command.value_for(COMMAND_YAW, 0.0),
                    "proboscis": command.value_for(COMMAND_PROBOSCIS, 0.0),
                    "decoder_state": command.metadata.get("decoder_state"),
                    "descending_left_hz": dict(command.metadata.get("decoder_inputs", {})).get(
                        "descending_left_hz"
                    ),
                    "descending_right_hz": dict(command.metadata.get("decoder_inputs", {})).get(
                        "descending_right_hz"
                    ),
                    "descending_drive_hz": dict(command.metadata.get("decoder_inputs", {})).get(
                        "descending_drive_hz"
                    ),
                    "target_coordinates_available": command.metadata.get(
                        "target_coordinates_available", False
                    ),
                }
                for fly_id, command in sorted(self._pending.items())
            },
            "causal_timing": self._last_step,
            "events": list(self._events[-100:]),
            "claim_boundary": (
                "Shared-world engineering demonstration. Full-CNS labels mean the complete "
                "MaleCNS runtime graph was executed for that agent; dynamics, visual "
                "transduction, decoder and kinematic collision-disc body remain P/E. Batched "
                "agents are stochastic states of one specimen, not different reconstructed flies."
            ),
            "assumption_ids": ["MULTI-01", "WEB-01", "DEMO-03", "MOTOR-03"],
        }


__all__ = [
    "ArenaObservation",
    "BatchedNeuralEngine",
    "ControllerOnlyPolicy",
    "FlyAgentState",
    "FlyMode",
    "MultiFlyArenaParameters",
    "MultiFlyCoordinator",
    "NeuralAgentPipeline",
    "NeuralCohort",
    "SharedKinematicArena",
    "StimulusKind",
    "WorldStimulus",
    "zero_command",
]
