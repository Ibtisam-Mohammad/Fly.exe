# SPDX-License-Identifier: GPL-2.0-or-later
"""DEMO-01 visual route: retinotopic entry at the lamina, whole optic lobe in the loop.

The odour route this replaces failed for structural reasons, measured on the exact graph
rather than guessed. There are no direct ORN-to-DNa edges; the path is three synapses; the
signed contact-share flow arriving at the four steering descending neurons was 6.6e-05 of
the injected signal, about one part in fifteen thousand, onto cells that each integrate
750 to 1200 inputs at an excitatory-to-inhibitory contact ratio between 1.17 and 2.04; and
laterality was *contralaterally* biased at the first hop and gone by the third. No choice
of gain could repair that, because a gain scales both sides equally.

The visual route was chosen after measuring every alternative the released annotations
offer. What the measurements say:

* **Photoreceptors cannot be the entry.** They do carry 66,533 outgoing edges over 4,045
  of 4,114 bodies, but *every one of those edges is zeroed by the frozen sign policy* --
  100.0% of edges and 100.0% of contacts, for R1-R6, R7 and R8 alike. Fly photoreceptors
  are histaminergic and histamine is absent from the transmitter model, so the consensus
  prediction is unresolved and the registered `zero` policy removes them. Inventing a sign
  for 66,533 edges to enable a demonstration would be a larger fabrication than entering
  one synapse downstream, so the retina-to-lamina synapse is declared as the one link this
  demonstration cannot execute.
* **The lamina monopolar cells can.** L1 through L5, 8,883 bodies, of which 69.8% carry
  released column coordinates (L1, L2 and L5 at about 99%, L3 at 50%, L4 at none), over
  877 distinct left-eye columns spanning hex1 1..36 and hex2 1..39. Their output is not
  zeroed: L1 is predicted wholly inhibitory and L2 through L5 wholly excitatory, which is
  the ON/OFF split of the lamina, so the relative L1 drive is searched rather than assumed.
* **Retinotopy survives to the lobula.** Two disjoint hex patches of the left lamina drive
  LC4 response vectors whose cosine similarity is +0.000 -- fully orthogonal. Different
  parts of the visual field reach different LC4 cells.
* **Laterality survives to the descending layer.** A left-eye patch reaches descending
  neurons at hop 3 with left/right flow +2.5e-03 against -2.0e-05, an index of +1.000.
* **The optic lobe participates functionally.** 59,799 of 99,154 optic-lobe neurons are
  reached at the first hop and 99,128 at the second; all 1,304 descending neurons by the
  third. The 89,390-neuron optic lobe is doing the visual computation, not being stepped
  beside it.

So the loop is::

    visual scene -> retinotopic lamina drive -> 99,154-neuron optic lobe
                 -> LC4/LPLC2/LC10a -> descending neurons -> E decoder -> MuJoCo body
                 -> the cue moves in the visual field

One consequence is recorded rather than hidden. The strongest route in this connectome is
looming to escape descending neurons, and the canonical approach route (LC10a to AOTU019
to DNa02) is both 23 times weaker and predicted *inhibitory* at its final synapse. The
declared behaviour target is therefore a cue-side-dependent turn whose **sign is read off
the frozen network**, not chosen in advance. Turning toward the cue and turning away from
it are both acceptable outcomes; which one occurs is a measured property.

Every parameter in this module is P/E or E. Nothing here is validated physiology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from flysim.contracts import NeuralInputFrame, SignalType
from flysim.demo01 import Demo01Populations, PopulationSpec, selectivity_index
from flysim.errors import ConfigurationError

# --------------------------------------------------------------------------------------
# Declared populations
# --------------------------------------------------------------------------------------

# Entry: the lamina monopolar cells, split by pathway because their predicted signs
# differ. L1 output is inhibitory and L2-L5 excitatory, so driving them together and
# driving them separately are different experiments; the balance is a searched axis.
VISUAL_ENTRY_SPECS: tuple[PopulationSpec, ...] = (
    PopulationSpec(
        "lamina-on-left", "L1", "L", "somaSide",
        "ON-pathway lamina monopolar, predicted inhibitory output",
    ),
    PopulationSpec(
        "lamina-on-right", "L1", "R", "somaSide",
        "ON-pathway lamina monopolar, predicted inhibitory output",
    ),
    PopulationSpec(
        "lamina-off-left", "L2", "L", "somaSide",
        "OFF-pathway lamina monopolar, predicted excitatory output",
    ),
    PopulationSpec(
        "lamina-off-right", "L2", "R", "somaSide",
        "OFF-pathway lamina monopolar, predicted excitatory output",
    ),
    PopulationSpec(
        "lamina-wide-left", "L5", "L", "somaSide",
        "wide-field lamina monopolar, predicted excitatory output",
    ),
    PopulationSpec(
        "lamina-wide-right", "L5", "R", "somaSide",
        "wide-field lamina monopolar, predicted excitatory output",
    ),
)

# L3 and L4 are deliberately excluded, and the reason is a property of the release rather
# than a modelling choice. Released column coordinates cover L3 on the right (892 bodies)
# and not at all on the left (0 of 880); L4 carries none on either side. Driving them
# would put a two-fold left-right imbalance into the entry layer before any dynamics ran,
# which is precisely the confound the reversal criterion exists to catch. L1, L2 and L5
# are 98.4 to 100 per cent covered and balanced at about 875 left against 893 right.
LAMINA_TYPES_EXCLUDED_FOR_MISSING_COLUMNS = {
    "L3": "columns released on the right only: 892 of 892 right, 0 of 880 left",
    "L4": "no released column coordinates on either side",
}

# Readout, three tiers, every one declared by released annotation columns.
#
# The odour search produced selectivity indices of exactly +-1.000 from a single spike
# against zero, which is why the narrow tiers are no longer read alone: 4 and 2 bodies per
# side cannot average away the spike quantum at a 15 ms coupling interval. The pool tier
# has 656 and 648 bodies and can.
VISUAL_READOUT_SPECS: tuple[PopulationSpec, ...] = (
    PopulationSpec(
        "dn-loom-left", "DNp02", "L", "somaSide",
        "looming-responsive escape descending neurons",
        additional_types=("DNp03", "DNp04", "DNp06"),
    ),
    PopulationSpec(
        "dn-loom-right", "DNp02", "R", "somaSide",
        "looming-responsive escape descending neurons",
        additional_types=("DNp03", "DNp04", "DNp06"),
    ),
    PopulationSpec(
        "dn-steer-left", "DNa01", "L", "somaSide",
        "steering descending neurons",
        additional_types=("DNa02",),
    ),
    PopulationSpec(
        "dn-steer-right", "DNa01", "R", "somaSide",
        "steering descending neurons",
        additional_types=("DNa02",),
    ),
    PopulationSpec(
        "dn-visual-left", "DNp", "L", "somaSide",
        "posterior descending group, the visually driven descending population",
        type_prefixes=("DNp",),
    ),
    PopulationSpec(
        "dn-visual-right", "DNp", "R", "somaSide",
        "posterior descending group, the visually driven descending population",
        type_prefixes=("DNp",),
    ),
    PopulationSpec(
        "dn-pool-left", "descending_neuron", "L", "somaSide",
        "every descending neuron on the left, recorded as the whole-population reference",
        match_column="superclass",
    ),
    PopulationSpec(
        "dn-pool-right", "descending_neuron", "R", "somaSide",
        "every descending neuron on the right, recorded as the whole-population reference",
        match_column="superclass",
    ),
)

# The population pair the decoder actually steers on. Declared here rather than inferred
# so that changing it is a visible edit to a named constant.
#
# Why the posterior descending group and not the whole pool. Measured on the exact graph
# with the whole LC/LPLC/LLPC family as driver:
#
#     group             L    R   LC share of input   laterality h1/h2/h3
#     all descending  656  648               3.56%   +0.918 / +0.318 / +0.526
#     DNp*            160  158               8.83%   +0.961 / +0.504 / +0.420
#     DNa*             26   26               2.71%   +0.721 / +0.241 / +1.000
#     DNg*            426  422               0.44%   +0.727 / +0.098 / +0.312
#     DNp02/03/04/06    4    4              38.03%   +0.994 / +0.894 / +1.000
#
# The whole pool is two thirds DNg and DNge, 848 of 1,304 bodies, which take 0.44 per cent
# of their input from visual projection neurons. Averaging a lateralised visual signal into
# a population that is mostly visually blind is what held the measured index at 0.03 to
# 0.09. DNp* keeps the drive and the laterality while staying large enough that its index
# is a rate comparison rather than a spike count. The laterality figures average the
# left-driver and right-driver measurements, so a fixed anatomical asymmetry cancels.
VISUAL_LEFT_READOUT = "dn-visual-left"
VISUAL_RIGHT_READOUT = "dn-visual-right"

VISUAL_MONITOR_POOLS: dict[str, dict[str, str]] = {
    "photoreceptors": {"column": "superclass", "value": "ol_sensory"},
    "optic-lobe": {"column": "superclass", "value": "ol_intrinsic"},
    "visual-projection": {"column": "superclass", "value": "visual_projection"},
    "central-brain": {"column": "superclass", "value": "cb_intrinsic"},
    "descending-all": {"column": "superclass", "value": "descending_neuron"},
    "vnc-intrinsic": {"column": "superclass", "value": "vnc_intrinsic"},
    "vnc-motor-all": {"column": "superclass", "value": "vnc_motor"},
}


# --------------------------------------------------------------------------------------
# The declared retinal map and visual encoder
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetinaMap:
    """A declared linear map from visual direction to released column coordinates.

    The released table gives every lamina cell a column index pair but no visual
    direction, so a map has to be declared. This one is linear and deliberately simple:
    azimuth measured from straight ahead runs along hex1 and elevation along hex2, over
    the spans given here. It is P/E. It is not a measured optical axis, and the demo makes
    no claim that column (17, 20) looks at any particular point in the world.

    Azimuth is signed in the ipsilateral direction: for the left eye, a cue to the fly's
    left has positive ipsilateral azimuth.
    """

    hex1_min: float
    hex1_max: float
    hex2_min: float
    hex2_max: float
    azimuth_min_deg: float
    azimuth_max_deg: float
    elevation_min_deg: float
    elevation_max_deg: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> RetinaMap:
        values = cls(
            hex1_min=float(raw["hex1_min"]),
            hex1_max=float(raw["hex1_max"]),
            hex2_min=float(raw["hex2_min"]),
            hex2_max=float(raw["hex2_max"]),
            azimuth_min_deg=float(raw["azimuth_min_deg"]),
            azimuth_max_deg=float(raw["azimuth_max_deg"]),
            elevation_min_deg=float(raw["elevation_min_deg"]),
            elevation_max_deg=float(raw["elevation_max_deg"]),
        )
        if values.hex1_max <= values.hex1_min or values.hex2_max <= values.hex2_min:
            raise ConfigurationError("Retinal column spans must be increasing")
        if values.azimuth_max_deg <= values.azimuth_min_deg:
            raise ConfigurationError("Retinal azimuth span must be increasing")
        if values.elevation_max_deg <= values.elevation_min_deg:
            raise ConfigurationError("Retinal elevation span must be increasing")
        return values

    def column_for(self, azimuth_deg: float, elevation_deg: float) -> tuple[float, float]:
        """Which column a visual direction lands on. Unclamped, so off-eye stays off-eye."""
        a = (azimuth_deg - self.azimuth_min_deg) / (
            self.azimuth_max_deg - self.azimuth_min_deg
        )
        e = (elevation_deg - self.elevation_min_deg) / (
            self.elevation_max_deg - self.elevation_min_deg
        )
        return (
            self.hex1_min + a * (self.hex1_max - self.hex1_min),
            self.hex2_min + e * (self.hex2_max - self.hex2_min),
        )

    def columns_per_degree(self) -> float:
        return (self.hex1_max - self.hex1_min) / (self.azimuth_max_deg - self.azimuth_min_deg)

    def as_dict(self) -> dict[str, Any]:
        return {
            "hex1_span": [self.hex1_min, self.hex1_max],
            "hex2_span": [self.hex2_min, self.hex2_max],
            "azimuth_span_deg": [self.azimuth_min_deg, self.azimuth_max_deg],
            "elevation_span_deg": [self.elevation_min_deg, self.elevation_max_deg],
            "columns_per_degree": self.columns_per_degree(),
            "provenance": "P/E",
            "what_this_is_not": (
                "Not a measured optical axis. The released table carries column indices "
                "but no visual direction, so this linear correspondence is declared."
            ),
        }


@dataclass(frozen=True, slots=True)
class VisualCue:
    """A cue in the world: a position, a physical radius and a contrast polarity."""

    x_mm: float
    y_mm: float
    radius_mm: float
    dark: bool = True

    def geometry_from(
        self, *, x_mm: float, y_mm: float, heading_rad: float
    ) -> tuple[float, float]:
        """Signed bearing in degrees (positive to the fly's left) and angular radius."""
        dx, dy = self.x_mm - x_mm, self.y_mm - y_mm
        distance = math.hypot(dx, dy)
        bearing = math.atan2(dy, dx) - heading_rad
        bearing = math.atan2(math.sin(bearing), math.cos(bearing))
        # Angular radius, saturating at a hemisphere when the cue engulfs the eye.
        ratio = self.radius_mm / distance if distance > self.radius_mm else 1.0
        angular_radius = math.degrees(math.asin(min(1.0, max(-1.0, ratio))))
        return math.degrees(bearing), angular_radius


@dataclass(frozen=True, slots=True)
class VisualEncodingParameters:
    """World-to-lamina transduction. P/E: a declared receptive-field shape."""

    lamina_max_rate_hz: float
    lamina_baseline_rate_hz: float
    lamina_on_off_balance: float
    receptive_field_sigma_columns: float
    loom_half_angle_deg: float

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> VisualEncodingParameters:
        values = cls(
            lamina_max_rate_hz=float(raw["lamina_max_rate_hz"]),
            lamina_baseline_rate_hz=float(raw["lamina_baseline_rate_hz"]),
            lamina_on_off_balance=float(raw["lamina_on_off_balance"]),
            receptive_field_sigma_columns=float(raw["receptive_field_sigma_columns"]),
            loom_half_angle_deg=float(raw["loom_half_angle_deg"]),
        )
        if values.lamina_max_rate_hz <= 0.0:
            raise ConfigurationError("Lamina maximum rate must be positive")
        if values.lamina_baseline_rate_hz < 0.0:
            raise ConfigurationError("Lamina baseline rate cannot be negative")
        if values.lamina_baseline_rate_hz >= values.lamina_max_rate_hz:
            raise ConfigurationError("Lamina baseline must sit below the maximum rate")
        if not 0.0 <= values.lamina_on_off_balance <= 1.0:
            raise ConfigurationError("ON/OFF balance must lie in [0, 1]")
        if values.receptive_field_sigma_columns <= 0.0:
            raise ConfigurationError("Receptive-field width must be positive")
        if values.loom_half_angle_deg <= 0.0:
            raise ConfigurationError("Loom half-angle must be positive")
        return values


class RetinotopicVisualEncoder:
    """A visual cue to per-body lamina firing rates, through released column coordinates.

    Each lamina cell's drive is a gaussian on its distance, in columns, from where the cue
    centre lands on that eye, scaled by a Michaelis-Menten term in the cue's angular size.
    That size term is the looming signal: a cue that grows as the fly approaches drives the
    lamina harder, which is the input the escape pathway is built to detect.

    Only the ipsilateral eye sees a cue in its hemifield, which is what makes the drive
    lateralised at the input rather than relying on the graph to create an asymmetry.

    The ON/OFF balance multiplies the L1 populations, whose predicted output sign is
    inhibitory. At 0.0 a dark cue drives only the excitatory OFF and wide-field pathways;
    at 1.0 every lamina pathway is driven alike. The right value is not known, so it is
    searched under neural criteria.
    """

    SENSOR_CUE_X = "world:visual-cue:x_mm"
    SENSOR_CUE_Y = "world:visual-cue:y_mm"

    def __init__(
        self,
        populations: Demo01Populations,
        parameters: VisualEncodingParameters,
        retina: RetinaMap,
        *,
        stimulus_present: bool = True,
    ) -> None:
        if not populations.entry_hex:
            raise ConfigurationError(
                "The retinotopic encoder needs released column coordinates; resolve the "
                "populations with require_hex=True"
            )
        self.populations = populations
        self.parameters = parameters
        self.retina = retina
        self.stimulus_present = stimulus_present
        # Precompute the per-body geometry once. Bodies without a released column
        # assignment are held at baseline rather than given an invented position.
        self._members: list[tuple[str, int, float, float]] = []
        self._no_column = 0
        for name, bodies in populations.entry.items():
            for body_id in bodies:
                column = populations.entry_hex.get(body_id)
                if column is None:
                    self._no_column += 1
                    continue
                self._members.append((name, body_id, column[0], column[1]))
        if not self._members:
            raise ConfigurationError("No entry body carries a released column coordinate")

    @property
    def bodies_without_column(self) -> int:
        return self._no_column

    def _pathway_gain(self, population: str) -> float:
        return (
            self.parameters.lamina_on_off_balance
            if population.startswith("lamina-on-")
            else 1.0
        )

    def rates_for(
        self, cue: VisualCue | None, *, x_mm: float, y_mm: float, heading_rad: float
    ) -> tuple[dict[int, float], dict[str, Any]]:
        """Per-body lamina rates, plus the scene description for the trace."""
        baseline = self.parameters.lamina_baseline_rate_hz
        span = self.parameters.lamina_max_rate_hz - baseline
        rates: dict[int, float] = {body: baseline for _, body, _, _ in self._members}
        scene: dict[str, Any] = {
            "stimulus_present": self.stimulus_present and cue is not None,
            "bearing_deg": None,
            "angular_radius_deg": None,
            "loom_term": 0.0,
            "eye_columns": {},
            "driven_bodies": 0,
            "receptive_field_sigma_columns": (
                self.parameters.receptive_field_sigma_columns
            ),
        }
        if cue is None or not self.stimulus_present:
            return rates, scene

        bearing_deg, angular_radius_deg = cue.geometry_from(
            x_mm=x_mm, y_mm=y_mm, heading_rad=heading_rad
        )
        loom = angular_radius_deg / (angular_radius_deg + self.parameters.loom_half_angle_deg)
        scene["bearing_deg"] = bearing_deg
        scene["angular_radius_deg"] = angular_radius_deg
        scene["loom_term"] = loom

        # Ipsilateral azimuth: the left eye sees a cue on the fly's left at positive
        # azimuth, the right eye sees the mirror image.
        eye_targets: dict[str, tuple[float, float]] = {}
        for side, sign in (("left", 1.0), ("right", -1.0)):
            azimuth = sign * bearing_deg
            column = self.retina.column_for(azimuth, 0.0)
            eye_targets[side] = column
            scene["eye_columns"][side] = {
                "ipsilateral_azimuth_deg": azimuth,
                "hex1": column[0],
                "hex2": column[1],
            }

        # The patch a cue covers is its own angular extent plus a declared blur. A larger
        # object legitimately lands on more columns, so the width is not a free constant.
        sigma = (
            self.parameters.receptive_field_sigma_columns
            + angular_radius_deg * self.retina.columns_per_degree()
        )
        two_sigma_sq = 2.0 * sigma * sigma
        scene["receptive_field_sigma_columns"] = sigma
        driven = 0
        for name, body_id, hex1, hex2 in self._members:
            side = "left" if name.endswith("-left") else "right"
            target1, target2 = eye_targets[side]
            d_sq = (hex1 - target1) ** 2 + (hex2 - target2) ** 2
            spatial = math.exp(-d_sq / two_sigma_sq)
            drive = spatial * loom * self._pathway_gain(name)
            if drive > 1e-4:
                driven += 1
            rates[body_id] = baseline + min(1.0, max(0.0, drive)) * span
        scene["driven_bodies"] = driven
        return rates, scene

    def encode(
        self,
        t_us: int,
        cue: VisualCue | None,
        *,
        x_mm: float,
        y_mm: float,
        heading_rad: float,
    ) -> NeuralInputFrame:
        rates, scene = self.rates_for(cue, x_mm=x_mm, y_mm=y_mm, heading_rad=heading_rad)
        ids = tuple(sorted(rates))
        return NeuralInputFrame(
            t_us=t_us,
            ids=ids,
            values=tuple(rates[body_id] for body_id in ids),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="P/E",
            assumption_ids=("DATA-03", "DEMO-03"),
            metadata={
                "entry_layer": "lamina monopolar cells L1-L5",
                "retina_to_lamina_synapse_executed": False,
                "why_not": (
                    "All 66,533 photoreceptor output edges are zeroed by the frozen sign "
                    "policy: fly photoreceptors are histaminergic and histamine is absent "
                    "from the transmitter model, so every prediction is unresolved."
                ),
                "optic_lobe_computes_the_response": True,
                "scene": scene,
                "on_off_balance": self.parameters.lamina_on_off_balance,
                "declared_populations": {
                    name: len(bodies) for name, bodies in self.populations.entry.items()
                },
                "entry_bodies_with_column_coordinates": len(self._members),
                "entry_bodies_without_column_held_at_baseline": self._no_column,
                "retina_map": self.retina.as_dict(),
                "annotations_sha256": self.populations.annotations_sha256,
            },
        )


# --------------------------------------------------------------------------------------
# Operating-point criteria for the visual route
# --------------------------------------------------------------------------------------
#
# C1 to C4 keep the identical thresholds registered for the odour contract that failed,
# and the identical arithmetic. The route changed; the bar did not. `score_operating_point`
# in `flysim.demo01` is deliberately left untouched, because it is part of the recorded
# failed experiment and rewriting it would edit that record.
#
# One criterion is added, and it only ever tightens. C5 requires a minimum number of raw
# readout spikes in each cue epoch. The odour search produced selectivity indices of
# exactly +-1.000 from one spike against zero, and both C3 magnitude and reversal are
# meaningless at that count. C5 makes the degenerate outcome unreachable rather than
# hoping the thresholds catch it.


@dataclass(frozen=True, slots=True)
class VisualOperatingPointCriteria:
    """Thresholds a visual operating point must satisfy on neural grounds alone."""

    baseline_max_hz: float
    saturation_max_fraction: float
    min_cue_response_hz: float
    min_selectivity_index: float
    max_recovery_fraction: float
    min_active_fraction: float
    max_active_fraction: float
    min_readout_spikes_per_cue_epoch: int

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> VisualOperatingPointCriteria:
        values = cls(
            baseline_max_hz=float(raw["baseline_max_hz"]),
            saturation_max_fraction=float(raw["saturation_max_fraction"]),
            min_cue_response_hz=float(raw["min_cue_response_hz"]),
            min_selectivity_index=float(raw["min_selectivity_index"]),
            max_recovery_fraction=float(raw["max_recovery_fraction"]),
            min_active_fraction=float(raw["min_active_fraction"]),
            max_active_fraction=float(raw["max_active_fraction"]),
            min_readout_spikes_per_cue_epoch=int(raw["min_readout_spikes_per_cue_epoch"]),
        )
        if values.min_readout_spikes_per_cue_epoch < 1:
            raise ConfigurationError(
                "The spike-count floor must be at least one, or the degenerate "
                "single-spike selectivity index stays reachable"
            )
        return values

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_max_hz": self.baseline_max_hz,
            "saturation_max_fraction": self.saturation_max_fraction,
            "min_cue_response_hz": self.min_cue_response_hz,
            "min_selectivity_index": self.min_selectivity_index,
            "max_recovery_fraction": self.max_recovery_fraction,
            "active_fraction_window": [self.min_active_fraction, self.max_active_fraction],
            "min_readout_spikes_per_cue_epoch": self.min_readout_spikes_per_cue_epoch,
        }


