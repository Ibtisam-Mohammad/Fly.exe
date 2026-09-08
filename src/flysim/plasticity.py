# SPDX-License-Identifier: GPL-2.0-or-later
"""Class-specific short-term depression as a registered, labelled alternative (``ND-06``).

The registry binds a synapse class to a depression-only Tsodyks-Markram rule. The engine
runs it only when a caller builds an :class:`EdgeDepression` from the registry and passes it
in, names the recovery time constant it uses, and that value lies in the registered range.
Nothing here is a validated model of MaleCNS synapses; it exists so the mechanism can be
exercised as a sensitivity alternative instead of being asserted or ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.config import load_json, sha256_json
from flysim.connectome import SparseConnectome
from flysim.errors import ConfigurationError
from flysim.provenance import parse_provenance


@dataclass(frozen=True, slots=True)
class DepressionRule:
    rule_id: str
    source_type_prefix: str
    target_type_pattern: re.Pattern[str]
    same_glomerulus_only: bool
    utilisation: float
    recovery_tau_range_ms: tuple[float, float]
    source: str
    utilisation_range: tuple[float, float] | None = None
    registered_recovery_tau_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "source_type_prefix": self.source_type_prefix,
            "target_type_regex": self.target_type_pattern.pattern,
            "same_glomerulus_only": self.same_glomerulus_only,
            "utilisation": self.utilisation,
            "utilisation_range": (
                list(self.utilisation_range) if self.utilisation_range is not None else None
            ),
            "recovery_tau_range_ms": list(self.recovery_tau_range_ms),
            "registered_recovery_tau_ms": self.registered_recovery_tau_ms,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ShortTermPlasticityRegistry:
    registry_id: str
    registry_sha256: str
    rules: tuple[DepressionRule, ...]

    @classmethod
    def load(cls, path: Path) -> ShortTermPlasticityRegistry:
        payload = load_json(path)
        if payload.get("schema_version") not in {"1.0", "1.1", "1.2"}:
            raise ConfigurationError("Unsupported short-term-plasticity registry schema")
        if "ND-06" not in payload.get("assumption_ids", []):
            raise ConfigurationError("A short-term-plasticity registry must cite ND-06")
        if payload.get("model", {}).get("family") != "tsodyks-markram-depression-only":
            raise ConfigurationError("Only the depression-only Tsodyks-Markram family is supported")
        rules: list[DepressionRule] = []
        for raw in payload["rules"]:
            utilisation = float(raw["utilisation"])
            if not 0.0 < utilisation <= 1.0:
                raise ConfigurationError("Utilisation must lie in (0, 1]")
            parse_provenance(str(raw["utilisation_provenance"]))
            recovery = raw["recovery_tau_ms"]
            low, high = (float(recovery["range"][0]), float(recovery["range"][1]))
            if not 0.0 < low <= high:
                raise ConfigurationError(
                    "Recovery time-constant range must be positive and ordered"
                )
            parse_provenance(str(recovery["provenance"]))
            # A registered value and a registered spread both travel with the rule so a run
            # cannot quote either as tighter than the published fits were.
            registered_tau: float | None = None
            if recovery.get("value") is not None:
                registered_tau = float(recovery["value"])
                if not low <= registered_tau <= high:
                    raise ConfigurationError(
                        f"Registered recovery time constant {registered_tau} ms lies outside "
                        f"its own range [{low}, {high}]"
                    )
            utilisation_range: tuple[float, float] | None = None
            if raw.get("utilisation_range") is not None:
                bounds = raw["utilisation_range"]
                u_low, u_high = (float(bounds[0]), float(bounds[1]))
                if not 0.0 < u_low <= u_high <= 1.0:
                    raise ConfigurationError(
                        "utilisation_range must be ordered and lie in (0, 1]"
                    )
                if not u_low <= utilisation <= u_high:
                    raise ConfigurationError(
                        f"utilisation_range does not contain the registered utilisation "
                        f"of rule {raw['rule_id']!r}"
                    )
                utilisation_range = (u_low, u_high)
            rules.append(
                DepressionRule(
                    rule_id=str(raw["rule_id"]),
                    source_type_prefix=str(raw["source_type_prefix"]),
                    target_type_pattern=re.compile(str(raw["target_type_regex"])),
                    same_glomerulus_only=bool(raw.get("same_glomerulus_only", False)),
                    utilisation=utilisation,
                    recovery_tau_range_ms=(low, high),
                    source=str(raw["source"]),
                    utilisation_range=utilisation_range,
                    registered_recovery_tau_ms=registered_tau,
                )
            )
        if not rules:
            raise ConfigurationError("A short-term-plasticity registry needs at least one rule")
        return cls(
            registry_id=str(payload["registry_id"]),
            registry_sha256=sha256_json(payload),
            rules=tuple(rules),
        )


@dataclass(frozen=True, slots=True)
class EdgeDepression:
    """Per-edge utilisation (zero on static edges) plus the one recovery constant in use."""

    utilisation: np.ndarray
    recovery_tau_ms: float
    depressing_edge_indices: np.ndarray
    summary: dict[str, Any]

    def validate(self, edge_count: int) -> None:
        if self.utilisation.shape != (edge_count,):
            raise ConfigurationError("Edge depression utilisation does not align with the graph")
        if not np.all(np.isfinite(self.utilisation)) or np.any(self.utilisation < 0.0):
            raise ConfigurationError("Edge utilisation must be finite and nonnegative")
        if np.any(self.utilisation > 1.0):
            raise ConfigurationError("Edge utilisation cannot exceed one")
        if not np.isfinite(self.recovery_tau_ms) or self.recovery_tau_ms <= 0.0:
            raise ConfigurationError("Recovery time constant must be positive and finite")


def steady_state_resource(utilisation: float, rate_hz: float, recovery_tau_ms: float) -> float:
    """Resting-normalised release per spike under a regular train, in the mean-field limit."""
    return 1.0 / (1.0 + utilisation * rate_hz * recovery_tau_ms / 1_000.0)


def _glomerulus_of_receptor(label: str, prefix: str) -> str:
    return label[len(prefix) :]


def _glomerulus_of_projection(label: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.match(label)
    if match is None:
        return None
    return label.split("_", 1)[0]


def build_edge_depression(
    graph: SparseConnectome,
    cell_types: tuple[str, ...],
    registry: ShortTermPlasticityRegistry,
    *,
    recovery_tau_ms: float,
) -> EdgeDepression:
    """Bind the registry rules to the edges of ``graph``.

    The caller names the recovery time constant; it must lie inside every matched rule's
    registered range, so an unregistered value cannot be run by accident.
    """
    graph.validate()
    if len(cell_types) != graph.neuron_count:
        raise ConfigurationError("Cell-type labels do not align with graph bodies")
    utilisation = np.zeros(graph.edge_count, dtype=np.float64)
    matched_by_rule: dict[str, int] = {}
    for rule in registry.rules:
        low, high = rule.recovery_tau_range_ms
        if not low <= recovery_tau_ms <= high:
            raise ConfigurationError(
                f"Recovery time constant {recovery_tau_ms} ms lies outside the registered "
                f"range [{low}, {high}] of rule {rule.rule_id!r}"
            )
        # Label matching runs once per neuron rather than twice per edge: the regex is the
        # expensive part and a connectome has orders of magnitude more edges than bodies.
        # Glomeruli become integer codes so the same-glomerulus test is an array comparison.
        codes: dict[str, int] = {}
        source_code = np.full(graph.neuron_count, -1, dtype=np.int64)
        target_code = np.full(graph.neuron_count, -1, dtype=np.int64)
        for index, label in enumerate(cell_types):
            if not label:
                continue
            if label.startswith(rule.source_type_prefix):
                glomerulus = _glomerulus_of_receptor(label, rule.source_type_prefix)
                source_code[index] = codes.setdefault(glomerulus, len(codes))
            projection = _glomerulus_of_projection(label, rule.target_type_pattern)
            if projection is not None:
                target_code[index] = codes.setdefault(projection, len(codes))
        edge_source = source_code[graph.source_indices]
        edge_target = target_code[graph.target_indices]
        selected = (edge_source >= 0) & (edge_target >= 0)
        if rule.same_glomerulus_only:
            selected &= edge_source == edge_target
        utilisation[selected] = rule.utilisation
        matched_by_rule[rule.rule_id] = int(np.count_nonzero(selected))
    depressing = np.flatnonzero(utilisation > 0.0).astype(np.int64)
    summary = {
        "registry_id": registry.registry_id,
        "registry_sha256": registry.registry_sha256,
        "recovery_tau_ms": recovery_tau_ms,
        "depressing_edges": int(depressing.size),
        "static_edges": int(graph.edge_count - depressing.size),
        "matched_edges_by_rule": matched_by_rule,
        "rules": [rule.as_dict() for rule in registry.rules],
        "steady_state_resource_at_50hz": {
            rule.rule_id: steady_state_resource(rule.utilisation, 50.0, recovery_tau_ms)
            for rule in registry.rules
        },
        "validation_status": (
            "executable alternative; no rate-dependent recording is registered to validate it"
        ),
    }
    return EdgeDepression(
        utilisation=utilisation,
        recovery_tau_ms=float(recovery_tau_ms),
        depressing_edge_indices=depressing,
        summary=summary,
    )
