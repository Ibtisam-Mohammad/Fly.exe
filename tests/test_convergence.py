# SPDX-License-Identifier: GPL-2.0-or-later
"""The parameter-free ORN-to-PN convergence test of the locked connectome."""

import json
import re
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.connectome import SparseConnectome
from flysim.convergence import (
    PROJECTION_PATTERN,
    _dense_indices,
    _pair_completeness,
    load_olfactory_populations,
)
from flysim.errors import DatasetError

REPO = Path(__file__).resolve().parents[1]


def _graph(sources: list[int], targets: list[int], contacts: list[int], bodies: list[int]):
    return SparseConnectome(
        body_ids=np.asarray(bodies, dtype=np.uint64),
        source_indices=np.asarray(sources, dtype=np.uint32),
        target_indices=np.asarray(targets, dtype=np.uint32),
        contact_counts=np.asarray(contacts, dtype=np.uint32),
        source_release="test",
        source_sha256="0" * 64,
    )


def _annotations(path: Path, rows: list[tuple[int, str | None, str]]) -> Path:
    table = pa.table(
        {
            "bodyId": pa.array([r[0] for r in rows], type=pa.int64()),
            "type": pa.array([r[1] for r in rows], type=pa.string()),
            "status": pa.array([r[2] for r in rows], type=pa.string()),
        }
    )
    feather.write_feather(table, path)
    return path


def test_only_traced_bodies_with_uniglomerular_labels_enter_the_populations(
    tmp_path: Path,
) -> None:
    path = _annotations(
        tmp_path / "ann.feather",
        [
            (1, "ORN_DM4", "Traced"),
            (2, "ORN_DM4", "Orphan"),  # wrong status
            (3, "DM4_adPN", "Traced"),
            (4, "DM4_adPN", "Unimportant"),  # wrong status
            (5, "DM4_lPN", "Traced"),
            (6, None, "Traced"),  # untyped
            (7, "DM4_bilateralPN", "Traced"),  # not a uniglomerular suffix
            (8, "ORN_VM2", "Traced"),
        ],
    )

    receptors, projections = load_olfactory_populations(path)

    assert receptors == {"DM4": [1], "VM2": [8]}
    assert projections == {"DM4": [3, 5]}


