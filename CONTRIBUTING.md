# Contributing

Bug reports, reproductions on other hardware, and corrections to the science are all welcome.
Before a code change, read [AGENTS.md](AGENTS.md) — it is the project's source of truth for
scientific interfaces and for what may be claimed.

## Setup and checks

```bash
uv sync --python 3.12 --extra data --extra render --extra web
uv run ruff check .
uv run mypy
uv run pytest
```

That is exactly what CI runs. The body, GPU and connectome extras are not installed there, so
tests needing FlyGym, MuJoCo or GeNN skip; if your change touches them, say in the pull
request what you ran locally and on what hardware.

## The rules that are not style

These exist because the project has been wrong before, and each one is the fix for a specific
failure recorded in [docs/adr/](docs/adr):

* **Every parameter carries a provenance class and an assumption ID.** `M` measured, `P`
  population prior, `F` fitted, `E` engineering scaffold, `I` irrecoverable, registered in
  [`configs/assumptions.json`](configs/assumptions.json). A number with no source does not go
  in.
* **Criteria are registered before they are scored.** Changing a threshold after seeing the
  result is refitting, and a criterion that was failed is never quietly restated.
* **Evidence-grade runs require a clean worktree.** Do not edit tracked files while a matrix
  is running; the gate is evaluated per variant and will invalidate completed work.
* **Reserved data stays unopened.** [`configs/datasets/stage2-reservations-v1.json`](configs/datasets/stage2-reservations-v1.json)
  declares which files, variables and columns are held out. Reading one spends it.
* **Failures stay in the record.** Withdrawn results, discarded arenas and negative outcomes
  are documented rather than deleted; see [docs/STATUS.md](docs/STATUS.md) for what that looks
  like in practice.
* **Datasets are not redistributed.** New external data needs a card in
  [`configs/datasets/`](configs/datasets) with source, checksum and licence, and an entry in
  [docs/REFERENCES.md](docs/REFERENCES.md).

## Licence

Contributions are accepted under the project's licence, GPL-2.0-or-later.
