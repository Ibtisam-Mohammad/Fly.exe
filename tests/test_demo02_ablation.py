# SPDX-License-Identifier: GPL-2.0-or-later
"""An ablation that does not reach the quantity the decoder reads is not an ablation.

The escape readout-ablated run came back byte-identical to the exact run -- same 1.562 mm
thorax rise, same 3,510,000 us onset, same 2,216,000 us airborne -- because
`FilteredDescendingReadout` zeroes the filtered rates while the escape decoder reads
``raw_population_spike_counts``, which passed through untouched. The control reported that
silencing the readout changed nothing, and it was right about its own arithmetic and wrong
about the experiment.

These tests pin both halves: that the helper zeroes what the decoder actually reads, and
that the decoder is silent once it does.
"""

from __future__ import annotations

import pytest

from flysim.contracts import NeuralOutputFrame, SignalType
from flysim.demo02 import (
    BehaviourState,
    DecoderParameters,
    EscapeDecoder,
    GroomDecoder,
    ablate_readout_frame,
)
from flysim.engines.body import COMMAND_JUMP

COUPLING_US = 15_000


def _frame(t_us: int, *, gf_left: int, gf_right: int, loom_hz: float) -> NeuralOutputFrame:
    return NeuralOutputFrame(
        t_us=t_us,
        ids=("giant-fibre-left", "giant-fibre-right", "dn-loom-left", "dn-loom-right"),
        values=(
            gf_left * 66.7, gf_right * 66.7, loom_hz, loom_hz,
        ),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("ND-01",),
        metadata={
            "raw_population_spike_counts": {
                "giant-fibre-left": gf_left,
                "giant-fibre-right": gf_right,
                "dn-loom-left": 3,
                "dn-loom-right": 3,
            },
            "window_us": COUPLING_US,
        },
    )


ABLATED = frozenset({"giant-fibre-left", "giant-fibre-right"})


def test_ablation_reaches_the_raw_counts_the_escape_decoder_reads() -> None:
    frame = ablate_readout_frame(_frame(0, gf_left=4, gf_right=0, loom_hz=9.0), ABLATED)
    counts = frame.metadata["raw_population_spike_counts"]

    assert counts["giant-fibre-left"] == 0
    assert counts["giant-fibre-right"] == 0
    # Everything not named stays exactly as it was, or the control is silencing the
    # network rather than the readout.
    assert counts["dn-loom-left"] == 3
    assert frame.value_for("dn-loom-left") == pytest.approx(9.0)


def test_ablation_still_zeroes_the_filtered_values() -> None:
    frame = ablate_readout_frame(_frame(0, gf_left=4, gf_right=2, loom_hz=9.0), ABLATED)

    assert frame.value_for("giant-fibre-left") == 0.0
    assert frame.value_for("giant-fibre-right") == 0.0


def test_an_empty_ablation_set_returns_the_frame_untouched() -> None:
    original = _frame(0, gf_left=4, gf_right=0, loom_hz=9.0)
    assert ablate_readout_frame(original, frozenset()) is original


def test_the_escape_decoder_fires_on_an_unablated_frame() -> None:
    """The other half. Without this, the ablation test passes on a decoder that never
    fires at all, which is the degenerate way to make a control look sound."""
    decoder = EscapeDecoder(
        parameters=DecoderParameters(
            quiescent_us=0, threshold_hz=0.0, spike_threshold=1,
            companion_threshold_hz=0.5, initiation_hold_us=0, action_us=1_000_000,
        ),
        coupling_us=COUPLING_US,
    )
    command = decoder.decode(_frame(0, gf_left=2, gf_right=0, loom_hz=9.0))

    assert decoder.state is BehaviourState.ACTING
    assert command.value_for(COMMAND_JUMP) > 0.0


def test_the_escape_decoder_is_silent_once_ablation_reaches_the_counts() -> None:
    decoder = EscapeDecoder(
        parameters=DecoderParameters(
            quiescent_us=0, threshold_hz=0.0, spike_threshold=1,
            companion_threshold_hz=0.5, initiation_hold_us=0, action_us=1_000_000,
        ),
        coupling_us=COUPLING_US,
    )
    for step in range(20):
        frame = ablate_readout_frame(
            _frame(step * COUPLING_US, gf_left=2, gf_right=0, loom_hz=9.0), ABLATED
        )
        command = decoder.decode(frame)
        assert command.value_for(COMMAND_JUMP) == 0.0
    assert decoder.state is not BehaviourState.ACTING


def test_a_rate_reading_decoder_was_never_affected() -> None:
    """Grooming and feeding read the filtered values, so the defect never touched them.
    Asserted rather than assumed, because that is why the bug was escape-only."""
    decoder = GroomDecoder(
        parameters=DecoderParameters(
            quiescent_us=0, threshold_hz=0.6, initiation_hold_us=0, action_us=1_000_000
        ),
        coupling_us=COUPLING_US,
    )
    frame = NeuralOutputFrame(
        t_us=0,
        ids=("groom-dn-left", "groom-dn-right"),
        values=(0.0, 0.0),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="M/P/E",
        assumption_ids=("ND-01",),
        metadata={"raw_population_spike_counts": {"groom-dn-left": 9}},
    )
    command = decoder.decode(frame)

    assert command.metadata["state"] != "ACTING"
