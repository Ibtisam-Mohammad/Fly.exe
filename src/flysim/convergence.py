# SPDX-License-Identifier: GPL-2.0-or-later
"""Complete ORN-to-PN convergence as a parameter-free test of the locked connectome.

Kazama and Wilson 2009 established physiologically that every olfactory receptor neuron of a
glomerulus synapses onto every uniglomerular projection neuron of that glomerulus. That is a
complete-bipartite prediction about structure, so it can be checked directly on the connectome
with no biophysical parameter, no fit and no simulation. A shortfall is a statement about edge
recovery or cell typing in MaleCNS, not about any model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.feather as feather

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

RECEPTOR_PREFIX = "ORN_"
PROJECTION_PATTERN = re.compile(r"^([A-Za-z0-9]+)_(?:ad|l|v|il|lv|vl|m)PN$")
TRACED = "Traced"


def load_olfactory_populations(
    annotations_path: Path,
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Traced ORN and uniglomerular PN body IDs, keyed by glomerulus.

    ORN somata sit in the antenna, outside the imaged volume, so every ORN body carries a null
    ``somaSide`` and the populations cannot be split by antenna. The prediction is bilateral in
    any case.
    """
    table = feather.read_table(
        annotations_path, columns=["bodyId", "type", "status"]
    )
    body_ids = table.column("bodyId").to_pylist()
    types = table.column("type").to_pylist()
    statuses = table.column("status").to_pylist()
    receptors: dict[str, list[int]] = {}
    projections: dict[str, list[int]] = {}
    for body, label, status in zip(body_ids, types, statuses, strict=True):
        if status != TRACED or not label:
            continue
        if label.startswith(RECEPTOR_PREFIX):
            receptors.setdefault(label[len(RECEPTOR_PREFIX) :], []).append(int(body))
            continue
        match = PROJECTION_PATTERN.match(label)
        if match is not None:
            projections.setdefault(match.group(1), []).append(int(body))
    return (
        {key: sorted(value) for key, value in receptors.items()},
        {key: sorted(value) for key, value in projections.items()},
    )


def _dense_indices(graph: SparseConnectome, bodies: list[int]) -> np.ndarray:
    """Dense indices of ``bodies`` present in the graph, in body order.

    ``body_ids`` is validated strictly increasing, so a search side lookup is exact. Bodies the
    graph does not carry are dropped and counted by the caller.
    """
    wanted = np.asarray(bodies, dtype=np.uint64)
    positions = np.searchsorted(graph.body_ids, wanted)
    positions = np.clip(positions, 0, graph.body_ids.size - 1)
    found = graph.body_ids[positions] == wanted
    return np.asarray(positions[found], dtype=np.int64)


def _pair_completeness(
    graph: SparseConnectome,
    source_indices: np.ndarray,
    target_indices: np.ndarray,
) -> tuple[int, np.ndarray]:
    """Realised ordered source-to-target pairs and the contact count of each.

    Every edge whose source is in ``source_indices`` and target in ``target_indices`` counts,
    with no contact threshold, which is the weakest reading of the prediction and therefore the
    one most favourable to it.
    """
    if source_indices.size == 0 or target_indices.size == 0:
        return 0, np.empty(0, dtype=np.uint32)
    source_member = np.zeros(graph.neuron_count, dtype=bool)
    target_member = np.zeros(graph.neuron_count, dtype=bool)
    source_member[source_indices] = True
    target_member[target_indices] = True
    selected = source_member[graph.source_indices] & target_member[graph.target_indices]
    contacts = graph.contact_counts[selected]
    # The aggregate graph carries at most one edge per ordered body pair, so the selected count
    # is already the number of realised pairs. Assert it rather than assume it.
    pairs = np.stack(
        (graph.source_indices[selected], graph.target_indices[selected]), axis=1
    )
    unique_pairs = np.unique(pairs, axis=0).shape[0] if pairs.size else 0
    if unique_pairs != int(selected.sum()):
        raise DatasetError(
            "The aggregate graph carries duplicate edges for an ordered body pair, so the "
            "convergence denominator would be wrong"
        )
    return unique_pairs, contacts


