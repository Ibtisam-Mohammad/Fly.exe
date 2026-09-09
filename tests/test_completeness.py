# SPDX-License-Identifier: GPL-2.0-or-later
"""The completeness correction, checked against synthetic data whose truth is known.

The whole point of this correction is to recover a quantity that cannot be observed, so
the only honest test is to generate data from the model, hide the truth, and see whether
the estimator finds it. Two of these tests would have caught a sign error in the thinning
inversion, and one checks the claim the sensitivity analysis rests on.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from flysim.completeness import (
    _log_binomial_table,
    correct_glomerulus,
    fit_truncated_negative_binomial,
    recover_survival,
    unthin,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "configs" / "experiments" / "completeness-corrected-contacts-v1.json"


def _simulate(
    *,
    dispersion: float,
    true_mean: float,
    survival: float,
    pairs: int,
    seed: int,
) -> tuple[np.ndarray, int]:
    """Draw true contact counts, thin them, and drop the pairs that vanish."""
    generator = np.random.default_rng(seed)
    q = dispersion / (dispersion + true_mean)
    # numpy's negative_binomial(n, p) counts failures before n successes, with mean
    # n(1-p)/p, so p is q in this parameterisation.
    truth = generator.negative_binomial(dispersion, q, size=pairs)
    truth = truth[truth >= 1]
    observed = generator.binomial(truth, survival)
    return observed[observed >= 1], int(truth.size)


# --- the log-binomial recurrence -------------------------------------------------------


def test_the_log_binomial_table_matches_lgamma() -> None:
    """It replaces lgamma for speed, so it has to agree with it."""
    dispersion = 3.7
    table = _log_binomial_table(dispersion, 40)

    for k in (0, 1, 2, 7, 23, 40):
        expected = (
            math.lgamma(k + dispersion) - math.lgamma(dispersion) - math.lgamma(k + 1.0)
        )
        assert table[k] == pytest.approx(expected, abs=1e-9)


def test_the_table_starts_at_one_contact_worth_of_nothing() -> None:
    assert _log_binomial_table(2.0, 5)[0] == pytest.approx(0.0)


# --- the thinning inversion ------------------------------------------------------------


def test_no_loss_leaves_the_distribution_alone() -> None:
    """At survival 1 the truth and the observation are the same distribution."""
    result = unthin(observed_q=0.3, dispersion=4.0, survival=1.0)

    assert result["true_q"] == pytest.approx(0.3)
    assert result["predicted_completeness"] == pytest.approx(1.0)


def test_heavier_loss_implies_a_larger_truth_and_a_smaller_completeness() -> None:
    mild = unthin(observed_q=0.3, dispersion=4.0, survival=0.8)
    severe = unthin(observed_q=0.3, dispersion=4.0, survival=0.2)

    assert severe["true_untruncated_mean"] > mild["true_untruncated_mean"]
    assert severe["predicted_completeness"] < mild["predicted_completeness"]
    assert 0.0 < severe["predicted_completeness"] < 1.0


def test_recovering_the_survival_rate_inverts_unthinning() -> None:
    """The two inversions are each other's inverse, which pins both sign conventions."""
    for survival in (0.2, 0.42, 0.75):
        for dispersion in (0.5, 4.0):
            forward = unthin(observed_q=0.3, dispersion=dispersion, survival=survival)
            recovered = recover_survival(
                observed_q=0.3,
                dispersion=dispersion,
                completeness=forward["predicted_completeness"],
            )
            assert recovered is not None
            assert recovered == pytest.approx(survival, rel=1e-6)


def test_the_survival_rate_is_not_identifiable_from_a_complete_glomerulus() -> None:
    """A real limit on H2, not a numerical nuisance.

    Pair-level completeness can only inform the per-synapse loss rate through the pairs
    that were lost. When the connection is strong enough that nothing is lost, the
    completeness is 1 to within double precision and carries no information about p at
    all. So the four glomeruli the convergence test found perfectly complete cannot
    contribute to H2 by construction, and the criterion is written to allow for that.
    """
    forward = unthin(observed_q=0.3, dispersion=30.0, survival=0.42)

    assert forward["predicted_completeness"] == pytest.approx(1.0, abs=1e-12)
    assert recover_survival(observed_q=0.3, dispersion=30.0, completeness=1.0) is None
    # And it is unrecoverable from the completeness the forward model itself produced,
    # not merely from a hand-written 1.0.
    assert (
        recover_survival(
            observed_q=0.3,
            dispersion=30.0,
            completeness=forward["predicted_completeness"],
        )
        is None
    )


