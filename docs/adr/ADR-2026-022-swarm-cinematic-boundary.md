# ADR-2026-022: Cohort target-approach cinematic boundary

Status: accepted 2026-09-13  
Decision owner: project owner, by explicit request for a multi-fly CNS-guided video

## Decision

The cinematic may show several simulated flies approaching one shared cue from different
directions, but it must describe the result as **cohort target approach**, not biological
swarming. Each agent receives body-relative retinotopic input, executes an independent neural
state over the complete MaleCNS runtime graph, and exposes only bilateral descending rates to the
engineering locomotor decoder. Target coordinates are unavailable to the decoder.

The cohort shares one MaleCNS donor topology and one sparse connectivity allocation. It does not
represent several reconstructed animals. No fly senses or follows another fly in this release;
pair contact is body physics, not social communication.

## Presentation requirements

- Show the executed neuron and edge counts.
- Label the visual encoder, transmitter-sign LIF, decoder and collision-disc body as `P/E`.
- Display biological time and state that the recording is played back offline.
- Say explicitly that the result is not social swarming and awards no scientific tier.
- Record body paths and neural activity before rendering; rendering may not advance the model.
- Preserve all source and video checksums in manifests.

## Scientific ceiling

The video can demonstrate that several independent states of the current engineering model carry
a visual cue through the full graph and generate target-directed motion. It cannot establish
validated physiology, collective intelligence, pheromone communication, social learning,
cross-animal generalisation, or a validation tier beyond the existing V0 Structural evidence.

## Implementation result

The seed-7 recording completed on 2026-09-13 with eight of eight states reducing their target
distance from approximately 13.0 mm to a final range of 1.24 to 3.38 mm. It used one
25,563,197-edge connectivity allocation and retained independent state for all 165,122 neurons
per agent. The recording manifest rejects any command carrying target coordinates.

The resulting 37.0-second, 1920 by 1080 H.264 video is
`artifacts/showcase/swarm-cns-v1/swarm-cns-hero.mp4`, SHA-256
`cdedfe50c6a6c054cbf1f4f2d853a67b27ea988c7f11de2d9b80a41f1d561ec4`. Rendering reads the
checksum-verified trace and aggregate-activity archive without advancing simulator state. The run
came from the current dirty implementation tree, remains presentation-grade, and awards no tier.

## Presentation revision

The project owner rejected v1's colorful glyph-and-dashboard treatment as childish and pointed to
the restrained style of `2-single-run-exact.mp4`. `swarm-cns-scientific-v2` therefore supersedes
v1 as the recommended cut without changing the recorded simulation. It uses the same large
released-soma CNS view, black instrument panels, amber limitation labels and continuous scientific
traces as DEMO-01.

The arena replaces illustrative glyphs with a real top-down NeuroMechFly default-pose render. This
mesh is a presentation proxy only: recorded x, y and heading place it, while no MuJoCo joint pose
or gait is implied. That limitation is printed above the arena and in the footer on every
simulation frame. The v2 MP4 SHA-256 is
`c23de7ee15d057937c1e1649ec15d959080ae96983bc910740bfe49fca2a9d07`; the proxy PNG SHA-256 is
`3c393884cf2aa5ce1abc43f96b8786427d56c474aa82a0788990021b7b0e29d5`.
