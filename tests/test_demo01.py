# SPDX-License-Identifier: GPL-2.0-or-later
"""DEMO-01: the bypasses are gone, the readout is causal, the criteria discriminate."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from flysim.connectome import SparseConnectome
from flysim.contracts import (
    NeuralInputFrame,
    NeuralOutputFrame,
    SensorFrame,
    SignalType,
)
from flysim.demo01 import (
    ENTRY_SPECS,
    LEFT_READOUTS,
    READOUT_SPECS,
    RIGHT_READOUTS,
    ApproachController,
    ApproachParameters,
    ApproachState,
    Demo01Populations,
    FilteredDescendingReadout,
    OperatingPointCriteria,
    OrnEncodingParameters,
    OrnSensoryEncoder,
    ReadoutParameters,
    score_operating_point,
    searched_parameter_grid,
    selectivity_index,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parents[1]

# One body per declared population, plus a couple of spare bodies for the monitor pools.
_ENTRY_BODIES = {
    ("ORN_DM1", "L"): [101, 102],
    ("ORN_DM1", "R"): [103, 104],
    ("ORN_DM4", "L"): [105],
    ("ORN_DM4", "R"): [106],
}
_READOUT_BODIES = {
    ("DNa01", "L"): [201],
    ("DNa02", "L"): [202],
    ("DNa01", "R"): [203],
    ("DNa02", "R"): [204],
}


def _annotations(tmp_path: Path, *, orn_side_unknown: int = 0) -> Path:
    import pyarrow as pa
    import pyarrow.feather as feather

    rows: list[dict[str, object]] = []
    for (cell_type, side), bodies in _ENTRY_BODIES.items():
        for body in bodies:
            rows.append(
                {
                    "bodyId": body,
                    "type": cell_type,
                    "class": "olfactory",
                    "superclass": "cb_sensory",
                    "somaSide": None,
                    "rootSide": side,
                }
            )
    for index in range(orn_side_unknown):
        rows.append(
            {
                "bodyId": 150 + index,
                "type": "ORN_DM1",
                "class": "olfactory",
                "superclass": "cb_sensory",
                "somaSide": None,
                "rootSide": "unknown",
            }
        )
    for (cell_type, side), bodies in _READOUT_BODIES.items():
        for body in bodies:
            rows.append(
                {
                    "bodyId": body,
                    "type": cell_type,
                    "class": None,
                    "superclass": "descending_neuron",
                    "somaSide": side,
                    "rootSide": None,
                }
            )
    # Filler so every monitor pool resolves.
    for body, klass, superclass in (
        (301, "ALPN", "cb_intrinsic"),
        (302, "ALLN", "cb_intrinsic"),
        (303, None, "vnc_motor"),
    ):
        rows.append(
            {
                "bodyId": body,
                "type": f"filler{body}",
                "class": klass,
                "superclass": superclass,
                "somaSide": "L",
                "rootSide": "L",
            }
        )
    table = pa.Table.from_pylist(rows)
    path = tmp_path / "annotations.feather"
    feather.write_feather(table, path)
    return path


def _graph(bodies: list[int]) -> SparseConnectome:
    ids = np.array(sorted(bodies), dtype=np.uint64)
    # A ring, so every body has one edge and the graph validates.
    sources = np.arange(ids.size, dtype=np.uint32)
    targets = np.roll(sources, 1).astype(np.uint32)
    return SparseConnectome(
        body_ids=ids,
        source_indices=sources,
        target_indices=targets,
        contact_counts=np.ones(ids.size, dtype=np.uint32),
        source_release="fixture:v1",
        source_sha256="0" * 64,
    )


def _all_bodies(*, orn_side_unknown: int = 0) -> list[int]:
    bodies = [b for group in _ENTRY_BODIES.values() for b in group]
    bodies += [b for group in _READOUT_BODIES.values() for b in group]
    bodies += [301, 302, 303]
    bodies += [150 + i for i in range(orn_side_unknown)]
    return bodies


def _populations(tmp_path: Path, *, orn_side_unknown: int = 0) -> Demo01Populations:
    path = _annotations(tmp_path, orn_side_unknown=orn_side_unknown)
    graph = _graph(_all_bodies(orn_side_unknown=orn_side_unknown))
    return Demo01Populations.resolve(path, graph)


def _readout_frame(
    counts: dict[int, int], *, t_us: int = 15_000, window_us: int = 15_000
) -> NeuralOutputFrame:
    ids = tuple(sorted(counts))
    window_s = window_us / 1_000_000.0
    return NeuralOutputFrame(
        t_us=t_us,
        ids=ids,
        values=tuple(counts[i] / window_s for i in ids),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("ND-01",),
        metadata={"window_us": window_us, "spike_counts": dict(counts)},
    )


def _population_frame(
    left_hz: float, right_hz: float, *, t_us: int = 15_000
) -> NeuralOutputFrame:
    """A frame shaped like the filtered readout's output: population names, not bodies."""
    names = (*LEFT_READOUTS, *RIGHT_READOUTS)
    values = (left_hz, left_hz, right_hz, right_hz)
    return NeuralOutputFrame(
        t_us=t_us,
        ids=names,
        values=values,
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("ND-01",),
        metadata={"window_us": 15_000},
    )


