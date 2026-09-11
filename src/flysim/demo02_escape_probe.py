# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only operating-point search for the giant-fibre escape route.

No body, no decoder, no outcome. Nothing here can read a displacement, a thorax height, an
airborne duration or a success flag, and `demo02-escape-v1` is never opened. That separation
is the whole point: DEMO-01's predecessor chose parameters while watching whether the fly
reached the food, and a bad network with a compensating decoder is indistinguishable from a
good one when you score them together.

Written as a separate module from `demo01_visual_probe` for the reason that module gives for
its own existence: the DEMO-01 probe is the recorded code of a passed experiment, and editing
it to serve a second readout would put that record at risk. The stimulus encoder, the retina
map, the sign policy and the engine are imported and reused unchanged; only the scored
population and the scoring arithmetic are new.

**The readout is counted in spikes, not rates.** `DNp01` is one cell per side. At a 15 ms
coupling interval a single spike is 66.7 Hz, so a filtered rate from two cells is a
0-1-2 counter wearing a decimal point. Every criterion here is a raw count over the scored
intervals of an epoch.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import sha256_json
from flysim.connectome import SparseConnectome
from flysim.demo01 import Demo01Populations, PopulationSpec
from flysim.demo01_visual import (
    VISUAL_ENTRY_SPECS,
    VISUAL_MONITOR_POOLS,
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualEncodingParameters,
)
from flysim.demo01_visual_probe import KERNEL_KEYS
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError

#: The giant fibre, one cell per side. This is the whole decoded readout.
ESCAPE_READOUT_SPECS = (
    PopulationSpec(
        "giant-fibre-left", "DNp01", "L", "somaSide",
        "the giant fibre; LC4 and LPLC2 supply 30.6 percent of its input contacts "
        "monosynaptically, with zero cross-side edges",
    ),
    PopulationSpec(
        "giant-fibre-right", "DNp01", "R", "somaSide", "the giant fibre",
    ),
)

LEFT = "giant-fibre-left"
RIGHT = "giant-fibre-right"

#: The refractory ceiling implied by the frozen 2.2 ms refractory period, used by the
#: saturation criterion. DEMO-01's number, unchanged.
REFRACTORY_CEILING_HZ = 454.5


@dataclass(frozen=True, slots=True)
class EscapeEpoch:
    name: str
    duration_us: int
    side: str  # "none", "left" or "right"


@dataclass(frozen=True, slots=True)
class EscapeCriteria:
    """The five frozen neural criteria. Thresholds come from the contract, not from here."""

    baseline_max_giant_fibre_spikes: int
    baseline_max_descending_hz: float
    saturation_max_fraction: float
    min_loom_giant_fibre_spikes: int
    min_selectivity_swing: float
    max_recovery_fraction: float
    min_active_fraction: float
    max_active_fraction: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> EscapeCriteria:
        return cls(
            baseline_max_giant_fibre_spikes=int(raw["baseline_max_giant_fibre_spikes"]),
            baseline_max_descending_hz=float(raw["baseline_max_descending_hz"]),
            saturation_max_fraction=float(raw["saturation_max_fraction"]),
            min_loom_giant_fibre_spikes=int(raw["min_loom_giant_fibre_spikes"]),
            min_selectivity_swing=float(raw["min_selectivity_swing"]),
            max_recovery_fraction=float(raw["max_recovery_fraction"]),
            min_active_fraction=float(raw["min_active_fraction"]),
            max_active_fraction=float(raw["max_active_fraction"]),
        )


def resolve_escape_populations(
    annotations_path: Path, graph: SparseConnectome
) -> Demo01Populations:
    """Lamina entry with released column coordinates, giant-fibre readout."""
    return Demo01Populations.resolve(
        annotations_path,
        graph,
        entry_specs=VISUAL_ENTRY_SPECS,
        readout_specs=ESCAPE_READOUT_SPECS,
        monitor_pools=VISUAL_MONITOR_POOLS,
        require_hex=True,
    )


