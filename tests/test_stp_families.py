# SPDX-License-Identifier: GPL-2.0-or-later
"""The candidate plasticity families, their protocol simulation and the hand-rolled fitter.

Nothing here reads a data file. The families are checked against closed forms derived by
hand, the chi-square tail against published critical values, the optimiser against
problems with known answers, and the structural ceilings against the numbers the
contract states them to be — because those ceilings are what excludes two of the
candidates, so they have to be true and not merely asserted.
"""

import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from flysim.errors import ConfigurationError
from flysim.stp_families import (
    FAMILIES,
    KAZAMA_WILSON_RELEASE_PROBABILITY,
    NAGEL_RECOVERY_TAU_MS,
    NAGEL_UTILISATION,
    PAIR_PERIOD_MS,
    PAIRS_AVERAGED,
    PARALLEL_SHARE,
    PINNED_FAST_TAU_MS,
    PINNED_RECOVERY_TAU_MS,
    SELECTION_ORDER,
    Observation,
    amplitudes,
    chi_square_upper_tail,
    effective_first_pulse_utilisation,
    family,
    fit_family,
    heterogeneous_paired_pulse_ratio,
    leave_one_out,
    maximum_single_pool_release_probability,
    nelder_mead,
    paired_pulse,
    predict,
    single_pool_paired_pulse_ceiling,
    synthetic_recovery,
    weighted_sse,
)

REPO = Path(__file__).resolve().parents[1]
INTERVALS = (10.0, 30.0, 100.0, 300.0, 1000.0)


def test_the_family_list_and_the_selection_order_agree() -> None:
    assert set(SELECTION_ORDER) == set(FAMILIES)
    assert len(SELECTION_ORDER) == len(FAMILIES)


