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

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from flysim.demo02 import DECODED as DECODED_BY_BEHAVIOUR
from flysim.errors import ConfigurationError, ValidationError

NOT_SCORED = "not_scored"
PASS = "pass"
FAIL = "fail"

VERDICT_NO_DEMONSTRATION = "NO DEMONSTRATION"
VERDICT_INVALID = "INVALID AS A CAUSAL CLAIM"
VERDICT_CAUSAL = "FULL-GRAPH CAUSAL BEHAVIOUR"
VERDICT_CAUSAL_TOPOLOGY = "FULL-GRAPH CAUSAL BEHAVIOUR, TOPOLOGY-SPECIFIC"


def read_variant(directory: Path) -> dict[str, Any]:
    """Load one variant's recording, and refuse an incoherent one.

    Runs write into a fixed directory. The recorder truncates ``trace.jsonl`` the moment
    it opens and ``summary.json`` is replaced only after the run succeeds, so a run that
    crashes or is killed leaves a short or empty trace beside the previous run's summary.
    Nothing detected that pair: the evaluator read whichever rows were present and scored
    them against a summary describing a different execution.
    """
    trace = directory / "trace.jsonl"
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in trace.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = summary.get("intervals")
    if isinstance(expected, int) and len(rows) != expected:
        raise ValidationError(
            f"{directory}: the summary describes {expected} intervals and the trace holds "
            f"{len(rows)} rows. That is a summary from one execution beside a trace from "
            "another; re-run the variant rather than scoring the pair."
        )
    recorded_digest = summary.get("trace_sha256")
    if recorded_digest:
        digest = hashlib.sha256()
        with trace.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != recorded_digest:
            raise ValidationError(
                f"{directory}: trace.jsonl hashes {digest.hexdigest()[:12]} and the "
                f"summary records {str(recorded_digest)[:12]}. The trace has changed "
                "since the run that wrote the summary."
            )
    # Graph-free controls intentionally have no resolved neural populations.  They are
    # still valid body-envelope/replay records and must remain scoreable alongside the
    # neural variants.  Older code indexed this field unconditionally, so the first
    # genuine controller-only run crashed the whole acceptance pass after every GPU run
    # had completed.
    population_summary = summary.get("populations", {})
    readout_sizes = population_summary.get("readout_sizes", {})
    decoded = tuple(readout_sizes)
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


def _spearman(left_values: list[float], right_values: list[float]) -> float:
    """Spearman correlation with average ranks, without a SciPy runtime dependency."""
    if len(left_values) != len(right_values) or len(left_values) < 2:
        raise ValidationError("Spearman comparison needs equal non-trivial sequences")

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=values.__getitem__)
        answer = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            rank = (start + end - 1) / 2.0
            for index in order[start:end]:
                answer[index] = rank
            start = end
        return answer

    left, right = ranks(left_values), ranks(right_values)
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)
    )
    left_ss = sum((x - left_mean) ** 2 for x in left)
    right_ss = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else 0.0


def _raw_spikes_after(variant: dict[str, Any], population: str, start_us: int) -> int:
    return sum(
        int(row.get("readout_raw_counts", {}).get(population, 0))
        for row in variant["rows"]
        if int(row["t_us"]) >= start_us
    )



LEG_CONTACT_PREFIX = "world:leg-contact:"


def _all_legs_released(row: dict[str, Any]) -> bool:
    """True when no tarsus is touching, read from the recorded world quantities."""
    contacts = [
        float(value)
        for name, value in row.get("sensors", {}).items()
        if name.startswith(LEG_CONTACT_PREFIX)
    ]
    return bool(contacts) and not any(contacts)


def _first_decoded_spike_us(variant: dict[str, Any], behaviour: str) -> int | None:
    for row in variant["rows"]:
        counts = row.get("readout_raw_counts", {})
        if sum(int(counts.get(name, 0)) for name in DECODED_BY_BEHAVIOUR[behaviour]) > 0:
            return int(row["t_us"])
    return None


