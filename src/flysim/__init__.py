# SPDX-License-Identifier: GPL-2.0-or-later
"""MaleCNS-constrained virtual fly simulation interfaces."""

from .contracts import (
    ActuatorCommandFrame,
    MotorNeuronFrame,
    MuscleActivationFrame,
    NeuralInputFrame,
    NeuralOutputFrame,
    SensorFrame,
    SignalType,
)

__all__ = [
    "ActuatorCommandFrame",
    "MotorNeuronFrame",
    "MuscleActivationFrame",
    "NeuralInputFrame",
    "NeuralOutputFrame",
    "SensorFrame",
    "SignalType",
]

__version__ = "0.1.0"