def test_the_contract_and_the_module_carry_the_same_family_list() -> None:
    contract = json.loads(
        (REPO / "configs/experiments/stage2-stp-family-selection-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert tuple(contract["families_considered"]) == SELECTION_ORDER
    declared = {entry["family_id"]: entry["parameters"] for entry in contract["families"]}
    assert declared == {
        family_id: FAMILIES[family_id].parameter_count for family_id in SELECTION_ORDER
    }


def test_an_unknown_family_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Unknown short-term-plasticity family"):
        family("wishful-thinking")


def test_the_wrong_number_of_parameters_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="takes 2 parameters"):
        amplitudes("depression-only", (0.2,), (0.0, 100.0))


def test_depression_only_reproduces_the_registered_closed_form() -> None:
    """M0's from-rest paired-pulse ratio must be 1 - U exp(-dt/tau), exactly."""
    for utilisation, tau in ((0.22, 893.0), (0.5, 100.0), (0.09, 629.0)):
        for interval in INTERVALS:
            expected = 1.0 - utilisation * math.exp(-interval / tau)
            assert paired_pulse(
                "depression-only", (utilisation, tau), interval, from_rest=True
            ) == pytest.approx(expected, rel=1e-12)


def test_depression_only_cannot_exceed_one_or_decrease_with_interval() -> None:
    """The two structural properties whose violation refuted ND-06 v0.1."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        utilisation = float(rng.uniform(0.01, 1.0))
        tau = float(rng.uniform(20.0, 5000.0))
        curve = [
            paired_pulse("depression-only", (utilisation, tau), interval, from_rest=True)
            for interval in INTERVALS
        ]
        assert max(curve) <= 1.0
        assert all(later >= earlier for earlier, later in pairwise(curve))


def test_facilitation_depression_matches_the_closed_form_derived_by_hand() -> None:
    """M1's from-rest ratio is (1 + phi exp(-dt/tf)) (1 - v exp(-dt/td)).

    With ``v = F + (1 - F) U`` the effective first-pulse utilisation and
    ``phi = F (1 - v) / v`` the facilitation factor. The derivation is what makes the
    four fitted parameters a bijection with the four quantities the observable can see,
    so it is checked rather than trusted.
    """
    for resting, increment, fast, slow in (
        (0.20, 0.30, 40.0, 900.0),
        (0.05, 0.10, 25.0, 2000.0),
        (0.60, 0.05, 90.0, 300.0),
    ):
        effective = increment + (1.0 - increment) * resting
        factor = increment * (1.0 - effective) / effective
        for interval in INTERVALS:
            expected = (1.0 + factor * math.exp(-interval / fast)) * (
                1.0 - effective * math.exp(-interval / slow)
            )
            assert paired_pulse(
                "facilitation-depression",
                (resting, increment, fast, slow),
                interval,
                from_rest=True,
            ) == pytest.approx(expected, rel=1e-12)


def test_the_classic_form_is_capped_at_one_and_a_half() -> None:
    """M1b's ceiling is what excludes it, so the ceiling must be real."""
    assert FAMILIES["facilitation-depression-classic"].paired_pulse_ceiling == 1.5
    rng = np.random.default_rng(11)
    best = 0.0
    for _ in range(400):
        theta = (
            float(rng.uniform(0.001, 0.999)),
            float(rng.uniform(1.0, 1000.0)),
            float(rng.uniform(10.0, 20000.0)),
        )
        for interval in (0.5, 1.0, 5.0, 10.0):
            best = max(
                best,
                paired_pulse(
                    "facilitation-depression-classic", theta, interval, from_rest=True
                ),
            )
    assert best < 1.5
    assert best > 1.4


def test_the_pinned_published_family_is_capped_below_the_measured_ten_millisecond_mean() -> None:
    """M3's ceiling of 1.388 is what excludes it, against a measured 1.5139."""
    ceiling = FAMILIES["pinned-published-depression"].paired_pulse_ceiling
    assert ceiling is not None
    expected = (1.0 + (1.0 - NAGEL_UTILISATION)) * (1.0 - NAGEL_UTILISATION)
    assert ceiling == pytest.approx(expected, abs=5e-4)
    rng = np.random.default_rng(13)
    best = 0.0
    for _ in range(400):
        theta = (float(rng.uniform(0.0, 0.219)), float(rng.uniform(1.0, 1000.0)))
        for interval in (0.5, 1.0, 5.0, 10.0):
            best = max(
                best,
                paired_pulse("pinned-published-depression", theta, interval, from_rest=True),
            )
    assert best < expected
    assert best < 1.5139


def test_the_pinned_family_keeps_the_published_first_pulse_utilisation() -> None:
    """M3 must really be 'the published depression leg, plus facilitation'."""
    for increment in (0.0, 0.05, 0.1, 0.2):
        # The first response consumes the pinned utilisation whatever the increment is,
        # so the resting amplitude is 0.22 and the resource left behind is 0.78.
        values = amplitudes("pinned-published-depression", (increment, 50.0), (0.0,))
        assert float(values[0]) == pytest.approx(NAGEL_UTILISATION, abs=1e-9)
    for increment in (0.0, 0.1, 0.2):
        # Once the facilitation has decayed away the ratio must be the published rule's,
        # unchanged: 1 - 0.22 exp(-dt/893).
        ratio = paired_pulse(
            "pinned-published-depression", (increment, 1.0), 400.0, from_rest=True
        )
        expected = 1.0 - NAGEL_UTILISATION * math.exp(-400.0 / NAGEL_RECOVERY_TAU_MS)
        assert ratio == pytest.approx(expected, rel=1e-6)
    assert NAGEL_RECOVERY_TAU_MS == 893.0


def test_parallel_components_match_their_closed_form() -> None:
    """M2's from-rest ratio is share (1 + step e^-t/tf) + (1 - share) (1 - U e^-t/td)."""
    for step, fast, utilisation, slow in ((1.0, 30.0, 0.3, 2000.0), (0.4, 60.0, 0.1, 800.0)):
        for interval in INTERVALS:
            expected = PARALLEL_SHARE * (1.0 + step * math.exp(-interval / fast)) + (
                1.0 - PARALLEL_SHARE
            ) * (1.0 - utilisation * math.exp(-interval / slow))
            assert paired_pulse(
                "parallel-release-components",
                (step, fast, utilisation, slow),
                interval,
                from_rest=True,
            ) == pytest.approx(expected, rel=1e-12)


def test_two_timescale_facilitation_matches_its_closed_form() -> None:
    """M4's from-rest ratio is (1 + a1 e^-t/t1 + a2 e^-t/t2)(1 - U e^-t/pinned)."""
    theta = (2.4, 0.34, 115.0, 0.10)
    for interval in INTERVALS:
        facilitation = (
            1.0
            + theta[0] * math.exp(-interval / PINNED_FAST_TAU_MS)
            + theta[1] * math.exp(-interval / theta[2])
        )
        depression = 1.0 - theta[3] * math.exp(-interval / PINNED_RECOVERY_TAU_MS)
        assert paired_pulse(
            "two-timescale-facilitation", theta, interval, from_rest=True
        ) == pytest.approx(facilitation * depression, rel=1e-12)


def test_a_single_facilitation_exponential_cannot_pass_through_the_three_short_means() -> None:
    """The claim that justifies carrying a five-parameter family, checked arithmetically.

    Forcing one exponential above the measured plateau through the 10 ms and 100 ms
    cohort means misses the 30 ms mean by more than three of its standard errors. That
    is a statement about the data, not about any model, so it is checked here against
    the recorded summary rather than asserted in a docstring.
    """
    means = (1.5139, 1.1583, 1.0286, 0.9299, 0.9302)
    deviations = (0.2482, 0.2299, 0.1832, 0.1050, 0.0765)
    animals = (20, 21, 22, 22, 22)
    errors = [dev / math.sqrt(count) for dev, count in zip(deviations, animals, strict=True)]
    plateau = 0.5 * (means[3] + means[4])
    excess = [value - plateau for value in means]
    tau = (INTERVALS[2] - INTERVALS[0]) / math.log(excess[0] / excess[2])
    predicted30 = plateau + excess[0] * math.exp(-(INTERVALS[1] - INTERVALS[0]) / tau)
    assert (predicted30 - means[1]) / errors[1] > 3.0
    # And the two-interval implied constants really do differ by a factor of about four.
    fast = (INTERVALS[1] - INTERVALS[0]) / math.log(excess[0] / excess[1])
    slow = (INTERVALS[2] - INTERVALS[1]) / math.log(excess[1] / excess[2])
    assert 15.0 < fast < 30.0
    assert 70.0 < slow < 100.0


def test_the_protocol_ratio_differs_from_the_from_rest_ratio_where_it_should() -> None:
    """Twenty pairs at 0.2 Hz matter at the long intervals and not at the short ones."""
    theta = (2.4, 0.34, 115.0, 0.10)
    at_ten = paired_pulse("two-timescale-facilitation", theta, 10.0)
    rest_ten = paired_pulse("two-timescale-facilitation", theta, 10.0, from_rest=True)
    at_thousand = paired_pulse("two-timescale-facilitation", theta, 1000.0)
    rest_thousand = paired_pulse("two-timescale-facilitation", theta, 1000.0, from_rest=True)
    assert abs(at_ten - rest_ten) < 0.002
    assert at_thousand - rest_thousand > 0.02


def test_the_protocol_constants_are_the_ones_the_methods_state() -> None:
    assert PAIR_PERIOD_MS == 5000.0
    assert PAIRS_AVERAGED == 20
    # The pinned fast constant must stay at or below the shortest recorded interval.
    # That is the entire justification for pinning it rather than fitting it.
    assert min(INTERVALS) >= PINNED_FAST_TAU_MS


def test_an_interval_longer_than_the_repetition_period_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="does not fit inside"):
        paired_pulse("depression-only", (0.2, 900.0), 6000.0)
    with pytest.raises(ConfigurationError, match="must be positive"):
        paired_pulse("depression-only", (0.2, 900.0), 0.0)


