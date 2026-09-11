# SPDX-License-Identifier: GPL-2.0-or-later
"""Read recordings and a frozen contract, return a verdict.

This module cannot run a simulation, cannot change a threshold and cannot see a video. It
reads what the contract says and what the recordings contain, and it reports which criteria
passed. Mirroring `demo01_acceptance`, which exists for the same reason: the code that scores
an experiment must not be able to alter it.

Every criterion is evaluated from the recording alone. Where a criterion cannot be evaluated
because a variant is missing, it is reported as `not_scored` with the reason, and never as a
pass. Where a criterion is gated on a spike floor, failing the floor makes it `not_scored`,
which is what DEMO-01's C5 does and why: a selectivity computed from one spike against zero
is exactly plus or minus one, and that number is noise wearing a result's clothes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

NOT_SCORED = "not_scored"
PASS = "pass"
FAIL = "fail"

VERDICT_NO_DEMONSTRATION = "NO DEMONSTRATION"
VERDICT_INVALID = "INVALID AS A CAUSAL CLAIM"
VERDICT_CAUSAL = "FULL-GRAPH CAUSAL BEHAVIOUR"
VERDICT_CAUSAL_TOPOLOGY = "FULL-GRAPH CAUSAL BEHAVIOUR, TOPOLOGY-SPECIFIC"


def read_variant(directory: Path) -> dict[str, Any]:
    """Load one variant's recording. Raises rather than inventing a missing run."""
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decoded = tuple(summary["populations"]["readout_sizes"])
    acting = [row for row in rows if row.get("command", {}).get("state") == "ACTING"]
    peak_readout = 0.0
    raw_spikes = 0
    for row in rows:
        for value in row.get("readout_hz", {}).values():
            peak_readout = max(peak_readout, float(value))
        for count in row.get("readout_raw_counts", {}).values():
            raw_spikes += int(count)
    poses = [row["pose"] for row in rows]
    displacement = 0.0
    if len(poses) >= 2:
        displacement = math.hypot(
            poses[-1]["x_mm"] - poses[0]["x_mm"], poses[-1]["y_mm"] - poses[0]["y_mm"]
        )
    return {
        "directory": str(directory),
        "summary": summary,
        "rows": rows,
        "intervals": len(rows),
        "reached_acting": bool(acting),
        "onset_us": acting[0]["t_us"] if acting else None,
        "acting_intervals": len(acting),
        "peak_readout_hz": peak_readout,
        "raw_readout_spikes": raw_spikes,
        "displacement_mm": displacement,
        "takeoff": summary.get("takeoff", {}),
        "peak_proboscis_rad": max(
            (float(r.get("body", {}).get("proboscis_rad", 0.0)) for r in rows), default=0.0
        ),
        "peak_groom_excursion_rad": max(
            (float(r.get("body", {}).get("groom_excursion_rad", 0.0)) for r in rows),
            default=0.0,
        ),
        "min_tarsus_arista_mm": min(
            (
                float(r.get("body", {}).get("tarsus_arista_mm", math.inf))
                for r in rows
            ),
            default=math.inf,
        ),
        "entry_bodies_driven_max": max(
            (int(r.get("entry_bodies_driven", 0)) for r in rows), default=0
        ),
        "decoded_populations": decoded,
    }


def _criterion(
    status: str, detail: str, **measured: Any
) -> dict[str, Any]:
    return {"status": status, "detail": detail, "measured": measured}


def _sustained_us(rows: list[dict[str, Any]], key: str, threshold: float) -> int:
    """Longest unbroken run, in microseconds, with a body metric at or above threshold."""
    best = current = 0
    previous = None
    for row in rows:
        value = float(row.get("body", {}).get(key, 0.0))
        step = row["t_us"] - previous if previous is not None else 0
        previous = row["t_us"]
        if value >= threshold:
            current += step
            best = max(best, current)
        else:
            current = 0
    return best


