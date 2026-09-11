# SPDX-License-Identifier: GPL-2.0-or-later
"""The closed loop for one behaviour and one control variant.

    world quantity -> sensory bus -> 165,122 neurons -> declared readout -> causal filter
    -> decoder that sees nothing else -> body -> the world quantity changes -> back again

Modelled on `demo01_embodied.run_embodied`, and deliberately not a generalisation of it.
That function is the recorded code of a passed experiment; a shared abstraction would put
its verdict at risk to make this one shorter.

Three things are fixed here that DEMO-01's runner has, and they are fixed here rather than
there for the same reason:

**The variant reaches the engine.** `demo01_embodied` hardcodes ``variant="exact"`` when it
builds the GeNN engine, and `_shuffled_graph` preserves ``source_sha256``, so the exact and
shuffled runs hash to the same model identity, share a build directory, and the second
silently recompiles over the first. Here the variant is part of the identity and the build
path.

**Rendering is separate by construction.** The run records ``qpos`` and writes no video,
following ADR-2026-015.

**Nothing is scored here.** This module runs and records. The contract is applied by
`demo02_acceptance`, which cannot run a simulation and cannot change a threshold.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.behaviour_body import BehaviourBody, BehaviourBodyParameters
from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, SignalType
from flysim.demo01 import FilteredDescendingReadout, ReadoutParameters
from flysim.demo02 import (
    DECODED,
    DECODERS,
    DecoderParameters,
    Demo02Populations,
    entry_channels,
)
from flysim.engines.body import BEHAVIOUR_COMMAND_IDS
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata, require_clean_worktree
from flysim.sensory_atlas import SensoryAtlas
from flysim.sensory_bus import ChannelBinding, SensoryBus
from flysim.transducers import SaturatingTransducer

#: Every control variant any of the three contracts names.
VARIANTS = (
    "exact",
    "readout-ablated",
    "stimulus-absent",
    "shuffled-connectome",
    "entry-swapped",
    "suppress-groom-replay",
    "controller-only",
    "zero-tonic-drive",
    "contact-without-sucrose",
    "matched-size-static",
    "command-replay",
    "jump-only",
    "wing-only",
)

#: World quantity per entry channel. Declared, and the kinds are in the sensor frame.
SENSOR_FOR_CHANNEL = {
    "antennal-jo-f-grooming:antenna:L": "world:antenna-deflection:l",
    "antennal-jo-f-grooming:antenna:R": "world:antenna-deflection:r",
    "tarsal-taste:leg-front:L": "world:tarsal-sucrose:lf",
    "tarsal-taste:leg-front:R": "world:tarsal-sucrose:rf",
    "tarsal-taste:leg-hind:L": "world:tarsal-sucrose:lh",
    "tarsal-taste:leg-hind:R": "world:tarsal-sucrose:rh",
}

#: One transducer per channel family. P/E under DEMO-03.
TRANSDUCERS = {
    "antennal-jo-f-grooming": SaturatingTransducer(
        max_rate_hz=140.0, half_saturation=0.20, threshold=0.02
    ),
    "tarsal-taste": SaturatingTransducer(max_rate_hz=110.0, half_saturation=0.25),
}


@dataclass(frozen=True, slots=True)
class BehaviourResult:
    behaviour: str
    variant: str
    directory: Path
    intervals: int
    duration_us: int
    displacement_mm: float
    onset_us: int | None
    summary: dict[str, Any]


def _shuffled_graph(
    graph: SparseConnectome, seed: int
) -> tuple[SparseConnectome, dict[str, Any]]:
    """Permute only which pairs the edges join.

    Edge count, every out-degree and the multiset of contact counts survive exactly, and
    the memory-mapped release is never mutated.
    """
    rng = np.random.default_rng(seed)
    targets = np.asarray(graph.target_indices).copy()
    rng.shuffle(targets)
    shuffled = replace(graph, target_indices=targets)
    return shuffled, {
        "shuffled": True,
        "seed": seed,
        "preserved": ["edge count", "every out-degree", "contact-count multiset"],
        "changed": ["which pairs the edges join"],
    }


class Recorder:
    """Streams one row per coupling interval, plus poses and spikes."""

    def __init__(self, directory: Path, *, neuron_count: int) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self._neuron_count = neuron_count
        self._trace = (directory / "trace.jsonl").open("w", encoding="utf-8")
        self._rows = 0
        self._offsets = [0]
        self._indices: list[np.ndarray] = []
        self._counts: list[np.ndarray] = []
        self._poses: list[np.ndarray] = []
        self._times: list[int] = []
        self.rows: list[dict[str, Any]] = []

    def add_interval(self, row: dict[str, Any], spikes: np.ndarray) -> None:
        """``spikes`` is the engine's per-neuron count in dense graph order."""
        self._trace.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.rows.append(row)
        self._rows += 1
        active = np.flatnonzero(spikes)
        self._indices.append(active.astype(np.uint32))
        self._counts.append(np.minimum(spikes[active], 255).astype(np.uint8))
        self._offsets.append(self._offsets[-1] + int(active.size))

    def add_pose(self, t_us: int, qpos: np.ndarray) -> None:
        self._poses.append(np.asarray(qpos, dtype=np.float64))
        self._times.append(int(t_us))

    def close(self) -> dict[str, Any]:
        self._trace.close()
        np.savez_compressed(
            self.directory / "spikes.npz",
            offsets=np.asarray(self._offsets, dtype=np.int64),
            indices=(
                np.concatenate(self._indices) if self._indices else np.zeros(0, np.uint32)
            ),
            counts=np.concatenate(self._counts) if self._counts else np.zeros(0, np.uint8),
            neuron_count=np.asarray(self._neuron_count, dtype=np.int64),
        )
        np.savez_compressed(
            self.directory / "poses.npz",
            qpos=(
                np.stack(self._poses) if self._poses else np.zeros((0, 0), dtype=np.float64)
            ),
            t_us=np.asarray(self._times, dtype=np.int64),
        )
        events = int(self._offsets[-1])
        return {
            "intervals": self._rows,
            "spike_events_recorded": events,
            "mean_active_neurons_per_interval": (
                events / self._rows if self._rows else 0.0
            ),
            "pose_intervals": len(self._poses),
            "qpos_size": int(self._poses[0].size) if self._poses else 0,
            "files": ["trace.jsonl", "spikes.npz", "poses.npz"],
            "why_no_video": (
                "Rendering is separated from simulation by construction, per ADR-2026-015. "
                "The model plus qpos determines every body frame, so replay is exact."
            ),
        }


