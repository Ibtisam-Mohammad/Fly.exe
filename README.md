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
flysim run eon-demo --graph /srv/flybrain-data/derived/male-cns-v1.0/graph
flysim run full-vnc-walk --graph /srv/flybrain-data/derived/male-cns-v1.0/graph
```

The command above is the conservative dry sizing check. Inside the pinned WSL environment, add `--genn` for a measured CUDA topology-load run. That benchmark sets every functional synaptic weight to zero and therefore makes no neural-dynamics claim:

```text
flysim benchmark neural --genn --scales 0.01 0.1 1.0 --graph /srv/flybrain-data/derived/male-cns-v1.0/graph --output /srv/flybrain-data/derived/male-cns-v1.0/genn-benchmark.json
```

Use `--profile metadata` for the initial 55 MB annotation/transmitter audit, `starter` for the aggregate graph inputs, and `full` only when contact-level Stage 0 validation begins.

`full-vnc-walk` deliberately refuses to run until the required MaleCNS graph, sensory registry, motor mapping, and production backends pass their readiness gates. There is no synthetic fallback hidden behind that scientific command.

## Data and credentials

MaleCNS v1.0 is the canonical anatomy and is licensed CC-BY. The importer uses official HHMI Janelia/Google Storage artifacts. Bulk downloads are checksummed locally into an immutable lock. neuPrint credentials must be provided through `NEUPRINT_APPLICATION_CREDENTIALS`; they are never written to a manifest or log.

## License

Project code is licensed under GPL-2.0-or-later. Dataset and dependency licenses remain their own; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