def score_visual_operating_point(
    *,
    baseline: dict[str, float],
    cue_left: dict[str, float],
    cue_right: dict[str, float],
    recovery: dict[str, float],
    pool_activity: dict[str, dict[str, float]],
    cue_epoch_spike_counts: dict[str, int],
    criteria: VisualOperatingPointCriteria,
    left_readout: str = VISUAL_LEFT_READOUT,
    right_readout: str = VISUAL_RIGHT_READOUT,
) -> dict[str, Any]:
    """Evaluate five neural criteria. No behavioural quantity is admissible here.

    The four epoch mappings carry a declared readout population name to its mean filtered
    rate over that epoch. ``cue_epoch_spike_counts`` carries the raw integer spike total
    over each cue epoch, keyed by epoch name, which is what C5 tests.
    """
    base_left, base_right = baseline[left_readout], baseline[right_readout]
    base_drive = 0.5 * (base_left + base_right)
    left_cue_drive = 0.5 * (cue_left[left_readout] + cue_left[right_readout])
    right_cue_drive = 0.5 * (cue_right[left_readout] + cue_right[right_readout])
    recovery_drive = 0.5 * (recovery[left_readout] + recovery[right_readout])

    # C1 stability: not saturated at rest, and a declared fraction of the descending pool
    # doing something without the whole pool firing.
    descending = pool_activity.get("descending-all", {})
    active_fraction = float(descending.get("active_fraction", 0.0))
    pool_rate = float(descending.get("mean_rate_hz", 0.0))
    refractory_ceiling_hz = 1000.0 / 2.2
    c1 = (
        base_drive <= criteria.baseline_max_hz
        and pool_rate <= criteria.saturation_max_fraction * refractory_ceiling_hz
        and criteria.min_active_fraction <= active_fraction <= criteria.max_active_fraction
    )

    # C2 cue responsiveness.
    cue_response = max(left_cue_drive, right_cue_drive) - base_drive
    c2 = cue_response >= criteria.min_cue_response_hz

    # C3 bilateral selectivity that reverses with cue side. A fixed anatomical asymmetry
    # passes a one-sided test and carries no cue information, so reversal is required.
    left_index = selectivity_index(cue_left[left_readout], cue_left[right_readout])
    right_index = selectivity_index(cue_right[left_readout], cue_right[right_readout])
    reverses = left_index > 0.0 > right_index or right_index > 0.0 > left_index
    c3 = reverses and abs(left_index - right_index) >= criteria.min_selectivity_index

    # C4 recovery once the cue is removed.
    span = max(left_cue_drive, right_cue_drive) - base_drive
    residual = (recovery_drive - base_drive) / span if span > 0.0 else 1.0
    c4 = residual <= criteria.max_recovery_fraction

    # C5 the spike-count floor that makes the single-spike index unreachable.
    floor = criteria.min_readout_spikes_per_cue_epoch
    counts = {name: int(value) for name, value in cue_epoch_spike_counts.items()}
    c5 = bool(counts) and all(value >= floor for value in counts.values())

    return {
        "baseline_drive_hz": base_drive,
        "cue_left_drive_hz": left_cue_drive,
        "cue_right_drive_hz": right_cue_drive,
        "recovery_drive_hz": recovery_drive,
        "cue_response_hz": cue_response,
        "left_cue_selectivity_index": left_index,
        "right_cue_selectivity_index": right_index,
        "selectivity_reverses_with_cue_side": reverses,
        "selectivity_swing": abs(left_index - right_index),
        "recovery_residual_fraction": residual,
        "descending_active_fraction": active_fraction,
        "descending_mean_rate_hz": pool_rate,
        "cue_epoch_readout_spike_counts": counts,
        "decoded_readouts": [left_readout, right_readout],
        "C1_stable_nonsaturated": bool(c1),
        "C2_cue_responsive": bool(c2),
        "C3_bilateral_selectivity_reverses": bool(c3),
        "C4_recovers_to_baseline": bool(c4),
        "C5_enough_spikes_to_be_meaningful": c5,
        "all_criteria_met": bool(c1 and c2 and c3 and c4 and c5),
        "criteria": criteria.as_dict(),
        "what_is_deliberately_not_here": (
            "No distance, no displacement, no approach outcome and no body quantity of "
            "any kind. The operating point is chosen on neural grounds so that a "
            "behavioural decoder cannot be compensating for a bad network."
        ),
    }


