# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the DEMO-01 acceptance evaluator.

The evaluator exists to stop a persuasive-looking demonstration from being reported as a
causal one. So the tests that matter are the ones that construct the predecessor's exact
failure mode and check that the verdict refuses it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flysim.demo01_acceptance import (
    CLAIM_CAUSAL_EMBODIMENT,
    CLAIM_INVALID,
    CLAIM_NO_DEMONSTRATION,
    CLAIM_TOPOLOGY,
    VariantSummary,
    evaluate,
    read_variant,
    summarise_for_console,
)
from flysim.errors import ReadinessError

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "configs/experiments/demo01-acceptance-v1.json"


def variant(
    name: str,
    *,
    displacement: float,
    locomoted: bool = True,
    initial: float = 14.0,
    final: float = 8.0,
    locked: bool | None = True,
    mean_difference: float = 1.4,
    mean_bearing: float = 32.0,
    agreement: float | None = 0.8,
    drift: float = 0.05,
    heading: float = 0.5,
) -> VariantSummary:
    return VariantSummary(
        variant=name,
        displacement_mm=displacement,
        net_heading_change_rad=heading,
        initial_cue_distance_mm=initial,
        final_cue_distance_mm=final,
        locomoted=locomoted,
        locomotion_onset_us=540000 if locomoted else None,
        quiescent_displacement_mm=drift,
        cue_locked=locked,
        mean_readout_difference_hz=mean_difference,
        mean_cue_bearing_deg=mean_bearing,
        cue_locked_sign_agreement=agreement,
    )


def judge(**variants: VariantSummary) -> dict:
    return evaluate(contract_path=CONTRACT, variants=variants, quiescent_us=1_500_000)


def _clean_controls() -> dict[str, VariantSummary]:
    return {
        "readout-ablated": variant(
            "readout-ablated",
            displacement=0.4,
            locomoted=False,
            final=14.0,
            locked=None,
            agreement=None,
        ),
        "stimulus-absent": variant(
            "stimulus-absent",
            displacement=0.5,
            locomoted=False,
            final=14.2,
            locked=None,
            agreement=None,
        ),
    }


# ---------------------------------------------------------------------------
# The verdict ladder
# ---------------------------------------------------------------------------


def test_a_working_demonstration_earns_the_causal_claim() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=9.0),
            **_clean_controls(),
            "shuffled-connectome": variant("shuffled-connectome", displacement=8.4),
        }
    )
    assert verdict["claim"] == CLAIM_CAUSAL_EMBODIMENT
    assert verdict["criteria"]["A1_the_fly_starts_still_and_then_moves"]["passed"]
    assert verdict["criteria"]["A2_the_behaviour_is_caused_by_the_neural_readout"]["passed"]
    assert verdict["criteria"]["A3_the_behaviour_requires_the_stimulus"]["passed"]
    assert verdict["criteria"]["A4_the_turn_is_cue_locked"]["passed"]
    # A shuffle that behaved the same denies the stronger claim, which must be visible.
    assert not verdict["criteria"]["A5_topology_claim_gate"]["passed"]


def test_the_predecessors_failure_mode_is_refused() -> None:
    """A brain-independent demonstration walked 100.2 mm with every weight zeroed.

    Encoded here as an ablated variant that still walks as far as the exact run. The
    verdict must call it invalid, not merely note it.
    """
    verdict = judge(
        **{
            "exact": variant("exact", displacement=9.0),
            "readout-ablated": variant("readout-ablated", displacement=8.9),
            "stimulus-absent": variant(
                "stimulus-absent", displacement=0.4, locomoted=False, locked=None
            ),
        }
    )
    assert verdict["claim"] == CLAIM_INVALID
    assert not verdict["criteria"]["A2_the_behaviour_is_caused_by_the_neural_readout"]["passed"]


