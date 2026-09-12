# MaleCNS Virtual Fly

This repository builds a stochastic, MaleCNS-constrained embodied sensorimotor model of a representative adult male *Drosophila*. It is not a recovered copy of the imaged fly, a complete biological emulation, or a digital twin.

The project has two tracks:

- **Track A:** a visibly labelled Eon-like engineering demonstration: seek food, groom after antennal contamination, resume walking, and initiate proboscis extension.
- **Track B:** a scientific closed-loop walking model that preserves the MaleCNS brain–VNC–motor-neuron pathway and tests it against causal controls and held-out data.

Read [AGENTS.md](AGENTS.md) before changing scientific interfaces or claims. Current implementation status and honest limitations are in [docs/STATUS.md](docs/STATUS.md).

## Quick start

The lightweight reference engine runs before FlyGym, CUDA, or MaleCNS data are installed:

```powershell
uv python install 3.12
uv sync --python 3.12 --extra render
uv run flysim run eon-demo --seed 1 --headless
uv run flysim render runs/<run-id>
uv run pytest
```

Build the compact, explicitly engineered Eon-class release matrix from one clean commit:

```text
flysim showcase build --root /srv/flybrain-data
```

This runs three full-graph seeds, four causal interface ablations, two non-gating graph
diagnostics, and then renders the hero run offline. It awards no scientific tier. See
[the showcase release guide](docs/showcase/EON_SHOWCASE.md) for the exact claim boundary.

GeNN is a native source build rather than a registry package and is intentionally installed inside the WSL environment with `scripts/install_genn.sh`; it is recorded separately from the cross-platform Python lock.

For the production Linux environment after `scripts/bootstrap_wsl.ps1` completes:

```powershell
wsl -d FlyBrain -u flybrain -- bash /mnt/i/AI/fly_brain/scripts/bootstrap_python.sh
wsl -d FlyBrain -u flybrain -- bash /mnt/i/AI/fly_brain/scripts/install_genn.sh
wsl -d FlyBrain -u flybrain -- env CUDA_PATH=/usr /srv/flybrain-data/envs/production/bin/python /mnt/i/AI/fly_brain/scripts/smoke_genn.py
```

Generate the explicit controller-only NeuroMechFly/MuJoCo control baseline:

```powershell
wsl -d FlyBrain -u flybrain -- /srv/flybrain-data/envs/production/bin/python /mnt/i/AI/fly_brain/scripts/body_controller_preview.py --output /mnt/i/AI/fly_brain/artifacts/controller-only/body-preview.mp4 --duration-s 2 --seed 1 --headless
```

The generated demonstration is an `E` engineering scaffold. Its run manifest explicitly says that it is not a validated MaleCNS simulation.

## Production workflow

```text
flysim data sync --profile starter --root /srv/flybrain-data
flysim data validate --root /srv/flybrain-data
flysim data import-aggregate --root /srv/flybrain-data
flysim benchmark neural --scales 0.01 0.1 1.0 --graph /srv/flybrain-data/derived/male-cns-v1.0/graph
flysim run eon-demo --seed 1 --headless
flysim run eon-malecns --root /srv/flybrain-data --graph /srv/flybrain-data/derived/male-cns-v1.0/graph --output-root /srv/flybrain-data/runs --seed 1 --headless
flysim run full-vnc-walk --graph /srv/flybrain-data/derived/male-cns-v1.0/graph
```

The command above is the conservative dry sizing check. Inside the pinned WSL environment, add `--genn` for a measured CUDA topology-load run. That benchmark sets every functional synaptic weight to zero and therefore makes no neural-dynamics claim:

```text
flysim benchmark neural --genn --scales 0.01 0.1 1.0 --graph /srv/flybrain-data/derived/male-cns-v1.0/graph --output /srv/flybrain-data/derived/male-cns-v1.0/genn-benchmark.json
```

Use `--profile metadata` for the initial 55 MB annotation/transmitter audit, `starter` for the aggregate graph inputs, and `full` only when contact-level Stage 0 validation begins.

For an unattended full-profile download, launch the Windows-host supervisor rather than a
service inside WSL. The host process keeps `wsl.exe` attached, preserves HTTP partial files,
retries failures, prevents system sleep while active, and exits only after full-profile
checksum validation succeeds:

```powershell
$script = (Resolve-Path scripts\supervise_full_dataset.ps1).Path
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script)
Get-Content artifacts\logs\full-dataset-supervisor.log -Wait
```

Completion is recorded in `artifacts\logs\full-dataset-supervisor.complete`. A single-instance
mutex prevents two supervisors from writing the same partial artifact.

The full profile is now seven checksum-locked flat-connectome tables. Contact-level Stage 0 work
uses bounded, resumable sharding and keeps contact rows off the GPU:

