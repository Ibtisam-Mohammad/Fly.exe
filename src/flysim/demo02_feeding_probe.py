# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only operating-point probe for tarsal taste to the MN9 readout."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import SensorFrame, SignalType
from flysim.demo01_visual_probe import KERNEL_KEYS
from flysim.demo02 import Demo02Populations, entry_channels
from flysim.demo02_escape_probe import REFRACTORY_CEILING_HZ
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.sensory_atlas import SensoryAtlas
from flysim.sensory_bus import ChannelBinding, SensoryBus
from flysim.transducers import SaturatingTransducer

READOUT = "rostrum-mn9"
MOTOR_POOL = "vnc-motor"
SENSORS = {
    "L": ("world:tarsal-sucrose:lf", "world:tarsal-sucrose:lh"),
    "R": ("world:tarsal-sucrose:rf", "world:tarsal-sucrose:rh"),
}


@dataclass(frozen=True, slots=True)
class FeedingEpoch:
    name: str
    duration_us: int
    concentration: float


def epochs_from_contract(contract: dict[str, Any]) -> tuple[FeedingEpoch, ...]:
    raw = contract["epochs"]
    middle = tuple(
        FeedingEpoch(f"concentration_{value:g}", int(raw["concentration_us"]), float(value))
        for value in raw["concentrations"]
    )
    return (
        FeedingEpoch("baseline", int(raw["baseline_us"]), 0.0),
        *middle,
        FeedingEpoch("recovery", int(raw["recovery_us"]), 0.0),
    )


def _sensor_frame(t_us: int, concentration: float) -> SensorFrame:
    ids = tuple(value for side in ("L", "R") for value in SENSORS[side])
    return SensorFrame(
        t_us=t_us,
        ids=ids,
        values=tuple(float(concentration) for _ in ids),
        units=",".join("normalized" for _ in ids),
        signal_type=SignalType.WORLD_QUANTITY,
        provenance="E",
        assumption_ids=("SENS-05", "DEMO-03"),
        metadata={
            "scripted": True,
            "body_attached": False,
            "why": "neural-only operating-point selection; no feeding outcome is visible",
        },
    )