def _first_release_after_us(variant: dict[str, Any], after_us: int) -> int | None:
    """The first interval with every tarsus off the ground at or after a time.

    Deliberately not the recording's ``first_all_legs_released_us``, which is the first
    release of the whole run and lands at 17,500 us: that is the settling chatter measured
    at 5.0 to 5.5 ms, not a takeoff, and scoring E5 against it would compare a spike to a
    bounce that happened seconds earlier.
    """
    for row in variant["rows"]:
        if int(row["t_us"]) >= after_us and _all_legs_released(row):
            return int(row["t_us"])
    return None


def _airborne_displacement_mm(variant: dict[str, Any]) -> float:
    airborne = [row for row in variant["rows"] if _all_legs_released(row)]
    if len(airborne) < 2:
        return 0.0
    first, last = airborne[0]["pose"], airborne[-1]["pose"]
    return math.hypot(last["x_mm"] - first["x_mm"], last["y_mm"] - first["y_mm"])




def _first_decoded_spike_in_window_us(
    variant: dict[str, Any], behaviour: str, window: tuple[int, int]
) -> int | None:
    """First decoded spike inside the scoring window.

    v1 anchored on the first spike of the whole run, which a single stochastic spike at
    90,000 us satisfied 3.4 seconds before the response it was supposed to time.
    """
    for row in variant["rows"]:
        t = int(row["t_us"])
        if not window[0] <= t <= window[1]:
            continue
        counts = row.get("readout_raw_counts", {})
        if sum(int(counts.get(name, 0)) for name in DECODED_BY_BEHAVIOUR[behaviour]) > 0:
            return t
    return None


def _spikes_before_us(variant: dict[str, Any], behaviour: str, start_us: int) -> int:
    """Decoded spikes strictly before a time.

    The signature of a network that fires regardless of the stimulus, which is what a
    specificity clause should be testing.
    """
    total = 0
    for row in variant["rows"]:
        if int(row["t_us"]) >= start_us:
            break
        counts = row.get("readout_raw_counts", {})
        total += sum(
            int(counts.get(name, 0)) for name in DECODED_BY_BEHAVIOUR[behaviour]
        )
    return total


def _spike_window_fractions(
    variant: dict[str, Any], behaviour: str, window: tuple[int, int]
) -> tuple[int, int]:
    """(total decoded spikes, how many fall inside the window)."""
    total = inside = 0
    for row in variant["rows"]:
        counts = row.get("readout_raw_counts", {})
        n = sum(int(counts.get(name, 0)) for name in DECODED_BY_BEHAVIOUR[behaviour])
        total += n
        if window[0] <= int(row["t_us"]) <= window[1]:
            inside += n
    return total, inside



def _named(criteria: dict[str, Any], prefix: str) -> tuple[str, dict[str, Any]]:
    """Find a criterion by its identifier prefix rather than its full name.

    v2 renames E1 to carry its new uprightness clause in the name. Looking criteria up by
    full string would make a contract unscoreable the moment its wording improves, and
    would do it with a KeyError rather than a verdict.
    """
    for name, spec in criteria.items():
        if name.startswith(prefix):
            return name, spec
    raise ConfigurationError(
        f"No criterion beginning {prefix!r} in this contract; it has "
        f"{sorted(criteria)}."
    )