def _sensors(*, odour_left: float, odour_right: float, distance_mm: float) -> SensorFrame:
    return SensorFrame(
        t_us=15_000,
        ids=(OrnSensoryEncoder.SENSOR_LEFT, OrnSensoryEncoder.SENSOR_RIGHT),
        values=(odour_left, odour_right),
        units="normalized [0,1]",
        signal_type=SignalType.WORLD_QUANTITY,
        provenance="E",
        assumption_ids=("SENS-03",),
        metadata={"target_distance_mm": distance_mm},
    )


def _decoder() -> ApproachParameters:
    return ApproachParameters.from_mapping(
        {
            "quiescent_us": 0,
            "forward_half_rate_hz": 10.0,
            "forward_threshold_hz": 1.0,
            "yaw_gain_per_hz": 0.05,
            "max_yaw_rad_s": 2.5,
            "arrival_radius_mm": 1.0,
            "initiation_hold_us": 0,
        }
    )


# ---------------------------------------------------------------------------
# The bypasses are gone. These are the tests the predecessor could not pass.
# ---------------------------------------------------------------------------


def test_the_command_is_a_pure_function_of_the_neural_readout() -> None:
    """The odour gradient must not reach the command by any route.

    In eon-malecns-v0.2 the controller added odor_gradient_yaw_gain_rad_s times the
    odour difference straight into yaw. Measured on its own control traces, yaw
    correlated +0.975 with the gradient and +0.132 with the descending readout, and a
    zero-weight brain still produced 100.2 mm of steered walking. So this test drives
    the same readout against opposite, saturating odour gradients and requires the
    command to be identical.
    """
    frame = _population_frame(66.7, 0.0)
    left_cue = ApproachController(_decoder()).decode(
        frame, _sensors(odour_left=1.0, odour_right=0.0, distance_mm=9.0)
    )
    right_cue = ApproachController(_decoder()).decode(
        frame, _sensors(odour_left=0.0, odour_right=1.0, distance_mm=9.0)
    )
    assert left_cue.values == right_cue.values
    # And the yaw is not zero, so the test is not passing trivially on a null command.
    assert left_cue.value_for("actuator:yaw-drive") != 0.0
    assert left_cue.metadata["sensor_terms_in_command"] == []


def test_yaw_follows_the_descending_asymmetry_and_reverses_with_it() -> None:
    parameters = _decoder()
    left_louder = ApproachController(parameters).decode(
        _population_frame(133.3, 0.0),
        _sensors(odour_left=0.5, odour_right=0.5, distance_mm=9.0),
    )
    right_louder = ApproachController(parameters).decode(
        _population_frame(0.0, 133.3),
        _sensors(odour_left=0.5, odour_right=0.5, distance_mm=9.0),
    )
    left_yaw = left_louder.value_for("actuator:yaw-drive")
    right_yaw = right_louder.value_for("actuator:yaw-drive")
    assert left_yaw > 0.0 > right_yaw
    assert math.isclose(left_yaw, -right_yaw, rel_tol=1e-9)


