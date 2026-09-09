# SPDX-License-Identifier: GPL-2.0-or-later
"""Commit-reveal for a validation seed, and the property it must not overclaim.

MOTOR-04's seed was registered in plaintext, which fixed the validation set in advance
and left the twelve poses drawable by whoever was tuning. A commitment fixes the seed
without publishing it. What it cannot do is make the seed unknown to the party that
generated it, so these tests hold fixation and blinding apart and check that a
single-party commitment cannot report itself as a blind holdout.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from flysim.commit_reveal import (
    BLINDING_SOURCES,
    SeedCommitment,
    commit_seed,
    derive_seed_from_beacon,
    new_nonce,
    verify_seed,
)
from flysim.errors import ConfigurationError
from flysim.station_validation import draw_committed_validation_poses

REPO = Path(__file__).resolve().parents[1]
PROTOCOL = REPO / "configs" / "experiments" / "motor-05-validation-protocol-v1.json"
NONCE = "a" * 64


@pytest.fixture
def protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def _commitment(seed: int = 12345, blinding: str = "none") -> dict[str, Any]:
    return {
        "commitment": commit_seed(seed=seed, nonce_hex=NONCE),
        "blinding": blinding,
        "justification": (
            "The tuning party drew the seed and holds its own nonce, so this fixes the set "
            "and does not blind the tuner."
        ),
        "reveal_trigger": "the MOTOR-05 freeze commit",
    }


def test_a_commitment_is_deterministic_and_hides_the_seed() -> None:
    first = commit_seed(seed=20260910, nonce_hex=NONCE)
    assert first == commit_seed(seed=20260910, nonce_hex=NONCE)
    assert len(first) == 64
    assert str(20260910) not in first
    assert commit_seed(seed=20260911, nonce_hex=NONCE) != first


def test_a_short_nonce_is_refused_because_a_date_shaped_seed_is_guessable() -> None:
    with pytest.raises(ConfigurationError, match="brute-forced"):
        commit_seed(seed=20260910, nonce_hex="abcd")


def test_a_nonce_must_be_lowercase_hexadecimal() -> None:
    with pytest.raises(ConfigurationError, match="hexadecimal"):
        commit_seed(seed=1, nonce_hex="A" * 64)
    with pytest.raises(ConfigurationError, match="hexadecimal"):
        commit_seed(seed=1, nonce_hex="z" * 64)


def test_the_generated_nonce_is_long_enough_to_use() -> None:
    nonce = new_nonce()
    assert len(nonce) == 64
    assert commit_seed(seed=1, nonce_hex=nonce)
    assert new_nonce() != nonce


def test_an_out_of_range_seed_is_refused() -> None:
    with pytest.raises(ConfigurationError, match=r"\[0, 2\*\*64\)"):
        commit_seed(seed=-1, nonce_hex=NONCE)
    with pytest.raises(ConfigurationError, match=r"\[0, 2\*\*64\)"):
        commit_seed(seed=1 << 64, nonce_hex=NONCE)
    with pytest.raises(ConfigurationError, match="must be an integer"):
        commit_seed(seed=True, nonce_hex=NONCE)  # type: ignore[arg-type]


def test_a_matching_reveal_verifies() -> None:
    commitment = commit_seed(seed=777, nonce_hex=NONCE)
    verify_seed(commitment=commitment, seed=777, nonce_hex=NONCE)


def test_a_swapped_seed_is_refused_at_reveal() -> None:
    commitment = commit_seed(seed=777, nonce_hex=NONCE)
    with pytest.raises(ConfigurationError, match="does not match the registered commitment"):
        verify_seed(commitment=commitment, seed=778, nonce_hex=NONCE)


def test_a_swapped_nonce_is_refused_at_reveal() -> None:
    commitment = commit_seed(seed=777, nonce_hex=NONCE)
    with pytest.raises(ConfigurationError, match="does not match"):
        verify_seed(commitment=commitment, seed=777, nonce_hex="b" * 64)


def test_a_malformed_commitment_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="64-character sha256"):
        verify_seed(commitment="not-a-digest", seed=1, nonce_hex=NONCE)


def test_the_beacon_route_is_recheckable_and_needs_no_secret() -> None:
    value = "9f" * 32
    seed = derive_seed_from_beacon(beacon_value_hex=value)
    assert seed == derive_seed_from_beacon(beacon_value_hex=value)
    assert 0 <= seed < 1 << 64
    assert seed != derive_seed_from_beacon(beacon_value_hex="9e" * 32)
    with pytest.raises(ConfigurationError, match="32 lowercase hex"):
        derive_seed_from_beacon(beacon_value_hex="abc")


def test_fixation_and_blinding_are_recorded_separately() -> None:
    single = SeedCommitment.from_contract(_commitment())
    assert single.blinding == "none"
    assert single.establishes_blinding is False
    recorded = single.as_dict()
    assert recorded["establishes_fixation"] is True
    assert recorded["establishes_blinding"] is False
    assert "does not establish" in recorded["blinding_means"]

    blinded = SeedCommitment.from_contract(_commitment(blinding="second-party-secret"))
    assert blinded.establishes_blinding is True
    assert blinded.as_dict()["establishes_fixation"] is True


def test_every_blinding_route_says_what_it_establishes() -> None:
    assert set(BLINDING_SOURCES) == {"public-beacon", "second-party-secret", "none"}
    assert "did not exist" in BLINDING_SOURCES["public-beacon"]
    assert "blind" in BLINDING_SOURCES["second-party-secret"]
    assert "must not be described as a blind holdout" in BLINDING_SOURCES["none"]


def test_an_unknown_blinding_route_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Unknown blinding source"):
        SeedCommitment.from_contract(_commitment(blinding="trust-me"))


def test_a_commitment_must_say_who_held_the_secret() -> None:
    payload = _commitment()
    payload["justification"] = "blind"
    with pytest.raises(ConfigurationError, match="not a protocol"):
        SeedCommitment.from_contract(payload)


def test_a_commitment_must_name_its_reveal_trigger() -> None:
    payload = _commitment()
    payload["reveal_trigger"] = "  "
    with pytest.raises(ConfigurationError, match="triggers the reveal"):
        SeedCommitment.from_contract(payload)


def test_a_committed_draw_verifies_before_it_draws() -> None:
    revealed = draw_committed_validation_poses(
        commitment=_commitment(seed=4242),
        seed=4242,
        nonce_hex=NONCE,
        count=5,
        max_attempts=5,
    )
    assert revealed["seed"] == 4242
    assert len(revealed["poses"]) == 5
    assert revealed["commitment"]["establishes_blinding"] is False
    assert "unseen during tuning only if" in revealed["claim_boundary"]


def test_a_committed_draw_refuses_a_seed_that_was_not_committed() -> None:
    with pytest.raises(ConfigurationError, match="does not match the registered commitment"):
        draw_committed_validation_poses(
            commitment=_commitment(seed=4242),
            seed=9999,
            nonce_hex=NONCE,
            count=5,
            max_attempts=5,
        )


def test_a_committed_draw_still_refuses_the_spent_seed() -> None:
    # Committing a spent seed must not launder it back into use.
    with pytest.raises(ConfigurationError, match="is spent"):
        draw_committed_validation_poses(
            commitment=_commitment(seed=20260910),
            seed=20260910,
            nonce_hex=NONCE,
            count=12,
            max_attempts=40,
        )


def test_the_protocol_ranks_the_routes_and_names_what_each_proves(
    protocol: dict[str, Any],
) -> None:
    routes = {item["id"]: item for item in protocol["seed_sources_in_order_of_strength"]}
    assert list(routes) == ["public-beacon", "second-party-secret", "single-party"]
    assert routes["single-party"]["blinding"] == "none"
    assert "Fixation only" in routes["single-party"]["what_it_establishes"]
    assert "blind holdout" in routes["single-party"]["what_it_must_not_be_called"]
    kept_apart = protocol["two_properties_kept_apart"]
    assert "could not be changed after the freeze" in kept_apart["fixation"]
    assert "did not know the seed while tuning" in kept_apart["blinding"]


def test_the_protocol_names_the_reveal_trigger_before_tuning(protocol: dict[str, Any]) -> None:
    steps = " ".join(protocol["protocol"])
    assert "reveal trigger" in steps
    assert "cannot be timed to suit a result" in steps
    assert "evaluate once" in steps


def test_the_protocol_discloses_what_it_cannot_fix(protocol: dict[str, Any]) -> None:
    # Repeated attempts each with a fresh holdout is selection across attempts, and the
    # protocol has to say so rather than imply a commitment removes the problem.
    limits = protocol["what_this_protocol_cannot_fix"]
    assert "selection across attempts" in limits
    assert "count of attempts" in limits


def test_the_v5_contract_now_requires_a_commitment_rather_than_plaintext() -> None:
    v5 = json.loads(
        (REPO / "configs" / "experiments" / "track-a-acceptance-v5-criteria.json").read_text(
            encoding="utf-8"
        )
    )
    rule = v5["future_development_rule"]
    requirements = " ".join(rule["requirements"])
    assert "COMMITMENT rather than in plaintext" in requirements
    assert "rested on discipline" in requirements
    assert "blinding 'none'" in requirements
    assert rule["protocol"] == "configs/experiments/motor-05-validation-protocol-v1.json"
    assert "second attempt" in rule["attempt_number"]


def test_the_spent_seed_record_admits_how_it_was_registered() -> None:
    from flysim.station_validation import SPENT_VALIDATION_SEEDS

    record = SPENT_VALIDATION_SEEDS[20260910]
    how = record["how_this_seed_was_registered"]
    assert "In plaintext" in how
    assert "rested on discipline" in how
    assert "commitment rather than in plaintext" in record["successor_rule"]
