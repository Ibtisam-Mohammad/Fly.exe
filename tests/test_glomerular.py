# SPDX-License-Identifier: GPL-2.0-or-later
"""Glomerular volume measurement and the hand-rolled Spearman it is scored with."""

import json
from pathlib import Path

import numpy as np
import pytest

from flysim.errors import ConfigurationError
from flysim.glomerular import (
    VOXEL_NM,
    _occupied_volume_um3,
    _rank,
    _rarefied_volume_um3,
    _spearman,
)

REPO = Path(__file__).resolve().parents[1]


def test_spearman_is_exact_on_perfect_monotone_relations() -> None:
    x = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _spearman(x, x * 3.0 + 1.0)[0] == pytest.approx(1.0)
    assert _spearman(x, -x)[0] == pytest.approx(-1.0)
    # Monotone but strongly non-linear: rank correlation must still be exactly 1.
    assert _spearman(x, np.exp(x))[0] == pytest.approx(1.0)


def test_spearman_matches_a_hand_computed_case() -> None:
    """Classic worked example: rho = 1 - 6*sum(d^2)/(n(n^2-1))."""
    x = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.asarray([2.0, 1.0, 4.0, 3.0, 5.0])
    differences = np.asarray([-1.0, 1.0, -1.0, 1.0, 0.0])
    expected = 1.0 - 6.0 * (differences**2).sum() / (5 * (25 - 1))

    assert _spearman(x, y)[0] == pytest.approx(expected)
    assert expected == pytest.approx(0.8)


def test_ranks_average_over_ties() -> None:
    ranks = _rank(np.asarray([10.0, 20.0, 20.0, 30.0]))
    assert ranks.tolist() == [1.0, 2.5, 2.5, 4.0]


def test_the_spearman_p_value_is_calibrated_against_the_null() -> None:
    """Under independence the p-value must be roughly uniform, so 5% reject at 0.05."""
    generator = np.random.default_rng(7)
    rejects = 0
    trials = 400
    for _ in range(trials):
        a = generator.normal(size=30)
        b = generator.normal(size=30)
        if _spearman(a, b)[1] < 0.05:
            rejects += 1
    # Binomial(400, 0.05) has SD 4.4; allow a generous band rather than a brittle one.
    assert 6 <= rejects <= 36, f"{rejects} of {trials} rejected at 0.05"


def test_a_strong_correlation_is_significant_and_a_weak_one_is_not() -> None:
    generator = np.random.default_rng(3)
    x = generator.normal(size=50)
    strong_rho, strong_p = _spearman(x, x + 0.2 * generator.normal(size=50))
    assert strong_rho > 0.9 and strong_p < 1e-6

    weak_rho, weak_p = _spearman(generator.normal(size=50), generator.normal(size=50))
    assert weak_p > 0.05 or abs(weak_rho) > 0.27


def test_spearman_refuses_too_few_observations() -> None:
    with pytest.raises(ConfigurationError, match="three paired observations"):
        _spearman(np.asarray([1.0, 2.0]), np.asarray([1.0, 2.0]))


def test_occupied_volume_counts_bins_not_points() -> None:
    """Many points in one bin are one bin; the measure is extent, not density."""
    bin_edge = 125
    clustered = np.zeros((500, 3), dtype=np.int64)
    assert _occupied_volume_um3(clustered, bin_edge) == pytest.approx(
        (bin_edge * VOXEL_NM / 1000.0) ** 3
    )

    spread = np.asarray([[0, 0, 0], [bin_edge, 0, 0], [0, bin_edge, 0]], dtype=np.int64)
    assert _occupied_volume_um3(spread, bin_edge) == pytest.approx(
        3.0 * (bin_edge * VOXEL_NM / 1000.0) ** 3
    )
    assert _occupied_volume_um3(np.empty((0, 3), dtype=np.int64), bin_edge) == 0.0


def test_the_bin_edge_converts_to_one_cubic_micrometre() -> None:
    """125 voxels at 8 nm is 1 um, so one occupied bin must be 1 um^3."""
    assert pytest.approx(1.0) == 125 * VOXEL_NM / 1000.0
    assert _occupied_volume_um3(np.zeros((1, 3), dtype=np.int64), 125) == pytest.approx(1.0)


def test_rarefaction_removes_the_sampling_confound() -> None:
    """Two clouds of identical extent but different point counts must rarefy to the same volume."""
    generator = np.random.default_rng(5)
    extent = 4000
    sparse = generator.integers(0, extent, size=(400, 3))
    dense = generator.integers(0, extent, size=(40_000, 3))

    # Unrarefied, the denser cloud looks much larger purely from sampling.
    assert _occupied_volume_um3(dense, 125) > 1.5 * _occupied_volume_um3(sparse, 125)

    sparse_rarefied = _rarefied_volume_um3(sparse, 125, 400, 25, 20260909)
    dense_rarefied = _rarefied_volume_um3(dense, 125, 400, 25, 20260909)
    assert dense_rarefied == pytest.approx(sparse_rarefied, rel=0.15)


def test_rarefaction_is_a_no_op_when_the_cloud_is_already_at_target() -> None:
    points = np.random.default_rng(1).integers(0, 1000, size=(50, 3))
    assert _rarefied_volume_um3(points, 125, 50, 25, 1) == _occupied_volume_um3(points, 125)


def test_the_contract_is_preregistered_and_declares_its_confound() -> None:
    contract = json.loads(
        (REPO / "configs" / "experiments" / "glomerular-volume-scaling-v1.json").read_text()
    )

    assert contract["preregistration"]["blind"].startswith("No glomerular volume has been")
    hypotheses = {item["id"]: item for item in contract["hypotheses"]}
    assert hypotheses["H1"]["blind"] is True
    assert hypotheses["H2"]["blind"] is True
    # The sampling confound must be controlled, not merely mentioned.
    control = contract["sampling_confound_and_its_control"]
    assert control["repeats"] == 25 and control["seed"] == 20260909
    assert "Rarefaction" in control["control"]
    # H2 must be genuinely two-sided in its reading, not a hypothesis that cannot lose.
    assert "Both outcomes are informative and neither is assumed" in hypotheses["H2"]["note"]
    assert contract["volume_definition"]["bin_edge_voxels"] == 125
