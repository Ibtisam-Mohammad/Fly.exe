# SPDX-License-Identifier: GPL-2.0-or-later
"""The ND-06 predictions, and the discipline around them.

Two things matter here. The closed forms must be right, which is checked against the
registry's own independently recorded numbers rather than against a value computed by the
same code. And the preregistration must be a preregistration: predictions for observables
the model can generate, no observables it cannot, a primary that was committed before the
data was staged, and no threshold that a wide confidence interval could satisfy.
"""

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from flysim.depression import (
    load_published_fits,
    paired_pulse_ratio,
    predict,
    train_resource,
    train_steady_state,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "configs" / "neural" / "short-term-plasticity-v0.1.json"
CONTRACT = REPO / "configs" / "experiments" / "stage2-depression-external-test-v1.json"
RULE = "orn-to-uniglomerular-pn"


@pytest.fixture
def registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture
def contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_the_paired_pulse_form_reproduces_the_registered_prediction(
    registry: dict[str, Any],
) -> None:
    # 0.8033 was written into the registry at commit fb01944 by a different route. If this
    # module disagrees with it, one of the two is wrong and the test says so.
    recorded = registry["rules"][0]["preregistered_prediction"]
    ratio = paired_pulse_ratio(
        utilisation=float(recorded["predicted_at"]["utilisation"]),
        recovery_tau_ms=float(recorded["predicted_at"]["recovery_tau_ms"]),
        interval_ms=float(recorded["predicted_at"]["interstimulus_interval_ms"]),
    )
    assert ratio == pytest.approx(float(recorded["predicted"]), abs=5e-5)


def test_the_steady_state_reproduces_the_registered_values(registry: dict[str, Any]) -> None:
    recorded = registry["rules"][0]["preregistered_prediction"]["steady_state_predictions"]
    assert train_steady_state(
        utilisation=0.22, recovery_tau_ms=893.0, interval_ms=100.0
    ) == pytest.approx(float(recorded["regular_train_10hz_exact"]), abs=5e-5)
    assert train_steady_state(
        utilisation=0.22, recovery_tau_ms=893.0, interval_ms=20.0
    ) == pytest.approx(float(recorded["regular_train_50hz_exact"]), abs=5e-5)


def test_the_recorded_seven_hertz_failure_is_reproducible(registry: dict[str, Any]) -> None:
    external = registry["rules"][0]["external_test"]
    predicted = train_steady_state(
        utilisation=0.22, recovery_tau_ms=893.0, interval_ms=1000.0 / 7.0
    )
    assert predicted == pytest.approx(
        float(external["predicted_steady_state_resource"]), abs=5e-5
    )
    assert external["verdict"].startswith("FAILED")


def test_the_train_recursion_converges_on_its_own_fixed_point() -> None:
    trajectory = train_resource(
        utilisation=0.22, recovery_tau_ms=893.0, interval_ms=50.0, pulses=200
    )
    assert trajectory[0] == 1.0
    assert trajectory[-1] == pytest.approx(
        train_steady_state(utilisation=0.22, recovery_tau_ms=893.0, interval_ms=50.0),
        abs=1e-9,
    )
    # Depression-only: the resource can never increase from pulse to pulse under a train.
    assert all(later <= earlier + 1e-12 for earlier, later in pairwise(trajectory))


def test_the_ratio_cannot_fall_below_one_minus_utilisation() -> None:
    # This is the whole of H2, so it is worth an executable statement rather than prose.
    for interval in (0.001, 1.0, 10.0, 1000.0, 1e6):
        assert paired_pulse_ratio(
            utilisation=0.23, recovery_tau_ms=1006.0, interval_ms=interval
        ) >= 0.77 - 1e-12


def test_the_ratio_rises_with_interval() -> None:
    ratios = [
        paired_pulse_ratio(utilisation=0.22, recovery_tau_ms=893.0, interval_ms=interval)
        for interval in (10.0, 30.0, 100.0, 300.0, 1000.0)
    ]
    assert ratios == sorted(ratios)
    assert ratios[0] < ratios[-1]


def test_impossible_parameters_are_refused() -> None:
    with pytest.raises(ConfigurationError):
        paired_pulse_ratio(utilisation=0.0, recovery_tau_ms=893.0, interval_ms=100.0)
    with pytest.raises(ConfigurationError):
        paired_pulse_ratio(utilisation=1.5, recovery_tau_ms=893.0, interval_ms=100.0)
    with pytest.raises(ConfigurationError):
        paired_pulse_ratio(utilisation=0.22, recovery_tau_ms=0.0, interval_ms=100.0)
    with pytest.raises(ConfigurationError):
        paired_pulse_ratio(utilisation=0.22, recovery_tau_ms=893.0, interval_ms=0.0)
    with pytest.raises(ConfigurationError):
        train_resource(
            utilisation=0.22, recovery_tau_ms=893.0, interval_ms=100.0, pulses=0
        )


def test_the_published_fits_are_pairs_and_the_primary_is_the_registered_one() -> None:
    fits = load_published_fits(REGISTRY, rule_id=RULE)
    assert len(fits) == 3
    primary = [fit for fit in fits if fit.primary]
    assert len(primary) == 1
    assert primary[0].utilisation == 0.22
    assert primary[0].recovery_tau_ms == 893.0
    # The pairs must never be recombined: the fast component's utilisation belongs with
    # its own recovery constant, not with the whole-EPSC one.
    pairs = {(fit.utilisation, fit.recovery_tau_ms) for fit in fits}
    assert pairs == {(0.22, 893.0), (0.23, 1006.0), (0.09, 629.0)}


def test_a_fit_outside_the_registered_range_is_refused(tmp_path: Path) -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["rules"][0]["published_fits"][1]["utilisation"] = 0.5
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="outside the registered range"):
        load_published_fits(path, rule_id=RULE)


