#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

if [[ "$(uname -r)" != *microsoft* ]]; then
  printf '%s\n' "This installer is pinned and tested for the FlyBrain WSL environment." >&2
  exit 2
fi
if [[ -z "${CUDA_PATH:-}" ]] && command -v nvcc >/dev/null 2>&1; then
  nvcc_path="$(readlink -f "$(command -v nvcc)")"
  export CUDA_PATH="$(dirname "$(dirname "$nvcc_path")")"
fi
if [[ -z "${CUDA_PATH:-}" || ! -d "$CUDA_PATH" ]]; then
  printf '%s\n' "CUDA_PATH does not exist: ${CUDA_PATH:-<unset>}" >&2
  exit 2
fi

environment_python=/srv/flybrain-data/envs/production/bin/python
if [[ ! -x "$environment_python" ]]; then
  printf '%s\n' "Production environment missing; run scripts/bootstrap_python.sh first." >&2
  exit 2
fi
"$environment_python" -m pip install --upgrade pip
"$environment_python" -m pip install "https://github.com/genn-team/genn/archive/refs/tags/5.4.0.zip"
"$environment_python" -c 'import pygenn; print(pygenn.__version__)'
