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

import hashlib
import json
import math
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
    ablate_readout_frame,
    entry_channels,
)
from flysim.engines.body import (
    BEHAVIOUR_COMMAND_IDS,
    COMMAND_GROOM,
    COMMAND_JUMP,
    COMMAND_PROBOSCIS,
    COMMAND_WING_DEPRESSION,
)
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
    "concentration-0.25",
    "concentration-0.5",
    "concentration-0.75",
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
class ApproachingObject:
    """An object on a script the brain cannot influence.

    Escape is open loop on purpose. The encoder's looming term is angular SIZE, not
    expansion rate, so on a walking fly the approach would be self-generated and both the
    stimulus-absent and readout-ablated controls would fail to expose it: the fly really
    would have caused its own stimulus. So the object moves and the fly does not.
    """

    radius_mm: float = 2.5
    start_distance_mm: float = 30.0
    final_distance_mm: float = 4.0
    approach_start_us: int = 1_500_000
    approach_end_us: int = 3_500_000
    bearing_deg: float = 35.0

    def distance_at(self, t_us: int, *, static: bool) -> float:
        if static:
            # The matched-size control: the same angular size from t=0, no expansion.
            return self.final_distance_mm
        if t_us <= self.approach_start_us:
            return self.start_distance_mm
        if t_us >= self.approach_end_us:
            return self.final_distance_mm
        span = self.approach_end_us - self.approach_start_us
        fraction = (t_us - self.approach_start_us) / span
        return self.start_distance_mm + fraction * (
            self.final_distance_mm - self.start_distance_mm
        )

    def position(
        self, t_us: int, *, x_mm: float, y_mm: float, heading_rad: float, static: bool
    ) -> tuple[float, float]:
        distance = self.distance_at(t_us, static=static)
        angle = heading_rad + math.radians(self.bearing_deg)
        return x_mm + distance * math.cos(angle), y_mm + distance * math.sin(angle)

    def as_dict(self) -> dict[str, Any]:
        return {
            "radius_mm": self.radius_mm,
            "start_distance_mm": self.start_distance_mm,
            "final_distance_mm": self.final_distance_mm,
            "approach_start_us": self.approach_start_us,
            "approach_end_us": self.approach_end_us,
            "bearing_deg": self.bearing_deg,
            "provenance": "E",
            "the_brain_cannot_influence_this": (
                "The locomotor drives are held identically zero for the whole run, so the "
                "object's approach is a script and not a consequence of the fly's motion."
            ),
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



def compiled_kernel_fingerprint(build_root: Path, identity: str) -> dict[str, Any]:
    """Hash the shared object that was actually loaded, not the key it was filed under.

    The build cache is keyed on parameters, so two runs with the same key are *assumed* to
    have executed the same kernel. They are not guaranteed to: a build interrupted
    mid-link leaves a file that the key still points at. This session hit the loud version
    of that -- three truncated librunner.so files after a WSL crash, each failing with
    "file too short" -- and a silent version is the same failure without the error, giving
    deterministic wrong answers under correct-looking provenance.

    Hashing the object closes it after the fact: two runs claiming one build key and
    carrying different kernel hashes did not run the same code, whatever their summaries
    say.
    """
    directory = build_root / identity
    for candidate in sorted(directory.rglob("librunner.so")):
        payload = candidate.read_bytes()
        return {
            "path": str(candidate),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    return {"path": str(directory), "sha256": None, "bytes": 0,
            "note": "no librunner.so found under the build key"}


def _sha256_file(path: Path) -> str:
    """The recorded bytes of a file, so a later reader can prove it is the same file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
    atlas: SensoryAtlas,
    behaviour: str,
    *,
    variant: str,
    parameters: dict[str, Any],
    sensory_delay_us: int = 0,
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
        transducer = TRANSDUCERS[key.modality]
        if key.modality == "tarsal-taste" and "taste_max_rate_hz" in parameters:
            transducer = SaturatingTransducer(
                max_rate_hz=float(parameters["taste_max_rate_hz"]),
                half_saturation=transducer.half_saturation,
                threshold=transducer.threshold,
            )
        elif (
            key.modality == "antennal-jo-f-grooming"
            and "antennal_max_rate_hz" in parameters
        ):
            transducer = SaturatingTransducer(
                max_rate_hz=float(parameters["antennal_max_rate_hz"]),
                half_saturation=transducer.half_saturation,
                threshold=transducer.threshold,
            )
        bindings.append(
            ChannelBinding(
                key=key,
                sensor_id=sensor,
                transducer=transducer,
                delay_us=sensory_delay_us,
                enabled=not silent,
                kind=atlas.modality_kind.get(key.modality, "real"),
                why=f"{behaviour} entry",
            )
        )
    return tuple(bindings)


def _controller_only_values(behaviour: str, active: bool) -> dict[str, float]:
    """A fixed body command, deliberately independent of sensors and a graph."""
    values = {name: 0.0 for name in BEHAVIOUR_COMMAND_IDS}
    if not active:
        return values
    if behaviour == "grooming":
        values[COMMAND_GROOM] = 1.0
    elif behaviour == "feeding":
        values[COMMAND_PROBOSCIS] = 1.0
    elif behaviour == "escape":
        values[COMMAND_JUMP] = 1.0
        values[COMMAND_WING_DEPRESSION] = 1.0
    else:  # guarded by run_behaviour, retained here as a fail-closed boundary
        raise ConfigurationError(f"Unknown controller-only behaviour: {behaviour}")
    return values


def _run_controller_only(
    *,
    behaviour: str,
    contract: dict[str, Any],
    verification: dict[str, Any],
    output_directory: Path,
    body_parameters: BehaviourBodyParameters,
    trajectory_path: Path | None,
    decoder: DecoderParameters,
    duration_us: int,
    seed: int,
    coupling_us: int,
    progress: bool,
) -> BehaviourResult:
    """Record the body envelope under a fixed command with no graph or neural engine."""
    body = BehaviourBody(
        parameters=replace(
            body_parameters,
            antennal_stimulus_side="none",
            sucrose_x_mm=1e6,
        ),
        behaviour=behaviour,
        seed=seed,
        trajectory_path=trajectory_path,
    )
    recorder = Recorder(output_directory, neuron_count=0)
    intervals = duration_us // coupling_us
    onset_us = decoder.quiescent_us
    started = time.perf_counter()
    try:
        for step in range(intervals):
            t_us = step * coupling_us
            active = decoder.quiescent_us <= t_us < (
                decoder.quiescent_us + decoder.action_us
            )
            values = _controller_only_values(behaviour, active)
            command = ActuatorCommandFrame(
                t_us=t_us,
                ids=BEHAVIOUR_COMMAND_IDS,
                values=tuple(values[name] for name in BEHAVIOUR_COMMAND_IDS),
                units=", ".join("normalized" for _ in BEHAVIOUR_COMMAND_IDS),
                signal_type=SignalType.ACTUATOR_COMMAND,
                provenance="E",
                assumption_ids=("MOTOR-03", "MOTOR-06", "DEMO-02"),
                metadata={
                    "state": "ACTING" if active else "QUIESCENT",
                    "controller_only": True,
                    "graph_attached": False,
                },
            )
            body.apply_actuators(command)
            sensors = body.sample_sensors()
            body.step_until(t_us + coupling_us)
            x_mm, y_mm, z_mm, heading = body.pose()
            recorder.add_interval(
                {
                    "t_us": t_us + coupling_us,
                    "t_start_us": t_us,
                    "t_sensors_us": t_us,
                    "t_neural_us": None,
                    "t_body_us": t_us + coupling_us,
                    "pose": {
                        "x_mm": x_mm,
                        "y_mm": y_mm,
                        "z_mm": z_mm,
                        "heading_rad": heading,
                    },
                    "sensors": dict(zip(sensors.ids, sensors.values, strict=True)),
                    "channel_rate_hz": {},
                    "scene": {},
                    "entry_bodies_driven": 0,
                    "readout_hz": {},
                    "readout_raw_counts": {},
                    "command": {**values, "state": command.metadata["state"]},
                    "body": body.metrics(),
                },
                np.zeros(0, dtype=np.int64),
            )
            recorder.add_pose(t_us + coupling_us, body.qpos())
            if progress and step % 50 == 0:
                print(f"  {behaviour}/controller-only {step}/{intervals}", flush=True)
        recording = recorder.close()
        first = recorder.rows[0]["pose"] if recorder.rows else {"x_mm": 0.0, "y_mm": 0.0}
        last = recorder.rows[-1]["pose"] if recorder.rows else first
        displacement = float(
            np.hypot(last["x_mm"] - first["x_mm"], last["y_mm"] - first["y_mm"])
        )
        summary = {
            "behaviour": behaviour,
            "variant": "controller-only",
            "code_commit": verification["commit"],
            "worktree_dirty": verification["dirty"],
            "verification": verification.get("verification", {}),
            "seed": seed,
            "experiment_id": contract["experiment_id"],
            "experiment_sha256": sha256_json(contract),
            "decoder": decoder.as_dict(),
            "graph": {"attached": False, "neurons": 0, "edges": 0},
            "model_identity": None,
            "decoded_population_names": [],
            "populations": {},
            "sensory_bus": {"attached": False},
            "body": body.describe(),
            "station_keeping": body.station_keeping(),
            "takeoff": body.takeoff(),
            "coupling_us": coupling_us,
            "duration_us": duration_us,
            "intervals": intervals,
            "build_seconds": 0.0,
            "simulation_seconds": time.perf_counter() - started,
            "recording": recording,
            "trace_rows": len(recorder.rows),
            "trace_sha256": _sha256_file(output_directory / "trace.jsonl"),
            "outcome": {
                "displacement_mm": displacement,
                "onset_us": onset_us,
                "decoder_events": [
                    {"t_us": onset_us, "state": "ACTING", "source": "fixed command"}
                ],
                "reached_acting": True,
            },
            "claim_boundary": contract["claim_boundary"],
            "control_truth": (
                "Fixed command to the body; no connectome, neural engine, sensory encoder "
                "or neural decoder was attached."
            ),
        }
        (output_directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return BehaviourResult(
            behaviour=behaviour,
            variant="controller-only",
            directory=output_directory,
            intervals=intervals,
            duration_us=duration_us,
            displacement_mm=displacement,
            onset_us=onset_us,
            summary=summary,
        )
    finally:
        body.close()


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
    # NUM-01 registers a 2000 us sensory delay realised as ceil(2000/coupling)*coupling,
    # and DEMO-02 bound every channel at zero, so the loop realised a motor delay only
    # while the summary reported `sensorimotor_delay_us` as though both legs were there.
    # The delay is now a contract-declared quantity. Contracts that predate this and say
    # "the declared sensorimotor delay is one interval" carry no key, keep zero, and stay
    # true; new contracts declare what they want and the summary records what was realised
    # on both legs separately, so the two can never silently disagree again.
    sensory_delay_us = int(contract["fixed_parameters"].get("sensory_delay_us", 0))
    if sensory_delay_us % coupling_us:
        raise ConfigurationError(
            f"A {sensory_delay_us} us sensory delay is not a whole number of "
            f"{coupling_us} us coupling intervals. NUM-01 quantises it to "
            "ceil(registered / coupling) * coupling; declare the realised value."
        )

    if variant == "controller-only":
        return _run_controller_only(
            behaviour=behaviour,
            contract=contract,
            verification=verification,
            output_directory=output_directory,
            body_parameters=body_parameters,
            trajectory_path=trajectory_path,
            decoder=decoder,
            duration_us=duration_us,
            seed=seed,
            coupling_us=coupling_us,
            progress=progress,
        )

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

    # The build key covers the parameters AND the graph's actual wiring. Keying it on the
    # variant *name* instead would be both too coarse and too fine: readout-ablated zeroes
    # a readout after the brain has computed it and does not touch the network, so it must
    # share a kernel with the exact run, while shuffled-connectome permutes the targets and
    # must not. DEMO-01's runner keyed on neither and let two different topologies carry the
    # same model identity into their artifacts.
    wiring = hashlib.sha256(
        np.asarray(graph.target_indices, dtype=np.int64).tobytes()
    ).hexdigest()[:12]
    identity = sha256_json({
        **{
            k: v for k, v in engine_parameters.items()
            if k not in {"functional_edge_signs", "entry_body_ids"}
        },
        "wiring": wiring,
        # The seed MUST be in the build key. GeNN bakes it into the generated code, so
        # three seeds produced three different librunner.so hashes under one key, and a
        # later run reusing that key loads whichever kernel was compiled last. That is not
        # hypothetical: it is the only explanation that survived for a pair of escape runs
        # that reported a different trajectory under byte-identical recorded provenance,
        # twice, and then stopped once other runs had rewritten the cache.
        "seed": seed,
    })[:12]
    engine = TrackAGeNNEngine(build_root / identity, variant="exact")
    build_started = time.perf_counter()
    engine.initialize(graph, engine_parameters, seed)
    build_seconds = time.perf_counter() - build_started

    # Vision enters at the lamina through DEMO-01's frozen encoder, unchanged. It is the
    # only sensory entry in this project that has passed a causal contract, and the
    # photoreceptors upstream of it carry zero live edges.
    visual_encoder = None
    cue_object: ApproachingObject | None = None
    if behaviour == "escape":
        from flysim.demo01_visual import (
            RetinaMap,
            RetinotopicVisualEncoder,
            VisualCue,
            VisualEncodingParameters,
        )
        from flysim.demo01_visual_probe import resolve_visual_populations

        retina = parameters.get("retina_map")
        if not retina:
            raise ConfigurationError(
                "Escape needs DEMO-01's frozen retina map; refusing to invent one."
            )
        visual_encoder = RetinotopicVisualEncoder(
            resolve_visual_populations(annotations_path, graph),
            VisualEncodingParameters.from_mapping(parameters),
            RetinaMap.from_mapping(retina),
            stimulus_present=variant not in {"stimulus-absent", "controller-only"},
        )
        cue_object = ApproachingObject()

    bindings = _bindings(
        atlas,
        behaviour,
        variant=variant,
        parameters=parameters,
        sensory_delay_us=sensory_delay_us,
    )
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
            suppress_groom_replay=variant == "suppress-groom-replay",
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
    # AGENTS.md section 10 requires a command replay: the exact run's recorded commands
    # driven into the body with the graph playing no part. If the body moves the same way,
    # the motion followed from the commands and nothing else was quietly contributing.
    replayed_commands: list[dict[str, float]] | None = None
    if variant == "command-replay":
        source = output_directory.parent / "exact" / "trace.jsonl"
        if not source.exists():
            raise ConfigurationError(
                f"command-replay needs the exact run's trace at {source}, and it is not "
                "recorded. Run the exact variant first."
            )
        replayed_commands = [
            {k: float(v) for k, v in json.loads(line)["command"].items()
             if k != "state"}
            for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    if variant == "entry-swapped":
        raise ConfigurationError(
            "entry-swapped is named in demo02-grooming-v1 and is not implemented. It must "
            "drive the same readout from the head-bristle tactile population at a MATCHED "
            "total input rate, and matching that rate is a measurement nobody has made. "
            "Until then this variant was not refused and not implemented either: it sat "
            "in the variant list with no branch anywhere, so running it executed the "
            "exact run under a control's name and would have recorded a control that "
            "never happened."
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
            if replayed_commands is not None:
                # Row k of the exact run's trace is the command the exact run APPLIED at
                # step k. Routing it through `pending` applied it at step k+1, so the
                # replay ran one 15 ms interval behind the run it was replaying and the
                # control silently tested a shifted command sequence. Measured on the
                # recorded escape pair: the first nonzero command is row 234 in exact and
                # row 235 in the replay.
                recorded = replayed_commands[min(step, len(replayed_commands) - 1)]
                applied = ActuatorCommandFrame(
                    t_us=t_us,
                    ids=BEHAVIOUR_COMMAND_IDS,
                    values=tuple(
                        recorded.get(name, 0.0) for name in BEHAVIOUR_COMMAND_IDS
                    ),
                    units=applied.units,
                    signal_type=applied.signal_type,
                    provenance="E",
                    assumption_ids=applied.assumption_ids,
                    metadata={
                        "state": "REPLAY",
                        "replayed_from": str(output_directory.parent / "exact"),
                        "replayed_row": min(step, len(replayed_commands) - 1),
                        "the_graph_did_not_drive_this": True,
                    },
                )
            # The two effector controls the escape contract names. They gate the command
            # on its way to the body and touch nothing upstream, so the network, the
            # stimulus and the decoder are identical to the exact run and the only
            # difference is which effector is allowed to move.
            if variant in {"jump-only", "wing-only"}:
                silenced = (
                    COMMAND_WING_DEPRESSION if variant == "jump-only" else COMMAND_JUMP
                )
                applied = ActuatorCommandFrame(
                    t_us=applied.t_us,
                    ids=applied.ids,
                    values=tuple(
                        0.0 if name == silenced else value
                        for name, value in zip(applied.ids, applied.values, strict=True)
                    ),
                    units=applied.units,
                    signal_type=applied.signal_type,
                    provenance=applied.provenance,
                    assumption_ids=applied.assumption_ids,
                    metadata={**applied.metadata, "silenced_command": silenced},
                )
            body.apply_actuators(applied)
            sensors = body.sample_sensors()
            extra: dict[int, float] | None = None
            scene: dict[str, Any] = {}
            if visual_encoder is not None and cue_object is not None:
                px, py, _, heading = body.pose()
                cue_x, cue_y = cue_object.position(
                    t_us,
                    x_mm=px,
                    y_mm=py,
                    heading_rad=heading,
                    static=variant == "matched-size-static",
                )
                cue = VisualCue(x_mm=cue_x, y_mm=cue_y, radius_mm=cue_object.radius_mm)
                extra, scene = visual_encoder.rates_for(
                    cue, x_mm=px, y_mm=py, heading_rad=heading
                )
            frame_in = bus.encode(t_us, sensors, extra_rates=extra)
            engine.push_inputs(frame_in)
            engine.step_until(t_us + coupling_us)
            raw = engine.read_outputs(readout_ids, coupling_us)
            neural = ablate_readout_frame(
                readout.read(raw),
                frozenset(DECODED[behaviour]) if variant == "readout-ablated"
                else frozenset(),
            )
            # The graph runs and its decode is recorded whatever the variant. Under
            # command-replay it is simply never applied: `applied` was overwritten from
            # the recorded trace at the top of this interval.
            pending = controller.decode(neural)
            if onset_us is None and controller.state.value == "ACTING":
                onset_us = pending.t_us
            body.step_until(t_us + coupling_us)
            x_mm, y_mm, z_mm, heading = body.pose()
            metrics = body.metrics()
            recorder.add_interval(
                {
                    # One row spans one coupling interval and its parts are sampled at
                    # different ends of it. `t_us` is the row's close and every criterion
                    # in demo02_acceptance reads that; the three fields beside it say
                    # which quantity belongs to which instant, so a latency scored off
                    # this row can never silently compare a start-of-interval sensor
                    # against an end-of-interval body state.
                    "t_us": t_us + coupling_us,
                    "t_start_us": t_us,
                    "t_sensors_us": t_us,
                    "t_neural_us": t_us + coupling_us,
                    "t_body_us": t_us + coupling_us,
                    "pose": {"x_mm": x_mm, "y_mm": y_mm, "z_mm": z_mm,
                             "heading_rad": heading},
                    "sensors": dict(zip(sensors.ids, sensors.values, strict=True)),
                    "channel_rate_hz": frame_in.metadata["channel_rate_hz"],
                    "scene": scene,
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
            "wiring_sha256_12": wiring,
            "build_key": identity,
            "compiled_kernel": compiled_kernel_fingerprint(build_root, identity),
            # Keep the populations monitored by the recorder separate from the subset
            # the decoder is allowed to read.  The first corrected feeding contract
            # required this distinction but the run summary recorded only the former,
            # making its own F6 mapping criterion impossible to score.
            "decoded_population_names": list(DECODED[behaviour]),
            "populations": populations.as_dict(),
            "sensory_bus": bus.describe(),
            "approaching_object": cue_object.as_dict() if cue_object else None,
            "body": body.describe(),
            "station_keeping": body.station_keeping(),
            "takeoff": body.takeoff(),
            "coupling_us": coupling_us,
            "delays": {
                "realised_sensory_delay_us": sensory_delay_us,
                "realised_motor_delay_us": coupling_us,
                "realised_sensorimotor_delay_us": sensory_delay_us + coupling_us,
                "num01_registered_sensory_delay_us": 2000,
                "num01_registered_motor_delay_us": 2000,
                "num01_effective_sensory_delay_us": 15000,
                "num01_effective_motor_delay_us": 15000,
                "deviates_from_num01": sensory_delay_us != 15000,
                "why_the_motor_leg_is_one_interval": (
                    "a command decoded at the close of interval k is applied at the "
                    "start of interval k+1, which is one coupling interval by "
                    "construction and is not configurable"
                ),
                "why_this_block_replaced_a_single_number": (
                    "the summary previously reported sensorimotor_delay_us as one "
                    "coupling interval without saying which leg supplied it, while "
                    "NUM-01 registers both legs; the two disagreed and nothing said so"
                ),
            },
            "duration_us": duration_us,
            "intervals": intervals,
            "build_seconds": build_seconds,
            "simulation_seconds": simulation_seconds,
            "recording": recording,
            # The trace is truncated when the recorder opens and the summary is written
            # only on success, so a crashed run leaves a short trace beside an old
            # summary. These two let the evaluator refuse that pair instead of scoring
            # a stale verdict against a partial recording.
            "trace_rows": len(recorder.rows),
            "trace_sha256": _sha256_file(output_directory / "trace.jsonl"),
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