def test_two_primaries_are_refused(tmp_path: Path) -> None:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["rules"][0]["published_fits"][1]["primary"] = True
    path = tmp_path / "two-primaries.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Exactly one"):
        load_published_fits(path, rule_id=RULE)


def test_the_band_is_attained_by_published_pairs_only() -> None:
    fits = load_published_fits(REGISTRY, rule_id=RULE)
    predictions = predict(
        fits=fits,
        paired_pulse_intervals_ms=(10.0, 1000.0),
        train_frequencies_hz=(10.0,),
        train_pulses={"10": 100},
    )
    for row in predictions["paired_pulse"]:
        band = row["registered_family_band"]
        attained = set(row["by_published_fit"].values())
        # Every edge of the band is a value some published fit actually produces, rather
        # than a corner of the parameter rectangle that no measurement corresponds to.
        assert band["lowest"] in attained
        assert band["highest"] in attained


def test_the_pairing_makes_no_numerical_difference_for_this_family() -> None:
    # Worth an executable statement because the contract says so and it would be easy to
    # imply the pairing tightens the band. It does not: across the three published fits
    # the utilisation and the recovery constant increase together, so the extreme corners
    # of the rectangle happen to be real pairs. The pairing is kept because a mixed pair
    # describes no measurement and because a later revision need not be co-monotone.
    fits = load_published_fits(REGISTRY, rule_id=RULE)
    utilisations = [fit.utilisation for fit in fits]
    recoveries = [fit.recovery_tau_ms for fit in fits]
    order = sorted(range(len(fits)), key=lambda index: utilisations[index])
    assert [recoveries[index] for index in order] == sorted(recoveries)
    for interval in (10.0, 100.0, 1000.0):
        pair_band = {
            paired_pulse_ratio(
                utilisation=fit.utilisation,
                recovery_tau_ms=fit.recovery_tau_ms,
                interval_ms=interval,
            )
            for fit in fits
        }
        rectangle = {
            paired_pulse_ratio(
                utilisation=utilisation, recovery_tau_ms=recovery, interval_ms=interval
            )
            for utilisation in (min(utilisations), max(utilisations))
            for recovery in (min(recoveries), max(recoveries))
        }
        assert min(pair_band) == pytest.approx(min(rectangle))
        assert max(pair_band) == pytest.approx(max(rectangle))


