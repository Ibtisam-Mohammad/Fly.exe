# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

import numpy as np
import pytest

from flysim.connectome import import_aggregate_graph
from flysim.contracts import NeuralInputFrame, SignalType
from flysim.engines.lif import NumpyLIFEngine
from flysim.errors import ConfigurationError
from flysim.provenance import AssumptionRegistry


def graph_and_parameters(tmp_path: Path) -> tuple[object, dict]:
    source = tmp_path / "circuit.csv"
    source.write_text("body_pre,body_post,weight\n1,2,5\n", encoding="utf-8")
    graph = import_aggregate_graph(source, tmp_path / "circuit.npz")
    registry = AssumptionRegistry.load(
        Path(__file__).resolve().parents[1] / "configs" / "assumptions.json"
    )
    parameters = dict(registry.value_map("ND-LIF-01"))
    return graph, parameters


def test_lif_requires_explicit_functional_signs(tmp_path: Path) -> None:
    graph, parameters = graph_and_parameters(tmp_path)
    engine = NumpyLIFEngine()
    with pytest.raises(ConfigurationError, match="functional_edge_signs"):
        engine.initialize(graph, parameters, seed=1)


def test_lif_accepts_body_ids_and_emits_rates(tmp_path: Path) -> None:
    graph, parameters = graph_and_parameters(tmp_path)
    parameters["functional_edge_signs"] = np.array([1.0], dtype=np.float32)
    engine = NumpyLIFEngine()
    engine.initialize(graph, parameters, seed=1)
    engine.push_inputs(
        NeuralInputFrame(
            t_us=0,
            ids=(1,),
            values=(1.0,),
            units="normalized current drive",
            signal_type=SignalType.RECEPTOR_ACTIVITY,
            provenance="E",
            assumption_ids=("ND-LIF-01",),
            metadata={"delay_us": 100},
        )
    )
    engine.step_until(50_000)
    output = engine.read_outputs((1, 2), window_us=50_000)
    assert output.t_us == 50_000
    assert output.values[0] > 0.0

