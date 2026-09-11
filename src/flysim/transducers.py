# SPDX-License-Identifier: GPL-2.0-or-later
"""World quantity to firing rate, one declared function per channel family.

Every transducer here is `P/E`: a saturating curve with a declared half-saturation, not a
measured receptor response. No fly was recorded to produce any of these numbers, and the
`DEMO-03` record says so.

Two properties are not cosmetic.

**A silent channel returns exactly zero, and the snap to zero is explicit.** The GeNN neuron
model's reset code reads ``RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac``, so *any*
nonzero rate removes that neuron's refractory period and lifts its ceiling from about
1/TauRefrac (455 Hz) to 1/dt (10,000 Hz). A baseline of 1 Hz therefore buys one Hz of drive
and pays with a twenty-two-fold ceiling increase on every entry neuron at once, including
the modalities that are switched off. ``InputRateHz > 0.0`` is a strict comparison, and
float arithmetic makes a value of 1e-300 easy to produce by accident, so the snap is a
declared step rather than a hope.

**The curve is monotone and bounded.** A transducer that can exceed ``max_rate_hz`` would let
a world quantity outside its declared range drive the entry layer past any rate the
operating-point search ever examined.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from flysim.errors import ConfigurationError

#: Below this, a rate is snapped to exactly zero. See the module docstring: the comparison
#: in the neuron model is strict, so "almost silent" and "silent" behave very differently.
SILENCE_FLOOR_HZ = 1e-6


@dataclass(frozen=True, slots=True)
class SaturatingTransducer:
    """``rate = max_rate_hz * x / (x + half_saturation)``, clamped and snapped.

    The Michaelis-Menten form is the same one DEMO-01's visual encoder uses for its angular
    size term, reused so the two encoders are not gratuitously different shapes.
    """

    max_rate_hz: float
    half_saturation: float
    threshold: float = 0.0
    provenance: str = "P/E"

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_rate_hz) or self.max_rate_hz <= 0.0:
            raise ConfigurationError("A transducer needs a positive finite maximum rate")
        if not math.isfinite(self.half_saturation) or self.half_saturation <= 0.0:
            raise ConfigurationError("A transducer needs a positive half-saturation")
        if not math.isfinite(self.threshold) or self.threshold < 0.0:
            raise ConfigurationError("A transducer threshold cannot be negative")

    def rate_hz(self, quantity: float) -> float:
        if not math.isfinite(quantity):
            raise ConfigurationError(f"World quantity is not finite: {quantity}")
        driven = abs(quantity) - self.threshold
        if driven <= 0.0:
            return 0.0
        rate = self.max_rate_hz * driven / (driven + self.half_saturation)
        return 0.0 if rate < SILENCE_FLOOR_HZ else min(rate, self.max_rate_hz)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> SaturatingTransducer:
        return cls(
            max_rate_hz=float(raw["max_rate_hz"]),
            half_saturation=float(raw["half_saturation"]),
            threshold=float(raw.get("threshold", 0.0)),
            provenance=str(raw.get("provenance", "P/E")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": "saturating",
            "max_rate_hz": self.max_rate_hz,
            "half_saturation": self.half_saturation,
            "threshold": self.threshold,
            "provenance": self.provenance,
            "silence_floor_hz": SILENCE_FLOOR_HZ,
            "what_this_is_not": (
                "a measured receptor response. No fly produced these numbers; they are an "
                "engineering scaffold under DEMO-03."
            ),
        }
