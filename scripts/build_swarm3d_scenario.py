"""Generate the v2 arena: flies scattered and pointed at random, food that dominates.

Three changes from v1, and the reason for each is measured rather than aesthetic.

**Flies are placed and aimed at random.** In v1 they sat on a 26 mm ring all facing inward,
which had a consequence nobody intended: a body commanded to stand drifts *forward along its
own axis*, so the stimulus-absent control drifted inward too and ended 12 of 12 nearer a food
object. A directional start geometry makes the null control look like it succeeded. Random
headings make that drift isotropic, so the control has nothing to gain.

**Food is bigger and the pillars are thin.** In v1 the pillars sat between the flies and the
food, and angular size is radius over distance, so a 1.3 mm pillar at 8.6 mm (8.72 deg) beat
a 2.2 mm food sphere at 20.4 mm (6.19 deg). Nine of twelve flies locked onto a pillar at the
first interval and never left. Food at about 4 mm against pillars at 0.7 mm means a pillar
has to be roughly six times nearer to win, which some fly will still manage -- and should,
because the encoder genuinely cannot tell them apart.

**The pillars stay.** They are real contact geoms and the flies still have to get around
them; what changes is that they stop being the most salient thing in the arena.

Placement is rejection sampling under a fixed seed and the concrete coordinates are written
into the scenario file, so the arena is inspectable, hashable and reproducible rather than
regenerated at load time.
"""

import json
import math
from pathlib import Path

import numpy as np

SEED = 11
FLY_COUNT = 12
ARENA_RADIUS_MM = 30.0
MIN_FLY_GAP_MM = 6.0
MIN_OBJECT_SURFACE_GAP_MM = 5.0
# The widest a food object may sit off a fly's nose at t=0. The encoder's declared
# azimuth span is -10 to +160 degrees per eye; measured on the v1 arena, every fly whose
# target started inside 105 degrees arrived, and five of seven past 116 degrees received
# no descending drive and walked out of the arena.
MAX_START_BEARING_DEG = 100.0

FOOD = [
    ("food-a", 6.5, 5.0, 4.3, (0.88, 0.28, 0.10, 1.0)),
    ("food-b", -8.0, 7.0, 3.6, (0.93, 0.62, 0.09, 1.0)),
    ("food-c", -6.0, -8.0, 4.0, (0.80, 0.18, 0.32, 1.0)),
    ("food-d", 9.0, -6.5, 3.1, (0.95, 0.45, 0.12, 1.0)),
]
PILLAR_COUNT = 6
PILLAR_RADIUS_MM = 0.7
PILLAR_BAND_MM = (11.0, 24.0)


