# SPDX-License-Identifier: GPL-2.0-or-later
"""Render a DEMO-01 recording into a video: the brain, the body, and the traces together.

Nothing here touches the simulation. It reads a finished recording -- `trace.jsonl`,
`spikes.npz` and the body camera's `body.mp4` -- and composites frames. A render cannot
change what was simulated, and re-rendering a recording with different settings produces a
different video from identical numbers.

The brain view is a projection of the released soma coordinates, 141,000 of the 165,122
executed bodies. The remaining 24,122 carry no released position: 7,708 optic-lobe
intrinsic neurons, 6,363 ventral-cord sensory, 4,868 central-brain sensory including the
olfactory receptor neurons, and 4,086 photoreceptors. They are simulated and recorded like
every other neuron and simply cannot be drawn, which the footer says on every frame rather
than leaving the viewer to assume the cloud is the whole graph.

Brightness is spike count, not membrane voltage, and it decays over a few frames so that
activity at a 15 ms coupling interval is visible at 30 frames per second. That decay is a
display choice and is stated on the frame.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.errors import ConfigurationError, ReadinessError

# Composition. 70 + 640 + 310 + 60 = 1080, and 1150 + 770 = 1920.
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
HEADER_HEIGHT = 70
PANEL_HEIGHT = 640
TRACE_HEIGHT = 310
FOOTER_HEIGHT = 60
BRAIN_WIDTH = 1150
BODY_WIDTH = FRAME_WIDTH - BRAIN_WIDTH
# Fixed because the legend's contents are fixed: a title, six colour keys, four lines of
# what-is-not-drawn, and four live population rates. Drawn as a filled box before any of
# that text, so the panel is legible over the point cloud behind it.
LEGEND_HEIGHT = 282
# The legend and the frontal inset get a column of their own, and the dorsal view starts to
# the right of it. Drawing the brain across the full width and then putting an opaque legend
# on top of it hid the fly's left optic lobe behind the key that explains it.
BRAIN_VIEW_LEFT = 350
BRAIN_VIEW_WIDTH = BRAIN_WIDTH - BRAIN_VIEW_LEFT

INK = (232, 236, 244)
DIM = (128, 138, 156)
BACKGROUND = (9, 11, 16)
PANEL = (14, 17, 24)
WARN = (255, 206, 84)

# Colours by role. The structural cloud is deliberately dark so that activity reads as
# activity rather than as anatomy.
STRUCTURE_COLOUR = np.array([0.085, 0.110, 0.170], dtype=np.float32)
REGION_TINT: dict[str, tuple[float, float, float]] = {
    "ol_intrinsic": (0.30, 0.42, 0.72),
    "ol_sensory": (0.30, 0.42, 0.72),
    "visual_projection": (0.95, 0.62, 0.22),
    "visual_centrifugal": (0.85, 0.55, 0.25),
    "cb_intrinsic": (0.42, 0.78, 0.86),
    "cb_sensory": (0.42, 0.78, 0.86),
    "descending_neuron": (0.98, 0.32, 0.42),
    "vnc_intrinsic": (0.55, 0.85, 0.55),
    "vnc_motor": (0.70, 1.00, 0.60),
}
DEFAULT_TINT = (0.72, 0.76, 0.88)

# Readout population names used only for the on-frame captions. Declared here rather
# than imported so the renderer does not depend on the route module.
VISUAL_LEFT_READOUT_NAME = "dn-visual-left"
VISUAL_RIGHT_READOUT_NAME = "dn-visual-right"

ROLE_COLOURS = {
    "entry": (0.35, 1.00, 0.45),
    "readout": (1.00, 0.28, 0.38),
}

# --------------------------------------------------------------------------------------
# How activity becomes brightness, and why these numbers
# --------------------------------------------------------------------------------------
#
# The first version clipped decayed spike counts at 8.0, scaled by 1.8 and ran them through
# an exposure curve. Measured against the recordings that shipped, that map was saturated
# almost everywhere: a neuron with a decayed count of 1.0 already rendered at 0.95 of full
# white, and 2.0 rendered at 0.998. The actual range in the exact run reaches 76.3, with a
# median 99.9th percentile of 47.2, so the entire top two decades were flattened into white.
#
# It cost more than looks. The shuffled-connectome control's median 99.9th percentile is
# 5.96 against the exact run's 47.2, an eightfold difference in how hard the graph drives
# itself -- and the display threw that difference away by saturating both. The control
# comparison's most important visual claim was being erased by its own colour map.
#
# Two changes fix it. Brightness is now logarithmic, referenced to a fixed constant so that
# variants stay comparable frame for frame; per-run normalisation would have made the four
# control panels incomparable, which is the one thing that video may not do. And activity is
# averaged over the neurons drawn at a pixel rather than summed, so the optic lobes stop
# rendering as a white slab merely because more somata project there. What a bright pixel
# now means is that the neurons at that pixel are firing hard, not that there are many.
#
# The gain is not a taste setting either. Measured on the finished recordings at the real
# 1150x640 dorsal projection, the 99th-percentile lit pixel carries a mean activity of 0.308
# in the exact run against 0.127 in the degree-preserving shuffle. The exposure curve is
# 1 - exp(-gain * exposure * activity), and the gain that maximally separates those two
# values is ln(0.308/0.127) / (0.308 - 0.127) / exposure, which is 2.22. So the display is
# tuned to make the control contrast as visible as the medium allows, and the exact run's
# brightest pixels land at 0.97 rather than clipping.
GLOW_REFERENCE = 48.0
ACTIVITY_GAIN = 2.2
ACTIVITY_EXPOSURE = 2.2
# Activity is a per-pixel mean and so already looks the same at any panel size, but the
# structural cloud is a sum and does not: 141,000 somata into the 1150x640 hero panel is
# 1.14 neurons per lit pixel, while the same cloud in a 620x379 comparison panel is more
# than twice that, and the hero view came out visibly fainter than the small panels beside
# it. Rescaling to a reference density makes the anatomy read identically in both, without
# flattening the density differences *within* a view, which are anatomy and should show.
STRUCTURE_REFERENCE_DENSITY = 2.5


def activity_intensity(glow: np.ndarray) -> np.ndarray:
    """Compress a decayed spike count into [0, ~1.12]. Fixed map, never per-run."""
    compressed: np.ndarray = np.log1p(np.maximum(glow, 0.0)) / math.log1p(GLOW_REFERENCE)
    return compressed


@dataclass(frozen=True, slots=True)
class BrainAtlas:
    """Released soma positions, normalised, with per-neuron colours and roles."""

    dense_index: np.ndarray
    body_id: np.ndarray
    unit_xyz: np.ndarray
    tint: np.ndarray
    role: np.ndarray
    drawn: int
    missing: int
    missing_by_superclass: dict[str, int]

    @classmethod
    def load(
        cls,
        positions_path: Path,
        *,
        neuron_count: int,
        entry_body_ids: Sequence[int] = (),
        readout_body_ids: Sequence[int] = (),
    ) -> BrainAtlas:
        if not positions_path.is_file():
            raise ReadinessError(
                f"Soma positions are missing: {positions_path}. Build them from the "
                "released annotation table before rendering."
            )
        payload = np.load(positions_path, allow_pickle=True)
        dense = np.asarray(payload["dense_index"], dtype=np.int64)
        body_id = (
            np.asarray(payload["body_id"], dtype=np.int64)
            if "body_id" in payload.files
            else np.zeros(dense.size, dtype=np.int64)
        )
        xyz = np.asarray(payload["xyz"], dtype=np.float32)
        superclass = np.asarray(payload["superclass"]).astype(str)
        missing = np.asarray(payload["missing_dense_index"], dtype=np.int64)
        if dense.shape[0] != xyz.shape[0]:
            raise ConfigurationError("Soma position arrays disagree in length")

        # Normalise into a unit box, keeping the aspect ratio so the shape is not stretched.
        centre = 0.5 * (xyz.max(axis=0) + xyz.min(axis=0))
        scale = float(np.max(xyz.max(axis=0) - xyz.min(axis=0)))
        unit = (xyz - centre) / (scale if scale > 0.0 else 1.0)

        tint = np.empty((dense.size, 3), dtype=np.float32)
        for index, name in enumerate(superclass):
            tint[index] = REGION_TINT.get(name, DEFAULT_TINT)

        role = np.zeros(dense.size, dtype=np.uint8)
        order = np.argsort(body_id)
        sorted_ids = body_id[order]
        for value, wanted in ((1, entry_body_ids), (2, readout_body_ids)):
            requested = np.asarray(list(wanted), dtype=np.int64)
            if requested.size == 0:
                continue
            slot = np.searchsorted(sorted_ids, requested)
            slot = np.clip(slot, 0, sorted_ids.size - 1)
            matched = sorted_ids[slot] == requested
            role[order[slot[matched]]] = value

        missing_counts: dict[str, int] = {}
        if "missing_superclass" in payload.files:
            for name in np.asarray(payload["missing_superclass"]).astype(str):
                missing_counts[name] = missing_counts.get(name, 0) + 1
        return cls(
            dense_index=dense,
            body_id=body_id,
            unit_xyz=unit,
            tint=tint,
            role=role,
            drawn=int(dense.size),
            missing=int(missing.size),
            missing_by_superclass=missing_counts,
        )

    def project(
        self,
        azimuth_rad: float,
        elevation_rad: float,
        width: int,
        height: int,
        view: str = "frontal",
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Orthographic screen coordinates and a depth term in [0, 1].

        The released axes are used as they come: x separates left from right (left somata
        average 80,090 against 16,756 on the right), and z runs from the brain into the
        ventral cord (about 33,000 against 101,000), so z is the vertical axis and the
        brain sits above the cord.
        """
        x = self.unit_xyz[:, 0]
        y = self.unit_xyz[:, 1]
        z = self.unit_xyz[:, 2]
        ca, sa = math.cos(azimuth_rad), math.sin(azimuth_rad)
        horizontal = x * ca - y * sa
        depth = x * sa + y * ca
        ce, se = math.cos(elevation_rad), math.sin(elevation_rad)
        if view == "dorsal":
            # Looking down the dorsoventral axis: left-right across, front-back down.
            # The released x increases toward the fly's left, and screen columns increase
            # rightward, so the axis is negated. A dorsal view with anterior at the top of
            # frame shows the animal's left on the viewer's left, which is what the frame
            # caption claims and what this makes true.
            horizontal = -(x * ca - z * sa)
            spin = x * sa + z * ca
            vertical = y * ce - spin * se
            depth_out = spin * ce + y * se
        else:
            # Image rows increase downward and released z increases from the brain into
            # the ventral cord, so +z draws the brain above the cord as an anatomist would.
            vertical = z * ce - depth * se
            depth_out = depth * ce + z * se

        margin = 0.03
        h_span = float(np.ptp(horizontal)) or 1.0
        v_span = float(np.ptp(vertical)) or 1.0
        usable = 1.0 - 2.0 * margin
        scale = min(usable * (width - 1) / h_span, usable * (height - 1) / v_span)
        px = (horizontal - float(horizontal.min())) * scale
        py = (vertical - float(vertical.min())) * scale
        px += (width - 1 - float(np.ptp(px))) / 2.0
        py += (height - 1 - float(np.ptp(py))) / 2.0
        near = float(depth_out.min())
        far = float(depth_out.max())
        normalised = (depth_out - near) / ((far - near) if far > near else 1.0)
        return px, py, normalised.astype(np.float32)


