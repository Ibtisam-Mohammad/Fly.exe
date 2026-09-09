# SPDX-License-Identifier: GPL-2.0-or-later
"""Ipsilateral against contralateral ORN input onto a shared projection neuron.

Kazama and Wilson 2008 found that ipsilateral and contralateral ORN projections produce
uEPSCs of equal amplitude, at p > 0.54. Because they also found release probability and
quantal size constant across glomeruli, equal amplitude implies an equal number of
contacts per connection from each antenna onto the same PN.

That makes a parameter-free structural test, and a better-conditioned one than any
previous contact-based test here: it is paired within a PN, so the glomerulus-to-glomerulus
variation that confounded the volume and homeostatic-matching tests cancels. It is also an
internal consistency check on the connectome, because a fly's two antennae are equivalent
and any asymmetry that is not ipsi-versus-contra has to be reconstruction.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.feather as feather

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.convergence import PROJECTION_PATTERN, RECEPTOR_PREFIX, TRACED, _dense_indices
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

SIDES = ("L", "R")


def load_sided_olfactory_populations(
    annotations_path: Path,
) -> tuple[dict[tuple[str, str], list[int]], dict[tuple[str, str], list[int]]]:
    """ORN and uniglomerular PN body IDs keyed by (glomerulus, side).

    ``somaSide`` is null for every ORN, because ORN somata sit in the antenna outside the
    imaged volume, and ``load_olfactory_populations`` records that as meaning the
    populations cannot be split by antenna. That conclusion is too strong: ``rootSide``
    carries the side for 2,226 of 2,635 ORN bodies, and PN sides are in the ``instance``
    suffix. Only ``somaSide`` is unusable.
    """
    table = feather.read_table(
        annotations_path,
        columns=["bodyId", "type", "status", "rootSide", "instance"],
    )
    body_ids = table.column("bodyId").to_pylist()
    types = table.column("type").to_pylist()
    statuses = table.column("status").to_pylist()
    root_sides = table.column("rootSide").to_pylist()
    instances = table.column("instance").to_pylist()
    receptors: dict[tuple[str, str], list[int]] = {}
    projections: dict[tuple[str, str], list[int]] = {}
    unsided_receptors = 0
    for body, label, status, root_side, instance in zip(
        body_ids, types, statuses, root_sides, instances, strict=True
    ):
        if status != TRACED or not label:
            continue
        if label.startswith(RECEPTOR_PREFIX):
            if root_side not in SIDES:
                unsided_receptors += 1
                continue
            key = (label[len(RECEPTOR_PREFIX) :], str(root_side))
            receptors.setdefault(key, []).append(int(body))
            continue
        match = PROJECTION_PATTERN.match(label)
        if match is None:
            continue
        suffix = (instance or "").rsplit("_", 1)[-1]
        if suffix not in SIDES:
            continue
        projections.setdefault((match.group(1), suffix), []).append(int(body))
    if not receptors or not projections:
        raise DatasetError("No sided olfactory populations were resolved from the annotation")
    return (
        {key: sorted(value) for key, value in receptors.items()},
        {key: sorted(value) for key, value in projections.items()},
    )


def _sign_test(differences: np.ndarray) -> tuple[int, int, float]:
    """Two-sided exact sign test. Returns (positive, negative, p).

    Hand-rolled because scipy is not a declared dependency of this project. Ties are
    discarded, which is the standard convention and is conservative here.
    """
    positive = int(np.count_nonzero(differences > 0.0))
    negative = int(np.count_nonzero(differences < 0.0))
    total = positive + negative
    if total == 0:
        return 0, 0, 1.0
    smaller = min(positive, negative)
    tail = sum(math.comb(total, k) for k in range(smaller + 1)) / (2.0**total)
    return positive, negative, min(1.0, 2.0 * tail)


def _pair_contacts(
    graph: SparseConnectome, source_indices: np.ndarray, target_index: int
) -> np.ndarray:
    """Contact counts of every realised edge from the sources onto one target."""
    if source_indices.size == 0:
        return np.empty(0, dtype=np.int64)
    member = np.zeros(graph.neuron_count, dtype=bool)
    member[source_indices] = True
    selected = member[graph.source_indices] & (graph.target_indices == target_index)
    return np.asarray(graph.contact_counts[selected], dtype=np.int64)


def measure_projection_neuron(
    *,
    graph: SparseConnectome,
    glomerulus: str,
    side: str,
    body_id: int,
    target_index: int,
    receptor_indices: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Ipsilateral and contralateral input onto one projection neuron."""
    other = "R" if side == "L" else "L"
    row: dict[str, Any] = {
        "glomerulus": glomerulus,
        "projection_body_id": body_id,
        "projection_side": side,
    }
    for label, which in (("ipsilateral", side), ("contralateral", other)):
        indices = receptor_indices.get(which, np.empty(0, dtype=np.int64))
        contacts = _pair_contacts(graph, indices, target_index)
        possible = int(indices.size)
        row[f"{label}_receptor_bodies"] = possible
        row[f"{label}_realised_pairs"] = int(contacts.size)
        row[f"{label}_total_contacts"] = int(contacts.sum())
        row[f"{label}_mean_contacts_per_pair"] = (
            float(contacts.mean()) if contacts.size else float("nan")
        )
        row[f"{label}_completeness"] = (contacts.size / possible) if possible else float("nan")
    ipsi = row["ipsilateral_mean_contacts_per_pair"]
    contra = row["contralateral_mean_contacts_per_pair"]
    row["log2_ipsi_over_contra"] = (
        math.log2(ipsi / contra)
        if ipsi > 0.0 and contra > 0.0 and math.isfinite(ipsi) and math.isfinite(contra)
        else float("nan")
    )
    ipsi_completeness = row["ipsilateral_completeness"]
    contra_completeness = row["contralateral_completeness"]
    row["completeness_difference"] = (
        ipsi_completeness - contra_completeness
        if math.isfinite(ipsi_completeness) and math.isfinite(contra_completeness)
        else float("nan")
    )
    return row