def test_out_of_order_spike_times_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="non-decreasing"):
        amplitudes("depression-only", (0.2, 900.0), (0.0, 50.0, 20.0))
    with pytest.raises(ConfigurationError, match="at least one spike"):
        amplitudes("depression-only", (0.2, 900.0), ())


def test_the_chi_square_tail_matches_published_critical_values() -> None:
    # Upper-tail 0.05 critical values from a standard table.
    for degrees, critical in ((1, 3.841), (2, 5.991), (3, 7.815), (5, 11.070), (10, 18.307)):
        assert chi_square_upper_tail(critical, degrees) == pytest.approx(0.05, abs=5e-4)
    # And the 0.01 column.
    for degrees, critical in ((1, 6.635), (2, 9.210), (3, 11.345)):
        assert chi_square_upper_tail(critical, degrees) == pytest.approx(0.01, abs=5e-4)
    assert chi_square_upper_tail(0.0, 3) == pytest.approx(1.0)


def test_the_chi_square_tail_refuses_impossible_inputs() -> None:
    with pytest.raises(ConfigurationError, match="degree of freedom"):
        chi_square_upper_tail(1.0, 0)
    with pytest.raises(ConfigurationError, match="cannot be negative"):
        chi_square_upper_tail(-1.0, 2)


def test_nelder_mead_finds_the_minimum_of_problems_with_known_answers() -> None:
    quadratic = nelder_mead(
        lambda x: float(np.sum((x - np.array([1.0, -2.0, 3.0])) ** 2)), np.zeros(3)
    )
    assert quadratic[0] == pytest.approx(np.array([1.0, -2.0, 3.0]), abs=1e-6)
    assert quadratic[1] == pytest.approx(0.0, abs=1e-10)
    # Rosenbrock in two dimensions, minimum at (1, 1).
    rosenbrock = nelder_mead(
        lambda x: float((1.0 - x[0]) ** 2 + 100.0 * (x[1] - x[0] ** 2) ** 2),
        np.array([-1.2, 1.0]),
        iterations=20000,
    )
    assert rosenbrock[0] == pytest.approx(np.array([1.0, 1.0]), abs=1e-4)