GLOW_KERNEL: tuple[tuple[int, int, float], ...] = (
    (0, 0, 1.0),
    (1, 0, 0.34),
    (-1, 0, 0.34),
    (0, 1, 0.34),
    (0, -1, 0.34),
)


def _accumulate(
    buffer: np.ndarray, px: np.ndarray, py: np.ndarray, values: np.ndarray, glow: bool
) -> None:
    """Add per-point values into an (H, W, C) float buffer with an optional 1-pixel glow.

    ``values`` is (N, C) and must match the buffer's channel count, so the same routine
    accumulates three-channel colour and the single-channel density map that colour is
    later divided by. Both have to use the identical kernel or the division is meaningless.
    """
    height, width, channels = buffer.shape
    ix = np.rint(px).astype(np.int64)
    iy = np.rint(py).astype(np.int64)
    inside = (ix >= 1) & (ix < width - 1) & (iy >= 1) & (iy < height - 1)
    if not np.any(inside):
        return
    ix, iy, values = ix[inside], iy[inside], values[inside]
    offsets = GLOW_KERNEL if glow else ((0, 0, 1.0),)
    flat_size = height * width
    for dx, dy, weight in offsets:
        flat = (iy + dy) * width + (ix + dx)
        for channel in range(channels):
            buffer[..., channel] += np.bincount(
                flat, weights=values[:, channel] * weight, minlength=flat_size
            ).reshape(height, width)


@dataclass(frozen=True, slots=True)
class BrainProjection:
    """Everything about one fixed viewpoint that does not change from frame to frame.

    The structural cloud and the per-pixel neuron density depend only on the viewpoint, so
    with a fixed camera they are computed once for the whole video instead of 600 times.
    The view is fixed on purpose: an orbiting point cloud reads as a tumbling blob, while a
    still anatomical view reads as a brain and lets the eye attribute every change on screen
    to activity, which is the only thing that should be moving.
    """

    px: np.ndarray
    py: np.ndarray
    depth: np.ndarray
    structure: np.ndarray
    density: np.ndarray
    width: int
    height: int

    @classmethod
    def build(
        cls,
        atlas: BrainAtlas,
        *,
        azimuth_rad: float,
        elevation_rad: float,
        width: int,
        height: int,
        view: str = "frontal",
    ) -> BrainProjection:
        px, py, depth = atlas.project(azimuth_rad, elevation_rad, width, height, view=view)

        structure = np.zeros((height, width, 3), dtype=np.float64)
        # The structural cloud, dimmed with depth so the shape reads as three-dimensional.
        shade = (0.45 + 0.55 * depth).astype(np.float32)[:, None]
        _accumulate(structure, px, py, STRUCTURE_COLOUR[None, :] * shade, glow=False)

        # Declared populations, always visible so the viewer can see where input enters and
        # where the readout is taken even while they are silent.
        for value, colour in ((1, ROLE_COLOURS["entry"]), (2, ROLE_COLOURS["readout"])):
            mask = atlas.role == value
            if not np.any(mask):
                continue
            tint = np.tile(np.asarray(colour, dtype=np.float32), (int(mask.sum()), 1))
            _accumulate(structure, px[mask], py[mask], tint * 0.22, glow=False)

        density = np.zeros((height, width, 1), dtype=np.float64)
        _accumulate(density, px, py, np.ones((px.size, 1), dtype=np.float64), glow=True)
        lit = density[..., 0] > 0.0
        if np.any(lit):
            structure *= STRUCTURE_REFERENCE_DENSITY / float(density[..., 0][lit].mean())
        return cls(
            px=px,
            py=py,
            depth=depth,
            structure=structure,
            density=density,
            width=width,
            height=height,
        )


def render_brain(
    atlas: BrainAtlas,
    glow: np.ndarray,
    *,
    azimuth_rad: float = 0.0,
    elevation_rad: float = 0.0,
    width: int = 0,
    height: int = 0,
    exposure: float = ACTIVITY_EXPOSURE,
    gain: float = ACTIVITY_GAIN,
    view: str = "frontal",
    projection: BrainProjection | None = None,
) -> np.ndarray:
    """One brain frame. ``glow`` is a per-drawn-neuron activity level, already decayed.

    Pass a prebuilt ``projection`` to reuse a fixed viewpoint across a whole video.
    """
    if projection is None:
        projection = BrainProjection.build(
            atlas,
            azimuth_rad=azimuth_rad,
            elevation_rad=elevation_rad,
            width=width,
            height=height,
            view=view,
        )
    activity = np.zeros((projection.height, projection.width, 3), dtype=np.float64)
    active = glow > 1e-3
    if np.any(active):
        intensity = activity_intensity(glow[active])[:, None].astype(np.float32)
        active_colour = atlas.tint[active].copy()
        roles = atlas.role[active]
        active_colour[roles == 2] = np.asarray(ROLE_COLOURS["readout"], dtype=np.float32)
        active_colour[roles == 1] = np.asarray(ROLE_COLOURS["entry"], dtype=np.float32)
        _accumulate(
            activity,
            projection.px[active],
            projection.py[active],
            active_colour * intensity,
            glow=True,
        )
        # Mean over the neurons drawn at each pixel, so brightness reports how hard those
        # neurons are firing rather than how many of them happen to project there.
        activity /= np.maximum(projection.density, 1.0)

    buffer = projection.structure + activity * gain
    tone = 1.0 - np.exp(-buffer * exposure)
    return (np.clip(tone, 0.0, 1.0) * 255.0).astype(np.uint8)


