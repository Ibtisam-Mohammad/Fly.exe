# Operations

The long-running commands: getting the data, building the graph, running the preregistered
matrices, and constructing evidence bundles. The [README](../README.md) covers installation
and the demonstrations; this file is for actually operating the project.

Every path below uses `$FLYSIM_DATA_ROOT`. Set it once to a directory with room for the
dataset and the run outputs — the machine these results were produced on uses
`/srv/flybrain-data` inside WSL:

```bash
export FLYSIM_DATA_ROOT=/srv/flybrain-data
```

`--root` defaults to that variable, so it is omitted below wherever the default is wanted.

## 1. Data

MaleCNS v1.0 is the canonical anatomy and is licensed CC-BY. The importer pulls the official
HHMI Janelia/Google Storage artifacts, checksums every download into an immutable lock, and
refuses a changed checksum for an already-locked dataset. No credential is needed for the
bulk tables. neuPrint access, where used, reads `NEUPRINT_APPLICATION_CREDENTIALS`; the value
is never written to a manifest or a log.

```bash
flysim data sync --profile starter
flysim data validate
flysim data import-aggregate
```

Profiles: `metadata` is the initial 55 MB annotation and transmitter audit, `starter` is the
aggregate graph inputs, and `full` — seven checksum-locked flat-connectome tables — is needed
only for contact-level Stage 0 work.

For an unattended full-profile download, launch the Windows-host supervisor rather than a
service inside WSL. The host process keeps `wsl.exe` attached, preserves HTTP partial files,
retries failures, prevents system sleep while active, and exits only after full-profile
checksum validation succeeds:

```powershell
$script = (Resolve-Path scripts\supervise_full_dataset.ps1).Path
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script)
Get-Content artifacts\logs\full-dataset-supervisor.log -Wait
```

Completion is recorded in `artifacts\logs\full-dataset-supervisor.complete`, and a
single-instance mutex prevents two supervisors writing the same partial artifact.

Contact-level Stage 0 work uses bounded, resumable sharding and keeps contact rows off the
GPU:

```bash
flysim data status --profile full --json
flysim data validate --profile full --remote --deep
flysim data import-contacts --resume --memory-limit-gb 3 --threads 2
flysim data audit-contacts --strict
flysim data sync-skeleton-canaries
flysim data audit-body-universes
flysim data audit-structural-references
```

For the long normalization and audit sequence use `scripts/supervise_contact_foundation.ps1`,
then `scripts/supervise_contact_rebuild.ps1`. Progress is JSONL in the matching logs. The
foundation marker covers contact and body-universe audits; the rebuild marker is written only
after both clean layouts, their logical comparisons, evidence-derived V0 construction, and
final bundle validation.

Runtime graph arrays are hashed in their manifest and verified on every load:

```bash
flysim data verify-graph --graph "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/graph"
```

## 2. Benchmarks

```bash
flysim benchmark neural --scales 0.01 0.1 1.0 --graph "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/graph"
```

That is the conservative dry sizing check. Inside the pinned WSL environment, add `--genn`
for a measured CUDA topology-load run. It sets every functional synaptic weight to zero and
therefore makes no neural-dynamics claim:

```bash
flysim benchmark neural --genn --scales 0.01 0.1 1.0 \
    --graph "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/graph" \
    --output "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/genn-benchmark.json"
```

Batched multi-state capacity, before deploying to different hardware:

```bash
flysim benchmark multi-fly --agents 2 4 --duration-s 2 --seed 1 \
    --output "$FLYSIM_DATA_ROOT/evidence/multifly/multifly-capacity.json"
```

On an RTX 3060 the working-tree engineering run fit both two and four full-CNS states in one
shared connectivity allocation but reached only 0.167x and 0.080x biological real time.

## 3. Runs

```bash
flysim run eon-demo --seed 1 --headless                       # no data needed
flysim run eon-malecns --graph "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/graph" \
    --output-root "$FLYSIM_DATA_ROOT/runs" --seed 1 --headless
flysim run full-vnc-walk --graph "$FLYSIM_DATA_ROOT/derived/male-cns-v1.0/graph"
```

`eon-demo` is the semantic engineering storyboard and the neural-bypass control.
`eon-malecns` uses numeric MaleCNS populations, direct PyGeNN, the full traced aggregate
graph, FlyGym, and the checksum-locked Özdil grooming trajectory; add `--render` to produce
the MP4, whose checksum is recorded in the run manifest. Its central sensory relays, direct
DNg97 intent drive, odour-gradient steering and joint controllers are visibly registered
engineering scaffolds, so it is an offline engineering prototype rather than autonomous
connectome-generated behaviour. `full-vnc-walk` remains gated, with no synthetic fallback
hidden behind the scientific command.

