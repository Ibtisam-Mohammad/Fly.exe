#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render the DEMO-02 escape control matrix as one synchronised comparison.

    PYTHONPATH=src python scripts/render_demo02_escape.py

Writes two videos. The 2x2 comparison is the result: the fly hops, and it stops hopping
when either the readout or the object is removed. The effector reel is why the exact run
looks the way it does: the wings generate nothing and are what turn the fly over.

Under the v1 contract the verdict is INVALID AS A CAUSAL CLAIM, so this is a diagnostic
reel with the verdict on every frame, not a demonstration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flysim.demo02_render import (  # noqa: E402
    EFFECTOR_PANELS,
    ESCAPE_PANELS,
    PanelReplay,
    PanelSpec,
    caption_for,
    framing_for,
    scaffolds,
)

INK = (232, 232, 238)
DIM = (150, 150, 162)
ALARM = (236, 96, 88)
GOOD = (126, 200, 140)
BAND = (16, 16, 20)


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_panel(
    replay: PanelReplay, spec: PanelSpec, index: int, size: tuple[int, int]
):
    """One panel: the render, plus the numbers that stop it being misread."""
    from PIL import Image, ImageDraw

    # The exact and jump panels need headroom for the arc; the still controls do not.
    distance = 5.6 if spec.variant in {"exact", "jump-only"} else 4.8
    frame = replay.render(index, framing_for(replay, index, distance_mm=distance))
    image = Image.fromarray(frame).resize(size)
    draw = ImageDraw.Draw(image)
    small, tiny = _font(17), _font(14)

    draw.rectangle([(0, 0), (size[0], 48)], fill=BAND)
    draw.text((10, 5), spec.title, font=small, fill=INK)
    draw.text((10, 27), spec.note, font=tiny, fill=DIM)

    roll = replay.roll_deg(index)
    inverted = replay.inverted(index)
    z = replay.z_mm(index)
    state = replay.state(index)
    spikes = replay.giant_fibre_spikes(index)

    lines = [
        (f"roll {roll:5.1f} deg" + ("   INVERTED" if inverted else ""),
         ALARM if inverted else INK),
        (f"thorax z {z:5.3f} mm", INK),
        (f"decoder {state}", GOOD if state == "ACTING" else DIM),
        (f"giant fibre {'|' * min(spikes, 8)}{'' if spikes else '-'}",
         GOOD if spikes else DIM),
    ]
    # Bottom-left, narrow, so it never sits over the fly.
    top = size[1] - 19 * len(lines) - 8
    draw.rectangle([(0, top - 5), (196, size[1])], fill=BAND)
    for number, (text, colour) in enumerate(lines):
        draw.text((8, top + number * 19), text, font=tiny, fill=colour)
    return image


def render_matrix(
    root: Path, panels: tuple[PanelSpec, ...], output: Path, *, columns: int,
    panel_size: tuple[int, int], fps: int, label: str,
) -> dict:
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw

    replays: dict[str, PanelReplay] = {}
    for spec in panels:
        directory = root / f"runs/demo02-escape/{spec.variant}"
        if not (directory / "summary.json").exists():
            raise SystemExit(f"missing run: {directory}")
        replays[spec.variant] = PanelReplay(
            directory, resolution=(panel_size[1], panel_size[0])
        )

    verdict_path = root / "evidence/demo02/escape-acceptance.json"
    verdict = (
        json.loads(verdict_path.read_text(encoding="utf-8"))
        if verdict_path.exists() else {}
    )
    lead = replays[panels[0].variant]
    caption = caption_for(lead.summary, verdict)
    frames = len(lead.qpos)
    rows = (len(panels) + columns - 1) // columns
    width = columns * panel_size[0]
    band = 22 * (len(caption) + 1) + 34
    height = rows * panel_size[1] + band
    small, tiny = _font(16), _font(14)

    # Slow motion across the launch: the object passes 38 degrees, two spikes land, six
    # tarsi leave the ground. Everything before it is a fly standing still.
    launch = next(
        (i for i in range(frames) if lead.giant_fibre_spikes(i) > 0
         and lead.state(i) != "QUIESCENT"),
        frames // 2,
    )
    slow = range(max(0, launch - 6), min(frames, launch + 26))
    order: list[int] = []
    for i in range(frames):
        order.append(i)
        if i in slow:
            order.extend([i] * 5)

    print(f"{label}: {frames} recorded frames -> {len(order)} rendered "
          f"(slow motion {slow.start}-{slow.stop})", flush=True)
    written = 0
    with imageio.get_writer(output, fps=fps, macro_block_size=1) as writer:
        for position, index in enumerate(order):
            canvas = Image.new("RGB", (width, height), BAND)
            for number, spec in enumerate(panels):
                panel = draw_panel(replays[spec.variant], spec, index, panel_size)
                canvas.paste(
                    panel,
                    ((number % columns) * panel_size[0],
                     (number // columns) * panel_size[1]),
                )
            draw = ImageDraw.Draw(canvas)
            base = rows * panel_size[1]
            slowing = index in slow
            draw.text(
                (12, base + 8),
                f"t = {lead.t_us[min(index, len(lead.t_us) - 1)] / 1e6:6.3f} s"
                f"    object angular radius {lead.angular_radius_deg(index):5.2f} deg"
                + ("    [1/6 SPEED]" if slowing else ""),
                font=small, fill=GOOD if slowing else INK,
            )
            for number, text in enumerate(caption):
                draw.text((12, base + 34 + number * 22), text, font=tiny, fill=DIM)
            writer.append_data(np.asarray(canvas))
            written += 1
            if position % 200 == 0:
                print(f"  {position}/{len(order)}", flush=True)

    off, upside = lead.split_airborne_us()
    for replay in replays.values():
        replay.close()
    return {
        "output": str(output),
        "frames": written,
        "fps": fps,
        "panels": [spec.variant for spec in panels],
        "lead_off_ground_us": off,
        "lead_of_which_inverted_us": upside,
        "verdict": verdict.get("verdict"),
        "scaffolds": list(scaffolds()),
        "rendering_is_separate_from_simulation": (
            "The run recorded qpos and wrote no video; this rebuilt the identical plant "
            "and wrote recorded state into it, with the actuator-set digest checked."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--panel", type=int, nargs=2, default=(640, 400))
    args = parser.parse_args()

    out = args.root / "evidence/demo02/video"
    out.mkdir(parents=True, exist_ok=True)
    panel = (int(args.panel[0]), int(args.panel[1]))

    records = [
        render_matrix(
            args.root, ESCAPE_PANELS, out / "escape-control-matrix.mp4",
            columns=2, panel_size=panel, fps=args.fps, label="control matrix",
        ),
        render_matrix(
            args.root, EFFECTOR_PANELS, out / "escape-effectors.mp4",
            columns=3, panel_size=panel, fps=args.fps, label="effector decomposition",
        ),
    ]
    manifest = out / "manifest.json"
    manifest.write_text(
        json.dumps(records, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    for record in records:
        print(f"  {record['output']}  {record['frames']} frames")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