class SpikeRecording:
    """Sparse per-interval spike counts, read back for rendering."""

    def __init__(self, path: Path) -> None:
        payload = np.load(path)
        self.offsets = np.asarray(payload["offsets"], dtype=np.int64)
        self.indices = np.asarray(payload["indices"], dtype=np.int64)
        self.counts = np.asarray(payload["counts"], dtype=np.float32)
        self.neuron_count = int(payload["neuron_count"])
        self.intervals = int(self.offsets.size - 1)

    def interval(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        start, stop = int(self.offsets[index]), int(self.offsets[index + 1])
        return self.indices[start:stop], self.counts[start:stop]


def load_trace(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise ReadinessError(f"Trace is empty: {path}")
    return rows


# --------------------------------------------------------------------------------------
# Brain-view geometry, built from the released annotation table
# --------------------------------------------------------------------------------------

SOMA_POSITION_COLUMNS = ("somaLocation", "tosomaLocation")


def build_soma_positions(
    annotations_path: Path, graph: Any, output_path: Path
) -> dict[str, Any]:
    """Cache the released soma coordinates for every in-graph body that has one.

    Read verbatim: nothing here interpolates, guesses or projects a missing position. A
    body without a released ``somaLocation`` (or the ``tosomaLocation`` fallback the table
    also carries) is listed as missing and is not drawn, and the count is reported on
    every rendered frame so the cloud is never mistaken for the whole graph.

    The released axes are used as they come. Measured on this release, x separates left
    from right -- optic-lobe somata average 80,090 on the left against 16,756 on the right
    -- and z runs from the brain into the ventral nerve cord, about 33,000 against 101,000.
    """
    import pyarrow.feather as feather

    table = feather.read_table(annotations_path)
    needed = {"bodyId", "superclass", "somaSide", *SOMA_POSITION_COLUMNS}
    missing_columns = sorted(needed - set(table.column_names))
    if missing_columns:
        raise ConfigurationError(f"Annotation table lacks columns {missing_columns}")
    columns = {name: table.column(name).to_pylist() for name in needed}
    in_graph = {int(value) for value in graph.body_ids}

    dense_ok: list[int] = []
    body_ok: list[int] = []
    coordinates: list[tuple[float, float, float]] = []
    superclasses: list[str] = []
    sides: list[str] = []
    dense_missing: list[int] = []
    missing_superclass: list[str] = []
    for index, body in enumerate(columns["bodyId"]):
        body_id = int(body)
        if body_id not in in_graph:
            continue
        location = columns["somaLocation"][index] or columns["tosomaLocation"][index]
        superclass = str(columns["superclass"][index])
        if location is None or len(location) != 3:
            dense_missing.append(graph.dense_index(body_id))
            missing_superclass.append(superclass)
            continue
        dense_ok.append(graph.dense_index(body_id))
        body_ok.append(body_id)
        coordinates.append(
            (float(location[0]), float(location[1]), float(location[2]))
        )
        superclasses.append(superclass)
        sides.append(str(columns["somaSide"][index]))

    if not dense_ok:
        raise ConfigurationError("No in-graph body carries a released soma position")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        dense_index=np.asarray(dense_ok, dtype=np.int32),
        body_id=np.asarray(body_ok, dtype=np.int64),
        xyz=np.asarray(coordinates, dtype=np.float32),
        superclass=np.asarray(superclasses),
        side=np.asarray(sides),
        missing_dense_index=np.asarray(dense_missing, dtype=np.int32),
        missing_superclass=np.asarray(missing_superclass),
    )
    by_superclass: dict[str, int] = {}
    for name in missing_superclass:
        by_superclass[name] = by_superclass.get(name, 0) + 1
    return {
        "path": str(output_path),
        "drawn": len(dense_ok),
        "missing": len(dense_missing),
        "neurons": int(graph.neuron_count),
        "missing_by_superclass": dict(
            sorted(by_superclass.items(), key=lambda item: -item[1])
        ),
        "read_verbatim": (
            "somaLocation, with tosomaLocation as the released fallback. No position is "
            "interpolated or invented."
        ),
    }


# --------------------------------------------------------------------------------------
# Trace panels
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceChannel:
    """One line on one strip chart."""

    label: str
    values: np.ndarray
    colour: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class TraceStrip:
    """One strip chart: a title, a shared vertical scale, and one or more lines."""

    title: str
    channels: tuple[TraceChannel, ...]
    unit: str
    symmetric: bool = False


def build_strips(rows: list[dict[str, Any]]) -> tuple[TraceStrip, ...]:
    """Turn a recording into the three strips the video shows.

    Three, not four. The causal chain still reads top to bottom -- what the eye received,
    what the brain sent down, what the body was given -- but the whole-population rates
    that used to occupy a fourth strip now appear as live numbers beside the brain, where
    they belong: they describe the picture next to them rather than being a fourth line to
    read. Four dense strip charts made the frame a figure from a paper, and a viewer reads
    two or three traces while a video is moving, not four.
    """

    def column(path: tuple[str, ...], default: float = 0.0) -> np.ndarray:
        out = np.empty(len(rows), dtype=np.float64)
        for index, row in enumerate(rows):
            value: Any = row
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
                if value is None:
                    break
            out[index] = default if value is None else float(value)
        return out

    return (
        TraceStrip(
            title="retinal input: lamina cells driven, and cue angular radius",
            unit="bodies / degrees",
            channels=(
                TraceChannel(
                    "lamina bodies driven", column(("cue", "driven_lamina_bodies")),
                    (90, 230, 120),
                ),
                TraceChannel(
                    "cue angular radius (deg)",
                    column(("cue", "angular_radius_deg")),
                    (170, 200, 255),
                ),
            ),
        ),
        TraceStrip(
            title="descending readout, causally filtered: posterior descending group",
            unit="Hz",
            channels=(
                TraceChannel(
                    "DNp left (160 bodies)",
                    column(("readout_hz", "dn-visual-left")),
                    (255, 90, 110),
                ),
                TraceChannel(
                    "DNp right (158 bodies)",
                    column(("readout_hz", "dn-visual-right")),
                    (255, 190, 90),
                ),
            ),
        ),
        TraceStrip(
            title="decoder command, the only thing the body receives",
            unit="normalised",
            symmetric=True,
            channels=(
                TraceChannel("forward drive", column(("command", "forward")), (200, 220, 255)),
                TraceChannel("yaw drive", column(("command", "yaw")), (255, 140, 200)),
            ),
        ),
    )


def chapter_caption(row: dict[str, Any], variant: str) -> tuple[str, tuple[int, int, int]]:
    """One line saying what is happening right now, read off the recording.

    Not a script. Every branch below is decided by a recorded quantity -- whether the cue
    was present, which control variant this is, what state the decoder was in, which
    descending side was stronger -- so the caption cannot claim something the frame is not
    showing. A video that narrates itself from a timeline can drift from its own data; this
    one cannot.
    """
    if not row["cue"].get("present", True):
        return (
            "no cue on the retina. Same brain, same body, same seed, nothing to see.",
            DIM,
        )
    if variant == "readout-ablated":
        return (
            "the brain is computing normally; the declared readout is zeroed before the "
            "decoder can hear it",
            WARN,
        )
    # The encoder saturates angular radius at a hemisphere once the fly is nearer to the
    # cue than the cue's own radius, which is what "arrived" means for a stimulus that has
    # no collision. Saying so is more useful than describing a turn that is already over.
    if float(row["cue"].get("angular_radius_deg", 0.0)) >= 89.999:
        return (
            "the fly is inside the cue's radius: the encoder saturates its angular radius "
            "at a hemisphere, and the cue is drawn see-through because it has no collision",
            INK,
        )
    state = str(row["command"].get("state", ""))
    if state != "LOCOMOTING":
        return (
            "the cue is on the retina; the descending readout has not crossed the "
            "decoder's threshold",
            DIM,
        )
    left = float(row["readout_hz"].get(VISUAL_LEFT_READOUT_NAME, 0.0))
    right = float(row["readout_hz"].get(VISUAL_RIGHT_READOUT_NAME, 0.0))
    if abs(left - right) < 1e-9:
        return ("the descending readout is symmetric; the body drives forward", INK)
    side = "left" if left > right else "right"
    return (
        f"the descending readout favours the fly's {side} by "
        f"{abs(left - right):.2f} Hz, and the decoder steers that way",
        INK,
    )


# The whole-population rates that used to occupy a fourth strip chart. They belong beside
# the brain, because they describe the picture they sit next to.
LIVE_POOL_ROWS: tuple[tuple[str, str], ...] = (
    ("optic lobe", "optic-lobe"),
    ("visual projection", "visual-projection"),
    ("central brain", "central-brain"),
    ("descending", "descending-all"),
)


def live_pool_rates(row: dict[str, Any]) -> tuple[tuple[str, float], ...]:
    rates = row.get("pool_mean_rate_hz", {})
    return tuple(
        (label, float(rates.get(key, 0.0))) for label, key in LIVE_POOL_ROWS
    )


def draw_strips(
    draw: Any,
    strips: tuple[TraceStrip, ...],
    *,
    origin: tuple[int, int],
    width: int,
    height: int,
    cursor: int,
    fonts: dict[str, Any],
) -> None:
    """Draw every strip with the whole run on the x axis and a playhead at ``cursor``."""
    left, top = origin
    label_width = 330
    plot_left = left + label_width
    plot_width = width - label_width - 30
    count = len(strips)
    gap = 8
    strip_height = (height - gap * (count - 1)) // count
    total = max(1, len(strips[0].channels[0].values))

    for index, strip in enumerate(strips):
        y0 = top + index * (strip_height + gap)
        y1 = y0 + strip_height
        draw.rectangle((plot_left, y0, plot_left + plot_width, y1), fill=(17, 20, 28))
        peak = max(
            float(np.max(np.abs(channel.values))) for channel in strip.channels
        )
        peak = peak if peak > 1e-9 else 1.0
        if strip.symmetric:
            low, high = -peak, peak
            zero_y = (y0 + y1) / 2.0
            draw.line((plot_left, zero_y, plot_left + plot_width, zero_y), fill=(46, 52, 66))
        else:
            low, high = 0.0, peak

        draw.text((left, y0 + 2), strip.title, font=fonts["small"], fill=DIM)
        legend_y = y0 + 20
        for channel in strip.channels:
            draw.line((left, legend_y + 6, left + 18, legend_y + 6), fill=channel.colour, width=3)
            draw.text((left + 24, legend_y), channel.label, font=fonts["tiny"], fill=INK)
            legend_y += 15
        scale_label = f"{high:.3g} {strip.unit}"
        draw.text(
            (plot_left + plot_width - 8 - draw.textlength(scale_label, font=fonts["tiny"]),
             y0 + 2),
            scale_label,
            font=fonts["tiny"],
            fill=DIM,
        )

        span = high - low
        for channel in strip.channels:
            values = channel.values[: cursor + 1]
            if values.size < 2:
                continue
            step = max(1, values.size // plot_width)
            sampled = values[::step]
            xs = plot_left + np.arange(sampled.size) * (plot_width / max(1, total / step))
            ys = y1 - (sampled - low) / span * (strip_height - 4) - 2
            points = [
                (float(a), float(b))
                for a, b in zip(np.clip(xs, plot_left, plot_left + plot_width), ys, strict=True)
            ]
            if len(points) > 1:
                draw.line(points, fill=channel.colour, width=2)
        playhead = plot_left + (cursor / max(1, total - 1)) * plot_width
        draw.line((playhead, y0, playhead, y1), fill=(255, 255, 255), width=1)


def draw_trajectory_inset(
    draw: Any,
    rows: list[dict[str, Any]],
    cursor: int,
    *,
    box: tuple[int, int, int, int],
    cue_xy: tuple[float, float],
    cue_radius_mm: float,
    fonts: dict[str, Any],
    cue_present: bool = True,
) -> None:
    """A top-down map of where the fly has been and, when there is one, where the cue is.

    ``cue_present`` is not cosmetic. The stimulus-absent control's whole claim is that
    there is nothing in the world to react to, and drawing a cue on its map contradicted
    the caption directly above it.
    """
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=(10, 13, 19), outline=(52, 60, 76))
    xs = np.array([row["pose"]["x_mm"] for row in rows], dtype=np.float64)
    ys = np.array([row["pose"]["y_mm"] for row in rows], dtype=np.float64)
    extra_x = [cue_xy[0]] if cue_present else []
    extra_y = [cue_xy[1]] if cue_present else []
    all_x = np.concatenate([xs, extra_x])
    all_y = np.concatenate([ys, extra_y])
    pad = 3.0
    lo_x, hi_x = float(all_x.min()) - pad, float(all_x.max()) + pad
    lo_y, hi_y = float(all_y.min()) - pad, float(all_y.max()) + pad
    span = max(hi_x - lo_x, hi_y - lo_y, 1e-6)
    cx, cy = 0.5 * (lo_x + hi_x), 0.5 * (lo_y + hi_y)
    inner = min(x1 - x0, y1 - y0) - 16

    def to_screen(mx: float, my: float) -> tuple[float, float]:
        sx = (x0 + x1) / 2.0 + (mx - cx) / span * inner
        sy = (y0 + y1) / 2.0 - (my - cy) / span * inner
        return sx, sy

    if cue_present:
        radius_px = max(3.0, cue_radius_mm / span * inner)
        ccx, ccy = to_screen(*cue_xy)
        draw.ellipse(
            (ccx - radius_px, ccy - radius_px, ccx + radius_px, ccy + radius_px),
            fill=(58, 62, 78),
            outline=(150, 160, 185),
        )
        draw.text((ccx + radius_px + 4, ccy - 7), "cue", font=fonts["tiny"], fill=DIM)
    else:
        draw.text((x0 + 6, y1 - 18), "no cue in this world", font=fonts["tiny"], fill=DIM)

    path = [
        to_screen(float(a), float(b))
        for a, b in zip(xs[: cursor + 1], ys[: cursor + 1], strict=True)
    ]
    if len(path) > 1:
        draw.line(path, fill=(120, 180, 255), width=2)
    if path:
        hx, hy = path[-1]
        heading = float(rows[cursor]["pose"]["heading_rad"])
        draw.ellipse((hx - 4, hy - 4, hx + 4, hy + 4), fill=(255, 255, 255))
        draw.line(
            (hx, hy, hx + math.cos(heading) * 14, hy - math.sin(heading) * 14),
            fill=(255, 255, 255),
            width=2,
        )
    draw.text((x0 + 6, y0 + 4), "trajectory (top-down)", font=fonts["tiny"], fill=DIM)


def _fonts() -> dict[str, Any]:
    from PIL import ImageFont

    def pick(size: int) -> Any:
        for name in (
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "arial.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    return {
        "title": pick(26),
        "body": pick(17),
        "small": pick(14),
        "tiny": pick(12),
    }


# --------------------------------------------------------------------------------------
# Opening and closing cards
# --------------------------------------------------------------------------------------


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _card(
    image_class: Any,
    draw_module: Any,
    fonts: dict[str, Any],
    *,
    heading: str,
    lines: list[tuple[str, str]],
    footer: str,
) -> Any:
    """One full-frame card. ``lines`` is a list of (label, body) pairs."""
    canvas = image_class.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
    draw = draw_module.Draw(canvas)
    y = 120
    draw.text((140, y), heading, font=fonts["title"], fill=INK)
    y += 70
    draw.line((140, y, FRAME_WIDTH - 140, y), fill=(40, 48, 62), width=2)
    y += 40
    for label, body in lines:
        if label:
            draw.text((140, y), label, font=fonts["body"], fill=WARN)
            y += 30
        for wrapped in _wrap(draw, body, fonts["body"], FRAME_WIDTH - 320):
            draw.text((160, y), wrapped, font=fonts["body"], fill=INK if label else DIM)
            y += 27
        y += 20
    footer_y = FRAME_HEIGHT - 130
    for wrapped in _wrap(draw, footer, fonts["small"], FRAME_WIDTH - 320):
        draw.text((140, footer_y), wrapped, font=fonts["small"], fill=DIM)
        footer_y += 26
    return canvas


def opening_card(summary: dict[str, Any], fonts: dict[str, Any]) -> Any:
    from PIL import Image, ImageDraw

    graph = summary["graph"]
    populations = summary["populations"]
    entry = sum(populations["entry_sizes"].values())
    return _card(
        Image,
        ImageDraw,
        fonts,
        heading="A visual cue reaching a body through the whole released MaleCNS graph",
        lines=[
            (
                "WHAT IS EXECUTED",
                f"{graph['neurons']:,} neurons and {graph['edges']:,} edges, every one "
                "built and stepped. The engine refuses to run if a single registered edge "
                "is missing.",
            ),
            (
                "THE ONLY ROUTE FROM WORLD TO BODY",
                "cue geometry, then a retinotopic drive on "
                f"{entry:,} lamina monopolar cells, then the full runtime, then a declared "
                "descending readout, a causal filter, an engineering decoder, and the "
                "body. The decoder takes no sensor input and the body publishes no sensory "
                "channel, so there is no shortcut to disable.",
            ),
            (
                "WHAT IS NOT EXECUTED",
                "The retina. All 66,533 photoreceptor output edges are zeroed by the "
                "frozen sign policy, because fly photoreceptors are histaminergic and "
                "histamine is absent from the transmitter model. Entry is one synapse "
                "downstream.",
            ),
            (
                "ENGINEERED STAND-INS",
                "; ".join(
                    scaffold.split(". ")[0].rstrip(".")
                    for scaffold in summary["body"]["scaffolds"]
                )
                + ". None of these is a model of the animal, and the arena holds exactly "
                "one object because the encoder models exactly one.",
            ),
            (
                "TIER",
                "V0 Structural. This is an engineering demonstration. The network "
                "parameters are P/E, the decoder and body are E, and nothing here is "
                "validated physiology or a measurement of a fly.",
            ),
        ],
        footer=(
            f"commit {summary.get('code_commit', 'unknown')}    "
            f"graph sha256 {graph['source_sha256'][:16]}    seed {summary['seed']}"
        ),
    )


def verdict_card(
    summary: dict[str, Any], verdict: dict[str, Any] | None, fonts: dict[str, Any]
) -> Any:
    from PIL import Image, ImageDraw

    if verdict is None:
        lines = [
            (
                "NO VERDICT HAS BEEN COMPUTED",
                "This recording has not been through the frozen acceptance contract, so "
                "nothing about causation may be read off it. A single run that looks right "
                "is exactly what the predecessor demonstration produced while its body was "
                "not listening to its brain.",
            )
        ]
    else:
        measured = verdict["measured"]
        criteria = verdict["criteria"]
        rows = "    |    ".join(
            f"{name} {row['displacement_mm']:.2f} mm"
            for name, row in measured.items()
        )
        marks = "    |    ".join(
            f"{name.split('_')[0]} {'PASS' if row['passed'] else 'FAIL'}"
            for name, row in criteria.items()
        )
        lines = [
            ("VERDICT", str(verdict["claim"])),
            ("", str(verdict["claim_text"])),
            ("DISPLACEMENT BY VARIANT", rows),
            ("FROZEN CRITERIA", marks),
            (
                "WHAT MAY NEVER BE CLAIMED",
                str(verdict["may_never_claim"]),
            ),
        ]
    return _card(
        Image,
        ImageDraw,
        fonts,
        heading="What this does and does not establish",
        lines=lines,
        footer=(
            "The contract was committed before these runs, and the code that applies it "
            "cannot run a simulation or alter a threshold."
        ),
    )


def _open_body_source(
    run_directory: Path, summary: dict[str, Any], resolution: tuple[int, int]
) -> tuple[Any, Any, Any]:
    """Prefer replay from recorded physics state; fall back to a run's baked-in video.

    Recordings made before the body became re-renderable carry `body.mp4` and no `qpos`,
    and they still render, from the camera they were made with. New recordings carry the
    state and get the shot list.
    """
    from flysim.demo01_body import Demo01BodyParameters
    from flysim.demo01_replay import BodyReplay, PoseRecording

    poses_path = run_directory / "poses.npz"
    raw = summary.get("body", {}).get("parameters")
    if poses_path.is_file() and raw:
        poses = PoseRecording(poses_path)
        replay = BodyReplay(
            Demo01BodyParameters.from_mapping(raw),
            seed=int(summary["seed"]),
            resolution=resolution,
        )
        return replay, poses, None

    import imageio.v2 as imageio

    video = run_directory / "body.mp4"
    if video.is_file():
        return None, None, imageio.get_reader(video)
    raise ReadinessError(
        f"{run_directory} carries neither poses.npz nor body.mp4, so the body cannot be "
        "drawn. Re-run the recording."
    )


def render_recording(
    run_directory: Path,
    *,
    positions_path: Path,
    output_path: Path | None = None,
    fps: int = 30,
    orbit_degrees_per_second: float = 0.0,
    glow_decay: float = 0.78,
    title: str | None = None,
) -> Path:
    """Composite one recording into an MP4. Reads only; simulates nothing."""
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ReadinessError("Rendering needs imageio and Pillow") from exc

    from flysim.demo01_replay import ShotPlan, frame_camera, smooth_track

    summary = json.loads((run_directory / "summary.json").read_text(encoding="utf-8"))
    rows = load_trace(run_directory / "trace.jsonl")
    spikes = SpikeRecording(run_directory / "spikes.npz")
    if spikes.intervals != len(rows):
        raise ConfigurationError(
            f"Recording is inconsistent: {len(rows)} trace rows against "
            f"{spikes.intervals} spike intervals"
        )
    populations = summary["populations"]
    atlas = BrainAtlas.load(
        positions_path,
        neuron_count=spikes.neuron_count,
        entry_body_ids=populations.get("entry_body_ids", ()),
        readout_body_ids=populations.get("readout_body_ids", ()),
    )
    strips = build_strips(rows)
    fonts = _fonts()

    replay, poses, body_reader = _open_body_source(
        run_directory, summary, (PANEL_HEIGHT, BODY_WIDTH)
    )
    # Read baked-in frames one at a time rather than buffering them. A 20 s run at
    # 770x640 is about 900 MB of uint8 if held in a list, which is a large amount of
    # memory to spend on frames that are consumed strictly in order.
    body_iterator: Iterator[Any] | None = (
        iter(body_reader.iter_data()) if body_reader is not None else None
    )
    body_frame: np.ndarray | None = None
    body_exhausted = body_iterator is None

    output_path = output_path or run_directory / "demo.mp4"
    writer = imageio.get_writer(output_path, fps=fps, codec="libx264", quality=9)

    verdict_path = run_directory.parent / "acceptance.json"
    verdict = (
        json.loads(verdict_path.read_text(encoding="utf-8"))
        if verdict_path.is_file()
        else None
    )
    opening_seconds, closing_seconds = 5, 6

    coupling_us = int(summary["coupling_us"])
    interval_s = coupling_us / 1_000_000.0
    frame_period_s = 1.0 / fps
    variant = str(summary["variant"])
    heading = title or "MaleCNS full-graph closed loop"
    glow = np.zeros(atlas.drawn, dtype=np.float32)

    # The camera track: recorded poses, smoothed over about a third of a second so the
    # shot does not shake with every step. Only the camera sees the smoothed values.
    onset_us = summary.get("outcome", {}).get("locomotion_onset_us")
    plan = ShotPlan.from_recording(
        duration_s=len(rows) * interval_s,
        onset_s=None if onset_us is None else float(onset_us) / 1e6,
    )
    track_x, track_y, track_z, track_heading = smooth_track(
        np.array([row["pose"]["x_mm"] for row in rows]),
        np.array([row["pose"]["y_mm"] for row in rows]),
        np.array([row["pose"]["z_mm"] for row in rows]),
        np.array([row["pose"]["heading_rad"] for row in rows]),
        window=max(3, round(0.35 / interval_s)),
    )
    cue_xy = (
        float(summary["body"]["cue_xy_mm"][0]),
        float(summary["body"]["cue_xy_mm"][1]),
    )
    cue_radius_mm = float(summary["body"]["cue_radius_mm"])
    cue_height_mm = float(
        summary["body"].get("parameters", {}).get("cue_height_mm", cue_radius_mm)
    )
    # Map dense graph index to a row in the drawn cloud, once.
    row_by_dense = np.full(spikes.neuron_count, -1, dtype=np.int64)
    row_by_dense[atlas.dense_index] = np.arange(atlas.drawn, dtype=np.int64)

    frame_count = max(1, round(len(rows) * interval_s * fps))
    # The dorsal view is the hero: it shows both optic lobes, the central brain and the
    # left-right asymmetry the demonstration is about. The frontal view goes in a corner
    # inset because its job is only to show that the ventral nerve cord is there and
    # running. Both are fixed, and both are therefore built once.
    inset_size = 300
    dorsal_projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(6.0),
        width=BRAIN_VIEW_WIDTH,
        height=PANEL_HEIGHT,
        view="dorsal",
    )
    frontal_projection = BrainProjection.build(
        atlas,
        azimuth_rad=math.radians(20.0),
        elevation_rad=math.radians(10.0),
        width=inset_size,
        height=inset_size,
        view="frontal",
    )
    try:
        opening = np.asarray(opening_card(summary, fonts))
        for _ in range(opening_seconds * fps):
            writer.append_data(opening)
        for frame_index in range(frame_count):
            t_s = frame_index * frame_period_s
            cursor = min(len(rows) - 1, int(t_s / interval_s))
            # Every interval since the previous frame contributes, so no spike is dropped
            # when the coupling interval is shorter than the frame period.
            previous_cursor = (
                min(len(rows) - 1, int((frame_index - 1) * frame_period_s / interval_s))
                if frame_index
                else -1
            )
            glow *= glow_decay
            for interval in range(previous_cursor + 1, cursor + 1):
                indices, counts = spikes.interval(interval)
                if indices.size == 0:
                    continue
                target = row_by_dense[indices]
                keep = target >= 0
                if np.any(keep):
                    np.add.at(glow, target[keep], counts[keep])

            if orbit_degrees_per_second:
                spin = math.radians(orbit_degrees_per_second * t_s)
                dorsal_projection = BrainProjection.build(
                    atlas,
                    azimuth_rad=spin * 0.5,
                    elevation_rad=math.radians(6.0),
                    width=BRAIN_VIEW_WIDTH,
                    height=PANEL_HEIGHT,
                    view="dorsal",
                )
            dorsal = render_brain(atlas, glow, projection=dorsal_projection)
            frontal = render_brain(atlas, glow, projection=frontal_projection)

            canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
            canvas.paste(Image.fromarray(dorsal), (BRAIN_VIEW_LEFT, HEADER_HEIGHT))
            inset_x = 10
            inset_y = HEADER_HEIGHT + PANEL_HEIGHT - inset_size - 30
            canvas.paste(Image.fromarray(frontal), (inset_x, inset_y))
            row = rows[cursor]
            if replay is not None and poses is not None:
                shot = plan.shot_at(t_s)
                framing = frame_camera(
                    shot,
                    fly_xyz_mm=(
                        float(track_x[cursor]),
                        float(track_y[cursor]),
                        float(track_z[cursor]),
                    ),
                    heading_rad=float(track_heading[cursor]),
                    cue_xy_mm=cue_xy,
                    cue_height_mm=cue_height_mm,
                    cue_radius_mm=cue_radius_mm,
                    cue_present=bool(row["cue"].get("present", True)),
                    t_s=t_s,
                )
                body_frame = np.asarray(
                    replay.render(
                        poses.at(cursor),
                        framing,
                        cue_visible=bool(row["cue"].get("present", True)),
                    )
                )
            elif body_iterator is not None and not body_exhausted:
                try:
                    body_frame = np.asarray(next(body_iterator))
                except StopIteration:
                    # The body video ends when the recording does; hold the last frame
                    # rather than blanking the panel under the closing card.
                    body_exhausted = True
            if body_frame is not None:
                image = Image.fromarray(body_frame)
                if image.size != (BODY_WIDTH, PANEL_HEIGHT):
                    image = image.resize((BODY_WIDTH, PANEL_HEIGHT))
                canvas.paste(image, (BRAIN_WIDTH, HEADER_HEIGHT))
            else:
                ImageDraw.Draw(canvas).rectangle(
                    (BRAIN_WIDTH, HEADER_HEIGHT, FRAME_WIDTH, HEADER_HEIGHT + PANEL_HEIGHT),
                    fill=PANEL,
                )

            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, FRAME_WIDTH, HEADER_HEIGHT), fill=(13, 16, 23))
            draw.text((26, 10), heading, font=fonts["title"], fill=INK)
            draw.text(
                (26, 42),
                f"165,122 neurons and 25,563,197 edges, every one stepped   |   "
                f"t = {t_s:5.2f} s   |   state {row['command']['state']}   |   "
                f"control variant: {variant}",
                font=fonts["small"],
                fill=DIM,
            )
            chip = "V0 STRUCTURAL - ENGINEERING DEMONSTRATION - NOT VALIDATED PHYSIOLOGY"
            draw.text((FRAME_WIDTH - 640, 14), chip, font=fonts["small"], fill=WARN)
            draw.text(
                (FRAME_WIDTH - 640, 36),
                "P/E network parameters, E decoder and body",
                font=fonts["tiny"],
                fill=DIM,
            )

            draw.rectangle(
                (inset_x, inset_y, inset_x + inset_size, inset_y + inset_size),
                outline=(34, 40, 52),
            )
            draw.text(
                (inset_x + 6, inset_y + inset_size + 4),
                "frontal view: brain above, ventral nerve cord below",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (BRAIN_WIDTH - 436, HEADER_HEIGHT + 8),
                "dorsal view, looking down. Left of frame is the fly's left.",
                font=fonts["tiny"],
                fill=DIM,
            )
            legend_x1 = 344
            legend_y = HEADER_HEIGHT + 12
            # Drawn filled and first, because an unfilled legend sitting on top of a point
            # cloud is unreadable, which is what the first cut of this video did.
            draw.rectangle(
                (8, legend_y - 6, legend_x1, legend_y + LEGEND_HEIGHT),
                fill=(10, 12, 18),
                outline=(30, 36, 48),
            )
            draw.text(
                (16, legend_y),
                "brain: released soma positions",
                font=fonts["small"],
                fill=DIM,
            )
            for label, colour in (
                (f"lamina entry ({sum(populations['entry_sizes'].values())} bodies)",
                 ROLE_COLOURS["entry"]),
                ("DNp readout (318 bodies)", ROLE_COLOURS["readout"]),
                ("optic lobe", REGION_TINT["ol_intrinsic"]),
                ("visual projection", REGION_TINT["visual_projection"]),
                ("central brain", REGION_TINT["cb_intrinsic"]),
                ("ventral nerve cord", REGION_TINT["vnc_intrinsic"]),
            ):
                legend_y += 18
                rgb = tuple(int(255 * c) for c in colour)
                draw.rectangle((16, legend_y + 4, 28, legend_y + 12), fill=rgb)
                draw.text((34, legend_y), label, font=fonts["tiny"], fill=INK)
            legend_y += 24
            draw.text(
                (16, legend_y),
                f"{atlas.drawn:,} of {spikes.neuron_count:,} drawn. {atlas.missing:,} have no",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (16, legend_y + 13),
                "released soma position and cannot be drawn.",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (16, legend_y + 26),
                "Brightness: mean recent spike count of the",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (16, legend_y + 39),
                "neurons drawn at that pixel, on a fixed log scale.",
                font=fonts["tiny"],
                fill=DIM,
            )
            # The whole-population rates, live. These used to be a fourth strip chart at
            # the bottom of the frame, a long way from the picture they describe.
            legend_y += 60
            draw.text(
                (16, legend_y), "population rate, this interval", font=fonts["small"], fill=DIM
            )
            for label, value in live_pool_rates(row):
                legend_y += 16
                draw.text((22, legend_y), label, font=fonts["tiny"], fill=INK)
                text = f"{value:6.2f} Hz"
                draw.text(
                    (legend_x1 - 12 - draw.textlength(text, font=fonts["tiny"]), legend_y),
                    text,
                    font=fonts["tiny"],
                    fill=INK,
                )

            # What is happening right now, read off the recording rather than scripted.
            caption, caption_colour = chapter_caption(row, variant)
            band_top = HEADER_HEIGHT + PANEL_HEIGHT - 30
            draw.rectangle(
                (BRAIN_VIEW_LEFT, band_top, BRAIN_WIDTH, HEADER_HEIGHT + PANEL_HEIGHT),
                fill=(10, 12, 18),
            )
            draw.text(
                (BRAIN_VIEW_LEFT + 12, band_top + 7),
                caption,
                font=fonts["small"],
                fill=caption_colour,
            )

            cue = row["cue"]
            bearing = cue["bearing_deg"]
            # The body view has a bright sky, so the caption needs its own ground.
            draw.rectangle(
                (BRAIN_WIDTH + 8, HEADER_HEIGHT + 6, FRAME_WIDTH - 8, HEADER_HEIGHT + 74),
                fill=(10, 12, 18),
            )
            draw.text(
                (BRAIN_WIDTH + 16, HEADER_HEIGHT + 12),
                "body: FlyGym / MuJoCo, engineered walking controller",
                font=fonts["small"],
                fill=DIM,
            )
            draw.text(
                (BRAIN_WIDTH + 16, HEADER_HEIGHT + 32),
                (
                    f"cue bearing {bearing:+6.1f} deg" if bearing is not None
                    else "cue absent (stimulus-absent control)"
                ),
                font=fonts["small"],
                fill=INK,
            )
            draw.text(
                (BRAIN_WIDTH + 16, HEADER_HEIGHT + 52),
                f"cue distance {cue['distance_mm']:6.2f} mm",
                font=fonts["small"],
                fill=INK,
            )
            draw_trajectory_inset(
                draw,
                rows,
                cursor,
                # Bottom right, because the establishing shot puts the fly on the left of
                # the body panel and an inset in that corner covered the animal.
                box=(
                    FRAME_WIDTH - 246,
                    HEADER_HEIGHT + PANEL_HEIGHT - 250,
                    FRAME_WIDTH - 16,
                    HEADER_HEIGHT + PANEL_HEIGHT - 20,
                ),
                cue_xy=(
                    float(summary["body"]["cue_xy_mm"][0]),
                    float(summary["body"]["cue_xy_mm"][1]),
                ),
                cue_radius_mm=float(summary["body"]["cue_radius_mm"]),
                fonts=fonts,
                cue_present=bool(row["cue"].get("present", True)),
            )

            draw_strips(
                draw,
                strips,
                origin=(26, HEADER_HEIGHT + PANEL_HEIGHT + 8),
                width=FRAME_WIDTH - 52,
                height=TRACE_HEIGHT - 16,
                cursor=cursor,
                fonts=fonts,
            )

            # Two lines, not three. The full list of engineered stand-ins moved to the
            # opening card, where a viewer has time to read it; what stays on every frame
            # is the sentence that would change how the frame is understood.
            footer_y = FRAME_HEIGHT - FOOTER_HEIGHT
            draw.rectangle((0, footer_y, FRAME_WIDTH, FRAME_HEIGHT), fill=(13, 16, 23))
            draw.text(
                (26, footer_y + 9),
                "The walking controller is an engineered pattern generator, not the "
                "simulated ventral cord. The retina-to-lamina synapse is NOT executed: the "
                "frozen sign policy zeroes all 66,533 photoreceptor edges.",
                font=fonts["tiny"],
                fill=WARN,
            )
            draw.text(
                (26, footer_y + 30),
                "Network parameters are P/E and the decoder and body are E. The camera "
                "track is smoothed for display; no recorded quantity is.    "
                f"commit {summary.get('code_commit', 'unknown')[:12]}   "
                f"graph sha256 {summary['graph']['source_sha256'][:16]}   "
                f"seed {summary['seed']}",
                font=fonts["tiny"],
                fill=DIM,
            )
            writer.append_data(np.asarray(canvas))
        closing = np.asarray(verdict_card(summary, verdict, fonts))
        for _ in range(closing_seconds * fps):
            writer.append_data(closing)
    finally:
        writer.close()
        if body_reader is not None:
            body_reader.close()
        if replay is not None:
            replay.close()
    return output_path.resolve()