def visual_searched_parameter_grid(raw: dict[str, Any]) -> tuple[dict[str, float], ...]:
    """Expand the registered P/E visual search grid into candidate operating points.

    The axes are declared in the contract rather than hard-coded here so the recorded
    artifact and the code cannot disagree about what was searched.
    """
    axes = {str(name): [float(v) for v in values] for name, values in raw.items()}
    if not axes:
        raise ConfigurationError("The visual search grid declares no axis")
    empty = sorted(name for name, values in axes.items() if not values)
    if empty:
        raise ConfigurationError(f"Searched axes {empty} declare no value")
    names = sorted(axes)
    combinations: list[dict[str, float]] = [{}]
    for name in names:
        combinations = [
            {**base, name: value} for base in combinations for value in axes[name]
        ]
    return tuple(combinations)


__all__ = [
    "VISUAL_ENTRY_SPECS",
    "VISUAL_LEFT_READOUT",
    "VISUAL_MONITOR_POOLS",
    "VISUAL_READOUT_SPECS",
    "VISUAL_RIGHT_READOUT",
    "RetinaMap",
    "RetinotopicVisualEncoder",
    "VisualCue",
    "VisualEncodingParameters",
    "VisualOperatingPointCriteria",
    "score_visual_operating_point",
    "visual_searched_parameter_grid",
]
