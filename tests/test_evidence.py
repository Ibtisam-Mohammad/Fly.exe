# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

import pytest

from flysim.errors import ValidationError
from flysim.evidence import (
    REQUIRED_GATES,
    ValidationTier,
    build_evidence_bundle,
    validate_evidence_bundle,
)


def test_v0_bundle_requires_every_gate_and_hashed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "structural-report.json"
    artifact.write_text('{"passed": true}\n', encoding="utf-8")
    output = tmp_path / "V0-evidence.json"
    gates = tuple(f"{gate}=true" for gate in REQUIRED_GATES[ValidationTier.V0])

    bundle = build_evidence_bundle(
        ValidationTier.V0,
        output,
        (f"structural-report={artifact}",),
        gates,
    )

    assert bundle.tier is ValidationTier.V0
    assert validate_evidence_bundle(output)["valid"] is True


def test_bundle_rejects_missing_gate_and_detects_artifact_mutation(tmp_path: Path) -> None:
    artifact = tmp_path / "report.json"
    artifact.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "bundle.json"
    with pytest.raises(ValidationError, match="missing gates"):
        build_evidence_bundle(ValidationTier.V0, output, (f"report={artifact}",), ())

    gates = tuple(f"{gate}=true" for gate in REQUIRED_GATES[ValidationTier.V0])
    build_evidence_bundle(ValidationTier.V0, output, (f"report={artifact}",), gates)
    artifact.write_text(json.dumps({"changed": True}), encoding="utf-8")
    result = validate_evidence_bundle(output)
    assert result["valid"] is False
    assert any("artifact byte count changed" in item for item in result["failures"])


def test_higher_tier_requires_valid_immediate_prerequisite(tmp_path: Path) -> None:
    artifact = tmp_path / "cellular-report.json"
    artifact.write_text("{}\n", encoding="utf-8")
    gates = tuple(f"{gate}=true" for gate in REQUIRED_GATES[ValidationTier.V1])
    with pytest.raises(ValidationError, match="prior-tier-evidence"):
        build_evidence_bundle(
            ValidationTier.V1,
            tmp_path / "V1.json",
            (f"cellular-report={artifact}",),
            gates,
        )
