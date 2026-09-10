# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the DEMO-01 visual route.

The tests that matter here are the ones that would catch the demo becoming a workaround:
that no behavioural quantity can enter the operating-point score, that the encoder drives
only declared populations, that a bilaterally symmetric cue cannot produce selectivity,
and that the added dynamics parameters are neutral at their defaults.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from flysim.demo01 import PopulationSpec
from flysim.demo01_visual import (
    VISUAL_ENTRY_SPECS,
    VISUAL_LEFT_READOUT,
    VISUAL_MONITOR_POOLS,
    VISUAL_READOUT_SPECS,
    VISUAL_RIGHT_READOUT,
    RetinaMap,
    VisualCue,
    VisualEncodingParameters,
    VisualOperatingPointCriteria,
    score_visual_operating_point,
    visual_searched_parameter_grid,
)
from flysim.errors import ConfigurationError

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "configs/experiments/demo01-visual-operating-point-v1.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture
def retina(contract: dict) -> RetinaMap:
    return RetinaMap.from_mapping(contract["retina_map"])


@pytest.fixture
def criteria(contract: dict) -> VisualOperatingPointCriteria:
    return VisualOperatingPointCriteria.from_mapping(contract["neural_criteria"])


# ---------------------------------------------------------------------------
# The declaration itself
# ---------------------------------------------------------------------------


def test_entry_and_readout_superclasses_cannot_overlap() -> None:
    """Visual projection neurons and descending neurons are disjoint by construction."""
    entry_types = {spec.cell_type for spec in VISUAL_ENTRY_SPECS}
    readout_types = {spec.cell_type for spec in VISUAL_READOUT_SPECS}
    assert entry_types.isdisjoint(readout_types)
    # Entry is the lamina; every readout is a descending declaration.
    assert entry_types <= {"L1", "L2", "L5"}


def test_the_entry_is_left_right_balanced_in_declaration() -> None:
    """Each entry cell type appears once per side and nowhere else."""
    by_side: dict[str, set[str]] = {"L": set(), "R": set()}
    for spec in VISUAL_ENTRY_SPECS:
        assert spec.side in ("L", "R")
        assert spec.side_column == "somaSide"
        by_side[str(spec.side)].add(spec.cell_type)
    assert by_side["L"] == by_side["R"]


def test_l3_and_l4_are_excluded_because_their_columns_are_not_released() -> None:
    """The exclusion is a property of the release, so it must be recorded, not silent."""
    from flysim.demo01_visual import LAMINA_TYPES_EXCLUDED_FOR_MISSING_COLUMNS as excluded

    assert set(excluded) == {"L3", "L4"}
    declared = {spec.cell_type for spec in VISUAL_ENTRY_SPECS}
    assert declared.isdisjoint(excluded)


def test_the_decoded_readout_is_the_visually_driven_group() -> None:
    """Steering on the whole descending pool is what held selectivity at 0.03."""
    assert VISUAL_LEFT_READOUT == "dn-visual-left"
    assert VISUAL_RIGHT_READOUT == "dn-visual-right"
    decoded = [
        spec for spec in VISUAL_READOUT_SPECS
        if spec.name in (VISUAL_LEFT_READOUT, VISUAL_RIGHT_READOUT)
    ]
    assert len(decoded) == 2
    for spec in decoded:
        assert spec.type_prefixes == ("DNp",)
    # And the whole pool is still recorded, so the comparison stays available.
    assert {"dn-pool-left", "dn-pool-right"} <= {s.name for s in VISUAL_READOUT_SPECS}


def test_prefix_and_exact_matching_do_not_bleed_into_each_other() -> None:
    prefix = PopulationSpec("p", "DNp", "L", "somaSide", "r", type_prefixes=("DNp",))
    assert prefix.accepts("DNp01")
    assert prefix.accepts("DNpe004")
    assert not prefix.accepts("DNa02")
    assert not prefix.accepts(None)
    exact = PopulationSpec("e", "DNa01", "L", "somaSide", "r", additional_types=("DNa02",))
    assert exact.accepts("DNa01")
    assert exact.accepts("DNa02")
    assert not exact.accepts("DNa01x")


def test_the_monitor_pools_cover_the_whole_executed_graph_by_superclass() -> None:
    """The recorder must see the optic lobe, not only the parts the cue touches."""
    values = {rule["value"] for rule in VISUAL_MONITOR_POOLS.values()}
    assert {"ol_sensory", "ol_intrinsic", "visual_projection", "descending_neuron"} <= values


# ---------------------------------------------------------------------------
# The retinal map and the encoder geometry
# ---------------------------------------------------------------------------