def epochs_from_contract(contract: dict[str, Any]) -> tuple[EscapeEpoch, ...]:
    spec = contract["epochs"]
    return (
        EscapeEpoch("baseline", int(spec["baseline_us"]), "none"),
        EscapeEpoch("loom_left", int(spec["loom_left_us"]), "left"),
        EscapeEpoch("loom_right", int(spec["loom_right_us"]), "right"),
        EscapeEpoch("recovery", int(spec["recovery_us"]), "none"),
    )


def cue_for(side: str, stimulus: dict[str, float]) -> VisualCue | None:
    """The object, placed at a bearing. It is held, not approaching; the contract says so."""
    if side == "none":
        return None
    if side not in {"left", "right"}:
        raise ConfigurationError(f"Unknown cue side: {side}")
    sign = 1.0 if side == "left" else -1.0
    bearing = math.radians(float(stimulus["cue_bearing_deg"]) * sign)
    distance = float(stimulus["cue_distance_mm"])
    return VisualCue(
        x_mm=distance * math.cos(bearing),
        y_mm=distance * math.sin(bearing),
        radius_mm=float(stimulus["cue_radius_mm"]),
    )


def selectivity_index(left: float, right: float) -> float:
    total = left + right
    return 0.0 if total <= 0.0 else (left - right) / total


