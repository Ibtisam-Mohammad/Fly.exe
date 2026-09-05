# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit, replayable functional-sign alternatives for aggregate edges."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

from flysim.config import project_root
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.errors import DatasetError


class UnresolvedSignPolicy(StrEnum):
    ZERO = "zero"
    EXCITATORY = "excitatory-control"
    INHIBITORY = "inhibitory-control"
    SEEDED_BALANCED = "seeded-balanced-control"


@dataclass(frozen=True, slots=True)
class EdgeSignResult:
    edge_signs: np.ndarray
    neuron_signs: np.ndarray
    transmitter_by_neuron: tuple[str, ...]
    known_neurons: int
    unresolved_neurons: int


def _transmitter_map(source: Path, body_ids: np.ndarray) -> dict[int, str]:
    if not source.is_file():
        raise DatasetError(f"Body neurotransmitter source is missing: {source}")
    table = feather.read_table(source, columns=("body", "consensus_nt"), memory_map=True)
    selected = table.filter(
        pc.is_in(
            pc.cast(table["body"], pa.uint64()),
            value_set=pa.array(body_ids, type=pa.uint64()),
        )
    )
    transmitters: dict[int, str] = {}
    for row in selected.to_pylist():
        body_id = int(row["body"])
        value = str(row["consensus_nt"] or "unclear").lower()
        previous = transmitters.get(body_id)
        if previous is not None and previous != value:
            concrete = {item for item in (previous, value) if item != "unclear"}
            if len(concrete) > 1:
                raise DatasetError(
                    f"Conflicting consensus transmitters for MaleCNS body {body_id}: "
                    f"{sorted(concrete)}"
                )
            value = next(iter(concrete), "unclear")
        transmitters[body_id] = value
    return transmitters


def build_shiu_regression_signs(
    graph: SparseConnectome,
    transmitter_source: Path,
    *,
    unresolved_policy: UnresolvedSignPolicy,
    seed: int,
) -> EdgeSignResult:
    """Build the named transmitter-only regression variant, never a physiological default."""
    graph.validate()
    transmitters = _transmitter_map(transmitter_source, graph.body_ids)
    labels = tuple(transmitters.get(int(body_id), "unclear") for body_id in graph.body_ids)
    signs = np.zeros(graph.neuron_count, dtype=np.float32)
    inhibitory = {"gaba", "glutamate"}
    excitatory = {"acetylcholine", "dopamine", "octopamine", "serotonin"}
    known = np.fromiter(
        (label in inhibitory or label in excitatory for label in labels),
        dtype=np.bool_,
        count=graph.neuron_count,
    )
    signs[np.fromiter((x in excitatory for x in labels), dtype=np.bool_)] = 1.0
    signs[np.fromiter((x in inhibitory for x in labels), dtype=np.bool_)] = -1.0
    unresolved = ~known
    if unresolved_policy is UnresolvedSignPolicy.EXCITATORY:
        signs[unresolved] = 1.0
    elif unresolved_policy is UnresolvedSignPolicy.INHIBITORY:
        signs[unresolved] = -1.0
    elif unresolved_policy is UnresolvedSignPolicy.SEEDED_BALANCED:
        rng = np.random.default_rng(seed)
        signs[unresolved] = rng.choice(
            np.array([-1.0, 1.0], dtype=np.float32), size=int(unresolved.sum())
        )
    return EdgeSignResult(
        edge_signs=signs[graph.source_indices],
        neuron_signs=signs,
        transmitter_by_neuron=labels,
        known_neurons=int(known.sum()),
        unresolved_neurons=int(unresolved.sum()),
    )


def write_edge_sign_variant(
    graph: SparseConnectome,
    transmitter_source: Path,
    output: Path,
    *,
    unresolved_policy: UnresolvedSignPolicy,
    seed: int,
) -> dict[str, Any]:
    """Write signs and an adjacent immutable provenance manifest."""
    if not transmitter_source.is_file():
        raise DatasetError(f"Body neurotransmitter source is missing: {transmitter_source}")
    manifest = output.with_suffix(output.suffix + ".json")
    if output.exists() or manifest.exists():
        if not output.is_file() or not manifest.is_file():
            raise DatasetError(f"Incomplete edge-sign derivative already exists: {output}")
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        expected_identity = {
            "graph_source_sha256": graph.source_sha256,
            "transmitter_source_sha256": sha256_file(transmitter_source),
            "unresolved_policy": unresolved_policy.value,
            "seed": seed,
        }
        if any(existing.get(key) != value for key, value in expected_identity.items()):
            raise DatasetError(f"Refusing to overwrite a different edge-sign derivative: {output}")
        if existing.get("edge_signs_sha256") != sha256_file(output):
            raise DatasetError(f"Edge-sign derivative checksum changed: {output}")
        return {**existing, "manifest": str(manifest.resolve())}
    result = build_shiu_regression_signs(
        graph,
        transmitter_source,
        unresolved_policy=unresolved_policy,
        seed=seed,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    with temporary.open("wb") as stream:
        np.save(stream, result.edge_signs, allow_pickle=False)
    os.replace(temporary, output)
    payload = {
        "schema_version": "1.0",
        "implementation_version": "shiu-regression-signs-v1",
        "variant": "shiu-transmitter-only-regression",
        "physiological_default": False,
        "unresolved_policy": unresolved_policy.value,
        "seed": seed,
        "assumption_ids": ["ND-03", "ND-04", "ND-LIF-01"],
        "provenance": "M/P/E",
        "warning": (
            "Transmitter-only signs reproduce a published regression rule but do not resolve "
            "postsynaptic receptor-dependent polarity."
        ),
        "graph_source_sha256": graph.source_sha256,
        "transmitter_source": str(transmitter_source.resolve()),
        "transmitter_source_sha256": sha256_file(transmitter_source),
        "neurons": graph.neuron_count,
        "edges": graph.edge_count,
        "known_transmitter_sign_neurons": result.known_neurons,
        "unresolved_transmitter_sign_neurons": result.unresolved_neurons,
        "edge_signs_path": str(output.resolve()),
        "edge_signs_sha256": sha256_file(output),
        "code_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=project_root(),
        ).stdout.strip(),
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    part = manifest.with_suffix(manifest.suffix + ".part")
    part.write_text(encoded, encoding="utf-8")
    os.replace(part, manifest)
    return {**payload, "manifest": str(manifest.resolve())}