def evaluate(
    *, behaviour: str, contract: dict[str, Any], variants: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Apply the frozen contract. Missing variants make criteria not_scored, never passed."""
    criteria = contract["acceptance_criteria"]
    exact = variants.get("exact")
    results: dict[str, dict[str, Any]] = {}

    def missing(*names: str) -> str | None:
        absent = [name for name in names if name not in variants]
        return f"variants not recorded: {', '.join(absent)}" if absent else None

    if exact is None:
        return {
            "behaviour": behaviour,
            "experiment_id": contract["experiment_id"],
            "verdict": VERDICT_NO_DEMONSTRATION,
            "criteria": {
                name: _criterion(NOT_SCORED, "the exact run is not recorded")
                for name in criteria
            },
            "claim_boundary": contract["claim_boundary"],
        }

    # --- the behaviour-exists criterion, one per behaviour -----------------------
    if behaviour == "grooming":
        spec = criteria["G1_the_bout_is_a_reach_and_not_a_wave"]
        excursion_floor = float(spec["min_excursion_rad"])
        baseline = float(spec["measured_non_grooming_baseline_mm"])
        approach_limit = baseline * float(spec["max_closest_approach_fraction_of_baseline"])
        excursion = exact["peak_groom_excursion_rad"]
        approach = exact["min_tarsus_arista_mm"]
        ok = excursion >= excursion_floor and approach <= approach_limit
        results["G1_the_bout_is_a_reach_and_not_a_wave"] = _criterion(
            PASS if ok else FAIL,
            (
                f"peak excursion {excursion:.4f} rad against a floor of "
                f"{excursion_floor:.4f}; closest approach {approach:.4f} mm against a "
                f"limit of {approach_limit:.4f} mm"
            ),
            peak_excursion_rad=excursion,
            min_excursion_rad=excursion_floor,
            closest_approach_mm=approach,
            approach_limit_mm=approach_limit,
            reached_acting=exact["reached_acting"],
        )
    elif behaviour == "feeding":
        spec = criteria["F1_the_extension_is_achieved_and_not_merely_commanded"]
        floor = float(spec["min_achieved_rad"])
        needed_us = int(spec["min_sustained_us"])
        held = _sustained_us(exact["rows"], "proboscis_rad", floor)
        ok = exact["peak_proboscis_rad"] >= floor and held >= needed_us
        results["F1_the_extension_is_achieved_and_not_merely_commanded"] = _criterion(
            PASS if ok else FAIL,
            (
                f"achieved {exact['peak_proboscis_rad']:.4f} rad against {floor:.2f}, "
                f"sustained {held} us against {needed_us}"
            ),
            peak_achieved_rad=exact["peak_proboscis_rad"],
            sustained_us=held,
            reached_acting=exact["reached_acting"],
        )
    else:
        spec = criteria["E1_the_fly_leaves_the_ground"]
        airborne = int(exact["takeoff"].get("longest_airborne_us", 0))
        rise = float(exact["takeoff"].get("z_rise_mm", 0.0))
        ok = airborne >= int(spec["min_airborne_us"]) and rise >= float(
            spec["min_z_rise_mm"]
        )
        results["E1_the_fly_leaves_the_ground"] = _criterion(
            PASS if ok else FAIL,
            (
                f"airborne {airborne} us against {spec['min_airborne_us']}, "
                f"z rise {rise:.3f} mm against {spec['min_z_rise_mm']}"
            ),
            longest_airborne_us=airborne,
            z_rise_mm=rise,
            reached_acting=exact["reached_acting"],
        )

    # --- the two causal criteria, shared in shape across all three ---------------
    ablated_name = {
        "grooming": "G2_the_readout_causes_it",
        "feeding": "F2_the_readout_causes_it",
        "escape": "E2_the_brain_caused_it",
    }[behaviour]
    absent_name = {
        "grooming": "G3_the_stimulus_is_required",
        "feeding": "F3_the_stimulus_is_required",
        "escape": "E3_the_stimulus_was_required",
    }[behaviour]

    for name, variant_key in ((ablated_name, "readout-ablated"), (absent_name, "stimulus-absent")):
        reason = missing(variant_key)
        if reason:
            results[name] = _criterion(NOT_SCORED, reason)
            continue
        control = variants[variant_key]
        acted = control["reached_acting"]
        detail = f"{variant_key} reached ACTING: {acted}"
        extra: dict[str, Any] = {"reached_acting": acted}
        ok = not acted
        if behaviour == "escape":
            limit = float(
                criteria[name].get("max_ablated_z_rise_mm")
                or criteria[name].get("max_absent_z_rise_mm")
            )
            rise = float(control["takeoff"].get("z_rise_mm", 0.0))
            ok = ok and rise <= limit
            detail += f"; z rise {rise:.3f} mm against {limit}"
            extra["z_rise_mm"] = rise
        elif behaviour == "feeding" and "max_ablated_achieved_rad" in criteria[name]:
            limit = float(criteria[name]["max_ablated_achieved_rad"])
            achieved = control["peak_proboscis_rad"]
            ok = ok and achieved <= limit
            detail += f"; achieved {achieved:.4f} rad against {limit}"
            extra["peak_achieved_rad"] = achieved
        elif behaviour == "grooming" and "max_ablated_excursion_fraction" in criteria[name]:
            fraction = float(criteria[name]["max_ablated_excursion_fraction"])
            reference = exact["peak_groom_excursion_rad"]
            achieved = control["peak_groom_excursion_rad"]
            allowed = reference * fraction
            ok = ok and achieved <= allowed
            detail += f"; excursion {achieved:.4f} rad against {allowed:.4f}"
            extra["peak_excursion_rad"] = achieved
        results[name] = _criterion(PASS if ok else FAIL, detail, **extra)

    # --- the topology gate, shared in shape --------------------------------------
    gate_name = {
        "grooming": "G7_topology_claim_gate",
        "feeding": "F6_topology_claim_gate",
        "escape": "E7_topology_claim_gate",
    }[behaviour]
    reason = missing("shuffled-connectome")
    if reason:
        results[gate_name] = _criterion(NOT_SCORED, reason)
    else:
        shuffled = variants["shuffled-connectome"]
        fraction = float(
            criteria[gate_name].get("max_shuffled_fraction_of_exact_peak", 0.0) or 0.0
        )
        allowed = exact["peak_readout_hz"] * fraction
        ok = not shuffled["reached_acting"] and (
            fraction <= 0.0 or shuffled["peak_readout_hz"] <= allowed
        )
        results[gate_name] = _criterion(
            PASS if ok else FAIL,
            (
                f"shuffled reached ACTING: {shuffled['reached_acting']}; peak readout "
                f"{shuffled['peak_readout_hz']:.4f} Hz against {allowed:.4f}"
            ),
            reached_acting=shuffled["reached_acting"],
            peak_readout_hz=shuffled["peak_readout_hz"],
            exact_peak_readout_hz=exact["peak_readout_hz"],
        )

    # Everything the contract names that this evaluator has not scored is reported as
    # unscored with a reason, so a verdict can never be read off a partial matrix.
    for name in criteria:
        if name not in results:
            results[name] = _criterion(
                NOT_SCORED,
                "this criterion needs a variant or a measurement this run did not produce",
            )

    behaviour_criterion = next(
        name for name in results if name.startswith(("G1", "F1", "E1"))
    )
    optional = {
        name
        for name, spec in criteria.items()
        if isinstance(spec, dict) and spec.get("this_criterion_is_optional_to_pass")
    }
    required = [name for name in criteria if name not in optional]
    failed_required = [
        name for name in required if results[name]["status"] == FAIL
    ]
    unscored_required = [
        name for name in required if results[name]["status"] == NOT_SCORED
    ]

    if results[behaviour_criterion]["status"] != PASS:
        verdict = VERDICT_NO_DEMONSTRATION
    elif results[ablated_name]["status"] == FAIL or results[absent_name]["status"] == FAIL:
        verdict = VERDICT_INVALID
    elif failed_required or unscored_required:
        verdict = "INCOMPLETE"
    elif results[gate_name]["status"] == PASS:
        verdict = VERDICT_CAUSAL_TOPOLOGY
    else:
        verdict = VERDICT_CAUSAL

    return {
        "behaviour": behaviour,
        "experiment_id": contract["experiment_id"],
        "verdict": verdict,
        "criteria": results,
        "failed_required": failed_required,
        "unscored_required": unscored_required,
        "variants_recorded": sorted(variants),
        "variants_the_contract_names": list(contract["control_variants"]),
        "claim_ladder": contract["claim_ladder"],
        "may_never_claim": contract["claim_ladder"]["may_never_claim"],
        "declared_limitations": contract[
            "declared_limitations_that_must_travel_with_any_claim"
        ],
        "claim_boundary": contract["claim_boundary"],
        "tier": "V0 Structural, unchanged. This is engineering acceptance, not evidence.",
    }
