# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only operating-point search for DEMO-01. No body, no trajectory, no target.

This module exists to keep the two tuning problems apart. The predecessor demonstration
chose its parameters while watching whether the fly reached the food, which means a bad
network and a compensating decoder could not be told apart. Here the network operating
point is searched against four criteria that are all measurable with no body attached:

* **C1 stability** -- descending drive at rest below a registered ceiling, mean rate well
  under the refractory limit, and a declared fraction of the descending pool active but
  not all of it;
* **C2 cue responsiveness** -- the odour cue must raise descending drive above baseline;
* **C3 bilateral selectivity that reverses** -- the left-right descending asymmetry must
  change sign when the cue moves to the other side. A fixed asymmetry satisfies a
  one-sided test and carries no cue information, so reversal is required rather than
  magnitude;
* **C4 recovery** -- drive must fall back toward baseline once the cue is removed.

The probe drives the full graph from a scripted pose sequence through exactly the
registered SENS-03 odour field the embodied run will use, so the network sees the same
input statistics without any closed loop. Nothing here can read a distance, a
displacement or a success flag, and `score_operating_point` refuses to accept one.

Every searched value is P/E engineering calibration. Finding an operating point awards no
tier and validates nothing.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import NeuralInputFrame, SignalType
from flysim.demo01 import (
    Demo01Populations,
    FilteredDescendingReadout,
    OperatingPointCriteria,
    OrnEncodingParameters,
    OrnSensoryEncoder,
    ReadoutParameters,
    bilateral_odour,
    score_operating_point,
    searched_parameter_grid,
)
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot


@dataclass(frozen=True, slots=True)
class Epoch:
    """One scripted stimulus epoch: a duration and a cue side."""

    name: str
    duration_us: int
    cue: str  # "none", "left" or "right"


def default_epochs(*, baseline_us: int, cue_us: int, recovery_us: int) -> tuple[Epoch, ...]:
    return (
        Epoch("baseline", baseline_us, "none"),
        Epoch("cue_left", cue_us, "left"),
        Epoch("cue_right", cue_us, "right"),
        Epoch("recovery", recovery_us, "none"),
    )


def _cue_odour(cue: str, geometry: dict[str, float]) -> tuple[float, float]:
    """Bilateral odour values for a cue on one side, from the registered field."""
    if cue == "none":
        return 0.0, 0.0
    offset = float(geometry["cue_lateral_offset_mm"])
    source_y = offset if cue == "left" else -offset
    return bilateral_odour(
        x_mm=0.0,
        y_mm=0.0,
        heading_rad=0.0,
        source_x_mm=float(geometry["cue_forward_offset_mm"]),
        source_y_mm=source_y,
        source_strength=float(geometry["source_strength"]),
        softening_mm2=float(geometry["softening_mm2"]),
        half_saturation=float(geometry["half_saturation"]),
        antenna_separation_mm=float(geometry["antenna_separation_mm"]),
    )


def probe_operating_point(
    *,
    graph: SparseConnectome,
    populations: Demo01Populations,
    signs: np.ndarray,
    base_parameters: dict[str, Any],
    candidate: dict[str, float],
    epochs: tuple[Epoch, ...],
    geometry: dict[str, float],
    criteria: OperatingPointCriteria,
    readout_parameters: ReadoutParameters,
    coupling_us: int,
    build_root: Path,
    seed: int,
    settle_fraction: float = 0.4,
) -> dict[str, Any]:
    """Run one candidate through the scripted epochs and score it on neural grounds."""
    if not 0.0 <= settle_fraction < 1.0:
        raise ConfigurationError("settle_fraction must lie in [0, 1)")
    parameters = {**base_parameters, **candidate}
    tag = "-".join(f"{key}{value:g}" for key, value in sorted(candidate.items()))
    digest = sha256_json(candidate)[:12]
    engine = TrackAGeNNEngine(build_root / digest, variant="exact")
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
    encoder = OrnSensoryEncoder(
        populations,
        OrnEncodingParameters.from_mapping(parameters),
    )
    readout = FilteredDescendingReadout(populations, readout_parameters)
    readout_ids = populations.readout_body_ids
    pools: dict[str, Sequence[int]] = dict(populations.monitors)

    epoch_samples: dict[str, list[dict[str, float]]] = {epoch.name: [] for epoch in epochs}
    pool_samples: dict[str, list[dict[str, float]]] = {epoch.name: [] for epoch in epochs}
    timeline: list[dict[str, Any]] = []
    t_us = 0
    simulation_started = time.perf_counter()
    try:
        for epoch in epochs:
            if epoch.duration_us % coupling_us:
                raise ConfigurationError(
                    f"Epoch {epoch.name} is not a whole number of coupling intervals"
                )
            steps = epoch.duration_us // coupling_us
            settle = int(steps * settle_fraction)
            left, right = _cue_odour(epoch.cue, geometry)
            for step in range(steps):
                sensor_like = NeuralInputFrame(
                    t_us=t_us,
                    ids=(OrnSensoryEncoder.SENSOR_LEFT, OrnSensoryEncoder.SENSOR_RIGHT),
                    values=(left, right),
                    units="normalized [0,1]",
                    signal_type=SignalType.WORLD_QUANTITY,
                    provenance="E",
                    assumption_ids=("SENS-03",),
                    metadata={"scripted_epoch": epoch.name},
                )
                engine.push_inputs(encoder.encode(sensor_like))
                t_us += coupling_us
                engine.step_until(t_us)
                frame = readout.read(engine.read_outputs(readout_ids, coupling_us))
                activity = engine.population_activity(pools, coupling_us)
                sample: dict[str, float] = {
                    str(name): float(value)
                    for name, value in zip(frame.ids, frame.values, strict=True)
                }
                if step >= settle:
                    epoch_samples[epoch.name].append(sample)
                    pool_samples[epoch.name].append(
                        {name: value["mean_rate_hz"] for name, value in activity.items()}
                    )
                timeline.append(
                    {
                        "t_us": t_us,
                        "epoch": epoch.name,
                        "cue": epoch.cue,
                        "odour": [left, right],
                        "readout_hz": {str(k): float(v) for k, v in sample.items()},
                        "raw_counts": frame.metadata["raw_population_spike_counts"],
                        "pool_mean_rate_hz": {
                            name: value["mean_rate_hz"] for name, value in activity.items()
                        },
                        "pool_active_fraction": {
                            name: value["active_fraction"] for name, value in activity.items()
                        },
                    }
                )
        simulation_seconds = time.perf_counter() - simulation_started
        final_activity = engine.population_activity(pools, coupling_us)
    finally:
        engine.close()

    def epoch_mean(name: str) -> dict[str, float]:
        rows = epoch_samples[name]
        if not rows:
            raise ConfigurationError(f"Epoch {name} produced no scored sample")
        return {
            key: float(np.mean([row[key] for row in rows])) for key in rows[0]
        }

    pool_mean: dict[str, dict[str, float]] = {}
    for name in populations.monitors:
        values = [row[name] for rows in pool_samples.values() for row in rows]
        pool_mean[name] = {"mean_rate_hz": float(np.mean(values))}
    # Active fraction is taken from the cue epochs, where the network is driven.
    driven = [
        row
        for entry in timeline
        if entry["epoch"] in ("cue_left", "cue_right")
        for row in (entry["pool_active_fraction"],)
    ]
    for name in populations.monitors:
        pool_mean[name]["active_fraction"] = float(
            np.mean([row[name] for row in driven])
        )

    score = score_operating_point(
        baseline=epoch_mean("baseline"),
        cue_left=epoch_mean("cue_left"),
        cue_right=epoch_mean("cue_right"),
        recovery=epoch_mean("recovery"),
        pool_activity=pool_mean,
        criteria=criteria,
    )
    return {
        "candidate": candidate,
        "candidate_tag": tag,
        "candidate_sha256": sha256_json(candidate),
        "build_seconds": build_seconds,
        "simulation_seconds": simulation_seconds,
        "epoch_means": {epoch.name: epoch_mean(epoch.name) for epoch in epochs},
        "pool_summary": pool_mean,
        "final_pool_activity": final_activity,
        "score": score,
        "timeline": timeline,
    }


