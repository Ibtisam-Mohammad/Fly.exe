# SPDX-License-Identifier: GPL-2.0-or-later
"""Track A scenario arbitration with explicit engineering provenance."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from flysim.contracts import ActuatorCommandFrame, NeuralOutputFrame, SensorFrame, SignalType
from flysim.engines.body import COMMAND_IDS
from flysim.engines.reference import (
    OUTPUT_DNA_L,
    OUTPUT_DNA_R,
    OUTPUT_FEED,
    OUTPUT_FORWARD,
    OUTPUT_GROOM,
    SENSOR_CONTAMINATION,
    SENSOR_ODOR_L,
    SENSOR_ODOR_R,
    SENSOR_SUCROSE,
)


class DemoState(StrEnum):
    SEEK = "SEEK"
    GROOM = "GROOM"
    SEEK_RESUME = "SEEK_RESUME"
    FEED_INITIATION = "FEED_INITIATION"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class ControllerParameters:
    max_forward_mm_s: float
    yaw_gain_rad_s_per_hz: float
    odor_gradient_yaw_gain_rad_s: float
    max_yaw_rad_s: float
    forward_half_rate_hz: float
    groom_bout_min_us: int
    groom_refractory_us: int
    feed_extension_us: int
    feed_min_evoked_rate_hz: float
    trigger_sigma: float
    release_sigma: float
    threshold_sd_floor_hz: float
    baseline_window_us: int
    readout_window_us: int
    contamination_trigger: float
    contamination_release: float


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    t_us: int
    from_state: DemoState
    to_state: DemoState
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_us": self.t_us,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
        }


class BaselineThreshold:
    def __init__(
        self, window_us: int, trigger_sigma: float, release_sigma: float, sd_floor_hz: float
    ) -> None:
        self.window_us = window_us
        self.trigger_sigma = trigger_sigma
        self.release_sigma = release_sigma
        self.sd_floor_hz = sd_floor_hz
        self._samples: list[float] = []

    def observe(self, t_us: int, value: float) -> None:
        if t_us <= self.window_us:
            self._samples.append(value)

    @property
    def ready(self) -> bool:
        return bool(self._samples)

    def _stats(self) -> tuple[float, float]:
        if not self._samples:
            return 0.0, 0.0
        mean = statistics.fmean(self._samples)
        std = statistics.pstdev(self._samples) if len(self._samples) > 1 else 0.0
        return mean, max(std, self.sd_floor_hz)

    @property
    def trigger(self) -> float:
        mean, std = self._stats()
        return mean + self.trigger_sigma * std

    @property
    def release(self) -> float:
        mean, std = self._stats()
        return mean + self.release_sigma * std


class EonDemoController:
    """Priority arbiter for a visibly labelled engineering demonstration."""

    def __init__(self, parameters: ControllerParameters) -> None:
        self.parameters = parameters
        self.state = DemoState.SEEK
        self.entered_state_us = 0
        self.events: list[TransitionEvent] = []
        self.last_groom_exit_us: int | None = None
        self.groom_threshold = BaselineThreshold(
            parameters.baseline_window_us,
            parameters.trigger_sigma,
            parameters.release_sigma,
            parameters.threshold_sd_floor_hz,
        )
        self.feed_threshold = BaselineThreshold(
            parameters.baseline_window_us,
            parameters.trigger_sigma,
            parameters.release_sigma,
            parameters.threshold_sd_floor_hz,
        )
        self._groom_window: list[tuple[int, float]] = []
        self._feed_window: list[tuple[int, float]] = []

    def _windowed_rate(self, samples: list[tuple[int, float]], t_us: int, value: float) -> float:
        samples.append((t_us, value))
        cutoff = t_us - self.parameters.readout_window_us
        while samples and samples[0][0] < cutoff:
            samples.pop(0)
        return statistics.fmean(item[1] for item in samples)

    def _transition(self, t_us: int, to_state: DemoState, reason: str) -> None:
        event = TransitionEvent(t_us=t_us, from_state=self.state, to_state=to_state, reason=reason)
        self.events.append(event)
        self.state = to_state
        self.entered_state_us = t_us

    def decode(
        self,
        neural: NeuralOutputFrame,
        sensors: SensorFrame,
    ) -> ActuatorCommandFrame:
        t_us = neural.t_us
        groom_rate = self._windowed_rate(
            self._groom_window, t_us, neural.value_for(OUTPUT_GROOM)
        )
        feed_rate = self._windowed_rate(
            self._feed_window, t_us, neural.value_for(OUTPUT_FEED)
        )
        self.groom_threshold.observe(t_us, groom_rate)
        self.feed_threshold.observe(t_us, feed_rate)
        contamination = sensors.value_for(SENSOR_CONTAMINATION)
        sucrose = sensors.value_for(SENSOR_SUCROSE)

        baseline_complete = t_us >= self.parameters.baseline_window_us
        groom_refractory_complete = (
            self.last_groom_exit_us is None
            or t_us - self.last_groom_exit_us >= self.parameters.groom_refractory_us
        )
        if self.state in {DemoState.SEEK, DemoState.SEEK_RESUME}:
            if (
                baseline_complete
                and groom_refractory_complete
                and contamination >= self.parameters.contamination_trigger
                and groom_rate > self.groom_threshold.trigger
            ):
                self._transition(t_us, DemoState.GROOM, "contamination-and-groom-readout")
            elif (
                self.state == DemoState.SEEK_RESUME
                and baseline_complete
                and sucrose > 0.0
                and feed_rate >= self.parameters.feed_min_evoked_rate_hz
                and feed_rate > self.feed_threshold.trigger
            ):
                self._transition(t_us, DemoState.FEED_INITIATION, "sucrose-and-MN9-readout")
        elif self.state == DemoState.GROOM:
            bout_elapsed = t_us - self.entered_state_us
            if (
                bout_elapsed >= self.parameters.groom_bout_min_us
                and contamination <= self.parameters.contamination_release
                and groom_rate <= self.groom_threshold.release
            ):
                self.last_groom_exit_us = t_us
                self._transition(t_us, DemoState.SEEK_RESUME, "contamination-cleared")
        elif (
            self.state == DemoState.FEED_INITIATION
            and t_us - self.entered_state_us >= self.parameters.feed_extension_us
        ):
            self._transition(t_us, DemoState.COMPLETE, "feeding-initiation-pose-complete")

        forward = 0.0
        yaw = 0.0
        grooming = 0.0
        proboscis = 0.0
        if self.state in {DemoState.SEEK, DemoState.SEEK_RESUME}:
            # Both outputs are dimensionless descending drives in [0, 1] and [-1, 1].
            # They are not commanded or achieved physical velocities: each body backend
            # maps them onto its own locomotor scale (MOTOR-03 full-scale values).
            forward_rate = neural.value_for(OUTPUT_FORWARD)
            forward = forward_rate / (forward_rate + self.parameters.forward_half_rate_hz)
            left_rate = neural.value_for(OUTPUT_DNA_L)
            right_rate = neural.value_for(OUTPUT_DNA_R)
            odor_left = sensors.value_for(SENSOR_ODOR_L)
            odor_right = sensors.value_for(SENSOR_ODOR_R)
            raw_yaw = (
                self.parameters.yaw_gain_rad_s_per_hz * (left_rate - right_rate)
                + self.parameters.odor_gradient_yaw_gain_rad_s
                * (odor_left - odor_right)
            )
            yaw = min(1.0, max(-1.0, raw_yaw / self.parameters.max_yaw_rad_s))
        elif self.state == DemoState.GROOM:
            grooming = 1.0
        elif self.state == DemoState.FEED_INITIATION:
            proboscis = 1.0

        return ActuatorCommandFrame(
            t_us=t_us,
            ids=COMMAND_IDS,
            values=(forward, yaw, grooming, proboscis),
            units="normalized-drive [0,1], normalized-drive [-1,1], normalized, normalized",
            signal_type=SignalType.ACTUATOR_COMMAND,
            provenance="E",
            assumption_ids=("MOTOR-03",),
            metadata={
                "controller_state": self.state.value,
                "vnc_bypass": True,
                "normalized_controller_drive": True,
            },
        )


def controller_parameters(motor: dict[str, Any], sensory: dict[str, Any]) -> ControllerParameters:
    return ControllerParameters(
        max_forward_mm_s=float(motor["max_forward_mm_s"]),
        yaw_gain_rad_s_per_hz=float(motor["yaw_gain_rad_s_per_hz"]),
        odor_gradient_yaw_gain_rad_s=float(motor["odor_gradient_yaw_gain_rad_s"]),
        max_yaw_rad_s=float(motor["max_yaw_rad_s"]),
        forward_half_rate_hz=float(motor["forward_half_rate_hz"]),
        groom_bout_min_us=int(motor["groom_bout_min_us"]),
        groom_refractory_us=int(motor["groom_refractory_us"]),
        feed_extension_us=int(motor["feed_extension_us"]),
        feed_min_evoked_rate_hz=float(motor["feed_min_evoked_rate_hz"]),
        trigger_sigma=float(motor["trigger_sigma"]),
        release_sigma=float(motor["release_sigma"]),
        threshold_sd_floor_hz=float(motor["threshold_sd_floor_hz"]),
        baseline_window_us=int(motor["baseline_window_us"]),
        readout_window_us=int(motor["readout_window_us"]),
        contamination_trigger=float(sensory["contamination_trigger"]),
        contamination_release=float(sensory["contamination_release"]),
    )