def test_the_uniglomerular_regex_agrees_with_the_plasticity_registry() -> None:
    """The same population definition must serve both, or the two results are incomparable.

    The convergence pattern adds a capture group so the glomerulus can be read off; the two
    must otherwise accept and reject exactly the same labels.
    """
    registry = json.loads(
        (REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json").read_text()
    )
    registered = re.compile(registry["rules"][0]["target_type_regex"])
    labels = [
        "DL5_adPN", "DM4_lPN", "VM2_vPN", "DA1_ilPN", "DL2d_lvPN", "VC3_vlPN", "DP1m_mPN",
        "DM4_bilateralPN", "ORN_DM4", "DL5_adPNx", "xDL5_adPN", "DL5-adPN", "_adPN", "PN",
    ]

    assert [bool(registered.match(label)) for label in labels] == [
        bool(PROJECTION_PATTERN.match(label)) for label in labels
    ]
    # Any alphanumeric prefix is a candidate glomerulus name, so "xDL5_adPN" is accepted
    # too; the suffix is what the pattern constrains.
    assert [label for label in labels if PROJECTION_PATTERN.match(label)] == [
        "DL5_adPN", "DM4_lPN", "VM2_vPN", "DA1_ilPN", "DL2d_lvPN", "VC3_vlPN",
        "DP1m_mPN", "xDL5_adPN",
    ]


@pytest.mark.parametrize("suffix", ["adPN", "lPN", "vPN", "ilPN", "lvPN", "vlPN", "mPN"])
def test_every_registered_uniglomerular_suffix_is_recognised(suffix: str) -> None:
    match = PROJECTION_PATTERN.match(f"DL5_{suffix}")
    assert match is not None and match.group(1) == "DL5"


def test_dense_indices_drops_bodies_the_graph_does_not_carry() -> None:
    graph = _graph([0], [1], [3], bodies=[10, 20, 30])

    assert _dense_indices(graph, [10, 30]).tolist() == [0, 2]
    assert _dense_indices(graph, [15, 99]).tolist() == []
    # A body above every graph body must not clip onto the last index.
    assert _dense_indices(graph, [40]).tolist() == []


def test_completeness_counts_ordered_pairs_with_no_contact_threshold() -> None:
    # bodies 10, 11 are receptors (indices 0, 1); 20, 21 are projections (indices 2, 3).
    # Three of the four ordered receptor->projection pairs carry an edge.
    graph = _graph(
        sources=[0, 0, 1, 2],
        targets=[2, 3, 2, 0],
        contacts=[1, 40, 7, 5],
        bodies=[10, 11, 20, 21],
    )
    receptors = np.asarray([0, 1], dtype=np.int64)
    projections = np.asarray([2, 3], dtype=np.int64)

    realised, contacts = _pair_completeness(graph, receptors, projections)

    assert realised == 3
    assert sorted(contacts.tolist()) == [1, 7, 40]
    # A single-contact edge counts, which is the reading most favourable to the prediction.
    assert 1 in contacts.tolist()
    # The reverse direction is measured separately and is not part of the numerator.
    reverse, reverse_contacts = _pair_completeness(graph, projections, receptors)
    assert reverse == 1 and reverse_contacts.tolist() == [5]


def test_completeness_is_zero_when_no_edge_joins_the_populations() -> None:
    graph = _graph([0], [1], [9], bodies=[10, 11, 20])
    realised, contacts = _pair_completeness(
        graph, np.asarray([0], dtype=np.int64), np.asarray([2], dtype=np.int64)
    )
    assert realised == 0 and contacts.size == 0


def test_an_empty_population_yields_no_pairs() -> None:
    graph = _graph([0], [1], [9], bodies=[10, 11])
    empty = np.empty(0, dtype=np.int64)

    realised, contacts = _pair_completeness(graph, empty, np.asarray([1], dtype=np.int64))

    assert realised == 0 and contacts.size == 0


def test_duplicate_ordered_edges_are_refused_because_they_break_the_denominator() -> None:
    """The aggregate graph must carry one edge per ordered pair or completeness can exceed 1."""
    graph = _graph(sources=[0, 0], targets=[1, 1], contacts=[3, 4], bodies=[10, 20])

    with pytest.raises(DatasetError, match="duplicate edges"):
        _pair_completeness(
            graph, np.asarray([0], dtype=np.int64), np.asarray([1], dtype=np.int64)
        )


def test_the_contract_registers_the_sizes_and_keeps_h1_and_h2_blind() -> None:
    contract = json.loads(
        (REPO / "configs" / "experiments" / "orn-pn-convergence-v1.json").read_text()
    )
    sizes = contract["sizes_observed_before_registration"]

    assert sizes["glomeruli_with_both_populations"] == 50
    assert sizes["possible_orn_by_pn_pairs"] == 16384
    hypotheses = {item["id"]: item for item in contract["hypotheses"]}
    assert hypotheses["H1"]["expect"] == 1.0
    assert hypotheses["H2"]["expect_at_least"] == 0.95
    # H3 is not blind and must say so rather than being reported as a prediction.
    assert "disclosure" in hypotheses["H3"]
    assert "32" in hypotheses["H3"]["disclosure"]
    # H2's floor must be justified by an argument, not asserted.
    assert "0.9957" in hypotheses["H2"]["derivation"]
    assert "interpretation_if_failed" in hypotheses["H2"]


def test_the_h2_recovery_argument_is_arithmetically_correct() -> None:
    """A floor of 0.95 is only defensible if per-synapse incompleteness cannot reach it."""
    postsynaptic_completion = 0.42
    miss = 1.0 - postsynaptic_completion
    assert 1.0 - miss**10 == pytest.approx(0.9957, abs=5e-5)
    assert 1.0 - miss**25 == pytest.approx(0.9999988, abs=5e-7)
