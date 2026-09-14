# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from flysim.cli import build_parser
from flysim.connectome import SparseConnectome
from flysim.contracts import ActuatorCommandFrame, NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.engines.body import BEHAVIOUR_COMMAND_IDS, COMMAND_FORWARD, COMMAND_PROBOSCIS
from flysim.engines.genn import TrackAGeNNEngine, TrackAGeNNParameters
from flysim.errors import ConfigurationError
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
from flysim.multifly_live import Demo01VisualPipeline, build_preview_runtime
from flysim.web_demo import ALLOWED_CLIENT_COMMANDS, LiveDemoService, create_app


def _command(t_us: int, *, forward: float = 0.0, proboscis: float = 0.0) -> ActuatorCommandFrame:
    values = {
        COMMAND_FORWARD: forward,
        COMMAND_PROBOSCIS: proboscis,
    }
    return ActuatorCommandFrame(
        t_us=t_us,
        ids=BEHAVIOUR_COMMAND_IDS,
        values=tuple(values.get(identifier, 0.0) for identifier in BEHAVIOUR_COMMAND_IDS),
        units="normalized engineering commands",
        signal_type=SignalType.ACTUATOR_COMMAND,
        provenance="E",
        assumption_ids=("MULTI-01",),
    )


def _arena(*flies: FlyAgentState) -> SharedKinematicArena:
    return SharedKinematicArena(
        MultiFlyArenaParameters(physics_dt_us=1_000),
        flies,
    )


def test_shared_odor_is_body_local_and_controller_never_gets_target_coordinates() -> None:
    arena = _arena(
        FlyAgentState("fly", FlyMode.CONTROLLER_ONLY, 0.0, 0.0, 0.0)
    )
    arena.place_stimulus(
        WorldStimulus("food", StimulusKind.FOOD, 5.0, 2.0, 1.0)
    )
    observation = arena.observe("fly")
    assert observation.odor_left > observation.odor_right
    assert "x_mm" not in observation.controller_view()
    assert "y_mm" not in observation.controller_view()
    command = ControllerOnlyPolicy().decode(observation, command_t_us=15_000)
    assert command.metadata["target_coordinates_available"] is False
    assert not any(
        "target" in str(key) and "coordinate" not in str(key)
        for key in command.metadata
    )


def test_collision_discs_do_not_pass_through_a_passive_fly() -> None:
    arena = _arena(
        FlyAgentState("moving", FlyMode.CONTROLLER_ONLY, -2.6, 0.0, 0.0),
        FlyAgentState("passive", FlyMode.PASSIVE, 0.0, 0.0, 0.0),
    )
    arena.apply_command("moving", _command(0, forward=1.0))
    arena.apply_command("passive", _command(0))
    arena.step_until(100_000)
    moving = arena.flies["moving"]
    passive = arena.flies["passive"]
    distance = np.hypot(moving.x_mm - passive.x_mm, moving.y_mm - passive.y_mm)
    assert distance + 1e-9 >= moving.radius_mm + passive.radius_mm
    assert "passive" in moving.contacts


def test_food_depletion_requires_contact_and_proboscis_command() -> None:
    arena = _arena(
        FlyAgentState("feeding", FlyMode.CONTROLLER_ONLY, 0.0, 0.0, 0.0),
        FlyAgentState("far", FlyMode.CONTROLLER_ONLY, -10.0, 0.0, 0.0),
    )
    arena.place_stimulus(WorldStimulus("food", StimulusKind.FOOD, 0.0, 0.0, 1.0))
    arena.apply_command("feeding", _command(0, proboscis=0.0))
    arena.apply_command("far", _command(0, proboscis=1.0))
    arena.step_until(100_000)
    assert arena.stimuli["food"].remaining == 1.0
    arena.apply_command("feeding", _command(100_000, proboscis=1.0))
    arena.apply_command("far", _command(100_000, proboscis=1.0))
    arena.step_until(200_000)
    assert arena.stimuli["food"].remaining < 1.0
    assert arena.flies["feeding"].food_consumed > 0.0
    assert arena.flies["far"].food_consumed == 0.0


class _FakeBatchEngine:
    def __init__(self, labels: tuple[str, ...]) -> None:
        self.batch_labels = labels
        self.batch_size = len(labels)
        self._t_us = 0
        self.pushed: list[tuple[NeuralInputFrame, ...]] = []

    @property
    def t_us(self) -> int:
        return self._t_us

    def push_batch_inputs(self, frames: Sequence[NeuralInputFrame]) -> None:
        self.pushed.append(tuple(frames))

    def step_until(self, t_us: int) -> None:
        self._t_us = t_us

    def read_batch_outputs(
        self, ids: tuple[str | int, ...], window_us: int
    ) -> tuple[NeuralOutputFrame, ...]:
        return tuple(
            NeuralOutputFrame(
                t_us=self._t_us,
                ids=ids,
                values=(4.0, 2.0),
                units="Hz",
                signal_type=SignalType.FIRING_RATE,
                provenance="M/P/E",
                assumption_ids=("ND-01",),
                metadata={
                    "window_us": window_us,
                    "batch_index": index,
                    "model_identity": "fake-shared-graph",
                    "full_graph": True,
                },
            )
            for index in range(self.batch_size)
        )

    def checkpoint(self) -> dict[str, Any]:
        return {"batch_size": self.batch_size, "connectivity_allocations": 1}