def test_the_fitter_recovers_parameters_it_generated_itself() -> None:
    """A noiseless round trip: the fitter must find the truth it was given."""
    truth = (0.15, 0.35, 45.0, 1200.0)
    observations = [
        Observation(
            interval_ms=interval,
            mean=paired_pulse("facilitation-depression", truth, interval),
            standard_error=0.02,
            animals=20,
        )
        for interval in INTERVALS
    ]
    fitted = fit_family("facilitation-depression", observations, restarts=24)
    assert fitted.weighted_sse < 1e-6
    assert np.allclose(predict("facilitation-depression", fitted.theta, INTERVALS),
                       [row.mean for row in observations], atol=1e-4)


def test_a_family_cannot_be_fitted_to_fewer_points_than_it_has_parameters() -> None:
    observations = [Observation(10.0, 1.5, 0.05, 20), Observation(30.0, 1.1, 0.05, 20)]
    with pytest.raises(ConfigurationError, match="cannot be fitted"):
        fit_family("two-timescale-facilitation", observations)


def test_a_saturated_fit_reports_no_goodness_of_fit_rather_than_a_misleading_one() -> None:
    """Four points against four parameters leaves nothing to test, and it must say so."""
    observations = [Observation(interval, 1.0, 0.05, 20) for interval in INTERVALS[:4]]
    fitted = fit_family("two-timescale-facilitation", observations, restarts=8)
    assert fitted.degrees_of_freedom == 0
    assert fitted.goodness_of_fit_p is None
    assert fitted.as_dict()["goodness_of_fit_is_undefined"] is True


def test_leave_one_out_declines_to_score_a_family_it_cannot_train() -> None:
    """Three points cannot determine four parameters, and the result must say so."""
    observations = [Observation(interval, 1.0, 0.05, 20) for interval in INTERVALS[:4]]
    result = leave_one_out("two-timescale-facilitation", observations, restarts=4)
    assert result["intervals_scored"] == 0
    assert result["total_weighted_squared_error"] is None
    assert all(row["scored"] is False for row in result["by_interval"])
    assert "cannot determine" in result["by_interval"][0]["why_not"]


def test_the_weighted_residual_is_in_units_of_the_standard_error() -> None:
    observations = [Observation(100.0, 1.0, 0.1, 20)]
    # A prediction one standard error away contributes exactly one.
    theta = (0.5, 20000.0)
    predicted = paired_pulse("depression-only", theta, 100.0)
    shifted = [Observation(100.0, predicted - 0.1, 0.1, 20)]
    assert weighted_sse("depression-only", theta, shifted) == pytest.approx(1.0, rel=1e-6)
    del observations


