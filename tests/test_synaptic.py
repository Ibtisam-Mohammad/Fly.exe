# SPDX-License-Identifier: GPL-2.0-or-later
"""Synaptic-tier structure and waveform analysis."""

import numpy as np
import pytest

from flysim.errors import ConfigurationError
from flysim.synaptic import (
    coefficient_of_variation,
    difference_of_exponentials_kernel,
    epsc_waveform_features,
    olfactory_convergence_profile,
    projection_type_pattern,
    spearman_rho,
)

TRACTS = ("ad", "l", "v", "il", "lv", "vl", "m")


def test_projection_type_pattern_accepts_every_registered_tract() -> None:
    pattern = projection_type_pattern(TRACTS)

    assert pattern.match("DM1_lPN").group("glomerulus") == "DM1"
    assert pattern.match("VC5_lvPN").group("glomerulus") == "VC5"
    assert pattern.match("V_ilPN").group("glomerulus") == "V"
    assert pattern.match("ORN_DM1") is None
    assert pattern.match("DM1_lPN_extra") is None


def test_convergence_profile_counts_only_matching_receptor_neurons() -> None:
    # Two ORN_DM1 cells and one unrelated cell all project onto one DM1_lPN.
    cell_types = ("ORN_DM1", "ORN_DM1", "ORN_DL5", "DM1_lPN")
    sources = np.asarray([0, 1, 2], dtype=np.uint32)
    targets = np.asarray([3, 3, 3], dtype=np.uint32)
    contacts = np.asarray([40, 60, 500], dtype=np.uint32)

    profile = olfactory_convergence_profile(
        sources, targets, contacts, cell_types, tracts=TRACTS
    )

    assert len(profile) == 1
    connection = profile[0]
    assert connection.glomerulus == "DM1"
    assert connection.converging_receptor_neurons == 2
    assert connection.total_contacts == 100
    assert connection.median_contacts == pytest.approx(50.0)
    # The 500-contact DL5 input must not leak into a DM1 profile.
    assert connection.maximum_contacts == 60


def test_a_projection_neuron_with_no_matching_receptor_input_is_omitted() -> None:
    cell_types = ("ORN_DL5", "DM1_lPN")
    profile = olfactory_convergence_profile(
        np.asarray([0], dtype=np.uint32),
        np.asarray([1], dtype=np.uint32),
        np.asarray([10], dtype=np.uint32),
        cell_types,
        tracts=TRACTS,
    )

    assert profile == []


def test_coefficient_of_variation_is_scale_free() -> None:
    values = np.asarray([10.0, 20.0, 30.0, 40.0])

    assert coefficient_of_variation(values) == pytest.approx(
        coefficient_of_variation(values * 7.0)
    )
    assert coefficient_of_variation(np.full(4, 5.0)) == pytest.approx(0.0)


def test_coefficient_of_variation_refuses_a_zero_mean() -> None:
    with pytest.raises(ConfigurationError, match="zero mean"):
        coefficient_of_variation(np.asarray([-1.0, 1.0]))


def test_spearman_matches_a_hand_computed_monotone_case() -> None:
    x = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0])

    assert spearman_rho(x, x**3) == pytest.approx(1.0)
    assert spearman_rho(x, -(x**3)) == pytest.approx(-1.0)


def test_spearman_averages_tied_ranks() -> None:
    # With ties handled correctly these two rankings are identical, so rho is exactly 1.
    x = np.asarray([1.0, 2.0, 2.0, 3.0])
    y = np.asarray([10.0, 20.0, 20.0, 30.0])

    assert spearman_rho(x, y) == pytest.approx(1.0)


def test_spearman_refuses_a_constant_input() -> None:
    with pytest.raises(ConfigurationError, match="constant"):
        spearman_rho(np.asarray([1.0, 2.0, 3.0]), np.full(3, 4.0))


def test_epsc_features_recover_a_synthetic_waveform() -> None:
    time_ms = np.arange(0.0, 200.0, 0.1)
    kernel = difference_of_exponentials_kernel(
        time_ms, onset_ms=50.0, rise_tau_ms=1.0, decay_tau_ms=10.0
    )
    trace = -20.0 * kernel  # inward current on a zero baseline

    features = epsc_waveform_features(time_ms, trace)

    assert features["baseline_pa"] == pytest.approx(0.0)
    assert features["peak_inward_amplitude_pa"] == pytest.approx(20.0)
    assert 50.0 < features["peak_time_ms"] < 56.0
    # A difference of exponentials with a 10 ms decay falls to 1/e in about 10 ms.
    assert 8.0 < features["peak_to_one_over_e_ms"] < 13.0


