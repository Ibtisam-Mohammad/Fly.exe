#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure candidate routes for grooming, feeding and escape before building any of them.

    PYTHONPATH=src python scripts/measure_demo02_routes.py --root /srv/flybrain-data

DEMO-01 chose its route by measurement rather than by preference, and the olfactory route it
started with was abandoned because the measurement said it could not work: no direct edges, a
three-synapse path, and a signed contact-share flow of 6.6e-05 arriving at cells that
integrate hundreds of inputs. That number is the yardstick here, and so is the visual route
that replaced it.

This script applies the same method to the three behaviours a demonstration might add. It
simulates nothing, fits nothing and decides nothing. It writes a JSON artifact of structural
quantities so the decision about what to build is made against numbers that existed first.

Flow is contact share: one unit of drive spread over the source population, propagated along
edges weighted by each edge's share of the target neuron's total input contacts. It is a
structural upper bound on influence and is blind to sign, dynamics and delay.
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

# Wing steering muscle motor neurons carry a trailing " MN" in the released type strings.
WING_STEERING = frozenset(
    f"{name} MN"
    for name in ("b1", "b2", "b3", "i1", "i2", "iii1", "iii3", "hg1", "hg2", "hg3", "ps1",
                 "tp1", "tp2")
)

Predicate = Callable[[str, str, str], bool]

POPULATIONS: dict[str, tuple[str, Predicate]] = {
    # The two reference points. Everything else is only meaningful against these.
    "lamina-L1L2L5": (
        "DEMO-01's validated entry: lamina monopolar cells L1, L2 and L5",
        lambda ty, cl, sc: ty in ("L1", "L2", "L5"),
    ),
    "DNp-all": (
        "DEMO-01's validated readout: the posterior descending group",
        lambda ty, cl, sc: ty.startswith("DNp"),
    ),
    # Escape.
    "LC4": ("Lobula columnar type 4, a looming detector",
            lambda ty, cl, sc: ty == "LC4"),
    "LPLC2": ("Lobula plate/lobula columnar type 2, a looming detector",
              lambda ty, cl, sc: ty == "LPLC2"),
    "DNp01-giant-fibre": ("The giant fibre, the escape command neuron",
                          lambda ty, cl, sc: ty == "DNp01"),
    "TTMn": ("Tergotrochanteral motor neuron, the jump muscle",
             lambda ty, cl, sc: ty.startswith("TTM")),
    "PSI": ("Peripherally synapsing interneuron",
            lambda ty, cl, sc: ty.startswith("PSI")),
    "wing-power-MN": ("Dorsal longitudinal and dorsoventral power muscle motor neurons",
                      lambda ty, cl, sc: ty.startswith("DLMn") or ty.startswith("DVMn")),
    "wing-steering-MN": ("The thirteen wing steering muscle motor neurons",
                         lambda ty, cl, sc: ty in WING_STEERING),
    # Grooming.
    "JO-F": ("Johnston's organ F subtypes, the Track A grooming input",
             lambda ty, cl, sc: ty in ("JO-FV", "JO-FD1", "JO-FD2")),
    "BM_InOm": ("Head bristle mechanosensory neurons, inner ommatidial row",
                lambda ty, cl, sc: ty == "BM_InOm"),
    "DNg12": ("DNg12 subtypes, associated with grooming",
              lambda ty, cl, sc: ty.startswith("DNg12")),
    "groom-DN-track-a": ("The grooming descending readout Track A declared",
                         lambda ty, cl, sc: ty in ("DNg62", "DNge078", "DNg21")),
    # Feeding.
    "gustatory": ("Every neuron the release labels class gustatory",
                  lambda ty, cl, sc: cl == "gustatory"),
    "MN9": ("MN9, the pharyngeal pump motor neuron",
            lambda ty, cl, sc: ty == "MN9"),
    "proboscis-MN": ("Proboscis motor neurons MN10, MN11 and MN12",
                     lambda ty, cl, sc: ty in ("MN10", "MN11D", "MN11V", "MN12D")),
}

ROUTES: tuple[tuple[str, str, str, str], ...] = (
    ("reference", "lamina-L1L2L5", "DNp-all",
     "DEMO-01's own route, end to end, for scale"),
    ("reference", "LC4", "DNp-all",
     "DEMO-01's one-hop route to the whole descending group"),
    ("escape", "LC4", "DNp01-giant-fibre", "looming detector to the escape command neuron"),
    ("escape", "LPLC2", "DNp01-giant-fibre", "the second looming detector to the same cell"),
    ("escape", "DNp01-giant-fibre", "TTMn", "command neuron to the jump muscle"),
    ("escape", "DNp01-giant-fibre", "PSI", "command neuron to the wing depressor interneuron"),
    ("escape", "PSI", "wing-power-MN", "interneuron to the wing power muscles"),
    ("escape", "DNp01-giant-fibre", "wing-power-MN",
     "command neuron directly to wing power, which a fly does not do"),
    ("grooming", "JO-F", "groom-DN-track-a", "Track A's declared grooming route"),
    ("grooming", "JO-F", "DNg12", "Johnston's organ to DNg12"),
    ("grooming", "BM_InOm", "groom-DN-track-a", "head bristles to the same readout"),
    ("grooming", "BM_InOm", "DNg12", "head bristles to DNg12"),
    ("feeding", "gustatory", "MN9", "taste to the pharyngeal pump"),
    ("feeding", "gustatory", "proboscis-MN", "taste to proboscis extension"),
)