def test_the_contract_scores_only_observables_the_model_generates(
    contract: dict[str, Any],
) -> None:
    section = contract["the_model_and_what_it_can_generate"]
    excluded = section["observables_the_dataset_supplies_and_the_model_cannot_generate"]
    for observable in (
        "response_latency",
        "latency_jitter",
        "miniature_epsc_amplitude_and_frequency",
        "evoked_amplitude_in_picoamps",
        "bruchpilot_puncta",
    ):
        assert observable in excluded
        assert "not scored" in excluded[observable]
    scored = json.dumps(contract["hypotheses"])
    assert "latency" not in scored.lower() or "no magnitude" in scored
    assert len(section["predicted_observables"]) == 2


def test_the_primary_is_the_wild_type_baseline_and_the_perturbation_is_secondary(
    contract: dict[str, Any],
) -> None:
    hypotheses = {item["id"]: item for item in contract["hypotheses"]}
    assert hypotheses["H1"]["this_is_the_primary"] is True
    assert "control" in contract["data"]["primary_source"]["variables"][0]
    assert all(
        "_control" in name for name in contract["data"]["primary_source"]["variables"]
    )
    assert hypotheses["H5"]["secondary"] is True
    assert "manipulation" in contract["data"]["primary_source"]["why_control_only"]


def test_the_blind_hypotheses_are_blind_by_commit_ordering(contract: dict[str, Any]) -> None:
    why = contract["why_this_exists"]["the_open_prediction"]
    assert "fb01944" in why
    assert "a24249f" in why
    for identifier in ("H1", "H2", "H3", "H4"):
        hypothesis = next(item for item in contract["hypotheses"] if item["id"] == identifier)
        assert hypothesis["blind"] is True


def test_every_interval_test_carries_a_degenerate_outcome_check(
    contract: dict[str, Any],
) -> None:
    # A confidence interval wide enough to contain anything must not count as agreement.
    for identifier in ("H1", "H4"):
        hypothesis = next(item for item in contract["hypotheses"] if item["id"] == identifier)
        assert "degenerate_outcome_check" in hypothesis
        assert "NO VERDICT" in hypothesis["degenerate_outcome_check"] or "half-width" in (
            hypothesis["degenerate_outcome_check"]
        )


def test_the_contract_refuses_to_refit_on_the_outcome(contract: dict[str, Any]) -> None:
    acceptance = contract["acceptance"]
    assert "No parameter is changed on this outcome" in acceptance["no_refitting"]
    assert "training set" in acceptance["no_refitting"]
    assert "never rewritten" in acceptance["no_criterion_may_be_restated"]


def test_the_contract_does_not_claim_to_reinstate_the_synaptic_leg(
    contract: dict[str, Any],
) -> None:
    claim = contract["why_this_exists"]["what_it_is_not"]
    assert "NOT a reinstatement" in claim
    assert "0 of 3" in claim


def test_the_contract_records_that_its_values_are_now_open(contract: dict[str, Any]) -> None:
    # Opened 2026-09-09 in two stages. The flag is what stops a second scoring pass.
    assert contract["values_opened"] is True
    assert contract["status"].startswith("EXECUTED")
    stages = [entry["stage"] for entry in contract["execution_record"]["stages"]]
    assert stages == ["primary", "intervals"]
    counts = [len(entry["variables_opened"]) for entry in contract["execution_record"]["stages"]]
    assert counts == [1, 5]


