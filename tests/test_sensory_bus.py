# SPDX-License-Identifier: GPL-2.0-or-later
"""The bus: one frame, no duplicates, no sensor reaching the command, and silence is silent.

The last property is the one with teeth. A nonzero input rate removes a neuron's refractory
period in the GeNN kernel, so "almost off" and "off" are twenty-two-fold different in firing
ceiling. A stimulus-absent control that leaks a baseline is not a control.
"""

from __future__ import annotations

import inspect

import pytest

from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SensorFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError
from flysim.sensory_atlas import ChannelKey, SensoryAtlas
from flysim.sensory_bus import ChannelBinding, SensoryBus
from flysim.transducers import SaturatingTransducer

COUPLING_US = 15_000

LEFT = ChannelKey("antennal-jo-f-grooming", "antenna", "L")
RIGHT = ChannelKey("antennal-jo-f-grooming", "antenna", "R")
THERMO = ChannelKey("thermosensory", "antenna", "L")


def _atlas(**overrides: object) -> SensoryAtlas:
    channels = {
        str(LEFT): (10, 11),
        str(RIGHT): (20, 21, 22),
        str(THERMO): (30,),
    }
    base = {
        "registry_id": "test-atlas",
        "annotations_sha256": "0" * 64,
        "channels": channels,
        "channel_keys": (LEFT, RIGHT, THERMO),
        "modality_kind": {
            "antennal-jo-f-grooming": "real",
            "thermosensory": "absent",
        },
        "modality_bodies": {
            "antennal-jo-f-grooming": (10, 11, 20, 21, 22),
            "thermosensory": (30,),
        },
        "modality_note": {},
        "surrogates": {},
        "unassigned": (),
        "entry_union": (10, 11, 20, 21, 22, 30),
        "entry_union_sha256": "a" * 64,
        "ledger": {},
    }
    base.update(overrides)
    return SensoryAtlas(**base)  # type: ignore[arg-type]


def _transducer() -> SaturatingTransducer:
    return SaturatingTransducer(max_rate_hz=80.0, half_saturation=0.2)


def _bindings(**overrides: object) -> tuple[ChannelBinding, ...]:
    common = {"transducer": _transducer(), "delay_us": 0, "kind": "real"}
    common.update(overrides)
    return (
        ChannelBinding(key=LEFT, sensor_id="world:antenna-deflection:l", **common),  # type: ignore[arg-type]
        ChannelBinding(key=RIGHT, sensor_id="world:antenna-deflection:r", **common),  # type: ignore[arg-type]
    )


def _sensors(t_us: int, left: float, right: float) -> SensorFrame:
    return SensorFrame(
        t_us=t_us,
        ids=("world:antenna-deflection:l", "world:antenna-deflection:r"),
        values=(left, right),
        units="rad,rad",
        signal_type=SignalType.WORLD_QUANTITY,
        provenance="M/E",
        assumption_ids=("SENS-04",),
    )


def _bus(**overrides: object) -> SensoryBus:
    bindings = overrides.pop("bindings", None) or _bindings()
    return SensoryBus(
        atlas=overrides.pop("atlas", None) or _atlas(),  # type: ignore[arg-type]
        bindings=bindings,  # type: ignore[arg-type]
        coupling_us=int(overrides.pop("coupling_us", COUPLING_US)),  # type: ignore[arg-type]
    )


def test_no_stimulus_means_no_neuron_carries_a_rate() -> None:
    """The property a stimulus-absent control depends on.

    ``RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac`` in the kernel, so a single
    nonzero neuron is a neuron whose firing ceiling has moved from about 455 Hz to
    10,000 Hz. Zero has to mean zero.
    """
    frame = _bus().encode(0, _sensors(0, 0.0, 0.0))

    assert frame.ids == ()
    assert frame.values == ()
    assert frame.metadata["entry_bodies_with_nonzero_rate"] == 0
    assert frame.metadata["active_channels"] == []
    assert len(frame.metadata["silent_channels"]) == 2


def test_a_stimulus_on_one_side_drives_only_that_side() -> None:
    frame = _bus().encode(0, _sensors(0, 0.4, 0.0))

    assert set(frame.ids) == {10, 11}
    assert frame.values == pytest.approx((80.0 * 0.4 / 0.6,) * 2)
    assert frame.metadata["active_channels"] == [str(LEFT)]
    assert frame.metadata["entry_bodies_with_nonzero_rate"] == 2


def test_every_id_in_the_frame_is_unique_across_channels() -> None:
    """SignalFrame would raise on a duplicate, which is the point: the partition makes a
    double-claimed body unrepresentable rather than caught at injection time."""
    frame = _bus().encode(0, _sensors(0, 0.5, 0.5))

    assert len(set(frame.ids)) == len(frame.ids) == 5
    assert frame.units == "Hz" and frame.signal_type is SignalType.FIRING_RATE


def test_a_disabled_channel_is_silent_but_still_declared() -> None:
    bindings = (
        ChannelBinding(
            key=LEFT, sensor_id="world:antenna-deflection:l", transducer=_transducer(),
            delay_us=0, enabled=False,
        ),
        _bindings()[1],
    )
    frame = _bus(bindings=bindings).encode(0, _sensors(0, 0.9, 0.9))

    assert set(frame.ids) == {20, 21, 22}
    assert frame.metadata["channel_rate_hz"][str(LEFT)] == 0.0
    # The world quantity is still recorded, so "off" is distinguishable from "absent".
    assert frame.metadata["channel_world_quantity"][str(LEFT)] == pytest.approx(0.9)