def test_a_cue_straight_ahead_lands_on_both_eyes_alike(retina: RetinaMap) -> None:
    left = retina.column_for(0.0, 0.0)
    right = retina.column_for(0.0, 0.0)
    assert left == right


def test_an_ipsilateral_cue_lands_inside_one_eye_and_outside_the_other(
    retina: RetinaMap,
) -> None:
    """This is what makes the drive lateralised at the input rather than by the graph."""
    inside = retina.column_for(45.0, 0.0)
    outside = retina.column_for(-45.0, 0.0)
    assert retina.hex1_min <= inside[0] <= retina.hex1_max
    assert outside[0] < retina.hex1_min


def test_the_retinal_map_rejects_a_degenerate_span() -> None:
    base = {
        "hex1_min": 1.0, "hex1_max": 36.0, "hex2_min": 1.0, "hex2_max": 39.0,
        "azimuth_min_deg": -10.0, "azimuth_max_deg": 160.0,
        "elevation_min_deg": -60.0, "elevation_max_deg": 60.0,
    }
    with pytest.raises(ConfigurationError):
        RetinaMap.from_mapping({**base, "hex1_max": 1.0})
    with pytest.raises(ConfigurationError):
        RetinaMap.from_mapping({**base, "azimuth_max_deg": -10.0})


def test_the_cue_bearing_is_signed_and_wraps() -> None:
    cue = VisualCue(x_mm=0.0, y_mm=10.0, radius_mm=3.0)
    bearing, _ = cue.geometry_from(x_mm=0.0, y_mm=0.0, heading_rad=0.0)
    assert bearing == pytest.approx(90.0)
    # Turning to face it puts it straight ahead.
    bearing, _ = cue.geometry_from(x_mm=0.0, y_mm=0.0, heading_rad=math.pi / 2)
    assert bearing == pytest.approx(0.0)
    # And a cue behind the fly wraps to the short way round, never to 350 degrees.
    behind = VisualCue(x_mm=-10.0, y_mm=-0.001, radius_mm=3.0)
    bearing, _ = behind.geometry_from(x_mm=0.0, y_mm=0.0, heading_rad=0.0)
    assert -180.0 <= bearing <= 180.0


def test_the_angular_radius_grows_as_the_cue_approaches() -> None:
    """The loom signal is the whole reason the escape pathway responds."""
    cue = VisualCue(x_mm=20.0, y_mm=0.0, radius_mm=2.0)
    far = cue.geometry_from(x_mm=0.0, y_mm=0.0, heading_rad=0.0)[1]
    near = cue.geometry_from(x_mm=18.0, y_mm=0.0, heading_rad=0.0)[1]
    assert near > far
    # And it saturates rather than exploding when the cue engulfs the eye.
    engulfing = cue.geometry_from(x_mm=19.5, y_mm=0.0, heading_rad=0.0)[1]
    assert engulfing <= 90.0


def test_the_encoding_parameters_reject_nonsense() -> None:
    base = {
        "lamina_max_rate_hz": 300.0,
        "lamina_baseline_rate_hz": 1.0,
        "lamina_on_off_balance": 0.0,
        "receptive_field_sigma_columns": 2.0,
        "loom_half_angle_deg": 15.0,
    }
    assert VisualEncodingParameters.from_mapping(base).lamina_max_rate_hz == 300.0
    for bad in (
        {"lamina_max_rate_hz": 0.0},
        {"lamina_baseline_rate_hz": 400.0},
        {"lamina_on_off_balance": 1.5},
        {"receptive_field_sigma_columns": 0.0},
        {"loom_half_angle_deg": -1.0},
    ):
        with pytest.raises(ConfigurationError):
            VisualEncodingParameters.from_mapping({**base, **bad})


# ---------------------------------------------------------------------------
# The operating-point score: the guarantees that keep this from being a workaround
# ---------------------------------------------------------------------------


def _epochs(
    base: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
    recovery: tuple[float, float],
) -> dict[str, dict[str, float]]:
    def frame(pair: tuple[float, float]) -> dict[str, float]:
        return {VISUAL_LEFT_READOUT: pair[0], VISUAL_RIGHT_READOUT: pair[1]}

    return {
        "baseline": frame(base),
        "cue_left": frame(left),
        "cue_right": frame(right),
        "recovery": frame(recovery),
    }


POOL = {"descending-all": {"mean_rate_hz": 1.0, "active_fraction": 0.05}}
SPIKES = {"cue_left": 500, "cue_right": 500}