# --------------------------------------------------------------------------------------
# The control comparison: four identical-seed runs side by side
# --------------------------------------------------------------------------------------
#
# This is the shot that carries the causal evidence, and it is the one a viewer should be
# shown before the single-run video rather than after. Four runs from an identical seed,
# on the same time axis: the exact graph, the same brain with its readout silenced, the
# same everything with no cue, and a degree-preserving shuffle of the graph. If the four
# panels look alike, the demonstration has not shown what it claims, and the frame says so
# rather than leaving the viewer to notice.

COMPARISON_PANEL_ORDER = (
    "exact",
    "readout-ablated",
    "stimulus-absent",
    "shuffled-connectome",
)

# The ablated caption is worded carefully. Zeroing the readout after the brain has
# computed it leaves the two brains identical *given identical input*, and that stops
# being true the moment the bodies differ: the exact fly approaches, so its cue looms
# larger and drives the lamina harder, while the ablated fly stands still and its retinal
# input never grows. The panels visibly diverge in brightness for that reason, and the
# divergence is evidence the loop is closed rather than a discrepancy to explain away.
# An earlier caption said "identical brain", which was true only at the first interval.
COMPARISON_CAPTIONS = {
    "exact": "EXACT: the released graph, all 25,563,197 edges",
    "readout-ablated": "READOUT ABLATED: readout zeroed after the brain computes it",
    "stimulus-absent": "STIMULUS ABSENT: identical everything, no cue",
    "shuffled-connectome": "SHUFFLED: same edge count and out-degrees, rewired",
}


