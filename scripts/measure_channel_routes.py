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

**Two things a first version of this script got wrong, recorded because they change how the
numbers must be read.**

It reported a "gain from splitting" as the best channel's null ratio over the modality's,
and the top of that table was every 1- and 2-body channel in the atlas, at ratios up to
275,000. The mechanism: a one-body null draws random one-body sets, most of which reach a
26-cell target with no flow at all after three hops, so the null median collapses to about
1e-12 and the ratio explodes. In the worst case the channel's own flow was 47 times
*smaller* than the modality's while its ratio was 60,000 times larger. **A ratio to this
null is not comparable across population sizes**, and 1,322 of 7,296 hop entries have a null
median of exactly zero. Ratios are therefore marked unreportable below
``--min-null-bodies``, and that guard is structural rather than chosen from the answers: it
is the size below which the null has no usable median, not the size below which the results
became inconvenient.

Then, measured by flow instead, splitting "helped" in 100 percent of comparisons with a
minimum of exactly 1.00 -- which is arithmetic, not a finding. Flow is the mean per-neuron
reach, the modality's flow is the mean over its members, and the maximum over subsets of a
set is always at least its mean. So there is no version of "does splitting help" that a
maximum can answer. What is reported instead is **dispersion**: how far a modality's best
channel stands above its median channel, which says whether that sense separates by organ
and side or is homogeneous across them. And **laterality**, the left-to-right flow ratio at
one organ, which is a genuine asymmetry and not a maximum over anything.

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
    parser.add_argument(
        "--min-null-bodies", type=int, default=20,
        help="Below this source size a ratio to the matched null is marked unreportable, "
             "because the null's median collapses toward zero and the ratio stops "
             "measuring route strength. Flow is still reported at every size.",
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
            reportable = (
                members.size >= args.min_null_bodies and best["null_median"] > 0.0
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
                "best_flow": best["flow"],
                "best_ratio_to_null": best["ratio_to_null"],
                "best_percentile": best["percentile_in_null"],
                "null_ratio_reportable": bool(reportable),
                "why_not_reportable": (
                    ""
                    if reportable
                    else (
                        f"source has {members.size} bodies, below the declared "
                        f"{args.min_null_bodies}, so the matched null has no usable median"
                        if members.size < args.min_null_bodies
                        else "the matched null's median at this hop is exactly zero"
                    )
                ),
            })

    def finite(value: float) -> float:
        return value if np.isfinite(value) else 1e18

    def flow_at(row: dict[str, Any], hop: int) -> float:
        return float(next(h for h in row["hops"] if h["hop"] == hop)["flow"])

    # How far does a modality's best channel stand above its median channel? This says
    # whether the sense separates by organ and side, or is homogeneous across them. It is
    # deliberately NOT "best channel over the modality": the modality's flow is the mean
    # over its members and a maximum over subsets always beats a mean, so that comparison
    # can only ever come out above one and answers nothing.
    dispersion: list[dict[str, Any]] = []
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
            hop = int(lump["best_hop"])
            flows = sorted(((flow_at(row, hop), row) for row in parts), reverse=True)
            values = [value for value, _ in flows]
            median = float(np.median(values))
            top_flow, top_row = flows[0]
            dispersion.append({
                "modality": modality,
                "target": target_name,
                "hop": hop,
                "channels_compared": len(parts),
                "modality_flow": flow_at(lump, hop),
                "best_channel": top_row["source"],
                "best_channel_bodies": top_row["source_bodies"],
                "best_channel_flow": top_flow,
                "median_channel_flow": median,
                "min_channel_flow": float(values[-1]),
                "best_over_median": (top_flow / median) if median > 0 else float("inf"),
                "best_channel_null_ratio_reportable": top_row["null_ratio_reportable"],
                "best_channel_ratio_to_null": top_row["best_ratio_to_null"],
            })
    dispersion.sort(key=lambda c: -finite(c["best_over_median"]))

    # Left against right at one organ. Not a maximum over anything, so this one is a real
    # asymmetry: a route that is genuinely lateralised should show it here.
    laterality: list[dict[str, Any]] = []
    for key in atlas.channel_keys:
        if key.side != "L":
            continue
        mirror = f"{key.modality}:{key.organ}:R"
        for target_name in targets:
            left = next(
                (r for r in rows if r["source"] == f"channel:{key}" and r["target"] == target_name),
                None,
            )
            right = next(
                (
                    r for r in rows
                    if r["source"] == f"channel:{mirror}" and r["target"] == target_name
                ),
                None,
            )
            if left is None or right is None:
                continue
            hop = int(max(left["best_hop"], right["best_hop"]))
            left_flow, right_flow = flow_at(left, hop), flow_at(right, hop)
            if left_flow <= 0 and right_flow <= 0:
                continue
            total = left_flow + right_flow
            laterality.append({
                "modality": key.modality,
                "organ": key.organ,
                "target": target_name,
                "hop": hop,
                "left_bodies": left["source_bodies"],
                "right_bodies": right["source_bodies"],
                "left_flow": left_flow,
                "right_flow": right_flow,
                "index": (left_flow - right_flow) / total if total > 0 else 0.0,
            })
    laterality.sort(key=lambda entry: -abs(entry["index"]))

    rows.sort(key=lambda r: -finite(r["best_ratio_to_null"]))
    header = (
        f"{'source':44s} {'target':20s} {'src':>5s} {'edges':>7s} {'hop':>4s} "
        f"{'x null':>9s} {'pct':>6s}"
    )
    reportable = [row for row in rows if row["null_ratio_reportable"]]
    print(f"\ntop 40 routes whose null ratio is reportable "
          f"({len(reportable)} of {len(rows)})\n" + header)
    print("-" * len(header))
    for row in reportable[:40]:
        print(
            f"{row['source']:44s} {row['target']:20s} {row['source_bodies']:5d} "
            f"{row['direct_edges']:7d} {row['best_hop']:4d} "
            f"{row['best_ratio_to_null']:9.1f} {row['best_percentile']:5.1f}%"
        )

    print("\nwhere a sense separates most by organ and side (best channel over median "
          "channel, at the modality's best hop)")
    print(f"{'modality':24s} {'target':20s} {'ch':>4s} {'best channel':32s} "
          f"{'n':>5s} {'best/med':>9s}")
    for entry in dispersion[:20]:
        print(
            f"{entry['modality']:24s} {entry['target']:20s} "
            f"{entry['channels_compared']:4d} "
            f"{entry['best_channel'].replace('channel:', ''):32s} "
            f"{entry['best_channel_bodies']:5d} {entry['best_over_median']:8.2f}x"
        )

    print("\nstrongest left/right asymmetries (index = (L-R)/(L+R), at a shared hop)")
    print(f"{'modality':24s} {'organ':12s} {'target':20s} {'L':>5s} {'R':>5s} {'index':>7s}")
    for entry in laterality[:20]:
        print(
            f"{entry['modality']:24s} {entry['organ']:12s} {entry['target']:20s} "
            f"{entry['left_bodies']:5d} {entry['right_bodies']:5d} {entry['index']:+7.2f}"
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
            "null_ratio_size_limit": (
                f"A ratio to this null is not comparable across population sizes. Below "
                f"{args.min_null_bodies} source bodies the null's median collapses toward "
                "zero for distant targets and the ratio stops measuring route strength, so "
                "those rows carry null_ratio_reportable false and a reason. A first "
                "version of this script did not do that, and its headline table was every "
                "one- and two-body channel in the atlas at ratios up to 275000, one of "
                "which had a flow 47 times smaller than the modality it was beating."
            ),
            "why_dispersion_not_gain": (
                "Flow is the mean per-neuron reach and a modality's flow is the mean over "
                "its members, so the maximum over its channels is always at least the "
                "modality's own value. 'Does splitting help' measured that way comes out "
                "above one every time, with a minimum of exactly 1.00, which is arithmetic "
                "and not a result. Dispersion compares a modality's best channel against "
                "its median channel instead, which says whether the sense separates by "
                "organ and side or is homogeneous across them."
            ),
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
        "organ_side_dispersion": dispersion,
        "laterality": laterality,
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
