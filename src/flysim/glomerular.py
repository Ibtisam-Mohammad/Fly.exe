# SPDX-License-Identifier: GPL-2.0-or-later
"""Glomerular volume from synapse clouds, to test the published release-site scaling.

Kazama and Wilson 2008 measured unitary EPSC amplitude against the glomerular volume occupied
by the PN dendritic tuft. The project's earlier synaptic-structure test substituted converging
ORN count for that volume and found no scaling. This module measures the volume directly, so
the claim can be tested in the form the source paper makes it.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.convergence import _dense_indices, load_olfactory_populations
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

VOXEL_NM = 8.0


def _spearman(first: np.ndarray, second: np.ndarray) -> tuple[float, float]:
    """Rank correlation and a two-sided p-value from the t approximation.

    Implemented here rather than pulled from scipy because the production environment does
    not carry scipy and the statistic is three lines.
    """
    size = first.size
    if size != second.size or size < 3:
        raise ConfigurationError("Spearman needs at least three paired observations")
    ranked_first = _rank(first)
    ranked_second = _rank(second)
    centred_first = ranked_first - ranked_first.mean()
    centred_second = ranked_second - ranked_second.mean()
    denominator = float(np.sqrt((centred_first**2).sum() * (centred_second**2).sum()))
    if denominator == 0.0:
        return float("nan"), float("nan")
    rho = float((centred_first * centred_second).sum() / denominator)
    if abs(rho) >= 1.0:
        return rho, 0.0
    statistic = rho * np.sqrt((size - 2) / (1.0 - rho**2))
    return rho, float(_two_sided_t_p(abs(statistic), size - 2))


def _rank(values: np.ndarray) -> np.ndarray:
    """Average ranks, so ties do not bias the correlation."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(1, values.size + 1, dtype=np.float64)
    unique, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    if counts.max() > 1:
        sums = np.zeros(unique.size, dtype=np.float64)
        np.add.at(sums, inverse, ranks)
        ranks = (sums / counts)[inverse]
    return ranks


def _two_sided_t_p(statistic: float, degrees: int) -> float:
    """Two-sided Student-t tail by the regularised incomplete beta, via a continued fraction."""
    x = degrees / (degrees + statistic**2)
    return float(_incomplete_beta(0.5 * degrees, 0.5, x))


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    import math

    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_continued_fraction(a: float, b: float, x: float, iterations: int = 300) -> float:
    """Lentz evaluation of the continued fraction for the incomplete beta.

    Written in the standard two-steps-per-iteration form. An earlier one-step-per-index
    version had the parity inverted, which made p-values roughly five times too small; the
    null-calibration test in the suite is what caught it and is why it exists.
    """
    tiny = 1e-30
    epsilon = 1e-14
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    result = d
    for m in range(1, iterations + 1):
        m2 = 2 * m
        # Even step.
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        result *= d * c
        # Odd step.
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return result


def _occupied_volume_um3(points: np.ndarray, bin_edge_voxels: int) -> float:
    """Volume of the region the points occupy, as occupied bins on a fixed cubic lattice.

    An occupied-bin count is used rather than a convex hull because a hull is dominated by a
    handful of outlying points and this cloud has them.
    """
    if points.size == 0:
        return 0.0
    binned = points // bin_edge_voxels
    occupied = np.unique(binned, axis=0).shape[0]
    bin_um = bin_edge_voxels * VOXEL_NM / 1000.0
    return float(occupied * bin_um**3)


def _rarefied_volume_um3(
    points: np.ndarray,
    bin_edge_voxels: int,
    target: int,
    repeats: int,
    seed: int,
) -> float:
    """Occupied volume after subsampling to a common synapse count, averaged over repeats.

    Glomeruli differ enormously in synapse count, and more synapses occupy more bins for
    reasons of sampling alone. Rarefaction removes that confound; without it the measure
    would partly be a count.
    """
    if points.shape[0] <= target:
        return _occupied_volume_um3(points, bin_edge_voxels)
    generator = np.random.default_rng(seed)
    volumes = [
        _occupied_volume_um3(
            points[generator.choice(points.shape[0], size=target, replace=False)],
            bin_edge_voxels,
        )
        for _ in range(repeats)
    ]
    return float(np.mean(volumes))


def collect_postsynaptic_points(
    partners_root: Path, wanted_bodies: dict[int, str]
) -> dict[str, np.ndarray]:
    """Stream the syn-partners shards and gather post-site coordinates per glomerulus.

    The raw syn-points Feather must never be read whole; a previous attempt at 357 million
    points saturated the machine. The derivative is sharded precisely so this is streamable.
    """
    shards = sorted(glob.glob(str(partners_root / "*.parquet")))
    if not shards:
        raise DatasetError(f"No syn-partners shards under {partners_root}")
    body_ids = np.fromiter(wanted_bodies.keys(), dtype=np.uint64, count=len(wanted_bodies))
    order = np.argsort(body_ids)
    sorted_bodies = body_ids[order]
    labels = np.asarray(list(wanted_bodies.values()), dtype=object)[order]
    collected: dict[str, list[np.ndarray]] = {}
    for shard in shards:
        table = pq.read_table(
            shard, columns=["body_post", "x_post", "y_post", "z_post"]
        )
        post = table.column("body_post").to_numpy()
        positions = np.searchsorted(sorted_bodies, post)
        positions = np.clip(positions, 0, sorted_bodies.size - 1)
        hit = sorted_bodies[positions] == post
        if not hit.any():
            continue
        coordinates = np.stack(
            (
                table.column("x_post").to_numpy()[hit],
                table.column("y_post").to_numpy()[hit],
                table.column("z_post").to_numpy()[hit],
            ),
            axis=1,
        ).astype(np.int64)
        for label in np.unique(labels[positions[hit]]):
            mask = labels[positions[hit]] == label
            collected.setdefault(str(label), []).append(coordinates[mask])
    return {
        label: np.concatenate(chunks) if chunks else np.empty((0, 3), dtype=np.int64)
        for label, chunks in collected.items()
    }


