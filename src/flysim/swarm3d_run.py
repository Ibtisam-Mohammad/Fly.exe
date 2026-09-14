# SPDX-License-Identifier: GPL-2.0-or-later
"""The closed loop for an embodied swarm: N brains, N bodies, one scene, one GPU model.

The loop, per fly, per coupling interval::

    the scene as that fly's eyes are placed
      -> retinotopic lamina drive over every visible object   (flysim.swarm3d_vision)
      -> 165,122 neurons and 25,563,197 edges, that fly's own state   (GeNN, batched)
      -> declared posterior descending readout, causally filtered      (flysim.demo01)
      -> two normalised drives                                         (flysim.demo01_visual)
      -> HybridTurningController -> that fly's legs                    (flysim.swarm3d)
      -> the bodies all step together and collide with the objects, though not with
         each other: no fly-fly contact pair exists, so they are coupled by vision only
      -> the scene has changed, and every fly sees the change

Three structural properties, each of which is a thing that can be checked rather than
asserted.

**One connectivity allocation, N independent states.** GeNN's native batching holds the
sparse connectivity once and runs `batch_size` neuron states over it. Twelve flies do not
mean twelve copies of a 25.5-million-edge graph; they mean one graph and twelve membrane
vectors, twelve spike counters and twelve independent noise streams. The summary reports
`connectivity_allocations`, and it is 1.

**The decoders cannot see the world.** Each fly's decoder takes two descending population
rates and nothing else -- no pose, no distance to anything, no bearing, no time. The
command frames carry `target_coordinates_available: false` for the same reason DEMO-01's
do: so that the claim can be inspected rather than believed.

**The sensorimotor delay is real.** A command decoded from activity over one interval
drives the body over the next one. The first interval runs on an explicit zero command,
because a brain cannot move a body with activity it has not produced yet.

What this is not. There is no preregistered biological hypothesis here and no acceptance
contract, so nothing in this module awards a validation tier and the summary says so in a
field rather than in prose. It is an engineering demonstration of the machinery the project
has built, run on the exact released graph at the frozen DEMO-01 operating point.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, SignalType
from flysim.demo01 import FilteredDescendingReadout, ReadoutParameters
from flysim.demo01_embodied import _shuffled_graph
from flysim.demo01_visual import (
    VISUAL_LEFT_READOUT,
    VISUAL_RIGHT_READOUT,
    RetinaMap,
    VisualDecoderParameters,
    VisualEncodingParameters,
    VisualLocomotorDecoder,
)
from flysim.demo01_visual_probe import resolve_visual_populations
from flysim.demo02_embodied import compiled_kernel_fingerprint
from flysim.engines.body import COMMAND_FORWARD, COMMAND_IDS, COMMAND_YAW
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata, require_clean_worktree
from flysim.swarm3d import (
    SCAFFOLDS,
    SwarmArenaParameters,
    SwarmFlySpec,
    SwarmObject,
    SwarmWorld,
)
from flysim.swarm3d_vision import MultiObjectLaminaEncoder, visible_objects_for

# Every control variant this module knows how to run, all from an identical seed.
#
# `stimulus-absent` is the one that matters most for a public video. It removes the scene
# from the encoder and changes nothing else: the same graph, the same bodies, the same
# noise stream, the same decoders. Whatever the flies do in that run is what walking looks
# like when the brain is driven only by its own baseline, and it is the floor that "eight
# of eight closed on a target" has to beat before it means anything.
CONTROL_VARIANTS: tuple[str, ...] = (
    "exact",
    "stimulus-absent",
    "shuffled-connectome",
)


def zero_command(t_us: int) -> ActuatorCommandFrame:
    return ActuatorCommandFrame(
        t_us=t_us,
        ids=COMMAND_IDS,
        values=(0.0, 0.0, 0.0, 0.0),
        units="normalized-drive [0,1], normalized-drive [-1,1], normalized, normalized",
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MOTOR-06", "DEMO-03"),
        metadata={
            "decoder_state": "QUIESCENT",
            "sensor_terms_in_command": [],
            "target_coordinates_available": False,
            "why_zero": (
                "The first coupling interval precedes any brain output, so the body is "
                "commanded to stand rather than given a guessed drive."
            ),
        },
    )


# --------------------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------------------


class SwarmRecorder:
    """Scalars as JSONL, whole-scene physics state and per-fly spikes as arrays.

    The spike files use exactly the layout `flysim.demo01_render.SpikeRecording` reads, so
    the brain view that was built for one fly renders any fly in this scene with no new
    loader and no new format.
    """

    def __init__(self, directory: Path, *, fly_ids: Sequence[str], neuron_count: int) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.fly_ids = tuple(fly_ids)
        self.neuron_count = neuron_count
        self._trace = (directory / "trace.jsonl").open("w", encoding="utf-8")
        self._spike_indices: list[list[np.ndarray]] = [[] for _ in self.fly_ids]
        self._spike_counts: list[list[np.ndarray]] = [[] for _ in self.fly_ids]
        self._qpos: list[np.ndarray] = []
        self._pose_t_us: list[int] = []
        self._rows = 0

    def add_interval(self, row: dict[str, Any], spikes: np.ndarray) -> None:
        self._trace.write(json.dumps(row, separators=(",", ":")) + "\n")
        for index in range(len(self.fly_ids)):
            counts = spikes[index]
            active = np.flatnonzero(counts)
            self._spike_indices[index].append(active.astype(np.uint32))
            self._spike_counts[index].append(
                np.minimum(counts[active], 255).astype(np.uint8)
            )
        self._rows += 1

    def add_pose(self, t_us: int, qpos: np.ndarray) -> None:
        self._pose_t_us.append(int(t_us))
        self._qpos.append(np.asarray(qpos, dtype=np.float64))

    def close(self) -> dict[str, Any]:
        self._trace.close()
        spike_files: dict[str, str] = {}
        total_events = 0
        for index, fly_id in enumerate(self.fly_ids):
            offsets = np.zeros(self._rows + 1, dtype=np.int64)
            chunks = self._spike_indices[index]
            if chunks:
                offsets[1:] = np.cumsum([chunk.size for chunk in chunks])
                indices = np.concatenate(chunks)
                counts = np.concatenate(self._spike_counts[index])
            else:
                indices = np.zeros(0, dtype=np.uint32)
                counts = np.zeros(0, dtype=np.uint8)
            name = f"spikes-{fly_id}.npz"
            np.savez_compressed(
                self.directory / name,
                offsets=offsets,
                indices=indices,
                counts=counts,
                neuron_count=np.int64(self.neuron_count),
            )
            spike_files[fly_id] = name
            total_events += int(indices.size)
            # Release as we go: twelve flies at four thousand intervals is a few hundred
            # megabytes of index arrays, and holding all of it to the end is unnecessary.
            self._spike_indices[index] = []
            self._spike_counts[index] = []
        qpos = (
            np.stack(self._qpos) if self._qpos else np.zeros((0, 0), dtype=np.float64)
        )
        np.savez_compressed(
            self.directory / "poses.npz",
            qpos=qpos,
            t_us=np.asarray(self._pose_t_us, dtype=np.int64),
        )
        return {
            "intervals": self._rows,
            "spike_events_recorded": total_events,
            "mean_active_neurons_per_interval_per_fly": (
                float(total_events / self._rows / len(self.fly_ids))
                if self._rows
                else 0.0
            ),
            "trace": "trace.jsonl",
            "spikes": spike_files,
            "poses": "poses.npz",
            "pose_intervals": int(qpos.shape[0]),
            "qpos_size": int(qpos.shape[1]) if qpos.ndim == 2 else 0,
            "why_poses_and_not_video": (
                "The whole scene's generalised position vector is recorded once per "
                "coupling interval instead of a rendered frame, so no camera is baked "
                "into the recording and every shot can be recut without re-simulating."
            ),
        }


@dataclass(frozen=True, slots=True)
class SwarmRunResult:
    variant: str
    directory: Path
    intervals: int
    duration_us: int
    summary: dict[str, Any]


# --------------------------------------------------------------------------------------
# Scenario
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwarmScenario:
    scenario_id: str
    arena: SwarmArenaParameters
    flies: tuple[SwarmFlySpec, ...]
    objects: tuple[SwarmObject, ...]
    decoder: VisualDecoderParameters
    include_other_flies: bool

    @classmethod
    def load(cls, path: Path) -> SwarmScenario:
        raw = load_json(path)
        flies = tuple(SwarmFlySpec.from_mapping(item) for item in raw["flies"])
        objects = tuple(SwarmObject.from_mapping(item) for item in raw.get("objects", ()))
        if not flies:
            raise ConfigurationError(f"{path} declares no flies")
        return cls(
            scenario_id=str(raw["scenario_id"]),
            arena=SwarmArenaParameters.from_mapping(raw["arena"]),
            flies=flies,
            objects=objects,
            decoder=VisualDecoderParameters.from_mapping(raw["decoder"]),
            include_other_flies=bool(
                raw.get("vision", {}).get("include_other_flies", True)
            ),
        )


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


def run_swarm3d(
    *,
    contract_path: Path,
    scenario: SwarmScenario,
    operating_point: dict[str, float],
    graph_path: Path,
    annotations_path: Path,
    transmitter_path: Path,
    build_root: Path,
    output_directory: Path,
    duration_us: int,
    seed: int,
    variant: str = "exact",
    allow_dirty_tree: bool = False,
    progress: bool = False,
) -> SwarmRunResult:
    """One closed-loop swarm run of one control variant, fully recorded."""
    if variant not in CONTROL_VARIANTS:
        raise ConfigurationError(
            f"Unknown control variant {variant!r}; expected one of {CONTROL_VARIANTS}"
        )
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree(f"The embodied swarm run ({variant})")
    )
    contract = load_json(contract_path)
    coupling_us = int(contract["coupling_us"])
    if duration_us % coupling_us:
        raise ConfigurationError("Duration must be a whole number of coupling intervals")
    dt_us = scenario.arena.physics_dt_us
    if coupling_us % dt_us:
        raise ConfigurationError("Coupling interval must be a whole number of physics steps")

    fly_count = len(scenario.flies)
    fly_ids = tuple(fly.fly_id for fly in scenario.flies)

    graph = SparseConnectome.load(graph_path)
    graph.validate()
    populations = resolve_visual_populations(annotations_path, graph)
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs

    shuffle_report: dict[str, Any] | None = None
    if variant == "shuffled-connectome":
        # DEMO-01's control, imported rather than reimplemented: it permutes the
        # target array, preserving the edge count, every out-degree and the contact
        # multiset, and it asserts all three. Its regime caveat travels with it.
        graph, shuffle_report = _shuffled_graph(graph, seed)
        shuffle_report["what_this_control_cannot_do"] = (
            "It moves the network's operating regime as well as its wiring, so a "
            "difference between exact and shuffled is not attributable to topology "
            "alone. See docs/evidence/SHUFFLE_CONTROL_REGIME_MATCHED.md."
        )
        graph.validate()

    parameters = {**contract["fixed_parameters"], **operating_point}
    # GeNN bakes the RNG seed, the connectivity and the batch size into the generated
    # code, so all three enter the build key. Without the wiring digest the exact and
    # shuffled variants would share one key while executing different graphs; without the
    # batch size a one-fly build would be loaded for a twelve-fly run.
    wiring_digest = hashlib.sha256(
        np.asarray(graph.target_indices, dtype=np.int64).tobytes()
    ).hexdigest()[:12]
    build_key = sha256_json(
        {**parameters, "wiring": wiring_digest, "seed": seed, "batch": fly_count}
    )[:12]
    engine = TrackAGeNNEngine(
        build_root / build_key,
        variant="exact",
        batch_size=fly_count,
        batch_labels=fly_ids,
    )
    build_started = time.perf_counter()
    engine.initialize(
        graph,
        {
            **parameters,
            "functional_edge_signs": signs,
            "entry_body_ids": populations.entry_body_ids,
        },
        seed,
    )
    build_seconds = time.perf_counter() - build_started
    kernel = compiled_kernel_fingerprint(build_root, build_key)

    encoder = MultiObjectLaminaEncoder(
        populations,
        VisualEncodingParameters.from_mapping(parameters),
        RetinaMap.from_mapping(contract["retina_map"]),
        stimulus_present=variant != "stimulus-absent",
    )
    readouts = [
        FilteredDescendingReadout(
            populations, ReadoutParameters.from_mapping(contract["readout"])
        )
        for _ in range(fly_count)
    ]
    decoders = [VisualLocomotorDecoder(scenario.decoder) for _ in range(fly_count)]
    world = SwarmWorld(
        scenario.arena,
        scenario.flies,
        scenario.objects,
        seed=seed,
        appearance=False,
        lighting=False,
    )
    readout_ids = populations.readout_body_ids
    pools = dict(populations.monitors)
    recorder = SwarmRecorder(
        output_directory, fly_ids=fly_ids, neuron_count=graph.neuron_count
    )

    object_order = tuple(obj.object_id for obj in scenario.objects)
    food_xy = {
        obj.object_id: (obj.x_mm, obj.y_mm)
        for obj in scenario.objects
        if obj.kind == "food"
    }
    intervals = duration_us // coupling_us
    pending = [zero_command(0) for _ in range(fly_count)]
    initial_poses = world.poses()
    onset_us: list[int | None] = [None] * fly_count

    simulation_started = time.perf_counter()
    try:
        for step in range(intervals):
            t_us = step * coupling_us
            for index in range(fly_count):
                world.apply_actuators(index, pending[index])
            poses = world.poses()

            frames = []
            scenes = []
            for index in range(fly_count):
                x_mm, y_mm, _, heading = poses[index]
                seen = visible_objects_for(
                    index,
                    poses,
                    scenario.objects,
                    fly_visual_radius_mm=scenario.arena.fly_visual_radius_mm,
                    include_other_flies=scenario.include_other_flies,
                )
                frame = encoder.encode(
                    t_us, seen, x_mm=x_mm, y_mm=y_mm, heading_rad=heading
                )
                frames.append(frame)
                scenes.append(frame.metadata["scene"])

            engine.push_batch_inputs(frames)
            engine.step_until(t_us + coupling_us)
            raw_frames = engine.read_batch_outputs(readout_ids, coupling_us)

            applied = list(pending)
            filtered = []
            for index in range(fly_count):
                neural = readouts[index].read(raw_frames[index])
                filtered.append(neural)
                command = decoders[index].decode(neural)
                pending[index] = command
                if onset_us[index] is None and decoders[index].state.value == "LOCOMOTING":
                    onset_us[index] = command.t_us

            world.step_until(t_us + coupling_us)
            activity = engine.population_activity_batch(pools, coupling_us)
            spikes = engine.spike_counts_since_last_frame_batch()

            new_poses = world.poses()
            row: dict[str, Any] = {
                "t_us": t_us + coupling_us,
                "flies": [],
            }
            for index in range(fly_count):
                x_mm, y_mm, z_mm, heading = new_poses[index]
                neural = filtered[index]
                scene = scenes[index]
                nearest_food = _nearest(food_xy, x_mm, y_mm)
                row["flies"].append(
                    {
                        "fly_id": fly_ids[index],
                        "pose": {
                            "x_mm": x_mm,
                            "y_mm": y_mm,
                            "z_mm": z_mm,
                            "heading_rad": heading,
                        },
                        "readout_hz": {
                            VISUAL_LEFT_READOUT: neural.value_for(VISUAL_LEFT_READOUT),
                            VISUAL_RIGHT_READOUT: neural.value_for(VISUAL_RIGHT_READOUT),
                        },
                        "readout_raw_counts": {
                            str(name): int(value)
                            for name, value in neural.metadata[
                                "raw_population_spike_counts"
                            ].items()
                        },
                        "scene": {
                            "stimulus_present": scene["stimulus_present"],
                            "driven_lamina_bodies": scene["driven_bodies"],
                            "objects_visible": scene["objects_visible"],
                            "strongest": scene["strongest"],
                            "peak_drive_by_object": [
                                next(
                                    (
                                        entry["peak_drive"]
                                        for entry in scene["per_object"]
                                        if entry["object_id"] == object_id
                                    ),
                                    0.0,
                                )
                                for object_id in object_order
                            ],
                        },
                        "nearest_food": nearest_food,
                        "pool_mean_rate_hz": {
                            name: value["mean_rate_hz"]
                            for name, value in activity[index].items()
                        },
                        "command": {
                            "forward": applied[index].value_for(COMMAND_FORWARD, 0.0),
                            "yaw": applied[index].value_for(COMMAND_YAW, 0.0),
                            "state": applied[index].metadata["decoder_state"],
                        },
                        "command_decoded_this_interval": {
                            "forward": pending[index].value_for(COMMAND_FORWARD, 0.0),
                            "yaw": pending[index].value_for(COMMAND_YAW, 0.0),
                            "state": pending[index].metadata["decoder_state"],
                            "drives_the_body_next_interval": True,
                        },
                    }
                )
            recorder.add_interval(row, spikes)
            recorder.add_pose(t_us + coupling_us, world.qpos())
            if progress and step % 50 == 0:
                moving = sum(
                    1
                    for index in range(fly_count)
                    if pending[index].metadata["decoder_state"] == "LOCOMOTING"
                )
                nearest = min(
                    (entry["nearest_food"]["distance_mm"] for entry in row["flies"]),
                    default=float("nan"),
                )
                print(
                    f"  [{step:5d}/{intervals}] t={t_us / 1e6:6.2f}s  "
                    f"walking {moving}/{fly_count}  nearest food {nearest:6.2f} mm",
                    flush=True,
                )
        simulation_seconds = time.perf_counter() - simulation_started
    finally:
        recording = recorder.close()
        world.close()
        engine.close()

    final_poses = tuple(
        (entry["pose"]["x_mm"], entry["pose"]["y_mm"], 0.0, entry["pose"]["heading_rad"])
        for entry in row["flies"]
    )
    outcome = _outcome(
        fly_ids=fly_ids,
        initial=initial_poses,
        final=final_poses,
        food_xy=food_xy,
        onset_us=onset_us,
        decoders=decoders,
    )

    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "run": "swarm3d-showcase",
        "variant": variant,
        "provenance": "P/E for the network, E for the decoder, the bodies and the arena",
        "evidence_grade": False,
        "why_not_evidence": (
            "There is no preregistered biological hypothesis for a swarm and no "
            "acceptance contract scoring one, so this run can demonstrate machinery and "
            "cannot validate biology. Every number it reports is an engineering "
            "measurement of what the frozen DEMO-01 network did in this arena."
        ),
        "validation_tier_awarded": None,
        "code_commit": worktree.get("commit"),
        "worktree_dirty": worktree.get("dirty"),
        "code_verification": worktree.get("verification"),
        "seed": seed,
        "scenario_id": scenario.scenario_id,
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "operating_point": dict(operating_point),
        "operating_point_source": (
            "frozen artifact of the registered DEMO-01 visual operating-point search; "
            "no parameter here was chosen for this video"
        ),
        "decoder": scenario.decoder.as_dict(),
        "graph": {
            "neurons": graph.neuron_count,
            "edges": int(graph.target_indices.size),
            "every_edge_built": True,
            "shuffle": shuffle_report,
        },
        "batch": {
            "size": fly_count,
            "labels": list(fly_ids),
            "connectivity_allocations": 1,
            "neurons_per_fly": graph.neuron_count,
            "edges_shared_per_cohort": int(graph.target_indices.size),
            "what_is_shared": (
                "One immutable sparse connectivity allocation. Membrane voltage, "
                "adaptation state, spike counters and the membrane-noise stream are "
                "independent per fly."
            ),
            "what_is_not_modelled": (
                "The flies are parameterised copies of one specimen. They are not "
                "individuals and there is no genetic, developmental or connectomic "
                "variation between them."
            ),
        },
        "kernel": kernel,
        "populations": populations.as_dict(),
        "build_key": build_key,
        "wiring_digest": wiring_digest,
        "coupling_us": coupling_us,
        "duration_us": duration_us,
        "intervals": intervals,
        "sensorimotor_delay_us": coupling_us,
        "build_seconds": build_seconds,
        "simulation_seconds": simulation_seconds,
        "biological_per_wall": (
            duration_us / 1_000_000.0 / simulation_seconds if simulation_seconds else 0.0
        ),
        "world": world_description(scenario),
        "vision": {
            "encoder": "flysim.swarm3d_vision.MultiObjectLaminaEncoder",
            "reduces_to_demo01_with_one_object": True,
            "entry_bodies_driven": encoder.entry_body_count,
            "include_other_flies": scenario.include_other_flies,
            "stimulus_present": variant != "stimulus-absent",
        },
        "recording": recording,
        "outcome": outcome,
        "scaffolds": list(SCAFFOLDS),
        "omissions": [
            "No fly-fly collision: FlyGym gives every fly geom contype 0 and this "
            "world writes no fly-fly contact pair, so two bodies pass through one "
            "another. The flies are coupled through vision only.",
            "No retina-to-lamina synapse: every photoreceptor edge is zeroed by the "
            "frozen unresolved-sign policy, so the loop enters one synapse downstream.",
            "No VNC motor hierarchy: leg movement comes from an engineered pattern "
            "generator, not from the simulated ventral cord.",
            "No feeding, no ingestion and no proboscis extension. Food here is a "
            "coloured sphere the flies can see and touch, and nothing else.",
            "No odour, no taste, no mechanosensation, no wind and no gravity sensing.",
            "No learning, no plasticity and no internal state of any kind between "
            "coupling intervals beyond the membrane and adaptation variables.",
        ],
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return SwarmRunResult(
        variant=variant,
        directory=output_directory,
        intervals=intervals,
        duration_us=duration_us,
        summary=summary,
    )


def world_description(scenario: SwarmScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "arena": scenario.arena.as_dict(),
        "flies": [fly.as_dict() for fly in scenario.flies],
        "objects": [obj.as_dict() for obj in scenario.objects],
    }


def _nearest(
    food_xy: dict[str, tuple[float, float]], x_mm: float, y_mm: float
) -> dict[str, Any]:
    if not food_xy:
        return {"object_id": None, "distance_mm": float("inf")}
    best_id, best = min(
        food_xy.items(),
        key=lambda item: (item[1][0] - x_mm) ** 2 + (item[1][1] - y_mm) ** 2,
    )
    return {
        "object_id": best_id,
        "distance_mm": float(np.hypot(best[0] - x_mm, best[1] - y_mm)),
    }


def _outcome(
    *,
    fly_ids: Sequence[str],
    initial: Sequence[tuple[float, float, float, float]],
    final: Sequence[tuple[float, float, float, float]],
    food_xy: dict[str, tuple[float, float]],
    onset_us: Sequence[int | None],
    decoders: Sequence[VisualLocomotorDecoder],
) -> dict[str, Any]:
    per_fly = []
    for index, fly_id in enumerate(fly_ids):
        x0, y0 = initial[index][0], initial[index][1]
        x1, y1 = final[index][0], final[index][1]
        start = _nearest(food_xy, x0, y0)
        end = _nearest(food_xy, x1, y1)
        per_fly.append(
            {
                "fly_id": fly_id,
                "displacement_mm": float(np.hypot(x1 - x0, y1 - y0)),
                "initial_nearest_food_mm": start["distance_mm"],
                "final_nearest_food_mm": end["distance_mm"],
                "closed_mm": start["distance_mm"] - end["distance_mm"],
                "initial_nearest_food": start["object_id"],
                "final_nearest_food": end["object_id"],
                "locomotion_onset_us": onset_us[index],
                "decoder_events": decoders[index].events,
            }
        )
    closed = [entry["closed_mm"] for entry in per_fly]
    return {
        "per_fly": per_fly,
        "flies_that_closed_on_a_food_object": sum(1 for value in closed if value > 0.0),
        "median_closed_mm": float(np.median(closed)) if closed else 0.0,
        "what_closed_mm_is": (
            "Distance to the nearest food object at the start minus distance to the "
            "nearest food object at the end. It is a descriptive measurement of this "
            "run, not a criterion: no threshold on it was preregistered and none is "
            "scored."
        ),
    }


__all__ = [
    "CONTROL_VARIANTS",
    "SwarmRecorder",
    "SwarmRunResult",
    "SwarmScenario",
    "run_swarm3d",
    "world_description",
    "zero_command",
]
