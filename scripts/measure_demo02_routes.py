#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure every labelled sense against every candidate output, before building anything.

    PYTHONPATH=src python scripts/measure_demo02_routes.py --root /srv/flybrain-data

DEMO-01 chose its route by measurement and abandoned the olfactory one because the numbers
said it could not work. This applies the same idea to the whole sensory inventory, and it
exists because a first version of this survey was not good enough to support the conclusion
it was used for.

That first version measured two routes, compared them against a yardstick that had been
computed with a different normalisation, and concluded that feeding "has no route". Three
things were wrong with that. It looked only at direct edges for a pathway that is
polysynaptic in every animal, so absence of a one-hop edge proved nothing. It compared a
one-hop route's first-hop flow against a three-hop route's third-hop flow, which is not a
comparison, because flow decays with distance whatever the route's quality. And it had no
null, so there was no way to say whether any number was large.

What is here instead:

**Every sense the release labels**, not the two that were convenient, including the ones a
first pass forgets: wind and gravity, halteres, chordotonal organs, campaniform sensilla,
thermo, hygro, and the tactile bristles.

**A degree-matched null.** For each source population, sets of the same size and the same
out-contact profile are drawn at random and pushed through the identical propagation. A
route is reported as a ratio against the median of that null and as a percentile within it.
This is the part that makes a number answerable: 2.4e-05 means nothing on its own, and
"eleven times what a matched random population achieves" means something.

**The best hop, not a fixed hop.** Each route is scored at the hop where it stands highest
against its own null, and that hop is reported, so a polysynaptic pathway is not penalised
for being polysynaptic.

Still structural. Flow is contact share: one unit of drive spread over the source
population, propagated along edges weighted by each edge's share of the target neuron's
total input contacts. It is blind to sign, to dynamics and to delay, so a strong route here
is necessary for a demonstration and nowhere near sufficient.
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

from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.runs import git_metadata  # noqa: E402

SENSORY_SUPERCLASSES = frozenset({
    "cb_sensory", "vnc_sensory", "ol_sensory", "sensory_ascending", "sensory_descending",
    "cb_sensory_tbc", "vnc_sensory_tbc", "sensory_ascending_tbc",
})
WING_STEERING = frozenset(
    f"{name} MN"
    for name in ("b1", "b2", "b3", "i1", "i2", "iii1", "iii3", "hg1", "hg2", "hg3", "ps1",
                 "tp1", "tp2")
)

# (type, class, subclass, superclass) -> bool
Predicate = Callable[[str, str, str, str], bool]


def _sense(class_name: str) -> Predicate:
    return lambda ty, cl, sub, sc: sc in SENSORY_SUPERCLASSES and cl == class_name


def _subsense(subclass_name: str) -> Predicate:
    return lambda ty, cl, sub, sc: sc in SENSORY_SUPERCLASSES and sub == subclass_name


SOURCES: dict[str, tuple[str, Predicate]] = {
    "visual": ("every sensory-superclass neuron labelled class visual", _sense("visual")),
    "olfactory": ("class olfactory", _sense("olfactory")),
    "gustatory": ("class gustatory", _sense("gustatory")),
    "mechano-tactile": ("class mechanosensory_tactile", _sense("mechanosensory_tactile")),
    "mechano-proprio": ("class mechanosensory_proprioceptive",
                        _sense("mechanosensory_proprioceptive")),
    "mechano-other": ("class mechanosensory", _sense("mechanosensory")),
    "thermosensory": ("class thermosensory", _sense("thermosensory")),
    "hygrosensory": ("class hygrosensory", _sense("hygrosensory")),
    "chemosensory": ("class chemosensory", _sense("chemosensory")),
    "unknown-sensory": ("class unknown_sensory", _sense("unknown_sensory")),
    "wind-gravity": ("subclass wind_gravity, the antennal wind and gravity receptors",
                     _subsense("wind_gravity")),
    "haltere": ("subclass haltere, the gyroscopic organ", _subsense("haltere")),
    "chordotonal": ("subclass chordotonal organ", _subsense("chordotonal organ")),
    "campaniform": ("subclass campaniform sensilla", _subsense("campaniform sensilla")),
    "auditory": ("subclass auditory", _subsense("auditory")),
    "grooming-subclass": ("subclass grooming, the population Track A declared",
                          _subsense("grooming")),
    "taste-bristle": ("subclass taste bristle", _subsense("taste bristle")),
    "labellar-bristle": ("subclass labellar bristle", _subsense("labellar bristle")),
    "pharyngeal": ("subclass pharyngeal sensillum", _subsense("pharyngeal sensillum")),
    # Entry points that are not sensory neurons, for reference.
    "lamina-L1L2L5": ("DEMO-01's validated entry, one synapse past the photoreceptors",
                      lambda ty, cl, sub, sc: ty in ("L1", "L2", "L5")),
    "LC4": ("Lobula columnar type 4, a looming detector", lambda ty, cl, sub, sc: ty == "LC4"),
    "LPLC2": ("Lobula plate columnar type 2, a looming detector",
              lambda ty, cl, sub, sc: ty == "LPLC2"),
}

