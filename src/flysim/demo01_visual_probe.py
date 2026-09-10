# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only operating-point search for the DEMO-01 visual route. No body, no outcome.

The predecessor demonstration chose its parameters while watching whether the fly reached
the food, so a bad network and a compensating decoder could not be told apart. This search
keeps the two problems separate: the network operating point is scored on criteria that
are all measurable with no body attached, and nothing here can read a distance, a
displacement or a success flag.

The scripted stimulus is a looming visual cue placed on one side of the fly at a fixed
pose. The fly does not move, so the cue's retinal position is held constant within an
epoch and the network sees the same input statistics the embodied run will produce without
any closed loop. Four epochs run in order: no cue, cue to the left, cue to the right, no
cue again.

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
from flysim.demo01 import (
    Demo01Populations,
    FilteredDescendingReadout,
    ReadoutParameters,
)
from flysim.demo01_visual import (
    VISUAL_ENTRY_SPECS,
    VISUAL_LEFT_READOUT,
    VISUAL_MONITOR_POOLS,
    VISUAL_READOUT_SPECS,
    VISUAL_RIGHT_READOUT,
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualEncodingParameters,
    VisualOperatingPointCriteria,
    score_visual_operating_point,
    visual_searched_parameter_grid,
)
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

# Parameters that change the *generated CUDA kernel*, and therefore force a recompile.
# GeNN compiles shared neuron parameters into the kernel as constants but loads synaptic
# weights as runtime variables, so a candidate that differs only in a weight scale needs
# no recompile at all. Keying the build directory on the weight scales instead cost 18
# separate three-and-a-half-minute compiles for two distinct kernels, which is where an
# hour of this search was going.
KERNEL_KEYS = (
    "neural_dt_us",
    "resting_mv",
    "reset_mv",
    "threshold_mv",
    "membrane_tau_ms",
    "synapse_tau_ms",
    "refractory_ms",
    "synaptic_delay_ms",
    "reset_synaptic_state_on_spike",
    "tonic_drive_mv",
    "adaptation_increment_mv",
    "adaptation_tau_ms",
)

# Weight-only parameters, listed so the search can order candidates to group identical
# kernels together. These never trigger a recompile.
WEIGHT_KEYS = (
    "synaptic_mv_per_contact",
    "central_entry_outgoing_gain",
    "synaptic_target_normalisation_exponent",
    "inhibitory_weight_gain",
)


@dataclass(frozen=True, slots=True)
class VisualEpoch:
    """One scripted stimulus epoch: a duration and a cue side."""

    name: str
    duration_us: int
    cue: str  # "none", "left" or "right"


def default_visual_epochs(
    *, baseline_us: int, cue_us: int, recovery_us: int
) -> tuple[VisualEpoch, ...]:
    return (
        VisualEpoch("baseline", baseline_us, "none"),
        VisualEpoch("cue_left", cue_us, "left"),
        VisualEpoch("cue_right", cue_us, "right"),
        VisualEpoch("recovery", recovery_us, "none"),
    )


def cue_for(side: str, geometry: dict[str, float]) -> VisualCue | None:
    """The scripted cue for one epoch, at a declared bearing and distance."""
    if side == "none":
        return None
    bearing_deg = float(geometry["cue_bearing_deg"])
    if side == "right":
        bearing_deg = -bearing_deg
    distance = float(geometry["cue_distance_mm"])
    angle = np.radians(bearing_deg)
    return VisualCue(
        x_mm=float(distance * np.cos(angle)),
        y_mm=float(distance * np.sin(angle)),
        radius_mm=float(geometry["cue_radius_mm"]),
        dark=True,
    )


def resolve_visual_populations(
    annotations_path: Path, graph: SparseConnectome
) -> Demo01Populations:
    """Resolve the declared visual populations, requiring released column coordinates."""
    return Demo01Populations.resolve(
        annotations_path,
        graph,
        entry_specs=VISUAL_ENTRY_SPECS,
        readout_specs=VISUAL_READOUT_SPECS,
        monitor_pools=VISUAL_MONITOR_POOLS,
        require_hex=True,
    )