def test_synthetic_recovery_reports_one_row_per_parameter() -> None:
    truth = (0.2, 900.0)
    observations = [
        Observation(interval, paired_pulse("depression-only", truth, interval), 0.02, 20)
        for interval in INTERVALS
    ]
    summary = synthetic_recovery(
        "depression-only", truth, observations, replicates=8, restarts=4
    )
    assert set(summary["parameters"]) == set(FAMILIES["depression-only"].parameter_names)
    assert summary["replicates"] == 8
    for row in summary["parameters"].values():
        assert row["percentile_5"] <= row["median"] <= row["percentile_95"]

def test_the_free_variant_reduces_to_the_pinned_one_at_the_pinned_value() -> None:
    """M4 and M4f must be the same model when M4f's fast constant is pinned's value."""
    pinned = (2.4, 0.34, 115.0, 0.10)
    free = (2.4, PINNED_FAST_TAU_MS, 0.34, 115.0, 0.10)
    for interval in INTERVALS:
        assert paired_pulse("two-timescale-facilitation", pinned, interval) == pytest.approx(
            paired_pulse("two-timescale-facilitation-free", free, interval), rel=1e-12
        )


def test_the_free_variant_has_one_more_parameter_and_no_goodness_of_fit_on_five_means() -> None:
    assert (
        FAMILIES["two-timescale-facilitation-free"].parameter_count
        == FAMILIES["two-timescale-facilitation"].parameter_count + 1
    )
    observations = [Observation(interval, 1.0, 0.05, 20) for interval in INTERVALS]
    fitted = fit_family("two-timescale-facilitation-free", observations, restarts=6)
    assert fitted.degrees_of_freedom == 0
    assert fitted.goodness_of_fit_p is None


def test_the_parallel_share_is_unidentifiable_from_one_pair_and_nearly_so_from_twenty() -> None:
    """The claim that justifies pinning it, and the limit of that claim.

    For a single pair from rest, dividing the step and the utilisation by their own
    shares leaves the ratio identical: the share is exactly unidentifiable and fitting
    it would be fitting a direction the observable cannot see. Under the recorded
    twenty-pair protocol the invariance is only approximate, because the depressing
    pool's depletion across forty pulses depends on its utilisation nonlinearly and not
    merely on the product of share and utilisation. The residual is small but it is not
    zero, which is exactly why the pinning is put through the E3 sweep rather than
    asserted.
    """
    import flysim.stp_families as module

    baseline_share = module.PARALLEL_SHARE
    step, fast, utilisation, slow = 1.0, 30.0, 0.3, 2000.0
    from_rest = [
        paired_pulse(
            "parallel-release-components", (step, fast, utilisation, slow), interval,
            from_rest=True,
        )
        for interval in INTERVALS
    ]
    protocol = [
        paired_pulse("parallel-release-components", (step, fast, utilisation, slow), interval)
        for interval in INTERVALS
    ]
    worst_protocol = 0.0
    try:
        for share in (0.25, 0.75):
            module.PARALLEL_SHARE = share
            rescaled = (
                step * baseline_share / share,
                fast,
                utilisation * (1.0 - baseline_share) / (1.0 - share),
                slow,
            )
            for interval, expected in zip(INTERVALS, from_rest, strict=True):
                assert paired_pulse(
                    "parallel-release-components", rescaled, interval, from_rest=True
                ) == pytest.approx(expected, rel=1e-9)
            for interval, expected in zip(INTERVALS, protocol, strict=True):
                observed = paired_pulse("parallel-release-components", rescaled, interval)
                worst_protocol = max(worst_protocol, abs(observed - expected))
    finally:
        module.PARALLEL_SHARE = baseline_share
    assert worst_protocol > 0.0
    assert worst_protocol < 0.01


