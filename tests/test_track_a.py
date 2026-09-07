# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pytest

from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.engines.genn import TrackAGeNNParameters
from flysim.engines.reference import (
    OUTPUT_DNA_L,
    OUTPUT_DNA_R,
    OUTPUT_FEED,
    OUTPUT_FORWARD,
    OUTPUT_GROOM,
    SENSOR_CONTAMINATION,
    SENSOR_ODOR_L,
    SENSOR_ODOR_R,
    SENSOR_SUCROSE,
)
from flysim.errors import ConfigurationError
from flysim.track_a import (
    REQUIRED_TRACK_A_POPULATIONS,
    TrackAEncodingParameters,
    TrackAPopulationEncoder,
    TrackAPopulationMap,
    TrackAPopulationReadout,
)


def _population_map(tmp_path: Path) -> TrackAPopulationMap:
    body_ids = {
        "steering-dn-left": [11, 12],
        "steering-dn-right": [13, 14],
        "forward-odn1": [15, 16],
        "feeding-mn9": [17, 18],
        "grooming-jo-f": [21, 22],
        "grooming-descending-readout": [23, 24],
        "ethyl-acetate-receptor-entry": [31, 32, 33, 34],
        "sucrose-receptor-entry": [41, 42],
    }
    populations = []
    for population_id in REQUIRED_TRACK_A_POPULATIONS:
        ids = body_ids[population_id]
        rows = []
        for index, body_id in enumerate(ids):
            side = "L" if index % 2 == 0 else "R"
            rows.append({"bodyId": body_id, "instance": f"fixture_{side}"})
        populations.append(
            {
                "id": population_id,
                "status": "resolved",
                "body_ids": ids,
                "rows": rows,
            }
        )
    path = tmp_path / "populations.json"
    path.write_text(
        json.dumps({"registry_id": "fixture-v1", "populations": populations}),
        encoding="utf-8",
    )
    return TrackAPopulationMap.load(path)


def test_track_a_encoder_preserves_numeric_entries_and_intent_bias(tmp_path: Path) -> None:
    populations = _population_map(tmp_path)
    encoder = TrackAPopulationEncoder(
        populations,
        TrackAEncodingParameters(
            odor_max_rate_hz=1000.0,
            contamination_max_rate_hz=1000.0,
            sucrose_rate_hz=1000.0,
            forward_intent_rate_hz=20.0,
        ),
    )
    source = NeuralInputFrame(
        t_us=15_000,
        ids=(SENSOR_ODOR_L, SENSOR_ODOR_R, SENSOR_CONTAMINATION, SENSOR_SUCROSE),
        values=(0.25, 0.5, 0.75, 1.0),
        units="normalized [0,1]",
        signal_type=SignalType.RECEPTOR_ACTIVITY,
        provenance="E",
        assumption_ids=("TRACKA-01",),
    )
    result = encoder.encode(source)
    assert all(isinstance(body_id, int) for body_id in result.ids)
    assert result.value_for(31) == 250.0
    assert result.value_for(32) == 500.0
    assert result.value_for(21) == 750.0
    assert result.value_for(41) == 1000.0
    assert result.value_for(15) == 10.0
    assert result.metadata["intent_bias"].startswith("odor-gated DNg97")


def test_track_a_readout_aggregates_registered_population_members(tmp_path: Path) -> None:
    populations = _population_map(tmp_path)
    frame = NeuralOutputFrame(
        t_us=30_000,
        ids=populations.output_body_ids,
        values=tuple(float(value) for value in populations.output_body_ids),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("TRACKA-01",),
    )
    result = TrackAPopulationReadout(populations).read(frame)
    assert result.value_for(OUTPUT_DNA_L) == 11.5
    assert result.value_for(OUTPUT_DNA_R) == 13.5
    assert result.value_for(OUTPUT_FORWARD) == 15.5
    assert result.value_for(OUTPUT_GROOM) == 23.5
    assert result.value_for(OUTPUT_FEED) == 17.5


def test_track_a_parameter_validation_rejects_subunit_entry_gain() -> None:
    raw = {
        "neural_dt_us": 100,
        "resting_mv": -52.0,
        "reset_mv": -52.0,
        "threshold_mv": -45.0,
        "membrane_tau_ms": 20.0,
        "synapse_tau_ms": 5.0,
        "refractory_ms": 2.2,
        "synaptic_delay_ms": 0.1,
        "synaptic_mv_per_contact": 0.275,
        "central_entry_outgoing_gain": 0.5,
        "tonic_drive_mv": 0.0,
        "reset_synaptic_state_on_spike": True,
    }
    with pytest.raises(ConfigurationError, match="central-entry gain"):
        TrackAGeNNParameters.from_mapping(raw)