TARGETS: dict[str, tuple[str, Predicate]] = {
    "DN-all": ("every descending neuron",
               lambda ty, cl, sub, sc: sc == "descending_neuron"),
    "DNp-all": ("DEMO-01's readout, the posterior descending group",
                lambda ty, cl, sub, sc: ty.startswith("DNp")),
    "DNa01-DNa02": ("the steering descending pair the olfactory route failed to reach",
                    lambda ty, cl, sub, sc: ty in ("DNa01", "DNa02")),
    "DNp01-giant-fibre": ("the giant fibre", lambda ty, cl, sub, sc: ty == "DNp01"),
    "groom-DN-track-a": ("the grooming descending readout Track A declared",
                         lambda ty, cl, sub, sc: ty in ("DNg62", "DNge078", "DNg21")),
    "DNg12": ("DNg12 subtypes", lambda ty, cl, sub, sc: ty.startswith("DNg12")),
    "vnc-motor-all": ("every ventral cord motor neuron",
                      lambda ty, cl, sub, sc: sc == "vnc_motor"),
    "MN9": ("the pharyngeal pump motor neuron", lambda ty, cl, sub, sc: ty == "MN9"),
    "proboscis-MN": ("proboscis motor neurons MN10, MN11, MN12",
                     lambda ty, cl, sub, sc: ty in ("MN10", "MN11D", "MN11V", "MN12D")),
    "TTMn": ("the jump muscle motor neuron", lambda ty, cl, sub, sc: ty.startswith("TTM")),
    "PSI": ("the peripherally synapsing interneuron",
            lambda ty, cl, sub, sc: ty.startswith("PSI")),
    "wing-power-MN": ("wing power muscle motor neurons",
                      lambda ty, cl, sub, sc: ty.startswith("DLMn") or ty.startswith("DVMn")),
    "wing-steering-MN": ("the thirteen wing steering motor neurons",
                         lambda ty, cl, sub, sc: ty in WING_STEERING),
}

# Which source is asked about which target. Every sense is asked about the two generic
# outputs; specific pairings are added where a named circuit exists to check.
GENERIC_TARGETS = ("DN-all", "vnc-motor-all")
SPECIFIC: tuple[tuple[str, str], ...] = (
    ("lamina-L1L2L5", "DNp-all"),
    ("LC4", "DNp-all"),
    ("LC4", "DNp01-giant-fibre"),
    ("LPLC2", "DNp01-giant-fibre"),
    ("visual", "DNp01-giant-fibre"),
    ("olfactory", "DNa01-DNa02"),
    ("olfactory", "DNp-all"),
    ("gustatory", "MN9"),
    ("gustatory", "proboscis-MN"),
    ("taste-bristle", "MN9"),
    ("labellar-bristle", "MN9"),
    ("pharyngeal", "MN9"),
    ("mechano-tactile", "groom-DN-track-a"),
    ("mechano-tactile", "DNg12"),
    ("grooming-subclass", "groom-DN-track-a"),
    ("wind-gravity", "DN-all"),
    ("haltere", "wing-steering-MN"),
    ("haltere", "DN-all"),
    ("campaniform", "vnc-motor-all"),
    ("chordotonal", "vnc-motor-all"),
    ("thermosensory", "DN-all"),
    ("hygrosensory", "DN-all"),
)