class _FakePipeline:
    output_ids: tuple[str | int, ...] = ("left", "right")

    def __init__(self, *, ablated: bool = False) -> None:
        self.ablated = ablated

    def encode(self, observation: ArenaObservation) -> NeuralInputFrame:
        value = 0.0 if self.ablated else observation.odor_left
        return NeuralInputFrame(
            t_us=observation.t_us,
            ids=(101,),
            values=(value,),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="E",
            assumption_ids=("MULTI-01",),
        )

    def decode(self, frame: NeuralOutputFrame) -> ActuatorCommandFrame:
        return _command(frame.t_us, forward=1.0)


class _CueCapturingEncoder:
    def __init__(self) -> None:
        self.cues: list[Any] = []

    def encode(
        self,
        t_us: int,
        cue: Any,
        *,
        x_mm: float,
        y_mm: float,
        heading_rad: float,
    ) -> NeuralInputFrame:
        del x_mm, y_mm, heading_rad
        self.cues.append(cue)
        return NeuralInputFrame(
            t_us=t_us,
            ids=(10,),
            values=(0.0,),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="E",
            assumption_ids=("MULTI-01",),
        )


def test_live_visual_cue_begins_after_the_decoder_quiescent_window() -> None:
    encoder = _CueCapturingEncoder()
    pipeline = Demo01VisualPipeline(
        encoder=encoder,  # type: ignore[arg-type]
        readout=object(),  # type: ignore[arg-type]
        decoder=object(),  # type: ignore[arg-type]
        output_ids=(),
        cue_enable_us=100,
    )
    target = WorldStimulus("target", StimulusKind.VISUAL_TARGET, 4.0, 2.0, 1.0)
    base = {
        "fly_id": "exact",
        "x_mm": 0.0,
        "y_mm": 0.0,
        "heading_rad": 0.0,
        "odor_left": 0.0,
        "odor_right": 0.0,
        "food_contact": False,
        "fly_contacts": (),
        "primary_target": target,
    }
    before = pipeline.encode(ArenaObservation(t_us=99, **base))
    enabled = pipeline.encode(ArenaObservation(t_us=100, **base))
    assert encoder.cues[0] is None
    assert encoder.cues[1] is not None
    assert before.metadata["cue_temporally_enabled"] is False
    assert enabled.metadata["cue_temporally_enabled"] is True


def test_cohort_is_pushed_once_and_first_interval_remains_at_zero_command() -> None:
    arena = _arena(
        FlyAgentState("exact", FlyMode.FULL_CNS, 0.0, -3.0, 0.0),
        FlyAgentState("ablated", FlyMode.SENSORY_ABLATED, 0.0, 3.0, 0.0),
    )
    arena.place_stimulus(WorldStimulus("food", StimulusKind.FOOD, 10.0, 0.0, 1.0))
    engine = _FakeBatchEngine(("exact", "ablated"))
    cohort = NeuralCohort(
        "exact",
        engine,
        {"exact": _FakePipeline(), "ablated": _FakePipeline(ablated=True)},
    )
    coordinator = MultiFlyCoordinator(
        arena=arena,
        coupling_us=15_000,
        neural_cohorts=(cohort,),
    )
    first = coordinator.step()
    assert len(engine.pushed) == 1
    assert engine.pushed[0][0].values[0] > 0.0
    assert engine.pushed[0][1].values[0] == 0.0
    assert first["arena"]["flies"][0]["path_length_mm"] == 0.0
    second = coordinator.step()
    assert all(fly["path_length_mm"] > 0.0 for fly in second["arena"]["flies"])
    assert second["neural"]["cohorts"][0]["checkpoint"]["connectivity_allocations"] == 1
    assert all(
        not command["target_coordinates_available"]
        for command in second["pending_commands"].values()
    )


class _FakeVariable:
    def __init__(self, view: np.ndarray) -> None:
        self.view = view
        self.pushes = 0
        self.pulls = 0

    def push_to_device(self) -> None:
        self.pushes += 1

    def pull_from_device(self) -> None:
        self.pulls += 1


class _FakePopulation:
    def __init__(self, counts: np.ndarray) -> None:
        self.vars = {"SpikeCount": _FakeVariable(counts)}


