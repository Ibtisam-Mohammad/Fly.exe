#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Which labelled senses can actually drive anything, before any of them is wired up.

    PYTHONPATH=src python scripts/measure_sensory_live_edges.py --root /srv/flybrain-data

A sensory population can be perfectly well annotated, sit in the executed graph, receive
injected drive, produce a spike raster that renders beautifully in a video -- and change
nothing downstream, because every one of its outgoing edges carries a zero sign.

This is not hypothetical. It is already true of the photoreceptors. Fly photoreceptors are
histaminergic, histamine is absent from the transmitter model, so the frozen sign policy
resolves their sign to zero and all 66,533 of their output edges are dead. DEMO-01 knows
this and enters vision one synapse downstream, at the lamina monopolar cells. Nothing had
ever checked whether the same is true of the other fifteen thousand afferents.

So this runs before anything is built, and it reports, per channel of
:mod:`flysim.sensory_atlas`: how many bodies carry a live sign, and how many outgoing edges
and contacts survive the policy.

**The gate is a bright line, not a tuned threshold.** A channel with zero live outgoing
edges may not be enabled, because injecting into it is theatre. There is deliberately no
percentage cut-off: the live fraction varies from 0% to 100% across the labelled senses and
any threshold in between would be a number chosen after seeing the data. Instead every
channel's live fraction is recorded, and a channel below ``--report-below`` is flagged as
partially muted so that the fraction travels with any claim built on it rather than being
discovered later.

Structural, and downstream of one frozen choice: the unresolved-sign policy. Under the
``zero`` policy a neuron whose consensus transmitter is unclear is silent rather than
guessed. That is the conservative reading and it is the one DEMO-01 runs under.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.connectome import SparseConnectome  # noqa: E402
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs  # noqa: E402
from flysim.runs import git_metadata  # noqa: E402
from flysim.sensory_atlas import SensoryAtlas  # noqa: E402


