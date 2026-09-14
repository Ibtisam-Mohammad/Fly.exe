#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render a recorded MaleCNS cohort in the restrained DEMO-01 instrument style."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flysim.swarm_showcase_scientific import render_swarm_scientific


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--body-proxy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()
    output = render_swarm_scientific(
        args.source_directory,
        root=args.root,
        body_proxy_path=args.body_proxy,
        output_path=args.output,
        fps=args.fps,
    )
    print(json.dumps({"video": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
