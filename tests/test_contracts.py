# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from flysim.contracts import MuscleForceFrame, SensorFrame, SignalType, frame_from_dict
from flysim.errors import ConfigurationError


def frame() -> SensorFrame:
    return SensorFrame(
        t_us=100,
        ids=(123, "semantic-id"),
        values=(1.0, 2.0),
        units="normalized",
        signal_type=SignalType.RECEPTOR_ACTIVITY,
        provenance="M/P",
        assumption_ids=("SENS-01",),
    )


def test_frame_round_trip_and_identity_types() -> None:
    original = frame()
    restored = frame_from_dict(SensorFrame, original.as_dict())
    assert restored == original
    assert restored.value_for(123) == 1.0


@pytest.mark.parametrize(
    ("ids", "values", "assumption_ids"),
    [
        ((1,), (1.0, 2.0), ("SENS-01",)),
        ((1, 1), (1.0, 2.0), ("SENS-01",)),
        ((1,), (1.0,), ()),
    ],
)
def test_invalid_frames_fail(
    ids: tuple[int, ...], values: tuple[float, ...], assumption_ids: tuple[str, ...]
) -> None:
    with pytest.raises(ConfigurationError):
        SensorFrame(
            t_us=0,
            ids=ids,
            values=values,
            units="normalized",
            signal_type=SignalType.RECEPTOR_ACTIVITY,
            provenance="E",
            assumption_ids=assumption_ids,
        )


def test_force_boundary_is_not_an_actuator_command() -> None:
    force = MuscleForceFrame(
        t_us=100,
        ids=("T1-flexor",),
        values=(1.5,),
        units="mN",
        signal_type=SignalType.MUSCLE_FORCE,
        provenance="P/F/E",
        assumption_ids=("MOTOR-02",),
    )
    assert force.signal_type is SignalType.MUSCLE_FORCE
