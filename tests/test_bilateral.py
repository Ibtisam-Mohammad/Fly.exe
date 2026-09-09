# SPDX-License-Identifier: GPL-2.0-or-later
"""The bilateral ORN-to-PN symmetry test, and the sign test it is scored with."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from flysim.bilateral import SIDES, _sign_test, measure_projection_neuron
from flysim.convergence import PROJECTION_PATTERN, load_olfactory_populations

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "configs" / "experiments" / "stage2-bilateral-symmetry-v1.json"


class _StubGraph:
    """A tiny graph with known ipsi and contra contact counts."""

    def __init__(self, edges: list[tuple[int, int, int]], neuron_count: int = 12) -> None:
        self.neuron_count = neuron_count
        self.source_indices = np.asarray([edge[0] for edge in edges], dtype=np.int64)
        self.target_indices = np.asarray([edge[1] for edge in edges], dtype=np.int64)
        self.contact_counts = np.asarray([edge[2] for edge in edges], dtype=np.int64)


# --- the sign test ---------------------------------------------------------------------


def test_the_sign_test_matches_the_binomial_by_hand() -> None:
    """Eight of eight in one direction: two-sided p is 2 * 0.5^8."""
    positive, negative, p_value = _sign_test(np.ones(8))

    assert (positive, negative) == (8, 0)
    assert p_value == pytest.approx(2.0 * 0.5**8)


def test_an_even_split_does_not_reject() -> None:
    values = np.asarray([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
    positive, negative, p_value = _sign_test(values)

    assert (positive, negative) == (3, 3)
    assert p_value == pytest.approx(1.0)


def test_ties_are_discarded_rather_than_counted() -> None:
    positive, negative, _ = _sign_test(np.asarray([1.0, 0.0, 0.0, -1.0]))

    assert (positive, negative) == (1, 1)


def test_no_observations_cannot_reject() -> None:
    assert _sign_test(np.zeros(5))[2] == 1.0
    assert _sign_test(np.empty(0))[2] == 1.0


def test_the_sign_test_survives_more_than_a_thousand_observations() -> None:
    """The first implementation divided an exact binomial coefficient by 2.0 ** n and
    raised OverflowError above about a thousand paired observations, which the within-ORN
    version of this comparison exceeds."""
    values = np.concatenate([np.ones(1200), -np.ones(1100)])

    positive, negative, p_value = _sign_test(values)

    assert (positive, negative) == (1200, 1100)
    assert 0.0 <= p_value <= 1.0
    # 1200 of 2300 is a mild excess; it should not be significant.
    assert p_value > 0.01
    # And an extreme split at the same size must underflow to zero rather than overflow.
    assert _sign_test(np.ones(3000))[2] == pytest.approx(0.0, abs=1e-300)


def test_the_sign_test_matches_a_published_critical_value() -> None:
    """Fifteen of eighteen in one direction: two-sided p is 0.0075 to four decimals."""
    values = np.concatenate([np.ones(15), -np.ones(3)])

    assert _sign_test(values)[2] == pytest.approx(0.007538, abs=5e-6)


def test_the_sign_test_is_calibrated_against_the_null() -> None:
    generator = np.random.default_rng(19)
    rejects = 0
    trials = 400
    for _ in range(trials):
        if _sign_test(generator.normal(size=25))[2] < 0.05:
            rejects += 1
    # Binomial(400, 0.05) has SD 4.4; the exact test is conservative, so allow a low tail.
    assert rejects <= 36, f"{rejects} of {trials} rejected at 0.05"


# --- measuring one projection neuron ---------------------------------------------------


def test_ipsilateral_is_the_side_the_neuron_is_on() -> None:
    """Indices 0-1 are left ORNs, 2-3 right ORNs, 10 is the PN."""
    graph = _StubGraph([(0, 10, 40), (1, 10, 60), (2, 10, 10), (3, 10, 30)])
    receptors = {
        "L": np.asarray([0, 1], dtype=np.int64),
        "R": np.asarray([2, 3], dtype=np.int64),
    }

    left = measure_projection_neuron(
        graph=graph,  # type: ignore[arg-type]
        glomerulus="X",
        side="L",
        body_id=999,
        target_index=10,
        receptor_indices=receptors,
    )

    assert left["ipsilateral_mean_contacts_per_pair"] == pytest.approx(50.0)
    assert left["contralateral_mean_contacts_per_pair"] == pytest.approx(20.0)
    assert left["log2_ipsi_over_contra"] == pytest.approx(math.log2(2.5))

    right = measure_projection_neuron(
        graph=graph,  # type: ignore[arg-type]
        glomerulus="X",
        side="R",
        body_id=998,
        target_index=10,
        receptor_indices=receptors,
    )

    # The same graph read from the other side must invert the ratio exactly.
    assert right["log2_ipsi_over_contra"] == pytest.approx(-left["log2_ipsi_over_contra"])


def test_symmetric_input_gives_a_zero_log_ratio() -> None:
    graph = _StubGraph([(0, 10, 40), (1, 10, 60), (2, 10, 60), (3, 10, 40)])
    receptors = {
        "L": np.asarray([0, 1], dtype=np.int64),
        "R": np.asarray([2, 3], dtype=np.int64),
    }

    row = measure_projection_neuron(
        graph=graph,  # type: ignore[arg-type]
        glomerulus="X",
        side="L",
        body_id=1,
        target_index=10,
        receptor_indices=receptors,
    )

    assert row["log2_ipsi_over_contra"] == pytest.approx(0.0)
    assert row["completeness_difference"] == pytest.approx(0.0)


def test_the_statistic_is_per_pair_not_per_total() -> None:
    """A side with more recovered ORNs must not look stronger for that reason alone.

    Right-side ORNs outnumber left-side ones in the graph by 1.52 to 1, which is
    reconstruction rather than biology, so the strength statistic has to divide it out.
    """
    graph = _StubGraph(
        [(0, 10, 50), (2, 10, 50), (3, 10, 50), (4, 10, 50), (5, 10, 50)]
    )
    receptors = {
        "L": np.asarray([0, 1], dtype=np.int64),
        "R": np.asarray([2, 3, 4, 5], dtype=np.int64),
    }

    row = measure_projection_neuron(
        graph=graph,  # type: ignore[arg-type]
        glomerulus="X",
        side="L",
        body_id=1,
        target_index=10,
        receptor_indices=receptors,
    )

    assert row["ipsilateral_total_contacts"] == 50
    assert row["contralateral_total_contacts"] == 200
    # Four times the total, identical per pair: the statistic reports equality.
    assert row["log2_ipsi_over_contra"] == pytest.approx(0.0)
    # And the completeness asymmetry it hides is still recorded.
    assert row["ipsilateral_completeness"] == pytest.approx(0.5)
    assert row["contralateral_completeness"] == pytest.approx(1.0)
    assert row["completeness_difference"] == pytest.approx(-0.5)


def test_a_neuron_with_no_partner_on_one_side_yields_no_ratio() -> None:
    """A ratio needs both terms; the neuron still contributes to the completeness control."""
    graph = _StubGraph([(0, 10, 40)])
    receptors = {
        "L": np.asarray([0], dtype=np.int64),
        "R": np.asarray([2, 3], dtype=np.int64),
    }

    row = measure_projection_neuron(
        graph=graph,  # type: ignore[arg-type]
        glomerulus="X",
        side="L",
        body_id=1,
        target_index=10,
        receptor_indices=receptors,
    )

    assert math.isnan(row["log2_ipsi_over_contra"])
    assert row["completeness_difference"] == pytest.approx(1.0)


# --- the contract ----------------------------------------------------------------------


def test_the_contract_declares_what_it_knew_in_advance(
) -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    known = contract["preregistration"]["known_before_registration"]

    assert known["orn_bodies_by_side"] == {"R": 1343, "L": 883, "unknown": 409}
    assert "1.52" in known["why_this_matters"]
    hypotheses = {item["id"]: item for item in contract["hypotheses"]}
    assert hypotheses["H1"]["blind"] is True
    assert hypotheses["H2"]["blind"] is True
    # H3 is informed by the side counts, so it must say so and say it expects to fail.
    assert hypotheses["H3"]["blind"] is False
    assert "expecting to fail" in hypotheses["H3"]["not_blind_disclosure"]


def test_h2_decides_what_h1_means_rather_than_whether_it_passed(
) -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    h2 = next(item for item in contract["hypotheses"] if item["id"] == "H2")

    assert "opposite signs" in h2["criterion"]
    assert "withdrawn" in h2["criterion"]
    assert "cannot be satisfied by a degenerate outcome" in h2["why_this_control"]


def test_h1_is_two_sided(
) -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    h1 = next(item for item in contract["hypotheses"] if item["id"] == "H1")

    assert "neither is assumed" in h1["two_sided"]


# --- the correction to the pooled loader ------------------------------------------------


def test_the_pooled_loader_no_longer_claims_sides_are_unavailable() -> None:
    """It said so on the strength of somaSide alone, which was too strong."""
    assert load_olfactory_populations.__doc__ is not None
    documentation = load_olfactory_populations.__doc__

    assert "too strong" in documentation
    assert "rootSide" in documentation
    assert SIDES == ("L", "R")
    # The projection pattern is shared, so the two tests select the same PN types.
    assert PROJECTION_PATTERN.match("DL5_adPN") is not None
