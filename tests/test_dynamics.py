# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import numpy as np
import pytest

from flysim.connectome import SparseConnectome
from flysim.dynamics import (
    DynamicsRegistry,
    SignalRegime,
    edge_scale_multipliers,
    edge_type_pair_keys,
)
from flysim.errors import ConfigurationError


def _graph() -> SparseConnectome:
    return SparseConnectome(
        body_ids=np.asarray([10, 20, 30], dtype=np.uint64),
        source_indices=np.asarray([0, 1], dtype=np.uint32),
        target_indices=np.asarray([1, 2], dtype=np.uint32),
        contact_counts=np.asarray([2, 4], dtype=np.uint32),
        source_release="test:v1",
        source_sha256="a" * 64,
    )


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "registry_id": "test-dynamics-v1",
                "assumption_ids": ["ND-01", "ND-02", "ND-03", "ND-04", "ND-05"],
                "default_record": {
                    "cell_type": "__unregistered__",
                    "signal_regime": "unresolved",
                    "model_family": "competing",
                    "provenance": "E",
                    "status": "proposed",
                    "source": None,
                    "evidence_scope": "No evidence",
                    "biological_mismatch": "Unknown signaling regime",
                    "alternatives": ["lif", "passive-graded"],
                },
                "records": [
                    {
                        "cell_type": "A",
                        "signal_regime": "spiking",
                        "model_family": "lif",
                        "provenance": "P/E",
                        "status": "accepted",
                        "source": "doi:test",
                        "evidence_scope": "Class-level evidence",
                        "biological_mismatch": "Not specimen-specific",
                        "alternatives": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_registry_resolves_known_and_explicit_unknown_types(tmp_path: Path) -> None:
    path = tmp_path / "dynamics.json"
    _write_registry(path)

    registry = DynamicsRegistry.load(path)
    resolution = registry.resolve(("A", "B", "A"))

    assert resolution.body_signal_regimes == (
        SignalRegime.SPIKING,
        SignalRegime.UNRESOLVED,
        SignalRegime.SPIKING,
    )
    assert resolution.unresolved_cell_types == ("B",)
    assert {record.cell_type for record in resolution.records} == {"A", "B"}
    assert len(registry.registry_sha256) == 64


def test_stage2_registry_exposes_dm1_parameter_prior() -> None:
    registry = DynamicsRegistry.load(
        Path(__file__).parents[1] / "configs" / "neural" / "cell-dynamics-v0.2.json"
    )

    record = registry.resolve(("DM1_lPN",)).records[0]

    assert record.signal_regime is SignalRegime.SPIKING
    assert record.status == "proposed"
    assert record.parameter_prior_id == "gouwens-wilson-2009-dm1-passive-priors-v1"


def test_type_pair_scales_map_reversibly_to_edges() -> None:
    graph = _graph()
    cell_types = ("A", "B", "C")

    assert edge_type_pair_keys(graph, cell_types) == ("A->B", "B->C")
    multipliers = edge_scale_multipliers(
        graph,
        cell_types,
        absolute_scale_mv_per_contact={"A->B": 0.1},
        fallback_scale_mv_per_contact=0.2,
    )

    assert multipliers.tolist() == [0.5, 1.0]


def test_type_pair_scales_reject_invalid_values() -> None:
    with pytest.raises(ConfigurationError, match="finite and nonnegative"):
        edge_scale_multipliers(
            _graph(),
            ("A", "B", "C"),
            absolute_scale_mv_per_contact={"A->B": -0.1},
            fallback_scale_mv_per_contact=0.2,
        )