def test_the_first_pulse_utilisation_is_defined_for_every_family() -> None:
    probes = {
        "depression-only": (0.3, 900.0),
        "facilitation-depression": (0.1, 0.2, 40.0, 900.0),
        "facilitation-depression-classic": (0.2, 40.0, 900.0),
        "pinned-published-depression": (0.1, 40.0),
        "parallel-release-components": (1.0, 30.0, 0.3, 900.0),
        "two-timescale-facilitation": (2.4, 0.34, 115.0, 0.1),
        "two-timescale-facilitation-free": (2.4, 6.0, 0.34, 115.0, 0.1),
    }
    assert set(probes) == set(FAMILIES)
    for family_id, theta in probes.items():
        value = effective_first_pulse_utilisation(family_id, theta)
        assert 0.0 < value <= 1.0
    assert effective_first_pulse_utilisation("depression-only", (0.3, 900.0)) == pytest.approx(0.3)
    assert effective_first_pulse_utilisation(
        "pinned-published-depression", (0.1, 40.0)
    ) == pytest.approx(NAGEL_UTILISATION)
    with pytest.raises(ConfigurationError, match="takes 2 parameters"):
        effective_first_pulse_utilisation("depression-only", (0.3,))


def test_the_screens_in_the_module_and_the_contract_agree() -> None:
    from flysim.stp_fit import (
        PINNED_CONSTANTS,
        PINNED_SHIFT_LIMIT,
        REQUIRED_INTERVALS_INSIDE,
    )

    contract = json.loads(
        (REPO / "configs/experiments/stage2-stp-family-selection-v1.json").read_text(
            encoding="utf-8"
        )
    )
    screens = contract["screens"]
    assert str(REQUIRED_INTERVALS_INSIDE) in screens["e1_consistent_with_its_own_training_data"][
        "statement"
    ].replace("five", "5")
    assert screens["e3_no_smuggled_constants"]["limit"] == PINNED_SHIFT_LIMIT
    # Every declared sweep must exist in the module, with the same values, and must
    # contain the value the module actually pins.
    declared = contract["pinned_constant_sensitivity"]["sweeps"]
    flattened = {
        f"{family_id}/{attribute}": values
        for family_id, entries in PINNED_CONSTANTS.items()
        for attribute, values in entries
    }
    assert len(flattened) == len(declared)
    for key, values in declared.items():
        family_id, name = key.rsplit("/", 1)
        matching = [
            entries
            for candidate, entries in flattened.items()
            if candidate.startswith(family_id + "/") and name.lower() in candidate.lower()
        ]
        assert matching, key
        assert list(matching[0]) == list(values), key


def test_the_superseded_screen_is_preserved_and_says_what_it_would_have_decided() -> None:
    """The audit trail that makes the screen revision auditable rather than convenient."""
    contract = json.loads(
        (REPO / "configs/experiments/stage2-stp-family-selection-v1.json").read_text(
            encoding="utf-8"
        )
    )
    superseded = contract["superseded_screens"]
    assert "superseded_text_preserved" in superseded
    preserved = superseded["superseded_text_preserved"]
    assert "recovered when the family is refitted" in (
        preserved["two_identifiability_screen"]["statement"]
    )
    assert preserved["two_identifiability_screen"]["replicates"] == 120
    assert "parallel-release-components" in superseded[
        "what_the_superseded_screen_would_have_decided"
    ]
    assert "holdout has not been opened" in superseded["the_rule_this_does_not_break"]

def test_neither_frozen_family_runs_away_in_a_long_train() -> None:
    """The claim an earlier record got wrong, now computed and pinned.

    Both frozen families carry additive facilitation with no ceiling of its own, and the
    records said they therefore diverge in a long train. They do not: the facilitation
    multiplies a depleting resource, and over 112 pulses at 60 Hz the product peaks near
    1.4 times the first response within the first handful of pulses and falls to a few per
    cent of it by the end. The false claim was asserted from the facilitation term in
    isolation; this test is what should have been run instead.
    """
    frozen = {
        "two-timescale-facilitation-free": (1.36968, 7.73042, 0.33854, 115.01354, 0.10243),
        "facilitation-depression": (0.00687, 0.07402, 31.04546, 20000.0),
    }
    for family_id, theta in frozen.items():
        for hertz, pulses in ((1, 32), (10, 100), (20, 100), (60, 112)):
            interval = 1000.0 / hertz
            values = amplitudes(family_id, theta, [index * interval for index in range(pulses)])
            relative = values / values[0]
            assert relative.max() < 1.6, (family_id, hertz)
            assert relative[-1] < relative.max()
            # The train ends far below where it started: depletion wins outright.
            assert relative[-1] < 0.5, (family_id, hertz)
        # And the 1 Hz steady state, which is what the pinned recovery constant governs.
        slow = amplitudes(family_id, theta, [index * 1000.0 for index in range(32)])
        assert 0.25 < float(slow[-1] / slow[0]) < 0.5


