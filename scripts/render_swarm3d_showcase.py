#!/usr/bin/env python
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cut and render the embodied swarm video from a finished recording.

    PYTHONPATH=src python scripts/render_swarm3d_showcase.py \
        --run /srv/flybrain-data/runs/swarm3d-showcase/<stamp>_seed-1/exact \
        --control /srv/flybrain-data/runs/swarm3d-showcase/<stamp>_seed-1/stimulus-absent \
        --out /srv/flybrain-data/artifacts/swarm3d/swarm3d-showcase.mp4 --progress

Reads only finished artifacts. The shot list below is chosen after seeing what the flies
did, which is the only honest order to choose it in, and it cannot change what they did:
the replay path refuses to draw a world that has ever been stepped.

The subjects of the tracking shots are picked by a stated rule rather than by eye -- the fly
that closed the most ground, the pair that ended closest together -- so the camera is not
quietly selecting the run's best moments and calling them the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def choose_gl_backend() -> str:
    """Set MUJOCO_GL before anything imports MuJoCo, unless the caller already has.

    Measured here, idle, on a twelve-fly scene at 1280x760 with shadows: glfw 282 ms a
    frame, glfw forced onto the d3d12 gallium driver 435 ms, osmesa 487 ms. All three
    report `llvmpipe`, so all three are software and the GPU draws none of them -- see
    `report_gl_backend` for how that is checked rather than assumed. glfw is simply the
    fastest of the three available here.
    """
    if os.environ.get("MUJOCO_GL"):
        return os.environ["MUJOCO_GL"]
    os.environ.setdefault("DISPLAY", ":0")
    os.environ["MUJOCO_GL"] = "glfw"
    return "glfw"


def report_gl_backend() -> dict[str, object]:
    """What actually rasterised, read from the live context rather than from the request."""
    try:
        import OpenGL.GL as gl

        renderer = gl.glGetString(gl.GL_RENDERER)
        vendor = gl.glGetString(gl.GL_VENDOR)
        renderer_name = renderer.decode() if renderer else "unknown"
        vendor_name = vendor.decode() if vendor else "unknown"
    except Exception as error:  # pragma: no cover - depends on the live GL context
        return {"backend": os.environ.get("MUJOCO_GL"), "error": repr(error)}
    software = any(
        token in renderer_name.lower() for token in ("llvmpipe", "softpipe", "swrast")
    )
    return {
        "backend": os.environ.get("MUJOCO_GL"),
        "gl_renderer": renderer_name,
        "gl_vendor": vendor_name,
        "hardware_accelerated": not software,
        "note": (
            "Software rasterisation. /dev/dri is absent in this distro and the dxgk "
            "graphics adapter query fails, so Mesa falls back to llvmpipe; CUDA compute "
            "is unaffected and the network still runs on the GPU."
            if software
            else "Hardware rasterisation."
        ),
    }

from collections.abc import Sequence  # noqa: E402

from flysim.swarm3d_replay import (  # noqa: E402
    Shot,
    SwarmTrajectories,
    Timeline,
    clearest_azimuth_offset,
)
from flysim.swarm3d_video import RunRecording, render_showcase  # noqa: E402


def pick_subjects(recording: RunRecording) -> dict[str, str]:
    """Who the camera follows, by a rule written down before the shots are cut.

    `closer` is the fly that reduced its distance to a food object by the most, `traveller`
    the one that walked the furthest path, and `pair` the two flies that ended nearest each
    other. All three are read from the recorded summary.
    """
    per_fly = recording.summary["outcome"]["per_fly"]
    closer = max(per_fly, key=lambda entry: entry["closed_mm"])["fly_id"]
    traveller = max(per_fly, key=lambda entry: entry["displacement_mm"])["fly_id"]
    trajectories = recording.trajectories
    last = trajectories.intervals - 1
    best = (float("inf"), 0, 1)
    count = len(trajectories.fly_ids)
    for a in range(count):
        for b in range(a + 1, count):
            gap = float(
                np.hypot(
                    trajectories.x_mm[last, a] - trajectories.x_mm[last, b],
                    trajectories.y_mm[last, a] - trajectories.y_mm[last, b],
                )
            )
            if gap < best[0]:
                best = (gap, a, b)
    label = dict(zip(trajectories.fly_ids, trajectories.labels, strict=True))
    return {
        "closer": closer,
        "traveller": traveller,
        "closer_label": label[closer],
        "traveller_label": label[traveller],
        "pair_a": trajectories.fly_ids[best[1]],
        "pair_b": trajectories.fly_ids[best[2]],
        "pair_a_label": trajectories.labels[best[1]],
        "pair_b_label": trajectories.labels[best[2]],
        "pair_gap_mm": f"{best[0]:.2f}",
    }


