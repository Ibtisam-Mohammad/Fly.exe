# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the DEMO-01 renderer.

The renderer cannot affect a simulation, so these check the properties that would
otherwise silently mislead a viewer: that the projection puts anatomy where the labels
say it is, that a neuron with no released position is never invented, that declared
populations are matched to the right cells, and that the frame carries its provenance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from flysim.demo01_render import (
    BODY_WIDTH,
    BRAIN_WIDTH,
    FOOTER_HEIGHT,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    HEADER_HEIGHT,
    PANEL_HEIGHT,
    TRACE_HEIGHT,
    BrainAtlas,
    SpikeRecording,
    TraceChannel,
    build_strips,
    load_trace,
    render_brain,
)
from flysim.errors import ReadinessError


def _atlas_file(path: Path, *, with_body_ids: bool = True) -> Path:
    """A tiny synthetic atlas: two left cells, two right cells, one in the nerve cord."""
    xyz = np.array(
        [
            [80000.0, 30000.0, 30000.0],  # left brain
            [78000.0, 32000.0, 31000.0],  # left brain
            [17000.0, 30000.0, 30000.0],  # right brain
            [16000.0, 32000.0, 31000.0],  # right brain
            [50000.0, 55000.0, 101000.0],  # nerve cord
        ],
        dtype=np.float32,
    )
    payload = {
        "dense_index": np.array([0, 1, 2, 3, 4], dtype=np.int32),
        "xyz": xyz,
        "superclass": np.array(
            [
                "ol_intrinsic",
                "visual_projection",
                "ol_intrinsic",
                "descending_neuron",
                "vnc_motor",
            ]
        ),
        "side": np.array(["L", "L", "R", "R", "M"]),
        "missing_dense_index": np.array([5, 6], dtype=np.int32),
        "missing_superclass": np.array(["ol_sensory", "cb_sensory"]),
    }
    if with_body_ids:
        payload["body_id"] = np.array([100, 101, 200, 201, 300], dtype=np.int64)
    np.savez_compressed(path, **payload)
    return path


@pytest.fixture
def atlas(tmp_path: Path) -> BrainAtlas:
    return BrainAtlas.load(
        _atlas_file(tmp_path / "soma.npz"),
        neuron_count=7,
        entry_body_ids=(100, 200),
        readout_body_ids=(201,),
    )


# ---------------------------------------------------------------------------
# Geometry: the labels on the frame have to be true
# ---------------------------------------------------------------------------


def test_the_dorsal_view_puts_the_flys_left_on_the_left_of_frame(atlas: BrainAtlas) -> None:
    """The frame says so in words, so it must be true of the pixels."""
    px, _, _ = atlas.project(0.0, 0.0, 400, 400, view="dorsal")
    left = px[[0, 1]].mean()
    right = px[[2, 3]].mean()
    assert left < right


def test_the_frontal_view_puts_the_brain_above_the_nerve_cord(atlas: BrainAtlas) -> None:
    """Also stated on the frame. Image rows increase downward, so smaller y is higher."""
    _, py, _ = atlas.project(0.0, 0.0, 400, 400, view="frontal")
    brain = py[[0, 1, 2, 3]].mean()
    cord = py[4]
    assert brain < cord


def test_the_projection_stays_inside_the_panel(atlas: BrainAtlas) -> None:
    for view in ("frontal", "dorsal"):
        for azimuth in (0.0, 0.7, 1.9, 3.3):
            px, py, depth = atlas.project(azimuth, 0.2, 512, 256, view=view)
            assert px.min() >= -1.0 and px.max() <= 512.0
            assert py.min() >= -1.0 and py.max() <= 256.0
            assert depth.min() >= 0.0 and depth.max() <= 1.0


def test_a_neuron_without_a_released_position_is_never_drawn(atlas: BrainAtlas) -> None:
    """Inventing a position for the 24,122 bodies that lack one would be a fabrication."""
    assert atlas.drawn == 5
    assert atlas.missing == 2
    assert atlas.unit_xyz.shape == (5, 3)
    # And the count is available so the frame can state it.
    assert atlas.drawn + atlas.missing == 7


def test_declared_populations_are_matched_by_body_id_not_by_position(
    atlas: BrainAtlas,
) -> None:
    # body 100 and 200 are entry, 201 is readout, and nothing else is either.
    assert atlas.role.tolist() == [1, 0, 1, 2, 0]


