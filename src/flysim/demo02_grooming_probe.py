# SPDX-License-Identifier: GPL-2.0-or-later
"""Neural-only operating-point search for the antennal grooming route.

No body, no decoder, no outcome. `demo02-grooming-v1` is never opened and nothing here can
read a joint angle, an excursion, a tarsus-to-arista distance or a success flag.

The escape search found that DEMO-02's negative was a sample of one: eleven of thirty-six
points drove the giant fibre cleanly, and the parameter responsible was one DEMO-01 had
selected at the boundary of its own grid. Grooming has had the same zero candidates searched,
so its negative rests on the same assumption, and the measurement that makes it worth
searching is sharper than escape's was: **30.2 per cent of the grooming readout's input
contacts were active while the readout produced zero spikes.** The drive arrives. Something
between arrival and threshold is wrong, and gain is the cheapest of the candidate causes to
rule in or out.

Unlike escape, the entry here is not the lamina and there is no frozen retinotopic encoder.
Grooming enters through the sensory bus with a declared saturating transducer, so the
transducer's peak rate is the analogue of `lamina_max_rate_hz` and is the searched lever.
"""

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
from flysim.demo02_escape_probe import REFRACTORY_CEILING_HZ, selectivity_index
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError
from flysim.sensory_atlas import SensoryAtlas
from flysim.sensory_bus import ChannelBinding, SensoryBus
from flysim.transducers import SaturatingTransducer

LEFT = "groom-dn-left"
RIGHT = "groom-dn-right"
DESCENDING_POOL = "descending"

#: Where the deflection the transducer sees comes from. In the embodied run this is real
#: physics on a free hinge; here it is a scripted scalar, because the search must not need
#: a body to run.
SENSOR_LEFT = "world:antenna-deflection:l"
SENSOR_RIGHT = "world:antenna-deflection:r"


@dataclass(frozen=True, slots=True)
class GroomEpoch:
    name: str
    duration_us: int
    side: str  # "none", "left" or "right"


@dataclass(frozen=True, slots=True)
class GroomCriteria:
    baseline_max_readout_spikes: int
    baseline_max_descending_hz: float
    saturation_max_fraction: float
    min_response_readout_spikes: int
    min_selectivity_swing: float
    max_recovery_fraction: float
    min_active_fraction: float
    max_active_fraction: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> GroomCriteria:
        return cls(
            baseline_max_readout_spikes=int(raw["baseline_max_readout_spikes"]),
            baseline_max_descending_hz=float(raw["baseline_max_descending_hz"]),
            saturation_max_fraction=float(raw["saturation_max_fraction"]),
            min_response_readout_spikes=int(raw["min_response_readout_spikes"]),
            min_selectivity_swing=float(raw["min_selectivity_swing"]),
            max_recovery_fraction=float(raw["max_recovery_fraction"]),
            min_active_fraction=float(raw["min_active_fraction"]),
            max_active_fraction=float(raw["max_active_fraction"]),
        )


def epochs_from_contract(contract: dict[str, Any]) -> tuple[GroomEpoch, ...]:
    spec = contract["epochs"]
    return (
        GroomEpoch("baseline", int(spec["baseline_us"]), "none"),
        GroomEpoch("stimulus_left", int(spec["stimulus_left_us"]), "left"),
        GroomEpoch("stimulus_right", int(spec["stimulus_right_us"]), "right"),
        GroomEpoch("recovery", int(spec["recovery_us"]), "none"),
    )


def _sensor_frame(t_us: int, side: str, deflection_rad: float) -> SensorFrame:
    left = deflection_rad if side == "left" else 0.0
    right = deflection_rad if side == "right" else 0.0
    return SensorFrame(
        t_us=t_us,
        ids=(SENSOR_LEFT, SENSOR_RIGHT),
        values=(left, right),
        units="rad,rad",
        signal_type=SignalType.WORLD_QUANTITY,
        provenance="E",
        assumption_ids=("SENS-04",),
        metadata={
            "scripted": True,
            "what_this_is_not": (
                "a measured deflection. The embodied run reads a free hinge; this is a "
                "declared scalar so the search needs no body."
            ),
        },
    )