## 4. Preregistered matrices

Both refuse to start from a dirty worktree and will not reuse a run recorded against a
different commit. They are resumable.

```bash
python scripts/run_track_a_acceptance.py \
    --output-root "$FLYSIM_DATA_ROOT/runs/track-a-acceptance-v3" \
    --progress "$FLYSIM_DATA_ROOT/runs/track-a-acceptance-v3/primary-progress.json"
python scripts/run_track_a_controls.py \
    --run-root "$FLYSIM_DATA_ROOT/runs/track-a-controls-v3" \
    --primary-progress "$FLYSIM_DATA_ROOT/runs/track-a-acceptance-v3/primary-progress.json" \
    --output "$FLYSIM_DATA_ROOT/evidence/male-cns-v1.0/track-a-controls-v3.json"
```

**Do not edit any tracked file while a matrix is running.** The clean-worktree gate is
evaluated per variant and fires mid-matrix, so a one-line documentation edit forces every
completed variant to be re-run.

Track A's v2 acceptance evidence is withdrawn: it was produced from an uncommitted worktree,
at food positions a discarded round had already used, with a shuffled-connectome control that
could not fail, and with the body settling inside the dust patch. The v3 matrix ran from a
clean commit at three unused positions: 29 of 30 runs complete the sequence and all nine
controls pass, but **0 of 30 clear the grooming-displacement cap**, so Track A is not an
accepted milestone. See [the Track A evidence report](evidence/TRACK_A_EON_MALECNS.md) and
[the repair ADR](adr/ADR-2026-006-evidence-chain-repair.md).

## 5. Evidence bundles

A tier claim requires an immutable evidence bundle. A bundle cannot be created unless every
registered gate for the requested tier explicitly passes and every artifact is hashed:

```bash
flysim evidence build-v0 --output "$FLYSIM_DATA_ROOT/evidence/male-cns-v1.0/V0-evidence-r2.json"
flysim evidence validate PATH
```

`build-v0` is the release path for V0: it derives the gates from the canonical reports and
clean rebuild manifests, re-hashes all seven raw artifacts and the morphology canaries,
recomputes each artifact's upstream MD5 from local bytes, and rejects a clean contact build
that reached the 3 GiB RSS ceiling. The generic `flysim evidence build --tier ...` remains
available for reviewed non-V0 tiers and test fixtures; manually supplied booleans are not
sufficient for V0.

A bundle pins an immutable, V0-scoped snapshot of the `DATA-*` foundation records rather than
the whole mutable assumption register, so unrelated Stage 2 edits cannot invalidate a
structural bundle while any change to a scoped record still does.

**No command prints a tier as a literal.** `flysim run eon-malecns` resolves the project tier
by validating the bundles under `$FLYSIM_DATA_ROOT/evidence/male-cns-v1.0` at run time, and
records `null` when none of them still validate.

## 6. Environment notes

The production environment is Linux with CUDA. On Windows it is reached through WSL2; the
distribution name and user below are this machine's and mean nothing to yours:

```powershell
# scriptsootstrap_wsl.ps1 creates the distribution; substitute your own names.
wsl -d <distro> -u <user> -- bash /mnt/<drive>/<repo>/scripts/bootstrap_python.sh
wsl -d <distro> -u <user> -- bash /mnt/<drive>/<repo>/scripts/install_genn.sh
wsl -d <distro> -u <user> -- env CUDA_PATH=/usr python /mnt/<drive>/<repo>/scripts/smoke_genn.py
```

GeNN is a native source build rather than a registry package, is installed by
`scripts/install_genn.sh`, and is recorded separately from the cross-platform Python lock.

**Rendering does not use the GPU in WSL2.** Every GL backend available there reports
`GL_RENDERER: llvmpipe`: `/dev/dri` does not exist, `/sys/class/drm` holds only `version`,
and `dmesg` carries `misc dxg: dxgk: dxgkio_query_adapter_info: Ioctl failed: -2`, so Mesa's
`d3d12_dri.so` cannot reach the card. NVIDIA ships no Linux EGL or GLX driver into WSL by
design. CUDA compute takes a different path and is unaffected, which is why a
165,122-neuron network runs on the GPU while the rasteriser cannot. Of the software paths,
`glfw` is 1.7x faster than `osmesa` (282 against 487 ms a frame) and is the default. Render
manifests record `gl_renderer` and `hardware_accelerated`, so a render on a machine where the
GPU is reachable says so rather than looking the same.