def test_an_unknown_body_id_matches_nothing_rather_than_the_nearest(tmp_path: Path) -> None:
    """A searchsorted lookup that forgot to verify equality would silently mislabel."""
    atlas = BrainAtlas.load(
        _atlas_file(tmp_path / "soma.npz"),
        neuron_count=7,
        entry_body_ids=(999_999,),
        readout_body_ids=(),
    )
    assert not np.any(atlas.role == 1)


def test_a_missing_atlas_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    with pytest.raises(ReadinessError):
        BrainAtlas.load(tmp_path / "absent.npz", neuron_count=7)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_a_silent_brain_renders_dimmer_than_an_active_one(atlas: BrainAtlas) -> None:
    silent = render_brain(
        atlas,
        np.zeros(atlas.drawn, dtype=np.float32),
        azimuth_rad=0.0,
        elevation_rad=0.0,
        width=200,
        height=200,
    )
    active = render_brain(
        atlas,
        np.full(atlas.drawn, 4.0, dtype=np.float32),
        azimuth_rad=0.0,
        elevation_rad=0.0,
        width=200,
        height=200,
    )
    assert active.astype(np.int64).sum() > silent.astype(np.int64).sum()


def test_the_rendered_panel_has_the_requested_shape(atlas: BrainAtlas) -> None:
    frame = render_brain(
        atlas,
        np.zeros(atlas.drawn, dtype=np.float32),
        azimuth_rad=0.3,
        elevation_rad=0.1,
        width=321,
        height=123,
    )
    assert frame.shape == (123, 321, 3)
    assert frame.dtype == np.uint8


def test_the_composition_adds_up(atlas: BrainAtlas) -> None:
    """A layout that does not sum to the frame would silently crop a panel."""
    assert HEADER_HEIGHT + PANEL_HEIGHT + TRACE_HEIGHT + FOOTER_HEIGHT == FRAME_HEIGHT
    assert BRAIN_WIDTH + BODY_WIDTH == FRAME_WIDTH


# ---------------------------------------------------------------------------
# The recording round-trip
# ---------------------------------------------------------------------------


def test_the_sparse_spike_record_round_trips(tmp_path: Path) -> None:
    offsets = np.array([0, 2, 2, 5], dtype=np.int64)
    indices = np.array([3, 9, 1, 4, 7], dtype=np.uint32)
    counts = np.array([1, 2, 1, 1, 3], dtype=np.uint8)
    path = tmp_path / "spikes.npz"
    np.savez_compressed(
        path, offsets=offsets, indices=indices, counts=counts, neuron_count=np.int64(10)
    )
    recording = SpikeRecording(path)
    assert recording.intervals == 3
    assert recording.neuron_count == 10
    first_indices, first_counts = recording.interval(0)
    assert first_indices.tolist() == [3, 9]
    assert first_counts.tolist() == [1.0, 2.0]
    # An interval in which nothing fired is empty, not absent.
    empty_indices, _ = recording.interval(1)
    assert empty_indices.size == 0
    last_indices, last_counts = recording.interval(2)
    assert last_indices.tolist() == [1, 4, 7]
    assert last_counts.tolist() == [1.0, 1.0, 3.0]


def test_an_empty_trace_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ReadinessError):
        load_trace(path)


def test_the_trace_loader_ignores_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text('{"t_us": 1}\n\n{"t_us": 2}\n', encoding="utf-8")
    assert [row["t_us"] for row in load_trace(path)] == [1, 2]


# ---------------------------------------------------------------------------
# Trace strips
# ---------------------------------------------------------------------------


def _row(t_us: int, left: float, right: float, forward: float, yaw: float) -> dict:
    return {
        "t_us": t_us,
        "pose": {"x_mm": 0.0, "y_mm": 0.0, "z_mm": 1.0, "heading_rad": 0.0},
        "cue": {
            "bearing_deg": 40.0,
            "angular_radius_deg": 10.0,
            "loom_term": 0.4,
            "driven_lamina_bodies": 1500,
            "distance_mm": 14.0,
            "present": True,
        },
        "readout_hz": {"dn-visual-left": left, "dn-visual-right": right},
        "pool_mean_rate_hz": {
            "optic-lobe": 1.0,
            "visual-projection": 2.0,
            "central-brain": 3.0,
        },
        "command": {"forward": forward, "yaw": yaw, "state": "LOCOMOTING"},
    }