def _prepared_batched_engine(tmp_path: Path) -> TrackAGeNNEngine:
    graph = SparseConnectome(
        body_ids=np.asarray([10, 20, 30], dtype=np.uint64),
        source_indices=np.asarray([0, 1], dtype=np.uint32),
        target_indices=np.asarray([1, 2], dtype=np.uint32),
        contact_counts=np.asarray([1, 2], dtype=np.uint32),
        source_release="test",
        source_sha256="a" * 64,
    )
    engine = TrackAGeNNEngine(
        tmp_path / "build", batch_size=2, batch_labels=("one", "two")
    )
    engine._graph = graph
    engine._parameters = TrackAGeNNParameters.from_mapping(
        {
            "neural_dt_us": 100,
            "resting_mv": -52.0,
            "reset_mv": -52.0,
            "threshold_mv": -45.0,
            "membrane_tau_ms": 20.0,
            "synapse_tau_ms": 5.0,
            "refractory_ms": 2.2,
            "synaptic_delay_ms": 0.1,
            "synaptic_mv_per_contact": 0.2,
            "central_entry_outgoing_gain": 1.0,
            "tonic_drive_mv": 0.0,
            "reset_synaptic_state_on_spike": True,
        }
    )
    input_variable = _FakeVariable(np.zeros((2, 3), dtype=np.float32))
    engine._input_rates = (input_variable,)
    engine._group_by_dense = np.zeros(3, dtype=np.uint8)
    engine._local_by_dense = np.arange(3, dtype=np.uint32)
    engine._group_dense_indices = (np.arange(3, dtype=np.uint32),)
    engine._flat_index_by_dense = np.arange(3, dtype=np.int64)
    engine._populations = (
        _FakePopulation(np.asarray([[2, 0, 1], [0, 3, 1]], dtype=np.float32)),
    )
    engine._loaded = True
    return engine


def test_track_a_batched_api_keeps_input_and_readout_state_separate(tmp_path: Path) -> None:
    engine = _prepared_batched_engine(tmp_path)
    frames = tuple(
        NeuralInputFrame(
            t_us=0,
            ids=(10, 30),
            values=values,
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="E",
            assumption_ids=("MULTI-01",),
        )
        for values in ((10.0, 30.0), (20.0, 40.0))
    )
    engine.push_batch_inputs(frames)
    input_view = np.asarray(engine._input_rates[0].view)
    assert input_view.tolist() == [[10.0, 0.0, 30.0], [20.0, 0.0, 40.0]]
    outputs = engine.read_batch_outputs((10, 20), 100_000)
    assert outputs[0].values == (20.0, 0.0)
    assert outputs[1].values == (0.0, 30.0)
    assert outputs[0].metadata["connectivity_allocations"] == 1
    with pytest.raises(ConfigurationError, match="single-agent API"):
        engine.push_inputs(frames[0])


def test_web_service_accepts_only_world_commands() -> None:
    service = LiveDemoService(build_preview_runtime)
    try:
        assert "set-actuator" not in ALLOWED_CLIENT_COMMANDS
        with pytest.raises(ConfigurationError, match="Unsupported client command"):
            service.handle_command({"command": "set-actuator", "forward": 1.0})
        with pytest.raises(ConfigurationError, match="unsupported fields"):
            service.handle_command(
                {
                    "command": "place-stimulus",
                    "stimulus": {
                        "id": "food",
                        "kind": "food",
                        "x_mm": 0,
                        "y_mm": 0,
                        "radius_mm": 1,
                        "motor_command": 1,
                    },
                }
            )
        snapshot = service.handle_command({"command": "step"})
        assert snapshot["execution_mode"] == "controller-preview-no-cns"
        assert snapshot["neural"]["enabled"] is False
    finally:
        service.close()


def test_multifly_cli_surfaces_are_stable() -> None:
    parser = build_parser()
    benchmark = parser.parse_args(
        ["benchmark", "multi-fly", "--agents", "2", "4", "--duration-s", "0.2"]
    )
    assert benchmark.agents == [2, 4]
    assert benchmark.duration_s == 0.2

    web = parser.parse_args(["web", "serve", "--mode", "preview", "--port", "7861"])
    assert web.mode == "preview"
    assert web.port == 7861
    assert web.include_shuffled is False


def test_fastapi_application_exposes_only_world_control_routes() -> None:
    app = create_app(build_preview_runtime)
    try:
        paths = {route.path for route in app.routes}
        assert "/api/status" in paths
        assert "/api/command" in paths
        assert "/ws" in paths
        assert "/api/actuators" not in paths
        assert "/api/neural-state" not in paths
        async def post_target() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/command",
                    json={
                        "command": "place-stimulus",
                        "stimulus": {
                            "id": "http-target",
                            "kind": "visual-target",
                            "x_mm": 0.0,
                            "y_mm": 10.0,
                            "radius_mm": 1.0,
                            "strength": 1.0,
                        },
                    },
                )

        response = asyncio.run(post_target())
        assert response.status_code == 200
        assert any(
            stimulus["id"] == "http-target"
            for stimulus in response.json()["arena"]["stimuli"]
        )
    finally:
        app.state.flysim_service.close()