def build_timeline(
    duration_s: float,
    subjects: dict[str, str],
    *,
    with_control: bool,
    trajectories: SwarmTrajectories | None = None,
    obstacles: Sequence[tuple[float, float, float]] = (),
) -> tuple[Timeline, frozenset[str], frozenset[str], dict[str, float]]:
    """The cut. Times are fractions of the recording so the same list fits any duration."""

    def at(fraction: float) -> float:
        return round(duration_s * fraction, 3)

    # Where to stand for the two tracking shots, chosen by measured clearance from
    # the other eleven flies rather than by assuming the space behind an animal is
    # empty. Recorded in the manifest.
    clearance: dict[str, float] = {}

    def offset(name: str, subject: str, lo: float, hi: float, distance: float,
               elevation: float) -> float:
        if trajectories is None:
            return 0.0
        chosen, gap = clearest_azimuth_offset(
            trajectories,
            subject=subject,
            sim_start_s=at(lo),
            sim_end_s=at(hi),
            distance_mm=distance,
            elevation_deg=elevation,
            obstacles=obstacles,
            smoothed=trajectories.smoothed(15),
        )
        clearance[name] = gap
        clearance[f"{name}_offset_deg"] = chosen
        return chosen

    follow_offset = offset("follow", subjects["traveller"], 0.12, 0.46, 13.0, -24.0)
    close_offset = offset("close", subjects["traveller"], 0.20, 0.28, 8.0, -20.0)

    shots: list[Shot] = [
        Shot(
            name="establish",
            caption=(
                "Twelve Drosophila bodies on flat ground. Each one is running its own copy "
                "of the whole released male CNS connectome, and nothing else is steering."
            ),
            video_seconds=11.0,
            sim_start_s=0.0,
            sim_rate=(at(0.22) - 0.0) / 11.0,
            mode="orbit",
            azimuth_start_deg=35.0,
            azimuth_end_deg=98.0,
            elevation_start_deg=-33.0,
            elevation_end_deg=-22.0,
            distance_start_mm=96.0,
            distance_end_mm=78.0,
        ),
        Shot(
            name="sweep",
            caption=(
                "Every fly stood still for the first 1.5 s by construction, so the moment "
                "it starts walking is caused by something. What changed is descending "
                "activity, not a timer."
            ),
            video_seconds=10.0,
            sim_start_s=at(0.18),
            sim_rate=(at(0.42) - at(0.18)) / 10.0,
            mode="orbit",
            azimuth_start_deg=98.0,
            azimuth_end_deg=158.0,
            elevation_start_deg=-20.0,
            elevation_end_deg=-11.0,
            distance_start_mm=78.0,
            distance_end_mm=56.0,
        ),
        Shot(
            name="follow",
            caption=(
                f"{subjects['traveller_label']}. The camera angle is chosen to keep the "
                "other eleven flies and the objects off the line to it. The turns are the "
                "network's: its decoder reads two descending population rates and has no "
                "access to where anything is."
            ),
            video_seconds=11.0,
            sim_start_s=at(0.12),
            sim_rate=(at(0.46) - at(0.12)) / 11.0,
            mode="follow",
            subject=subjects["traveller"],
            azimuth_start_deg=follow_offset - 26.0,
            azimuth_end_deg=follow_offset + 26.0,
            elevation_start_deg=-30.0,
            elevation_end_deg=-18.0,
            distance_start_mm=17.0,
            distance_end_mm=9.0,
        ),
        Shot(
            name="brains",
            caption="Twelve independent neural states over one connectivity allocation.",
            video_seconds=9.0,
            sim_start_s=at(0.28),
            sim_rate=(at(0.60) - at(0.28)) / 9.0,
            mode="orbit",
        ),
        Shot(
            name="pair",
            caption=(
                f"{subjects['pair_a_label']} and {subjects['pair_b_label']}, which "
                f"ended {subjects['pair_gap_mm']} mm apart. Each fly is a visible object "
                "to the others, so the swarm is coupled through vision and not merely "
                "co-located."
            ),
            video_seconds=9.0,
            sim_start_s=at(0.32),
            sim_rate=(at(0.64) - at(0.32)) / 9.0,
            mode="pair",
            subject=subjects["pair_a"],
            partner=subjects["pair_b"],
            azimuth_start_deg=20.0,
            azimuth_end_deg=95.0,
            elevation_start_deg=-21.0,
            elevation_end_deg=-12.0,
            distance_start_mm=28.0,
            distance_end_mm=17.0,
        ),
        Shot(
            name="close",
            caption=(
                f"{(at(0.28) - at(0.20)) / 8.0:.2f} x speed. Six legs in a tripod gait, "
                "adhesion switching per leg, every contact solved by MuJoCo. The gait is "
                "an engineered pattern generator, not the simulated ventral nerve cord."
            ),
            video_seconds=8.0,
            sim_start_s=at(0.20),
            sim_rate=(at(0.28) - at(0.20)) / 8.0,
            mode="follow",
            subject=subjects["traveller"],
            azimuth_start_deg=close_offset - 24.0,
            azimuth_end_deg=close_offset + 24.0,
            elevation_start_deg=-26.0,
            elevation_end_deg=-15.0,
            distance_start_mm=10.5,
            distance_end_mm=6.2,
        ),
    ]
    if with_control:
        shots.append(
            Shot(
                name="control",
                caption=(
                    "The same twelve flies, the same seed, the same bodies, one change: "
                    "the encoder is held at its baseline. Both sides end a little nearer "
                    "the food, because a standing body drifts forward along its own axis "
                    "and every fly was aimed so that food lies inside the encoder's "
                    "mapped field. What the stimulus changes is whether a fly walks at "
                    "all, and whether it arrives at anything."
                ),
                video_seconds=10.0,
                sim_start_s=at(0.30),
                sim_rate=(at(1.0) - at(0.30)) / 10.0,
                mode="orbit",
                azimuth_start_deg=210.0,
                azimuth_end_deg=250.0,
                elevation_start_deg=-30.0,
                elevation_end_deg=-26.0,
                distance_start_mm=86.0,
                distance_end_mm=76.0,
            )
        )
    shots.extend(
        [
            Shot(
                name="arrive",
                caption=(
                    "The encoder has no colour channel and cannot tell food from a pillar. "
                    "What separates them is angular size, so the largest thing in view wins."
                ),
                video_seconds=10.0,
                sim_start_s=at(0.60),
                sim_rate=(at(1.0) - at(0.60)) / 10.0,
                mode="orbit",
                azimuth_start_deg=250.0,
                azimuth_end_deg=310.0,
                elevation_start_deg=-31.0,
                elevation_end_deg=-21.0,
                distance_start_mm=68.0,
                distance_end_mm=42.0,
            ),
            Shot(
                name="overhead",
                caption=(
                    "Where twelve flies ended up after "
                    f"{duration_s:.0f} seconds of simulated behaviour."
                ),
                video_seconds=8.0,
                sim_start_s=at(0.985),
                sim_rate=(at(1.0) - at(0.985)) / 8.0,
                mode="top",
                azimuth_start_deg=270.0,
                azimuth_end_deg=298.0,
                elevation_start_deg=-72.0,
                elevation_end_deg=-56.0,
                distance_start_mm=100.0,
                distance_end_mm=86.0,
            ),
        ]
    )
    return (
        Timeline(tuple(shots)),
        frozenset({"brains"}),
        frozenset({"control"}) if with_control else frozenset(),
        clearance,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--control", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument(
        "--scenario",
        type=Path,
        default=REPO / "configs/scenarios/swarm3d-showcase.json",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--title", default="One connectome. Twelve bodies. Nothing scripted."
    )
    parser.add_argument(
        "--stills",
        default="",
        help="Comma-separated video timestamps in seconds. Writes those frames as "
        "PNGs through the identical composition and writes no video.",
    )
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    backend = choose_gl_backend()
    print(f"gl backend  {backend}")

    recording = RunRecording.load(args.run)
    control = RunRecording.load(args.control, load_spikes_for=()) if args.control else None
    subjects = pick_subjects(recording)
    duration_s = recording.summary["duration_us"] / 1e6
    timeline, grid_shots, compare_shots, clearance = build_timeline(
        duration_s,
        subjects,
        with_control=control is not None,
        trajectories=recording.trajectories,
        obstacles=tuple(
            (obj["x_mm"], obj["y_mm"], obj["radius_mm"])
            for obj in recording.summary["world"]["objects"]
        ),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"recording  {args.run}")
    print(f"control    {args.control}")
    print(f"subjects   {subjects}")
    print(f"clearance  {clearance}")
    print(
        f"timeline   {timeline.video_seconds:.0f} s of shots + cards, "
        f"{timeline.frame_count(args.fps)} shot frames at {args.fps} fps"
    )

    still_times = tuple(
        float(value) for value in args.stills.split(",") if value.strip()
    )
    manifest = render_showcase(
        recording,
        output_path=args.out,
        stills=still_times,
        timeline=timeline,
        positions_path=args.root / "derived/male-cns-v1.0/soma-positions.npz",
        scenario_path=args.scenario,
        fps=args.fps,
        grid_shots=grid_shots,
        compare_shots=compare_shots,
        control=control,
        seed=args.seed,
        title=args.title,
        progress=args.progress,
    )
    manifest["gl"] = report_gl_backend()
    manifest["subjects"] = subjects
    manifest["tracking_shot_clearance_mm"] = clearance
    manifest["tracking_shot_clearance_rule"] = (
        "Each tracking shot's azimuth offset is the one that keeps the other "
        "eleven flies furthest off the line between camera and subject, sampled "
        "across the shot. It chooses a viewpoint on an already recorded "
        "trajectory and can change no behaviour."
    )
    manifest["subject_selection_rule"] = (
        "closer = largest reduction in distance to a food object; traveller = longest "
        "path walked; pair = the two flies nearest each other at the last recorded "
        "interval. All read from the run summary, none chosen by eye."
    )
    manifest_path = args.out.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {args.out}")
    print(f"      {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