def probe_escape_operating_point(
    *,
    graph: SparseConnectome,
    populations: Demo01Populations,
    signs: np.ndarray,
    base_parameters: dict[str, Any],
    candidate: dict[str, float],
    epochs: Sequence[EscapeEpoch],
    stimulus: dict[str, float],
    retina: RetinaMap,
    coupling_us: int,
    build_root: Path,
    seed: int,
    settle_fraction: float,
) -> dict[str, Any]:
    """Run one candidate through the scripted epochs and record what it did.

    Records. Does not judge -- `score_escape_candidate` does that, from this output alone,
    so the measurement and the threshold cannot be adjusted in the same place.
    """
    if not 0.0 <= settle_fraction < 1.0:
        raise ConfigurationError("settle_fraction must lie in [0, 1)")
    parameters = {**base_parameters, **candidate}
    # Only kernel parameters force a recompile; the searched three are weight-and-encoder
    # only, so the whole grid shares one compiled model.
    kernel = {key: parameters[key] for key in KERNEL_KEYS if key in parameters}
    engine = TrackAGeNNEngine(build_root / sha256_json(kernel)[:12], variant="exact")
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
    readout_ids = populations.readout_body_ids
    pools: dict[str, Sequence[int]] = dict(populations.monitors)

    measured: dict[str, dict[str, Any]] = {}
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
            cue = cue_for(epoch.side, stimulus)
            spikes: dict[str, int] = {LEFT: 0, RIGHT: 0}
            descending_hz: list[float] = []
            active_fraction: list[float] = []
            scored = 0
            for step in range(steps):
                engine.push_inputs(
                    encoder.encode(t_us, cue, x_mm=0.0, y_mm=0.0, heading_rad=0.0)
                )
                t_us += coupling_us
                engine.step_until(t_us)
                raw = engine.read_outputs(readout_ids, coupling_us)
                counts = raw.metadata.get("spike_counts", {})
                activity = engine.population_activity(pools, coupling_us)
                if step >= settle:
                    scored += 1
                    for name in (LEFT, RIGHT):
                        for body in populations.readout[name]:
                            spikes[name] += int(counts.get(body, 0))
                    descending = activity.get("descending", {})
                    descending_hz.append(float(descending.get("mean_rate_hz", 0.0)))
                    active_fraction.append(float(descending.get("active_fraction", 0.0)))
            duration_s = scored * coupling_us / 1_000_000.0
            measured[epoch.name] = {
                "scored_intervals": scored,
                "scored_seconds": duration_s,
                "giant_fibre_spikes": dict(spikes),
                "giant_fibre_spikes_total": spikes[LEFT] + spikes[RIGHT],
                "giant_fibre_hz": (
                    (spikes[LEFT] + spikes[RIGHT]) / 2.0 / duration_s
                    if duration_s > 0 else 0.0
                ),
                "descending_mean_hz": (
                    float(np.mean(descending_hz)) if descending_hz else 0.0
                ),
                "descending_active_fraction": (
                    float(np.mean(active_fraction)) if active_fraction else 0.0
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


def score_escape_candidate(
    measured: dict[str, Any], criteria: EscapeCriteria
) -> dict[str, Any]:
    """Apply the five frozen criteria to one candidate's recording."""
    epochs = measured["epochs"]
    baseline = epochs["baseline"]
    left = epochs["loom_left"]
    right = epochs["loom_right"]
    recovery = epochs["recovery"]

    # N1: silent and stable at rest, and not saturated while driven.
    saturation_ceiling = criteria.saturation_max_fraction * REFRACTORY_CEILING_HZ
    n1 = (
        baseline["giant_fibre_spikes_total"] <= criteria.baseline_max_giant_fibre_spikes
        and baseline["descending_mean_hz"] <= criteria.baseline_max_descending_hz
        and max(left["descending_mean_hz"], right["descending_mean_hz"])
        <= saturation_ceiling
    )

    # N2: the better side responds, in raw spikes.
    best_side = max(
        left["giant_fibre_spikes_total"], right["giant_fibre_spikes_total"]
    )
    n2 = best_side >= criteria.min_loom_giant_fibre_spikes

    # N3: selectivity reverses sign between a left object and a right object.
    index_left = selectivity_index(
        left["giant_fibre_spikes"][LEFT], left["giant_fibre_spikes"][RIGHT]
    )
    index_right = selectivity_index(
        right["giant_fibre_spikes"][LEFT], right["giant_fibre_spikes"][RIGHT]
    )
    swing = index_left - index_right
    reverses = (index_left > 0.0 > index_right) or (index_left < 0.0 < index_right)
    n3 = reverses and abs(swing) >= criteria.min_selectivity_swing

    # N4: falls back to within half the evoked increment.
    evoked = max(left["giant_fibre_hz"], right["giant_fibre_hz"])
    base_hz = baseline["giant_fibre_hz"]
    allowed = base_hz + criteria.max_recovery_fraction * max(evoked - base_hz, 0.0)
    n4 = recovery["giant_fibre_hz"] <= allowed

    # N5: alive and not saturated. This is what stops a dead network passing N1.
    driven_fraction = max(
        left["descending_active_fraction"], right["descending_active_fraction"]
    )
    n5 = criteria.min_active_fraction <= driven_fraction <= criteria.max_active_fraction

    return {
        "N1_silent_and_stable_at_rest": bool(n1),
        "N2_responds_to_the_object": bool(n2),
        "N3_side_selectivity_reverses": bool(n3),
        "N4_recovers_to_silence": bool(n4),
        "N5_the_network_is_alive_and_not_saturated": bool(n5),
        "passes": bool(n1 and n2 and n3 and n4 and n5),
        "values": {
            "baseline_giant_fibre_spikes": baseline["giant_fibre_spikes_total"],
            "baseline_descending_hz": baseline["descending_mean_hz"],
            "loom_left_spikes": left["giant_fibre_spikes"],
            "loom_right_spikes": right["giant_fibre_spikes"],
            "best_side_spikes": best_side,
            "selectivity_index_left_cue": index_left,
            "selectivity_index_right_cue": index_right,
            "selectivity_swing": swing,
            "selectivity_reverses": bool(reverses),
            "recovery_hz": recovery["giant_fibre_hz"],
            "recovery_allowed_hz": allowed,
            "driven_descending_hz": max(
                left["descending_mean_hz"], right["descending_mean_hz"]
            ),
            "saturation_ceiling_hz": saturation_ceiling,
            "driven_active_fraction": driven_fraction,
        },
    }


def select_operating_point(
    results: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """The frozen selection rule: largest selectivity swing among passing candidates.

    Ties break toward the lowest lamina rate then the lowest synaptic gain, so the least
    extreme point wins rather than an arbitrary one.
    """
    passing = [r for r in results if r["score"]["passes"]]
    if not passing:
        return None
    return max(
        passing,
        key=lambda r: (
            abs(r["score"]["values"]["selectivity_swing"]),
            -float(r["candidate"]["lamina_max_rate_hz"]),
            -float(r["candidate"]["synaptic_mv_per_contact"]),
        ),
    )