def test_the_kernel_is_causal_and_unit_peak() -> None:
    time_ms = np.arange(0.0, 200.0, 0.1)

    kernel = difference_of_exponentials_kernel(
        time_ms, onset_ms=47.25, rise_tau_ms=0.75, decay_tau_ms=15.0
    )

    assert np.all(kernel[time_ms < 47.25] == 0.0)
    assert kernel.max() == pytest.approx(1.0)


def test_the_kernel_refuses_a_decay_faster_than_its_rise() -> None:
    with pytest.raises(ConfigurationError, match="decay time constant"):
        difference_of_exponentials_kernel(
            np.arange(0.0, 10.0, 0.1), onset_ms=1.0, rise_tau_ms=5.0, decay_tau_ms=2.0
        )


def _write(path, payload):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sha(path):
    from flysim.datasets import sha256_file

    return sha256_file(path)


def test_the_exit_gate_fails_when_any_leg_fails(tmp_path) -> None:
    from flysim.synaptic import evaluate_stage2_exit_gate

    root = tmp_path / "root"
    good = _write(root / "good.json", {"acceptance": {"pass": True}})
    bad = _write(root / "bad.json", {"gate": {"coverage": 0.0}})
    contract = _write(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "test-exit",
            "provenance": "E",
            "gate_statement": {"source": "test", "text": "t"},
            "legs": [
                {
                    "id": "alpha",
                    "requirement": "r",
                    "artifact": {"path": "good.json", "sha256": _sha(good)},
                    "read": ["acceptance", "pass"],
                    "expect": True,
                    "sufficiency_caveats": [],
                },
                {
                    "id": "beta",
                    "requirement": "r",
                    "artifact": {"path": "bad.json", "sha256": _sha(bad)},
                    "read": ["gate", "coverage"],
                    "expect_at_least": 0.8,
                    "sufficiency_caveats": [],
                },
            ],
            "acceptance": {"partial_pass_is_not_a_pass": "no"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )

    result = evaluate_stage2_exit_gate(contract, root, tmp_path / "out.json")

    assert result["legs_passed"] == ["alpha"]
    assert result["legs_failed"] == ["beta"]
    assert result["acceptance"]["stage2_exit_gate_passed"] is False


def test_the_exit_gate_refuses_a_changed_artifact(tmp_path) -> None:
    import json

    import pytest as _pytest

    from flysim.errors import DatasetError
    from flysim.synaptic import evaluate_stage2_exit_gate

    root = tmp_path / "root"
    artifact = _write(root / "a.json", {"acceptance": {"pass": True}})
    contract = _write(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "test-exit",
            "provenance": "E",
            "gate_statement": {"source": "test", "text": "t"},
            "legs": [
                {
                    "id": "alpha",
                    "requirement": "r",
                    "artifact": {"path": "a.json", "sha256": _sha(artifact)},
                    "read": ["acceptance", "pass"],
                    "expect": True,
                    "sufficiency_caveats": [],
                }
            ],
            "acceptance": {"partial_pass_is_not_a_pass": "no"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )
    artifact.write_text(json.dumps({"acceptance": {"pass": True, "tampered": 1}}), encoding="utf-8")

    with _pytest.raises(DatasetError, match="SHA-256 mismatch"):
        evaluate_stage2_exit_gate(contract, root, tmp_path / "out.json")


def test_a_missing_field_is_an_error_not_a_silent_failure(tmp_path) -> None:
    import pytest as _pytest

    from flysim.errors import DatasetError
    from flysim.synaptic import evaluate_stage2_exit_gate

    root = tmp_path / "root"
    artifact = _write(root / "a.json", {"acceptance": {}})
    contract = _write(
        tmp_path / "contract.json",
        {
            "schema_version": "1.0",
            "experiment_id": "test-exit",
            "provenance": "E",
            "gate_statement": {"source": "test", "text": "t"},
            "legs": [
                {
                    "id": "alpha",
                    "requirement": "r",
                    "artifact": {"path": "a.json", "sha256": _sha(artifact)},
                    "read": ["acceptance", "absent"],
                    "expect": True,
                    "sufficiency_caveats": [],
                }
            ],
            "acceptance": {"partial_pass_is_not_a_pass": "no"},
            "tier_policy": "none",
            "claim_boundary": "none",
        },
    )

    with _pytest.raises(DatasetError, match="no field at"):
        evaluate_stage2_exit_gate(contract, root, tmp_path / "out.json")
