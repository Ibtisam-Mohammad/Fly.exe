#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""The same route measurement, at organ and side resolution instead of whole-class.

    PYTHONPATH=src python scripts/measure_channel_routes.py --root /srv/flybrain-data

Schema 2.0 of the route survey measured each sense as one lump: class ``gustatory``, all
1428 bodies, against MN9. It scored 7.4 times a matched null. Subclass ``labellar bristle``,
163 of those same bodies, scored 48.6. Nothing changed but the choice of entry population,
and the answer moved seven-fold.

That is the same lesson the lamina taught DEMO-01, which entered at L1/L2/L5 rather than at
"the visual system", and it is worth taking one step further: the release resolves most
afferents to a *nerve* and a *side*, so a leg sense can be asked about the front left leg
rather than about legs in general. This runs the identical propagation and the identical
degree-matched null over the 122 channels of :mod:`flysim.sensory_atlas` instead of over 22
class-level lumps, and reports each modality's best channel beside the modality as a whole.

It does not supersede schema 2.0 and does not overwrite it. Both artifacts stand: the
class-level one is what the behaviour contracts were reasoned from, and this one says
whether a narrower entry would have been better.

The null, the flow definition and the best-hop rule are imported from the schema-2.0 script
rather than copied, so the two surveys cannot drift apart.

Structural, and carrying the same caveat that governs every reading of it: DEMO-01's own
validated entry scores 0.44 times this null at the 0th percentile. A low score here cannot
rule a route out. Only a high score is informative.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from measure_demo02_routes import degree_bins, matched_null  # noqa: E402

from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.runs import git_metadata  # noqa: E402
from flysim.sensory_atlas import SensoryAtlas  # noqa: E402

WING_STEERING = frozenset(
    f"{name} MN"
    for name in ("b1", "b2", "b3", "i1", "i2", "iii1", "iii3", "hg1", "hg2", "hg3", "ps1",
                 "tp1", "tp2")
)

# (type, superclass) -> bool. Identical in content to schema 2.0's TARGETS; restated here
# rather than imported because that script's dict is keyed to its own source set.
TargetPredicate = Callable[[str, str], bool]

TARGETS: dict[str, tuple[str, TargetPredicate]] = {
    "DN-all": ("every descending neuron", lambda ty, sc: sc == "descending_neuron"),
    "DNp-all": ("DEMO-01's readout", lambda ty, sc: ty.startswith("DNp")),
    "DNp01-giant-fibre": ("the giant fibre", lambda ty, sc: ty == "DNp01"),
    "DNa01-DNa02": ("the steering pair", lambda ty, sc: ty in ("DNa01", "DNa02")),
    "groom-DN-track-a": (
        "the grooming descending readout Track A declared",
        lambda ty, sc: ty in ("DNg62", "DNge078", "DNg21"),
    ),
    "vnc-motor-all": ("every ventral cord motor neuron", lambda ty, sc: sc == "vnc_motor"),
    "MN9": ("the pharyngeal pump motor neuron", lambda ty, sc: ty == "MN9"),
    "proboscis-MN": (
        "proboscis motor neurons MN10, MN11, MN12",
        lambda ty, sc: ty in ("MN10", "MN11D", "MN11V", "MN12D"),
    ),
    "TTMn": ("the jump muscle motor neuron", lambda ty, sc: ty.startswith("TTM")),
    "PSI": ("the peripherally synapsing interneuron", lambda ty, sc: ty.startswith("PSI")),
    "wing-power-MN": (
        "wing power muscle motor neurons",
        lambda ty, sc: ty.startswith("DLMn") or ty.startswith("DVMn"),
    ),
    "wing-steering-MN": ("the wing steering motor neurons", lambda ty, sc: ty in WING_STEERING),
}