def _score(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    hypotheses = {str(item["id"]): item for item in contract["hypotheses"]}
    ratios = np.asarray(
        [row["log2_ipsi_over_contra"] for row in rows], dtype=np.float64
    )
    scored = ratios[np.isfinite(ratios)]
    if scored.size == 0:
        raise DatasetError("No projection neuron carries realised pairs on both sides")
    median_ratio = float(np.median(scored))
    positive, negative, sign_p = _sign_test(scored)
    h1_passed = bool(abs(median_ratio) <= 0.3 and sign_p >= 0.05)

    by_side: dict[str, dict[str, Any]] = {}
    for side in SIDES:
        side_ratios = np.asarray(
            [
                row["log2_ipsi_over_contra"]
                for row in rows
                if row["projection_side"] == side
            ],
            dtype=np.float64,
        )
        side_scored = side_ratios[np.isfinite(side_ratios)]
        side_positive, side_negative, side_p = _sign_test(side_scored)
        by_side[side] = {
            "projection_neurons": int(side_scored.size),
            "median_log2_ipsi_over_contra": (
                float(np.median(side_scored)) if side_scored.size else float("nan")
            ),
            "sign_test_positive": side_positive,
            "sign_test_negative": side_negative,
            "sign_test_p": side_p,
        }
    left_median = by_side["L"]["median_log2_ipsi_over_contra"]
    right_median = by_side["R"]["median_log2_ipsi_over_contra"]
    same_sign = bool(
        math.isfinite(left_median)
        and math.isfinite(right_median)
        and left_median * right_median > 0.0
    )

    differences = np.asarray(
        [row["completeness_difference"] for row in rows], dtype=np.float64
    )
    difference_scored = differences[np.isfinite(differences)]
    median_difference = float(np.median(difference_scored))
    h3_passed = bool(abs(median_difference) <= 0.05)

    return {
        "H1": {
            "statement": hypotheses["H1"]["statement"],
            "blind": True,
            "projection_neurons_scored": int(scored.size),
            "median_log2_ipsi_over_contra": median_ratio,
            "median_ipsi_over_contra_ratio": float(2.0**median_ratio),
            "sign_test_positive": positive,
            "sign_test_negative": negative,
            "sign_test_p": sign_p,
            "passed": h1_passed,
        },
        "H2": {
            "statement": hypotheses["H2"]["statement"],
            "blind": True,
            "by_projection_side": by_side,
            "same_sign_on_both_sides": same_sign,
            "reading": (
                "The asymmetry is an ipsilateral-versus-contralateral effect, so H1's "
                "reading stands as written."
                if same_sign
                else "The effect reverses sign between left-side and right-side projection "
                "neurons, so it is a left-versus-right asymmetry of the reconstruction "
                "rather than an ipsilateral-versus-contralateral property, and H1's "
                "reading is withdrawn in favour of that."
            ),
        },
        "H3": {
            "statement": hypotheses["H3"]["statement"],
            "blind": False,
            "not_blind_disclosure": hypotheses["H3"]["not_blind_disclosure"],
            "median_completeness_difference": median_difference,
            "projection_neurons_scored": int(difference_scored.size),
            "passed": h3_passed,
        },
    }


def run_bilateral_symmetry(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Score the published ipsi/contra equality against the locked connectome."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The bilateral ORN-to-PN symmetry test")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported bilateral-symmetry contract schema")
    parse_provenance(str(contract["provenance"]))

    annotations = (
        root / "raw" / "male-cns-v1.0" / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    if not annotations.is_file():
        raise DatasetError(f"Annotation artifact is required: {annotations}")
    receptors, projections = load_sided_olfactory_populations(annotations)
    graph = SparseConnectome.load(graph_path)
    graph.validate()

    glomeruli = sorted(
        {glomerulus for glomerulus, _ in receptors}
        & {glomerulus for glomerulus, _ in projections}
    )
    rows: list[dict[str, Any]] = []
    for glomerulus in glomeruli:
        receptor_indices = {
            side: _dense_indices(graph, receptors[(glomerulus, side)])
            for side in SIDES
            if (glomerulus, side) in receptors
        }
        if len(receptor_indices) < len(SIDES):
            continue
        for side in SIDES:
            for body_id in projections.get((glomerulus, side), []):
                target = _dense_indices(graph, [body_id])
                if target.size == 0:
                    continue
                rows.append(
                    measure_projection_neuron(
                        graph=graph,
                        glomerulus=glomerulus,
                        side=side,
                        body_id=body_id,
                        target_index=int(target[0]),
                        receptor_indices=receptor_indices,
                    )
                )
    if not rows:
        raise DatasetError("No projection neuron had ORN populations on both sides")

    hypotheses = _score(rows, contract)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-bilateral-symmetry-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "assumption_ids": list(contract["assumption_ids"]),
        "graph_source_sha256": graph.source_sha256,
        "glomeruli_with_both_sides": len(
            {row["glomerulus"] for row in rows}
        ),
        "projection_neurons": len(rows),
        "by_projection_neuron": rows,
        "hypotheses": hypotheses,
        "validation_tier_awarded": None,
        "claim_boundary": str(contract["claim_boundary"]),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "evidence_grade": not worktree["dirty"],
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot),
    }
