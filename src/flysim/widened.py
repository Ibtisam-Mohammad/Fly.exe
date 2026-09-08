# SPDX-License-Identifier: GPL-2.0-or-later
"""Structural sensitivity of the transferred grooming circuit to its selection rule.

ADR-2026-009 withdrew the idea that a synaptic mechanism explains why one contact scale
cannot fit both the 100 Hz and 220 Hz archived reference points, because the reference is a
whole-brain simulation and the transferred circuit a one-hop subgraph. This module runs the
structural test that argument implies: the same ND-04 sweep on circuits that keep every
input-to-readout path of bounded length, so the lateral and recurrent partners the
shortest-path rule dropped are present.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from flysim.circuit import (
    compare_backend_runs,
    load_cell_types,
    load_population_ids,
    make_stimulus_schedule,
    parameters_from_experiment,
    run_genn_circuit,
    run_numpy_circuit,
    select_bounded_path_circuit,
    select_shortest_path_circuit,
)
from flysim.config import load_json, project_root, sha256_json
from flysim.connectome import SparseConnectome
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.polarity import UnresolvedSignPolicy, build_shiu_regression_signs
from flysim.provenance import parse_provenance
from flysim.shiu_reference import load_or_build_shiu_figure5g_reference
from flysim.stage1 import (
    _atomic_json,
    _code_commit,
    _fit_nd04_contact_scale,
    _immutable_snapshot,
)


def _training_rates(candidate: dict[str, Any]) -> dict[float, float]:
    training = candidate["training"]
    return {
        float(frequency): float(rate)
        for frequency, rate in zip(
            training["frequencies_hz"], training["predicted_mean_rates_hz"], strict=True
        )
    }


def _readout_drive(
    selected: Any, edge_signs: np.ndarray
) -> list[dict[str, Any]]:
    """Signed contact composition of the drive arriving directly on each readout.

    A readout that never fires is either starved of input or held down by inhibition, and
    those are different findings. Recording the composition means the artifact can say which
    instead of leaving it to be guessed at.
    """
    body_to_index = {int(body): index for index, body in enumerate(selected.graph.body_ids)}
    drive: list[dict[str, Any]] = []
    for body in selected.readout_body_ids:
        index = body_to_index[int(body)]
        incoming = np.flatnonzero(selected.graph.target_indices == index)
        weighted = selected.graph.contact_counts[incoming] * edge_signs[incoming]
        excitatory = float(weighted[weighted > 0.0].sum())
        inhibitory = float(weighted[weighted < 0.0].sum())
        drive.append(
            {
                "body_id": int(body),
                "incoming_edges": int(incoming.size),
                "excitatory_contacts": excitatory,
                "inhibitory_contacts": inhibitory,
                "net_signed_contacts": excitatory + inhibitory,
                "net_sign": (
                    "excitatory"
                    if excitatory + inhibitory > 0.0
                    else "inhibitory"
                    if excitatory + inhibitory < 0.0
                    else "balanced"
                ),
            }
        )
    return drive


def _delivered_drive(
    selected: Any,
    edge_signs: np.ndarray,
    spike_indices: np.ndarray,
    *,
    frequency_hz: float,
    scale_mv_per_contact: float,
) -> list[dict[str, Any]]:
    """Signed contacts weighted by how often each presynaptic partner actually fired.

    The static composition in :func:`_readout_drive` counts every incoming edge whether or
    not its source ever spikes, and that makes it the wrong sign at K = 3: the static sum is
    net excitatory there while the drive the readout actually receives is strongly inhibitory,
    because almost all of the added excitatory partners are silent. Delivered drive is the
    measure that explains a silent readout; the static sum on its own does not.
    """
    counts = np.bincount(spike_indices, minlength=selected.graph.neuron_count).astype(np.float64)
    body_to_index = {int(body): index for index, body in enumerate(selected.graph.body_ids)}
    delivered: list[dict[str, Any]] = []
    for body in selected.readout_body_ids:
        index = body_to_index[int(body)]
        incoming = np.flatnonzero(selected.graph.target_indices == index)
        weighted = selected.graph.contact_counts[incoming] * edge_signs[incoming]
        source_counts = counts[selected.graph.source_indices[incoming]]
        product = weighted * source_counts
        excitatory_edges = weighted > 0.0
        inhibitory_edges = weighted < 0.0
        positive = float(product[product > 0.0].sum())
        negative = float(product[product < 0.0].sum())
        delivered.append(
            {
                "body_id": int(body),
                "frequency_hz": frequency_hz,
                "scale_mv_per_contact": scale_mv_per_contact,
                "delivered_excitation": positive,
                "delivered_inhibition": negative,
                "delivered_net": positive + negative,
                "static_net_signed_contacts": float(weighted.sum()),
                "static_and_delivered_agree_in_sign": bool(
                    np.sign(weighted.sum()) == np.sign(positive + negative)
                ),
                "active_excitatory_sources": int(
                    np.count_nonzero(excitatory_edges & (source_counts > 0.0))
                ),
                "excitatory_sources": int(np.count_nonzero(excitatory_edges)),
                "active_inhibitory_sources": int(
                    np.count_nonzero(inhibitory_edges & (source_counts > 0.0))
                ),
                "inhibitory_sources": int(np.count_nonzero(inhibitory_edges)),
            }
        )
    return delivered


def _selection_identity_control(
    graph: SparseConnectome,
    inputs: tuple[int, ...],
    readouts: tuple[int, ...],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """At K = 1 the bounded-path rule must return exactly the shortest-path circuit.

    Every number in this sweep is a comparison against the one-hop circuit, so the selection
    rule has to be shown to reproduce it. This fails closed.
    """
    bounded = select_bounded_path_circuit(graph, inputs, readouts, maximum_path_length=1)
    shortest = select_shortest_path_circuit(graph, inputs, readouts, maximum_hops=1)
    identical_bodies = set(bounded.graph.body_ids.tolist()) == set(shortest.graph.body_ids.tolist())
    matches_expected = (
        bounded.graph.neuron_count == int(expected["neurons"])
        and bounded.graph.edge_count == int(expected["edges"])
    )
    control = {
        "bounded_k1_neurons": int(bounded.graph.neuron_count),
        "bounded_k1_edges": int(bounded.graph.edge_count),
        "shortest_path_neurons": int(shortest.graph.neuron_count),
        "shortest_path_edges": int(shortest.graph.edge_count),
        "identical_body_sets": bool(identical_bodies),
        "matches_registered_expectation": bool(matches_expected),
        "input_bodies_stimulated": len(bounded.input_body_ids),
        "passed": bool(
            identical_bodies
            and matches_expected
            and bounded.graph.edge_count == shortest.graph.edge_count
        ),
    }
    if not control["passed"]:
        raise DatasetError(
            "The bounded-path rule does not reproduce the shortest-path circuit at K = 1: "
            f"{control}"
        )
    return control


def run_widened_grooming_transfer(
    *,
    root: Path,
    graph_path: Path,
    experiment_path: Path,
    population_resolution_path: Path,
    output_path: Path,
    backends: tuple[str, ...],
) -> dict[str, Any]:
    """Run the preregistered bounded-path sweep and score its hypotheses."""
    contract = load_json(experiment_path)
    if contract.get("schema_version") not in {"1.0", "1.1"}:
        raise ConfigurationError("Unsupported widened-circuit contract schema")
    parse_provenance(str(contract["provenance"]))
    base_path = project_root() / str(contract["base_experiment"])
    base = load_json(base_path)
    parameters = parameters_from_experiment(base)
    base_protocol = base["transfer_protocol"]
    fit_protocol = base_protocol["nd04_contact_scale_fit"]
    seeds = tuple(int(value) for value in base_protocol["seeds"])
    time_tolerance = float(base_protocol["backend_spike_time_tolerance_ms"])
    rate_tolerance = float(base_protocol["backend_rate_relative_tolerance"])

    one_hop = contract["one_hop_reference_values"]
    one_hop_path = root / str(one_hop["source_artifact"])
    observed = sha256_file(one_hop_path) if one_hop_path.is_file() else None
    if observed != str(one_hop["source_sha256"]):
        raise DatasetError(
            "One-hop reference artifact SHA-256 mismatch: "
            f"expected {one_hop['source_sha256']}, observed {observed}"
        )

    source_root = root / "raw" / "auxiliary" / "shiu-2024-brain-model"
    if not (source_root / "results.zip").is_file():
        raise DatasetError("The checksum-locked Shiu results archive is required for the sweep")
    reference = load_or_build_shiu_figure5g_reference(
        source_root=source_root,
        dataset_card_path=project_root() / "configs" / "datasets" / "shiu-2024-brain-model.json",
        output_path=root / "evidence" / "male-cns-v1.0" / "shiu-figure5g-reference.json",
    )
    reference_by_frequency = {
        float(item["frequency_hz"]): (float(item["mean_rate_hz"]), float(item["std_rate_hz"]))
        for item in reference["curve"]
    }
    for key in ("100", "220"):
        mean, std = reference_by_frequency[float(key)]
        if abs(mean - float(one_hop["reference_mean_hz"][key])) > 1e-3 or abs(
            std - float(one_hop["reference_std_hz"][key])
        ) > 1e-3:
            raise DatasetError(
                f"The registered reference values at {key} Hz disagree with the locked curve"
            )

    populations = load_population_ids(population_resolution_path)
    inputs = populations["shiu-jon-f-input"]
    readouts = populations["shiu-abn1-readout"]
    graph = SparseConnectome.load(graph_path)
    male_cns = root / "raw" / "male-cns-v1.0"
    annotations = male_cns / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    transmitters = male_cns / "body-neurotransmitters-male-cns-v1.0.feather"
    protocol = contract["protocol"]
    policy = UnresolvedSignPolicy(str(protocol["unresolved_sign_policy"]))
    parity = protocol["parity_condition"]
    hypotheses = {str(item["id"]): item for item in contract["hypotheses"]}
    match_scale = float(one_hop["scale_matching_100hz_mv_per_contact"])
    one_hop_220 = float(one_hop["readout_rate_at_0_15_hz"]["220"])
    h1_frequency = 220.0
    mean_100, std_100 = reference_by_frequency[100.0]
    mean_220, std_220 = reference_by_frequency[220.0]

    identity_control: dict[str, Any] | None = None
    control_spec = contract["circuit_selection"].get("identity_control")
    if control_spec is not None:
        identity_control = _selection_identity_control(
            graph, inputs, readouts, control_spec["expected"]
        )

    by_path_length: list[dict[str, Any]] = []
    for length in contract["circuit_selection"]["maximum_path_lengths"]:
        maximum_path_length = int(length)
        selected = select_bounded_path_circuit(
            graph, inputs, readouts, maximum_path_length=maximum_path_length
        )
        cell_types = load_cell_types(annotations, selected.graph.body_ids)
        sign_result = build_shiu_regression_signs(
            selected.graph, transmitters, unresolved_policy=policy, seed=seeds[0]
        )
        signs = sign_result.edge_signs
        inhibitory_sources = np.unique(selected.graph.source_indices[signs < 0.0])
        excitatory_sources = np.unique(selected.graph.source_indices[signs > 0.0])
        inhibition = {
            "inhibitory_neurons": int(inhibitory_sources.size),
            "excitatory_neurons": int(excitatory_sources.size),
            "neurons_with_no_signed_output": int(
                selected.graph.neuron_count - np.unique(
                    selected.graph.source_indices[signs != 0.0]
                ).size
            ),
            "inhibitory_edges": int(np.count_nonzero(signs < 0.0)),
            "excitatory_edges": int(np.count_nonzero(signs > 0.0)),
            "zero_sign_edges": int(np.count_nonzero(signs == 0.0)),
            "known_neurons": sign_result.known_neurons,
            "unresolved_neurons": sign_result.unresolved_neurons,
        }
        schedule = make_stimulus_schedule(
            selected.graph,
            selected.input_body_ids,
            frequency_hz=float(parity["frequency_hz"]),
            parameters=parameters,
            seed=int(parity["seed"]),
        )
        numpy_run = run_numpy_circuit(
            selected.graph, signs, schedule, parameters, selected.readout_body_ids
        )
        comparisons: list[dict[str, Any]] = []
        if "genn" in backends:
            genn_run = run_genn_circuit(
                selected.graph,
                signs,
                schedule,
                parameters,
                selected.readout_body_ids,
                root / "cache" / "genn" / "stage1"
                / f"{contract['experiment_id']}-k{maximum_path_length}",
            )
            comparisons.append(
                compare_backend_runs(
                    numpy_run,
                    genn_run,
                    spike_time_tolerance_ms=time_tolerance,
                    rate_relative_tolerance=rate_tolerance,
                )
            )
        parity_passed = (
            all(bool(item["passed"]) for item in comparisons) if comparisons else None
        )
        block: dict[str, Any] = {
            "maximum_path_length": maximum_path_length,
            "selection": selected.as_dict(),
            "circuit_sha256": selected.graph.source_sha256,
            "cell_type_counts": {
                value or "untyped": cell_types.count(value) for value in sorted(set(cell_types))
            },
            "inhibition": inhibition,
            "input_bodies_stimulated": len(selected.input_body_ids),
            "readout_drive": _readout_drive(selected, signs),
            "readout_delivered_drive": _delivered_drive(
                selected,
                signs,
                run_numpy_circuit(
                    selected.graph,
                    signs,
                    make_stimulus_schedule(
                        selected.graph,
                        selected.input_body_ids,
                        frequency_hz=h1_frequency,
                        parameters=replace(parameters, synaptic_mv_per_contact=match_scale),
                        seed=seeds[0],
                    ),
                    replace(parameters, synaptic_mv_per_contact=match_scale),
                    selected.readout_body_ids,
                ).spike_indices,
                frequency_hz=h1_frequency,
                scale_mv_per_contact=match_scale,
            ),
            "parity_condition": {
                "frequency_hz": float(parity["frequency_hz"]),
                "seed": int(parity["seed"]),
                "numpy_readout_rates_hz": list(numpy_run.readout_rates_hz),
                "total_spikes": int(numpy_run.spike_indices.size),
                "distinct_spiking_neurons": int(np.unique(numpy_run.spike_indices).size),
            },
            "backend_comparisons": [
                {key: value for key, value in item.items() if key != "timing_outliers"}
                | {"timing_outlier_count": len(item["timing_outliers"])}
                for item in comparisons
            ],
            "backend_parity_passed": parity_passed,
        }
        if parity_passed is not True:
            block["nd04_contact_scale_fit"] = {
                "status": "blocked",
                "reason": (
                    "Numerical backend parity must pass before the ND-04 sweep"
                    if comparisons
                    else "No second backend was requested, so parity is unestablished"
                ),
            }
            block["hypotheses"] = {"H1": None, "H2": None}
        else:
            fit = _fit_nd04_contact_scale(
                graph=selected.graph,
                edge_signs=signs,
                input_body_ids=selected.input_body_ids,
                readout_body_ids=selected.readout_body_ids,
                parameters=parameters,
                seeds=seeds,
                reference=reference,
                fit_protocol=fit_protocol,
            )
            block["nd04_contact_scale_fit"] = fit
            by_scale = {
                float(candidate["synaptic_mv_per_contact"]): _training_rates(candidate)
                for candidate in fit["candidate_results"]
            }
            if match_scale not in by_scale:
                raise ConfigurationError(
                    f"The one-hop matching scale {match_scale} is not in the candidate grid"
                )
            rate_220 = by_scale[match_scale][220.0]
            within_both = sorted(
                scale
                for scale, rates in by_scale.items()
                if abs(rates[100.0] - mean_100) <= std_100
                and abs(rates[220.0] - mean_220) <= std_220
            )
            # A one-sided "below the one-hop rate" test is satisfied by a readout that
            # produces nothing, which is not evidence that widening moves the response
            # toward the reference. The outcome is therefore three-way and only
            # "moderated" supports the structural reading.
            if rate_220 <= 0.0:
                outcome = "suppressed"
            elif rate_220 < one_hop_220:
                outcome = "moderated"
            else:
                outcome = "not_moderated"
            block["hypotheses"] = {
                "H1": {
                    "statement": hypotheses["H1"]["statement"],
                    "scale_mv_per_contact": match_scale,
                    "rate_100hz_at_scale": by_scale[match_scale][100.0],
                    "rate_220hz_at_scale": rate_220,
                    "one_hop_rate_220hz": one_hop_220,
                    "outcome": outcome,
                    "one_sided_inequality_holds": bool(rate_220 < one_hop_220),
                    "passed": outcome == "moderated",
                },
                "H2": {
                    "statement": hypotheses["H2"]["statement"],
                    "reference_100hz": {"mean": mean_100, "std": std_100},
                    "reference_220hz": {"mean": mean_220, "std": std_220},
                    "scales_within_one_sd_at_both": within_both,
                    "passed": bool(within_both),
                },
            }
        block["hypotheses_descriptive"] = {
            key: hypotheses[key]["statement"] for key in ("H3", "H4", "H5") if key in hypotheses
        }
        by_path_length.append(block)

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": str(contract["experiment_id"]),
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "base_experiment_sha256": sha256_json(base),
        "code_commit": _code_commit(),
        "provenance": str(contract["provenance"]),
        "assumption_ids": list(contract["assumption_ids"]),
        "graph_source_sha256": graph.source_sha256,
        "one_hop_reference_values": one_hop,
        "selection_identity_control": identity_control,
        "known_confound": contract.get("known_confound"),
        "supersedes": contract.get("supersedes"),
        "backends": list(backends),
        "by_path_length": by_path_length,
        "disclosure": str(contract["disclosure"]),
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