def test_a_silent_brain_produces_no_locomotor_drive(tmp_path: Path) -> None:
    """The zero-weight control must stand still, which the predecessor did not."""
    command = ApproachController(_decoder()).decode(
        _population_frame(0.0, 0.0),
        _sensors(odour_left=1.0, odour_right=0.0, distance_mm=9.0),
    )
    assert command.value_for("actuator:forward-drive") == 0.0
    assert command.value_for("actuator:yaw-drive") == 0.0


def test_the_encoder_injects_only_declared_orn_bodies(tmp_path: Path) -> None:
    populations = _populations(tmp_path)
    encoder = OrnSensoryEncoder(
        populations,
        OrnEncodingParameters.from_mapping(
            {"orn_max_rate_hz": 200.0, "orn_baseline_rate_hz": 2.0}
        ),
    )
    frame = encoder.encode(
        NeuralInputFrame(
            t_us=0,
            ids=(OrnSensoryEncoder.SENSOR_LEFT, OrnSensoryEncoder.SENSOR_RIGHT),
            values=(1.0, 0.0),
            units="normalized [0,1]",
            signal_type=SignalType.WORLD_QUANTITY,
            provenance="E",
            assumption_ids=("SENS-03",),
        )
    )
    assert set(frame.ids) == set(populations.entry_body_ids)
    # No descending body may be injected: that was the oDN1 defect.
    assert not set(frame.ids) & set(populations.readout_body_ids)
    assert frame.metadata["antennal_lobe_bypassed"] is False
    left_bodies = set(populations.entry["orn-dm1-left"])
    right_bodies = set(populations.entry["orn-dm1-right"])
    rates = dict(zip(frame.ids, frame.values, strict=True))
    assert all(rates[b] == pytest.approx(200.0) for b in left_bodies)
    assert all(rates[b] == pytest.approx(2.0) for b in right_bodies)


def test_entry_and_readout_populations_may_not_overlap(tmp_path: Path) -> None:
    """A readout body that is also injected would re-read the stimulus."""
    import pyarrow as pa
    import pyarrow.feather as feather

    rows = [
        {
            "bodyId": 201,
            "type": "ORN_DM1",
            "class": "olfactory",
            "superclass": "cb_sensory",
            "somaSide": "L",
            "rootSide": "L",
        }
    ]
    path = tmp_path / "clash.feather"
    feather.write_feather(pa.Table.from_pylist(rows), path)
    with pytest.raises(Exception):  # noqa: B017 - DatasetError or ConfigurationError
        Demo01Populations.resolve(path, _graph([201]))


def test_orn_laterality_comes_from_rootside_and_unknowns_are_excluded(
    tmp_path: Path,
) -> None:
    populations = _populations(tmp_path, orn_side_unknown=3)
    assert populations.excluded_unknown_side["ORN_DM1"] == 3
    injected = set(populations.entry_body_ids)
    assert not injected & {150, 151, 152}
    spec = next(s for s in ENTRY_SPECS if s.name == "orn-dm1-left")
    assert spec.side_column == "rootSide"
    readout_spec = next(s for s in READOUT_SPECS if s.name == "dn-steering-left")
    assert readout_spec.side_column == "somaSide"


# ---------------------------------------------------------------------------
# The causal filter
# ---------------------------------------------------------------------------


def test_the_filter_is_causal_and_converges_to_the_true_rate(tmp_path: Path) -> None:
    populations = _populations(tmp_path)
    readout = FilteredDescendingReadout(
        populations, ReadoutParameters.from_mapping({"readout_filter_tau_ms": 150.0})
    )
    # One spike per 15 ms interval in every left body is 66.67 Hz.
    steady = {201: 1, 202: 1, 203: 0, 204: 0}
    first = readout.read(_readout_frame(steady, t_us=15_000))
    assert first.value_for("dn-steering-left") < 66.67, "a causal filter cannot jump"
    values = [first.value_for("dn-steering-left")]
    for step in range(2, 80):
        frame = readout.read(_readout_frame(steady, t_us=15_000 * step))
        values.append(frame.value_for("dn-steering-left"))
    assert values == sorted(values), "monotone approach to the steady rate"
    assert values[-1] == pytest.approx(66.67, rel=0.01)
    # Raw counts survive.
    assert first.metadata["raw_population_spike_counts"]["dn-steering-left"] == 1