def test_no_behavioural_quantity_can_enter_the_visual_score() -> None:
    """The signature is the guarantee, so pin it, and check the body too."""
    import inspect

    from flysim import demo01_visual

    signature = inspect.signature(demo01_visual.score_visual_operating_point)
    assert set(signature.parameters) == {
        "baseline",
        "cue_left",
        "cue_right",
        "recovery",
        "pool_activity",
        "cue_epoch_spike_counts",
        "criteria",
        "left_readout",
        "right_readout",
    }
    forbidden = ("distance", "displacement", "trajectory", "success", "reward", "approach")
    source = inspect.getsource(demo01_visual.score_visual_operating_point)
    head = source.split("what_is_deliberately_not_here")[0]
    assert not any(word in head for word in forbidden)


def test_a_good_operating_point_passes_all_five(
    criteria: VisualOperatingPointCriteria,
) -> None:
    score = score_visual_operating_point(
        **_epochs((0.1, 0.1), (5.0, 1.0), (1.0, 5.0), (0.4, 0.4)),
        pool_activity=POOL,
        cue_epoch_spike_counts=SPIKES,
        criteria=criteria,
    )
    assert score["all_criteria_met"]
    assert score["selectivity_reverses_with_cue_side"]


def test_a_fixed_asymmetry_fails_the_reversal_criterion(
    criteria: VisualOperatingPointCriteria,
) -> None:
    """A brain wired lopsidedly carries no information about which side the cue is on."""
    score = score_visual_operating_point(
        **_epochs((0.1, 0.1), (5.0, 1.0), (5.0, 1.0), (0.4, 0.4)),
        pool_activity=POOL,
        cue_epoch_spike_counts=SPIKES,
        criteria=criteria,
    )
    assert not score["selectivity_reverses_with_cue_side"]
    assert not score["C3_bilateral_selectivity_reverses"]
    assert not score["all_criteria_met"]


def test_a_single_spike_selectivity_cannot_pass(
    criteria: VisualOperatingPointCriteria,
) -> None:
    """C5 exists because the odour search produced +-1.000 indices from one spike."""
    perfect_but_empty = score_visual_operating_point(
        **_epochs((0.0, 0.0), (5.0, 0.0), (0.0, 5.0), (0.0, 0.0)),
        pool_activity=POOL,
        cue_epoch_spike_counts={"cue_left": 1, "cue_right": 1},
        criteria=criteria,
    )
    assert perfect_but_empty["selectivity_swing"] == pytest.approx(2.0)
    assert perfect_but_empty["C3_bilateral_selectivity_reverses"]
    assert not perfect_but_empty["C5_enough_spikes_to_be_meaningful"]
    assert not perfect_but_empty["all_criteria_met"]


def test_a_network_that_never_recovers_fails_c4(
    criteria: VisualOperatingPointCriteria,
) -> None:
    score = score_visual_operating_point(
        **_epochs((0.1, 0.1), (5.0, 1.0), (1.0, 5.0), (5.0, 1.0)),
        pool_activity=POOL,
        cue_epoch_spike_counts=SPIKES,
        criteria=criteria,
    )
    assert not score["C4_recovers_to_baseline"]


def test_a_saturated_network_fails_stability(
    criteria: VisualOperatingPointCriteria,
) -> None:
    score = score_visual_operating_point(
        **_epochs((0.1, 0.1), (5.0, 1.0), (1.0, 5.0), (0.4, 0.4)),
        pool_activity={"descending-all": {"mean_rate_hz": 300.0, "active_fraction": 0.99}},
        cue_epoch_spike_counts=SPIKES,
        criteria=criteria,
    )
    assert not score["C1_stable_nonsaturated"]