def test_the_strips_follow_the_causal_chain() -> None:
    """Top to bottom must read input, optic lobe, descending readout, command."""
    strips = build_strips([_row(15000, 5.0, 1.0, 0.4, 0.2)])
    assert len(strips) == 4
    assert "retinal input" in strips[0].title
    assert "optic lobe" in strips[1].title
    assert "descending readout" in strips[2].title
    assert "decoder command" in strips[3].title
    # The command strip must be symmetric, because yaw is signed and a one-sided axis
    # would hide a turn in the wrong direction.
    assert strips[3].symmetric


def test_a_missing_channel_reads_as_zero_rather_than_crashing() -> None:
    row = _row(15000, 5.0, 1.0, 0.4, 0.2)
    del row["readout_hz"]["dn-visual-right"]
    strips = build_strips([row])
    readout = strips[2]
    right = next(c for c in readout.channels if "right" in c.label)
    assert right.values.tolist() == [0.0]


def test_the_strips_preserve_the_sign_of_yaw() -> None:
    strips = build_strips([_row(15000, 1.0, 5.0, 0.4, -0.6)])
    yaw = next(c for c in strips[3].channels if c.label == "yaw drive")
    assert yaw.values[0] == pytest.approx(-0.6)


def test_a_trace_channel_keeps_its_samples() -> None:
    channel = TraceChannel("x", np.array([1.0, 2.0, 3.0]), (1, 2, 3))
    assert channel.values.size == 3


# ---------------------------------------------------------------------------
# Provenance on the frame
# ---------------------------------------------------------------------------


def test_the_scenario_declares_what_may_not_be_claimed() -> None:
    repo = Path(__file__).resolve().parent.parent
    scenario = json.loads(
        (repo / "configs/scenarios/demo01-visual-approach.json").read_text(encoding="utf-8")
    )
    claims = scenario["what_may_and_may_not_be_claimed"]
    assert "may_never_claim" in claims
    assert "V0 Structural" in claims["may_never_claim"]
    # The retina limitation must be stated in the scenario, not only in the code.
    assert "66,533" in claims["the_retina_is_not_executed"]
    # The turn direction must be presented as the engineering choice it is: one sign
    # flips approach into avoidance, so it is not a property of the network.
    what = scenario["what_this_scenario_is"]
    assert "the_turn_direction_is_an_engineering_choice" in what
    assert "engineering choice" in what["the_turn_direction_is_an_engineering_choice"]


def test_the_decoder_in_the_scenario_cannot_see_the_world() -> None:
    repo = Path(__file__).resolve().parent.parent
    scenario = json.loads(
        (repo / "configs/scenarios/demo01-visual-approach.json").read_text(encoding="utf-8")
    )
    decoder = scenario["decoder"]
    assert decoder["turn_sign"] in (-1.0, 1.0)
    assert "no sensory term" in decoder["what_the_decoder_cannot_see"]
    # No world quantity may appear as a decoder parameter.
    for forbidden in ("distance", "bearing", "cue_x", "cue_y", "target"):
        assert not any(forbidden in key for key in decoder)


def test_the_body_geometry_puts_the_cue_where_the_note_says() -> None:
    repo = Path(__file__).resolve().parent.parent
    scenario = json.loads(
        (repo / "configs/scenarios/demo01-visual-approach.json").read_text(encoding="utf-8")
    )
    body = scenario["body"]
    distance = math.hypot(
        body["cue_x_mm"] - body["initial_x_mm"], body["cue_y_mm"] - body["initial_y_mm"]
    )
    bearing = math.degrees(
        math.atan2(
            body["cue_y_mm"] - body["initial_y_mm"], body["cue_x_mm"] - body["initial_x_mm"]
        )
        - body["initial_heading_rad"]
    )
    assert distance == pytest.approx(14.0, abs=0.05)
    assert bearing == pytest.approx(40.1, abs=0.15)
    # And the angular radius the note quotes.
    angular = math.degrees(math.asin(body["cue_radius_mm"] / distance))
    assert angular == pytest.approx(10.3, abs=0.1)
