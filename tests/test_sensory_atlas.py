# SPDX-License-Identifier: GPL-2.0-or-later
"""The sensory partition: that it is total, that it is disjoint, and that it stays put.

The unit tests build tiny annotation tables, because a test that needs the 5 GB release is
a test nobody runs. The last test does need the release, and skips when it is not staged --
it pins the numbers the whole plan is built on, so that a selector edit which quietly steals
bodies from one channel into another fails here rather than shifting a published result.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from flysim.errors import ConfigurationError, DatasetError
from flysim.sensory_atlas import ChannelKey, SensoryAtlas


@dataclass(frozen=True)
class _Graph:
    """The only thing SensoryAtlas.resolve asks a graph for."""

    body_ids: tuple[int, ...]


def _table(rows: list[dict[str, Any]]) -> pa.Table:
    columns = (
        "bodyId",
        "type",
        "class",
        "subclass",
        "superclass",
        "entryNerve",
        "rootSide",
        "receptorType",
        "instance",
        "exitNerve",
        "status",
    )
    return pa.table({name: [row.get(name) for row in rows] for name in columns})


def _write(
    tmp_path: Path, rows: list[dict[str, Any]], registry: dict[str, Any]
) -> tuple[Path, Path]:
    annotations = tmp_path / "annotations.feather"
    feather.write_feather(_table(rows), annotations)
    registry_path = tmp_path / "atlas.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return annotations, registry_path


def _registry(channels: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    base = {
        "registry_id": "test-atlas",
        "sensory_superclasses": ["cb_sensory", "vnc_sensory"],
        "nerve_to_organ": {"AN": "antenna", "ProLN": "leg-front"},
        "channels": channels,
    }
    base.update(extra)
    return base


def _sensory(body: int, **overrides: Any) -> dict[str, Any]:
    row = {
        "bodyId": body,
        "type": "",
        "class": "mechanosensory",
        "subclass": None,
        "superclass": "cb_sensory",
        "entryNerve": "AN",
        "rootSide": "L",
    }
    row.update(overrides)
    return row


def test_a_body_matched_by_two_rungs_is_claimed_only_by_the_earlier_one(tmp_path: Path) -> None:
    """This is the case that makes a partition necessary rather than tidy.

    Subclass 'pharyngeal sensillum' really does span class gustatory and class
    mechanosensory in the release. Filters would hand the same body to both encoders and
    SignalFrame would reject the duplicate id mid-run.
    """
    rows = [_sensory(1, subclass="pharyngeal sensillum", **{"class": "gustatory"})]
    registry = _registry([
        {
            "modality": "pharyngeal", "priority": 20, "combine": "all", "kind": "declared",
            "queries": [
                {"field": "subclass", "operator": "exact", "value": "pharyngeal sensillum"}
            ],
            "split_by": ["entryNerve", "rootSide"],
        },
        {
            "modality": "gustatory-other", "priority": 50, "combine": "all", "kind": "declared",
            "queries": [{"field": "class", "operator": "exact", "value": "gustatory"}],
            "split_by": ["entryNerve", "rootSide"],
        },
    ])
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1,)), registry_path=registry_path)

    assert atlas.modality_bodies["pharyngeal"] == (1,)
    assert atlas.modality_bodies["gustatory-other"] == ()
    assert atlas.ledger["assigned"] == 1
    assert sum(len(ids) for ids in atlas.channels.values()) == 1


def test_two_rungs_at_one_priority_claiming_the_same_body_is_an_error(tmp_path: Path) -> None:
    """First-match-wins would resolve this by declaration order, which hides the bug."""
    rows = [_sensory(1, subclass="haltere", **{"class": "mechanosensory"})]
    registry = _registry([
        {
            "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
            "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
            "split_by": ["rootSide"],
        },
        {
            "modality": "mechano-other", "priority": 20, "combine": "all", "kind": "real",
            "queries": [{"field": "class", "operator": "exact", "value": "mechanosensory"}],
            "split_by": ["rootSide"],
        },
    ])
    annotations, registry_path = _write(tmp_path, rows, registry)
    with pytest.raises(ConfigurationError, match="share priority"):
        SensoryAtlas.resolve(annotations, _Graph((1,)), registry_path=registry_path)


def test_bodies_the_ladder_does_not_match_are_named_not_dropped(tmp_path: Path) -> None:
    rows = [_sensory(1, subclass="haltere"), _sensory(2, **{"class": None, "subclass": None})]
    registry = _registry([{
        "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
        "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
        "split_by": ["rootSide"],
    }])
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1, 2)), registry_path=registry_path)

    assert atlas.unassigned == (2,)
    assert atlas.ledger["assigned"] + atlas.ledger["unassigned"] == 2


def test_an_unknown_side_becomes_its_own_channel_rather_than_a_discard(tmp_path: Path) -> None:
    """Demo01Populations drops unknown-side bodies and counts them. A bus that claims to
    carry every labelled sense may not do that, or the ledger stops closing."""
    rows = [
        _sensory(1, subclass="haltere", rootSide="L"),
        _sensory(2, subclass="haltere", rootSide=None),
    ]
    registry = _registry([{
        "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
        "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
        "split_by": ["entryNerve", "rootSide"],
    }])
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1, 2)), registry_path=registry_path)

    assert atlas.bodies_for(ChannelKey("haltere", "antenna", "L")) == (1,)
    assert atlas.bodies_for(ChannelKey("haltere", "antenna", "unknown")) == (2,)
    assert atlas.ledger["unassigned"] == 0


def test_a_channel_whose_count_moved_fails_closed(tmp_path: Path) -> None:
    rows = [_sensory(1, subclass="haltere")]
    registry = _registry([{
        "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
        "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
        "split_by": ["rootSide"], "expected_bodies": 205,
    }])
    annotations, registry_path = _write(tmp_path, rows, registry)
    with pytest.raises(DatasetError, match="resolves to 1 bodies"):
        SensoryAtlas.resolve(annotations, _Graph((1,)), registry_path=registry_path)


def test_a_body_outside_the_graph_is_not_in_the_atlas(tmp_path: Path) -> None:
    rows = [_sensory(1, subclass="haltere"), _sensory(2, subclass="haltere")]
    registry = _registry([{
        "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
        "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
        "split_by": ["rootSide"],
    }])
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1,)), registry_path=registry_path)

    assert atlas.modality_bodies["haltere"] == (1,)
    assert atlas.ledger["in_graph_sensory_bodies"] == 1


def test_an_absent_channel_is_resolved_but_never_drivable(tmp_path: Path) -> None:
    """'Everything labelled, enabled' still has to stop at senses with no world quantity.
    Thermo and hygro are resolved so the partition is total, and excluded from driving so
    that no invented temperature field reaches the network."""
    rows = [_sensory(1, subclass="haltere"), _sensory(2, **{"class": "thermosensory"})]
    registry = _registry([
        {
            "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
            "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
            "split_by": ["rootSide"],
        },
        {
            "modality": "thermosensory", "priority": 40, "combine": "all", "kind": "absent",
            "queries": [{"field": "class", "operator": "exact", "value": "thermosensory"}],
            "split_by": ["rootSide"],
            "absent_reason": "MuJoCo carries no temperature field.",
        },
    ])
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1, 2)), registry_path=registry_path)

    assert atlas.modality_bodies["thermosensory"] == (2,)
    assert "thermosensory" not in atlas.drivable_modalities()
    assert "haltere" in atlas.drivable_modalities()
    assert atlas.modality_note["thermosensory"]


def test_a_surrogate_entry_joins_the_union_without_joining_the_partition(tmp_path: Path) -> None:
    """The lamina is the entry vision actually uses, because every photoreceptor edge is
    zeroed by the sign policy. It is ol_intrinsic, so it is not part of the sensory
    partition -- but it must be inside the frozen union or enabling vision rebuilds the
    kernel."""
    rows = [
        _sensory(1, subclass="haltere"),
        {"bodyId": 2, "type": "L1", "class": None, "subclass": None,
         "superclass": "ol_intrinsic", "entryNerve": None, "rootSide": "L"},
    ]
    registry = _registry(
        [{
            "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
            "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
            "split_by": ["rootSide"],
        }],
        surrogate_entries=[{
            "id": "lamina-surrogate", "combine": "any",
            "queries": [{"field": "type", "operator": "regex", "value": "^(L1|L2|L5)$"}],
            "split_by": ["rootSide"], "organ_override": "optic-lobe",
        }],
    )
    annotations, registry_path = _write(tmp_path, rows, registry)
    atlas = SensoryAtlas.resolve(annotations, _Graph((1, 2)), registry_path=registry_path)

    assert atlas.surrogates["lamina-surrogate"] == (2,)
    assert atlas.ledger["in_graph_sensory_bodies"] == 1
    assert atlas.entry_union == (1, 2)


def test_the_entry_union_digest_depends_only_on_the_set(tmp_path: Path) -> None:
    """The union is hashed into every artifact, and into the GeNN model identity through
    entry_body_ids. Row order in the annotation table must not move it."""
    rows = [_sensory(1, subclass="haltere"), _sensory(2, subclass="haltere")]
    registry = _registry([{
        "modality": "haltere", "priority": 20, "combine": "all", "kind": "real",
        "queries": [{"field": "subclass", "operator": "exact", "value": "haltere"}],
        "split_by": ["rootSide"],
    }])
    first = tmp_path / "forward"
    second = tmp_path / "reverse"
    first.mkdir()
    second.mkdir()
    forward_annotations, forward_registry = _write(first, rows, registry)
    reverse_annotations, reverse_registry = _write(second, list(reversed(rows)), registry)
    forward = SensoryAtlas.resolve(
        forward_annotations, _Graph((1, 2)), registry_path=forward_registry
    )
    reverse = SensoryAtlas.resolve(
        reverse_annotations, _Graph((2, 1)), registry_path=reverse_registry
    )

    assert forward.entry_union == reverse.entry_union == (1, 2)
    assert forward.entry_union_sha256 == reverse.entry_union_sha256


def test_the_released_atlas_partitions_the_sensory_set(tmp_path: Path) -> None:
    """Against the real release, if it is staged. These are the numbers the plan rests on."""
    root = Path(os.environ.get("FLYSIM_DATA_ROOT", "/srv/flybrain-data"))
    annotations = root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    graph_path = root / "derived/male-cns-v1.0/graph"
    if not annotations.exists() or not graph_path.exists():
        pytest.skip("the MaleCNS release is not staged in this environment")

    from flysim.connectome import SparseConnectome

    graph = SparseConnectome.load(graph_path)
    atlas = SensoryAtlas.resolve(annotations, graph)

    assert atlas.ledger["in_graph_sensory_bodies"] == 15912
    assert atlas.ledger["assigned"] == 15856
    assert atlas.ledger["unassigned"] == 56
    assert atlas.ledger["modalities"] == 30
    assert atlas.ledger["by_kind"] == {"absent": 2, "declared": 9, "real": 19}
    lamina = atlas.surrogates["lamina-surrogate"]
    assert lamina == tuple(sorted(lamina))
    assert len(lamina) == 5342
    assert len(atlas.entry_union) == 15912 + 5342

    # No body is claimed twice, which is the property SignalFrame would otherwise enforce
    # at injection time, halfway through a twenty-second run.
    seen: set[int] = set()
    for ids in atlas.channels.values():
        assert not seen & set(ids)
        seen.update(ids)
    assert len(seen) == 15856

    # The routes the behaviours are built on, resolved to organ and side.
    assert len(atlas.bodies_for(ChannelKey("antennal-jo-f-grooming", "antenna", "L"))) == 40
    assert len(atlas.bodies_for(ChannelKey("antennal-jo-f-grooming", "antenna", "R"))) == 25
    assert len(atlas.bodies_for(ChannelKey("haltere", "haltere", "L"))) == 104
    # Taste bristles sit on the legs, which is what makes tarsal taste addressable per leg.
    assert len(atlas.bodies_for(ChannelKey("tarsal-taste", "leg-hind", "R"))) == 38
    assert len(atlas.bodies_for(ChannelKey("tarsal-taste", "leg-front", "L"))) == 6

    assert "thermosensory" not in atlas.drivable_modalities()
    assert "hygrosensory" not in atlas.drivable_modalities()
