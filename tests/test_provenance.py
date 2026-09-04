# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from flysim.errors import ConfigurationError
from flysim.provenance import AssumptionRegistry, ProvenanceClass, parse_provenance


def test_project_assumptions_are_complete_and_unique() -> None:
    from flysim.config import project_root

    registry = AssumptionRegistry.load(project_root() / "configs" / "assumptions.json")
    registry.require("DATA-01", "NUM-01", "MOTOR-03", "STATE-01")
    assert registry.assumption_set_id == "foundation-v0.1"
    assert registry.sha256


def test_combined_provenance_is_parsed() -> None:
    assert parse_provenance("P/E") == (
        ProvenanceClass.POPULATION_PRIOR,
        ProvenanceClass.ENGINEERING,
    )


def test_invalid_provenance_fails() -> None:
    with pytest.raises(ConfigurationError):
        parse_provenance("unknown")