def resolve_targets(
    annotations_path: Path, graph: SparseConnectome
) -> dict[str, np.ndarray]:
    import pyarrow.feather as feather

    table = feather.read_table(annotations_path, columns=("bodyId", "type", "superclass"))
    bodies = [int(v) for v in table.column("bodyId").to_pylist()]
    types = [str(v or "") for v in table.column("type").to_pylist()]
    superclasses = [str(v or "") for v in table.column("superclass").to_pylist()]
    dense_of = {int(body): graph.dense_index(int(body)) for body in graph.body_ids}

    resolved: dict[str, np.ndarray] = {}
    for name, (_, predicate) in TARGETS.items():
        found = {
            dense_of[body]
            for body, ty, sc in zip(bodies, types, superclasses, strict=True)
            if body in dense_of and predicate(ty, sc)
        }
        resolved[name] = np.array(sorted(found), dtype=np.int64)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--hops", type=int, default=4)
    parser.add_argument("--null-draws", type=int, default=64)
    parser.add_argument("--degree-bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument(
        "--min-bodies", type=int, default=1,
        help="Skip channels smaller than this. Default 1, i.e. skip nothing.",
    )
    args = parser.parse_args()

    from scipy.sparse import csr_matrix

    graph = SparseConnectome.load(args.root / "derived/male-cns-v1.0/graph")
    graph.validate()
    source = np.asarray(graph.source_indices)
    target = np.asarray(graph.target_indices)
    contacts = np.asarray(graph.contact_counts).astype(np.float64)
    count = graph.neuron_count
    annotations = (
        args.root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )

    atlas = SensoryAtlas.resolve(annotations, graph)
    dense_of = {int(body): graph.dense_index(int(body)) for body in graph.body_ids}
    targets = resolve_targets(annotations, graph)
    print(f"graph: {count:,} neurons, {len(source):,} edges")
    print(f"atlas: {len(atlas.channels)} channels over {len(atlas.modality_bodies)} modalities")

    # Sources are every channel, plus each modality as a whole so the split can be judged
    # against the lump it came from, plus the lamina surrogate as the calibration entry.
    sources: dict[str, tuple[str, np.ndarray]] = {}
    for name, ids in atlas.channels.items():
        if len(ids) >= args.min_bodies:
            sources[f"channel:{name}"] = (
                "channel", np.array([dense_of[b] for b in ids], dtype=np.int64)
            )
    for name, ids in atlas.modality_bodies.items():
        if len(ids) >= args.min_bodies:
            sources[f"modality:{name}"] = (
                "modality", np.array([dense_of[b] for b in ids], dtype=np.int64)
            )
    for name, ids in atlas.surrogates.items():
        sources[f"surrogate:{name}"] = (
            "surrogate", np.array([dense_of[b] for b in ids], dtype=np.int64)
        )
    print(f"sources: {len(sources)}")

    input_contacts = np.bincount(target, weights=contacts, minlength=count)
    out_contacts = np.bincount(source, weights=contacts, minlength=count)
    edge_share = contacts / np.maximum(input_contacts[target], 1.0)
    weights = csr_matrix((edge_share, (target, source)), shape=(count, count))
    bin_of = degree_bins(out_contacts, args.degree_bins)
    rng = np.random.default_rng(args.seed)

    source_mask = np.zeros(count, dtype=bool)
    target_mask = np.zeros(count, dtype=bool)
    rows: list[dict[str, Any]] = []

    for index, (source_name, (kind, members)) in enumerate(sorted(sources.items()), start=1):
        if members.size == 0:
            continue
        observed = np.zeros(count)
        observed[members] = 1.0 / members.size
        null = matched_null(members, bin_of, args.degree_bins, args.null_draws, rng)
        state = np.concatenate([observed[:, None], null], axis=1)
        print(f"  [{index}/{len(sources)}] {source_name} ({members.size} bodies)", flush=True)
        per_hop: list[np.ndarray] = []
        for _ in range(args.hops):
            state = weights @ state
            per_hop.append(state.copy())

        source_mask[:] = False
        source_mask[members] = True
        for target_name, target_members in targets.items():
            if target_members.size == 0:
                continue
            target_mask[:] = False
            target_mask[target_members] = True
            direct = source_mask[source] & target_mask[target]
            direct_edges = int(direct.sum())
            direct_share = (
                float(contacts[direct].sum() / max(input_contacts[target_members].sum(), 1.0))
                if direct_edges
                else 0.0
            )
            hops: list[dict[str, Any]] = []
            for hop, snapshot in enumerate(per_hop, start=1):
                arrived = snapshot[target_members].sum(axis=0) / target_members.size
                seen, nulls = float(arrived[0]), arrived[1:]
                median = float(np.median(nulls))
                ratio = (seen / median) if median > 0 else (float("inf") if seen > 0 else 0.0)
                hops.append({
                    "hop": hop,
                    "flow": seen,
                    "null_median": median,
                    "ratio_to_null": ratio,
                    "percentile_in_null": float((nulls < seen).mean() * 100.0),
                })
            best = max(
                hops,
                key=lambda h: h["ratio_to_null"] if np.isfinite(h["ratio_to_null"]) else -1.0,
            )
            rows.append({
                "source": source_name,
                "source_kind": kind,
                "target": target_name,
                "source_bodies": int(members.size),
                "target_bodies": int(target_members.size),
                "direct_edges": direct_edges,
                "direct_contact_share": direct_share,
                "hops": hops,
                "best_hop": best["hop"],
                "best_ratio_to_null": best["ratio_to_null"],
                "best_percentile": best["percentile_in_null"],
            })

    def finite(value: float) -> float:
        return value if np.isfinite(value) else 1e18

    # Does splitting a modality by organ and side beat the modality as a whole?
    comparison: list[dict[str, Any]] = []
    for modality in atlas.modality_bodies:
        for target_name in targets:
            lump = next(
                (
                    row for row in rows
                    if row["source"] == f"modality:{modality}" and row["target"] == target_name
                ),
                None,
            )
            if lump is None:
                continue
            parts = [
                row for row in rows
                if row["source_kind"] == "channel"
                and row["source"].startswith(f"channel:{modality}:")
                and row["target"] == target_name
            ]
            if len(parts) < 2:
                continue
            best_part = max(parts, key=lambda r: finite(r["best_ratio_to_null"]))
            comparison.append({
                "modality": modality,
                "target": target_name,
                "modality_ratio": lump["best_ratio_to_null"],
                "best_channel": best_part["source"],
                "best_channel_ratio": best_part["best_ratio_to_null"],
                "gain_from_splitting": (
                    finite(best_part["best_ratio_to_null"]) / lump["best_ratio_to_null"]
                    if lump["best_ratio_to_null"] > 0 else float("inf")
                ),
                "channels_compared": len(parts),
            })
    comparison.sort(key=lambda c: -finite(c["gain_from_splitting"]))

    rows.sort(key=lambda r: -finite(r["best_ratio_to_null"]))
    header = (
        f"{'source':44s} {'target':20s} {'src':>5s} {'edges':>7s} {'hop':>4s} "
        f"{'x null':>9s} {'pct':>6s}"
    )
    print("\ntop 40 routes\n" + header)
    print("-" * len(header))
    for row in rows[:40]:
        print(
            f"{row['source']:44s} {row['target']:20s} {row['source_bodies']:5d} "
            f"{row['direct_edges']:7d} {row['best_hop']:4d} "
            f"{row['best_ratio_to_null']:9.1f} {row['best_percentile']:5.1f}%"
        )

    print("\nwhere splitting by organ and side helps most")
    print(f"{'modality':26s} {'target':20s} {'lump':>8s} {'best part':>10s} {'gain':>7s}")
    for entry in comparison[:20]:
        print(
            f"{entry['modality']:26s} {entry['target']:20s} "
            f"{entry['modality_ratio']:8.1f} {entry['best_channel_ratio']:10.1f} "
            f"{entry['gain_from_splitting']:7.2f}x"
        )

    payload = {
        "schema_version": "3.0",
        "supersedes": (
            "nothing. Schema 2.0 stands unchanged and is the artifact the behaviour "
            "contracts were reasoned from. This one asks a narrower question: whether a "
            "sense resolved to an organ and a side reaches a target better than the same "
            "sense taken as a whole class."
        ),
        "why_this_exists": (
            "Schema 2.0 measured class gustatory (1428 bodies) to MN9 at 7.4x a matched "
            "null and subclass labellar bristle (163 of those same bodies) at 48.6x. "
            "Nothing changed but the entry population and the answer moved seven-fold, so "
            "entry specificity is worth measuring rather than assuming."
        ),
        "method": {
            "flow": (
                "One unit of drive spread over the source population, propagated along "
                "edges weighted by each edge's share of the target neuron's total input "
                "contacts. Imported from the schema-2.0 script, not reimplemented."
            ),
            "null": (
                f"{args.null_draws} random source sets per source, matched in size and "
                f"out-contact profile across {args.degree_bins} quantile bins."
            ),
            "scoring": "Each route is scored at the hop where it stands highest.",
            "blind_to": "sign, dynamics, delay, and whether the network uses the path",
        },
        "instrument_limit": (
            "DEMO-01's validated lamina entry scores about 0.44 times this null at the "
            "0th percentile, and that route passed a frozen causal contract. Flow dilutes "
            "across four hops and 89390 optic lobe neurons. A low score therefore cannot "
            "rule a route out; only a high score is informative."
        ),
        "graph": {
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "atlas": atlas.as_dict(),
        "targets": {name: {"description": TARGETS[name][0], "bodies": int(ids.size)}
                    for name, ids in sorted(targets.items())},
        "routes": rows,
        "splitting_comparison": comparison,
        "claim_boundary": (
            "Structural only. A high ratio says the released wiring connects these "
            "populations far more than a size- and degree-matched random set would. It "
            "does not say the network uses that path, with what sign, or that any "
            "behaviour follows."
        ),
        "seed": args.seed,
        "git": git_metadata(),
    }
    output = args.output or args.root / "evidence/demo02/channel-route-survey.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nartifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