def probe_visual_operating_point(
    *,
    graph: SparseConnectome,
    populations: Demo01Populations,
    signs: np.ndarray,
    base_parameters: dict[str, Any],
    candidate: dict[str, float],
    epochs: tuple[VisualEpoch, ...],
    geometry: dict[str, float],
    retina: RetinaMap,
    criteria: VisualOperatingPointCriteria,
    readout_parameters: ReadoutParameters,
    coupling_us: int,
    build_root: Path,
    seed: int,
    settle_fraction: float = 0.4,
    keep_timeline: bool = True,
) -> dict[str, Any]:
    """Run one candidate through the scripted epochs and score it on neural grounds."""
    if not 0.0 <= settle_fraction < 1.0:
        raise ConfigurationError("settle_fraction must lie in [0, 1)")
    parameters = {**base_parameters, **candidate}
    kernel = {key: parameters[key] for key in KERNEL_KEYS if key in parameters}
    build_key = sha256_json(kernel)[:12]
    engine = TrackAGeNNEngine(build_root / build_key, variant="exact")
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
        populations, VisualEncodingParameters.from_mapping(parameters), retina
    )
    readout = FilteredDescendingReadout(populations, readout_parameters)
    readout_ids = populations.readout_body_ids
    pools: dict[str, Sequence[int]] = dict(populations.monitors)

    epoch_samples: dict[str, list[dict[str, float]]] = {epoch.name: [] for epoch in epochs}
    pool_samples: dict[str, list[dict[str, float]]] = {epoch.name: [] for epoch in epochs}
    active_samples: dict[str, list[dict[str, float]]] = {epoch.name: [] for epoch in epochs}
    epoch_spikes: dict[str, int] = {epoch.name: 0 for epoch in epochs}
    timeline: list[dict[str, Any]] = []
    t_us = 0
    simulation_started = time.perf_counter()
    decoded = (VISUAL_LEFT_READOUT, VISUAL_RIGHT_READOUT)
    try:
        for epoch in epochs:
            if epoch.duration_us % coupling_us:
                raise ConfigurationError(
                    f"Epoch {epoch.name} is not a whole number of coupling intervals"
                )
            steps = epoch.duration_us // coupling_us
            settle = int(steps * settle_fraction)
            cue = cue_for(epoch.cue, geometry)
            for step in range(steps):
                engine.push_inputs(
                    encoder.encode(t_us, cue, x_mm=0.0, y_mm=0.0, heading_rad=0.0)
                )
                t_us += coupling_us
                engine.step_until(t_us)
                frame = readout.read(engine.read_outputs(readout_ids, coupling_us))
                activity = engine.population_activity(pools, coupling_us)
                sample = {
                    str(name): float(value)
                    for name, value in zip(frame.ids, frame.values, strict=True)
                }
                counts = frame.metadata["raw_population_spike_counts"]
                if step >= settle:
                    epoch_samples[epoch.name].append(sample)
                    pool_samples[epoch.name].append(
                        {name: value["mean_rate_hz"] for name, value in activity.items()}
                    )
                    active_samples[epoch.name].append(
                        {name: value["active_fraction"] for name, value in activity.items()}
                    )
                    epoch_spikes[epoch.name] += sum(
                        int(counts[name]) for name in decoded
                    )
                if keep_timeline:
                    timeline.append(
                        {
                            "t_us": t_us,
                            "epoch": epoch.name,
                            "cue": epoch.cue,
                            "readout_hz": sample,
                            "raw_counts": {str(k): int(v) for k, v in counts.items()},
                            "pool_mean_rate_hz": {
                                name: value["mean_rate_hz"]
                                for name, value in activity.items()
                            },
                            "pool_active_fraction": {
                                name: value["active_fraction"]
                                for name, value in activity.items()
                            },
                            "scene": frame.metadata.get("scene"),
                        }
                    )
        simulation_seconds = time.perf_counter() - simulation_started
        final_activity = engine.population_activity(pools, coupling_us)
        layout = dict(engine.checkpoint().get("sparse_layout", {}))
    finally:
        engine.close()

    def epoch_mean(name: str) -> dict[str, float]:
        rows = epoch_samples[name]
        if not rows:
            raise ConfigurationError(f"Epoch {name} produced no scored sample")
        return {key: float(np.mean([row[key] for row in rows])) for key in rows[0]}

    pool_mean: dict[str, dict[str, float]] = {}
    for name in populations.monitors:
        values = [row[name] for rows in pool_samples.values() for row in rows]
        pool_mean[name] = {"mean_rate_hz": float(np.mean(values))}
    # The active fraction is taken over the cue epochs, where the network is driven, and
    # from the scored samples rather than the optional timeline: the timeline can be
    # switched off to save memory, and reading it here made the fraction silently zero.
    driven = [
        row
        for epoch in ("cue_left", "cue_right")
        for row in active_samples[epoch]
    ]
    if not driven:
        raise ConfigurationError(
            "No scored sample in either cue epoch; the active fraction cannot be measured"
        )
    for name in populations.monitors:
        pool_mean[name]["active_fraction"] = float(np.mean([row[name] for row in driven]))

    score = score_visual_operating_point(
        baseline=epoch_mean("baseline"),
        cue_left=epoch_mean("cue_left"),
        cue_right=epoch_mean("cue_right"),
        recovery=epoch_mean("recovery"),
        pool_activity=pool_mean,
        cue_epoch_spike_counts={
            name: epoch_spikes[name] for name in ("cue_left", "cue_right")
        },
        criteria=criteria,
    )
    return {
        "candidate": candidate,
        "candidate_sha256": sha256_json(candidate),
        "structural_build_key": build_key,
        "build_seconds": build_seconds,
        "simulation_seconds": simulation_seconds,
        "epoch_means": {epoch.name: epoch_mean(epoch.name) for epoch in epochs},
        "epoch_readout_spike_totals": epoch_spikes,
        "pool_summary": pool_mean,
        "final_pool_activity": final_activity,
        "per_target_normalisation": layout.get("per_target_normalisation"),
        "score": score,
        "timeline": timeline,
    }


