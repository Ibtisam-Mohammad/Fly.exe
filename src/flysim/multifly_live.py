# SPDX-License-Identifier: GPL-2.0-or-later
"""Factories for controller-preview and full-MaleCNS interactive multi-fly runtimes."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, project_root, sha256_json
from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, NeuralInputFrame, NeuralOutputFrame
from flysim.demo01 import FilteredDescendingReadout, ReadoutParameters
from flysim.demo01_visual import (
    RetinaMap,
    RetinotopicVisualEncoder,
    VisualCue,
    VisualDecoderParameters,
    VisualEncodingParameters,
    VisualLocomotorDecoder,
)
from flysim.demo01_visual_probe import resolve_visual_populations
from flysim.engines.genn import TrackAGeNNEngine
from flysim.errors import ConfigurationError, ReadinessError
from flysim.multifly import (
    ArenaObservation,
    ControllerOnlyPolicy,
    FlyAgentState,
    FlyMode,
    MultiFlyArenaParameters,
    MultiFlyCoordinator,
    NeuralCohort,
    SharedKinematicArena,
    StimulusKind,
    WorldStimulus,
)
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.runs import git_metadata


class Demo01VisualPipeline:
    """World geometry to lamina, full graph to DN readout, DN-only motor decoder."""

    def __init__(
        self,
        *,
        encoder: RetinotopicVisualEncoder,
        readout: FilteredDescendingReadout,
        decoder: VisualLocomotorDecoder,
        output_ids: tuple[int, ...],
        stimulus_ablated: bool = False,
        cue_enable_us: int = 0,
    ) -> None:
        self.encoder = encoder
        self.readout = readout
        self.decoder = decoder
        self.output_ids: tuple[str | int, ...] = output_ids
        self.stimulus_ablated = stimulus_ablated
        self.cue_enable_us = cue_enable_us

    def encode(self, observation: ArenaObservation) -> NeuralInputFrame:
        target = (
            None
            if self.stimulus_ablated or observation.t_us < self.cue_enable_us
            else observation.primary_target
        )
        cue = (
            VisualCue(
                x_mm=target.x_mm,
                y_mm=target.y_mm,
                radius_mm=target.radius_mm,
            )
            if target is not None
            else None
        )
        frame = self.encoder.encode(
            observation.t_us,
            cue,
            x_mm=observation.x_mm,
            y_mm=observation.y_mm,
            heading_rad=observation.heading_rad,
        )
        return replace(
            frame,
            metadata={
                **frame.metadata,
                "interactive_world_revision": (
                    target.revision if target is not None else None
                ),
                "stimulus_ablated": self.stimulus_ablated,
                "cue_enable_us": self.cue_enable_us,
                "cue_temporally_enabled": observation.t_us >= self.cue_enable_us,
            },
        )

    def decode(self, frame: NeuralOutputFrame) -> ActuatorCommandFrame:
        filtered = self.readout.read(frame)
        command = self.decoder.decode(filtered)
        return replace(
            command,
            metadata={
                **command.metadata,
                "source": "full-malecns-descending-readout",
                "target_coordinates_available": False,
                "full_graph": bool(frame.metadata.get("full_graph")),
                "batch_index": frame.metadata.get("batch_index"),
            },
        )


class InteractiveMultiFlyRuntime:
    """Thread-safe boundary used by the HTTP/WebSocket service."""

    def __init__(
        self,
        coordinator: MultiFlyCoordinator,
        *,
        execution_mode: str,
        closeables: Sequence[Any] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.execution_mode = execution_mode
        self._closeables = tuple(closeables)
        self._metadata = dict(metadata or {})
        self._lock = threading.RLock()

    @property
    def t_us(self) -> int:
        return self.coordinator.t_us

    def place_stimulus(
        self,
        *,
        stimulus_id: str,
        kind: str,
        x_mm: float,
        y_mm: float,
        radius_mm: float,
        strength: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            self.coordinator.place_stimulus(
                WorldStimulus(
                    stimulus_id=stimulus_id,
                    kind=StimulusKind(kind),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    radius_mm=radius_mm,
                    strength=strength,
                )
            )
            return self.snapshot()

    def remove_stimulus(self, stimulus_id: str) -> dict[str, Any]:
        with self._lock:
            self.coordinator.remove_stimulus(stimulus_id)
            return self.snapshot()

    def step(self) -> dict[str, Any]:
        with self._lock:
            return self._decorate(self.coordinator.step())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._decorate(self.coordinator.snapshot())

    def _decorate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            "execution_mode": self.execution_mode,
            "runtime": dict(self._metadata),
        }

    def close(self) -> None:
        with self._lock:
            for value in reversed(self._closeables):
                close = getattr(value, "close", None)
                if close is not None:
                    close()


def _arena_parameters(raw: Mapping[str, Any]) -> MultiFlyArenaParameters:
    return MultiFlyArenaParameters(
        **{
            name: raw[name]
            for name in MultiFlyArenaParameters.__dataclass_fields__
            if name in raw
        }
    )


def _flies(raw: Sequence[Mapping[str, Any]]) -> list[FlyAgentState]:
    return [
        FlyAgentState(
            fly_id=str(item["id"]),
            mode=FlyMode(str(item["mode"])),
            x_mm=float(item["x_mm"]),
            y_mm=float(item["y_mm"]),
            heading_rad=float(item.get("heading_rad", 0.0)),
            radius_mm=float(item.get("radius_mm", 1.25)),
            color=str(item.get("color", "#55d6be")),
        )
        for item in raw
    ]


def _place_initial_stimuli(
    coordinator: MultiFlyCoordinator, raw: Sequence[Mapping[str, Any]]
) -> None:
    for item in raw:
        coordinator.place_stimulus(
            WorldStimulus(
                stimulus_id=str(item["id"]),
                kind=StimulusKind(str(item["kind"])),
                x_mm=float(item["x_mm"]),
                y_mm=float(item["y_mm"]),
                radius_mm=float(item["radius_mm"]),
                strength=float(item.get("strength", 1.0)),
                remaining=float(item.get("remaining", 1.0)),
            )
        )


def build_preview_runtime(
    scenario_path: Path | None = None,
) -> InteractiveMultiFlyRuntime:
    """CPU-only interactive shell. It explicitly contains no neural engine."""
    path = scenario_path or project_root() / "configs/scenarios/multifly-web.json"
    scenario = load_json(path)
    arena = SharedKinematicArena(
        _arena_parameters(scenario["arena"]), _flies(scenario["preview_flies"])
    )
    policies = {
        fly_id: ControllerOnlyPolicy()
        for fly_id, fly in arena.flies.items()
        if fly.mode is FlyMode.CONTROLLER_ONLY
    }
    coordinator = MultiFlyCoordinator(
        arena=arena,
        coupling_us=int(scenario["coupling_us"]),
        controller_policies=policies,
    )
    _place_initial_stimuli(coordinator, scenario.get("initial_stimuli", []))
    return InteractiveMultiFlyRuntime(
        coordinator,
        execution_mode="controller-preview-no-cns",
        metadata={
            "scenario": str(path),
            "scenario_sha256": sha256_json(scenario),
            "full_graph": False,
            "warning": "CPU preview only; no neural graph is loaded or implied.",
        },
    )


def _shuffled_graph(graph: SparseConnectome, seed: int) -> SparseConnectome:
    rng = np.random.default_rng(seed)
    targets = np.array(graph.target_indices, copy=True)
    rng.shuffle(targets)
    shuffled = SparseConnectome(
        body_ids=np.array(graph.body_ids, copy=True),
        source_indices=np.array(graph.source_indices, copy=True),
        target_indices=targets,
        contact_counts=np.array(graph.contact_counts, copy=True),
        source_release=graph.source_release,
        source_sha256=graph.source_sha256,
    )
    shuffled.validate()
    return shuffled


def _pipeline(
    *,
    populations: Any,
    parameters: Mapping[str, Any],
    contract: Mapping[str, Any],
    decoder_parameters: VisualDecoderParameters,
    stimulus_ablated: bool,
) -> Demo01VisualPipeline:
    return Demo01VisualPipeline(
        encoder=RetinotopicVisualEncoder(
            populations,
            VisualEncodingParameters.from_mapping(dict(parameters)),
            RetinaMap.from_mapping(dict(contract["retina_map"])),
        ),
        readout=FilteredDescendingReadout(
            populations,
            ReadoutParameters.from_mapping(dict(contract["readout"])),
        ),
        decoder=VisualLocomotorDecoder(decoder_parameters),
        output_ids=populations.readout_body_ids,
        stimulus_ablated=stimulus_ablated,
        cue_enable_us=decoder_parameters.quiescent_us,
    )


def build_full_cns_runtime(
    *,
    data_root: Path,
    scenario_path: Path | None = None,
    contract_path: Path | None = None,
    operating_point_path: Path | None = None,
    seed: int = 1,
    include_shuffled: bool = False,
    neural_copies: int | None = None,
) -> InteractiveMultiFlyRuntime:
    """Build the full-graph causal visual cohort and labelled comparison flies.

    Exact and sensory-ablated flies share one graph allocation. A shuffled fly needs a
    second graph allocation and is opt-in because it is unlikely to fit beside the exact
    graph on a 12 GB GPU. The default live comparison therefore uses exact,
    sensory-ablated, controller-only and passive agents.
    """
    scenario_file = scenario_path or project_root() / "configs/scenarios/multifly-web.json"
    contract_file = (
        contract_path
        or project_root() / "configs/experiments/demo01-visual-operating-point-v1.json"
    )
    operating_file = (
        operating_point_path
        or data_root / "evidence/demo01/demo01-visual-operating-point-v1.json"
    )
    if not operating_file.is_file():
        raise ReadinessError(f"Frozen DEMO-01 operating point is missing: {operating_file}")
    scenario = load_json(scenario_file)
    contract = load_json(contract_file)
    operating_artifact = load_json(operating_file)
    selected = operating_artifact.get("selected")
    if not isinstance(selected, dict) or not selected:
        raise ReadinessError("The frozen visual search selected no operating point")
    parameters = {**contract["fixed_parameters"], **selected}

    graph_path = data_root / "derived/male-cns-v1.0/graph"
    annotations_path = (
        data_root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    transmitter_path = (
        data_root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"
    )
    graph = SparseConnectome.load(graph_path)
    graph.validate()
    populations = resolve_visual_populations(annotations_path, graph)
    signs = build_shiu_regression_signs(
        graph,
        transmitter_path,
        unresolved_policy=UnresolvedSignPolicy(str(contract["unresolved_sign_policy"])),
        seed=seed,
    ).edge_signs

    if neural_copies is not None:
        if not 1 <= neural_copies <= 16:
            raise ConfigurationError("Neural benchmark copy count must lie in [1, 16]")
        fly_records: list[Mapping[str, Any]] = [
            {
                "id": f"full-{index + 1}",
                "mode": "full-cns",
                "x_mm": -18.0,
                "y_mm": (index - (neural_copies - 1) / 2.0) * 3.5,
                "heading_rad": 0.0,
                "color": "#55d6be",
            }
            for index in range(neural_copies)
        ]
        include_shuffled = False
    else:
        fly_records = list(scenario["full_cns_flies"])
    if not include_shuffled:
        fly_records = [
            item
            for item in fly_records
            if FlyMode(str(item["mode"])) is not FlyMode.SHUFFLED_CONNECTOME
        ]
    arena = SharedKinematicArena(
        _arena_parameters(scenario["arena"]), _flies(fly_records)
    )
    decoder_parameters = VisualDecoderParameters.from_mapping(scenario["decoder"])
    cohorts: list[NeuralCohort] = []
    closeables: list[TrackAGeNNEngine] = []

    exact_ids = tuple(
        fly.fly_id
        for fly in arena.flies.values()
        if fly.mode in {FlyMode.FULL_CNS, FlyMode.SENSORY_ABLATED}
    )
    if exact_ids:
        build_key = sha256_json(
            {
                "parameters": parameters,
                "graph": graph.source_sha256,
                "batch_size": len(exact_ids),
                "variant": "exact",
            }
        )[:16]
        engine = TrackAGeNNEngine(
            data_root / "build/multifly" / build_key,
            variant="exact",
            batch_size=len(exact_ids),
            batch_labels=exact_ids,
        )
        engine.initialize(
            graph,
            {
                **parameters,
                "functional_edge_signs": signs,
                "entry_body_ids": populations.entry_body_ids,
            },
            seed,
        )
        pipelines = {
            fly_id: _pipeline(
                populations=populations,
                parameters=parameters,
                contract=contract,
                decoder_parameters=decoder_parameters,
                stimulus_ablated=(
                    arena.flies[fly_id].mode is FlyMode.SENSORY_ABLATED
                ),
            )
            for fly_id in exact_ids
        }
        cohorts.append(NeuralCohort("exact-malecns", engine, pipelines))
        closeables.append(engine)

    shuffled_ids = tuple(
        fly.fly_id
        for fly in arena.flies.values()
        if fly.mode is FlyMode.SHUFFLED_CONNECTOME
    )
    if shuffled_ids:
        shuffled = _shuffled_graph(graph, seed)
        wiring = hashlib.sha256(shuffled.target_indices.astype("<u4").tobytes()).hexdigest()
        build_key = sha256_json(
            {
                "parameters": parameters,
                "graph": graph.source_sha256,
                "wiring": wiring,
                "batch_size": len(shuffled_ids),
                "variant": "shuffled-connectome",
            }
        )[:16]
        engine = TrackAGeNNEngine(
            data_root / "build/multifly" / build_key,
            variant="shuffled-connectome",
            batch_size=len(shuffled_ids),
            batch_labels=shuffled_ids,
        )
        engine.initialize(
            shuffled,
            {
                **parameters,
                "functional_edge_signs": signs,
                "entry_body_ids": populations.entry_body_ids,
            },
            seed,
        )
        pipelines = {
            fly_id: _pipeline(
                populations=populations,
                parameters=parameters,
                contract=contract,
                decoder_parameters=decoder_parameters,
                stimulus_ablated=False,
            )
            for fly_id in shuffled_ids
        }
        cohorts.append(NeuralCohort("shuffled-diagnostic", engine, pipelines))
        closeables.append(engine)

    policies = {
        fly_id: ControllerOnlyPolicy()
        for fly_id, fly in arena.flies.items()
        if fly.mode is FlyMode.CONTROLLER_ONLY
    }
    coordinator = MultiFlyCoordinator(
        arena=arena,
        coupling_us=int(scenario["coupling_us"]),
        neural_cohorts=cohorts,
        controller_policies=policies,
    )
    _place_initial_stimuli(coordinator, scenario.get("initial_stimuli", []))
    worktree = git_metadata()
    return InteractiveMultiFlyRuntime(
        coordinator,
        execution_mode="full-malecns-batched",
        closeables=closeables,
        metadata={
            "scenario": str(scenario_file),
            "scenario_sha256": sha256_json(scenario),
            "contract": str(contract_file),
            "contract_sha256": sha256_json(contract),
            "operating_point": str(operating_file),
            "operating_point_sha256": sha256_json(operating_artifact),
            "code_commit": worktree.get("commit"),
            "worktree_dirty": worktree.get("dirty"),
            "full_graph": True,
            "neurons_per_neural_fly": graph.neuron_count,
            "edges_shared_per_cohort": graph.edge_count,
            "neural_cohorts": len(cohorts),
            "shuffled_enabled": bool(shuffled_ids),
            "body_backend": "shared-kinematic-collision-discs",
            "validation_tier_awarded": None,
        },
    )


__all__ = [
    "Demo01VisualPipeline",
    "InteractiveMultiFlyRuntime",
    "build_full_cns_runtime",
    "build_preview_runtime",
]
