# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from flysim.connectome import SparseConnectome
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs


def test_transmitter_regression_signs_keep_unresolved_policy_explicit(tmp_path: Path) -> None:
    source = tmp_path / "transmitters.feather"
    feather.write_feather(
        pa.table(
            {
                "body": pa.array([10, 20, 30, 40], type=pa.int64()),
                "consensus_nt": ["acetylcholine", "gaba", "glutamate", "unclear"],
            }
        ),
        source,
    )
    graph = SparseConnectome(
        body_ids=np.array([10, 20, 30, 40], dtype=np.uint64),
        source_indices=np.array([0, 1, 2, 3], dtype=np.uint32),
        target_indices=np.array([1, 2, 3, 0], dtype=np.uint32),
        contact_counts=np.ones(4, dtype=np.uint32),
        source_release="fixture",
        source_sha256="fixture",
    )
    zero = build_shiu_regression_signs(
        graph, source, unresolved_policy=UnresolvedSignPolicy.ZERO, seed=1
    )
    excitatory = build_shiu_regression_signs(
        graph, source, unresolved_policy=UnresolvedSignPolicy.EXCITATORY, seed=1
    )
    assert zero.edge_signs.tolist() == [1.0, -1.0, -1.0, 0.0]
    assert excitatory.edge_signs.tolist() == [1.0, -1.0, -1.0, 1.0]
    assert zero.known_neurons == 3
    assert zero.unresolved_neurons == 1