def test_the_recorded_verdicts_are_the_ones_that_came_out(contract: dict[str, Any]) -> None:
    results = contract["execution_record"]["results"]
    assert results["H1"].startswith("FAILED")
    assert "1.0286" in results["H1"]
    assert "0.8033" in results["H1"]
    assert "not a NO VERDICT" in results["H1"]
    # A pass that the measurement never came near must not be reported as support.
    assert results["H2"].startswith("PASSED, and the pass is uninformative")
    assert results["H3"].startswith("FAILED")
    assert "DECREASE with interval" in results["H3"]
    assert "not scored" in results["H4"]
    assert "not scored" in results["H5"]


def test_the_failure_is_recorded_as_structural_and_not_as_a_parameter_miss(
    contract: dict[str, Any],
) -> None:
    record = contract["execution_record"]
    assert "no parameter setting could" in record["what_this_establishes"]
    assert "refutation of the registered model FAMILY" in record["what_this_establishes"]
    assert "refitting cannot rescue it" in record["what_this_establishes"]
    # And depletion is explicitly not what failed.
    not_established = record["what_this_does_not_establish"]
    assert "does not falsify presynaptic vesicle depletion" in not_established
    assert "MISSING mechanism" in not_established
    assert "0.79" in not_established


def test_nothing_was_refitted(contract: dict[str, Any]) -> None:
    performed = contract["execution_record"]["no_refitting_performed"]
    assert "utilisation stays 0.22" in performed
    assert "recovery time constant stays 893" in performed
    assert "no revision may claim this test as evidence" in performed


def test_the_single_agreement_is_not_banked_as_a_success(contract: dict[str, Any]) -> None:
    note = contract["execution_record"]["the_one_agreement_is_the_least_informative_interval"]
    assert "1000 ms" in note
    assert "asymptotes" in note
    assert "coincidence as a prediction" in note


def test_the_minimal_stimulation_correction_is_recorded_with_its_consequences(
    contract: dict[str, Any],
) -> None:
    correction = contract["post_execution_corrections"][
        "correction_1_the_recordings_are_minimal_stimulation_not_compound"
    ]
    assert "compound evoked responses" in correction["what_was_written"]
    assert "minimal stimulation protocol" in correction["what_the_paper_says"]
    # It cuts both ways and both ways must be recorded.
    assert "loses most of its force" in correction["consequence_for_the_observation_model"]
    assert "MORE attributable to the model" in correction["consequence_for_the_observation_model"]
    assert "extrapolated first response" in correction["consequence_for_the_10_ms_interval"]
    leg = correction["consequence_for_the_retired_synaptic_leg"]
    assert "STAYS RETIRED" in leg
    assert "0 of 3" in leg
    assert "not the unitary WAVEFORMS" in leg


def test_the_orientation_gap_is_admitted_and_closed_from_published_prose(
    contract: dict[str, Any],
) -> None:
    correction = contract["post_execution_corrections"][
        "correction_2_the_orientation_was_never_registered_and_is_now_settled"
    ]
    assert "did not name the orientation" in correction["the_gap"]
    assert "H3 would have passed" in correction["the_gap"]
    assert "FACILITATION" in correction["how_it_is_settled_without_spending_anything"]
    assert "Nothing in the numbers" in correction["what_it_changes"]


def test_the_expected_outcome_is_written_down_before_the_run(contract: dict[str, Any]) -> None:
    expected = contract["expected_outcome_stated_before_the_run"]
    assert "H2 is expected to FAIL" in expected["prediction"]
    # And the joint diagnosis, so that a two-sided failure is not read as noise.
    assert "one-resource collapse" in expected["what_a_joint_outcome_would_mean"]


def test_the_train_normalisation_is_fixed_before_the_values_are_opened(
    contract: dict[str, Any],
) -> None:
    model = contract["observation_model"]
    assert model["assumption_id"] == "VAL-02"
    assert "final ten pulses" in model["train_normalisation_fixed_now"]
    assert "nan_handling_fixed_now" in model