def test_an_unreachable_completeness_returns_nothing_rather_than_a_number() -> None:
    """A completeness the fitted shape cannot produce is a finding, not an error."""
    assert recover_survival(observed_q=0.3, dispersion=4.0, completeness=1e-9) is None
    assert recover_survival(observed_q=0.3, dispersion=4.0, completeness=0.0) is None


def test_the_inversion_refuses_impossible_inputs() -> None:
    with pytest.raises(ConfigurationError, match="survival probability"):
        unthin(observed_q=0.3, dispersion=1.0, survival=0.0)
    with pytest.raises(ConfigurationError, match="q must lie"):
        unthin(observed_q=1.0, dispersion=1.0, survival=0.5)


# --- recovering a known truth ----------------------------------------------------------


def test_the_fit_recovers_the_observed_distribution_it_was_generated_from() -> None:
    observed, _ = _simulate(
        dispersion=5.0, true_mean=60.0, survival=1.0, pairs=6000, seed=11
    )

    fit = fit_truncated_negative_binomial(observed)

    assert fit["dispersion"] == pytest.approx(5.0, rel=0.35)
    assert fit["observed_untruncated_mean"] == pytest.approx(60.0, rel=0.15)
    assert fit["at_search_boundary"] is False


def test_the_correction_recovers_a_hidden_true_mean() -> None:
    """The estimator is asked for a number it cannot see, from data that lost 58% of it."""
    survival = 0.42
    dispersion, true_mean = 4.0, 50.0
    observed, true_pairs = _simulate(
        dispersion=dispersion,
        true_mean=true_mean,
        survival=survival,
        pairs=8000,
        seed=3,
    )
    truncated_true_q = dispersion / (dispersion + true_mean)
    expected = true_mean / (1.0 - truncated_true_q**dispersion)

    row = correct_glomerulus(
        glomerulus="synthetic",
        contacts=observed,
        possible_pairs=true_pairs,
        survival=survival,
    )

    # The naive statistic is badly wrong in the direction the convergence test predicted.
    assert row["naive_mean_contacts"] < 0.6 * expected
    # Both corrected estimators find it, and they agree with each other.
    assert row["exact_corrected_mean_contacts"] == pytest.approx(expected, rel=0.10)
    assert row["model_corrected_mean_contacts"] == pytest.approx(expected, rel=0.15)
    assert row["estimator_ratio"] == pytest.approx(1.0, rel=0.15)


def test_the_predicted_completeness_matches_the_simulated_one() -> None:
    """This is H1's mechanism: the fit never sees the pair count, so this is out of sample."""
    survival = 0.42
    observed, true_pairs = _simulate(
        dispersion=2.0, true_mean=12.0, survival=survival, pairs=8000, seed=7
    )

    row = correct_glomerulus(
        glomerulus="synthetic",
        contacts=observed,
        possible_pairs=true_pairs,
        survival=survival,
    )

    assert row["predicted_completeness"] == pytest.approx(
        row["measured_completeness"], abs=0.05
    )
    assert row["recovered_survival"] is not None
    assert row["recovered_survival"] == pytest.approx(survival, rel=0.30)


def test_weak_connections_are_what_the_thinning_loses() -> None:
    """The mechanism the correction assumes, stated as a test rather than as prose."""
    survival = 0.42
    strong, strong_pairs = _simulate(
        dispersion=8.0, true_mean=120.0, survival=survival, pairs=4000, seed=5
    )
    weak, weak_pairs = _simulate(
        dispersion=8.0, true_mean=3.0, survival=survival, pairs=4000, seed=5
    )

    assert strong.size / strong_pairs > 0.999
    assert weak.size / weak_pairs < 0.9


# --- the correction's shape ------------------------------------------------------------


