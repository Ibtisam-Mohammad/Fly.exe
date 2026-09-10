# SPDX-License-Identifier: GPL-2.0-or-later
"""Candidate short-term-plasticity families for the ORN-to-PN synapse, with a fitter.

The registered ND-06 rule is depression-only and it failed structurally against
Rozenfeld and colleagues' wild-type paired-pulse measurements: those ratios exceed one
at short intervals and decrease with interval, and a single depleting resource can do
neither. That failure diagnosed a *missing* mechanism rather than a wrong one, and this
module is the successor's workshop. It carries seven families, every one of them a
mechanism that is standard in the synaptic-physiology literature, and the machinery to
fit them, cross-validate them, bootstrap them and check whether their parameters are
identifiable at all from five paired-pulse means.

Three properties are deliberately built in.

The families are **state machines over a spike train**, not closed-form paired-pulse
expressions. That costs a loop and buys protocol fidelity: Rozenfeld and colleagues
recorded paired pulses at 0.2 Hz and averaged twenty traces, so the ratio they report is
the mean second response over the mean first response across twenty pairs whose earlier
members leave the resource partly depleted, not a single pair from rest. A closed form
would have to assume the difference away. It is computed here instead, and the from-rest
value is reported next to it so the size of the correction is visible.

Nothing in this module reads a sealed file, and nothing in it knows what a holdout is.
It fits what it is given. The separation matters because the data it will be given are
*spent*: the Fig3D wild-type arrays were opened and scored on 2026-09-09, so they can
never again serve as a test, and using them as training data is the only remaining
honest use for them. A fit is not a validation and this module cannot award one.

The fitter is hand-rolled because scipy is not a declared dependency. It is a
Nelder-Mead simplex over a sigmoid-transformed box, restarted from a seeded
Latin-hypercube sample, and it is tested against problems with known answers.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from flysim.errors import ConfigurationError

# The protocol, from the paper's methods: "Paired-pulse recordings were made at 0.2 Hz
# with inter-stimulus intervals of (in ms): 10, 30, 100, 300, and 1000. For each interval
# 20 traces were averaged."
PAIR_PERIOD_MS = 5000.0
PAIRS_AVERAGED = 20

# The registered ND-06 primary fit, used only to pin the M3 family's depression leg.
NAGEL_UTILISATION = 0.22
NAGEL_RECOVERY_TAU_MS = 893.0


@dataclass(frozen=True, slots=True)
class Parameter:
    """One fitted parameter and the box it is fitted inside."""

    name: str
    low: float
    high: float
    unit: str
    meaning: str


@dataclass(frozen=True, slots=True)
class Family:
    """A candidate mechanism, its free parameters and its declared structural limits."""

    family_id: str
    title: str
    parameters: tuple[Parameter, ...]
    mechanism: str
    paired_pulse_ceiling: float | None
    structural_limits: str

    @property
    def parameter_count(self) -> int:
        return len(self.parameters)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "title": self.title,
            "mechanism": self.mechanism,
            "parameter_count": self.parameter_count,
            "parameters": [
                {
                    "name": parameter.name,
                    "bounds": [parameter.low, parameter.high],
                    "unit": parameter.unit,
                    "meaning": parameter.meaning,
                }
                for parameter in self.parameters
            ],
            "paired_pulse_ceiling": self.paired_pulse_ceiling,
            "structural_limits": self.structural_limits,
        }


def _relax(state: float, resting: float, elapsed_ms: float, tau_ms: float) -> float:
    """One exponential relaxation of a state variable back toward its resting value."""
    return resting + (state - resting) * math.exp(-elapsed_ms / tau_ms)


def _decays(gaps: list[float], tau_ms: float) -> dict[float, float]:
    """Decay factors for each distinct gap, computed once.

    The protocol simulation visits only two distinct gaps -- the interval and the rest
    of the repetition period -- forty times each, and the fitter evaluates it thousands
    of times per restart. Memoising the exponential here is the difference between a fit
    that takes ten seconds and one that takes two.
    """
    return {gap: math.exp(-gap / tau_ms) for gap in set(gaps)}


def _amplitudes_depression_only(gaps: list[float], theta: Sequence[float]) -> list[float]:
    """M0: one depleting resource. The registered ND-06 rule, term for term."""
    utilisation, recovery_tau = float(theta[0]), float(theta[1])
    recovery = _decays(gaps, recovery_tau)
    resource = 1.0
    out: list[float] = []
    for gap in gaps:
        resource = 1.0 + (resource - 1.0) * recovery[gap]
        out.append(resource)
        resource *= 1.0 - utilisation
    return out


def _amplitudes_facilitation_depression(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M1: Markram-Tsodyks release-probability facilitation over a depleting resource.

    On a spike the utilisation is first stepped up by ``increment`` toward one, the
    response is the stepped utilisation times the available resource, and only then is
    the resource depleted by the stepped utilisation. Between spikes the utilisation
    relaxes to its resting value with ``facilitation_tau`` and the resource recovers to
    one with ``recovery_tau``.
    """
    resting, increment = float(theta[0]), float(theta[1])
    facilitation_tau, recovery_tau = float(theta[2]), float(theta[3])
    facilitation = _decays(gaps, facilitation_tau)
    recovery = _decays(gaps, recovery_tau)
    use, resource = resting, 1.0
    out: list[float] = []
    for gap in gaps:
        use = resting + (use - resting) * facilitation[gap]
        resource = 1.0 + (resource - 1.0) * recovery[gap]
        use = use + increment * (1.0 - use)
        out.append(use * resource)
        resource *= 1.0 - use
    return out


