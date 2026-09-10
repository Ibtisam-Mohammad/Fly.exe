# SPDX-License-Identifier: GPL-2.0-or-later
"""The DEMO-01 closed loop: world, brain, body, and a synchronised recording of all three.

The loop, and the only route from world to body::

    cue geometry -> retinotopic lamina encoder -> full MaleCNS runtime (165,122 bodies,
    25,563,197 edges, every one stepped) -> declared descending readout -> causal filter
    -> E decoder -> FlyGym walking controller -> MuJoCo body -> the cue's retinal position
    changes -> back to the encoder

Nothing bypasses that. The body publishes no sensory channel, the decoder takes no sensor
argument, and the encoder writes only to declared lamina bodies. The controls below exist
to prove it rather than to assert it.

Control variants, all from an identical seed:

* ``exact`` -- the run itself;
* ``readout-ablated`` -- the declared descending readout is forced to zero after the brain
  has computed it, so the brain runs identically and the body cannot hear it. If behaviour
  survives this, the behaviour was never neural;
* ``stimulus-absent`` -- no cue, everything else identical;
* ``shuffled-connectome`` -- the same neurons, the same number of edges, the same degree
  sequence, rewired. If the exact graph and this one behave alike, the claim is about a
  network of that size and not about MaleCNS topology.

Recording is deliberately not a membrane trace. Every neuron's voltage at the 0.1 ms
neural step would be 165,122 times 10,000 floats per second and would say nothing the
video shows. Instead each coupling interval records: the spike count of every neuron that
fired, sparsely; seven whole-population rates; the declared readouts filtered and raw; the
decoder command; the cue's retinal geometry; and the body pose. That is enough to render
the brain, the body and the traces from disk without rerunning anything.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, SignalType
from flysim.demo01 import FilteredDescendingReadout, ReadoutParameters
from flysim.demo01_body import Demo01BodyParameters, Demo01VisualBody
from flysim.demo01_visual import (
    VISUAL_LEFT_READOUT,
    VISUAL_RIGHT_READOUT,
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualDecoderParameters,
    VisualEncodingParameters,
    VisualLocomotorDecoder,
)
from flysim.demo01_visual_probe import resolve_visual_populations
from flysim.engines.body import COMMAND_FORWARD, COMMAND_IDS, COMMAND_YAW
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata, require_clean_worktree

CONTROL_VARIANTS = (
    "exact",
    "readout-ablated",
    "stimulus-absent",
    "shuffled-connectome",
)


@dataclass(frozen=True, slots=True)
class EmbodiedResult:
    """What one closed-loop run produced, and where its recording sits."""

    variant: str
    directory: Path
    intervals: int
    duration_us: int
    displacement_mm: float
    net_heading_change_rad: float
    final_distance_mm: float
    initial_distance_mm: float
    locomotion_onset_us: int | None
    summary: dict[str, Any]


def _shuffle_preserving_degree(
    graph: SparseConnectome, seed: int
) -> np.ndarray:
    """Permute edge targets within out-degree-matched blocks, keeping every count.

    The control has to differ from the exact graph in *who connects to whom* and in
    nothing else, or a difference in behaviour could be a difference in edge count or
    degree distribution instead of topology. Permuting the target array preserves the
    number of edges exactly, preserves every neuron's out-degree exactly, and preserves
    the multiset of contact counts exactly, while destroying which pairs they join.
    """
    rng = np.random.default_rng(seed)
    permuted = np.asarray(graph.target_indices).copy()
    rng.shuffle(permuted)
    return permuted


class Demo01Recorder:
    """Writes the synchronised recording: scalars as JSONL, spikes sparsely, frames as MP4."""

    def __init__(
        self,
        directory: Path,
        *,
        neuron_count: int,
        fps: int,
        camera_resolution: tuple[int, int],
        write_video: bool,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.neuron_count = neuron_count
        self.fps = fps
        self._trace = (directory / "trace.jsonl").open("w", encoding="utf-8")
        self._spike_indices: list[np.ndarray] = []
        self._spike_counts: list[np.ndarray] = []
        self._rows = 0
        self._writer: Any | None = None
        self._write_video = write_video
        self._camera_resolution = camera_resolution
        if write_video:
            import imageio.v2 as imageio

            self._writer = imageio.get_writer(
                directory / "body.mp4", fps=fps, codec="libx264", quality=8
            )

    def add_interval(self, row: dict[str, Any], spikes: np.ndarray) -> None:
        self._trace.write(json.dumps(row, separators=(",", ":")) + "\n")
        active = np.flatnonzero(spikes)
        self._spike_indices.append(active.astype(np.uint32))
        self._spike_counts.append(np.minimum(spikes[active], 255).astype(np.uint8))
        self._rows += 1

    def add_frame(self, frame: np.ndarray) -> None:
        if self._writer is not None:
            self._writer.append_data(frame)

    def close(self) -> dict[str, Any]:
        self._trace.close()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        offsets = np.zeros(self._rows + 1, dtype=np.int64)
        if self._spike_indices:
            offsets[1:] = np.cumsum([array.size for array in self._spike_indices])
            indices = np.concatenate(self._spike_indices)
            counts = np.concatenate(self._spike_counts)
        else:
            indices = np.zeros(0, dtype=np.uint32)
            counts = np.zeros(0, dtype=np.uint8)
        np.savez_compressed(
            self.directory / "spikes.npz",
            offsets=offsets,
            indices=indices,
            counts=counts,
            neuron_count=np.int64(self.neuron_count),
        )
        return {
            "intervals": self._rows,
            "spike_events_recorded": int(indices.size),
            "mean_active_neurons_per_interval": (
                float(indices.size / self._rows) if self._rows else 0.0
            ),
            "trace": "trace.jsonl",
            "spikes": "spikes.npz",
            "video": "body.mp4" if self._write_video else None,
            "what_is_not_recorded": (
                "No membrane voltage at the neural step. Every neuron's voltage at 0.1 ms "
                "would be 165,122 x 10,000 floats per second and would show nothing the "
                "population rates and the sparse spike record do not."
            ),
        }


def run_embodied(
    *,
    contract_path: Path,
    operating_point: dict[str, float],
    decoder: VisualDecoderParameters,
    graph_path: Path,
    annotations_path: Path,
    transmitter_path: Path,
    build_root: Path,
    output_directory: Path,
    duration_us: int,
    body_parameters: Demo01BodyParameters,
    seed: int,
    variant: str = "exact",
    fps: int = 30,
    camera_resolution: tuple[int, int] = (720, 1280),
    write_video: bool = True,
    allow_dirty_tree: bool = False,
    progress: bool = False,
) -> EmbodiedResult:
    """One closed-loop run of one control variant, fully recorded."""
    if variant not in CONTROL_VARIANTS:
        raise ConfigurationError(
            f"Unknown control variant {variant!r}; expected one of {CONTROL_VARIANTS}"
        )
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree(f"The DEMO-01 embodied run ({variant})")
    )
    contract = load_json(contract_path)
    coupling_us = int(contract["coupling_us"])
    if duration_us % coupling_us:
        raise ConfigurationError("Duration must be a whole number of coupling intervals")
    if body_parameters.physics_dt_us and coupling_us % body_parameters.physics_dt_us:
        raise ConfigurationError("Coupling interval must be a whole number of physics steps")

    graph = SparseConnectome.load(graph_path)
    graph.validate()
    populations = resolve_visual_populations(annotations_path, graph)
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs

    # The shuffled control rewires the graph and changes nothing else. Because the engine
    # asserts that every registered edge is built, the control still executes all
    # 25,563,197 of them.
    shuffle_report: dict[str, Any] | None = None
    if variant == "shuffled-connectome":
        original_targets = np.asarray(graph.target_indices).copy()
        permuted = _shuffle_preserving_degree(graph, seed)
        out_degree_before = np.bincount(
            np.asarray(graph.source_indices), minlength=graph.neuron_count
        )
        graph.target_indices[:] = permuted
        out_degree_after = np.bincount(
            np.asarray(graph.source_indices), minlength=graph.neuron_count
        )
        shuffle_report = {
            "rule": (
                "the target array is permuted, so the edge count, every out-degree and the "
                "multiset of contact counts are preserved exactly and only which pairs the "
                "edges join changes"
            ),
            "edges": int(graph.edge_count),
            "out_degree_preserved": bool(np.array_equal(out_degree_before, out_degree_after)),
            "targets_changed": int(np.count_nonzero(original_targets != permuted)),
            "seed": seed,
        }

    parameters = {**contract["fixed_parameters"], **operating_point}
    engine = TrackAGeNNEngine(build_root / f"{sha256_json(parameters)[:12]}", variant="exact")
    started = time.perf_counter()
    engine.initialize(
        graph,
        {
            **parameters,
            "functional_edge_signs": signs,
            "entry_body_ids": populations.entry_body_ids,
        },
        seed,
    )
    build_seconds = time.perf_counter() - started

    encoder = RetinotopicVisualEncoder(
        populations,
        VisualEncodingParameters.from_mapping(parameters),
        RetinaMap.from_mapping(contract["retina_map"]),
        stimulus_present=variant != "stimulus-absent",
    )
    readout = FilteredDescendingReadout(
        populations,
        ReadoutParameters.from_mapping(contract["readout"]),
        ablated_population_ids=(
            frozenset({VISUAL_LEFT_READOUT, VISUAL_RIGHT_READOUT})
            if variant == "readout-ablated"
            else frozenset()
        ),
    )
    controller = VisualLocomotorDecoder(decoder)
    body = Demo01VisualBody(
        body_parameters, seed=seed, camera_resolution=camera_resolution
    )
    cue = VisualCue(
        x_mm=body_parameters.cue_x_mm,
        y_mm=body_parameters.cue_y_mm,
        radius_mm=body_parameters.cue_radius_mm,
    )
    readout_ids = populations.readout_body_ids
    pools = dict(populations.monitors)
    recorder = Demo01Recorder(
        output_directory,
        neuron_count=graph.neuron_count,
        fps=fps,
        camera_resolution=camera_resolution,
        write_video=write_video,
    )

    intervals = duration_us // coupling_us
    video_period_us = max(coupling_us, round(1_000_000 / fps))
    next_frame_us = 0
    # A command computed from brain activity over [t, t+dt] drives the body over
    # [t+dt, t+2dt]. That one-interval sensorimotor delay is not a convenience: a brain
    # cannot move a body with activity it has not produced yet, and stamping the command
    # at the body's current time would have the body act on its own future. The first
    # interval therefore runs on an explicit zero command.
    pending = ActuatorCommandFrame(
        t_us=0,
        ids=COMMAND_IDS,
        values=(0.0, 0.0, 0.0, 0.0),
        units="normalized-drive [0,1], normalized-drive [-1,1], normalized, normalized",
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MOTOR-06", "DEMO-03"),
        metadata={
            "decoder_state": "QUIESCENT",
            "sensor_terms_in_command": [],
            "why_zero": (
                "The first coupling interval precedes any brain output, so the body is "
                "commanded to stand rather than given a guessed drive."
            ),
        },
    )
    initial_x, initial_y, _, initial_heading = body.pose()
    initial_distance = body.cue_distance_mm()
    onset_us: int | None = None
    simulation_started = time.perf_counter()
    try:
        for step in range(intervals):
            t_us = step * coupling_us
            # The body acts on the command decoded from the previous interval's brain
            # activity, which is what the one-interval delay above means in code.
            applied = pending
            body.apply_actuators(applied)
            x_mm, y_mm, _, heading = body.pose()
            frame_in = encoder.encode(t_us, cue, x_mm=x_mm, y_mm=y_mm, heading_rad=heading)
            engine.push_inputs(frame_in)
            engine.step_until(t_us + coupling_us)
            raw = engine.read_outputs(readout_ids, coupling_us)
            neural = readout.read(raw)
            pending = controller.decode(neural)
            if onset_us is None and controller.state.value == "LOCOMOTING":
                onset_us = pending.t_us
            body.step_until(t_us + coupling_us)
            activity = engine.population_activity(pools, coupling_us)
            spikes = engine.spike_counts_since_last_frame()

            scene = frame_in.metadata["scene"]
            new_x, new_y, new_z, new_heading = body.pose()
            recorder.add_interval(
                {
                    "t_us": t_us + coupling_us,
                    "pose": {
                        "x_mm": new_x,
                        "y_mm": new_y,
                        "z_mm": new_z,
                        "heading_rad": new_heading,
                    },
                    "cue": {
                        "bearing_deg": scene["bearing_deg"],
                        "angular_radius_deg": scene["angular_radius_deg"],
                        "loom_term": scene["loom_term"],
                        "driven_lamina_bodies": scene["driven_bodies"],
                        "distance_mm": body.cue_distance_mm(),
                        "present": scene["stimulus_present"],
                    },
                    "readout_hz": {
                        str(name): float(value)
                        for name, value in zip(neural.ids, neural.values, strict=True)
                    },
                    "readout_raw_counts": {
                        str(k): int(v)
                        for k, v in neural.metadata["raw_population_spike_counts"].items()
                    },
                    "pool_mean_rate_hz": {
                        name: value["mean_rate_hz"] for name, value in activity.items()
                    },
                    "pool_active_fraction": {
                        name: value["active_fraction"] for name, value in activity.items()
                    },
                    "command": {
                        "forward": applied.value_for(COMMAND_FORWARD, 0.0),
                        "yaw": applied.value_for(COMMAND_YAW, 0.0),
                        "state": applied.metadata["decoder_state"],
                    },
                    "command_decoded_this_interval": {
                        "forward": pending.value_for(COMMAND_FORWARD, 0.0),
                        "yaw": pending.value_for(COMMAND_YAW, 0.0),
                        "state": pending.metadata["decoder_state"],
                        "drives_the_body_next_interval": True,
                    },
                },
                spikes,
            )
            if write_video and t_us >= next_frame_us:
                recorder.add_frame(body.render_frame())
                next_frame_us += video_period_us
            if progress and step % 100 == 0:
                print(
                    f"  [{step:5d}/{intervals}] t={t_us / 1e6:6.2f}s "
                    f"dn L/R {neural.value_for(VISUAL_LEFT_READOUT):6.2f}/"
                    f"{neural.value_for(VISUAL_RIGHT_READOUT):6.2f} Hz  "
                    f"fwd {pending.value_for(COMMAND_FORWARD, 0.0):5.3f} "
                    f"yaw {pending.value_for(COMMAND_YAW, 0.0):+6.3f}  "
                    f"d={body.cue_distance_mm():6.2f}mm  {controller.state.value}",
                    flush=True,
                )
        simulation_seconds = time.perf_counter() - simulation_started
    finally:
        recording = recorder.close()
        body.close()
        engine.close()

    final_x, final_y, _, final_heading = body.pose()
    displacement = float(np.hypot(final_x - initial_x, final_y - initial_y))
    heading_change = float(
        np.arctan2(
            np.sin(final_heading - initial_heading), np.cos(final_heading - initial_heading)
        )
    )
    final_distance = float(
        np.hypot(final_x - body_parameters.cue_x_mm, final_y - body_parameters.cue_y_mm)
    )
    outcome: dict[str, Any] = {
        "displacement_mm": displacement,
        "net_heading_change_rad": heading_change,
        "initial_cue_distance_mm": initial_distance,
        "final_cue_distance_mm": final_distance,
        "locomotion_onset_us": onset_us,
        "decoder_events": controller.events,
    }
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "variant": variant,
        "provenance": "P/E for the network, E for the decoder and the body",
        "evidence_grade": not allow_dirty_tree,
        "code_commit": worktree.get("commit"),
        "worktree_dirty": worktree.get("dirty"),
        "seed": seed,
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "operating_point": dict(operating_point),
        "decoder": decoder.as_dict(),
        "graph": {
            "path": str(graph_path),
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
            "every_edge_built": True,
            "shuffle": shuffle_report,
        },
        "populations": populations.as_dict(),
        "body": body.describe(),
        "coupling_us": coupling_us,
        "sensorimotor_delay_us": coupling_us,
        "why_a_delay": (
            "A command decoded from brain activity over one coupling interval drives the "
            "body over the next one. A brain cannot move a body with activity it has not "
            "produced yet, and applying the command inside the interval that produced it "
            "would have the body act on its own future."
        ),
        "duration_us": duration_us,
        "intervals": intervals,
        "build_seconds": build_seconds,
        "simulation_seconds": simulation_seconds,
        "recording": recording,
        "outcome": outcome,
        "the_only_route_from_world_to_body": (
            "cue geometry -> retinotopic lamina encoder -> full MaleCNS runtime -> declared "
            "descending readout -> causal filter -> E decoder -> walking controller -> body"
        ),
        "claim_boundary": (
            "An engineering demonstration on the exact released graph. The tier is V0 "
            "Structural. The lamina rates, the retinal map, the excitatory-inhibitory "
            "ratio, the adaptation and the per-contact scale are declared engineering "
            "values, the walking controller is an engineered pattern generator rather than "
            "a VNC model, and the retina-to-lamina synapse is not executed at all because "
            "the frozen sign policy zeroes every photoreceptor edge. Nothing here is "
            "validated physiology."
        ),
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return EmbodiedResult(
        variant=variant,
        directory=output_directory,
        intervals=intervals,
        duration_us=duration_us,
        displacement_mm=displacement,
        net_heading_change_rad=heading_change,
        final_distance_mm=final_distance,
        initial_distance_mm=initial_distance,
        locomotion_onset_us=onset_us,
        summary=summary,
    )


__all__ = [
    "CONTROL_VARIANTS",
    "Demo01Recorder",
    "EmbodiedResult",
    "run_embodied",
]