def render_comparison(
    run_root: Path,
    *,
    positions_path: Path,
    output_path: Path | None = None,
    fps: int = 30,
    variants: Sequence[str] = COMPARISON_PANEL_ORDER,
    glow_decay: float = 0.78,
) -> Path:
    """Composite the control variants into one frame each, on a shared clock.

    Each panel shows that variant's brain activity and its trajectory, and the panel
    footer carries its measured displacement. Panels for variants that were not run are
    drawn as explicit gaps rather than omitted, so a missing control is visible.
    """
    try:
        import imageio.v2 as imageio
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ReadinessError("Rendering needs imageio and Pillow") from exc

    loaded: dict[str, dict[str, Any]] = {}
    for variant in variants:
        directory = run_root / variant
        if not (directory / "summary.json").is_file():
            continue
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        rows = load_trace(directory / "trace.jsonl")
        spikes = SpikeRecording(directory / "spikes.npz")
        loaded[variant] = {"summary": summary, "rows": rows, "spikes": spikes}
    if "exact" not in loaded:
        raise ReadinessError(
            f"The comparison needs the exact run at {run_root / 'exact'}"
        )

    reference = loaded["exact"]
    atlas = BrainAtlas.load(
        positions_path,
        neuron_count=reference["spikes"].neuron_count,
        entry_body_ids=reference["summary"]["populations"].get("entry_body_ids", ()),
        readout_body_ids=reference["summary"]["populations"].get("readout_body_ids", ()),
    )
    row_by_dense = np.full(reference["spikes"].neuron_count, -1, dtype=np.int64)
    row_by_dense[atlas.dense_index] = np.arange(atlas.drawn, dtype=np.int64)

    fonts = _fonts()
    coupling_us = int(reference["summary"]["coupling_us"])
    interval_s = coupling_us / 1_000_000.0
    intervals = len(reference["rows"])
    frame_count = max(1, round(intervals * interval_s * fps))

    header = 78
    footer = 52
    panel_w = FRAME_WIDTH // 2
    panel_h = (FRAME_HEIGHT - header - footer) // 2
    brain_w = 620
    brain_h = panel_h - 96
    side_x = 636
    side_w = 310
    side_h = 200
    glow = {variant: np.zeros(atlas.drawn, dtype=np.float32) for variant in loaded}
    projection = BrainProjection.build(
        atlas,
        azimuth_rad=0.0,
        elevation_rad=math.radians(6.0),
        width=brain_w,
        height=brain_h,
        view="dorsal",
    )

    # Each panel gets its own fly, drawn through one shared shot plan. The plan comes from
    # the exact run so that at any instant all four panels are in the same kind of shot
    # following their own animal, which is what makes them comparable. Cutting each panel
    # on its own events would have three of them establishing while the fourth arrives.
    from flysim.demo01_replay import ShotPlan, frame_camera, smooth_track

    onset_us = reference["summary"].get("outcome", {}).get("locomotion_onset_us")
    plan = ShotPlan.from_recording(
        duration_s=intervals * interval_s,
        onset_s=None if onset_us is None else float(onset_us) / 1e6,
    )
    for variant, payload in loaded.items():
        try:
            replay, poses, _ = _open_body_source(
                run_root / variant, payload["summary"], (side_h, side_w)
            )
        except ReadinessError:
            replay, poses = None, None
        payload["replay"] = replay
        payload["poses"] = poses
        rows = payload["rows"]
        payload["track"] = smooth_track(
            np.array([row["pose"]["x_mm"] for row in rows]),
            np.array([row["pose"]["y_mm"] for row in rows]),
            np.array([row["pose"]["z_mm"] for row in rows]),
            np.array([row["pose"]["heading_rad"] for row in rows]),
            window=max(3, round(0.35 / interval_s)),
        )

    output_path = output_path or run_root / "control-comparison.mp4"
    writer = imageio.get_writer(output_path, fps=fps, codec="libx264", quality=9)
    try:
        for frame_index in range(frame_count):
            t_s = frame_index / fps
            cursor = min(intervals - 1, int(t_s / interval_s))
            previous = (
                min(intervals - 1, int((frame_index - 1) / fps / interval_s))
                if frame_index
                else -1
            )
            canvas = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), BACKGROUND)
            draw = ImageDraw.Draw(canvas)

            draw.rectangle((0, 0, FRAME_WIDTH, header), fill=(13, 16, 23))
            draw.text(
                (26, 8),
                "MaleCNS full-graph closed loop: identical-seed controls",
                font=fonts["title"],
                fill=INK,
            )
            draw.text(
                (26, 40),
                "Same seed, same body, same decoder, same operating point. If these four "
                f"panels behave alike, the demonstration has not shown a neural cause.   "
                f"t = {t_s:5.2f} s",
                font=fonts["small"],
                fill=DIM,
            )
            draw.text(
                (FRAME_WIDTH - 640, 14),
                "V0 STRUCTURAL - ENGINEERING DEMONSTRATION - NOT VALIDATED PHYSIOLOGY",
                font=fonts["small"],
                fill=WARN,
            )

            for index, variant in enumerate(variants):
                col, rowi = index % 2, index // 2
                x0 = col * panel_w
                y0 = header + rowi * panel_h
                draw.rectangle(
                    (x0 + 4, y0 + 4, x0 + panel_w - 4, y0 + panel_h - 4),
                    outline=(34, 40, 52),
                )
                if variant not in loaded:
                    draw.text(
                        (x0 + 20, y0 + panel_h // 2),
                        f"{variant}: NOT RUN",
                        font=fonts["body"],
                        fill=WARN,
                    )
                    continue
                payload = loaded[variant]
                rows = payload["rows"]
                local_cursor = min(len(rows) - 1, cursor)
                state = glow[variant]
                state *= glow_decay
                for interval in range(previous + 1, local_cursor + 1):
                    if interval >= payload["spikes"].intervals:
                        break
                    indices, counts = payload["spikes"].interval(interval)
                    if indices.size == 0:
                        continue
                    target = row_by_dense[indices]
                    keep = target >= 0
                    if np.any(keep):
                        np.add.at(state, target[keep], counts[keep])
                brain = render_brain(atlas, state, projection=projection)
                canvas.paste(Image.fromarray(brain), (x0 + 8, y0 + 30))

                draw.text(
                    (x0 + 14, y0 + 8),
                    COMPARISON_CAPTIONS.get(variant, variant),
                    font=fonts["body"],
                    fill=INK if variant == "exact" else DIM,
                )
                row = rows[local_cursor]
                cue_present = bool(row["cue"].get("present", True))
                body_summary = payload["summary"]["body"]

                # This panel's own fly, in the same shot as every other panel's.
                if payload["replay"] is not None and payload["poses"] is not None:
                    track_x, track_y, track_z, track_h = payload["track"]
                    body_parameters = body_summary.get("parameters", {})
                    framing = frame_camera(
                        plan.shot_at(t_s),
                        fly_xyz_mm=(
                            float(track_x[local_cursor]),
                            float(track_y[local_cursor]),
                            float(track_z[local_cursor]),
                        ),
                        heading_rad=float(track_h[local_cursor]),
                        cue_xy_mm=(
                            float(body_summary["cue_xy_mm"][0]),
                            float(body_summary["cue_xy_mm"][1]),
                        ),
                        cue_height_mm=float(
                            body_parameters.get(
                                "cue_height_mm", body_summary["cue_radius_mm"]
                            )
                        ),
                        cue_radius_mm=float(body_summary["cue_radius_mm"]),
                        cue_present=cue_present,
                        t_s=t_s,
                    )
                    body_frame = np.asarray(
                        payload["replay"].render(
                            payload["poses"].at(local_cursor),
                            framing,
                            cue_visible=cue_present,
                        )
                    )
                    canvas.paste(
                        Image.fromarray(body_frame).resize((side_w, side_h)),
                        (x0 + side_x, y0 + 30),
                    )
                else:
                    draw.rectangle(
                        (x0 + side_x, y0 + 30, x0 + side_x + side_w, y0 + 30 + side_h),
                        fill=PANEL,
                        outline=(34, 40, 52),
                    )
                    draw.text(
                        (x0 + side_x + 10, y0 + 30 + side_h // 2),
                        "no recorded physics state",
                        font=fonts["tiny"],
                        fill=DIM,
                    )

                travelled = math.hypot(
                    row["pose"]["x_mm"] - rows[0]["pose"]["x_mm"],
                    row["pose"]["y_mm"] - rows[0]["pose"]["y_mm"],
                )
                left = float(row["readout_hz"].get(VISUAL_LEFT_READOUT_NAME, 0.0))
                right = float(row["readout_hz"].get(VISUAL_RIGHT_READOUT_NAME, 0.0))
                draw.text(
                    (x0 + 14, y0 + brain_h + 36),
                    f"travelled {travelled:6.2f} mm    DNp L/R {left:5.2f}/{right:5.2f} Hz"
                    f"    {row['command']['state']}",
                    font=fonts["small"],
                    fill=INK,
                )
                draw_trajectory_inset(
                    draw,
                    rows,
                    local_cursor,
                    box=(
                        x0 + side_x,
                        y0 + 30 + side_h + 12,
                        x0 + side_x + side_w,
                        y0 + 30 + side_h + 12 + side_h,
                    ),
                    cue_xy=(
                        float(body_summary["cue_xy_mm"][0]),
                        float(body_summary["cue_xy_mm"][1]),
                    ),
                    cue_radius_mm=float(body_summary["cue_radius_mm"]),
                    fonts=fonts,
                    cue_present=cue_present,
                )

            footer_y = FRAME_HEIGHT - footer
            draw.rectangle((0, footer_y, FRAME_WIDTH, FRAME_HEIGHT), fill=(13, 16, 23))
            draw.text(
                (26, footer_y + 4),
                "The shuffle preserves the edge count, every out-degree and the multiset "
                "of contact counts, changing only which pairs the edges join, so a "
                "difference between it and the exact run cannot be a difference in size.",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (26, footer_y + 18),
                "All four panels use one fixed logarithmic brightness scale, so a dimmer "
                "brain is a quieter brain and not a different exposure. They differ "
                "because the loop is closed: a fly that approaches sees a larger cue, "
                "which drives its lamina harder.",
                font=fonts["tiny"],
                fill=DIM,
            )
            draw.text(
                (26, footer_y + 32),
                f"commit {reference['summary'].get('code_commit', 'unknown')}   "
                f"graph sha256 {reference['summary']['graph']['source_sha256'][:16]}   "
                f"seed {reference['summary']['seed']}   "
                "verdict computed separately by the frozen acceptance contract",
                font=fonts["tiny"],
                fill=DIM,
            )
            writer.append_data(np.asarray(canvas))
    finally:
        writer.close()
        for payload in loaded.values():
            if payload.get("replay") is not None:
                payload["replay"].close()
    return output_path.resolve()


__all__ = [
    "ACTIVITY_EXPOSURE",
    "ACTIVITY_GAIN",
    "BODY_WIDTH",
    "BRAIN_VIEW_LEFT",
    "BRAIN_VIEW_WIDTH",
    "BRAIN_WIDTH",
    "COMPARISON_CAPTIONS",
    "COMPARISON_PANEL_ORDER",
    "FOOTER_HEIGHT",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "GLOW_REFERENCE",
    "HEADER_HEIGHT",
    "LEGEND_HEIGHT",
    "PANEL_HEIGHT",
    "STRUCTURE_REFERENCE_DENSITY",
    "TRACE_HEIGHT",
    "BrainAtlas",
    "BrainProjection",
    "SpikeRecording",
    "TraceChannel",
    "TraceStrip",
    "activity_intensity",
    "build_soma_positions",
    "build_strips",
    "chapter_caption",
    "live_pool_rates",
    "load_trace",
    "opening_card",
    "render_brain",
    "render_comparison",
    "render_recording",
    "verdict_card",
]
