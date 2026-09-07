# SPDX-License-Identifier: GPL-2.0-or-later
import numpy as np

from flysim.circuit import TransferLIFParameters
from flysim.connectome import SparseConnectome
from flysim.stage1 import _fit_nd04_contact_scale


def test_nd04_fit_freezes_smallest_tied_candidate_before_held_out() -> None:
    graph = SparseConnectome(
        body_ids=np.asarray([10, 20], dtype=np.uint64),
        source_indices=np.asarray([0], dtype=np.uint32),
        target_indices=np.asarray([1], dtype=np.uint32),
        contact_counts=np.asarray([1], dtype=np.uint32),
        source_release="test:v1",
        source_sha256="a" * 64,
    )
    parameters = TransferLIFParameters(
        dt_ms=0.1,
        duration_ms=1.0,
        resting_mv=-52.0,
        reset_mv=-52.0,
        threshold_mv=-45.0,
        membrane_tau_ms=20.0,
        synapse_tau_ms=5.0,
        refractory_ms=0.2,
        synaptic_delay_ms=0.1,
        synaptic_mv_per_contact=0.275,
        tonic_drive_mv=0.0,
        reset_synaptic_state_on_spike=True,
        state_updater="source-faithful-linear",
        genn_precision="float64-reference",
    )
    result = _fit_nd04_contact_scale(
        graph=graph,
        edge_signs=np.ones(1, dtype=np.float32),
        input_body_ids=(10,),
        readout_body_ids=(20,),
        parameters=parameters,
        seeds=(1,),
        reference={
            "curve": [
                {"frequency_hz": 20.0, "mean_rate_hz": 0.0},
                {"frequency_hz": 40.0, "mean_rate_hz": 0.0},
            ]
        },
        fit_protocol={
            "candidate_values_mv_per_contact": [0.1, 0.2],
            "training_frequencies_hz": [20.0],
            "held_out_frequencies_hz": [40.0],
            "objective": "test RMSE",
            "tie_break": "smallest candidate scale",
            "claim_boundary": "test only",
        },
    )

    assert result["selected_value"] == 0.1
    assert result["frozen_before_held_out_evaluation"] is True
    assert result["training_metrics"]["frequencies_hz"] == [20.0]
    assert result["held_out_metrics"]["frequencies_hz"] == [40.0]