def _bindings(
    atlas: SensoryAtlas, behaviour: str, *, variant: str
) -> tuple[ChannelBinding, ...]:
    channels = entry_channels(behaviour)
    silent = variant in {"stimulus-absent", "controller-only", "command-replay"}
    if behaviour == "feeding" and variant == "contact-without-sucrose":
        silent = True
    bindings: list[ChannelBinding] = []
    for key in channels:
        sensor = SENSOR_FOR_CHANNEL.get(str(key))
        if sensor is None:
            raise ConfigurationError(f"No world quantity declared for channel {key}")
        bindings.append(
            ChannelBinding(
                key=key,
                sensor_id=sensor,
                transducer=TRANSDUCERS[key.modality],
                delay_us=0,
                enabled=not silent,
                kind=atlas.modality_kind.get(key.modality, "real"),
                why=f"{behaviour} entry",
            )
        )
    return tuple(bindings)


def run_behaviour(
    *,
    behaviour: str,
    variant: str,
    contract_path: Path,
    graph_path: Path,
    annotations_path: Path,
    transmitter_path: Path,
    build_root: Path,
    output_directory: Path,
    body_parameters: BehaviourBodyParameters,
    trajectory_path: Path | None,
    decoder: DecoderParameters,
    parameters: dict[str, Any],
    duration_us: int,
    seed: int,
    allow_dirty_tree: bool = False,
    progress: bool = False,
) -> BehaviourResult:
    if behaviour not in DECODERS:
        raise ConfigurationError(f"Unknown behaviour: {behaviour}")
    if variant not in VARIANTS:
        raise ConfigurationError(f"Unknown variant: {variant}")
    verification = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree(f"A DEMO-02 {behaviour} run")
    )
    contract = load_json(contract_path)
    coupling_us = int(contract["fixed_parameters"]["coupling_us"])
    if duration_us % coupling_us:
        raise ConfigurationError("The duration must be a whole number of intervals")

    graph = SparseConnectome.load(graph_path)
    graph.validate()
    atlas = SensoryAtlas.resolve(annotations_path, graph)
    populations = Demo02Populations.resolve(
        annotations_path, graph, behaviour=behaviour, entry_body_ids=atlas.entry_union
    )
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(parameters["unresolved_sign_policy"]),
        seed=seed,
    ).edge_signs
    shuffle: dict[str, Any] = {"shuffled": False}
    if variant == "shuffled-connectome":
        graph, shuffle = _shuffled_graph(graph, seed)

    engine_parameters = dict(parameters)
    engine_parameters.pop("unresolved_sign_policy", None)
    if variant == "zero-tonic-drive":
        engine_parameters["tonic_drive_mv"] = 0.0
    engine_parameters["functional_edge_signs"] = signs
    engine_parameters["entry_body_ids"] = atlas.entry_union

    identity = sha256_json({
        k: v for k, v in engine_parameters.items()
        if k not in {"functional_edge_signs", "entry_body_ids"}
    })[:12]
    # The variant is part of the build path AND of the engine identity, so the shuffled
    # control cannot share a compiled model with the exact run.
    engine = TrackAGeNNEngine(build_root / f"{identity}-{variant}", variant=variant)
    build_started = time.perf_counter()
    engine.initialize(graph, engine_parameters, seed)
    build_seconds = time.perf_counter() - build_started

    bindings = _bindings(atlas, behaviour, variant=variant)
    bus = SensoryBus(atlas=atlas, bindings=bindings, coupling_us=coupling_us)
    readout = FilteredDescendingReadout(
        populations=populations,  # type: ignore[arg-type]
        parameters=ReadoutParameters(
            filter_tau_ms=float(parameters["readout_filter_tau_ms"])
        ),
        ablated_population_ids=(
            frozenset(DECODED[behaviour]) if variant == "readout-ablated" else frozenset()
        ),
    )
    controller = DECODERS[behaviour](parameters=decoder, coupling_us=coupling_us)

    stimulus_off = variant in {"stimulus-absent", "contact-without-sucrose"}
    body = BehaviourBody(
        parameters=replace(
            body_parameters,
            antennal_stimulus_side=(
                "none" if stimulus_off or behaviour != "grooming"
                else body_parameters.antennal_stimulus_side
            ),
            sucrose_x_mm=(
                1e6 if stimulus_off and behaviour == "feeding"
                else body_parameters.sucrose_x_mm
            ),
        ),
        behaviour=behaviour,
        seed=seed,
        trajectory_path=trajectory_path,
    )
    recorder = Recorder(output_directory, neuron_count=graph.neuron_count)
    readout_ids = populations.readout_body_ids
    intervals = duration_us // coupling_us
    onset_us: int | None = None
    simulation_started = time.perf_counter()

    pending = ActuatorCommandFrame(
        t_us=0,
        ids=BEHAVIOUR_COMMAND_IDS,
        values=tuple(0.0 for _ in BEHAVIOUR_COMMAND_IDS),
        units=", ".join("normalized" for _ in BEHAVIOUR_COMMAND_IDS),
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MOTOR-03", "DEMO-02"),
        metadata={"why_zero": "the first interval has no neural history to decode"},
    )
    try:
        for step in range(intervals):
            t_us = step * coupling_us
            applied = pending
            body.apply_actuators(applied)
            sensors = body.sample_sensors()
            frame_in = bus.encode(t_us, sensors)
            engine.push_inputs(frame_in)
            engine.step_until(t_us + coupling_us)
            raw = engine.read_outputs(readout_ids, coupling_us)
            neural = readout.read(raw)
            pending = controller.decode(neural)
            if onset_us is None and controller.state.value == "ACTING":
                onset_us = pending.t_us
            body.step_until(t_us + coupling_us)
            x_mm, y_mm, z_mm, heading = body.pose()
            metrics = body.metrics()
            recorder.add_interval(
                {
                    "t_us": t_us + coupling_us,
                    "pose": {"x_mm": x_mm, "y_mm": y_mm, "z_mm": z_mm,
                             "heading_rad": heading},
                    "sensors": dict(zip(sensors.ids, sensors.values, strict=True)),
                    "channel_rate_hz": frame_in.metadata["channel_rate_hz"],
                    "entry_bodies_driven": frame_in.metadata[
                        "entry_bodies_with_nonzero_rate"
                    ],
                    "readout_hz": dict(zip(neural.ids, neural.values, strict=True)),
                    "readout_raw_counts": neural.metadata.get(
                        "raw_population_spike_counts", {}
                    ),
                    "command": {
                        **dict(zip(applied.ids, applied.values, strict=True)),
                        "state": applied.metadata.get("state", "QUIESCENT"),
                    },
                    "body": metrics,
                },
                engine.spike_counts_since_last_frame(),
            )
            recorder.add_pose(t_us + coupling_us, body.qpos())
            if progress and step % 50 == 0:
                print(f"  {behaviour}/{variant} {step}/{intervals}", flush=True)
        simulation_seconds = time.perf_counter() - simulation_started
        recording = recorder.close()
        start = recorder.rows[0]["pose"] if recorder.rows else {"x_mm": 0.0, "y_mm": 0.0}
        end = recorder.rows[-1]["pose"] if recorder.rows else start
        displacement = float(
            np.hypot(end["x_mm"] - start["x_mm"], end["y_mm"] - start["y_mm"])
        )
        summary = {
            "behaviour": behaviour,
            "variant": variant,
            "code_commit": verification["commit"],
            "worktree_dirty": verification["dirty"],
            "verification": verification.get("verification", {}),
            "seed": seed,
            "experiment_id": contract["experiment_id"],
            "experiment_sha256": sha256_json(contract),
            "parameters": {
                k: v for k, v in parameters.items() if k != "functional_edge_signs"
            },
            "decoder": decoder.as_dict(),
            "graph": {
                "path": str(graph_path),
                "source_sha256": graph.source_sha256,
                "neurons": graph.neuron_count,
                "edges": graph.edge_count,
                "shuffle": shuffle,
            },
            "model_identity": engine.checkpoint().get("model_identity"),
            "populations": populations.as_dict(),
            "sensory_bus": bus.describe(),
            "body": body.describe(),
            "station_keeping": body.station_keeping(),
            "takeoff": body.takeoff(),
            "coupling_us": coupling_us,
            "sensorimotor_delay_us": coupling_us,
            "duration_us": duration_us,
            "intervals": intervals,
            "build_seconds": build_seconds,
            "simulation_seconds": simulation_seconds,
            "recording": recording,
            "outcome": {
                "displacement_mm": displacement,
                "onset_us": onset_us,
                "decoder_events": controller.events,
                "reached_acting": onset_us is not None,
            },
            "claim_boundary": contract["claim_boundary"],
        }
        (output_directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return BehaviourResult(
            behaviour=behaviour,
            variant=variant,
            directory=output_directory,
            intervals=intervals,
            duration_us=duration_us,
            displacement_mm=displacement,
            onset_us=onset_us,
            summary=summary,
        )
    finally:
        body.close()
        engine.close()