def resolve(
    annotations_path: Path, graph: SparseConnectome, wanted: dict[str, tuple[str, Predicate]]
) -> dict[str, np.ndarray]:
    import pyarrow.feather as feather

    table = feather.read_table(annotations_path)
    needed = ("bodyId", "type", "class", "subclass", "superclass")
    missing = [name for name in needed if name not in table.column_names]
    if missing:
        raise SystemExit(f"Annotation table lacks columns {missing}")
    columns = {name: table.column(name).to_pylist() for name in needed}
    dense_by_body = {int(body): graph.dense_index(int(body)) for body in graph.body_ids}

    resolved: dict[str, np.ndarray] = {}
    for name, (_, predicate) in wanted.items():
        found: set[int] = set()
        for row, body in enumerate(columns["bodyId"]):
            dense = dense_by_body.get(int(body))
            if dense is None:
                continue
            if predicate(
                str(columns["type"][row] or ""),
                str(columns["class"][row] or ""),
                str(columns["subclass"][row] or ""),
                str(columns["superclass"][row] or ""),
            ):
                found.add(dense)
        resolved[name] = np.array(sorted(found), dtype=np.int64)
    return resolved


def degree_bins(out_contacts: np.ndarray, bins: int) -> np.ndarray:
    """Assign every neuron to an out-contact quantile bin, so nulls can match profile."""
    edges = np.quantile(out_contacts, np.linspace(0.0, 1.0, bins + 1))
    edges[0] -= 1.0
    edges[-1] += 1.0
    return np.clip(np.searchsorted(edges, out_contacts, side="right") - 1, 0, bins - 1)


