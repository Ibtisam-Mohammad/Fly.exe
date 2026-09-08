# SPDX-License-Identifier: GPL-2.0-or-later
"""Configuration discovery and hashing."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def project_root() -> Path:
    configured = os.environ.get("FLYSIM_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "AGENTS.md").exists():
        return candidate
    return Path.cwd().resolve()


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Missing configuration file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON at {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Configuration root must be an object: {path}")
    return raw


def sha256_json(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    scenario_id: str
    track: str
    assumption_set: str
    required_assumptions: tuple[str, ...]
    neural_backend: str
    body_backend: str
    graph_requirement: str
    claim_boundary: str
    scaffolds: tuple[str, ...]
    omissions: tuple[str, ...]
    sha256: str

    @classmethod
    def load(cls, path: Path) -> ScenarioConfig:
        raw = load_json(path)
        return cls(
            scenario_id=str(raw["scenario_id"]),
            track=str(raw["track"]),
            assumption_set=str(raw["assumption_set"]),
            required_assumptions=tuple(raw["required_assumptions"]),
            neural_backend=str(raw["neural_backend"]),
            body_backend=str(raw["body_backend"]),
            graph_requirement=str(raw["graph_requirement"]),
            claim_boundary=str(raw["claim_boundary"]),
            scaffolds=tuple(raw["scaffolds"]),
            omissions=tuple(raw["omissions"]),
            sha256=sha256_json(raw),
        )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write an immutable evidence artifact so a crash cannot leave a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