def test_an_absent_modality_may_not_be_bound() -> None:
    """Thermo and hygro resolve so the partition is total, and have no world quantity.
    Binding one would be the fake generic channel SENS-05 forbids."""
    bindings = (
        ChannelBinding(
            key=THERMO, sensor_id="world:temperature", transducer=_transducer(), delay_us=0
        ),
    )
    with pytest.raises(ConfigurationError, match="absent modality"):
        _bus(bindings=bindings)


def test_one_channel_cannot_be_bound_twice() -> None:
    bindings = (*_bindings(), _bindings()[0])
    with pytest.raises(ConfigurationError, match="bound twice"):
        _bus(bindings=bindings)


def test_a_delay_the_bus_cannot_deliver_is_refused() -> None:
    """Because one frame carries every sense, delay is quantised to the coupling interval.
    Accepting 5000 us and delivering 15000 would be a silent lie about causality."""
    with pytest.raises(ConfigurationError, match="quantised"):
        _bus(bindings=_bindings(delay_us=5_000))


def test_a_delayed_channel_is_silent_until_its_sample_arrives() -> None:
    bus = _bus(bindings=_bindings(delay_us=COUPLING_US))

    first = bus.encode(0, _sensors(0, 0.5, 0.0))
    second = bus.encode(COUPLING_US, _sensors(COUPLING_US, 0.0, 0.0))

    assert first.ids == (), "a sample pushed at t=0 cannot also arrive at t=0"
    assert set(second.ids) == {10, 11}, "it arrives one interval later"


def test_the_bus_refuses_to_encode_an_interval_twice() -> None:
    bus = _bus()
    bus.encode(0, _sensors(0, 0.1, 0.1))
    with pytest.raises(CausalityError, match="may not be produced twice"):
        bus.encode(0, _sensors(0, 0.1, 0.1))


def test_the_bus_refuses_a_sensor_sample_from_another_interval() -> None:
    with pytest.raises(CausalityError, match="never reads a sample from another interval"):
        _bus().encode(COUPLING_US, _sensors(0, 0.1, 0.1))


def test_a_channel_outside_the_frozen_entry_union_is_refused() -> None:
    """The union is hashed into the GeNN model identity through entry_body_ids, so a body
    outside it cannot be driven without a new CUDA build."""
    atlas = _atlas(entry_union=(10, 11))
    with pytest.raises(ConfigurationError, match="outside the frozen entry union"):
        _bus(atlas=atlas)


def test_the_transducer_is_bounded_and_snaps_to_silence() -> None:
    transducer = SaturatingTransducer(max_rate_hz=80.0, half_saturation=0.2)

    assert transducer.rate_hz(0.0) == 0.0
    assert transducer.rate_hz(1e-12) == 0.0, "a float whisker above zero is still silence"
    assert transducer.rate_hz(1e9) <= 80.0
    assert transducer.rate_hz(0.2) == pytest.approx(40.0)
    # Monotone, so a bigger world quantity never produces less drive.
    rates = [transducer.rate_hz(x / 20.0) for x in range(40)]
    assert rates == sorted(rates)


def test_a_threshold_holds_a_channel_silent_below_it() -> None:
    transducer = SaturatingTransducer(max_rate_hz=50.0, half_saturation=0.1, threshold=0.3)

    assert transducer.rate_hz(0.29) == 0.0
    assert transducer.rate_hz(0.4) > 0.0


def test_no_decoder_may_take_a_sensor_frame() -> None:
    """The structural guarantee, not the cosmetic one.

    DEMO-01's predecessor had ``decode(neural, sensors)`` and its 'behaviour' turned out to
    be the sensor term. DEMO-01 deleted the argument. A multi-sensory bus makes that
    regression easy and cheap, so it is asserted rather than remembered.
    """
    from flysim.demo01_visual import VisualLocomotorDecoder

    signature = inspect.signature(VisualLocomotorDecoder.decode)
    parameters = [p for name, p in signature.parameters.items() if name != "self"]

    assert len(parameters) == 1
    assert parameters[0].annotation in (NeuralOutputFrame, "NeuralOutputFrame")
    assert SensorFrame.__name__ not in str(signature)


def test_describe_states_the_limitations_rather_than_implying_them() -> None:
    described = _bus().describe()

    assert described["bound_channels"] == 2
    assert described["bound_bodies"] == 5
    joined = " ".join(described["declared_limitations"])
    assert "quantised" in joined
    assert "10000 Hz" in joined
    assert "1.0" in joined, "the entry gain commitment must be stated"


def test_the_frame_cites_its_assumptions_and_says_what_it_cannot_see() -> None:
    frame = _bus().encode(0, _sensors(0, 0.3, 0.3))

    assert "DEMO-03" in frame.assumption_ids
    assert isinstance(frame, NeuralInputFrame)
    assert "pose" in frame.metadata["the_bus_cannot_see"]
