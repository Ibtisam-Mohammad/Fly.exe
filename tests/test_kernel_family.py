# SPDX-License-Identifier: GPL-2.0-or-later
"""The two-decay uEPSC kernel family, which both source papers describe and the frozen fit lacks."""

import json
from pathlib import Path

import numpy as np
import pytest

from flysim.errors import ConfigurationError
from flysim.synaptic import (
    _kernel_half_decay_ms,
    difference_of_exponentials_kernel,
    fit_difference_of_exponentials_kernel,
    fit_two_component_kernel,
    two_component_kernel,
)

REPO = Path(__file__).resolve().parents[1]
TIME = np.arange(0.0, 300.0, 0.1)


def test_the_two_component_kernel_has_unit_peak_and_is_causal() -> None:
    kernel = two_component_kernel(
        TIME,
        onset_ms=50.0,
        rise_tau_ms=1.0,
        fast_decay_tau_ms=9.3,
        slow_decay_tau_ms=80.0,
        fast_fraction=0.786,
    )

    assert kernel.max() == pytest.approx(1.0)
    assert np.all(kernel[TIME < 50.0] == 0.0)
    assert np.all(kernel >= 0.0)
    # It must decay, not plateau.
    assert kernel[-1] < 0.05


def test_the_two_component_kernel_refuses_incoherent_parameters() -> None:
    base = {
        "onset_ms": 50.0,
        "rise_tau_ms": 1.0,
        "fast_decay_tau_ms": 9.3,
        "slow_decay_tau_ms": 80.0,
        "fast_fraction": 0.786,
    }
    with pytest.raises(ConfigurationError, match="fast_fraction"):
        two_component_kernel(TIME, **{**base, "fast_fraction": 0.0})
    with pytest.raises(ConfigurationError, match="rise time constant must be positive"):
        two_component_kernel(TIME, **{**base, "rise_tau_ms": 0.0})
    with pytest.raises(ConfigurationError, match="fast decay constant must exceed"):
        two_component_kernel(TIME, **{**base, "fast_decay_tau_ms": 0.5})
    with pytest.raises(ConfigurationError, match="slow decay constant must exceed"):
        two_component_kernel(TIME, **{**base, "slow_decay_tau_ms": 5.0})


def test_a_fast_fraction_of_one_reduces_to_the_single_decay_family() -> None:
    """With all weight on the fast component the two families must agree exactly."""
    two = two_component_kernel(
        TIME,
        onset_ms=50.0,
        rise_tau_ms=1.0,
        fast_decay_tau_ms=12.0,
        slow_decay_tau_ms=80.0,
        fast_fraction=1.0,
    )
    one = difference_of_exponentials_kernel(
        TIME, onset_ms=50.0, rise_tau_ms=1.0, decay_tau_ms=12.0
    )

    assert np.allclose(two, one, atol=1e-12)


def test_half_decay_is_measured_from_the_peak() -> None:
    """A pure exponential decay of tau has a half-decay of tau*ln2."""
    kernel = difference_of_exponentials_kernel(
        TIME, onset_ms=50.0, rise_tau_ms=0.05, decay_tau_ms=10.0
    )

    assert _kernel_half_decay_ms(kernel, TIME) == pytest.approx(10.0 * np.log(2.0), abs=0.2)


def test_the_two_component_fit_recovers_a_synthetic_biphasic_population() -> None:
    """A waveform the single-decay family cannot represent must be recovered by the two."""
    truth = two_component_kernel(
        TIME,
        onset_ms=47.5,
        rise_tau_ms=1.0,
        fast_decay_tau_ms=9.3,
        slow_decay_tau_ms=80.0,
        fast_fraction=0.786,
    )
    amplitudes = np.asarray([30.0, 40.0, 50.0])
    rng = np.random.default_rng(11)
    curves = -amplitudes[:, None] * truth[None, :] + rng.normal(0.0, 0.05, (3, TIME.size))

    two = fit_two_component_kernel(TIME, curves)
    one = fit_difference_of_exponentials_kernel(TIME, curves)

    assert two["fast_decay_tau_ms"] == pytest.approx(9.3, abs=2.0)
    assert two["slow_decay_tau_ms"] == pytest.approx(80.0, abs=45.0)
    assert two["population_amplitude_pa"] == pytest.approx(40.0, rel=0.1)
    # The two-decay family must fit a two-decay waveform better than the one-decay family.
    assert two["training_huber_pa2"] < one["training_huber_pa2"]
    # And it must recover the amplitude better than the misspecified family does.
    assert abs(two["population_amplitude_pa"] - 40.0) < abs(
        one["population_amplitude_pa"] - 40.0
    )


def test_the_single_decay_family_underestimates_a_biphasic_peak() -> None:
    """The mechanism behind the recorded amplitude shortfall, isolated on synthetic data."""
    truth = two_component_kernel(
        TIME,
        onset_ms=47.5,
        rise_tau_ms=1.0,
        fast_decay_tau_ms=9.3,
        slow_decay_tau_ms=80.0,
        fast_fraction=0.786,
    )
    curves = -40.0 * truth[None, :]

    one = fit_difference_of_exponentials_kernel(TIME, curves)

    assert one["population_amplitude_pa"] < 40.0
    # The misspecified single decay lands between the true fast and slow constants.
    assert 9.3 < one["decay_tau_ms"] < 80.0


def test_the_contract_declares_itself_not_blind() -> None:
    """It was written after the comparison was explored, and must not read as preregistered."""
    contract = json.loads(
        (REPO / "configs" / "experiments" / "stage2-uepsc-kernel-family-v1.json").read_text()
    )

    assert "not_blind" in json.dumps(contract)
    assert contract["observed_before_registration"]["direct_peak_amplitude_mean_pa"] == 36.61
    for hypothesis in contract["hypotheses"]:
        if hypothesis["id"] in {"H1", "H2", "H3"}:
            assert hypothesis["not_blind"] is True
    # Neither family can be validated here; the boundary must say so.
    assert "awards no validation tier" in contract["claim_boundary"]
    assert "12" in str(contract["recordings"]["cells"]) or contract["recordings"]["cells"] == 12
