# Eon showcase v2 — operator handoff

Status: preregistered and blocked

Scientific tier: V0 Structural, unchanged

Contract: `configs/experiments/eon-showcase-v2.json`

## What changed

v2 is not a repaired serial state machine. It is a clearly edited presentation of three separate
causal experiments. This prevents a failed early transition from making every later ablation look
successful and prevents a strong visual-navigation result from laundering weak grooming or feeding
evidence.

The order is fixed:

1. Run `scripts/search_demo02_feeding_operating_point.py` from a clean commit. If it selects no
   point, stop and publish the neural-route negative.
2. Run the three component matrices from one clean commit. Navigation uses only DEMO-01's visual
   route at the three positions in the v2 contract. Grooming must pass G1--G6. Feeding must use the
   selected MN9 point and pass its required F criteria.
3. Record readout-ablated, stimulus-absent, command-replay and graph-free controller-only controls
   for every component.
4. Write a draft bundle, render the comparison cut, add the video and render-manifest hashes, then
   validate the final bundle.

## Draft bundle shape

Paths are relative to the directory containing `bundle.json`. Every referenced file has a SHA-256.

```json
{
  "experiment_id": "eon-showcase-v2",
  "scientific_validation_tier_awarded": null,
  "components": {
    "navigation": [
      {
        "target_id": "heldout-left",
        "seed": 11,
        "cue_position_mm": [11.4, 7.8],
        "code_commit": "40-hex-commit",
        "verdict": {"path": "evidence/navigation-left.json", "sha256": "..."},
        "controls": {
          "readout-ablated": {"passed": true},
          "stimulus-absent": {"passed": true},
          "command-replay": {"passed": true},
          "controller-only": {"passed": true}
        }
      }
    ],
    "grooming": {"code_commit": "...", "verdict": {"path": "...", "sha256": "..."}, "controls": {}},
    "feeding": {"code_commit": "...", "verdict": {"path": "...", "sha256": "..."}, "controls": {}}
  },
  "presentation_sources": {
    "navigation": {"exact": {"path": "...", "sha256": "..."}, "ablation": {"path": "...", "sha256": "..."}},
    "grooming": {"exact": {"path": "...", "sha256": "..."}, "ablation": {"path": "...", "sha256": "..."}},
    "feeding": {"exact": {"path": "...", "sha256": "..."}, "ablation": {"path": "...", "sha256": "..."}}
  }
}
```

The navigation array contains all three frozen target IDs. The shortened `controls` objects above
are illustrative; the real bundle contains all four entries on every component.

## Commands

```text
flysim showcase render-v2 DRAFT_BUNDLE --output SHOWCASE_MP4
flysim showcase validate-v2 FINAL_BUNDLE
```

The renderer first runs component-only validation. It refuses to render a persuasive video if any
component gate failed. It makes a 66-second 1920-by-1080 exact-versus-ablation cut and never advances
simulator state. The final bundle adds:

```json
{
  "video": {
    "path": "showcase.mp4",
    "sha256": "...",
    "manifest": {"path": "render-manifest.json", "sha256": "..."}
  }
}
```

`validate-v2` is the only command that can report `accepted_as_engineering_showcase: true`. It
checks all artifact hashes, one shared component commit, target coordinates and seeds, target
reach, every required criterion and control, video length/format/layout/labels, and the absence of
a tier claim.