def test_the_correction_factor_is_completeness_over_survival() -> None:
    """The identity the whole model-free leg rests on."""
    contacts = np.asarray([10, 20, 30, 40], dtype=np.int64)
    row = correct_glomerulus(
        glomerulus="synthetic", contacts=contacts, possible_pairs=8, survival=0.42
    )

    assert row["measured_completeness"] == pytest.approx(0.5)
    assert row["correction_factor"] == pytest.approx(0.5 / 0.42)
    assert row["exact_corrected_mean_contacts"] == pytest.approx(
        row["naive_mean_contacts"] * row["correction_factor"]
    )
    assert row["exact_corrected_mean_contacts"] == pytest.approx(100.0 / (0.42 * 8))


def test_a_complete_glomerulus_is_corrected_upward_by_exactly_one_over_survival() -> None:
    """Nothing was lost at the pair level, so only the within-pair loss remains."""
    contacts = np.asarray([40, 50, 60, 50], dtype=np.int64)
    row = correct_glomerulus(
        glomerulus="synthetic", contacts=contacts, possible_pairs=4, survival=0.42
    )

    assert row["measured_completeness"] == pytest.approx(1.0)
    assert row["correction_factor"] == pytest.approx(1.0 / 0.42)


def test_a_badly_reconstructed_glomerulus_is_corrected_downward() -> None:
    """The two biases oppose each other, which is the non-obvious part of the identity."""
    contacts = np.asarray([30, 40, 50], dtype=np.int64)
    row = correct_glomerulus(
        glomerulus="synthetic", contacts=contacts, possible_pairs=30, survival=0.42
    )

    assert row["measured_completeness"] == pytest.approx(0.1)
    assert row["correction_factor"] < 1.0
    assert row["exact_corrected_mean_contacts"] < row["naive_mean_contacts"]


def test_rank_correlations_cannot_depend_on_the_survival_rate() -> None:
    """The claim the sensitivity analysis rests on: p is a common rescaling."""
    totals = np.asarray([100.0, 250.0, 90.0, 400.0])
    pairs = np.asarray([10.0, 40.0, 5.0, 50.0])

    low = totals / (0.35 * pairs)
    high = totals / (0.50 * pairs)

    assert np.argsort(low).tolist() == np.argsort(high).tolist()
    assert high == pytest.approx(low * (0.35 / 0.50))


def test_the_correction_refuses_a_denominator_smaller_than_the_numerator() -> None:
    with pytest.raises(ConfigurationError, match="realised pairs out of"):
        correct_glomerulus(
            glomerulus="synthetic",
            contacts=np.asarray([1, 2, 3], dtype=np.int64),
            possible_pairs=2,
            survival=0.42,
        )


def test_the_fit_refuses_an_absent_pair_disguised_as_a_zero() -> None:
    with pytest.raises(ConfigurationError, match="at least one"):
        fit_truncated_negative_binomial(np.asarray([0, 1, 2], dtype=np.int64))


# --- the contract ----------------------------------------------------------------------


def test_the_contract_declares_its_assumptions_and_its_gate() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    hypotheses = {item["id"]: item for item in contract["hypotheses"]}

    assert contract["model"]["p_registered"] == 0.42
    # The three assumptions must be recorded as assumptions, not buried.
    recorded = " ".join(contract["model"]["assumptions_recorded_as_assumptions"])
    assert "One anatomical contact is one vesicular release site" in recorded
    assert "independent across synapses" in recorded
    assert "Complete ORN-to-PN convergence" in recorded
    # H1 gates the rest.
    assert hypotheses["H1"]["blind"] is True
    assert "gate" in hypotheses["H1"]["why_it_matters"].lower()
    # The two informed hypotheses must say so.
    assert hypotheses["H4"]["blind"] is False
    assert hypotheses["H6"]["blind"] is False
    assert "expected to fail" in hypotheses["H6"]["not_blind_disclosure"]


def test_the_contract_registers_a_boundary_guard() -> None:
    """The kernel-family reissue is the reason this criterion has to exist."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    h5 = next(item for item in contract["hypotheses"] if item["id"] == "H5")

    assert "search boundary" in h5["statement"]
    assert "kernel-family" in h5["why_it_matters"]
