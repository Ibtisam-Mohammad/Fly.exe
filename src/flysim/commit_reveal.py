# SPDX-License-Identifier: GPL-2.0-or-later
"""Commit-reveal for a validation seed, and an honest account of what it proves.

Registering a validation seed in plaintext before tuning proves the set was fixed in
advance. It does not stop whoever is tuning from drawing the poses and looking at them,
because the seed is right there. MOTOR-04's twelve poses were registered that way; the
run happened to be honest, and the protocol did not require it to be.

A commitment fixes the seed without publishing it. What it cannot do by itself is make
the seed unknown to the party that generated it, so this module keeps the two properties
apart and refuses to let one be reported as the other:

**fixation** — the seed could not be changed after the controller was frozen. A digest in
a pre-tuning commit establishes this, whoever holds the secret.

**blinding** — the tuner did not know the seed while tuning. A digest establishes this
only if the secret was held by someone else, or if the seed did not exist yet because it
comes from a public source whose value postdates the freeze.

So a single-party commit-reveal is supported and must be labelled ``blinding: "none"``.
It is an improvement on plaintext and it is not the same thing as a blind holdout.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

from flysim.errors import ConfigurationError

_DOMAIN = b"flysim-validation-seed-v1"
_NONCE_MINIMUM_HEX = 32
_HEX = re.compile(r"\A[0-9a-f]+\Z")
_SEED_CEILING = 1 << 64

BLINDING_SOURCES: dict[str, str] = {
    "public-beacon": (
        "The seed is derived from a public randomness source whose value did not exist "
        "when the controller was frozen, so no party could know it. Strongest available."
    ),
    "second-party-secret": (
        "Another party generated the seed and the nonce, published the digest, and "
        "revealed after the freeze commit. The tuner was blind."
    ),
    "none": (
        "The tuning party generated the seed and holds its own secret. This establishes "
        "fixation only. It does not establish that the poses were unseen during tuning, "
        "and it must not be described as a blind holdout."
    ),
}


def new_nonce() -> str:
    """A 256-bit nonce. The seed may be low-entropy; the nonce is what hides it."""
    return secrets.token_hex(32)


def _check_nonce(nonce_hex: str) -> None:
    if not _HEX.match(nonce_hex):
        raise ConfigurationError("A commitment nonce must be lowercase hexadecimal")
    if len(nonce_hex) < _NONCE_MINIMUM_HEX:
        raise ConfigurationError(
            f"A commitment nonce needs at least {_NONCE_MINIMUM_HEX} hex characters; a "
            "short nonce lets a small seed space be brute-forced from the digest, which "
            "would make the commitment reveal the seed it is supposed to hide"
        )


def _check_seed(seed: int) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigurationError("A validation seed must be an integer")
    if not 0 <= seed < _SEED_CEILING:
        raise ConfigurationError("A validation seed must lie in [0, 2**64)")


def commit_seed(*, seed: int, nonce_hex: str) -> str:
    """The digest to register before tuning begins."""
    _check_seed(seed)
    _check_nonce(nonce_hex)
    payload = b":".join((_DOMAIN, nonce_hex.encode("ascii"), str(seed).encode("ascii")))
    return hashlib.sha256(payload).hexdigest()


def verify_seed(*, commitment: str, seed: int, nonce_hex: str) -> None:
    """Refuse a reveal that does not match what was committed."""
    if not _HEX.match(commitment) or len(commitment) != 64:
        raise ConfigurationError("A seed commitment must be a 64-character sha256 digest")
    recomputed = commit_seed(seed=seed, nonce_hex=nonce_hex)
    if not secrets.compare_digest(recomputed, commitment):
        raise ConfigurationError(
            f"Revealed seed {seed} with the given nonce hashes to {recomputed[:16]}..., "
            f"which does not match the registered commitment {commitment[:16]}.... Either "
            "the reveal is wrong or the seed was changed after it was committed."
        )


def derive_seed_from_beacon(*, beacon_value_hex: str) -> int:
    """Derive the seed from a public value that did not exist at freeze time.

    Deterministic and recheckable by anyone holding the beacon value, which is the point:
    with this route there is no secret for the tuner to hold and nothing to reveal.
    """
    if not _HEX.match(beacon_value_hex) or len(beacon_value_hex) < 32:
        raise ConfigurationError(
            "A beacon value must be at least 32 lowercase hex characters"
        )
    digest = hashlib.sha256(_DOMAIN + b":beacon:" + beacon_value_hex.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True, slots=True)
class SeedCommitment:
    """A registered commitment together with what it is claimed to establish."""

    commitment: str
    blinding: str
    justification: str
    reveal_trigger: str

    def __post_init__(self) -> None:
        if self.blinding not in BLINDING_SOURCES:
            raise ConfigurationError(
                f"Unknown blinding source {self.blinding!r}; expected one of "
                f"{sorted(BLINDING_SOURCES)}"
            )
        if not _HEX.match(self.commitment) or len(self.commitment) != 64:
            raise ConfigurationError("A seed commitment must be a 64-character sha256 digest")
        if len(self.justification.strip()) < 40:
            raise ConfigurationError(
                "A commitment must say in its own words who held the secret and why the "
                "claimed blinding follows; a one-word justification is not a protocol"
            )
        if not self.reveal_trigger.strip():
            raise ConfigurationError(
                "A commitment must name what triggers the reveal, so the reveal cannot be "
                "timed to suit the result"
            )

    @property
    def establishes_blinding(self) -> bool:
        return self.blinding != "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "commitment": self.commitment,
            "blinding": self.blinding,
            "blinding_means": BLINDING_SOURCES[self.blinding],
            "establishes_fixation": True,
            "establishes_blinding": self.establishes_blinding,
            "justification": self.justification,
            "reveal_trigger": self.reveal_trigger,
        }

    @classmethod
    def from_contract(cls, payload: dict[str, Any]) -> SeedCommitment:
        return cls(
            commitment=str(payload["commitment"]),
            blinding=str(payload["blinding"]),
            justification=str(payload["justification"]),
            reveal_trigger=str(payload["reveal_trigger"]),
        )