def main() -> None:
    rng = np.random.default_rng(SEED)
    objects = []
    for object_id, x, y, radius, rgba in FOOD:
        objects.append(
            {
                "object_id": object_id,
                "kind": "food",
                "x_mm": x,
                "y_mm": y,
                "radius_mm": radius,
                "height_mm": round(radius * 0.86, 3),
                "rgba": list(rgba),
                "visible_to_vision": True,
            }
        )

    # Pillars: scattered in a band, kept clear of the food and of each other.
    placed: list[tuple[float, float]] = []
    while len(placed) < PILLAR_COUNT:
        angle = rng.uniform(0.0, 2.0 * math.pi)
        radius = rng.uniform(*PILLAR_BAND_MM)
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        if any(math.hypot(x - px, y - py) < 7.0 for px, py in placed):
            continue
        if any(
            math.hypot(x - o["x_mm"], y - o["y_mm"]) < o["radius_mm"] + 5.0
            for o in objects
        ):
            continue
        placed.append((x, y))
    for index, (x, y) in enumerate(placed, start=1):
        objects.append(
            {
                "object_id": f"pillar-{index}",
                "kind": "pillar",
                "x_mm": round(x, 3),
                "y_mm": round(y, 3),
                "radius_mm": PILLAR_RADIUS_MM,
                "height_mm": round(float(rng.uniform(2.2, 3.6)), 3),
                "rgba": [0.44, 0.42, 0.38, 1.0],
                "visible_to_vision": True,
            }
        )

    flies: list[dict] = []
    attempts = 0
    while len(flies) < FLY_COUNT:
        attempts += 1
        if attempts > 100_000:
            raise SystemExit("could not place every fly; loosen the constraints")
        angle = rng.uniform(0.0, 2.0 * math.pi)
        radius = ARENA_RADIUS_MM * math.sqrt(rng.uniform(0.0, 1.0))
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        if any(
            math.hypot(x - f["x_mm"], y - f["y_mm"]) < MIN_FLY_GAP_MM for f in flies
        ):
            continue
        if any(
            math.hypot(x - o["x_mm"], y - o["y_mm"])
            < o["radius_mm"] + MIN_OBJECT_SURFACE_GAP_MM
            for o in objects
        ):
            continue
        # The heading is uniform over the full circle, but rejected if it leaves no food
        # inside the encoder's mapped visual field. That is a domain condition, not a
        # convenience: the retina map is declared over -10 to +160 degrees of azimuth per
        # eye, and measured on the v1 arena a target past that edge produced a descending
        # readout of 0.000 to 0.03 Hz -- no steering signal at all. Five of twelve flies
        # whose target started behind them walked straight out of the arena. Running the
        # model outside its declared domain and filming the result would be reporting a
        # missing mapping as a behaviour.
        heading = None
        for _ in range(400):
            candidate = float(rng.uniform(-math.pi, math.pi))
            for obj in objects:
                if obj["kind"] != "food":
                    continue
                bearing = math.atan2(obj["y_mm"] - y, obj["x_mm"] - x) - candidate
                bearing = math.atan2(math.sin(bearing), math.cos(bearing))
                if abs(math.degrees(bearing)) <= MAX_START_BEARING_DEG:
                    heading = candidate
                    break
            if heading is not None:
                break
        if heading is None:
            continue
        index = len(flies) + 1
        flies.append(
            {
                "fly_id": f"cns-{index:02d}",
                "x_mm": round(x, 3),
                "y_mm": round(y, 3),
                "heading_rad": round(heading, 6),
                "label": f"CNS-{index:02d}",
            }
        )

    demo = json.loads(
        Path("configs/scenarios/demo01-visual-approach.json").read_text(encoding="utf-8")
    )
    old = json.loads(
        Path("configs/scenarios/swarm3d-showcase.json").read_text(encoding="utf-8")
    )
    scenario = {
        "schema_version": "1.0",
        "scenario_id": "swarm3d-showcase-v2",
        "title": "Twelve embodied flies scattered at random among food and pillars",
        "provenance": "E",
        "status": (
            "Engineering demonstration scenario. "
            "Not evidence, not a tier, not a measurement."
        ),
        "assumption_set": old["assumption_set"],
        "last_reviewed": "2026-09-13",
        "supersedes": "swarm3d-showcase-v1",
        "seed": SEED,
        "what_changed_from_v1": {
            "flies_are_placed_and_aimed_at_random": (
                f"Rejection sampling under seed {SEED}: uniform over a "
                f"{ARENA_RADIUS_MM:.0f} mm disc, at least {MIN_FLY_GAP_MM:.0f} mm between "
                f"flies and {MIN_OBJECT_SURFACE_GAP_MM:.0f} mm clear of every object "
                "surface, with heading uniform over the full circle. The concrete "
                "coordinates are written here rather than regenerated at load time. The "
                f"heading is rejected if no food lies within {MAX_START_BEARING_DEG:.0f} "
                "degrees of the fly's nose."
            ),
            "why_the_heading_is_bounded": (
                "The retina map is declared over -10 to +160 degrees of azimuth per eye. "
                "Measured on the first randomised arena, a fly whose target started "
                "beyond that edge received a descending readout of 0.000 to 0.03 Hz -- no "
                "steering signal at all -- and because the drive was tiny rather than "
                "exactly zero it did not fall into the standing controller either, so it "
                "walked in a straight line out of the arena. Five of twelve did. That is "
                "the encoder having no mapping there, not the animal behaving, and "
                "filming it would be reporting a blind spot as a decision."
            ),
            "why_random_headings_matter": (
                "In v1 every fly faced inward. A body commanded to stand drifts forward "
                "along its own axis, so the stimulus-absent control drifted toward the "
                "food as well and ended 12 of 12 nearer it, median +3.99 mm. A "
                "directional start geometry makes the null control look successful. "
                "Isotropic headings remove that confound."
            ),
            "food_is_larger_and_the_pillars_are_thin": (
                "In v1 the pillars sat between the flies and the food. Angular size is "
                "radius over distance, so a 1.3 mm pillar at 8.6 mm subtended 8.72 "
                "degrees against a 2.2 mm food sphere at 20.4 mm at 6.19 degrees, and "
                "nine of twelve flies locked onto a pillar at the first interval and "
                f"never left. Food is now 3.1 to 4.3 mm and pillars {PILLAR_RADIUS_MM} "
                "mm, so a pillar must be about six times nearer to dominate. Some fly "
                "will still manage that, and should: the encoder genuinely cannot tell "
                "the two apart."
            ),
            "the_pillars_are_still_obstacles": (
                "They remain contact geoms in the compiled model and the flies still "
                "have to get around them. What changed is their salience, not their "
                "physics."
            ),
        },
        "what_this_scenario_is": {
            **old["what_this_scenario_is"],
            "why_these_positions": (
                "They are random under a declared seed. Nothing about the layout was "
                "chosen to produce a result, and the generator is "
                "scripts/build_swarm3d_scenario.py."
            ),
        },
        "arena": old["arena"],
        "vision": old["vision"],
        "objects": objects,
        "flies": flies,
        "decoder": demo["decoder"],
    }
    Path("configs/scenarios/swarm3d-showcase.json").write_text(
        json.dumps(scenario, indent=1) + "\n", encoding="utf-8"
    )

    # Report what the geometry implies before anything is run.
    wins = {"food": 0, "pillar": 0}
    for fly in flies:
        best = None
        for obj in objects:
            distance = math.hypot(obj["x_mm"] - fly["x_mm"], obj["y_mm"] - fly["y_mm"])
            angle = math.degrees(math.asin(min(1.0, obj["radius_mm"] / distance)))
            if best is None or angle > best[1]:
                best = (obj["object_id"], angle, distance, obj["kind"])
        wins[best[3]] += 1
        winner = next(o for o in objects if o["object_id"] == best[0])
        bearing = math.degrees(
            math.atan2(winner["y_mm"] - fly["y_mm"], winner["x_mm"] - fly["x_mm"])
            - fly["heading_rad"]
        )
        bearing = (bearing + 180.0) % 360.0 - 180.0
        print(
            f"  {fly['fly_id']}  at ({fly['x_mm']:6.2f},{fly['y_mm']:6.2f}) "
            f"heading {math.degrees(fly['heading_rad']):+7.1f}  -> largest in view "
            f"{best[0]:9s} {best[3]:6s} {best[1]:5.2f} deg at {best[2]:5.1f} mm, "
            f"bearing {bearing:+7.1f}"
        )
    print(f"\n  largest object in view at t=0: food {wins['food']}/12, pillar {wins['pillar']}/12")
    spread = [math.hypot(f["x_mm"], f["y_mm"]) for f in flies]
    print(f"  fly radius from centre: {min(spread):.1f} to {max(spread):.1f} mm")


main()