```text
flysim data status --profile full --json --root /srv/flybrain-data
flysim data validate --profile full --remote --deep --root /srv/flybrain-data
flysim data import-contacts --resume --memory-limit-gb 3 --threads 2 --root /srv/flybrain-data
flysim data audit-contacts --strict --root /srv/flybrain-data
flysim data sync-skeleton-canaries --root /srv/flybrain-data
flysim data audit-body-universes --root /srv/flybrain-data
flysim data audit-structural-references --root /srv/flybrain-data
```

For the long normalization and audit sequence, use
`scripts/supervise_contact_foundation.ps1`, followed by
`scripts/supervise_contact_rebuild.ps1`. Progress is JSONL in the matching logs. The foundation
marker covers contact and body-universe audits; the rebuild marker is written only after both clean
layouts, their logical comparisons, evidence-derived V0 construction, and final bundle validation.

Scientific tier claims require an immutable evidence bundle. A bundle cannot be created unless
all registered gates for its requested tier are explicitly passed and every artifact is hashed:

```text
flysim evidence build-v0 --root /srv/flybrain-data --output /srv/flybrain-data/evidence/male-cns-v1.0/V0-evidence-r2.json
flysim evidence build --tier V0 --root /srv/flybrain-data --output /srv/flybrain-data/evidence/male-cns-v1.0/V0-evidence-r2.json
flysim evidence validate PATH
```

`build-v0` is the release path for V0: it derives the gates from the canonical reports and clean
rebuild manifests, re-hashes all seven raw artifacts and morphology canaries, recomputes each
artifact's upstream MD5 from local bytes, and rejects a clean contact build that reached the
3-GiB RSS ceiling. The generic builder remains available for reviewed non-V0 tiers and test
fixtures; manually supplied booleans are not sufficient for V0.

A bundle pins an immutable, V0-scoped snapshot of the `DATA-*` foundation records rather than the
whole mutable assumption register, so unrelated Stage 2 edits cannot invalidate a structural
bundle while any change to a scoped record still does. No command prints a tier as a literal:
`flysim run eon-malecns` resolves the project tier by validating the bundles under
`<root>/evidence/male-cns-v1.0` at run time and records `null` when none of them still validate.

Runtime graph arrays are hashed in their manifest and verified on every load:

```text
flysim data verify-graph --graph /srv/flybrain-data/derived/male-cns-v1.0/graph
```

Track A's full-graph `eon-malecns` gate is now open. It uses numeric MaleCNS populations, direct
PyGeNN, the full traced aggregate graph, FlyGym, and the checksum-locked Ozdil grooming trajectory.
To render the physical run, add `--render`; the final MP4 and checksum are recorded in the run
manifest. Its central sensory relays, direct DNg97 intent drive, odor-gradient steering and joint
controllers are visibly registered engineering scaffolds, so this is an offline engineering
prototype rather than autonomous connectome-generated behavior.

The preregistered Track A matrix and controls are resumable. Both refuse to start from a
dirty worktree and will not reuse a run recorded against a different commit:

```text
python scripts/run_track_a_acceptance.py --root /srv/flybrain-data --output-root /srv/flybrain-data/runs/track-a-acceptance-v3 --progress /srv/flybrain-data/runs/track-a-acceptance-v3/primary-progress.json
python scripts/run_track_a_controls.py --root /srv/flybrain-data --run-root /srv/flybrain-data/runs/track-a-controls-v3 --primary-progress /srv/flybrain-data/runs/track-a-acceptance-v3/primary-progress.json --output /srv/flybrain-data/evidence/male-cns-v1.0/track-a-controls-v3.json
```

The v2 acceptance evidence has been withdrawn. It was produced from an uncommitted worktree,
at food positions a discarded v1 round had already used, with a shuffled-connectome control
that could not fail, and with the body settling inside the dust patch. The v3 matrix ran from a
clean commit at three unused positions: 29 of 30 runs complete the sequence and all nine
controls pass, but **0 of 30 clear the grooming-displacement cap**, so Track A is not an
accepted milestone. The body translates a median 6.26 mm during a 3-second grooming bout under
a zero forward command, and it drifts even while standing, so the defect is stance
station-keeping. Of the nine controls, five are causal ablations, one is a quantitative
degradation control, one is an equivalence check that tests transition identities but not
timing, and two are recorded baselines. See
[the Track A evidence report](docs/evidence/TRACK_A_EON_MALECNS.md) for the v3 results and the
withdrawal record, and [the repair ADR](docs/adr/ADR-2026-006-evidence-chain-repair.md) for
what changed.
`full-vnc-walk` remains gated; there is no synthetic fallback hidden behind that scientific
command. `eon-demo` remains the semantic engineering storyboard and neural-bypass control.

## Data and credentials

MaleCNS v1.0 is the canonical anatomy and is licensed CC-BY. The importer uses official HHMI Janelia/Google Storage artifacts. Bulk downloads are checksummed locally into an immutable lock. neuPrint credentials must be provided through `NEUPRINT_APPLICATION_CREDENTIALS`; they are never written to a manifest or log.

## License

Project code is licensed under GPL-2.0-or-later. Dataset and dependency licenses remain their own; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
