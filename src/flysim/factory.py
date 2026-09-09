# SPDX-License-Identifier: GPL-2.0-or-later
"""Construct simulation components exclusively from registered assumptions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from flysim.circuit import load_cell_types
from flysim.config import ScenarioConfig, project_root
from flysim.connectome import SparseConnectome
from flysim.dynamics import DynamicsRegistry
from flysim.engines.body import KinematicBodyEngine, KinematicParameters
from flysim.engines.flygym import FlyGymTrackABodyEngine, FlyGymTrackAParameters
from flysim.engines.genn import TrackAGeNNEngine
from flysim.engines.reference import ReferenceNeuralEngine
from flysim.errors import ConfigurationError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.provenance import AssumptionRegistry
from flysim.scenario import EonDemoController, controller_parameters
from flysim.scheduler import CausalScheduler
from flysim.track_a import (
    TrackAEncodingParameters,
    TrackAPopulationEncoder,
    TrackAPopulationMap,
    TrackAPopulationReadout,
)


@dataclass(frozen=True, slots=True)
class ReferenceDemo:
    scenario: ScenarioConfig
    registry: AssumptionRegistry
    scheduler: CausalScheduler
    duration_us: int


@dataclass(frozen=True, slots=True)
class TrackADemo:
    scenario: ScenarioConfig
    registry: AssumptionRegistry
    scheduler: CausalScheduler
    duration_us: int
    graph: SparseConnectome
    populations: TrackAPopulationMap
    neural: TrackAGeNNEngine
    body: FlyGymTrackABodyEngine
    variant: str


def _merged(*values: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for value in values:
        duplicate = output.keys() & value.keys()
        if duplicate:
            raise ValueError(f"Duplicate registered parameter keys: {sorted(duplicate)}")
        output.update(value)
    return output


def _require_registered_effective_delays(
    scheduler: CausalScheduler, timing: dict[str, Any]
) -> None:
    """Refuse to run unless NUM-01 declares the delays the loop actually realises.

    Delay queues are polled once per coupling interval, so a registered 2 ms interface
    delay is realised as one 15 ms coupling cycle. The realised values are registered
    explicitly so that the manifest, the register, and the loop cannot drift apart.
    """
    expected = {
        "effective_sensory_delay_us": scheduler.effective_sensory_delay_us,
        "effective_motor_delay_us": scheduler.effective_motor_delay_us,
    }
    for key, realised in expected.items():
        if key not in timing:
            raise ConfigurationError(f"NUM-01 must register {key}")
        if int(timing[key]) != realised:
            raise ConfigurationError(
                f"NUM-01 registers {key}={timing[key]} but the scheduler realises {realised} "
                f"at a {scheduler.coupling_us} us coupling interval"
            )


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

    body_registry = registry.value_map("BODY-01")
    body_values = _merged(
        {"physics_dt_us": timing["physics_dt_us"]},
        {
            key: body_registry[key]
            for key in (
                "initial_x_mm",
                "initial_y_mm",
                "initial_heading_rad",
                "food_x_mm",
                "food_y_mm",
                "dust_x_mm",
                "dust_y_mm",
                "dust_radius_mm",
            )
        },
        {
            key: registry.value_map("MOTOR-03")[key]
            for key in ("max_forward_mm_s", "max_yaw_rad_s")
        },
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
        sensory_delay_us=int(timing["sensory_delay_us"]),
        motor_delay_us=int(timing["motor_delay_us"]),
    )
    _require_registered_effective_delays(scheduler, timing)
    duration_us = int(registry.value_map("DEMO-01")["duration_us"])
    return ReferenceDemo(
        scenario=scenario,
        registry=registry,
        scheduler=scheduler,
        duration_us=duration_us,
    )


def _track_a_graph_variant(
    graph: SparseConnectome, variant: str, seed: int
) -> SparseConnectome:
    if variant in {"exact", "zero-weight"}:
        return graph
    if variant != "shuffled-connectome":
        raise ValueError(f"Unsupported Track A graph variant: {variant}")
    import hashlib

    import numpy as np

    rng = np.random.default_rng(seed)
    targets = np.array(graph.target_indices, copy=True)
    rng.shuffle(targets)
    identity = hashlib.sha256()
    identity.update(graph.source_sha256.encode())
    identity.update(targets.astype("<u4", copy=False).tobytes())
    shuffled = SparseConnectome(
        body_ids=graph.body_ids,
        source_indices=graph.source_indices,
        target_indices=targets,
        contact_counts=graph.contact_counts,
        source_release=graph.source_release,
        source_sha256=f"shuffled:{identity.hexdigest()}",
    )
    shuffled.validate()
    return shuffled


def build_track_a_demo(
    *,
    seed: int,
    graph_path: Path,
    population_resolution_path: Path,
    transmitter_path: Path,
    grooming_trajectory_path: Path,
    build_path: Path,
    variant: str = "exact",
    ablated_inputs: frozenset[str] = frozenset(),
    ablated_outputs: frozenset[str] = frozenset(),
    food_position_mm: tuple[float, float] | None = None,
    render: bool = False,
    fps: int = 30,
    suppress_groom_replay: bool = False,
    assumptions_path: Path | None = None,
    scenario_path: Path | None = None,
    dynamics_registry_path: Path | None = None,
    annotations_path: Path | None = None,
) -> TrackADemo:
    """Build the full-graph Track A simulation from immutable registered inputs."""
    root = project_root()
    registry = AssumptionRegistry.load(assumptions_path or root / "configs" / "assumptions.json")
    scenario = ScenarioConfig.load(
        scenario_path or root / "configs" / "scenarios" / "eon-malecns.json"
    )
    registry.require(*scenario.required_assumptions)
    if registry.assumption_set_id != scenario.assumption_set:
        raise ValueError(
            f"Scenario expects assumption set {scenario.assumption_set}, "
            f"found {registry.assumption_set_id}"
        )
    graph = _track_a_graph_variant(SparseConnectome.load(graph_path), variant, seed)
    populations = TrackAPopulationMap.load(population_resolution_path)
    track_a_values = registry.value_map("TRACKA-01")
    sign_policy = UnresolvedSignPolicy(str(track_a_values["unresolved_sign_policy"]))
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=sign_policy,
        seed=seed,
    ).edge_signs
    if variant == "zero-weight":
        import numpy as np

        signs = np.zeros(graph.edge_count, dtype=np.float32)
    # Type-resolved membrane parameters are opt-in. Without a registry the engine keeps the
    # single global Shiu-style LIF, so an existing Track A run is bit-for-bit unchanged.
    cell_parameters: dict[str, Any] = {}
    if dynamics_registry_path is not None:
        if annotations_path is None:
            raise ValueError(
                "A dynamics registry needs the body-annotation table to resolve cell types"
            )
        cell_types = load_cell_types(annotations_path, graph.body_ids)
        resolution = DynamicsRegistry.load(dynamics_registry_path).resolve_parameters(cell_types)
        cell_parameters = {
            "per_neuron_parameters": resolution.parameter_arrays,
            "signal_regimes": tuple(
                regime.value for regime in resolution.signal_regimes
            ),
            "cell_parameter_report": resolution.as_dict(),
        }
    neural = TrackAGeNNEngine(build_path, variant=variant)
    neural.initialize(
        graph,
        {
            **track_a_values,
            **cell_parameters,
            "functional_edge_signs": signs,
            "entry_body_ids": tuple(
                dict.fromkeys(
                    body_id
                    for population_id in (
                        "ethyl-acetate-receptor-entry",
                        "grooming-jo-f",
                        "sucrose-receptor-entry",
                    )
                    for body_id in populations.body_ids[population_id]
                )
            ),
        },
        seed,
    )
    encoder = TrackAPopulationEncoder(
        populations,
        TrackAEncodingParameters.from_mapping(track_a_values),
        ablated_sensor_ids=ablated_inputs,
    )
    readout = TrackAPopulationReadout(populations, ablated_output_ids=ablated_outputs)

    timing = registry.value_map("NUM-01")
    body_values = registry.value_map("BODY-01")
    motor_values = registry.value_map("MOTOR-03")
    sensory_odor = registry.value_map("SENS-03")
    sensory_contact = registry.value_map("SENS-04")
    parameters = FlyGymTrackAParameters(
        **body_values,
        physics_dt_us=int(timing["physics_dt_us"]),
        **{
            key: sensory_odor[key]
            for key in (
                "source_strength",
                "softening_mm2",
                "half_saturation",
                "antenna_separation_mm",
            )
        },
        **{
            key: sensory_contact[key]
            for key in (
                "dust_deposition_per_s",
                "dust_exposure_cap",
                "single_dust_exposure",
                "groom_removal_per_s",
                "food_contact_radius_mm",
            )
        },
        **{
            key: motor_values[key]
            for key in (
                "max_forward_mm_s",
                "max_yaw_rad_s",
                "feed_rostrum_extension_rad",
                "feed_haustellum_extension_rad",
                "groom_blend_in_us",
            )
        },
        **registry.value_map("MOTOR-04"),
    )
    if food_position_mm is not None:
        parameters = replace(
            parameters,
            food_x_mm=float(food_position_mm[0]),
            food_y_mm=float(food_position_mm[1]),
        )
    body = FlyGymTrackABodyEngine(
        parameters,
        grooming_trajectory_path,
        seed=seed,
        render=render,
        fps=fps,
        suppress_groom_replay=suppress_groom_replay,
    )
    controller = EonDemoController(
        controller_parameters(motor_values, sensory_contact)
    )
    scheduler = CausalScheduler(
        neural=neural,
        body=body,
        controller=controller,
        coupling_us=int(timing["track_a_coupling_us"]),
        sensory_delay_us=int(timing["sensory_delay_us"]),
        motor_delay_us=int(timing["motor_delay_us"]),
        population_encoder=encoder,
        population_readout=readout,
        output_ids=populations.output_body_ids,
    )
    _require_registered_effective_delays(scheduler, timing)
    return TrackADemo(
        scenario=scenario,
        registry=registry,
        scheduler=scheduler,
        duration_us=int(registry.value_map("DEMO-01")["duration_us"]),
        graph=graph,
        populations=populations,
        neural=neural,
        body=body,
        variant=variant,
    )
