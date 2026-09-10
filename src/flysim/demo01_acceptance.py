# SPDX-License-Identifier: GPL-2.0-or-later
"""Judge a finished DEMO-01 control matrix against the frozen acceptance contract.

This module reads recordings and a contract and returns a verdict. It cannot run a
simulation, cannot change a threshold, and cannot see a video. That separation is the
point: the numbers that license a claim are computed by code that has no way to produce
them.

The criteria are in `configs/experiments/demo01-acceptance-v1.json` and were committed
before the control matrix ran. If one fails, the failure is recorded and the claim is
narrowed. None is rewritten.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.demo01_render import load_trace
from flysim.demo01_visual import VISUAL_LEFT_READOUT, VISUAL_RIGHT_READOUT
from flysim.errors import ConfigurationError, ReadinessError

CLAIM_NO_DEMONSTRATION = "NO DEMONSTRATION"
CLAIM_INVALID = "INVALID AS A CAUSAL CLAIM"
CLAIM_CAUSAL_EMBODIMENT = "FULL-GRAPH CAUSAL EMBODIMENT"
CLAIM_TOPOLOGY = "FULL-GRAPH CAUSAL EMBODIMENT, TOPOLOGY-SPECIFIC"


@dataclass(frozen=True, slots=True)
class VariantSummary:
    """The measured behaviour of one control variant."""

    variant: str
    displacement_mm: float
    net_heading_change_rad: float
    initial_cue_distance_mm: float
    final_cue_distance_mm: float
    locomoted: bool
    locomotion_onset_us: int | None
    quiescent_displacement_mm: float
    # A4 as the contract states it: do the two means share a sign?
    cue_locked: bool | None
    mean_readout_difference_hz: float
    mean_cue_bearing_deg: float
    # Reported, never scored. See _cue_locked for why it is not the criterion.
    cue_locked_sign_agreement: float | None

    @property
    def approach_mm(self) -> float:
        """How much closer the fly ended up. Negative means it retreated."""
        return self.initial_cue_distance_mm - self.final_cue_distance_mm


def _quiescent_displacement(rows: list[dict[str, Any]], quiescent_us: int) -> float:
    """How far the body drifted before the decoder was allowed to command anything."""
    before = [row for row in rows if int(row["t_us"]) <= quiescent_us]
    if len(before) < 2:
        return 0.0
    first, last = before[0]["pose"], before[-1]["pose"]
    return float(
        math.hypot(last["x_mm"] - first["x_mm"], last["y_mm"] - first["y_mm"])
    )


def _cue_locked(rows: list[dict[str, Any]]) -> tuple[bool | None, float, float, float | None]:
    """A4 exactly as the frozen contract states it, plus the diagnostic it is not.

    The contract's words are: "the mean signed difference between the two decoded
    descending populations must have the same sign as the cue's mean signed bearing, over
    the intervals in which the decoder is LOCOMOTING." That is a comparison of two means,
    and it is what this returns.

    An earlier version of this function tested something else -- the fraction of intervals
    whose signs agreed, against a threshold of one half -- and the difference is not
    cosmetic. A fly that turns *toward* a cue drives the bearing through zero, where its
    sign is noise, so the per-interval fraction is systematically harsher on an approach
    than on an avoidance. The sweep showed exactly that: at the same gain the avoidance
    decoder scored 0.854 and the approach decoder 0.718. Comparing means is insensitive to
    it, because the mean bearing stays on the side the cue was on.

    The fraction is still returned, as a diagnostic that is reported and not scored.
    """
    differences: list[float] = []
    bearings: list[float] = []
    agree = 0
    counted = 0
    for row in rows:
        if row["command"]["state"] != "LOCOMOTING":
            continue
        bearing = row["cue"].get("bearing_deg")
        if bearing is None:
            continue
        left = float(row["readout_hz"].get(VISUAL_LEFT_READOUT, 0.0))
        right = float(row["readout_hz"].get(VISUAL_RIGHT_READOUT, 0.0))
        difference = left - right
        differences.append(difference)
        bearings.append(float(bearing))
        if difference != 0.0 and bearing != 0.0:
            counted += 1
            if (difference > 0.0) == (bearing > 0.0):
                agree += 1
    if not differences:
        return None, 0.0, 0.0, None
    mean_difference = float(np.mean(differences))
    mean_bearing = float(np.mean(bearings))
    if mean_difference == 0.0 or mean_bearing == 0.0:
        locked: bool | None = False
    else:
        locked = (mean_difference > 0.0) == (mean_bearing > 0.0)
    fraction = agree / counted if counted else None
    return locked, mean_difference, mean_bearing, fraction


def read_variant(directory: Path, quiescent_us: int) -> VariantSummary:
    """Load one variant's recording and reduce it to the quantities the contract names."""
    summary_path = directory / "summary.json"
    if not summary_path.is_file():
        raise ReadinessError(f"No recording at {directory}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = load_trace(directory / "trace.jsonl")
    outcome = summary["outcome"]
    locked, mean_difference, mean_bearing, fraction = _cue_locked(rows)
    return VariantSummary(
        variant=str(summary["variant"]),
        displacement_mm=float(outcome["displacement_mm"]),
        net_heading_change_rad=float(outcome["net_heading_change_rad"]),
        initial_cue_distance_mm=float(outcome["initial_cue_distance_mm"]),
        final_cue_distance_mm=float(outcome["final_cue_distance_mm"]),
        locomoted=any(row["command"]["state"] == "LOCOMOTING" for row in rows),
        locomotion_onset_us=(
            int(outcome["locomotion_onset_us"])
            if outcome["locomotion_onset_us"] is not None
            else None
        ),
        quiescent_displacement_mm=_quiescent_displacement(rows, quiescent_us),
        cue_locked=locked,
        mean_readout_difference_hz=mean_difference,
        mean_cue_bearing_deg=mean_bearing,
        cue_locked_sign_agreement=fraction,
    )


def evaluate(
    *,
    contract_path: Path,
    variants: dict[str, VariantSummary],
    quiescent_us: int,
) -> dict[str, Any]:
    """Apply the frozen criteria and return the verdict with every measured number."""
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported DEMO-01 acceptance contract schema")
    criteria = contract["acceptance_criteria"]
    required = {"exact", "readout-ablated", "stimulus-absent"}
    missing = sorted(required - set(variants))
    if missing:
        raise ReadinessError(
            f"The acceptance contract needs variants {missing}, which were not run"
        )
    exact = variants["exact"]
    ablated = variants["readout-ablated"]
    absent = variants["stimulus-absent"]
    shuffled = variants.get("shuffled-connectome")

    a1_min = float(criteria["A1_the_fly_starts_still_and_then_moves"]["min_displacement_mm"])
    a1 = exact.locomoted and exact.displacement_mm >= a1_min

    a2_rule = criteria["A2_the_behaviour_is_caused_by_the_neural_readout"]
    a2_fraction = (
        float(ablated.displacement_mm / exact.displacement_mm)
        if exact.displacement_mm > 0
        else float("inf")
    )
    a2 = (
        a2_fraction <= float(a2_rule["max_ablated_displacement_fraction"])
        and not ablated.locomoted
    )

    a3_rule = criteria["A3_the_behaviour_requires_the_stimulus"]
    a3_fraction = (
        float(absent.displacement_mm / exact.displacement_mm)
        if exact.displacement_mm > 0
        else float("inf")
    )
    a3 = (
        a3_fraction <= float(a3_rule["max_absent_displacement_fraction"])
        and absent.approach_mm <= float(a3_rule["max_absent_approach_mm"])
    )

    a4 = bool(exact.cue_locked)

    a5_rule = criteria["A5_topology_claim_gate"]
    a5_divergence = (
        abs(shuffled.displacement_mm - exact.displacement_mm)
        if shuffled is not None
        else None
    )
    a5 = bool(
        shuffled is not None
        and (
            (a5_divergence or 0.0) >= float(a5_rule["min_shuffled_divergence_mm"])
            or not (shuffled.locomoted and shuffled.displacement_mm >= a1_min)
        )
    )

    if not a1:
        claim = CLAIM_NO_DEMONSTRATION
    elif not (a2 and a3 and a4):
        # A2 and A3 are the causal gates and A4 is the cue-locking gate. Failing any of
        # them means the same thing: the behaviour is not shown to be caused by the cue
        # reaching the body through the brain.
        claim = CLAIM_INVALID
    elif a5:
        claim = CLAIM_TOPOLOGY
    else:
        claim = CLAIM_CAUSAL_EMBODIMENT

    return {
        "schema_version": "1.0",
        "result_id": "demo01-acceptance-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "quiescent_us": quiescent_us,
        "measured": {
            name: {
                "displacement_mm": value.displacement_mm,
                "net_heading_change_rad": value.net_heading_change_rad,
                "net_heading_change_deg": math.degrees(value.net_heading_change_rad),
                "initial_cue_distance_mm": value.initial_cue_distance_mm,
                "final_cue_distance_mm": value.final_cue_distance_mm,
                "approach_mm": value.approach_mm,
                "locomoted": value.locomoted,
                "locomotion_onset_us": value.locomotion_onset_us,
                "quiescent_displacement_mm": value.quiescent_displacement_mm,
                "cue_locked": value.cue_locked,
                "mean_readout_difference_hz": value.mean_readout_difference_hz,
                "mean_cue_bearing_deg": value.mean_cue_bearing_deg,
                "cue_locked_sign_agreement_reported_not_scored": (
                    value.cue_locked_sign_agreement
                ),
            }
            for name, value in sorted(variants.items())
        },
        "criteria": {
            "A1_the_fly_starts_still_and_then_moves": {
                "passed": bool(a1),
                "displacement_mm": exact.displacement_mm,
                "threshold_mm": a1_min,
                "locomoted": exact.locomoted,
            },
            "A2_the_behaviour_is_caused_by_the_neural_readout": {
                "passed": bool(a2),
                "ablated_displacement_fraction": a2_fraction,
                "threshold": float(a2_rule["max_ablated_displacement_fraction"]),
                "ablated_locomoted": ablated.locomoted,
            },
            "A3_the_behaviour_requires_the_stimulus": {
                "passed": bool(a3),
                "absent_displacement_fraction": a3_fraction,
                "threshold": float(a3_rule["max_absent_displacement_fraction"]),
                "absent_approach_mm": absent.approach_mm,
                "approach_threshold_mm": float(a3_rule["max_absent_approach_mm"]),
            },
            "A4_the_turn_is_cue_locked": {
                "passed": bool(a4),
                "mean_readout_difference_hz": exact.mean_readout_difference_hz,
                "mean_cue_bearing_deg": exact.mean_cue_bearing_deg,
                "test": (
                    "the two means share a sign, exactly as the frozen contract states"
                ),
                "sign_agreement_fraction_reported_not_scored": (
                    exact.cue_locked_sign_agreement
                ),
            },
            "A5_topology_claim_gate": {
                "passed": bool(a5),
                "optional": True,
                "shuffled_divergence_mm": a5_divergence,
                "threshold_mm": float(a5_rule["min_shuffled_divergence_mm"]),
                "shuffled_locomoted": shuffled.locomoted if shuffled else None,
            },
        },
        "claim": claim,
        "claim_text": contract["claim_ladder"][
            "if_A1_fails"
            if claim == CLAIM_NO_DEMONSTRATION
            else "if_A1_passes_and_A2_or_A3_fails"
            if claim == CLAIM_INVALID
            else "if_A1_to_A5_pass"
            if claim == CLAIM_TOPOLOGY
            else "if_A1_to_A4_pass_and_A5_fails"
        ],
        "limitations_that_travel_with_the_claim": contract[
            "declared_limitations_that_must_travel_with_any_claim"
        ],
        "may_never_claim": contract["claim_ladder"]["may_never_claim"],
        "no_criterion_was_restated": (
            "The thresholds applied here are read from the contract committed before the "
            "control matrix ran. This module cannot run a simulation and cannot alter a "
            "threshold."
        ),
    }


def summarise_for_console(verdict: dict[str, Any]) -> str:
    """A compact table plus the verdict, for a run log."""
    lines: list[str] = []
    lines.append(
        f"{'variant':22s} {'displ mm':>9s} {'d head deg':>11s} "
        f"{'cue mm':>16s} {'approach':>9s} {'walked':>7s} {'drift mm':>9s}"
    )
    for name, row in verdict["measured"].items():
        lines.append(
            f"{name:22s} {row['displacement_mm']:9.2f} "
            f"{row['net_heading_change_deg']:+11.1f} "
            f"{row['initial_cue_distance_mm']:7.2f}->{row['final_cue_distance_mm']:7.2f} "
            f"{row['approach_mm']:+9.2f} "
            f"{'yes' if row['locomoted'] else 'no':>7s} "
            f"{row['quiescent_displacement_mm']:9.3f}"
        )
    lines.append("")
    for name, row in verdict["criteria"].items():
        mark = "PASS" if row["passed"] else ("n/a " if row.get("optional") else "FAIL")
        detail = ", ".join(
            f"{key}={value}"
            for key, value in row.items()
            if key not in ("passed", "optional")
        )
        lines.append(f"  [{mark}] {name}: {detail}")
    lines.append("")
    lines.append(f"CLAIM: {verdict['claim']}")
    lines.append(f"  {verdict['claim_text']}")
    return "\n".join(lines)


__all__ = [
    "CLAIM_CAUSAL_EMBODIMENT",
    "CLAIM_INVALID",
    "CLAIM_NO_DEMONSTRATION",
    "CLAIM_TOPOLOGY",
    "VariantSummary",
    "evaluate",
    "read_variant",
    "summarise_for_console",
]
