#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record and render the full-CNS cohort target-approach cinematic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flysim.swarm_showcase import build_swarm_showcase, record_swarm_cns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/srv/flybrain-data"))
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fps", type=int)
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="Record the full-CNS cohort without rendering the cinematic.",
    )
    args = parser.parse_args()
    if args.record_only:
        if args.source_directory is not None:
            parser.error("--record-only cannot be combined with --source-directory")
        source_directory = record_swarm_cns(
            root=args.root,
            scenario_path=args.scenario,
            output_root=args.output_root,
            seed=args.seed,
        )
        print(json.dumps({"source_directory": str(source_directory)}, indent=2))
        return 0
    result = build_swarm_showcase(
        root=args.root,
        scenario_path=args.scenario,
        output_root=args.output_root,
        source_directory=args.source_directory,
        output_path=args.output,
        seed=args.seed,
        fps=args.fps,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