def run_orn_pn_convergence(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Measure convergence completeness per glomerulus and score the contract."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The ORN-to-PN convergence test")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported convergence contract schema")
    parse_provenance(str(contract["provenance"]))
    hypotheses = {str(item["id"]): item for item in contract["hypotheses"]}

    male_cns = root / "raw" / "male-cns-v1.0"
    annotations = male_cns / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    if not annotations.is_file():
        raise DatasetError(f"Annotation artifact is required: {annotations}")
    receptors, projections = load_olfactory_populations(annotations)
    graph = SparseConnectome.load(graph_path)
    graph.validate()

    glomeruli = sorted(set(receptors) & set(projections))
    sizes = contract["sizes_observed_before_registration"]
    registered = int(sizes["glomeruli_with_both_populations"])
    if len(glomeruli) != registered:
        raise DatasetError(
            f"Glomerulus count changed since registration: {len(glomeruli)} against {registered}"
        )

    by_glomerulus: list[dict[str, Any]] = []
    for glomerulus in glomeruli:
        receptor_bodies = receptors[glomerulus]
        projection_bodies = projections[glomerulus]
        receptor_indices = _dense_indices(graph, receptor_bodies)
        projection_indices = _dense_indices(graph, projection_bodies)
        possible = int(receptor_indices.size) * int(projection_indices.size)
        realised, contacts = _pair_completeness(graph, receptor_indices, projection_indices)
        reverse, reverse_contacts = _pair_completeness(
            graph, projection_indices, receptor_indices
        )
        completeness = float(realised / possible) if possible else float("nan")
        # A PN that no ORN of its own glomerulus reaches is the signature of a typing error
        # rather than of missing synapses, so it is counted separately.
        orphan_projections = 0
        if realised and projection_indices.size:
            reached = np.zeros(graph.neuron_count, dtype=bool)
            source_member = np.zeros(graph.neuron_count, dtype=bool)
            source_member[receptor_indices] = True
            target_member = np.zeros(graph.neuron_count, dtype=bool)
            target_member[projection_indices] = True
            selected = source_member[graph.source_indices] & target_member[graph.target_indices]
            reached[graph.target_indices[selected]] = True
            orphan_projections = int(np.count_nonzero(~reached[projection_indices]))
        elif projection_indices.size:
            orphan_projections = int(projection_indices.size)
        by_glomerulus.append(
            {
                "glomerulus": glomerulus,
                "receptor_bodies_annotated": len(receptor_bodies),
                "receptor_bodies_in_graph": int(receptor_indices.size),
                "projection_bodies_annotated": len(projection_bodies),
                "projection_bodies_in_graph": int(projection_indices.size),
                "possible_pairs": possible,
                "realised_pairs": realised,
                "completeness": completeness,
                "projection_neurons_reached_by_no_cognate_receptor": orphan_projections,
                "median_contacts_per_realised_pair": (
                    float(np.median(contacts)) if contacts.size else None
                ),
                "total_contacts": int(contacts.sum()) if contacts.size else 0,
                "reverse_pairs_pn_to_orn": reverse,
                "reverse_total_contacts": (
                    int(reverse_contacts.sum()) if reverse_contacts.size else 0
                ),
            }
        )

    values = np.asarray([item["completeness"] for item in by_glomerulus], dtype=np.float64)
    finite = values[np.isfinite(values)]
    all_contacts = np.concatenate(
        [
            np.full(item["realised_pairs"], item["median_contacts_per_realised_pair"])
            for item in by_glomerulus
            if item["realised_pairs"] and item["median_contacts_per_realised_pair"] is not None
        ]
        or [np.empty(0)]
    )
    minimum = float(finite.min()) if finite.size else float("nan")
    median = float(np.median(finite)) if finite.size else float("nan")
    h2_floor = float(hypotheses["H2"]["expect_at_least"])
    dm4 = next((item for item in by_glomerulus if item["glomerulus"] == "DM4"), None)

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": str(contract["experiment_id"]),
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "evidence_grade": not worktree["dirty"],
        "provenance": str(contract["provenance"]),
        "assumption_ids": list(contract["assumption_ids"]),
        "graph_source_sha256": graph.source_sha256,
        "annotation_sha256": sha256_file(annotations),
        "glomeruli_tested": len(by_glomerulus),
        "totals": {
            "possible_pairs": int(sum(item["possible_pairs"] for item in by_glomerulus)),
            "realised_pairs": int(sum(item["realised_pairs"] for item in by_glomerulus)),
            "pooled_completeness": float(
                sum(item["realised_pairs"] for item in by_glomerulus)
                / sum(item["possible_pairs"] for item in by_glomerulus)
            ),
            "receptor_bodies_in_graph": int(
                sum(item["receptor_bodies_in_graph"] for item in by_glomerulus)
            ),
            "projection_bodies_in_graph": int(
                sum(item["projection_bodies_in_graph"] for item in by_glomerulus)
            ),
            "projection_neurons_reached_by_no_cognate_receptor": int(
                sum(
                    item["projection_neurons_reached_by_no_cognate_receptor"]
                    for item in by_glomerulus
                )
            ),
            "reverse_pairs_pn_to_orn": int(
                sum(item["reverse_pairs_pn_to_orn"] for item in by_glomerulus)
            ),
        },
        "completeness_distribution": {
            "minimum": minimum,
            "median": median,
            "maximum": float(finite.max()) if finite.size else float("nan"),
            "glomeruli_at_1_0": int(np.count_nonzero(finite >= 1.0)),
            "glomeruli_below_h2_floor": int(np.count_nonzero(finite < h2_floor)),
        },
        "hypotheses": {
            "H1": {
                "statement": hypotheses["H1"]["statement"],
                "minimum_completeness": minimum,
                "criterion": "minimum across glomeruli == 1.0",
                "passed": bool(finite.size and minimum >= 1.0),
            },
            "H2": {
                "statement": hypotheses["H2"]["statement"],
                "derivation": hypotheses["H2"]["derivation"],
                "median_completeness": median,
                "criterion": f">= {h2_floor}",
                "passed": bool(finite.size and median >= h2_floor),
                "interpretation_if_failed": hypotheses["H2"]["interpretation_if_failed"],
            },
        },
        "hypotheses_descriptive": {
            "H3": {
                "statement": hypotheses["H3"]["statement"],
                "disclosure": hypotheses["H3"]["disclosure"],
                "malecns_dm4_receptor_bodies": (
                    dm4["receptor_bodies_annotated"] if dm4 is not None else None
                ),
                "kw2009_per_antenna": 17.4,
                "kw2009_bilateral_expected": 34.8,
            },
            "H4": {"statement": hypotheses["H4"]["statement"], "table": "by_glomerulus"},
            "H5": {
                "statement": hypotheses["H5"]["statement"],
                "assumption": hypotheses["H5"]["assumption"],
                "median_of_per_glomerulus_medians": (
                    float(np.median(all_contacts)) if all_contacts.size else None
                ),
                "kw2008_release_sites_mpfa": [51.4, 7.8],
                "rozenfeld2023_release_sites_range": [10, 30],
            },
        },
        "by_glomerulus": by_glomerulus,
        "claim_boundary": str(contract["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output_path, result)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **result,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot),
    }