def test_the_single_pool_bound_matches_its_closed_form_and_its_inverse() -> None:
    for probability in (0.05, 0.2, 0.5, 0.79, 1.0):
        for interval, tau in ((10.0, 893.0), (100.0, 20000.0), (0.0, 500.0)):
            ceiling = single_pool_paired_pulse_ceiling(
                release_probability=probability, interval_ms=interval, recovery_tau_ms=tau
            )
            expected = (1.0 - probability * math.exp(-interval / tau)) / probability
            assert ceiling == pytest.approx(expected, rel=1e-12)
            if ceiling <= 0.0:
                # p = 1 at a vanishing interval empties the pool: the ratio is zero and
                # there is nothing to invert. The degenerate corner, not a failure.
                assert probability == pytest.approx(1.0) and interval == 0.0
                continue
            # The inverse must return the probability that makes the bound exactly tight.
            recovered = maximum_single_pool_release_probability(
                paired_pulse_ratio=ceiling, interval_ms=interval, recovery_tau_ms=tau
            )
            assert recovered == pytest.approx(probability, rel=1e-9)


def test_a_high_release_probability_forbids_paired_pulse_facilitation() -> None:
    """The measured release probability and the measured ratio are not both possible.

    At Kazama and Wilson's 0.79 a single homogeneous pool cannot exceed a paired-pulse
    ratio of about 0.28 at 10 ms, whatever facilitation is invoked, against a measured
    1.5139. The bound is generous by construction: it allows the second pulse to release
    with certainty, and it assumes no desensitisation and no change in quantal size.
    """
    ceiling = single_pool_paired_pulse_ceiling(
        release_probability=KAZAMA_WILSON_RELEASE_PROBABILITY,
        interval_ms=10.0,
        recovery_tau_ms=893.0,
    )
    assert ceiling == pytest.approx(0.2770, abs=5e-4)
    assert ceiling < 1.0
    # Even the most generous end of the measured release probability does not help.
    assert (
        single_pool_paired_pulse_ceiling(
            release_probability=0.75, interval_ms=10.0, recovery_tau_ms=893.0
        )
        < 0.35
    )
    # Read the other way: the measured ratio caps the resting probability below one half.
    for ratio, interval in ((1.5139, 10.0), (1.1583, 30.0), (1.0286, 100.0)):
        cap = maximum_single_pool_release_probability(
            paired_pulse_ratio=ratio, interval_ms=interval, recovery_tau_ms=893.0
        )
        assert cap < 0.53
        assert cap < KAZAMA_WILSON_RELEASE_PROBABILITY
    # And the ceiling is monotone decreasing in the release probability, which is why
    # no facilitation mechanism can rescue a high one.
    ceilings = [
        single_pool_paired_pulse_ceiling(
            release_probability=value, interval_ms=10.0, recovery_tau_ms=893.0
        )
        for value in (0.1, 0.2, 0.4, 0.6, 0.79)
    ]
    assert all(later < earlier for earlier, later in pairwise(ceilings))


def test_every_eligible_family_sits_below_that_cap() -> None:
    """The fitted utilisations are consistent with the bound and not with the measurement."""
    cap = maximum_single_pool_release_probability(
        paired_pulse_ratio=1.5139, interval_ms=10.0, recovery_tau_ms=893.0
    )
    fitted = {
        "two-timescale-facilitation-free": 0.1024,
        "facilitation-depression": 0.0804,
        "parallel-release-components": 0.1332,
    }
    for family_id, utilisation in fitted.items():
        assert utilisation < cap, family_id
    assert cap < KAZAMA_WILSON_RELEASE_PROBABILITY


