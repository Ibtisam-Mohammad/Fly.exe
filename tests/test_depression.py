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
    assert contract["values_opened"] is False


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