def measure(
    bodies: tuple[int, ...],
    dense_of: dict[int, int],
    neuron_signs: np.ndarray,
    live_edges: np.ndarray,
    live_contacts: np.ndarray,
    total_edges: np.ndarray,
) -> dict[str, Any]:
    if not bodies:
        return {
            "bodies": 0, "live_bodies": 0, "live_body_fraction": 0.0,
            "live_out_edges": 0, "live_out_contacts": 0.0, "dead_out_edges": 0,
            "drivable": False,
        }
    rows = np.array([dense_of[body] for body in bodies], dtype=np.int64)
    alive = neuron_signs[rows] != 0
    edges = int(live_edges[rows].sum())
    return {
        "bodies": int(rows.size),
        "live_bodies": int(alive.sum()),
        "live_body_fraction": float(alive.mean()),
        "live_out_edges": edges,
        "live_out_contacts": float(live_contacts[rows].sum()),
        "dead_out_edges": int(total_edges[rows].sum()) - edges,
        "drivable": edges > 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument(
        "--unresolved-sign-policy", default="zero",
        help="Must match the policy the run will use, or this measures a different graph.",
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--report-below", type=float, default=0.90,
        help="Channels below this live fraction are flagged as partially muted. This "
             "flags, it never excludes; the only exclusion is zero live edges.",
    )
    args = parser.parse_args()

    graph = SparseConnectome.load(args.root / "derived/male-cns-v1.0/graph")
    graph.validate()
    annotations = (
        args.root / "raw/male-cns-v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    transmitters = args.root / "raw/male-cns-v1.0/body-neurotransmitters-male-cns-v1.0.feather"

    policy = UnresolvedSignPolicy(args.unresolved_sign_policy)
    signs = build_shiu_regression_signs(
        graph, transmitters, unresolved_policy=policy, seed=args.seed
    )
    neuron_signs = np.asarray(signs.neuron_signs)
    edge_signs = np.asarray(signs.edge_signs)
    source = np.asarray(graph.source_indices)
    contacts = np.asarray(graph.contact_counts, dtype=np.float64)
    live = edge_signs != 0
    live_edges = np.bincount(source[live], minlength=graph.neuron_count)
    live_contacts = np.bincount(
        source[live], weights=contacts[live], minlength=graph.neuron_count
    )
    total_edges = np.bincount(source, minlength=graph.neuron_count)

    print(
        f"graph: {graph.neuron_count:,} neurons, {graph.edge_count:,} edges; "
        f"{int((neuron_signs != 0).sum()):,} neurons carry a live sign under policy "
        f"{policy.value!r}"
    )

    atlas = SensoryAtlas.resolve(annotations, graph, registry_path=args.registry)
    dense_of = {int(body): graph.dense_index(int(body)) for body in graph.body_ids}

    modalities: dict[str, Any] = {}
    for name in sorted(atlas.modality_bodies):
        row = measure(
            atlas.modality_bodies[name], dense_of, neuron_signs,
            live_edges, live_contacts, total_edges,
        )
        row["kind"] = atlas.modality_kind[name]
        row["partially_muted"] = (
            row["drivable"] and row["live_body_fraction"] < args.report_below
        )
        modalities[name] = row

    surrogates = {
        name: measure(bodies, dense_of, neuron_signs, live_edges, live_contacts, total_edges)
        for name, bodies in sorted(atlas.surrogates.items())
    }
    channels = {
        name: measure(ids, dense_of, neuron_signs, live_edges, live_contacts, total_edges)
        for name, ids in sorted(atlas.channels.items())
    }

    header = (
        f"{'modality':26s}{'kind':10s}{'n':>6s}{'live':>7s}{'live%':>8s}"
        f"{'liveEdges':>11s}{'liveContacts':>14s}  flag"
    )
    print("\n" + header)
    print("-" * len(header))
    ordered = sorted(modalities.items(), key=lambda kv: kv[1]["live_body_fraction"])
    for name, row in ordered:
        flag = ""
        if not row["bodies"]:
            flag = "empty, claimed by an earlier rung"
        elif not row["drivable"]:
            flag = "NOT DRIVABLE"
        elif row["partially_muted"]:
            flag = "partially muted"
        print(
            f"{name:26s}{row['kind']:10s}{row['bodies']:6d}{row['live_bodies']:7d}"
            f"{row['live_body_fraction']:7.1%}{row['live_out_edges']:11d}"
            f"{row['live_out_contacts']:14.0f}  {flag}"
        )
    for name, row in surrogates.items():
        print(
            f"{name:26s}{'surrogate':10s}{row['bodies']:6d}{row['live_bodies']:7d}"
            f"{row['live_body_fraction']:7.1%}{row['live_out_edges']:11d}"
            f"{row['live_out_contacts']:14.0f}"
        )

    not_drivable = sorted(
        name for name, row in modalities.items() if row["bodies"] and not row["drivable"]
    )
    muted = sorted(name for name, row in modalities.items() if row["partially_muted"])
    print(f"\nnot drivable: {not_drivable or 'none'}")
    print(f"partially muted below {args.report_below:.0%}: {muted or 'none'}")

    payload = {
        "schema_version": "1.0",
        "what_this_measures": (
            "Per labelled sensory channel: how many bodies carry a live presynaptic sign "
            "under the frozen unresolved-sign policy, and how many outgoing edges and "
            "contacts survive it. A channel with zero live outgoing edges cannot change "
            "anything downstream, however convincing its spike raster looks."
        ),
        "why_it_exists": (
            "The photoreceptors are already this case: histaminergic, histamine absent "
            "from the transmitter model, all 66533 output edges zeroed. Nothing had "
            "checked whether the other labelled senses share that fate before this."
        ),
        "gate": {
            "rule": "A channel with zero live outgoing edges may not be enabled.",
            "why_no_percentage_threshold": (
                "The live fraction runs from 0 to 1 across the labelled senses, so any "
                "cut-off in between would be a number chosen after seeing the data. The "
                "bright line is the one that needs no choosing."
            ),
            "report_below": args.report_below,
            "reporting_is_not_exclusion": (
                "A partially muted channel is still drivable. The flag exists so the "
                "fraction travels with any claim built on that channel."
            ),
        },
        "unresolved_sign_policy": policy.value,
        "seed": args.seed,
        "graph": {
            "source_sha256": graph.source_sha256,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
            "neurons_with_live_sign": int((neuron_signs != 0).sum()),
            "live_edges": int(live.sum()),
        },
        "atlas": atlas.as_dict(),
        "modalities": modalities,
        "channels": channels,
        "surrogates": surrogates,
        "not_drivable": not_drivable,
        "partially_muted": muted,
        "claim_boundary": (
            "Structural only. A live edge is an edge the runtime will execute with a "
            "nonzero sign. It is not evidence that the population responds to anything, "
            "that the sign is correct, or that any behaviour follows."
        ),
        "git": git_metadata(),
    }
    output = args.output or args.root / "evidence/demo02/sensory-live-edges.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nartifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