def test_an_ablated_variant_that_walks_a_little_but_locomotes_still_fails() -> None:
    """The state matters as well as the distance: reaching LOCOMOTING means the decoder
    was driven, which cannot happen if the readout is truly silent."""
    verdict = judge(
        **{
            "exact": variant("exact", displacement=20.0),
            "readout-ablated": variant("readout-ablated", displacement=1.0, locomoted=True),
            "stimulus-absent": variant(
                "stimulus-absent", displacement=0.4, locomoted=False, locked=None
            ),
        }
    )
    assert verdict["criteria"]["A2_the_behaviour_is_caused_by_the_neural_readout"][
        "ablated_displacement_fraction"
    ] == pytest.approx(0.05)
    assert not verdict["criteria"]["A2_the_behaviour_is_caused_by_the_neural_readout"]["passed"]
    assert verdict["claim"] == CLAIM_INVALID


def test_a_fly_that_walks_without_a_cue_fails_the_stimulus_criterion() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=9.0),
            "readout-ablated": variant(
                "readout-ablated", displacement=0.4, locomoted=False, locked=None
            ),
            "stimulus-absent": variant(
                "stimulus-absent", displacement=8.5, locomoted=True, final=8.5
            ),
        }
    )
    assert not verdict["criteria"]["A3_the_behaviour_requires_the_stimulus"]["passed"]
    assert verdict["claim"] == CLAIM_INVALID


def test_a_stimulus_absent_run_that_drifts_toward_the_cue_fails() -> None:
    """Small displacement is not enough if it happens to close the distance."""
    verdict = judge(
        **{
            "exact": variant("exact", displacement=20.0),
            "readout-ablated": variant(
                "readout-ablated", displacement=0.4, locomoted=False, locked=None
            ),
            "stimulus-absent": variant(
                "stimulus-absent", displacement=2.0, locomoted=False, initial=14.0, final=10.0
            ),
        }
    )
    a3 = verdict["criteria"]["A3_the_behaviour_requires_the_stimulus"]
    assert a3["absent_approach_mm"] == pytest.approx(4.0)
    assert not a3["passed"]


def test_a_fly_that_never_moves_is_no_demonstration() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=0.6, locomoted=False),
            **_clean_controls(),
        }
    )
    assert verdict["claim"] == CLAIM_NO_DEMONSTRATION
    assert not verdict["criteria"]["A1_the_fly_starts_still_and_then_moves"]["passed"]


def test_a_readout_that_leans_the_wrong_way_is_refused() -> None:
    """Displacement in a plausible direction can be luck; A4 asks the narrow question.

    The contract compares two means: the readout asymmetry and the cue bearing must share
    a sign over the locomoting intervals.
    """
    verdict = judge(
        **{
            "exact": variant(
                "exact",
                displacement=9.0,
                locked=False,
                mean_difference=-1.4,
                mean_bearing=32.0,
            ),
            **_clean_controls(),
        }
    )
    assert not verdict["criteria"]["A4_the_turn_is_cue_locked"]["passed"]
    assert verdict["claim"] == CLAIM_INVALID


def test_an_absent_locking_state_fails_rather_than_passing_by_default() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=9.0, locked=None, agreement=None),
            **_clean_controls(),
        }
    )
    assert not verdict["criteria"]["A4_the_turn_is_cue_locked"]["passed"]


def test_a4_is_the_contracts_comparison_of_means_not_a_fraction_of_intervals() -> None:
    """The two tests disagree, and the difference is not cosmetic.

    A fly turning toward a cue drives the bearing through zero, where its sign is noise,
    so a per-interval fraction is systematically harsher on an approach than on an
    avoidance. The sweep measured exactly that: 0.854 for avoidance against 0.718 for
    approach at the same gain. The contract compares means, so this does too, and the
    fraction is reported without being scored.
    """
    verdict = judge(
        **{
            "exact": variant(
                "exact",
                displacement=9.0,
                locked=True,
                mean_difference=0.8,
                mean_bearing=21.0,
                agreement=0.42,
            ),
            **_clean_controls(),
        }
    )
    a4 = verdict["criteria"]["A4_the_turn_is_cue_locked"]
    # A fraction below one half does not fail the criterion, because it is not the test.
    assert a4["passed"]
    assert a4["sign_agreement_fraction_reported_not_scored"] == pytest.approx(0.42)
    assert "share a sign" in a4["test"]