def _rank(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    order = np.argsort(array, kind="stable")
    ranks = np.empty(array.size, dtype=np.float64)
    start = 0
    while start < array.size:
        end = start + 1
        while end < array.size and array[order[end]] == array[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman(values: Sequence[float], responses: Sequence[float]) -> float:
    if len(values) != len(responses) or len(values) < 2:
        raise ConfigurationError("Spearman comparison needs equal non-trivial sequences")
    left, right = _rank(values), _rank(responses)
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def probe_feeding_operating_point(
    *,
    graph: SparseConnectome,
    atlas: SensoryAtlas,
    populations: Demo02Populations,
    signs: np.ndarray,
    base_parameters: dict[str, Any],
    candidate: dict[str, float],
    epochs: Sequence[FeedingEpoch],
    transducer_half_saturation: float,
    transducer_threshold: float,
    coupling_us: int,
    build_root: Path,
    seed: int,
    settle_fraction: float,
) -> dict[str, Any]:
    if not 0.0 <= settle_fraction < 1.0:
        raise ConfigurationError("settle_fraction must lie in [0, 1)")
    parameters = {**base_parameters, **candidate}
    kernel = {key: parameters[key] for key in KERNEL_KEYS if key in parameters}
    engine = TrackAGeNNEngine(
        build_root / sha256_json({**kernel, "seed": seed})[:12], variant="exact"
    )
    started = time.perf_counter()
    engine.initialize(
        graph,
        {
            **parameters,
            "functional_edge_signs": signs,
            "entry_body_ids": atlas.entry_union,
        },
        seed,
    )
    build_seconds = time.perf_counter() - started
    transducer = SaturatingTransducer(
        max_rate_hz=float(candidate["taste_max_rate_hz"]),
        half_saturation=transducer_half_saturation,
        threshold=transducer_threshold,
    )
    bindings = tuple(
        ChannelBinding(
            key=key,
            sensor_id=SENSORS[str(key.side)][0 if key.organ == "leg-front" else 1],
            transducer=transducer,
            delay_us=0,
            kind="declared",
            why="feeding operating-point search entry",
        )
        for key in entry_channels("feeding")
    )
    bus = SensoryBus(atlas=atlas, bindings=bindings, coupling_us=coupling_us)
    readout_ids = populations.readout[READOUT]
    if MOTOR_POOL not in populations.monitors:
        raise ConfigurationError(f"Required monitor pool is missing: {MOTOR_POOL}")
    measured: dict[str, dict[str, Any]] = {}
    t_us = 0
    simulation_started = time.perf_counter()
    try:
        for epoch in epochs:
            if epoch.duration_us % coupling_us:
                raise ConfigurationError("Epoch duration is not a whole coupling interval")
            steps = epoch.duration_us // coupling_us
            settle = int(steps * settle_fraction)
            spikes = 0
            motor_hz: list[float] = []
            active: list[float] = []
            scored = 0
            for step in range(steps):
                frame = bus.encode(t_us, _sensor_frame(t_us, epoch.concentration))
                engine.push_inputs(frame)
                t_us += coupling_us
                engine.step_until(t_us)
                raw = engine.read_outputs(readout_ids, coupling_us)
                counts = raw.metadata.get("spike_counts", {})
                activity = engine.population_activity(
                    {MOTOR_POOL: populations.monitors[MOTOR_POOL]}, coupling_us
                )[MOTOR_POOL]
                if step >= settle:
                    scored += 1
                    spikes += sum(int(counts.get(body, 0)) for body in readout_ids)
                    motor_hz.append(float(activity["mean_rate_hz"]))
                    active.append(float(activity["active_fraction"]))
            duration_s = scored * coupling_us / 1_000_000.0
            measured[epoch.name] = {
                "concentration": epoch.concentration,
                "scored_intervals": scored,
                "readout_spikes": spikes,
                "readout_hz": spikes / len(readout_ids) / duration_s if duration_s else 0.0,
                "motor_mean_hz": float(np.mean(motor_hz)) if motor_hz else 0.0,
                "motor_active_fraction": float(np.mean(active)) if active else 0.0,
                "entry_bodies_driven": int(
                    frame.metadata["entry_bodies_with_nonzero_rate"]
                ),
            }
    finally:
        engine.close()
    return {
        "candidate": dict(candidate),
        "epochs": measured,
        "build_seconds": build_seconds,
        "simulation_seconds": time.perf_counter() - simulation_started,
    }


def score_feeding_candidate(measured: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    epochs = measured["epochs"]
    rules = contract["neural_criteria"]
    baseline = epochs["baseline"]
    concentration_rows = [
        epochs[f"concentration_{float(value):g}"] for value in contract["epochs"]["concentrations"]
    ]
    recovery = epochs["recovery"]
    counts = [int(row["readout_spikes"]) for row in concentration_rows]
    concentrations = [float(row["concentration"]) for row in concentration_rows]
    n1 = (
        baseline["readout_spikes"] <= rules["N1_baseline_is_silent"]["max_mn9_spikes"]
        and baseline["motor_mean_hz"] <= rules["N1_baseline_is_silent"]["max_motor_pool_hz"]
    )
    n2 = counts[-1] >= rules["N2_the_route_responds"]["min_mn9_spikes_at_max_concentration"]
    rho = spearman(concentrations, counts)
    n3 = (
        rho >= rules["N3_the_response_tracks_concentration"]["min_spearman"]
        and len(set(counts))
        >= rules["N3_the_response_tracks_concentration"]["min_distinct_spike_counts"]
    )
    max_evoked_hz = max(float(row["readout_hz"]) for row in concentration_rows)
    allowed_recovery = float(baseline["readout_hz"]) + float(
        rules["N4_the_route_recovers"]["max_recovery_fraction"]
    ) * max(max_evoked_hz - float(baseline["readout_hz"]), 0.0)
    n4 = float(recovery["readout_hz"]) <= allowed_recovery
    fractions = [float(row["motor_active_fraction"]) for row in concentration_rows]
    max_motor_hz = max(float(row["motor_mean_hz"]) for row in concentration_rows)
    n5_rule = rules["N5_the_network_is_alive_and_not_saturated"]
    n5 = (
        max(fractions) >= n5_rule["min_motor_active_fraction"]
        and max(fractions) <= n5_rule["max_motor_active_fraction"]
        and max_motor_hz
        <= n5_rule["saturation_max_fraction_of_refractory_ceiling"]
        * REFRACTORY_CEILING_HZ
    )
    return {
        "N1_baseline_is_silent": bool(n1),
        "N2_the_route_responds": bool(n2),
        "N3_the_response_tracks_concentration": bool(n3),
        "N4_the_route_recovers": bool(n4),
        "N5_the_network_is_alive_and_not_saturated": bool(n5),
        "passes": bool(n1 and n2 and n3 and n4 and n5),
        "values": {
            "spike_counts_by_concentration": counts,
            "spearman": rho,
            "distinct_spike_counts": len(set(counts)),
            "baseline_spikes": baseline["readout_spikes"],
            "baseline_motor_hz": baseline["motor_mean_hz"],
            "recovery_hz": recovery["readout_hz"],
            "recovery_allowed_hz": allowed_recovery,
            "max_motor_hz": max_motor_hz,
            "max_motor_active_fraction": max(fractions),
            "response_range_spikes": max(counts) - min(counts),
        },
    }


def select_operating_point(results: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    passing = [row for row in results if row["score"]["passes"]]
    if not passing:
        return None
    return max(
        passing,
        key=lambda row: (
            int(row["score"]["values"]["response_range_spikes"]),
            -float(row["candidate"]["taste_max_rate_hz"]),
            -float(row["candidate"]["synaptic_mv_per_contact"]),
            float(row["candidate"]["inhibitory_weight_gain"]),
        ),
    )


__all__ = [
    "FeedingEpoch",
    "epochs_from_contract",
    "probe_feeding_operating_point",
    "score_feeding_candidate",
    "select_operating_point",
    "spearman",
]
