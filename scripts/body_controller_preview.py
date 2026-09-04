# SPDX-License-Identifier: GPL-2.0-or-later
"""Render the controller-only FlyGym/MuJoCo Phase-0 baseline.

This is deliberately an engineering control. It contains no MaleCNS neural model.
The joint trajectories and hybrid controller are FlyGym demonstration components.
"""

from __future__ import annotations

import argparse
import json
import os
from importlib.metadata import version
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=2.0)
    parser.add_argument("--timestep-s", type=float, default=0.0005)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.duration_s <= 0 or args.timestep_s <= 0:
        raise ValueError("duration and timestep must be positive")

    if args.headless:
        os.environ.setdefault("MUJOCO_GL", "osmesa")

    import mujoco
    from flygym import Simulation
    from flygym.compose import ActuatorType, FlatGroundWorld
    from flygym.utils.math import Rotation3D
    from flygym_demo.complex_terrain.common import (
        apply_locomotion_action,
        make_locomotion_fly,
    )
    from flygym_demo.complex_terrain.hybrid_controller import HybridControllerObservation
    from flygym_demo.complex_terrain.turning_controller import HybridTurningController

    fly_name = "controller_only"
    fly = make_locomotion_fly(name=fly_name, colorize=True)
    fly.add_tracking_camera(name="trackcam")
    world = FlatGroundWorld(half_size=100.0)
    world.add_fly(
        fly,
        spawn_position=np.array([0.0, 0.0, 0.2]),
        spawn_rotation=Rotation3D("quat", (1.0, 0.0, 0.0, 0.0)),
    )
    simulation = Simulation(world, timestep=args.timestep_s)
    simulation.set_renderer(
        f"{fly_name}/trackcam",
        camera_res=(544, 960),
        playback_speed=1.0,
        output_fps=30,
    )
    controller = HybridTurningController(timestep=args.timestep_s)
    controller.reset(seed=args.seed)

    body_order = fly.get_bodysegs_order()
    thorax_index = body_order.index(type(fly).BODY_SEGMENT_CLASS("c_thorax"))
    mujoco.mj_forward(simulation.mj_model, simulation.mj_data)
    initial_thorax = simulation.get_body_positions(fly_name)[thorax_index].copy()
    steps = round(args.duration_s / args.timestep_s)
    for _ in range(steps):
        observation = HybridControllerObservation.from_sim(simulation, fly_name)
        action = controller.step(np.array([1.0, 1.0]), observation)
        apply_locomotion_action(
            simulation,
            fly_name,
            action,
            actuator_type=ActuatorType.POSITION,
        )
        simulation.step()
        simulation.render_as_needed()
    final_thorax = simulation.get_body_positions(fly_name)[thorax_index].copy()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    simulation.renderer.save_video(args.output)

    manifest = {
        "artifact_type": "controller-only-body-preview",
        "claim_boundary": "engineering control; no MaleCNS neural model",
        "provenance": "P/E",
        "flygym_version": version("flygym"),
        "mujoco_version": version("mujoco"),
        "controller": "flygym_demo HybridTurningController",
        "seed": args.seed,
        "duration_s": args.duration_s,
        "timestep_s": args.timestep_s,
        "steps": steps,
        "initial_thorax_mm": initial_thorax.tolist(),
        "final_thorax_mm": final_thorax.tolist(),
        "displacement_mm": (final_thorax - initial_thorax).tolist(),
        "body_mismatch": "published NeuroMechFly female body used as population prior",
        "output": str(args.output.resolve()),
    }
    manifest_path = args.output.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
