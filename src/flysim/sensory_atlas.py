# SPDX-License-Identifier: GPL-2.0-or-later
"""Every sense the MaleCNS release labels, resolved as an ordered partition.

DEMO-01 drives one sensory population and the other fifteen thousand labelled afferents sit
inert. This module is the first half of changing that: it turns the released annotation
columns into a set of named channels, each carrying an organ and a side, so that an encoder
can bind to a sense rather than to a hand-written list of body IDs.

**Why a partition rather than a set of filters.** Selectors overlap in the real data.
Subclass ``pharyngeal sensillum`` spans class ``gustatory`` (48 bodies) and class
``mechanosensory`` (39); subclass ``haltere`` spans ``mechanosensory_proprioceptive`` (201)
and ``unknown_sensory`` (4); subclass ``abdomen`` spans three classes. Independent filters
would therefore claim the same body twice, and :class:`flysim.contracts.SignalFrame` rejects
duplicate ids -- so the failure would land at the moment of injection, deep inside a run,
rather than at the moment somebody wrote the selector. Here every in-graph sensory body is
assigned to exactly one channel by a priority ladder, first match wins, and what is left
over is named in the ledger instead of quietly disappearing.

**Where organ and side come from.** ``SENS-01`` requires every sensory population to declare
an organ and a side, and nothing in this codebase has ever supplied them. They are in the
release: ``entryNerve`` names the nerve an axon enters through, which is a fact about
peripheral anatomy the connectome does retain, and ``rootSide`` carries the entry side.
``somaSide`` is useless here -- it is null for sensory neurons, because their somata are
peripheral and outside the imaged volume.

Structural only. A channel resolving here says the release gave these bodies these labels.
It says nothing about what they respond to, with what tuning, sign or delay.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from flysim.config import load_json
from flysim.errors import ConfigurationError, DatasetError

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for type checkers
    from flysim.connectome import SparseConnectome

DEFAULT_REGISTRY = (
    Path(__file__).resolve().parent.parent.parent
    / "configs/populations/malecns-sensory-atlas-v1.json"
)

REQUIRED_COLUMNS = (
    "bodyId",
    "type",
    "class",
    "subclass",
    "superclass",
    "entryNerve",
    "rootSide",
)

KNOWN_SIDES = frozenset({"L", "R"})
UNKNOWN = "unknown"

#: Channel kinds. ``real`` has a genuine MuJoCo referent; ``declared`` is an invented world
#: field carried under an explicit assumption; ``absent`` has neither and is never driven.
CHANNEL_KINDS = frozenset({"real", "declared", "absent"})


@dataclass(frozen=True, slots=True, order=True)
class ChannelKey:
    """A sense, at an organ, on a side. The address an encoder binds to."""

    modality: str
    organ: str
    side: str

    def __str__(self) -> str:
        return f"{self.modality}:{self.organ}:{self.side}"

    @classmethod
    def parse(cls, text: str) -> ChannelKey:
        parts = text.split(":")
        if len(parts) != 3:
            raise ConfigurationError(f"Not a channel key: {text!r}")
        return cls(parts[0], parts[1], parts[2])


@dataclass(frozen=True, slots=True)
class SensoryAtlas:
    """The resolved partition, its coverage ledger, and the frozen entry union."""

    registry_id: str
    annotations_sha256: str
    channels: dict[str, tuple[int, ...]]
    channel_keys: tuple[ChannelKey, ...]
    modality_kind: dict[str, str]
    modality_bodies: dict[str, tuple[int, ...]]
    modality_note: dict[str, str]
    surrogates: dict[str, tuple[int, ...]]
    unassigned: tuple[int, ...]
    entry_union: tuple[int, ...]
    entry_union_sha256: str
    ledger: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ queries

    def bodies_for(self, key: ChannelKey | str) -> tuple[int, ...]:
        return self.channels.get(str(key), ())

    def keys_for_modality(self, modality: str) -> tuple[ChannelKey, ...]:
        return tuple(key for key in self.channel_keys if key.modality == modality)

    def drivable_modalities(self) -> tuple[str, ...]:
        """Modalities with a world referent. ``absent`` channels are never driven."""
        return tuple(
            sorted(name for name, kind in self.modality_kind.items() if kind != "absent")
        )

    # ------------------------------------------------------------------ resolve

    @classmethod
    def resolve(
        cls,
        annotations_path: Path,
        graph: SparseConnectome,
        *,
        registry_path: Path | None = None,
    ) -> SensoryAtlas:
        import pyarrow.compute as pc
        import pyarrow.feather as feather

        from flysim.populations import _query_mask

        registry = load_json(registry_path or DEFAULT_REGISTRY)
        table = feather.read_table(annotations_path, memory_map=True)
        missing = [name for name in REQUIRED_COLUMNS if name not in table.column_names]
        if missing:
            raise DatasetError(f"Annotation table lacks columns {missing}")

        in_graph = {int(body) for body in graph.body_ids}
        superclasses = frozenset(str(v) for v in registry["sensory_superclasses"])
        body_column = [int(v) for v in table.column("bodyId").to_pylist()]
        superclass_column = [str(v or "") for v in table.column("superclass").to_pylist()]
        paired = zip(body_column, superclass_column, strict=True)
        universe_rows = [
            row
            for row, (body, superclass) in enumerate(paired)
            if body in in_graph and superclass in superclasses
        ]
        universe = table.take(universe_rows)
        total = universe.num_rows

        bodies = np.array(
            [int(v) for v in universe.column("bodyId").to_pylist()], dtype=np.int64
        )
        nerves = [str(v or "") for v in universe.column("entryNerve").to_pylist()]
        sides = [str(v or "") for v in universe.column("rootSide").to_pylist()]
        nerve_to_organ = {str(k): str(v) for k, v in registry["nerve_to_organ"].items()}

        def mask_of(specification: dict[str, Any], source: Any) -> np.ndarray:
            masks = [_query_mask(source, query) for query in specification["queries"]]
            combine = str(specification.get("combine", "all"))
            merged = masks[0]
            for item in masks[1:]:
                merged = pc.and_(merged, item) if combine == "all" else pc.or_(merged, item)
            if combine not in {"all", "any"}:
                raise ConfigurationError(f"Invalid query combination: {combine}")
            return np.asarray(pc.fill_null(merged, False).to_pylist(), dtype=bool)

        specifications = list(registry["channels"])
        raw = [mask_of(spec, universe) for spec in specifications]

        # Two selectors at the same priority claiming one body is an authoring bug, and
        # first-match-wins would silently hide it behind declaration order.
        by_priority: dict[int, list[int]] = {}
        for index, spec in enumerate(specifications):
            by_priority.setdefault(int(spec["priority"]), []).append(index)
        for priority, indices in sorted(by_priority.items()):
            for position, left in enumerate(indices):
                for right in indices[position + 1 :]:
                    clash = int(np.count_nonzero(raw[left] & raw[right]))
                    if clash:
                        raise ConfigurationError(
                            f"Channels {specifications[left]['modality']!r} and "
                            f"{specifications[right]['modality']!r} share priority "
                            f"{priority} and both claim {clash} bodies. Give one a lower "
                            "priority so the ladder is explicit, or narrow the selector."
                        )

        claimed = np.zeros(total, dtype=bool)
        channels: dict[str, tuple[int, ...]] = {}
        channel_keys: list[ChannelKey] = []
        modality_kind: dict[str, str] = {}
        modality_bodies: dict[str, tuple[int, ...]] = {}
        modality_note: dict[str, str] = {}
        rungs: list[dict[str, Any]] = []

        order = sorted(
            range(len(specifications)),
            key=lambda i: (int(specifications[i]["priority"]), i),
        )
        for index in order:
            spec = specifications[index]
            modality = str(spec["modality"])
            kind = str(spec["kind"])
            if kind not in CHANNEL_KINDS:
                raise ConfigurationError(f"Channel {modality!r} has unknown kind {kind!r}")
            if modality in modality_kind:
                raise ConfigurationError(f"Duplicate channel modality: {modality}")
            take = raw[index] & ~claimed
            claimed |= take
            selected = np.flatnonzero(take)

            expected = spec.get("expected_bodies")
            if expected is not None and int(expected) != selected.size:
                raise DatasetError(
                    f"Channel {modality!r} resolves to {selected.size} bodies but the "
                    f"registry declares {int(expected)}. The annotation release or the "
                    "selector changed; update the registry deliberately rather than "
                    "letting a count drift."
                )

            split_by = tuple(str(v) for v in spec.get("split_by", ()))
            organ_override = spec.get("organ_override")
            grouped: dict[ChannelKey, list[int]] = {}
            for row in selected:
                if organ_override is not None:
                    organ = str(organ_override)
                elif "entryNerve" in split_by:
                    organ = nerve_to_organ.get(nerves[row], UNKNOWN)
                else:
                    organ = UNKNOWN
                side = sides[row] if sides[row] in KNOWN_SIDES else UNKNOWN
                if "rootSide" not in split_by:
                    side = UNKNOWN
                grouped.setdefault(ChannelKey(modality, organ, side), []).append(int(bodies[row]))

            for key in sorted(grouped):
                channels[str(key)] = tuple(sorted(grouped[key]))
                channel_keys.append(key)
            modality_kind[modality] = kind
            modality_bodies[modality] = tuple(sorted(int(bodies[row]) for row in selected))
            note = spec.get("note") or spec.get("absent_reason") or ""
            modality_note[modality] = str(note)
            rungs.append({
                "modality": modality,
                "priority": int(spec["priority"]),
                "kind": kind,
                "matched_before_claiming": int(np.count_nonzero(raw[index])),
                "claimed": int(selected.size),
                "channels": len(grouped),
            })

        unassigned = tuple(sorted(int(body) for body in bodies[~claimed]))
        expected_unassigned = registry.get("expected_unassigned")
        if expected_unassigned is not None and int(expected_unassigned) != len(unassigned):
            raise DatasetError(
                f"{len(unassigned)} bodies fall through the ladder but the registry "
                f"declares {int(expected_unassigned)}."
            )
        expected_total = registry.get("expected_total_in_graph")
        if expected_total is not None and int(expected_total) != total:
            raise DatasetError(
                f"{total} sensory bodies are in the graph but the registry declares "
                f"{int(expected_total)}."
            )

        assigned = sum(len(v) for v in channels.values())
        if assigned + len(unassigned) != total:
            raise ConfigurationError(
                f"Ledger does not close: {assigned} assigned + {len(unassigned)} "
                f"unassigned != {total} in-graph sensory bodies."
            )

        # Surrogates are entry points that are not sensory neurons -- the lamina, because
        # every photoreceptor edge is zeroed by the sign policy. They sit outside the
        # partition but inside the frozen entry union.
        surrogates: dict[str, tuple[int, ...]] = {}
        surrogate_ids: set[int] = set()
        for spec in registry.get("surrogate_entries", ()):
            in_graph_rows = [
                row for row, body in enumerate(body_column) if body in in_graph
            ]
            scope = table.take(in_graph_rows)
            scope_bodies = [int(v) for v in scope.column("bodyId").to_pylist()]
            found = np.flatnonzero(mask_of(spec, scope))
            picked = tuple(sorted(scope_bodies[row] for row in found))
            surrogates[str(spec["id"])] = picked
            surrogate_ids.update(picked)

        overlap = surrogate_ids & set(int(b) for b in bodies)
        if overlap:
            raise ConfigurationError(
                f"{len(overlap)} surrogate entry bodies are also sensory-superclass "
                "bodies, so the entry union would contain duplicates."
            )

        entry_union = tuple(sorted(set(int(b) for b in bodies) | surrogate_ids))
        digest = hashlib.sha256()
        digest.update(np.asarray(entry_union, dtype=np.int64).tobytes())

        ledger = {
            "in_graph_sensory_bodies": total,
            "assigned": assigned,
            "unassigned": len(unassigned),
            "channels": len(channels),
            "modalities": len(modality_kind),
            "by_kind": {
                kind: sum(1 for value in modality_kind.values() if value == kind)
                for kind in sorted(CHANNEL_KINDS)
            },
            "rungs": rungs,
            "surrogate_bodies": {name: len(v) for name, v in sorted(surrogates.items())},
            "entry_union_bodies": len(entry_union),
        }

        return cls(
            registry_id=str(registry["registry_id"]),
            annotations_sha256=_file_sha256(annotations_path),
            channels=channels,
            channel_keys=tuple(channel_keys),
            modality_kind=modality_kind,
            modality_bodies=modality_bodies,
            modality_note=modality_note,
            surrogates=surrogates,
            unassigned=unassigned,
            entry_union=entry_union,
            entry_union_sha256=digest.hexdigest(),
            ledger=ledger,
        )

    # ------------------------------------------------------------------ record

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "annotations_sha256": self.annotations_sha256,
            "entry_union_sha256": self.entry_union_sha256,
            "entry_union_bodies": len(self.entry_union),
            "ledger": self.ledger,
            "modalities": {
                name: {
                    "kind": self.modality_kind[name],
                    "bodies": len(self.modality_bodies[name]),
                    "channels": [str(key) for key in self.keys_for_modality(name)],
                    "note": self.modality_note.get(name, ""),
                }
                for name in sorted(self.modality_kind)
            },
            "channels": {name: len(ids) for name, ids in sorted(self.channels.items())},
            "unassigned_bodies": list(self.unassigned),
            "claim_boundary": (
                "Structural only. This records which released labels a body carries, not "
                "what it responds to, with what sign, tuning or delay."
            ),
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
