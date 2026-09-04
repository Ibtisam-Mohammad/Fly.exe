# SPDX-License-Identifier: GPL-2.0-or-later
"""Construct simulation components exclusively from registered assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flysim.config import ScenarioConfig, project_root
from flysim.engines.body import KinematicBodyEngine, KinematicParameters
from flysim.engines.reference import ReferenceNeuralEngine
from flysim.provenance import AssumptionRegistry
from flysim.scenario import EonDemoController, controller_parameters
from flysim.scheduler import CausalScheduler


@dataclass(frozen=True, slots=True)
class ReferenceDemo:
    scenario: ScenarioConfig
    registry: AssumptionRegistry
    scheduler: CausalScheduler
    duration_us: int


def _merged(*values: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for value in values:
        duplicate = output.keys() & value.keys()
        if duplicate:
            raise ValueError(f"Duplicate registered parameter keys: {sorted(duplicate)}")
        output.update(value)
    return output


def build_reference_demo(
    seed: int,
    ablated_inputs: frozenset[str] = frozenset(),
    ablated_outputs: frozenset[str] = frozenset(),
    assumptions_path: Path | None = None,
    scenario_path: Path | None = None,
) -> ReferenceDemo:
    root = project_root()
    registry = AssumptionRegistry.load(assumptions_path or root / "configs" / "assumptions.json")
    scenario = ScenarioConfig.load(
        scenario_path or root / "configs" / "scenarios" / "eon-demo.json"
    )
    registry.require(*scenario.required_assumptions)
    if registry.assumption_set_id != scenario.assumption_set:
        raise ValueError(
            f"Scenario expects assumption set {scenario.assumption_set}, "
            f"found {registry.assumption_set_id}"
        )

    timing = registry.value_map("NUM-01")
    neural_values = _merged(timing, registry.value_map("ND-08"))
    neural = ReferenceNeuralEngine(ablated_inputs, ablated_outputs)
    neural.initialize(graph=None, parameters=neural_values, seed=seed)

    body_values = _merged(
        {"physics_dt_us": timing["physics_dt_us"]},
        registry.value_map("BODY-01"),
        {
            key: registry.value_map("SENS-03")[key]
            for key in (
                "source_strength",
                "softening_mm2",
                "half_saturation",
                "antenna_separation_mm",
            )
        },
        {
            key: registry.value_map("SENS-04")[key]
            for key in (
                "dust_deposition_per_s",
                "dust_exposure_cap",
                "single_dust_exposure",
                "groom_removal_per_s",
                "food_contact_radius_mm",
            )
        },
    )
    body = KinematicBodyEngine(KinematicParameters(**body_values))
    controller = EonDemoController(
        controller_parameters(
            registry.value_map("MOTOR-03"), registry.value_map("SENS-04")
        )
    )
    scheduler = CausalScheduler(
        neural=neural,
        body=body,
        controller=controller,
        coupling_us=int(timing["track_a_coupling_us"]),
    )
    duration_us = int(registry.value_map("DEMO-01")["duration_us"])
    return ReferenceDemo(
        scenario=scenario,
        registry=registry,
        scheduler=scheduler,
        duration_us=duration_us,
    )