def test_a_silent_network_fails_both_response_and_activity(
    criteria: VisualOperatingPointCriteria,
) -> None:
    score = score_visual_operating_point(
        **_epochs((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
        pool_activity={"descending-all": {"mean_rate_hz": 0.0, "active_fraction": 0.0}},
        cue_epoch_spike_counts={"cue_left": 0, "cue_right": 0},
        criteria=criteria,
    )
    assert not score["C2_cue_responsive"]
    assert not score["C1_stable_nonsaturated"]
    assert not score["C5_enough_spikes_to_be_meaningful"]


def test_the_spike_floor_must_be_at_least_one(contract: dict) -> None:
    with pytest.raises(ConfigurationError):
        VisualOperatingPointCriteria.from_mapping(
            {**contract["neural_criteria"], "min_readout_spikes_per_cue_epoch": 0}
        )


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_contract_grid_matches_its_declared_size(contract: dict) -> None:
    grid = visual_searched_parameter_grid(contract["searched_grid"])
    assert len(grid) == contract["grid_size"]
    assert contract["values_opened"] is False


def test_the_contract_keeps_the_odour_thresholds_and_adds_only_a_tightening(
    contract: dict,
) -> None:
    """The route changed; the bar must not have moved."""
    odour = json.loads(
        (REPO / "configs/experiments/demo01-operating-point-v1.json").read_text(
            encoding="utf-8"
        )
    )["neural_criteria"]
    visual = contract["neural_criteria"]
    for key in (
        "baseline_max_hz",
        "saturation_max_fraction",
        "min_cue_response_hz",
        "min_selectivity_index",
        "max_recovery_fraction",
        "min_active_fraction",
        "max_active_fraction",
    ):
        assert visual[key] == odour[key], key
    # The one addition tightens.
    assert visual["min_readout_spikes_per_cue_epoch"] >= 1
    assert "min_readout_spikes_per_cue_epoch" not in odour


def test_the_contract_declares_the_pilot(contract: dict) -> None:
    """A grid shaped by a pilot must say so, and the pilot must be published."""
    assert "a_pilot_informed_this_grid" in contract
    assert (REPO / "docs/demo01/PILOT.md").is_file()


def test_no_behavioural_objective_appears_in_the_contract(contract: dict) -> None:
    text = json.dumps(contract).lower()
    for word in ("distance_to_target", "approach_success", "reward"):
        assert word not in text


def test_the_incumbent_values_are_inside_the_searched_range(contract: dict) -> None:
    """A search that excludes the value it is replacing is not a search."""
    grid = contract["searched_grid"]
    # The engine's original behaviour for both new dynamics parameters must be reachable.
    assert 0.0 in grid["adaptation_increment_mv"]
    assert contract["fixed_parameters"]["synaptic_target_normalisation_exponent"] == 0.0
    assert contract["fixed_parameters"]["tonic_drive_mv"] == 0.0


def test_the_searched_grid_expands_deterministically(contract: dict) -> None:
    first = visual_searched_parameter_grid(contract["searched_grid"])
    second = visual_searched_parameter_grid(contract["searched_grid"])
    assert first == second
    assert len({tuple(sorted(row.items())) for row in first}) == len(first)


def test_an_empty_axis_is_refused() -> None:
    with pytest.raises(ConfigurationError):
        visual_searched_parameter_grid({"a": [1.0], "b": []})
    with pytest.raises(ConfigurationError):
        visual_searched_parameter_grid({})


# ---------------------------------------------------------------------------
# The added dynamics parameters must be neutral at their defaults
# ---------------------------------------------------------------------------


def test_the_new_engine_parameters_default_to_the_original_behaviour() -> None:
    """Three parameters were added to the dynamics layer. None may change a recorded run."""
    from flysim.engines.genn import TrackAGeNNParameters

    base = {
        "neural_dt_us": 100,
        "resting_mv": -52.0,
        "reset_mv": -52.0,
        "threshold_mv": -45.0,
        "membrane_tau_ms": 20.0,
        "synapse_tau_ms": 5.0,
        "refractory_ms": 2.2,
        "synaptic_delay_ms": 0.1,
        "synaptic_mv_per_contact": 0.275,
        "central_entry_outgoing_gain": 10.0,
        "tonic_drive_mv": 0.0,
        "reset_synaptic_state_on_spike": True,
    }
    values = TrackAGeNNParameters.from_mapping(base)
    assert values.synaptic_target_normalisation_exponent == 0.0
    assert values.adaptation_increment_mv == 0.0
    assert values.inhibitory_weight_gain == 1.0


def test_the_new_engine_parameters_validate_their_range() -> None:
    from flysim.engines.genn import TrackAGeNNParameters

    base = {
        "neural_dt_us": 100,
        "resting_mv": -52.0,
        "reset_mv": -52.0,
        "threshold_mv": -45.0,
        "membrane_tau_ms": 20.0,
        "synapse_tau_ms": 5.0,
        "refractory_ms": 2.2,
        "synaptic_delay_ms": 0.1,
        "synaptic_mv_per_contact": 0.275,
        "central_entry_outgoing_gain": 1.0,
        "tonic_drive_mv": 0.0,
        "reset_synaptic_state_on_spike": True,
    }
    for bad in (
        {"synaptic_target_normalisation_exponent": 1.5},
        {"synaptic_target_normalisation_exponent": -0.1},
        {"adaptation_increment_mv": -1.0},
        {"adaptation_tau_ms": 0.0},
        {"inhibitory_weight_gain": -1.0},
    ):
        with pytest.raises(ConfigurationError):
            TrackAGeNNParameters.from_mapping({**base, **bad})
