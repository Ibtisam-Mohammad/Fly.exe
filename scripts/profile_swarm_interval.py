"""Partition one swarm coupling interval into its phases, on the real configuration.

Run this before believing anything in the documentation about where the wall clock goes. It
builds the same engine the showcase builds -- same contract, same frozen operating point,
same seed, same fly count, therefore the same build key and the same compiled kernel -- and
times each phase of the loop that `flysim.swarm3d_run` executes.

Two details make the attribution honest rather than plausible.

`step_time()` only enqueues work, so timing the step loop by itself measures submission and
charges the kernels to whichever later call happens to synchronise. The loop is therefore
timed in two parts: the enqueue, and an explicit device barrier after it. On this machine
that split is 2.9 ms against 497 ms, which is what establishes that the stepping phase is
device execution and not launch overhead.

`nvidia-smi` utilisation is not used and should not be trusted here: under WSL2's
paravirtualised driver it reported 7-11% for a phase the barrier proves the device is busy
through.

Usage, from the repository root inside the production environment:

    PYTHONPATH=src python scripts/profile_swarm_interval.py

`PROFILE_INTERVALS` and `PROFILE_WARMUP` override the measured and discarded interval counts.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.config import sha256_json  # noqa: E402
from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.datasets import default_data_root  # noqa: E402
from flysim.demo01 import FilteredDescendingReadout, ReadoutParameters  # noqa: E402
from flysim.demo01_visual import (  # noqa: E402
    RetinaMap,
    VisualEncodingParameters,
    VisualLocomotorDecoder,
)
from flysim.demo01_visual_probe import resolve_visual_populations  # noqa: E402
from flysim.engines.genn import TrackAGeNNEngine  # noqa: E402
from flysim.errors import ReadinessError  # noqa: E402
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs  # noqa: E402
from flysim.swarm3d import SwarmWorld  # noqa: E402
from flysim.swarm3d_run import SwarmScenario  # noqa: E402
from flysim.swarm3d_vision import (  # noqa: E402
    MultiObjectLaminaEncoder,
    visible_objects_for,
)

INTERVALS = int(os.environ.get("PROFILE_INTERVALS", "12"))
WARMUP = int(os.environ.get("PROFILE_WARMUP", "3"))


class Phases:
    """Wall time per named phase, summed over the measured intervals."""

    def __init__(self) -> None:
        self.totals: dict[str, float] = {}

    def add(self, name: str, seconds: float) -> None:
        self.totals[name] = self.totals.get(name, 0.0) + seconds

    def report(self, intervals: int) -> float:
        total = sum(self.totals.values())
        print(f"\n{'phase':<34} {'ms/interval':>12} {'share':>8}")
        print("-" * 56)
        for name, seconds in sorted(self.totals.items(), key=lambda kv: -kv[1]):
            print(
                f"{name:<34} {seconds / intervals * 1000.0:12.1f} "
                f"{seconds / total * 100:7.1f}%"
            )
        print("-" * 56)
        print(f"{'measured total':<34} {total / intervals * 1000.0:12.1f} {100.0:7.1f}%")
        return total


def main() -> None:
    root = default_data_root()
    contract_path = REPO / "configs/experiments/demo01-visual-operating-point-v1.json"
    scenario = SwarmScenario.load(REPO / "configs/scenarios/swarm3d-showcase.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    coupling_us = int(contract["coupling_us"])

    search_artifact = root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    if not search_artifact.is_file():
        raise ReadinessError(
            f"The frozen operating point is missing: {search_artifact}. This profile has to "
            "run the operating point the showcase ran, not one of its own."
        )
    operating_point = json.loads(search_artifact.read_text(encoding="utf-8"))["selected"]
    parameters = {**contract["fixed_parameters"], **operating_point}
    seed = 1
    fly_count = len(scenario.flies)
    steps_per_interval = coupling_us // int(parameters["neural_dt_us"])

    print(
        f"flies {fly_count}   coupling {coupling_us} us   "
        f"neural dt {parameters['neural_dt_us']} us   steps/interval {steps_per_interval}"
    )

    graph = SparseConnectome.load(root / "derived/male-cns-v1.0/graph")
    graph.validate()
    populations = resolve_visual_populations(
        root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather",
        graph,
    )
    signs = build_shiu_regression_signs(
        graph,
        root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather",
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs

    wiring_digest = hashlib.sha256(
        np.asarray(graph.target_indices, dtype=np.int64).tobytes()
    ).hexdigest()[:12]
    build_key = sha256_json(
        {**parameters, "wiring": wiring_digest, "seed": seed, "batch": fly_count}
    )[:12]
    build_root = root / "build/swarm3d"
    print(f"build key    {build_key}   cached {(build_root / build_key).is_dir()}")

    engine = TrackAGeNNEngine(
        build_root / build_key,
        variant="exact",
        batch_size=fly_count,
        batch_labels=tuple(fly.fly_id for fly in scenario.flies),
    )
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
    print(f"engine ready in {time.perf_counter() - started:.1f} s")

    encoder = MultiObjectLaminaEncoder(
        populations,
        VisualEncodingParameters.from_mapping(parameters),
        RetinaMap.from_mapping(contract["retina_map"]),
        stimulus_present=True,
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

    # Pulling the smallest population's counter is the cheapest available device barrier:
    # a few microseconds of transfer, and the queue has to drain before it returns.
    smallest = min(
        engine._populations,
        key=lambda pop: int(np.asarray(pop.vars["SpikeCount"].view).size),
    )
    barrier = smallest.vars["SpikeCount"]

    phases = Phases()
    t_us = 0
    try:
        for index in range(WARMUP + INTERVALS):
            recording = index >= WARMUP
            mark = time.perf_counter()
            poses = world.poses()
            frames = [
                encoder.encode(
                    t_us,
                    visible_objects_for(
                        fly,
                        poses,
                        scenario.objects,
                        fly_visual_radius_mm=scenario.arena.fly_visual_radius_mm,
                        include_other_flies=scenario.include_other_flies,
                    ),
                    x_mm=poses[fly][0],
                    y_mm=poses[fly][1],
                    heading_rad=poses[fly][3],
                )
                for fly in range(fly_count)
            ]
            if recording:
                phases.add("encode (host, all flies)", time.perf_counter() - mark)

            mark = time.perf_counter()
            engine.push_batch_inputs(frames)
            barrier.pull_from_device()
            if recording:
                phases.add("push_batch_inputs + barrier", time.perf_counter() - mark)

            mark = time.perf_counter()
            engine.step_until(t_us + coupling_us)
            enqueue_seconds = time.perf_counter() - mark
            mark = time.perf_counter()
            barrier.pull_from_device()
            barrier_seconds = time.perf_counter() - mark
            if recording:
                phases.add(
                    f"{steps_per_interval} x step_time (enqueue)", enqueue_seconds
                )
                phases.add("device barrier after the steps", barrier_seconds)

            mark = time.perf_counter()
            raw_frames = engine.read_batch_outputs(readout_ids, coupling_us)
            if recording:
                phases.add("read_batch_outputs (pull 1)", time.perf_counter() - mark)

            mark = time.perf_counter()
            for fly in range(fly_count):
                decoders[fly].decode(readouts[fly].read(raw_frames[fly]))
            if recording:
                phases.add("readout + decode (host)", time.perf_counter() - mark)

            mark = time.perf_counter()
            world.step_until(t_us + coupling_us)
            if recording:
                phases.add("MuJoCo physics, all bodies", time.perf_counter() - mark)

            mark = time.perf_counter()
            engine.population_activity_batch(pools, coupling_us)
            if recording:
                phases.add("population_activity (pull 2)", time.perf_counter() - mark)

            mark = time.perf_counter()
            engine.spike_counts_since_last_frame_batch()
            if recording:
                phases.add("spike_counts (pull 3)", time.perf_counter() - mark)

            t_us += coupling_us

        phases.report(INTERVALS)

        step_seconds = (
            phases.totals[f"{steps_per_interval} x step_time (enqueue)"]
            + phases.totals["device barrier after the steps"]
        ) / INTERVALS
        per_step_us = step_seconds / steps_per_interval * 1e6
        states = fly_count * graph.neuron_count
        print(
            f"\nper neural step: {per_step_us:.0f} us for {states:,} neuron states "
            f"= {states / (per_step_us * 1e-6) / 1e6:.0f} M updates/s"
        )
    finally:
        world.close()


if __name__ == "__main__":
    main()
