#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render the NeuroMechFly presentation proxy used by the cohort cinematic."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from flysim.config import load_json, project_root
from flysim.demo01_body import Demo01BodyParameters, Demo01VisualBody
from flysim.demo01_replay import CameraFraming


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=768)
    args = parser.parse_args()
    scenario = load_json(project_root() / "configs/scenarios/demo01-visual-approach.json")
    parameters = replace(
        Demo01BodyParameters.from_mapping(scenario["body"]),
        station_keeping_settle_us=0,
    )
    body = Demo01VisualBody(
        parameters,
        seed=1,
        camera_resolution=(args.size, args.size),
    )
    try:
        frame = body.render_frame(
            CameraFraming(
                shot="swarm-presentation-proxy",
                lookat_mm=(0.0, 0.0, 0.7),
                distance_mm=5.2,
                azimuth_deg=0.0,
                elevation_deg=-90.0,
            ),
            cue_visible=False,
        )
    finally:
        body.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rgb = np.asarray(frame, dtype=np.uint8)
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    alpha = np.clip((chroma - 1) * 28, 0, 255).astype(np.uint8)
    alpha_image = Image.fromarray(alpha).filter(ImageFilter.MaxFilter(3))
    alpha_image = alpha_image.filter(ImageFilter.GaussianBlur(0.7))
    rgba = Image.fromarray(rgb).convert("RGBA")
    rgba.putalpha(alpha_image)
    bounds = alpha_image.getbbox()
    if bounds is None:
        raise RuntimeError("The NeuroMechFly proxy chroma mask is empty")
    pad = 12
    left = max(0, bounds[0] - pad)
    top = max(0, bounds[1] - pad)
    right = min(rgba.width, bounds[2] + pad)
    bottom = min(rgba.height, bounds[3] + pad)
    rgba.crop((left, top, right, bottom)).save(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