def resolve(annotations_path: Path, graph: SparseConnectome) -> dict[str, np.ndarray]:
    import pyarrow.feather as feather

    table = feather.read_table(annotations_path)
    needed = ("bodyId", "type", "class", "superclass")
    missing = [name for name in needed if name not in table.column_names]
    if missing:
        raise SystemExit(f"Annotation table lacks columns {missing}")
    columns = {name: table.column(name).to_pylist() for name in needed}
    dense_by_body = {int(body): graph.dense_index(int(body)) for body in graph.body_ids}

    resolved: dict[str, np.ndarray] = {}
    for name, (_, predicate) in POPULATIONS.items():
        found: set[int] = set()
        for row, body in enumerate(columns["bodyId"]):
            dense = dense_by_body.get(int(body))
            if dense is None:
                continue
            if predicate(
                str(columns["type"][row] or ""),
                str(columns["class"][row] or ""),
                str(columns["superclass"][row] or ""),
            ):
                found.add(dense)
        resolved[name] = np.array(sorted(found), dtype=np.int64)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--hops", type=int, default=3)
    args = parser.parse_args()

    graph = SparseConnectome.load(args.root / "derived/male-cns-v1.0/graph")
    graph.validate()
    source = np.asarray(graph.source_indices)
    target = np.asarray(graph.target_indices)
    contacts = np.asarray(graph.contact_counts).astype(np.float64)
    count = graph.neuron_count

    populations = resolve(
        args.root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather",
        graph,
    )
    empty = [name for name, bodies in populations.items() if bodies.size == 0]
    if empty:
        print(f"populations with no body in the graph: {empty}")

    input_contacts = np.bincount(target, weights=contacts, minlength=count)
    edge_share = contacts / np.maximum(input_contacts[target], 1.0)

    def flow(sources: np.ndarray, targets: np.ndarray) -> list[float]:
        state = np.zeros(count, dtype=np.float64)
        state[sources] = 1.0 / max(sources.size, 1)
        out: list[float] = []
        for _ in range(args.hops):
            state = np.bincount(
                target, weights=state[source] * edge_share, minlength=count
            )
            out.append(float(state[targets].sum() / max(targets.size, 1)))
        return out

    def direct(sources: np.ndarray, targets: np.ndarray) -> tuple[int, float]:
        mask = np.isin(source, sources) & np.isin(target, targets)
        if not np.any(mask):
            return 0, 0.0
        return int(mask.sum()), float(
            contacts[mask].sum() / max(input_contacts[targets].sum(), 1.0)
        )

    rows: list[dict[str, Any]] = []
    header = (
        f"{'behaviour':10s} {'route':40s} {'src':>6s} {'tgt':>5s} {'edges':>7s} "
        f"{'direct share':>13s} {'hop1':>10s} {'hop2':>10s} {'hop3':>10s}"
    )
    print(header)
    print("-" * len(header))
    for behaviour, a, b, why in ROUTES:
        sources, targets = populations[a], populations[b]
        edges, share = direct(sources, targets)
        hops = flow(sources, targets)
        rows.append({
            "behaviour": behaviour,
            "source": a,
            "target": b,
            "why": why,
            "source_bodies": int(sources.size),
            "target_bodies": int(targets.size),
            "direct_edges": edges,
            "direct_contact_share": share,
            "flow_by_hop": hops,
        })
        print(
            f"{behaviour:10s} {a + ' -> ' + b:40s} {sources.size:6d} {targets.size:5d} "
            f"{edges:7d} {share:12.4%} " + " ".join(f"{h:10.2e}" for h in hops)
        )

    payload = {
        "schema_version": "1.0",
        "what_this_is": (
            "A structural survey of candidate routes, run before anything was built. It "
            "simulates nothing and fits nothing."
        ),
        "method": (
            "Contact-share flow: one unit of drive spread over the source population, "
            "propagated along edges weighted by each edge's share of the target neuron's "
            "total input contacts. A structural upper bound on influence, blind to sign, "
            "dynamics and delay."
        ),
        "yardsticks": {
            "olfactory_route_that_failed": 6.6e-05,
            "note": (
                "DEMO-01's olfactory route was abandoned on a measured flow of 6.6e-05 "
                "with no direct edges. The visual route that replaced it reached its "
                "target in one synapse. Both are in this table for scale."
            ),
        },
        "graph": {
            "path": str(args.root / "derived/male-cns-v1.0/graph"),
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
        },
        "populations": {
            name: {
                "description": POPULATIONS[name][0],
                "bodies": int(bodies.size),
            }
            for name, bodies in populations.items()
        },
        "routes": rows,
        "claim_boundary": (
            "Structural only. A strong route here is a necessary condition for a "
            "demonstration and not a sufficient one: it says a path exists and carries a "
            "large share of its target's input, not that the network uses it, nor with "
            "what sign, nor that any behaviour follows."
        ),
        "git": git_metadata(),
    }
    output = args.output or args.root / "evidence/demo02/demo02-route-survey.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nartifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