def _attitude(variant: dict[str, Any]) -> dict[str, Any]:
    """Body roll over the run, so an inverted fly cannot be read as an airborne one.

    The airborne test everywhere in this pipeline is "no tarsus touching", and a fly lying
    on its back satisfies it perfectly. The exact escape run reports 2,216,000 us airborne
    and ends at 179.4 degrees of roll with its thorax BELOW its standing height: it did
    hop, and then it turned over, and the tarsi never came back down. This is recorded
    beside E1 rather than folded into it, because E1 is frozen and says only "lose ground
    contact" and "rise 1.0 mm", both of which are literally true here.
    """
    rolls = [
        abs(math.degrees(float(row.get("sensors", {}).get(
            "world:gravity-in-body-frame:roll", 0.0))))
        for row in variant["rows"]
    ]
    if not rolls:
        return {}
    return {
        "max_abs_roll_deg": max(rolls),
        "final_abs_roll_deg": rolls[-1],
        "inverted_at_end": rolls[-1] > 90.0,
        "ever_inverted": max(rolls) > 90.0,
        "why_this_is_recorded": (
            "An inverted fly has no tarsus touching and is scored airborne by every "
            "airborne test here, including E1's."
        ),
    }


def _provenance(
    contract: dict[str, Any], variants: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """What produced this verdict, per variant, and whether the matrix hangs together.

    A verdict used to record only the names of the variants it scored. It did not record
    which commit each was run at, which seed, whether the worktree was clean, or whether
    the contract's required controls were present at all. A matrix assembled from four
    commits over two days, missing two of the controls its own contract names, therefore
    produced a verdict that looked exactly like a clean one.
    """
    per: dict[str, Any] = {}
    for name, variant in sorted(variants.items()):
        summary = variant["summary"]
        per[name] = {
            "code_commit": summary.get("code_commit"),
            "worktree_dirty": summary.get("worktree_dirty"),
            "seed": summary.get("seed"),
            "experiment_id": summary.get("experiment_id"),
            "experiment_sha256": summary.get("experiment_sha256"),
            "build_key": summary.get("build_key"),
            "wiring_sha256_12": summary.get("wiring_sha256_12"),
            "compiled_kernel": (summary.get("compiled_kernel") or {}).get("sha256"),
            "intervals": summary.get("intervals"),
            "trace_sha256": summary.get("trace_sha256"),
            "directory": variant.get("directory"),
        }
    commits = {v["code_commit"] for v in per.values() if v["code_commit"]}
    seeds = {v["seed"] for v in per.values() if v["seed"] is not None}
    hashes = {v["experiment_sha256"] for v in per.values() if v["experiment_sha256"]}
    declared = list(contract.get("control_variants", []))
    required = list(contract.get("required_controls", declared))
    absent = [name for name in required if name not in variants]
    faults: list[str] = []
    if len(commits) > 1:
        joined = ", ".join(sorted(c[:8] for c in commits))
        faults.append(
            f"the variants were run at {len(commits)} different commits ({joined}), so "
            "they do not describe one version of the code"
        )
    if len(seeds) > 1:
        faults.append(
            f"the variants carry different seeds ({sorted(seeds)}), so they are not one "
            "matrix"
        )
    if len(hashes) > 1:
        faults.append("the variants were run against different versions of the contract")
    if any(v["worktree_dirty"] for v in per.values()):
        faults.append("at least one variant was run from a dirty worktree")
    if absent:
        faults.append(
            "the contract requires controls that were not recorded: " + ", ".join(absent)
        )
    return {
        "per_variant": per,
        "required_controls": required,
        "required_controls_missing": absent,
        "declared_controls_missing": [n for n in declared if n not in variants],
        "code_commits": sorted(commits),
        "seeds": sorted(seeds),
        "chain_faults": faults,
        "chain_is_sound": not faults,
    }


def evaluate(
    *, behaviour: str, contract: dict[str, Any], variants: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Apply the frozen contract. Missing variants make criteria not_scored, never passed."""
    criteria = contract["acceptance_criteria"]
    exact = variants.get("exact")
    results: dict[str, dict[str, Any]] = {}
    provenance = _provenance(contract, variants)

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
            "tier": "V0 Structural, unchanged. This is engineering acceptance, not evidence.",
            "variants_recorded": sorted(variants),
            "provenance": provenance,
            "why_no_verdict": (
                "The exact run is not among the recorded variants, so there is nothing to "
                "score the controls against."
            ),
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
        e1_name, spec = _named(criteria, "E1")
        airborne = int(exact["takeoff"].get("longest_airborne_us", 0))
        rise = float(exact["takeoff"].get("z_rise_mm", 0.0))
        ok = airborne >= int(spec["min_airborne_us"]) and rise >= float(
            spec["min_z_rise_mm"]
        )
        attitude = _attitude(exact)
        # v2 adds an uprightness clause. v1 has no max_abs_roll_deg key, so this is a
        # no-op there and the v1 verdict is untouched by anything in this function.
        roll_cap = spec.get("max_abs_roll_deg")
        if roll_cap is not None:
            ok = ok and attitude.get("max_abs_roll_deg", 0.0) < float(roll_cap)
        note = ""
        if attitude.get("inverted_at_end"):
            note = (
                f" -- the body ends at {attitude['final_abs_roll_deg']:.1f} degrees of "
                "roll, so it is inverted and the airborne count includes time spent lying "
                "on its back."
            ) + (
                " This contract's roll clause catches it."
                if roll_cap is not None
                else " This contract has no roll clause, so both clauses are literally "
                     "satisfied; disclosed, not rescored."
            )
        results[e1_name] = _criterion(
            PASS if ok else FAIL,
            (
                f"airborne {airborne} us against {spec['min_airborne_us']}, "
                f"z rise {rise:.3f} mm against {spec['min_z_rise_mm']}{note}"
            ),
            longest_airborne_us=airborne,
            z_rise_mm=rise,
            reached_acting=exact["reached_acting"],
            body_attitude=attitude,
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

    # --- feeding-only controls and mapping checks -------------------------------
    if behaviour == "feeding":
        if "F4_it_is_taste_and_not_touch" in criteria:
            contact = variants.get("contact-without-sucrose")
            if contact is None:
                results["F4_it_is_taste_and_not_touch"] = _criterion(
                    NOT_SCORED, "variants not recorded: contact-without-sucrose"
                )
            else:
                passive_limit = float(
                    criteria["F2_the_readout_causes_it"].get(
                        "max_ablated_achieved_rad", 0.05
                    )
                )
                achieved = float(contact["peak_proboscis_rad"])
                acted = bool(contact["reached_acting"])
                results["F4_it_is_taste_and_not_touch"] = _criterion(
                    PASS if not acted and achieved <= passive_limit else FAIL,
                    (
                        f"contact-without-sucrose reached ACTING: {acted}; achieved "
                        f"{achieved:.4f} rad against the passive limit {passive_limit}"
                    ),
                    reached_acting=acted,
                    peak_achieved_rad=achieved,
                    passive_limit_rad=passive_limit,
                )

        if "F6_the_pump_is_recorded_and_was_not_decoded" in criteria:
            expected_decoded = tuple(contract.get("readout", {}).get("decoded", ()))
            recorded_only = tuple(
                contract.get("readout", {})
                .get("recorded_and_never_decoded", {})
                .keys()
            )
            named = tuple(exact["summary"].get("decoded_population_names", ()))
            neural_variants = [
                value
                for value in variants.values()
                if value["summary"].get("graph", {}).get("attached", True)
            ]
            rows_complete = bool(neural_variants) and all(
                all(
                    set(row.get("readout_raw_counts", {})).issuperset(
                        (*expected_decoded, *recorded_only)
                    )
                    for row in value["rows"]
                )
                for value in neural_variants
            )
            mapping_ok = named == expected_decoded and not set(named).intersection(
                recorded_only
            )
            results["F6_the_pump_is_recorded_and_was_not_decoded"] = _criterion(
                PASS if mapping_ok and rows_complete else FAIL,
                (
                    f"summary names decoded populations {list(named)} against "
                    f"{list(expected_decoded)}; every neural trace records decoded plus "
                    f"never-decoded pools: {rows_complete}"
                ),
                decoded_population_names=list(named),
                expected_decoded_population_names=list(expected_decoded),
                recorded_only_population_names=list(recorded_only),
                neural_traces_complete=rows_complete,
            )

        concentrations = [
            float(value)
            for value in contract.get("fixed_parameters", {}).get(
                "sucrose_concentrations", ()
            )
        ]
        if concentrations and (
            "F5_the_extension_tracks_the_concentration" in criteria
            or "F7_the_spike_count_is_large_enough_to_rank" in criteria
        ):
            concentration_runs: list[dict[str, Any]] = []
            missing_concentrations: list[float] = []
            for concentration in concentrations:
                key = "exact" if concentration == 1.0 else f"concentration-{concentration:g}"
                condition = variants.get(key)
                if condition is None:
                    missing_concentrations.append(concentration)
                else:
                    concentration_runs.append(condition)
            if missing_concentrations:
                detail = (
                    "concentration conditions not recorded: "
                    + ", ".join(f"{value:g}" for value in missing_concentrations)
                )
                for name in (
                    "F5_the_extension_tracks_the_concentration",
                    "F7_the_spike_count_is_large_enough_to_rank",
                ):
                    if name in criteria:
                        results[name] = _criterion(NOT_SCORED, detail)
            else:
                quiescent_us = int(exact["summary"].get("decoder", {}).get(
                    "quiescent_us", 0
                ))
                spike_counts = [
                    _raw_spikes_after(run, "rostrum-mn9", quiescent_us)
                    for run in concentration_runs
                ]
                peaks = [float(run["peak_proboscis_rad"]) for run in concentration_runs]
                floor = int(
                    criteria["F7_the_spike_count_is_large_enough_to_rank"][
                        "min_raw_spikes_per_epoch"
                    ]
                )
                enough = all(value >= floor for value in spike_counts)
                results["F7_the_spike_count_is_large_enough_to_rank"] = _criterion(
                    PASS if enough else FAIL,
                    f"post-quiescent MN9 spike counts {spike_counts} against floor {floor}",
                    concentrations=concentrations,
                    raw_spikes=spike_counts,
                    minimum_raw_spikes=floor,
                )
                rho = _spearman(concentrations, peaks)
                threshold = float(
                    criteria["F5_the_extension_tracks_the_concentration"][
                        "min_spearman"
                    ]
                )
                if not enough:
                    results["F5_the_extension_tracks_the_concentration"] = _criterion(
                        NOT_SCORED,
                        "F7 failed, so the frozen contract forbids scoring the rank",
                        concentrations=concentrations,
                        peak_achieved_rad=peaks,
                        spearman=rho,
                    )
                else:
                    results["F5_the_extension_tracks_the_concentration"] = _criterion(
                        PASS if rho >= threshold else FAIL,
                        f"peak achieved angles {peaks}; Spearman {rho:.3f} against {threshold}",
                        concentrations=concentrations,
                        peak_achieved_rad=peaks,
                        spearman=rho,
                    )

    # --- escape-only criteria: E4 the loom branch, E5 timing, E6 not a walk --------
    if behaviour == "escape":
        static = variants.get("matched-size-static")
        if static is None:
            results["E4_approach_or_merely_size"] = _criterion(
                NOT_SCORED, "variants not recorded: matched-size-static"
            )
        else:
            fired_static = static["reached_acting"]
            fired_exact = exact["reached_acting"]
            # A declared branch, not a pass or a fail: the contract wrote both outcomes
            # before the run and this only reports which one happened.
            if fired_exact and not fired_static:
                detail = (
                    "fired only in the moving case; the expansion claim is earned and "
                    "the word loom may be used"
                )
                status = PASS
            elif fired_exact and fired_static:
                detail = (
                    "fired in BOTH the moving and the matched-size-static case, so the "
                    "word loom is struck from every artifact and the claim narrows to: a "
                    "visual object of sufficient angular size drives the giant fibre. The "
                    "encoder computes angular size and not expansion rate, so this is the "
                    "outcome the contract predicted."
                )
                status = FAIL
            else:
                detail = "the exact run did not fire, so this branch does not apply"
                status = NOT_SCORED
            results["E4_approach_or_merely_size"] = _criterion(
                status, detail,
                exact_fired=fired_exact, static_fired=fired_static,
                static_onset_us=static["onset_us"], exact_onset_us=exact["onset_us"],
                this_is_a_branch_not_a_gate=True,
            )

        spec5 = criteria["E5_the_timing_is_stimulus_locked"]
        limit_us = int(spec5["max_spike_to_release_us"])
        # The criterion has two clauses and both are scored. The second -- "and must
        # itself fall inside the registered approach window" -- is not decoration. Without
        # it this reported PASS on a giant-fibre spike at 90,000 us, which is inside the
        # decoder's quiescent period and long before the object starts approaching, paired
        # with a "release" 30 ms later that is the 5.0 to 5.5 ms settling chatter. A
        # criterion that asks whether a takeoff is stimulus-locked was being satisfied by
        # two pieces of startup noise.
        approach = (exact["summary"].get("approaching_object") or {})
        coupling = int(exact["summary"].get("coupling_us", 15_000))
        # v2 extends the scoring window at its close by one coupling interval, because the
        # declared sensorimotor delay is one interval: a response to a stimulus peaking at
        # the close cannot be observed before the next interval. v1 has no such key and
        # keeps its original window, so its recorded verdict does not move.
        windowed = (
            "min_fraction_of_spikes_in_window" in spec5
            or "max_fraction_of_spikes_before_window" in spec5
        )
        extend = coupling if windowed else 0
        window = (
            int(approach.get("approach_start_us", 0)),
            int(approach.get("approach_end_us", 0)) + extend,
        )
        spike_us = (
            _first_decoded_spike_in_window_us(exact, behaviour, window)
            if windowed else _first_decoded_spike_us(exact, behaviour)
        )
        release_us = (
            _first_release_after_us(exact, spike_us) if spike_us is not None else None
        )
        in_window = (
            spike_us is not None and window[1] > window[0]
            and window[0] <= spike_us <= window[1]
        )
        gap = (
            release_us - spike_us
            if spike_us is not None and release_us is not None
            else None
        )
        within = gap is not None and gap <= limit_us
        # v2's specificity clause. Moving the anchor off "the first spike of the run"
        # would otherwise let a constantly-firing network pass on one well-timed spike.
        need_fraction = spec5.get("min_fraction_of_spikes_in_window")
        total, inside = _spike_window_fractions(exact, behaviour, window)
        fraction = inside / total if total else 0.0
        max_before = spec5.get("max_fraction_of_spikes_before_window")
        before = _spikes_before_us(exact, behaviour, window[0])
        before_fraction = before / total if total else 0.0
        # Two shapes of specificity clause. v2 asked for a fraction INSIDE the
        # window and that was the wrong test: the object stays at full angular size
        # after the window closes, so the response correctly continues and only 2 of
        # 250 spikes landed inside. What identifies a constantly-firing network is
        # activity BEFORE the stimulus, which is what escape-legs-v1 asks for.
        specific = True
        if need_fraction is not None:
            specific = specific and fraction >= float(need_fraction)
        if max_before is not None:
            specific = specific and before_fraction <= float(max_before)
        results["E5_the_timing_is_stimulus_locked"] = _criterion(
            PASS if (in_window and within and specific) else FAIL,
            (
                f"first giant-fibre spike at {spike_us} us, approach window "
                f"{window[0]}-{window[1]} us, in window: {in_window}; first release after "
                f"it {release_us} us, gap {gap} us against a limit of {limit_us}"
                + (
                    f"; {inside}/{total} spikes in window ({fraction:.3f}) against "
                    f"{need_fraction}"
                    if need_fraction is not None else ""
                )
                + (
                    f"; {before}/{total} spikes before the window "
                    f"({before_fraction:.3f}) against {max_before}"
                    if max_before is not None else ""
                )
            ),
            first_spike_us=spike_us,
            first_release_us=release_us,
            gap_us=gap,
            approach_window_us=list(window),
            spike_inside_approach_window=in_window,
            gap_within_limit=within,
            spikes_in_window=inside,
            spikes_total=total,
            fraction_in_window=fraction,
            specificity_met=specific,
            spikes_before_window=before,
            fraction_before_window=before_fraction,
        )

        spec6 = criteria["E6_it_is_an_escape_and_not_a_walk"]
        max_mm = float(spec6["max_horizontal_displacement_mm"])
        drives = [
            (float(row["command"].get("actuator:forward-drive", 0.0)),
             float(row["command"].get("actuator:yaw-drive", 0.0)))
            for row in exact["rows"]
        ]
        locomotor_zero = all(f == 0.0 and y == 0.0 for f, y in drives)
        travelled = _airborne_displacement_mm(exact)
        results["E6_it_is_an_escape_and_not_a_walk"] = _criterion(
            PASS if locomotor_zero and travelled <= max_mm else FAIL,
            f"locomotor drives identically zero across {len(drives)} intervals: "
            f"{locomotor_zero}; horizontal travel over the airborne window "
            f"{travelled:.3f} mm against {max_mm}",
            locomotor_drives_identically_zero=locomotor_zero,
            airborne_horizontal_mm=travelled,
        )

    # --- E8, escape-legs only: the withheld command is withheld in the recording ----
    if behaviour == "escape" and "E8_the_wing_command_is_actually_withheld" in criteria:
        values = [
            float(row["command"].get("actuator:wing-depression", 0.0))
            for row in exact["rows"]
        ]
        peak = max(values) if values else 0.0
        results["E8_the_wing_command_is_actually_withheld"] = _criterion(
            PASS if peak == 0.0 else FAIL,
            f"peak wing-depression command across {len(values)} intervals: {peak}",
            peak_wing_command=peak,
            intervals=len(values),
        )

    # --- the topology gate, shared in shape --------------------------------------
    gate_name = {
        "grooming": "G7_topology_claim_gate",
        "feeding": "F6_topology_claim_gate",
        "escape": "E7_topology_claim_gate",
    }[behaviour]
    # escape v2 removes the topology gate outright: the degree-preserving shuffle
    # destabilises this network rather than neutralising it (14,025 active neurons per
    # interval against 2,948), so passing or failing it licenses nothing. The variant is
    # still run and recorded, as an observation about the shuffle.
    has_gate = gate_name in criteria
    reason = missing("shuffled-connectome") if has_gate else None
    if not has_gate:
        pass
    elif reason:
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
    elif not provenance["chain_is_sound"]:
        # A matrix that does not describe one commit, one seed and one contract, with
        # every required control present, cannot support a positive claim whatever its
        # criteria say. This sits below the two failure branches and not above them
        # because a broken chain does not rescue a run that already failed.
        verdict = "EVIDENCE CHAIN BROKEN"
    elif failed_required or unscored_required:
        verdict = "INCOMPLETE"
    elif has_gate and results[gate_name]["status"] == PASS:
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
        "provenance": provenance,
        "variants_the_contract_names": list(contract["control_variants"]),
        "claim_ladder": contract["claim_ladder"],
        "may_never_claim": contract["claim_ladder"]["may_never_claim"],
        "declared_limitations": contract[
            "declared_limitations_that_must_travel_with_any_claim"
        ],
        "claim_boundary": contract["claim_boundary"],
        "tier": "V0 Structural, unchanged. This is engineering acceptance, not evidence.",
    }