def _amplitudes_facilitation_depression_classic(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M1b: M1 with the facilitation increment tied to the resting utilisation.

    This is the textbook Tsodyks-Markram form ``u <- u + U(1 - u)``. Tying the two
    together removes a parameter and imposes a hard ceiling of 1.5 on the paired-pulse
    ratio, which is why it is carried separately: the ceiling is testable.
    """
    resting = float(theta[0])
    return _amplitudes_facilitation_depression(
        gaps, (resting, resting, float(theta[1]), float(theta[2]))
    )


def _amplitudes_parallel_components(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M2: two release components in parallel, one facilitating and one depressing.

    The facilitating component carries a linear residual-calcium variable with no
    depletion and no ceiling; the depressing component is a depleting resource. Their
    resting contributions are fixed at equal shares, which is a declared structural
    choice and not a fitted one: a paired-pulse ratio identifies only the products
    ``share * facilitation_step`` and ``(1 - share) * utilisation``, so the share is not
    recoverable from this observable at all. See ``PARALLEL_SHARE``.
    """
    step, facilitation_tau = float(theta[0]), float(theta[1])
    utilisation, recovery_tau = float(theta[2]), float(theta[3])
    fast = _decays(gaps, facilitation_tau)
    recovery = _decays(gaps, recovery_tau)
    facilitation, resource = 1.0, 1.0
    out: list[float] = []
    for gap in gaps:
        facilitation = 1.0 + (facilitation - 1.0) * fast[gap]
        resource = 1.0 + (resource - 1.0) * recovery[gap]
        out.append(PARALLEL_SHARE * facilitation + (1.0 - PARALLEL_SHARE) * resource)
        facilitation += step
        resource *= 1.0 - utilisation
    return out


def _amplitudes_pinned_published_depression(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M3: M1 with the depression leg pinned to the published ND-06 fit.

    The free parameters are the facilitation increment and its time constant. This asks
    a specific question the previous failure left open: is the registered rule's problem
    only the absent facilitation, or are its depression parameters wrong for this
    dataset as well? The increment is capped at the pinned resting utilisation, above
    which the effective first-pulse utilisation would no longer be the published one.
    """
    return _amplitudes_facilitation_depression(
        gaps,
        (
            _pinned_resting_utilisation(float(theta[0])),
            float(theta[0]),
            float(theta[1]),
            NAGEL_RECOVERY_TAU_MS,
        ),
    )


def _pinned_resting_utilisation(increment: float) -> float:
    """The resting utilisation that keeps M3's effective first-pulse utilisation pinned.

    M1's first response consumes ``increment + (1 - increment) * resting`` of the
    resource, and pinning that to the published utilisation is what "the published
    depression leg, plus facilitation" has to mean. Solving for the resting value gives
    this expression, which is why M3's increment cannot exceed the pinned utilisation.
    """
    if increment >= NAGEL_UTILISATION:
        return 0.0
    return (NAGEL_UTILISATION - increment) / (1.0 - increment)


PARALLEL_SHARE = 0.5

# The recovery constant M4 pins. It is not a fitted value and it is not a measurement.
# Over the longest recorded interval a resource with this constant recovers by under five
# percent, so the component acts as an effectively non-recovering depression across the
# whole paired-pulse range. The fit set says the same thing directly: the 300 ms and
# 1000 ms cohort means differ by 0.0003 against a pooled standard error of 0.0277, which
# is what a non-recovering component predicts and what no recoverable one does.
PINNED_RECOVERY_TAU_MS = 20000.0

# The fast facilitation constant M4 pins, and why it is pinned rather than fitted.
#
# The shortest recorded interval is 10 ms. A facilitation component with a constant at or
# below that is present in the 10 ms cohort mean and gone by the 30 ms one, so the data
# carry exactly one number about it and cannot separate its size from its decay. Fitting
# both produced a flat ridge: doubling the step and shortening the constant to match left
# all five predictions unchanged. The value below is half the shortest measured interval.
# It is arbitrary within the indistinguishable set and it is not a measurement of
# anything. What is fitted is the amplitude, which the data do determine.
PINNED_FAST_TAU_MS = 5.0


def _amplitudes_two_timescale_facilitation(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M4: two facilitation timescales multiplying a depleting resource.

    The fit set forces this. Subtracting the plateau from the cohort means leaves an
    excess that decays with an implied constant of 21 ms between 10 and 30 ms and 83 ms
    between 30 and 100 ms, and a single exponential forced through the 10 ms and 100 ms
    points misses the 30 ms point by 3.3 standard errors. Two facilitation components are
    what a synapse with two release-site populations at different calcium-channel
    coupling distances produces, which is the Unc13A/Unc13B picture of Pooryasin and
    colleagues 2021.

    The resource recovery constant is pinned rather than fitted: see
    ``PINNED_RECOVERY_TAU_MS``. The facilitation is additive and has no ceiling, so this
    family's facilitation has no ceiling of its own, though it multiplies a depleting
    resource and so does not run away in a long train.
    """
    fast_step = float(theta[0])
    slow_step, slow_tau = float(theta[1]), float(theta[2])
    utilisation = float(theta[3])
    fast_decay = _decays(gaps, PINNED_FAST_TAU_MS)
    slow_decay = _decays(gaps, slow_tau)
    recovery = _decays(gaps, PINNED_RECOVERY_TAU_MS)
    fast, slow, resource = 0.0, 0.0, 1.0
    out: list[float] = []
    for gap in gaps:
        fast *= fast_decay[gap]
        slow *= slow_decay[gap]
        resource = 1.0 + (resource - 1.0) * recovery[gap]
        out.append((1.0 + fast + slow) * resource)
        fast += fast_step
        slow += slow_step
        resource *= 1.0 - utilisation
    return out


def _amplitudes_two_timescale_facilitation_free(
    gaps: list[float], theta: Sequence[float]
) -> list[float]:
    """M4f: M4 with the fast facilitation constant fitted instead of pinned.

    Carried beside M4 because the pinning is itself a question. M4 asserts that the
    fast constant is below the shortest recorded interval and therefore unresolvable;
    M4f lets the data answer. The two differ by one parameter and by nothing else, so
    whichever of them survives the screens carries the verdict on the assertion.
    """
    fast_step, fast_tau = float(theta[0]), float(theta[1])
    slow_step, slow_tau = float(theta[2]), float(theta[3])
    utilisation = float(theta[4])
    fast_decay = _decays(gaps, fast_tau)
    slow_decay = _decays(gaps, slow_tau)
    recovery = _decays(gaps, PINNED_RECOVERY_TAU_MS)
    fast, slow, resource = 0.0, 0.0, 1.0
    out: list[float] = []
    for gap in gaps:
        fast *= fast_decay[gap]
        slow *= slow_decay[gap]
        resource = 1.0 + (resource - 1.0) * recovery[gap]
        out.append((1.0 + fast + slow) * resource)
        fast += fast_step
        slow += slow_step
        resource *= 1.0 - utilisation
    return out


_SIMULATORS: dict[str, Callable[[list[float], Sequence[float]], list[float]]] = {
    "two-timescale-facilitation": _amplitudes_two_timescale_facilitation,
    "two-timescale-facilitation-free": _amplitudes_two_timescale_facilitation_free,
    "depression-only": _amplitudes_depression_only,
    "facilitation-depression": _amplitudes_facilitation_depression,
    "facilitation-depression-classic": _amplitudes_facilitation_depression_classic,
    "parallel-release-components": _amplitudes_parallel_components,
    "pinned-published-depression": _amplitudes_pinned_published_depression,
}

FAMILIES: dict[str, Family] = {
    "two-timescale-facilitation": Family(
        family_id="two-timescale-facilitation",
        title="M4: two facilitation timescales over a resource whose recovery is pinned",
        parameters=(
            Parameter("fast_step", 0.0, 40.0, "dimensionless", "fast facilitation kick"),
            Parameter("slow_step", 0.0, 10.0, "dimensionless", "slow facilitation kick"),
            Parameter("slow_tau_ms", 20.0, 2000.0, "ms", "slow kick decay constant"),
            Parameter("utilisation", 0.001, 1.0, "fraction", "resource consumed per spike"),
        ),
        mechanism=(
            "Two facilitating release components with different calcium decay constants, "
            "multiplying one depleting resource. Two components are not an extra "
            "flourish here: the fit set's excess over its own plateau decays with an "
            "implied 21 ms between the 10 and 30 ms intervals and 83 ms between the 30 "
            "and 100 ms intervals, and a single exponential forced through the 10 and "
            "100 ms points misses the 30 ms point by 3.3 standard errors."
        ),
        paired_pulse_ceiling=None,
        structural_limits=(
            "Two of its constants are pinned rather than fitted, and neither is a "
            "measurement. The fast facilitation constant is pinned because the shortest "
            "recorded interval is 10 ms, so the data carry one number about a component "
            "that decays faster than that and cannot separate its size from its decay; "
            "fitting both gave a flat ridge along which every prediction was unchanged. "
            "The resource recovery constant is pinned because the 300 ms and 1000 ms "
            "cohort means differ by 0.0003 against a pooled standard error of 0.0277, "
            "which fixes the depth of the plateau and says nothing about its rate. Four "
            "free parameters remain against five means. Its facilitation is additive and "
            "unbounded but multiplies a depleting resource, so it does not run away in "
            "a long train; see the train bound asserted in the test suite."
        ),
    ),
    "two-timescale-facilitation-free": Family(
        family_id="two-timescale-facilitation-free",
        title="M4f: M4 with the fast facilitation constant fitted rather than pinned",
        parameters=(
            Parameter("fast_step", 0.0, 40.0, "dimensionless", "fast facilitation kick"),
            Parameter("fast_tau_ms", 1.0, 200.0, "ms", "fast kick decay constant"),
            Parameter("slow_step", 0.0, 10.0, "dimensionless", "slow facilitation kick"),
            Parameter("slow_tau_ms", 20.0, 2000.0, "ms", "slow kick decay constant"),
            Parameter("utilisation", 0.001, 1.0, "fraction", "resource consumed per spike"),
        ),
        mechanism=(
            "The same two facilitating components as M4 over the same depleting "
            "resource, with the fast time constant fitted. It exists so that the "
            "decision to pin that constant is itself under test rather than assumed."
        ),
        paired_pulse_ceiling=None,
        structural_limits=(
            "Five free parameters against five cohort means leaves no residual degrees "
            "of freedom, so this family has no goodness-of-fit statistic and cannot be "
            "tested in sample at all. Its fast step and fast constant trade off along a "
            "ridge, so neither is separately determined by a curve whose shortest "
            "interval is 10 ms; what the data determine is the fast component's "
            "contribution at that one interval. Its facilitation is additive and "
            "unbounded but multiplies a depleting resource, so it does not run away in "
            "a long train; see the train bound asserted in the test suite."
        ),
    ),
    "depression-only": Family(
        family_id="depression-only",
        title="M0: one depleting resource, the registered ND-06 rule",
        parameters=(
            Parameter("utilisation", 0.001, 1.0, "fraction", "resource consumed per spike"),
            Parameter("recovery_tau_ms", 10.0, 20000.0, "ms", "resource recovery constant"),
        ),
        mechanism=(
            "Presynaptic vesicle depletion alone. Carried as the baseline the successor "
            "has to beat, and as the family whose refutation is already on record."
        ),
        paired_pulse_ceiling=1.0,
        structural_limits=(
            "The paired-pulse ratio is 1 - U exp(-dt/tau): bounded above by one and "
            "increasing in the interval at every parameter setting. Both properties are "
            "contradicted by the measurements, so this family is expected to be "
            "inadmissible and is fitted only to quantify how badly."
        ),
    ),
    "facilitation-depression": Family(
        family_id="facilitation-depression",
        title="M1: release-probability facilitation over a depleting resource",
        parameters=(
            Parameter("resting_utilisation", 0.001, 0.999, "fraction", "utilisation at rest"),
            Parameter("facilitation_increment", 0.0, 0.999, "fraction", "step toward one"),
            Parameter("facilitation_tau_ms", 1.0, 1000.0, "ms", "utilisation decay constant"),
            Parameter("recovery_tau_ms", 10.0, 20000.0, "ms", "resource recovery constant"),
        ),
        mechanism=(
            "The standard two-state Markram-Tsodyks synapse. Residual calcium raises "
            "release probability for tens of milliseconds while the vesicle pool is "
            "depleted for hundreds, so a facilitating short interval and a depressing "
            "long one arise from one mechanism with two time constants."
        ),
        paired_pulse_ceiling=2.0,
        structural_limits=(
            "The four parameters are in bijection with the four quantities a "
            "paired-pulse curve can identify, so nothing here is a fitted direction the "
            "observable cannot see. The ceiling of two is approached only as the resting "
            "utilisation goes to zero, where the response itself vanishes."
        ),
    ),
    "facilitation-depression-classic": Family(
        family_id="facilitation-depression-classic",
        title="M1b: M1 with the facilitation increment tied to the resting utilisation",
        parameters=(
            Parameter("resting_utilisation", 0.001, 0.999, "fraction", "utilisation at rest"),
            Parameter("facilitation_tau_ms", 1.0, 1000.0, "ms", "utilisation decay constant"),
            Parameter("recovery_tau_ms", 10.0, 20000.0, "ms", "resource recovery constant"),
        ),
        mechanism=(
            "The textbook form in which one number sets both the resting release "
            "probability and the facilitation step. One parameter fewer than M1 and, "
            "because of that, a hard ceiling."
        ),
        paired_pulse_ceiling=1.5,
        structural_limits=(
            "Tying the increment to the resting utilisation caps the paired-pulse ratio "
            "at 1.5 in the limit of a vanishing interval and a vanishing utilisation. "
            "The measured 10 ms cohort mean is above that cap, so this family is "
            "expected to fail, and where it fails is informative: it fails on the "
            "amount of facilitation, not on its presence."
        ),
    ),
    "parallel-release-components": Family(
        family_id="parallel-release-components",
        title="M2: a facilitating and a depressing release component in parallel",
        parameters=(
            Parameter("facilitation_step", 0.0, 10.0, "dimensionless", "additive kick"),
            Parameter("facilitation_tau_ms", 1.0, 1000.0, "ms", "kick decay constant"),
            Parameter("utilisation", 0.001, 1.0, "fraction", "depressing pool per spike"),
            Parameter("recovery_tau_ms", 10.0, 20000.0, "ms", "pool recovery constant"),
        ),
        mechanism=(
            "Two populations of release sites summing at the postsynaptic membrane, one "
            "loosely coupled to calcium channels and facilitating, one tightly coupled "
            "and depressing. Pooryasin and colleagues 2021 showed that Unc13A and "
            "Unc13B clusters at a fly central synapse differ in coupling distance and "
            "that 'coupling distance defines release components with distinct STP "
            "characteristics', which is the mechanism this family encodes."
        ),
        paired_pulse_ceiling=None,
        structural_limits=(
            "Its facilitation is additive and has no ceiling of its own, though it sums "
            "with a depleting component rather than multiplying one. On a paired-pulse "
            "curve it differs from M1 only by "
            "the product of the two effects, a term that decays with the facilitation "
            "constant, so the two are expected to be nearly indistinguishable on this "
            "observable and clearly distinguishable on a train. Its resting share is "
            "fixed rather than fitted because a paired-pulse ratio cannot identify it."
        ),
    ),
    "pinned-published-depression": Family(
        family_id="pinned-published-depression",
        title="M3: facilitation added to the published ND-06 depression leg, unchanged",
        parameters=(
            Parameter("facilitation_increment", 0.0, 0.219, "fraction", "step toward one"),
            Parameter("facilitation_tau_ms", 1.0, 1000.0, "ms", "utilisation decay constant"),
        ),
        mechanism=(
            "The minimal repair of the recorded failure: keep Nagel, Hong and Wilson's "
            "utilisation of 0.22 and recovery constant of 893 ms exactly as registered "
            "and add the missing facilitation. If this is admissible, the published "
            "parameters survive and only a mechanism was absent."
        ),
        paired_pulse_ceiling=1.388,
        structural_limits=(
            "Pinning the effective first-pulse utilisation to 0.22 caps the "
            "paired-pulse ratio at (1 + 0.78) * 0.78 = 1.388 as the interval goes to "
            "zero, and pins the long-interval plateau to 1 - 0.22 exp(-dt/893). Both "
            "are testable against the fit set."
        ),
    ),
}

SELECTION_ORDER: tuple[str, ...] = (
    "pinned-published-depression",
    "facilitation-depression-classic",
    "facilitation-depression",
    "parallel-release-components",
    "two-timescale-facilitation",
    "two-timescale-facilitation-free",
    "depression-only",
)


def family(family_id: str) -> Family:
    if family_id not in FAMILIES:
        raise ConfigurationError(
            f"Unknown short-term-plasticity family {family_id!r}; "
            f"expected one of {sorted(FAMILIES)}"
        )
    return FAMILIES[family_id]


def _run(family_id: str, theta: Sequence[float], gaps: list[float]) -> list[float]:
    """Dispatch to one family's recursion. The hot path: no numpy, no allocation."""
    spec = family(family_id)
    if len(theta) != spec.parameter_count:
        raise ConfigurationError(
            f"{family_id} takes {spec.parameter_count} parameters, got {len(theta)}"
        )
    return _SIMULATORS[family_id](gaps, theta)


def amplitudes(
    family_id: str, theta: Sequence[float], spike_times_ms: Sequence[float]
) -> np.ndarray:
    """Response amplitudes at the given spike times, relative to a resting first spike."""
    times = [float(value) for value in spike_times_ms]
    if not times:
        raise ConfigurationError("A spike train needs at least one spike")
    gaps = [0.0]
    for earlier, later in pairwise(times):
        if later < earlier:
            raise ConfigurationError("Spike times must be non-decreasing")
        gaps.append(later - earlier)
    return np.array(_run(family_id, theta, gaps), dtype=np.float64)


_PROTOCOL_GAPS: dict[float, list[float]] = {}


def _protocol_gaps(interval_ms: float) -> list[float]:
    """The gap sequence for twenty pairs at 0.2 Hz, built once per interval.

    Two distinct gaps repeated twenty times each. Caching the list and reusing it means
    the fitter's inner loop allocates nothing at all.
    """
    cached = _PROTOCOL_GAPS.get(interval_ms)
    if cached is None:
        rest = PAIR_PERIOD_MS - interval_ms
        cached = [0.0, interval_ms]
        for _ in range(PAIRS_AVERAGED - 1):
            cached.extend((rest, interval_ms))
        _PROTOCOL_GAPS[interval_ms] = cached
    return cached


def paired_pulse(
    family_id: str,
    theta: Sequence[float],
    interval_ms: float,
    *,
    from_rest: bool = False,
) -> float:
    """The paired-pulse ratio this family produces under the recorded protocol.

    By default the twenty pairs at 0.2 Hz that the authors averaged are simulated and
    the ratio is the mean second response over the mean first response, which is what
    averaging twenty traces and then measuring two amplitudes computes. Passing
    ``from_rest`` returns the single-pair-from-rest value instead, so the size of the
    protocol correction can be read off.
    """
    if interval_ms <= 0.0:
        raise ConfigurationError("A paired-pulse interval must be positive")
    if interval_ms >= PAIR_PERIOD_MS:
        raise ConfigurationError(
            f"An interval of {interval_ms} ms does not fit inside the "
            f"{PAIR_PERIOD_MS} ms pair repetition period"
        )
    if from_rest:
        values = _run(family_id, theta, [0.0, interval_ms])
        return values[1] / values[0]
    values = _run(family_id, theta, _protocol_gaps(interval_ms))
    first = 0.0
    second = 0.0
    for index in range(PAIRS_AVERAGED):
        first += values[2 * index]
        second += values[2 * index + 1]
    return second / first


KAZAMA_WILSON_RELEASE_PROBABILITY = 0.79


def effective_first_pulse_utilisation(family_id: str, theta: Sequence[float]) -> float:
    """The fraction of the resource one resting spike consumes, family by family.

    This is the quantity that maps onto a measured release probability, and it is
    reported for every family so that a fit which can only reproduce this curve by
    putting the release probability far below Kazama and Wilson's measured 0.79 says so
    out loud. It gates nothing: the mapping needs one vesicle per site and no
    within-pair recovery, and the ND-06 registry already records those as the reason the
    variance-derived value was not adopted in the first place.
    """
    spec = family(family_id)
    if len(theta) != spec.parameter_count:
        raise ConfigurationError(
            f"{family_id} takes {spec.parameter_count} parameters, got {len(theta)}"
        )
    if family_id == "depression-only":
        return float(theta[0])
    if family_id == "facilitation-depression":
        resting, increment = float(theta[0]), float(theta[1])
        return increment + (1.0 - increment) * resting
    if family_id == "facilitation-depression-classic":
        resting = float(theta[0])
        return resting + (1.0 - resting) * resting
    if family_id == "pinned-published-depression":
        return NAGEL_UTILISATION
    if family_id == "parallel-release-components":
        # Only the depressing component depletes, and it carries half the resting
        # response, so the response-weighted depletion is that share of its utilisation.
        return (1.0 - PARALLEL_SHARE) * float(theta[2])
    if family_id == "two-timescale-facilitation":
        return float(theta[3])
    if family_id == "two-timescale-facilitation-free":
        return float(theta[4])
    raise ConfigurationError(f"No first-pulse utilisation defined for {family_id!r}")


def predict(family_id: str, theta: Sequence[float], intervals_ms: Sequence[float]) -> np.ndarray:
    return np.array(
        [paired_pulse(family_id, theta, float(interval)) for interval in intervals_ms],
        dtype=np.float64,
    )


# --------------------------------------------------------------------------------------
# The fitter. Nelder-Mead over a sigmoid-transformed box, restarted from a seeded
# Latin-hypercube sample. scipy is not a declared dependency of this project.
# --------------------------------------------------------------------------------------


KAZAMA_WILSON_RELEASE_PROBABILITY_SD = 0.02


def single_pool_paired_pulse_ceiling(
    *, release_probability: float, interval_ms: float, recovery_tau_ms: float
) -> float:
    """The largest paired-pulse ratio one homogeneous pool can produce, at any facilitation.

    Take N release sites, each holding at most one vesicle, each releasing with probability
    ``p1`` at rest; let the second pulse release with probability ``p2``, and let a site
    that released be unavailable until it recovers with the given constant. Then

        R1 = N p1 q,   R2 = N p2 (1 - p1 e^{-dt/tau}) q,
        PPR = (p2 / p1) (1 - p1 e^{-dt/tau})  <=  (1 - p1 e^{-dt/tau}) / p1

    because no facilitation can push a probability above one. The bound is deliberately
    generous: it allows instantaneous facilitation to certainty, no desensitisation, no
    postsynaptic saturation and a quantal size that does not change.

    It matters because Kazama and Wilson measured a release probability of 0.79 at this
    synapse and Rozenfeld and colleagues measured a paired-pulse ratio of 1.51 at 10 ms.
    Those two numbers are not merely in tension under a single-pool model; they are
    incompatible with it by a factor of about five and a half, and no facilitation
    mechanism can close the gap.
    """
    if not 0.0 < release_probability <= 1.0:
        raise ConfigurationError("A release probability must lie in (0, 1]")
    if interval_ms < 0.0:
        raise ConfigurationError("An interval cannot be negative")
    if recovery_tau_ms <= 0.0:
        raise ConfigurationError("A recovery time constant must be positive")
    survived = math.exp(-interval_ms / recovery_tau_ms)
    return (1.0 - release_probability * survived) / release_probability


def maximum_single_pool_release_probability(
    *, paired_pulse_ratio: float, interval_ms: float, recovery_tau_ms: float
) -> float:
    """The largest resting release probability compatible with an observed ratio.

    The inverse of :func:`single_pool_paired_pulse_ceiling`: solving
    ``(1 - p e^{-dt/tau}) / p >= PPR`` gives ``p <= 1 / (PPR + e^{-dt/tau})``. A measured
    ratio above one therefore caps the resting release probability below one half, whatever
    facilitation is invoked.
    """
    if paired_pulse_ratio <= 0.0:
        raise ConfigurationError("A paired-pulse ratio must be positive")
    if interval_ms < 0.0:
        raise ConfigurationError("An interval cannot be negative")
    if recovery_tau_ms <= 0.0:
        raise ConfigurationError("A recovery time constant must be positive")
    return 1.0 / (paired_pulse_ratio + math.exp(-interval_ms / recovery_tau_ms))


def _to_box(unbounded: np.ndarray, spec: Family) -> np.ndarray:
    low = np.array([parameter.low for parameter in spec.parameters])
    high = np.array([parameter.high for parameter in spec.parameters])
    inside = low + (high - low) / (1.0 + np.exp(-np.clip(unbounded, -40.0, 40.0)))
    return np.asarray(inside, dtype=np.float64)


def _from_box(inside: np.ndarray, spec: Family) -> np.ndarray:
    low = np.array([parameter.low for parameter in spec.parameters])
    high = np.array([parameter.high for parameter in spec.parameters])
    fraction = np.clip((inside - low) / (high - low), 1e-9, 1.0 - 1e-9)
    return np.asarray(np.log(fraction / (1.0 - fraction)), dtype=np.float64)


def nelder_mead(
    objective: Callable[[np.ndarray], float],
    start: np.ndarray,
    *,
    step: float = 0.8,
    iterations: int = 2000,
    tolerance: float = 1e-10,
) -> tuple[np.ndarray, float]:
    """A plain Nelder-Mead simplex. Returns the best vertex and its objective value.

    The convergence test needs both halves. A relative test on the objective alone
    never fires when the minimum is at zero, which a saturated fit's is, and the search
    then burns its whole iteration budget on a converged simplex; a test on the simplex
    alone stops early on a flat ridge. Both are required, and the objective half carries
    an absolute floor for exactly the zero-minimum case.
    """
    dimension = start.size
    simplex = np.repeat(start.reshape(1, -1), dimension + 1, axis=0)
    for index in range(dimension):
        simplex[index + 1, index] += step
    values = np.array([objective(vertex) for vertex in simplex], dtype=np.float64)
    for _ in range(iterations):
        order = np.argsort(values)
        simplex, values = simplex[order], values[order]
        spread = float(values[-1] - values[0])
        extent = float(np.max(np.abs(simplex[1:] - simplex[0])))
        if spread <= tolerance * (1.0 + abs(values[0])) and extent <= 1e-7:
            break
        centroid = simplex[:-1].mean(axis=0)
        reflected = centroid + (centroid - simplex[-1])
        reflected_value = objective(reflected)
        if reflected_value < values[0]:
            expanded = centroid + 2.0 * (centroid - simplex[-1])
            expanded_value = objective(expanded)
            if expanded_value < reflected_value:
                simplex[-1], values[-1] = expanded, expanded_value
            else:
                simplex[-1], values[-1] = reflected, reflected_value
        elif reflected_value < values[-2]:
            simplex[-1], values[-1] = reflected, reflected_value
        else:
            contracted = centroid + 0.5 * (simplex[-1] - centroid)
            contracted_value = objective(contracted)
            if contracted_value < values[-1]:
                simplex[-1], values[-1] = contracted, contracted_value
            else:
                simplex[1:] = simplex[0] + 0.5 * (simplex[1:] - simplex[0])
                values[1:] = np.array([objective(vertex) for vertex in simplex[1:]])
    order = np.argsort(values)
    return simplex[order][0], float(values[order][0])


@dataclass(frozen=True, slots=True)
class Observation:
    """One cohort mean at one interval, with the spread the fit is weighted by."""

    interval_ms: float
    mean: float
    standard_error: float
    animals: int


@dataclass(frozen=True, slots=True)
class Fit:
    """The outcome of fitting one family to one set of observations."""

    family_id: str
    theta: tuple[float, ...]
    weighted_sse: float
    predicted: tuple[float, ...]
    degrees_of_freedom: int
    goodness_of_fit_p: float | None
    at_bound: tuple[str, ...]
    restarts: int

    def as_dict(self) -> dict[str, Any]:
        spec = family(self.family_id)
        return {
            "family_id": self.family_id,
            "parameters": dict(zip(spec.parameter_names, self.theta, strict=True)),
            "weighted_sse": self.weighted_sse,
            "predicted": list(self.predicted),
            "degrees_of_freedom": self.degrees_of_freedom,
            "goodness_of_fit_p": self.goodness_of_fit_p,
            "goodness_of_fit_is_undefined": self.degrees_of_freedom < 1,
            "parameters_at_a_bound": list(self.at_bound),
            "restarts": self.restarts,
        }


def weighted_sse(
    family_id: str, theta: Sequence[float], observations: Sequence[Observation]
) -> float:
    """Sum of squared residuals in units of the cohort standard error."""
    total = 0.0
    for observation in observations:
        predicted = paired_pulse(family_id, theta, observation.interval_ms)
        total += ((predicted - observation.mean) / observation.standard_error) ** 2
    return total


def _latin_hypercube(spec: Family, draws: int, rng: np.random.Generator) -> np.ndarray:
    """A stratified start set, with the time constants stratified logarithmically."""
    columns = []
    for index, parameter in enumerate(spec.parameters):
        edges = (rng.permutation(draws) + rng.random(draws)) / draws
        if parameter.name.endswith("_ms"):
            low, high = math.log(parameter.low), math.log(parameter.high)
            columns.append(np.exp(low + edges * (high - low)))
        else:
            span = parameter.high - parameter.low
            columns.append(parameter.low + 0.02 * span + edges * 0.96 * span)
        del index
    return np.column_stack(columns)


def fit_family(
    family_id: str,
    observations: Sequence[Observation],
    *,
    restarts: int = 40,
    seed: int = 20260910,
) -> Fit:
    """Fit one family by weighted least squares, restarted from a stratified sample."""
    spec = family(family_id)
    if len(observations) < spec.parameter_count:
        raise ConfigurationError(
            f"{family_id} has {spec.parameter_count} parameters and cannot be fitted to "
            f"{len(observations)} observations"
        )
    rng = np.random.default_rng(seed)
    starts = _latin_hypercube(spec, restarts, rng)

    def objective(unbounded: np.ndarray) -> float:
        return weighted_sse(
            family_id, [float(value) for value in _to_box(unbounded, spec)], observations
        )

    best_theta: np.ndarray | None = None
    best_value = math.inf
    for start in starts:
        candidate, value = nelder_mead(objective, _from_box(start, spec))
        if value < best_value:
            best_theta, best_value = candidate, value
    assert best_theta is not None
    theta = [float(value) for value in _to_box(best_theta, spec)]
    degrees = len(observations) - spec.parameter_count
    return Fit(
        family_id=family_id,
        theta=tuple(float(value) for value in theta),
        weighted_sse=float(best_value),
        predicted=tuple(
            float(paired_pulse(family_id, theta, observation.interval_ms))
            for observation in observations
        ),
        degrees_of_freedom=degrees,
        goodness_of_fit_p=(
            chi_square_upper_tail(float(best_value), degrees) if degrees >= 1 else None
        ),
        at_bound=tuple(
            parameter.name
            for parameter, value in zip(spec.parameters, theta, strict=True)
            if (value - parameter.low) < 0.01 * (parameter.high - parameter.low)
            or (parameter.high - value) < 0.01 * (parameter.high - parameter.low)
        ),
        restarts=restarts,
    )


def chi_square_upper_tail(statistic: float, degrees: int) -> float:
    """The upper tail of the chi-square distribution, by the regularised gamma function.

    Hand-rolled for the same reason the t quantile was: scipy is not a dependency and a
    goodness-of-fit p-value with one to three degrees of freedom is what decides whether
    a family is admissible, so it cannot be approximated.
    """
    if degrees < 1:
        raise ConfigurationError("A chi-square tail needs at least one degree of freedom")
    if statistic < 0.0:
        raise ConfigurationError("A chi-square statistic cannot be negative")
    return _regularised_gamma_upper(0.5 * degrees, 0.5 * statistic)


def _regularised_gamma_upper(shape: float, value: float) -> float:
    if value <= 0.0:
        return 1.0
    if value < shape + 1.0:
        return 1.0 - _gamma_series(shape, value)
    return _gamma_continued_fraction(shape, value)


def _gamma_series(shape: float, value: float) -> float:
    total = 1.0 / shape
    term = total
    for index in range(1, 1000):
        term *= value / (shape + index)
        total += term
        if abs(term) < abs(total) * 1e-16:
            break
    return total * math.exp(-value + shape * math.log(value) - math.lgamma(shape))


def _gamma_continued_fraction(shape: float, value: float) -> float:
    tiny = 1e-300
    b = value + 1.0 - shape
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for index in range(1, 1000):
        an = -index * (index - shape)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return h * math.exp(-value + shape * math.log(value) - math.lgamma(shape))


def leave_one_out(
    family_id: str,
    observations: Sequence[Observation],
    *,
    restarts: int = 24,
    seed: int = 20260910,
) -> dict[str, Any]:
    """Refit without each interval in turn and score the prediction at the held-out one.

    With five points and four parameters the training fit is nearly exact and the
    held-out point is an extrapolation, so this statistic is reported but is not the
    primary selection criterion. Recording why it cannot be is part of the result.
    """
    spec = family(family_id)
    rows: list[dict[str, Any]] = []
    total = 0.0
    for index, held_out in enumerate(observations):
        training = [row for position, row in enumerate(observations) if position != index]
        if len(training) < spec.parameter_count:
            rows.append(
                {
                    "interval_ms": held_out.interval_ms,
                    "scored": False,
                    "why_not": (
                        f"{len(training)} training points cannot determine "
                        f"{spec.parameter_count} parameters"
                    ),
                }
            )
            continue
        fitted = fit_family(family_id, training, restarts=restarts, seed=seed + index)
        predicted = paired_pulse(family_id, fitted.theta, held_out.interval_ms)
        residual = ((predicted - held_out.mean) / held_out.standard_error) ** 2
        total += residual
        rows.append(
            {
                "interval_ms": held_out.interval_ms,
                "scored": True,
                "predicted": predicted,
                "observed": held_out.mean,
                "weighted_squared_error": residual,
                "training_points": len(training),
                "training_degrees_of_freedom": len(training) - spec.parameter_count,
            }
        )
    scored = [row for row in rows if row["scored"]]
    return {
        "total_weighted_squared_error": total if scored else None,
        "intervals_scored": len(scored),
        "saturated": all(row.get("training_degrees_of_freedom") == 0 for row in scored),
        "by_interval": rows,
    }


def synthetic_recovery(
    family_id: str,
    theta: Sequence[float],
    observations: Sequence[Observation],
    *,
    replicates: int = 200,
    restarts: int = 16,
    seed: int = 20260910,
) -> dict[str, Any]:
    """Refit the family on data it generated itself, to see which parameters come back.

    A parameter that cannot be recovered from noise-free-in-expectation data at the
    measured noise level is not a parameter this observable constrains, whatever the
    point fit says. This is the check that decides admissibility alongside goodness of
    fit.
    """
    spec = family(family_id)
    rng = np.random.default_rng(seed)
    truth = predict(family_id, theta, [row.interval_ms for row in observations])
    errors = np.array([row.standard_error for row in observations])
    recovered = np.empty((replicates, spec.parameter_count), dtype=np.float64)
    for replicate in range(replicates):
        noisy = truth + rng.normal(0.0, errors)
        surrogate = [
            Observation(
                interval_ms=row.interval_ms,
                mean=float(value),
                standard_error=row.standard_error,
                animals=row.animals,
            )
            for row, value in zip(observations, noisy, strict=True)
        ]
        fitted = fit_family(
            family_id, surrogate, restarts=restarts, seed=int(rng.integers(1, 2**31 - 1))
        )
        recovered[replicate] = fitted.theta
    summary: dict[str, Any] = {"replicates": replicates, "parameters": {}}
    for index, parameter in enumerate(spec.parameters):
        column = recovered[:, index]
        true_value = float(theta[index])
        low, high = (float(value) for value in np.percentile(column, (5.0, 95.0)))
        summary["parameters"][parameter.name] = {
            "true": true_value,
            "median": float(np.median(column)),
            "percentile_5": low,
            "percentile_95": high,
            "median_relative_bias": float(np.median(column) - true_value) / true_value
            if true_value != 0.0
            else None,
            "interval_width_over_true": (high - low) / true_value if true_value != 0.0 else None,
        }
    return summary


def discrimination(
    generating: str,
    generating_theta: Sequence[float],
    competitor: str,
    observations: Sequence[Observation],
    *,
    replicates: int = 200,
    restarts: int = 16,
    seed: int = 20260910,
) -> dict[str, Any]:
    """How often the generating family beats a competitor on data it generated.

    Two families that fit a paired-pulse curve equally well are not two hypotheses this
    observable can choose between, and this quantifies that directly rather than
    inferring it from parameter counts.
    """
    rng = np.random.default_rng(seed)
    truth = predict(generating, generating_theta, [row.interval_ms for row in observations])
    errors = np.array([row.standard_error for row in observations])
    margins = np.empty(replicates, dtype=np.float64)
    for replicate in range(replicates):
        noisy = truth + rng.normal(0.0, errors)
        surrogate = [
            Observation(
                interval_ms=row.interval_ms,
                mean=float(value),
                standard_error=row.standard_error,
                animals=row.animals,
            )
            for row, value in zip(observations, noisy, strict=True)
        ]
        child = int(rng.integers(1, 2**31 - 1))
        own = fit_family(generating, surrogate, restarts=restarts, seed=child)
        other = fit_family(competitor, surrogate, restarts=restarts, seed=child)
        margins[replicate] = other.weighted_sse - own.weighted_sse
    return {
        "generating_family": generating,
        "competitor": competitor,
        "replicates": replicates,
        "generating_family_wins_fraction": float(np.mean(margins > 0.0)),
        "median_sse_margin": float(np.median(margins)),
        "percentile_95_sse_margin": float(np.percentile(margins, 95.0)),
        "reading": (
            "A margin near zero means the competitor reproduces data the generating "
            "family made, so the two are not separable on this observable."
        ),
    }


def bootstrap_predictions(
    family_id: str,
    samples: dict[float, np.ndarray],
    intervals_ms: Sequence[float],
    *,
    replicates: int = 400,
    restarts: int = 12,
    seed: int = 20260910,
) -> dict[str, Any]:
    """Resample animals within each interval, refit, and band the predictions.

    Resampling is independent per interval because the source arrays carry no animal
    identifier, so an animal recorded at several intervals cannot be kept together. The
    real design is partly within-animal, which makes this band somewhat too wide at the
    correlated directions and somewhat too narrow at none of them; it is reported as the
    band it is.
    """
    rng = np.random.default_rng(seed)
    ordered = sorted(samples)
    curves = np.empty((replicates, len(intervals_ms)), dtype=np.float64)
    thetas = np.empty((replicates, family(family_id).parameter_count), dtype=np.float64)
    for replicate in range(replicates):
        observations = []
        for interval in ordered:
            values = samples[interval]
            drawn = values[rng.integers(0, values.size, values.size)]
            observations.append(
                Observation(
                    interval_ms=interval,
                    mean=float(drawn.mean()),
                    standard_error=float(drawn.std(ddof=1) / math.sqrt(drawn.size)),
                    animals=int(drawn.size),
                )
            )
        fitted = fit_family(
            family_id, observations, restarts=restarts, seed=int(rng.integers(1, 2**31 - 1))
        )
        thetas[replicate] = fitted.theta
        curves[replicate] = predict(family_id, fitted.theta, intervals_ms)
    spec = family(family_id)
    return {
        "replicates": replicates,
        "by_interval": [
            {
                "interval_ms": float(interval),
                "percentile_2_5": float(np.percentile(curves[:, index], 2.5)),
                "median": float(np.median(curves[:, index])),
                "percentile_97_5": float(np.percentile(curves[:, index], 97.5)),
            }
            for index, interval in enumerate(intervals_ms)
        ],
        "parameters": {
            parameter.name: {
                "percentile_2_5": float(np.percentile(thetas[:, index], 2.5)),
                "median": float(np.median(thetas[:, index])),
                "percentile_97_5": float(np.percentile(thetas[:, index], 97.5)),
            }
            for index, parameter in enumerate(spec.parameters)
        },
        "resampling_unit": "animals within an interval, independently across intervals",
    }