def probe_grooming_operating_point(
    *,
    graph: SparseConnectome,
    atlas: SensoryAtlas,
    populations: Demo02Populations,
    signs: np.ndarray,
    base_parameters: dict[str, Any],
    candidate: dict[str, float],
    epochs: Sequence[GroomEpoch],
    deflection_rad: float,
    transducer_half_saturation: float,
    transducer_threshold: float,
    coupling_us: int,
    build_root: Path,
    seed: int,
    settle_fraction: float,
) -> dict[str, Any]:
    """Run one candidate through the scripted epochs and record what it did."""
    if not 0.0 <= settle_fraction < 1.0:
        raise ConfigurationError("settle_fraction must lie in [0, 1)")
    parameters = {**base_parameters, **candidate}
    kernel = {key: parameters[key] for key in KERNEL_KEYS if key in parameters}
    # The seed is in the build key. GeNN bakes it into the generated code, and omitting it
    # let three seeds share one compiled kernel elsewhere in this project.
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
        max_rate_hz=float(candidate["antennal_max_rate_hz"]),
        half_saturation=transducer_half_saturation,
        threshold=transducer_threshold,
    )
    bindings = tuple(
        ChannelBinding(
            key=key,
            sensor_id=SENSOR_LEFT if key.side == "L" else SENSOR_RIGHT,
            transducer=transducer,
            delay_us=0,
            kind="real",
            why="grooming search entry",
        )
        for key in entry_channels("grooming")
    )
    bus = SensoryBus(atlas=atlas, bindings=bindings, coupling_us=coupling_us)
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
            spikes: dict[str, int] = {LEFT: 0, RIGHT: 0}
            descending_hz: list[float] = []
            active_fraction: list[float] = []
            entry_driven: list[int] = []
            scored = 0
            for step in range(steps):
                frame = bus.encode(
                    t_us, _sensor_frame(t_us, epoch.side, deflection_rad)
                )
                engine.push_inputs(frame)
                t_us += coupling_us
                engine.step_until(t_us)
                raw = engine.read_outputs(readout_ids, coupling_us)
                counts = raw.metadata.get("spike_counts", {})
                activity = engine.population_activity(pools, coupling_us)
                if DESCENDING_POOL not in activity:
                    raise ConfigurationError(
                        f"Monitor pool {DESCENDING_POOL!r} is not recorded; available "
                        f"{sorted(activity)}. A criterion that cannot be measured must "
                        "stop the run, not score zero."
                    )
                if step >= settle:
                    scored += 1
                    for name in (LEFT, RIGHT):
                        for body in populations.readout[name]:
                            spikes[name] += int(counts.get(body, 0))
                    descending_hz.append(
                        float(activity[DESCENDING_POOL]["mean_rate_hz"])
                    )
                    active_fraction.append(
                        float(activity[DESCENDING_POOL]["active_fraction"])
                    )
                    entry_driven.append(
                        int(frame.metadata["entry_bodies_with_nonzero_rate"])
                    )
            duration_s = scored * coupling_us / 1_000_000.0
            measured[epoch.name] = {
                "scored_intervals": scored,
                "readout_spikes": dict(spikes),
                "readout_spikes_total": spikes[LEFT] + spikes[RIGHT],
                "readout_hz": (
                    (spikes[LEFT] + spikes[RIGHT]) / 6.0 / duration_s
                    if duration_s > 0 else 0.0
                ),
                "descending_mean_hz": (
                    float(np.mean(descending_hz)) if descending_hz else 0.0
                ),
                "descending_active_fraction": (
                    float(np.mean(active_fraction)) if active_fraction else 0.0
                ),
                "entry_bodies_driven": int(np.mean(entry_driven)) if entry_driven else 0,
            }
    finally:
        engine.close()
    return {
        "candidate": dict(candidate),
        "epochs": measured,
        "build_seconds": build_seconds,
        "simulation_seconds": time.perf_counter() - simulation_started,
    }


def score_grooming_candidate(
    measured: dict[str, Any], criteria: GroomCriteria
) -> dict[str, Any]:
    """Apply the five frozen criteria. Same shape and thresholds as the escape search."""
    epochs = measured["epochs"]
    baseline, left = epochs["baseline"], epochs["stimulus_left"]
    right, recovery = epochs["stimulus_right"], epochs["recovery"]

    ceiling = criteria.saturation_max_fraction * REFRACTORY_CEILING_HZ
    n1 = (
        baseline["readout_spikes_total"] <= criteria.baseline_max_readout_spikes
        and baseline["descending_mean_hz"] <= criteria.baseline_max_descending_hz
        and max(left["descending_mean_hz"], right["descending_mean_hz"]) <= ceiling
    )
    best = max(left["readout_spikes_total"], right["readout_spikes_total"])
    n2 = best >= criteria.min_response_readout_spikes

    index_left = selectivity_index(
        left["readout_spikes"][LEFT], left["readout_spikes"][RIGHT]
    )
    index_right = selectivity_index(
        right["readout_spikes"][LEFT], right["readout_spikes"][RIGHT]
    )
    swing = index_left - index_right
    reverses = (index_left > 0.0 > index_right) or (index_left < 0.0 < index_right)
    n3 = reverses and abs(swing) >= criteria.min_selectivity_swing

    evoked = max(left["readout_hz"], right["readout_hz"])
    base_hz = baseline["readout_hz"]
    allowed = base_hz + criteria.max_recovery_fraction * max(evoked - base_hz, 0.0)
    n4 = recovery["readout_hz"] <= allowed

    driven = max(
        left["descending_active_fraction"], right["descending_active_fraction"]
    )
    n5 = criteria.min_active_fraction <= driven <= criteria.max_active_fraction

    return {
        "N1_silent_and_stable_at_rest": bool(n1),
        "N2_responds_to_the_stimulus": bool(n2),
        "N3_side_selectivity_reverses": bool(n3),
        "N4_recovers_to_silence": bool(n4),
        "N5_the_network_is_alive_and_not_saturated": bool(n5),
        "passes": bool(n1 and n2 and n3 and n4 and n5),
        "values": {
            "baseline_readout_spikes": baseline["readout_spikes_total"],
            "baseline_descending_hz": baseline["descending_mean_hz"],
            "left_spikes": left["readout_spikes"],
            "right_spikes": right["readout_spikes"],
            "best_side_spikes": best,
            "selectivity_index_left": index_left,
            "selectivity_index_right": index_right,
            "selectivity_swing": swing,
            "selectivity_reverses": bool(reverses),
            "recovery_hz": recovery["readout_hz"],
            "recovery_allowed_hz": allowed,
            "driven_descending_hz": max(
                left["descending_mean_hz"], right["descending_mean_hz"]
            ),
            "saturation_ceiling_hz": ceiling,
            "driven_active_fraction": driven,
            "entry_bodies_driven": left["entry_bodies_driven"],
        },
    }


def select_operating_point(
    results: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Largest selectivity swing among passing candidates; ties to the least extreme."""
    passing = [r for r in results if r["score"]["passes"]]
    if not passing:
        return None
    return max(
        passing,
        key=lambda r: (
            abs(r["score"]["values"]["selectivity_swing"]),
            -float(r["candidate"]["antennal_max_rate_hz"]),
            -float(r["candidate"]["synaptic_mv_per_contact"]),
        ),
    )