def test_the_filter_refuses_a_frame_without_raw_counts(tmp_path: Path) -> None:
    populations = _populations(tmp_path)
    readout = FilteredDescendingReadout(
        populations, ReadoutParameters.from_mapping({"readout_filter_tau_ms": 150.0})
    )
    bare = NeuralOutputFrame(
        t_us=15_000,
        ids=(201,),
        values=(66.0,),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("ND-01",),
        metadata={"window_us": 15_000},
    )
    with pytest.raises(ConfigurationError, match="spike_counts"):
        readout.read(bare)


def test_readout_ablation_zeroes_only_the_named_population(tmp_path: Path) -> None:
    populations = _populations(tmp_path)
    readout = FilteredDescendingReadout(
        populations,
        ReadoutParameters.from_mapping({"readout_filter_tau_ms": 150.0}),
        ablated_population_ids=frozenset(LEFT_READOUTS),
    )
    frame = readout.read(_readout_frame({201: 2, 202: 2, 203: 2, 204: 2}))
    assert all(frame.value_for(name) == 0.0 for name in LEFT_READOUTS)
    assert all(frame.value_for(name) > 0.0 for name in RIGHT_READOUTS)
    # The raw counts are still recorded, so an ablation is visible rather than erased.
    assert frame.metadata["raw_population_spike_counts"]["dn-steering-left"] == 2


# ---------------------------------------------------------------------------
# The operating-point criteria have to discriminate
# ---------------------------------------------------------------------------


def _epoch(left: float, right: float) -> dict[str, float]:
    return {
        **{name: left for name in LEFT_READOUTS},
        **{name: right for name in RIGHT_READOUTS},
    }


def _criteria() -> OperatingPointCriteria:
    return OperatingPointCriteria.from_mapping(
        json.loads(
            (REPO / "configs/experiments/demo01-operating-point-v1.json").read_text(
                encoding="utf-8"
            )
        )["neural_criteria"]
    )


def _score(
    baseline: tuple[float, float],
    cue_left: tuple[float, float],
    cue_right: tuple[float, float],
    recovery: tuple[float, float],
    *,
    mean_rate_hz: float = 5.0,
    active_fraction: float = 0.3,
) -> dict[str, object]:
    return score_operating_point(
        baseline=_epoch(*baseline),
        cue_left=_epoch(*cue_left),
        cue_right=_epoch(*cue_right),
        recovery=_epoch(*recovery),
        pool_activity={
            "descending-all": {
                "mean_rate_hz": mean_rate_hz,
                "active_fraction": active_fraction,
            }
        },
        criteria=_criteria(),
    )


def test_a_good_operating_point_passes_all_four() -> None:
    score = _score((1.0, 1.0), (12.0, 4.0), (4.0, 12.0), (2.0, 2.0))
    assert score["all_criteria_met"] is True
    assert score["selectivity_reverses_with_cue_side"] is True


def test_a_fixed_asymmetry_fails_the_reversal_criterion() -> None:
    """A left-biased network that ignores the cue must not pass C3.

    This is the degenerate outcome the criterion exists to exclude: a large, perfectly
    stable left-right difference that is identical for a left cue and a right cue carries
    no information about which side the cue is on.
    """
    score = _score((1.0, 1.0), (12.0, 4.0), (12.0, 4.0), (2.0, 2.0))
    assert score["C2_cue_responsive"] is True
    assert score["C3_bilateral_selectivity_reverses"] is False
    assert score["all_criteria_met"] is False