def run_visual_operating_point_search(
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
    keep_timeline: bool = True,
    progress: bool = False,
) -> dict[str, Any]:
    """Search the registered P/E grid and record every candidate, passing or not."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The DEMO-01 visual operating-point search")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported DEMO-01 visual probe contract schema")
    graph = SparseConnectome.load(graph_path)
    graph.validate()
    populations = resolve_visual_populations(annotations_path, graph)
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs
    criteria = VisualOperatingPointCriteria.from_mapping(contract["neural_criteria"])
    readout_parameters = ReadoutParameters.from_mapping(contract["readout"])
    retina = RetinaMap.from_mapping(contract["retina_map"])
    epochs = default_visual_epochs(
        baseline_us=int(contract["epochs"]["baseline_us"]),
        cue_us=int(contract["epochs"]["cue_us"]),
        recovery_us=int(contract["epochs"]["recovery_us"]),
    )
    coupling_us = int(contract["coupling_us"])
    grid = visual_searched_parameter_grid(contract["searched_grid"])
    # Order candidates so every one sharing a generated kernel runs consecutively, which
    # keeps the number of CUDA compiles down to the number of distinct kernels.
    fixed = contract["fixed_parameters"]

    def kernel_key(row: dict[str, float]) -> str:
        merged = {**fixed, **row}
        return sha256_json({key: merged[key] for key in KERNEL_KEYS if key in merged})

    grid = tuple(sorted(grid, key=kernel_key))
    if max_candidates is not None:
        grid = grid[:max_candidates]
    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(grid, start=1):
        row = probe_visual_operating_point(
            graph=graph,
            populations=populations,
            signs=signs,
            base_parameters=contract["fixed_parameters"],
            candidate=candidate,
            epochs=epochs,
            geometry=contract["cue_geometry"],
            retina=retina,
            criteria=criteria,
            readout_parameters=readout_parameters,
            coupling_us=coupling_us,
            build_root=build_root,
            seed=seed,
            keep_timeline=keep_timeline,
        )
        results.append(row)
        if progress:
            met = row["score"]
            print(
                f"[{index:3d}/{len(grid)}] "
                + " ".join(f"{k}={v:g}" for k, v in sorted(candidate.items()))
                + f" | base {met['baseline_drive_hz']:6.2f} "
                + f"resp {met['cue_response_hz']:+7.2f} "
                + f"swing {met['selectivity_swing']:.3f} "
                + f"rev {'Y' if met['selectivity_reverses_with_cue_side'] else 'n'} "
                + f"spikes {min(met['cue_epoch_readout_spike_counts'].values())} "
                + "".join(
                    "P" if met[f"C{n}{tag}"] else "."
                    for n, tag in (
                        (1, "_stable_nonsaturated"),
                        (2, "_cue_responsive"),
                        (3, "_bilateral_selectivity_reverses"),
                        (4, "_recovers_to_baseline"),
                        (5, "_enough_spikes_to_be_meaningful"),
                    )
                )
                + (" <== PASS" if met["all_criteria_met"] else ""),
                flush=True,
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
        "route": "retinotopic lamina entry, full optic lobe, descending readout",
        "graph": {
            "path": str(graph_path),
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "populations": populations.as_dict(),
        "retina_map": retina.as_dict(),
        "cue_geometry": dict(contract["cue_geometry"]),
        "epochs": [
            {"name": epoch.name, "duration_us": epoch.duration_us, "cue": epoch.cue}
            for epoch in epochs
        ],
        "candidates_searched": len(results),
        "candidates_passing": len(passing),
        "results": results,
        "selected": (
            max(passing, key=lambda row: row["score"]["selectivity_swing"])["candidate"]
            if passing
            else None
        ),
        "selection_rule": (
            "Among candidates meeting every criterion, the largest selectivity swing. "
            "Selection happens only inside the passing set, so it cannot trade a failed "
            "criterion for a better number elsewhere."
        ),
        "this_is_engineering_calibration": (
            "Every value searched here is P/E. The criteria are neural only: no distance, "
            "no displacement and no approach outcome enters the objective. Finding an "
            "operating point awards no tier and validates no mechanism."
        ),
        "no_behavioural_objective": True,
    }
    _atomic_json(output_path, artifact)
    snapshot, digest = _immutable_snapshot(output_path)
    artifact["artifact_sha256"] = digest
    artifact["immutable_snapshot"] = str(snapshot)
    return artifact


__all__ = [
    "KERNEL_KEYS",
    "WEIGHT_KEYS",
    "VisualEpoch",
    "cue_for",
    "default_visual_epochs",
    "probe_visual_operating_point",
    "resolve_visual_populations",
    "run_visual_operating_point_search",
]