def test_the_bounds_refuse_impossible_inputs() -> None:
    with pytest.raises(ConfigurationError, match="release probability must lie"):
        single_pool_paired_pulse_ceiling(
            release_probability=0.0, interval_ms=10.0, recovery_tau_ms=893.0
        )
    with pytest.raises(ConfigurationError, match="release probability must lie"):
        single_pool_paired_pulse_ceiling(
            release_probability=1.5, interval_ms=10.0, recovery_tau_ms=893.0
        )
    with pytest.raises(ConfigurationError, match="recovery time constant must be positive"):
        single_pool_paired_pulse_ceiling(
            release_probability=0.5, interval_ms=10.0, recovery_tau_ms=0.0
        )
    with pytest.raises(ConfigurationError, match="ratio must be positive"):
        maximum_single_pool_release_probability(
            paired_pulse_ratio=0.0, interval_ms=10.0, recovery_tau_ms=893.0
        )


def test_heterogeneity_makes_paired_pulse_depression_worse_not_better() -> None:
    """The claim I got backwards, killed by a Monte Carlo of the thing itself.

    The argument was: a paired pulse facilitates because the first pulse preferentially
    depletes the high-probability sites, leaving low-probability survivors. The survivors
    do carry the second response and they carry *less* of it, because the sites removed
    were the ones contributing most. Simulated here rather than argued.
    """
    rng = np.random.default_rng(0)
    interval, tau = 10.0, 893.0
    survived = math.exp(-interval / tau)
    for sites in (
        np.full(50, 0.79),
        np.array([0.95] * 25 + [0.63] * 25),
        np.array([1.0] * 25 + [0.58] * 25),
    ):
        mean = float(sites.mean())
        variance = float(sites.var())
        analytic = heterogeneous_paired_pulse_ratio(
            mean_release_probability=mean,
            release_probability_variance=variance,
            interval_ms=interval,
            recovery_tau_ms=tau,
        )
        # Monte Carlo the site-by-site process directly.
        trials = 120_000
        released = rng.random((trials, sites.size)) < sites
        recovered = rng.random((trials, sites.size)) < (1.0 - survived)
        available = ~released | recovered
        second = available & (rng.random((trials, sites.size)) < sites)
        simulated = second.sum(1).mean() / released.sum(1).mean()
        assert simulated == pytest.approx(analytic, abs=3e-3)
        # And the point: never above the homogeneous value at the same mean.
        assert analytic <= 1.0 - survived * mean + 1e-12
        if variance > 0.0:
            assert analytic < 1.0 - survived * mean


def test_the_ceiling_depends_only_on_the_mean_release_probability() -> None:
    """Heterogeneity cannot rescue a high release probability, because the spread cancels."""
    interval, tau = 10.0, 893.0
    reference = single_pool_paired_pulse_ceiling(
        release_probability=KAZAMA_WILSON_RELEASE_PROBABILITY,
        interval_ms=interval,
        recovery_tau_ms=tau,
    )
    rng = np.random.default_rng(3)
    for _ in range(50):
        # Any distribution with the same mean gives the same first response and the same
        # upper bound on the second, so the ceiling cannot move.
        spread = float(rng.uniform(0.0, 0.20))
        sites = np.clip(
            rng.normal(KAZAMA_WILSON_RELEASE_PROBABILITY, spread, 200), 0.001, 1.0
        )
        sites = sites * KAZAMA_WILSON_RELEASE_PROBABILITY / sites.mean()
        survived = math.exp(-interval / tau)
        bound = float(np.mean(1.0 - sites * survived) / np.mean(sites))
        assert bound == pytest.approx(reference, rel=1e-9)
    assert reference < 0.3


def test_the_bound_refuses_impossible_heterogeneous_inputs() -> None:
    with pytest.raises(ConfigurationError, match="mean release probability must lie"):
        heterogeneous_paired_pulse_ratio(
            mean_release_probability=0.0,
            release_probability_variance=0.01,
            interval_ms=10.0,
            recovery_tau_ms=893.0,
        )
    with pytest.raises(ConfigurationError, match="variance cannot be negative"):
        heterogeneous_paired_pulse_ratio(
            mean_release_probability=0.5,
            release_probability_variance=-0.01,
            interval_ms=10.0,
            recovery_tau_ms=893.0,
        )