def test_a_divergent_shuffle_earns_the_topology_claim() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=12.0),
            **_clean_controls(),
            "shuffled-connectome": variant("shuffled-connectome", displacement=2.0),
        }
    )
    assert verdict["criteria"]["A5_topology_claim_gate"]["passed"]
    assert verdict["claim"] == CLAIM_TOPOLOGY


def test_a_shuffle_that_does_not_walk_at_all_also_earns_it() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=12.0),
            **_clean_controls(),
            "shuffled-connectome": variant(
                "shuffled-connectome", displacement=1.0, locomoted=False
            ),
        }
    )
    assert verdict["criteria"]["A5_topology_claim_gate"]["passed"]


def test_a_missing_shuffle_denies_the_topology_claim_without_failing_the_rest() -> None:
    verdict = judge(
        **{"exact": variant("exact", displacement=9.0), **_clean_controls()}
    )
    assert verdict["claim"] == CLAIM_CAUSAL_EMBODIMENT
    assert not verdict["criteria"]["A5_topology_claim_gate"]["passed"]
    assert verdict["criteria"]["A5_topology_claim_gate"]["shuffled_divergence_mm"] is None


def test_the_required_controls_cannot_be_skipped() -> None:
    with pytest.raises(ReadinessError):
        judge(**{"exact": variant("exact", displacement=9.0)})


# ---------------------------------------------------------------------------
# What travels with the verdict
# ---------------------------------------------------------------------------


def test_every_verdict_carries_the_limitations_and_the_never_claims() -> None:
    verdict = judge(
        **{"exact": variant("exact", displacement=9.0), **_clean_controls()}
    )
    limitations = verdict["limitations_that_travel_with_the_claim"]
    assert "the_retina_is_not_executed" in limitations
    assert "the_locomotor_system_is_engineered" in limitations
    assert "the_turn_direction_is_an_engineering_choice" in limitations
    assert "V0 Structural" in verdict["may_never_claim"]


def test_every_variant_is_reported_even_when_it_fails() -> None:
    verdict = judge(
        **{
            "exact": variant("exact", displacement=9.0),
            "readout-ablated": variant("readout-ablated", displacement=8.9),
            "stimulus-absent": variant(
                "stimulus-absent", displacement=0.4, locomoted=False, locked=None
            ),
        }
    )
    assert set(verdict["measured"]) == {"exact", "readout-ablated", "stimulus-absent"}
    for row in verdict["measured"].values():
        assert "displacement_mm" in row
        assert "quiescent_displacement_mm" in row
        assert "mean_readout_difference_hz" in row


def test_the_console_summary_states_the_claim() -> None:
    verdict = judge(
        **{"exact": variant("exact", displacement=9.0), **_clean_controls()}
    )
    text = summarise_for_console(verdict)
    assert "CLAIM:" in text
    assert CLAIM_CAUSAL_EMBODIMENT in text
    assert "readout-ablated" in text


# ---------------------------------------------------------------------------
# The contract itself
# ---------------------------------------------------------------------------


def test_the_contract_is_committed_and_closed() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["values_opened"] is False
    assert "no_criterion_may_be_restated" in contract
    ladder = contract["claim_ladder"]
    for key in (
        "if_A1_fails",
        "if_A1_passes_and_A2_or_A3_fails",
        "if_A1_to_A4_pass_and_A5_fails",
        "if_A1_to_A5_pass",
        "may_never_claim",
    ):
        assert key in ladder


def test_the_contract_names_the_predecessors_measured_failure() -> None:
    """The contract must say what it is guarding against, with the numbers."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    why = json.dumps(contract["why_this_exists"])
    assert "100.2 mm" in why
    assert "+0.975" in why


def test_no_behavioural_objective_leaked_into_the_operating_point_contract() -> None:
    """The acceptance contract may use behaviour. The operating-point contract may not."""
    search = json.loads(
        (REPO / "configs/experiments/demo01-visual-operating-point-v1.json").read_text(
            encoding="utf-8"
        )
    )
    text = json.dumps(search).lower()
    for word in ("displacement_mm", "approach_success", "distance_to_target"):
        assert word not in text


def test_reading_a_missing_recording_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ReadinessError):
        read_variant(tmp_path / "absent", 1_500_000)
