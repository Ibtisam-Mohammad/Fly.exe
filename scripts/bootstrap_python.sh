#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

project_dir=/mnt/i/AI/fly_brain
environment_dir=/srv/flybrain-data/envs/production

if [[ ! -f "$project_dir/uv.lock" ]]; then
  printf '%s\n' "Project lock is missing: $project_dir/uv.lock" >&2
  exit 2
fi
python3.12 -m venv "$environment_dir"
"$environment_dir/bin/python" -m pip install --upgrade "uv==0.12.5"
source "$environment_dir/bin/activate"
export UV_LINK_MODE=copy
cd "$project_dir"
uv sync --active --frozen --extra data --extra body --extra reference --extra render
python -c 'from importlib.metadata import version; import flygym, mujoco; print("FlyGym", version("flygym"), "MuJoCo", version("mujoco"))'
printf '%s\n' "Production Python environment ready: $environment_dir"