def run_operating_point_search(
    *,
    contract_path: Path,
    graph_path: Path,
    annotations_path: Path,
    transmitter_path: Path,
    build_root: Path,
    output_path: Path,
    seed: int,
    allow_dirty_tree: bool = False,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    """Search the registered P/E grid and record every candidate, passing or not."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The DEMO-01 operating-point search")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported DEMO-01 probe contract schema")
    graph = SparseConnectome.load(graph_path)
    graph.validate()
    populations = Demo01Populations.resolve(annotations_path, graph)
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs
    criteria = OperatingPointCriteria.from_mapping(contract["neural_criteria"])
    readout_parameters = ReadoutParameters.from_mapping(contract["readout"])
    epochs = default_epochs(
        baseline_us=int(contract["epochs"]["baseline_us"]),
        cue_us=int(contract["epochs"]["cue_us"]),
        recovery_us=int(contract["epochs"]["recovery_us"]),
    )
    coupling_us = int(contract["coupling_us"])
    grid = searched_parameter_grid(contract["searched_grid"])
    if max_candidates is not None:
        grid = grid[:max_candidates]
    results: list[dict[str, Any]] = []
    for candidate in grid:
        results.append(
            probe_operating_point(
                graph=graph,
                populations=populations,
                signs=signs,
                base_parameters=contract["fixed_parameters"],
                candidate=candidate,
                epochs=epochs,
                geometry=contract["cue_geometry"],
                criteria=criteria,
                readout_parameters=readout_parameters,
                coupling_us=coupling_us,
                build_root=build_root,
                seed=seed,
            )
        )
    passing = [row for row in results if row["score"]["all_criteria_met"]]
    artifact = {
        "schema_version": "1.0",
        "result_id": str(contract["experiment_id"]),
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": "P/E",
        "evidence_grade": not allow_dirty_tree,
        "code_commit": worktree.get("commit"),
        "worktree_dirty": worktree.get("dirty"),
        "worktree_verification": worktree,
        "seed": seed,
        "graph": {
            "path": str(graph_path),
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "populations": populations.as_dict(),
        "epochs": [
            {"name": epoch.name, "duration_us": epoch.duration_us, "cue": epoch.cue}
            for epoch in epochs
        ],
        "candidates_searched": len(results),
        "candidates_passing": len(passing),
        "results": results,
        "selected": (
            min(
                passing,
                key=lambda row: -row["score"]["selectivity_swing"],
            )["candidate"]
            if passing
            else None
        ),
        "this_is_engineering_calibration": (
            "Every value searched here is P/E. The criteria are neural only: no distance "
            "to target, no displacement and no approach success enters the objective. "
            "Finding an operating point awards no tier and validates no mechanism."
        ),
        "no_behavioural_objective": True,
    }
    _atomic_json(output_path, artifact)
    snapshot, digest = _immutable_snapshot(output_path)
    artifact["artifact_sha256"] = digest
    artifact["immutable_snapshot"] = str(snapshot)
    return artifact