def matched_null(
    sources: np.ndarray, bin_of: np.ndarray, bins: int, draws: int, rng: np.random.Generator
) -> np.ndarray:
    """``draws`` random source sets with the same size and out-contact profile."""
    members = [np.flatnonzero(bin_of == b) for b in range(bins)]
    wanted = np.bincount(bin_of[sources], minlength=bins)
    out = np.zeros((bin_of.size, draws), dtype=np.float64)
    for draw in range(draws):
        picked: list[np.ndarray] = []
        for b in range(bins):
            need = int(wanted[b])
            if need == 0:
                continue
            pool = members[b]
            take = min(need, pool.size)
            picked.append(rng.choice(pool, size=take, replace=False))
        chosen = np.concatenate(picked) if picked else np.zeros(0, dtype=np.int64)
        if chosen.size:
            out[chosen, draw] = 1.0 / chosen.size
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--hops", type=int, default=4)
    parser.add_argument("--null-draws", type=int, default=64)
    parser.add_argument("--degree-bins", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()

    from scipy.sparse import csr_matrix

    graph = SparseConnectome.load(args.root / "derived/male-cns-v1.0/graph")
    graph.validate()
    source = np.asarray(graph.source_indices)
    target = np.asarray(graph.target_indices)
    contacts = np.asarray(graph.contact_counts).astype(np.float64)
    count = graph.neuron_count
    print(f"graph: {count:,} neurons, {len(source):,} edges")

    annotations = (
        args.root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    pops = resolve(annotations, graph, {**SOURCES, **TARGETS})
    for name in sorted(pops):
        if pops[name].size == 0:
            print(f"  WARNING population resolves to nothing: {name}")

    input_contacts = np.bincount(target, weights=contacts, minlength=count)
    out_contacts = np.bincount(source, weights=contacts, minlength=count)
    edge_share = contacts / np.maximum(input_contacts[target], 1.0)
    # flow_next = W @ flow, with W[t, s] the share of t's input that edge s->t carries.
    weights = csr_matrix((edge_share, (target, source)), shape=(count, count))
    bin_of = degree_bins(out_contacts, args.degree_bins)
    rng = np.random.default_rng(args.seed)

    source_mask = np.zeros(count, dtype=bool)
    target_mask = np.zeros(count, dtype=bool)

    pairs: list[tuple[str, str]] = []
    for name in SOURCES:
        for generic in GENERIC_TARGETS:
            pairs.append((name, generic))
    for pair in SPECIFIC:
        if pair not in pairs:
            pairs.append(pair)

    by_source: dict[str, list[str]] = {}
    for s, t in pairs:
        by_source.setdefault(s, []).append(t)

    rows: list[dict[str, Any]] = []
    for source_name, target_names in by_source.items():
        sources = pops[source_name]
        if sources.size == 0:
            continue
        observed = np.zeros(count)
        observed[sources] = 1.0 / sources.size
        null = matched_null(sources, bin_of, args.degree_bins, args.null_draws, rng)
        state = np.concatenate([observed[:, None], null], axis=1)
        print(f"  propagating {source_name} ({sources.size} bodies) "
              f"with {args.null_draws} matched-null draws")
        per_hop: list[np.ndarray] = []
        for _ in range(args.hops):
            state = weights @ state
            per_hop.append(state.copy())

        source_mask[:] = False
        source_mask[sources] = True
        for target_name in target_names:
            targets = pops[target_name]
            if targets.size == 0:
                continue
            target_mask[:] = False
            target_mask[targets] = True
            direct = source_mask[source] & target_mask[target]
            direct_edges = int(direct.sum())
            direct_share = (
                float(contacts[direct].sum() / max(input_contacts[targets].sum(), 1.0))
                if direct_edges
                else 0.0
            )
            hops: list[dict[str, Any]] = []
            for hop, snapshot in enumerate(per_hop, start=1):
                arrived = snapshot[targets].sum(axis=0) / targets.size
                seen, nulls = float(arrived[0]), arrived[1:]
                median = float(np.median(nulls))
                hops.append({
                    "hop": hop,
                    "flow": seen,
                    "null_median": median,
                    "ratio_to_null": (seen / median) if median > 0 else float("inf")
                    if seen > 0 else 0.0,
                    "percentile_in_null": float((nulls < seen).mean() * 100.0),
                })
            best = max(hops, key=lambda h: h["ratio_to_null"] if np.isfinite(
                h["ratio_to_null"]) else -1.0)
            rows.append({
                "source": source_name,
                "target": target_name,
                "source_bodies": int(sources.size),
                "target_bodies": int(targets.size),
                "direct_edges": direct_edges,
                "direct_contact_share": direct_share,
                "hops": hops,
                "best_hop": best["hop"],
                "best_ratio_to_null": best["ratio_to_null"],
                "best_percentile": best["percentile_in_null"],
            })

    rows.sort(key=lambda r: -(r["best_ratio_to_null"] if np.isfinite(r["best_ratio_to_null"])
                              else 1e18))
    header = (
        f"{'source':20s} {'target':20s} {'src':>6s} {'tgt':>5s} {'edges':>7s} "
        f"{'direct':>9s} {'hop':>4s} {'flow':>10s} {'null':>10s} {'x null':>8s} {'pct':>6s}"
    )
    print("\n" + header)
    print("-" * len(header))
    for row in rows:
        best = next(h for h in row["hops"] if h["hop"] == row["best_hop"])
        ratio = row["best_ratio_to_null"]
        print(
            f"{row['source']:20s} {row['target']:20s} {row['source_bodies']:6d} "
            f"{row['target_bodies']:5d} {row['direct_edges']:7d} "
            f"{row['direct_contact_share']:8.3%} {row['best_hop']:4d} "
            f"{best['flow']:10.2e} {best['null_median']:10.2e} "
            f"{ratio:8.1f} {row['best_percentile']:5.1f}%"
        )

    payload = {
        "schema_version": "2.0",
        "supersedes": (
            "schema 1.0 of this artifact, which measured two routes, compared a one-hop "
            "flow against a three-hop flow, and had no null. Its conclusion that feeding "
            "'has no route' was not supported by what it measured."
        ),
        "method": {
            "flow": (
                "One unit of drive spread over the source population, propagated along "
                "edges weighted by each edge's share of the target neuron's total input "
                "contacts."
            ),
            "null": (
                f"{args.null_draws} random source sets per source population, matched in "
                f"size and in out-contact profile across {args.degree_bins} quantile bins, "
                "pushed through the identical propagation."
            ),
            "scoring": (
                "Each route is scored at the hop where it stands highest against its own "
                "null, so a polysynaptic pathway is not penalised for being polysynaptic."
            ),
            "blind_to": "sign, dynamics, delay, and whether the network uses the path at all",
        },
        "graph": {
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "populations": {
            name: {
                "description": ({**SOURCES, **TARGETS})[name][0],
                "bodies": int(bodies.size),
            }
            for name, bodies in sorted(pops.items())
        },
        "routes": rows,
        "claim_boundary": (
            "Structural only. A high ratio against the null says the released wiring "
            "connects these populations far more than a size- and degree-matched random "
            "set would. It does not say the network uses that path, with what sign, or "
            "that any behaviour follows."
        ),
        "seed": args.seed,
        "git": git_metadata(),
    }
    output = args.output or args.root / "evidence/demo02/demo02-route-survey.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nartifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