def run_glomerular_volume_scaling(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Measure glomerular volume and test the published release-site scaling against it."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("The glomerular volume scaling test")
    )
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported glomerular-volume contract schema")
    parse_provenance(str(contract["provenance"]))
    definition = contract["volume_definition"]
    control = contract["sampling_confound_and_its_control"]
    bin_edge = int(definition["bin_edge_voxels"])

    male_cns = root / "raw" / "male-cns-v1.0"
    annotations = male_cns / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    receptors, projections = load_olfactory_populations(annotations)
    graph = SparseConnectome.load(graph_path)
    graph.validate()
    glomeruli = sorted(set(receptors) & set(projections))

    # Only postsynaptic sites on uniglomerular PNs are wanted, labelled by glomerulus.
    wanted: dict[int, str] = {}
    for glomerulus in glomeruli:
        for body in projections[glomerulus]:
            wanted[int(body)] = glomerulus
    partners_root = root / "derived" / "male-cns-v1.0" / "contacts" / "syn-partners"
    clouds = collect_postsynaptic_points(partners_root, wanted)

    counts = {key: int(value.shape[0]) for key, value in clouds.items()}
    present = [g for g in glomeruli if counts.get(g, 0) > 0]
    if not present:
        raise DatasetError("No postsynaptic points were collected for any glomerulus")
    target = min(counts[g] for g in present)
    seed = int(control["seed"])
    repeats = int(control["repeats"])

    rows: list[dict[str, Any]] = []
    for glomerulus in present:
        receptor_indices = _dense_indices(graph, receptors[glomerulus])
        projection_indices = _dense_indices(graph, projections[glomerulus])
        source_member = np.zeros(graph.neuron_count, dtype=bool)
        target_member = np.zeros(graph.neuron_count, dtype=bool)
        source_member[receptor_indices] = True
        target_member[projection_indices] = True
        selected = source_member[graph.source_indices] & target_member[graph.target_indices]
        contacts = graph.contact_counts[selected]
        cloud = clouds[glomerulus]
        rows.append(
            {
                "glomerulus": glomerulus,
                "receptor_bodies": int(receptor_indices.size),
                "projection_bodies": int(projection_indices.size),
                "realised_connections": int(selected.sum()),
                "median_contacts_per_connection": (
                    float(np.median(contacts)) if contacts.size else None
                ),
                "postsynaptic_points": counts[glomerulus],
                "full_sample_volume_um3": _occupied_volume_um3(cloud, bin_edge),
                "rarefied_volume_um3": _rarefied_volume_um3(
                    cloud, bin_edge, target, repeats, seed
                ),
            }
        )

    scored = [row for row in rows if row["median_contacts_per_connection"] is not None]
    contacts_array = np.asarray(
        [row["median_contacts_per_connection"] for row in scored], dtype=np.float64
    )
    rarefied = np.asarray([row["rarefied_volume_um3"] for row in scored], dtype=np.float64)
    full = np.asarray([row["full_sample_volume_um3"] for row in scored], dtype=np.float64)
    receptor_counts = np.asarray([row["receptor_bodies"] for row in scored], dtype=np.float64)

    h1_rho, h1_p = _spearman(contacts_array, rarefied)
    h2_rho, h2_p = _spearman(rarefied, receptor_counts)
    full_rho, full_p = _spearman(contacts_array, full)
    hypotheses = {str(item["id"]): item for item in contract["hypotheses"]}
    kw_four = {
        row["glomerulus"]: row
        for row in scored
        if row["glomerulus"] in {"DL5", "DM4", "DM6", "VM2"}
    }

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
        "glomeruli_scored": len(scored),
        "rarefaction": {
            "target_points_per_glomerulus": target,
            "repeats": repeats,
            "seed": seed,
            "bin_edge_voxels": bin_edge,
            "bin_edge_um": bin_edge * VOXEL_NM / 1000.0,
        },
        "hypotheses": {
            "H1": {
                "statement": hypotheses["H1"]["statement"],
                "spearman_rho": h1_rho,
                "p_value": h1_p,
                "criterion": "rho > 0 at p < 0.05",
                "passed": bool(h1_rho > 0.0 and h1_p < 0.05),
                "full_sample_spearman_rho": full_rho,
                "full_sample_p_value": full_p,
            },
            "H2": {
                "statement": hypotheses["H2"]["statement"],
                "spearman_rho": h2_rho,
                "p_value": h2_p,
                "criterion": "not significantly positive at p < 0.05",
                "passed": bool(not (h2_rho > 0.0 and h2_p < 0.05)),
                "note": hypotheses["H2"]["note"],
            },
        },
        "hypotheses_descriptive": {
            "H3": {"statement": hypotheses["H3"]["statement"], "table": "by_glomerulus"},
            "H4": {
                "statement": hypotheses["H4"]["statement"],
                "kazama_wilson_glomeruli": {
                    key: {
                        "rarefied_volume_um3": value["rarefied_volume_um3"],
                        "median_contacts_per_connection": value[
                            "median_contacts_per_connection"
                        ],
                    }
                    for key, value in sorted(kw_four.items())
                },
            },
        },
        "by_glomerulus": rows,
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