def test_a_silent_network_fails_cue_responsiveness() -> None:
    score = _score((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), active_fraction=0.0)
    assert score["C2_cue_responsive"] is False
    assert score["C1_stable_nonsaturated"] is False
    assert score["all_criteria_met"] is False


def test_a_saturated_network_fails_stability() -> None:
    score = _score(
        (200.0, 200.0),
        (300.0, 250.0),
        (250.0, 300.0),
        (200.0, 200.0),
        mean_rate_hz=300.0,
        active_fraction=1.0,
    )
    assert score["C1_stable_nonsaturated"] is False
    assert score["all_criteria_met"] is False


def test_a_network_that_never_recovers_fails_c4() -> None:
    score = _score((1.0, 1.0), (12.0, 4.0), (4.0, 12.0), (11.0, 11.0))
    assert score["C2_cue_responsive"] is True
    assert score["C3_bilateral_selectivity_reverses"] is True
    assert score["C4_recovers_to_baseline"] is False
    assert score["all_criteria_met"] is False


def test_selectivity_index_is_zero_when_silent_or_balanced() -> None:
    assert selectivity_index(0.0, 0.0) == 0.0
    assert selectivity_index(5.0, 5.0) == 0.0
    assert selectivity_index(10.0, 0.0) == 1.0
    assert selectivity_index(0.0, 10.0) == -1.0


def test_no_behavioural_quantity_can_enter_the_operating_point_score() -> None:
    """The scoring function's signature is the guarantee, so pin it."""
    import inspect

    from flysim import demo01

    signature = inspect.signature(demo01.score_operating_point)
    assert set(signature.parameters) == {
        "baseline",
        "cue_left",
        "cue_right",
        "recovery",
        "pool_activity",
        "criteria",
    }
    forbidden = ("distance", "displacement", "trajectory", "success", "target", "reward")
    source = inspect.getsource(demo01.score_operating_point)
    assert not any(word in source.split("what_is_deliberately_not_here")[0] for word in forbidden)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_contract_grid_matches_its_declared_size() -> None:
    contract = json.loads(
        (REPO / "configs/experiments/demo01-operating-point-v1.json").read_text(
            encoding="utf-8"
        )
    )
    grid = searched_parameter_grid(contract["searched_grid"])
    assert len(grid) == contract["grid_size"]
    assert contract["values_opened"] is False
    # The registered predecessor values must be inside the searched range, so the search
    # cannot be accused of excluding the incumbent.
    assert 0.275 in contract["searched_grid"]["synaptic_mv_per_contact"]
    assert 10.0 in contract["searched_grid"]["central_entry_outgoing_gain"]
    assert 0.0 in contract["searched_grid"]["tonic_drive_mv"]
    # And no behavioural objective may appear in the contract.
    text = json.dumps(contract).lower()
    for word in ("distance_to_target", "approach_success", "reward"):
        assert word not in text


def test_the_approach_controller_state_machine_starts_quiescent() -> None:
    controller = ApproachController(
        ApproachParameters.from_mapping(
            {
                "quiescent_us": 300_000,
                "forward_half_rate_hz": 10.0,
                "forward_threshold_hz": 1.0,
                "yaw_gain_per_hz": 0.05,
                "max_yaw_rad_s": 2.5,
                "arrival_radius_mm": 1.0,
                "initiation_hold_us": 0,
            }
        )
    )
    assert controller.state is ApproachState.QUIESCENT
    early = controller.decode(
        _population_frame(133.3, 133.3, t_us=15_000),
        _sensors(odour_left=1.0, odour_right=0.0, distance_mm=9.0),
    )
    # A stationary fly stays stationary until the declared quiescent period elapses,
    # however loud the brain is.
    assert early.value_for("actuator:forward-drive") == 0.0
    assert controller.state is ApproachState.QUIESCENT
    late = controller.decode(
        _population_frame(133.3, 133.3, t_us=300_000),
        _sensors(odour_left=1.0, odour_right=0.0, distance_mm=9.0),
    )
    assert controller.state is ApproachState.CUE_PRESENT
    assert late.value_for("actuator:forward-drive") > 0.0