def test_the_bias_account_is_two_directional(contract: dict[str, Any]) -> None:
    model = contract["observation_model"]
    assert "known_biases_and_their_direction" not in model
    biases = model["known_biases_and_why_the_direction_is_not_one_sided"]
    assert "raises a measured ratio" in biases
    assert "desensitisation lowers it" in biases.lower()
    assert "can do either" in biases
    assert "no direction of disagreement is privileged" in biases


def test_the_primary_interval_is_justified_by_overlap_not_by_bias(
    contract: dict[str, Any],
) -> None:
    primary = next(item for item in contract["hypotheses"] if item["id"] == "H1")
    justification = primary["why_100_ms_is_the_primary"]
    assert "Reduced response overlap, not a one-sided bias" in justification
    assert "baseline convention" in justification
    # And the interval was not chosen by this contract at all.
    assert "fb01944" in justification


def test_the_amendment_preserves_the_withdrawn_text_and_changed_no_number(
    contract: dict[str, Any],
) -> None:
    amendment = contract["amendment"]
    assert amendment["values_opened_before_the_amendment"] is False
    assert "cannot be explained by any of them" in amendment["withdrawn_text_preserved"]
    unchanged = amendment["what_did_not_change"]
    assert "No numeric prediction, no criterion and no threshold" in unchanged
    assert "0.7700 is unchanged" in unchanged
    # The floor itself must still be the floor.
    floor = next(item for item in contract["hypotheses"] if item["id"] == "H2")
    assert "0.7700" in floor["statement"]


def test_a_failure_is_scoped_to_the_parameterised_rule_not_to_depletion(
    contract: dict[str, Any],
) -> None:
    meaning = contract["acceptance"]["what_a_failure_would_establish"]
    assert "single-resource depression rule, as parameterised" in meaning
    assert "compound evoked" in meaning
    assert "NOT a falsification of presynaptic vesicle depletion" in meaning
    # The independent support for the depletion form must be named, not merely asserted.
    assert "CV squared" in meaning
    assert "0.79" in meaning


def test_the_joint_diagnosis_is_a_candidate_rather_than_a_conclusion(
    contract: dict[str, Any],
) -> None:
    joint = contract["expected_outcome_stated_before_the_run"][
        "what_a_joint_outcome_would_mean"
    ]
    assert "candidate and not a conclusion" in joint
    assert "saturation at one interval and desensitisation at another" in joint


def test_the_floor_test_admits_which_bias_it_is_immune_to(contract: dict[str, Any]) -> None:
    floor = next(item for item in contract["hypotheses"] if item["id"] == "H2")
    sharpest = floor["why_this_is_the_sharpest_test"]
    assert "What it is not is immune to observation error" in sharpest
    # Saturation cannot push a measurement below a floor; the other two can.
    assert "saturation cannot push a measurement below the floor" in sharpest
    assert "cannot produce a failure of this floor" in floor["confound_disclosed"]


def test_the_registry_records_the_prediction_as_tested_and_failed(
    registry: dict[str, Any],
) -> None:
    rule = registry["rules"][0]
    status = rule["preregistered_prediction"]["status"]
    assert "TESTED AND FAILED" in status
    assert "1.0286" in status
    second = rule["second_external_test"]
    assert second["verdict"].startswith("FAILED at four of five intervals")
    assert "bounded above by 1" in second["why_no_parameter_change_could_fix_it"]
    assert "Presynaptic vesicle depletion" in second["what_it_does_not_refute"]
    assert "No parameter is changed" in second["not_acted_on"]
    assert second["measured"]["100ms"]["mean"] == 1.0286
    assert second["predicted"]["100ms"] == 0.8033


def test_the_registry_admits_two_failed_external_tests(registry: dict[str, Any]) -> None:
    status = registry["validation_status"]
    assert "two independent external tests and passed neither" in status
    assert "16 percentage points" in status
    assert "awards no validation tier" in status
    assert "Nothing is refitted" in status
